#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#include "io.h"
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

volatile sig_atomic_t cat_cancelled;
uint64_t cat_temp_limit = UINT64_C(192) * 1024 * 1024 * 1024;
char cat_error[512];
static cat_spool spools[8];
static uint64_t temp_bytes;
static int ready;
#ifdef CAT_TESTING
static uint64_t test_written;
static int test_armed;
#endif
int cat_fail(const char *message) {
    snprintf(cat_error, sizeof(cat_error), "%s", message);
    return -1;
}
int cat_syserr(const char *operation) {
    snprintf(cat_error, sizeof(cat_error), "%s: %s", operation, strerror(errno));
    return -1;
}
static void cancel_handler(int signal_number) { cat_cancelled = signal_number; }
int cat_check_cancel(void) { return cat_cancelled ? cat_fail("operation cancelled") : 0; }
int cat_io_init(int install_signals) {
    if (!ready) {
        for (size_t i = 0; i < 8; i++)
            spools[i].fd = -1;
        ready = 1;
    }
    if (!install_signals)
        return 0;
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = cancel_handler;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL))
        return cat_syserr("install signal handler");
    return 0;
}
cat_spool *cat_spool_new(void) {
    if (cat_check_cancel())
        return NULL;
    size_t slot = 0;
    while (slot < 8 && spools[slot].fd >= 0)
        slot++;
    if (slot == 8) {
        cat_fail("temporary descriptor limit exceeded");
        return NULL;
    }
    const char *directory = getenv("TMPDIR");
    if (!directory || !*directory)
        directory = "/tmp";
    size_t length = strlen(directory) + 24;
    char *name = malloc(length);
    if (!name) {
        cat_fail("out of memory");
        return NULL;
    }
    snprintf(name, length, "%s/catc-spool.XXXXXX", directory);
    int fd = mkstemp(name);
    if (fd < 0) {
        free(name);
        cat_syserr("create disk spool");
        return NULL;
    }
    if (unlink(name)) {
        int saved = errno;
        close(fd);
        free(name);
        errno = saved;
        cat_syserr("unlink disk spool");
        return NULL;
    }
    free(name);
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) < 0) {
        close(fd);
        cat_syserr("protect spool descriptor");
        return NULL;
    }
    spools[slot] = (cat_spool){fd, 0};
    return &spools[slot];
}
void cat_spool_close(cat_spool *spool) {
    if (spool && spool->fd >= 0) {
        close(spool->fd);
        temp_bytes -= spool->size;
        spool->fd = -1;
        spool->size = 0;
    }
}
void cat_spools_close(void) {
    for (size_t i = 0; i < 8; i++)
        cat_spool_close(&spools[i]);
}
int cat_seek(int fd, uint64_t offset) {
    if (offset > INT64_MAX)
        return cat_fail("file offset overflow");
    return lseek(fd, (off_t)offset, SEEK_SET) < 0 ? cat_syserr("seek") : 0;
}
int cat_read(int fd, void *data, size_t n) {
    uint8_t *p = data;
    while (n) {
        if (cat_check_cancel())
            return -1;
        ssize_t got = read(fd, p, n);
        if (got < 0 && errno == EINTR)
            continue;
        if (got < 0)
            return cat_syserr("read");
        if (!got)
            return cat_fail("unexpected end of file");
        p += (size_t)got;
        n -= (size_t)got;
    }
    return 0;
}
int cat_write(int fd, const void *data, size_t n) {
    const uint8_t *p = data;
    while (n) {
        if (cat_check_cancel())
            return -1;
        size_t request = n;
#ifdef CAT_TESTING
        const char *fault = getenv("CAT_TEST_WRITE_LIMIT");
        if (fault && (!getenv("CAT_TEST_WRITE_STAGE") || test_armed)) {
            uint64_t limit = strtoull(fault, NULL, 10);
            if (test_written >= limit) {
                errno = ENOSPC;
                return cat_syserr("injected disk-full write");
            }
            if (request > limit - test_written)
                request = (size_t)(limit - test_written);
        }
#endif
        ssize_t got = write(fd, p, request);
        if (got < 0 && errno == EINTR)
            continue;
        if (got <= 0)
            return cat_syserr("write");
        p += (size_t)got;
        n -= (size_t)got;
#ifdef CAT_TESTING
        test_written += (uint64_t)got;
#endif
    }
    return 0;
}
int cat_temp_claim(uint64_t n) {
    if (n > cat_temp_limit - temp_bytes)
        return cat_fail("temporary disk byte budget exceeded");
    temp_bytes += n;
    return 0;
}
void cat_temp_release(uint64_t n) { temp_bytes -= n; }
int cat_spool_write(cat_spool *spool, const void *data, size_t n) {
    off_t position = lseek(spool->fd, 0, SEEK_CUR);
    if (position < 0)
        return cat_syserr("spool position");
    if ((uint64_t)position > UINT64_MAX - n)
        return cat_fail("spool offset overflow");
    uint64_t end = (uint64_t)position + n, extra = end > spool->size ? end - spool->size : 0;
    if (cat_temp_claim(extra))
        return -1;
    /* Reserve growth even if an OS write fails partway; cleanup releases it. */
    if (end > spool->size)
        spool->size = end;
    return cat_write(spool->fd, data, n);
}
int cat_copy(int source, cat_spool *dest, uint64_t n) {
    uint8_t buffer[32768];
    while (n) {
        size_t take = n > sizeof(buffer) ? sizeof(buffer) : (size_t)n;
        if (cat_read(source, buffer, take) || cat_spool_write(dest, buffer, take))
            return -1;
        n -= take;
    }
    return 0;
}
int cat_sync(int fd, int directory) {
#ifdef CAT_TESTING
    if (getenv("CAT_TEST_SYNC_FAIL")) {
        errno = EIO;
        return cat_syserr("injected sync failure");
    }
#endif
    for (;;) {
        if (cat_check_cancel())
            return -1;
        if (!fsync(fd))
            return 0;
        if (errno == EINTR)
            continue;
        /* Some mounted filesystems cannot fsync directory descriptors. */
        if (directory && (errno == EINVAL || errno == ENOTSUP || errno == EOPNOTSUPP)) {
            fputs("catc: warning: filesystem cannot sync directory metadata\n", stderr);
            return 0;
        }
        return cat_syserr("sync");
    }
}
void cat_test_hook(const char *stage) {
#ifdef CAT_TESTING
    const char *write_stage = getenv("CAT_TEST_WRITE_STAGE");
    if (write_stage && !strcmp(write_stage, stage)) {
        test_armed = 1;
        test_written = 0;
    }
    const char *hook = getenv("CAT_TEST_HOOK");
    if (hook && !strcmp(hook, stage))
        raise(SIGSTOP);
#else
    (void)stage;
#endif
}
