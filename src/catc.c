#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#else
#define _GNU_SOURCE
#endif
#include "gzip.h"
#include "io.h"
#include "sha256.h"
#include "transform.h"
#include "xf.h"
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <fnmatch.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <zlib.h>
#ifdef __APPLE__
#include <sys/stdio.h>
#else
#include <sys/syscall.h>
#endif
#include <time.h>
#include <unistd.h>

#define CAT_VERSION "0.2.0-dev"
#define MAX_ENTRIES 4096u
#define MAX_DEPTH 64u
#define MAX_PATH_BYTES 4096u
#define MAX_EXCLUDES 64u
#define MAX_MANIFEST (2u * 1024u * 1024u)
#define HEADER 32u
#define RECORD 64u
static const uint8_t magic[8] = {'C', 'A', 'T', 0, 7, 0, 0, 0};
static const uint8_t magic_v07[8] = {'C', 'A', 'T', 0, 7, 0, 0, 0};
static const uint8_t magic_v06[8] = {'C', 'A', 'T', 0, 6, 0, 0, 0};
static const uint8_t magic_v02[8] = {'C', 'A', 'T', 0, 2, 0, 0, 0};
static const uint8_t magic_v03[8] = {'C', 'A', 'T', 0, 3, 0, 0, 0};
static const uint8_t magic_v04[8] = {'C', 'A', 'T', 0, 4, 0, 0, 0};
static const uint8_t magic_v05[8] = {'C', 'A', 'T', 0, 5, 0, 0, 0};
static const uint8_t magic_v01[8] = {'C', 'A', 'T', 0, 1, 0, 0, 0};
static uint64_t archive_block_max = CAT_BLOCK_MAX;
static uint64_t max_bytes = UINT64_C(64) * 1024 * 1024 * 1024;
static uint64_t max_archive = UINT64_C(64) * 1024 * 1024 * 1024;
static int require_atomic;
static int restore_permissions = 1;
static char *exclude_patterns[MAX_EXCLUDES];
static size_t exclude_count;
static size_t excluded_path_count;
static char *source_root_name;
static size_t source_root_length;
typedef struct {
    char *path;
    unsigned type, mode;
    uint64_t size, payload_size, payload_offset, data_offset;
    uint8_t hash[32];
} Entry;
static Entry entries[MAX_ENTRIES];
static size_t count, manifest_size;
static uint64_t total, tree_blocks, raw_blocks;
static void be(uint8_t *p, uint64_t n, unsigned width) {
    for (unsigned i = 0; i < width; i++)
        p[width - 1 - i] = (uint8_t)(n >> (i * 8));
}
static uint64_t un(const uint8_t *p, unsigned width) {
    uint64_t n = 0;
    for (unsigned i = 0; i < width; i++)
        n = n * 256 + p[i];
    return n;
}
static void clear_entries(void) {
    for (size_t i = 0; i < count; i++)
        free(entries[i].path);
    memset(entries, 0, sizeof(entries));
    count = manifest_size = 0;
    total = tree_blocks = raw_blocks = 0;
    free(source_root_name);
    source_root_name = NULL;
    source_root_length = 0;
}
static int safe_path(const char *p) {
    if (!*p || *p == '/' || strlen(p) >= MAX_PATH_BYTES)
        return 0;
    unsigned depth = 0;
    while (*p) {
        const char *slash = strchr(p, '/');
        size_t n = slash ? (size_t)(slash - p) : strlen(p);
        if (!n || (n == 1 && p[0] == '.') || (n == 2 && p[0] == '.' && p[1] == '.') ||
            ++depth > MAX_DEPTH)
            return 0;
        if (!slash)
            break;
        p = slash + 1;
        if (!*p)
            return 0;
    }
    return 1;
}
static int add_exclude_pattern(const char *pattern) {
    if (!pattern || !*pattern || pattern[0] == '/' || exclude_count == MAX_EXCLUDES ||
        strlen(pattern) >= MAX_PATH_BYTES)
        return -1;
    size_t length = strlen(pattern);
    while (length > 1 && pattern[length - 1] == '/')
        length--;
    if (!length)
        return -1;
    char *copy = strndup(pattern, length);
    if (!copy)
        return -1;
    exclude_patterns[exclude_count++] = copy;
    return 0;
}
static void clear_exclude_patterns(void) {
    for (size_t i = 0; i < exclude_count; i++)
        free(exclude_patterns[i]);
    exclude_count = 0;
}
static int path_is_excluded(const char *path) {
    const char *relative = path;
    if (source_root_name && !strncmp(path, source_root_name, source_root_length) &&
        path[source_root_length] == '/')
        relative = path + source_root_length + 1;
    const char *leaf = strrchr(relative, '/');
    leaf = leaf ? leaf + 1 : relative;
    for (size_t i = 0; i < exclude_count; i++) {
        const char *pattern = exclude_patterns[i];
        if (!fnmatch(pattern, relative, FNM_PATHNAME) ||
            (!strchr(pattern, '/') && !fnmatch(pattern, leaf, FNM_PATHNAME)))
            return 1;
    }
    return 0;
}
static int same_stat(const struct stat *a, const struct stat *b) {
#ifdef __APPLE__
#define MT st_mtimespec
#define CT st_ctimespec
#else
#define MT st_mtim
#define CT st_ctim
#endif
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino && a->st_size == b->st_size &&
           a->st_mode == b->st_mode && a->MT.tv_sec == b->MT.tv_sec &&
           a->MT.tv_nsec == b->MT.tv_nsec && a->CT.tv_sec == b->CT.tv_sec &&
           a->CT.tv_nsec == b->CT.tv_nsec;
}
static int hash_fd(int fd, uint64_t length, uint8_t hash[32]) {
    cat_sha256_ctx ctx;
    cat_sha256_init(&ctx);
    uint8_t buffer[32768];
    while (length) {
        size_t n = length > sizeof(buffer) ? sizeof(buffer) : (size_t)length;
        if (cat_read(fd, buffer, n))
            return -1;
        cat_sha256_update(&ctx, buffer, n);
        length -= n;
    }
    cat_sha256_final(&ctx, hash);
    return 0;
}
static int encode_file(int fd, Entry *e, cat_spool *payload) {
    e->payload_offset = payload->size;
    cat_sha256_ctx ctx;
    cat_sha256_init(&ctx);
    uint8_t bytes[CAT_BLOCK_MAX];
    uint64_t remaining = e->size;
    while (remaining) {
        size_t n = remaining > sizeof(bytes) ? sizeof(bytes) : (size_t)remaining;
        if (cat_read(fd, bytes, n))
            return -1;
        cat_sha256_update(&ctx, bytes, n);
        uint8_t *tree = NULL;
        size_t packed = cat_tree_estimate(bytes, n);
        int compressed = packed < n;
        if (compressed && cat_tree_encode(bytes, n, &tree, &packed))
            return cat_fail("XF tree encode failed");
        if (!compressed)
            packed = n;
        uint8_t frame[9];
        frame[0] = (uint8_t)compressed;
        be(frame + 1, n, 4);
        be(frame + 5, compressed ? packed : n, 4);
        int rc = cat_spool_write(payload, frame, sizeof(frame));
        if (!rc)
            rc = cat_spool_write(payload, compressed ? tree : bytes, compressed ? packed : n);
        free(tree);
        if (rc)
            return -1;
        if (compressed)
            tree_blocks++;
        else
            raw_blocks++;
        if (payload->size > max_archive)
            return cat_fail("archive byte budget exceeded");
        remaining -= n;
    }
    cat_test_hook("source-read");
    if (cat_check_cancel())
        return -1;
    uint8_t extra;
    ssize_t got;
    do {
        got = read(fd, &extra, 1);
    } while (got < 0 && errno == EINTR && !cat_cancelled);
    if (got < 0)
        return cat_syserr("read source tail");
    if (got)
        return cat_fail("source length changed during ingestion");
    cat_sha256_final(&ctx, e->hash);
    e->payload_size = payload->size - e->payload_offset;
    return 0;
}
static int name_cmp(const void *a, const void *b) {
    return strcmp(*(char *const *)a, *(char *const *)b);
}
static int walk(int parent, const char *name, const char *relative, unsigned depth,
                cat_spool *payload) {
    if (cat_check_cancel())
        return -1;
    if (depth > MAX_DEPTH || !safe_path(relative))
        return cat_fail("path/depth limit or unsafe source name");
    if (depth > 1 && path_is_excluded(relative)) {
        excluded_path_count++;
        return 0;
    }
    if (count == MAX_ENTRIES)
        return cat_fail("entry limit exceeded");
    size_t record_bytes = RECORD + strlen(relative);
    if (record_bytes > MAX_MANIFEST - manifest_size)
        return cat_fail("manifest byte budget exceeded");
    struct stat before, after;
    if (fstatat(parent, name, &before, AT_SYMLINK_NOFOLLOW))
        return cat_syserr("stat source");
    if (!S_ISREG(before.st_mode) && !S_ISDIR(before.st_mode))
        return cat_fail("symlinks and special files are rejected");
    int flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK | O_NOCTTY;
    if (S_ISDIR(before.st_mode))
        flags |= O_DIRECTORY;
    int fd = openat(parent, name, flags);
    if (fd < 0)
        return cat_syserr("open source");
    if (fstat(fd, &after) || !same_stat(&before, &after)) {
        close(fd);
        return cat_fail("source changed before ingestion");
    }
    Entry *e = &entries[count++];
    e->path = strdup(relative);
    e->mode = before.st_mode & 0777;
    e->type = S_ISDIR(before.st_mode) ? 1 : 2;
    manifest_size += record_bytes;
    if (!e->path) {
        close(fd);
        return cat_fail("out of memory");
    }
    int rc = 0;
    if (e->type == 2) {
        if (before.st_size < 0 || (uint64_t)before.st_size > max_bytes - total)
            rc = cat_fail("input byte budget exceeded");
        if (!rc) {
            e->size = (uint64_t)before.st_size;
            total += e->size;
            rc = encode_file(fd, e, payload);
        }
    } else {
        int dupfd = dup(fd);
        DIR *dir = dupfd < 0 ? NULL : fdopendir(dupfd);
        if (!dir) {
            if (dupfd >= 0)
                close(dupfd);
            rc = cat_syserr("read directory");
        }
        char **names = NULL;
        size_t nn = 0;
        if (!rc) {
            struct dirent *de;
            errno = 0;
            while ((de = readdir(dir))) {
                if (!strcmp(de->d_name, ".") || !strcmp(de->d_name, ".."))
                    continue;
                size_t child_length = strlen(relative) + strlen(de->d_name) + 2;
                char *child = malloc(child_length);
                if (!child) {
                    rc = cat_fail("out of memory");
                    break;
                }
                snprintf(child, child_length, "%s/%s", relative, de->d_name);
                if (path_is_excluded(child)) {
                    excluded_path_count++;
                    free(child);
                    errno = 0;
                    continue;
                }
                free(child);
                if (nn == MAX_ENTRIES) {
                    rc = cat_fail("directory entry limit exceeded");
                    break;
                }
                char **tmp = realloc(names, (nn + 1) * sizeof(*names));
                if (!tmp) {
                    rc = cat_fail("out of memory");
                    break;
                }
                names = tmp;
                names[nn] = strdup(de->d_name);
                if (!names[nn]) {
                    rc = cat_fail("out of memory");
                    break;
                }
                nn++;
                errno = 0;
            }
            if (!rc && errno)
                rc = cat_syserr("read directory");
            closedir(dir);
            if (nn > 1)
                qsort(names, nn, sizeof(*names), name_cmp);
            for (size_t i = 0; i < nn && !rc; i++) {
                size_t length = strlen(relative) + strlen(names[i]) + 2;
                char *child = malloc(length);
                if (!child) {
                    rc = cat_fail("out of memory");
                    break;
                }
                snprintf(child, length, "%s/%s", relative, names[i]);
                rc = walk(fd, names[i], child, depth + 1, payload);
                free(child);
            }
        }
        for (size_t i = 0; i < nn; i++)
            free(names[i]);
        free(names);
    }
    if (!rc && (fstat(fd, &after) || !same_stat(&before, &after)))
        rc = cat_fail("source changed during ingestion");
    close(fd);
    return rc;
}
static int inventory(const char *const *paths, size_t path_count, cat_spool *payload) {
    for (size_t input = 0; input < path_count; input++) {
        char *source = strdup(paths[input]);
        if (!source)
            return cat_fail("out of memory");
        size_t n = strlen(source);
        while (n > 1 && source[n - 1] == '/')
            source[--n] = 0;
        char *slash = strrchr(source, '/');
        const char *base = slash ? slash + 1 : source;
        char *name = strdup(base);
        int parent = -1, rc = 0;
        if (!name || !safe_path(name) || strchr(name, '/'))
            rc = cat_fail("input needs a safe non-dot basename");
        for (size_t i = 0; !rc && i < count; i++)
            if (!strcmp(entries[i].path, name))
                rc = cat_fail("input basenames collide in archive");
        if (!rc) {
            if (slash) {
                if (slash == source)
                    parent = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
                else {
                    *slash = 0;
                    parent = open(source, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
                }
            } else
                parent = open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
            if (parent < 0)
                rc = cat_syserr("open source parent");
        }
        if (!rc) {
            free(source_root_name);
            source_root_name = strdup(name);
            if (!source_root_name)
                rc = cat_fail("out of memory");
        }
        if (!rc) {
            source_root_length = strlen(source_root_name);
            rc = walk(parent, name, name, 1, payload);
        }
        if (parent >= 0)
            close(parent);
        free(name);
        free(source);
        if (rc)
            return rc;
    }
    return 0;
}
static int hashed_write(cat_spool *output, cat_sha256_ctx *hash, const void *data, size_t n) {
    if (cat_spool_write(output, data, n))
        return -1;
    cat_sha256_update(hash, data, n);
    return 0;
}
static int serialize(cat_spool *payload, cat_spool *archive) {
    uint64_t framing = HEADER + (uint64_t)manifest_size + 32;
    if (framing > max_archive || payload->size > max_archive - framing)
        return cat_fail("archive byte budget exceeded");
    uint8_t header[HEADER] = {0};
    memcpy(header, magic, 8);
    be(header + 8, count, 4);
    be(header + 16, manifest_size, 8);
    be(header + 24, payload->size, 8);
    cat_sha256_ctx hash;
    cat_sha256_init(&hash);
    if (hashed_write(archive, &hash, header, sizeof(header)))
        return -1;
    for (size_t i = 0; i < count; i++) {
        Entry *e = &entries[i];
        size_t length = strlen(e->path);
        uint8_t r[RECORD] = {0};
        be(r, i, 4);
        r[4] = (uint8_t)e->type;
        r[5] = e->type == 2 ? 1 : 0;
        be(r + 6, e->mode, 2);
        be(r + 8, length, 4);
        be(r + 16, e->size, 8);
        be(r + 24, e->payload_size, 8);
        memcpy(r + 32, e->hash, 32);
        if (hashed_write(archive, &hash, r, sizeof(r)) ||
            hashed_write(archive, &hash, e->path, length))
            return -1;
    }
    if (cat_seek(payload->fd, 0))
        return -1;
    uint64_t remaining = payload->size;
    uint8_t buffer[32768];
    while (remaining) {
        size_t n = remaining > sizeof(buffer) ? sizeof(buffer) : (size_t)remaining;
        if (cat_read(payload->fd, buffer, n) || hashed_write(archive, &hash, buffer, n))
            return -1;
        remaining -= n;
    }
    uint8_t digest[32];
    cat_sha256_final(&hash, digest);
    return cat_spool_write(archive, digest, sizeof(digest));
}
static int decode_file(int fd, Entry *e, cat_spool *decoded) {
    cat_sha256_ctx hash;
    cat_sha256_init(&hash);
    if (decoded)
        e->data_offset = decoded->size;
    uint64_t remaining = e->payload_size, original = e->size;
    while (remaining) {
        if (remaining < 9)
            return cat_fail("truncated block header");
        uint8_t frame[9];
        if (cat_read(fd, frame, sizeof(frame)))
            return -1;
        remaining -= 9;
        unsigned codec = frame[0];
        uint64_t length = un(frame + 1, 4), packed = un(frame + 5, 4);
        uint64_t want = original > archive_block_max ? archive_block_max : original;
        if (!length || length != want || packed > remaining || packed > archive_block_max)
            return cat_fail("invalid block bounds");
        uint8_t buffer[CAT_BLOCK_MAX], *bytes = buffer, *allocated = NULL;
        if (cat_read(fd, buffer, (size_t)packed))
            return -1;
        if (codec == 0) {
            if (packed != length)
                return cat_fail("invalid raw block size");
            raw_blocks++;
        } else if (codec == 1) {
            if (packed >= length ||
                cat_tree_decode(buffer, (size_t)packed, (size_t)length, &allocated))
                return cat_fail("malformed binary aggregate tree");
            bytes = allocated;
            tree_blocks++;
        } else
            return cat_fail("unsupported block codec");
        cat_sha256_update(&hash, bytes, (size_t)length);
        int rc = decoded ? cat_spool_write(decoded, bytes, (size_t)length) : 0;
        free(allocated);
        if (rc)
            return -1;
        remaining -= packed;
        original -= length;
    }
    if (original)
        return cat_fail("missing file blocks");
    uint8_t digest[32];
    cat_sha256_final(&hash, digest);
    return memcmp(digest, e->hash, 32) ? cat_fail("file SHA-256 mismatch") : 0;
}
static int parse(cat_spool *archive, cat_spool *decoded) {
    if (archive->size < HEADER + 32 || archive->size > max_archive)
        return cat_fail("invalid archive size");
    if (cat_seek(archive->fd, 0))
        return -1;
    uint8_t digest[32], stored[32];
    if (hash_fd(archive->fd, archive->size - 32, digest) || cat_read(archive->fd, stored, 32))
        return -1;
    if (memcmp(digest, stored, 32))
        return cat_fail("archive SHA-256 mismatch");
    if (cat_seek(archive->fd, 0))
        return -1;
    uint8_t header[HEADER];
    if (cat_read(archive->fd, header, HEADER))
        return -1;
    unsigned version = header[4];
    const uint8_t *known = version == 1   ? magic_v01
                           : version == 2 ? magic_v02
                           : version == 3 ? magic_v03
                           : version == 4 ? magic_v04
                           : version == 5 ? magic_v05
                           : version == 6 ? magic_v06
                           : version == 7 ? magic_v07
                                           : NULL;
    if (!known || memcmp(header, known, 8) || un(header + 12, 4))
        return cat_fail("bad magic/version or unsupported flags");
    static const uint32_t limits[] = {0, CAT_BLOCK_V01_MAX, CAT_BLOCK_V02_MAX, 65536u,
                                      32768u, 131072u, 8192u, 8192u};
    archive_block_max = limits[version];
    uint64_t nc = un(header + 8, 4), ml = un(header + 16, 8), pl = un(header + 24, 8);
    if (!nc || nc > MAX_ENTRIES || ml > MAX_MANIFEST || ml > archive->size - HEADER - 32 ||
        pl != archive->size - HEADER - 32 - ml)
        return cat_fail("invalid archive bounds");
    uint64_t remaining = ml, payload_remaining = pl, payload_offset = HEADER + ml;
    for (size_t i = 0; i < (size_t)nc; i++) {
        if (remaining < RECORD)
            return cat_fail("truncated manifest record");
        uint8_t r[RECORD];
        if (cat_read(archive->fd, r, RECORD))
            return -1;
        remaining -= RECORD;
        uint64_t size = un(r + 16, 8), packed = un(r + 24, 8), length = un(r + 8, 4);
        if (un(r, 4) != i || un(r + 12, 4) || !length || length >= MAX_PATH_BYTES ||
            length > remaining || (r[4] != 1 && r[4] != 2) || r[5] != (r[4] == 2 ? 1 : 0) ||
            un(r + 6, 2) > 0777 || size > max_bytes - total || packed > payload_remaining)
            return cat_fail("invalid manifest fields or input byte budget exceeded");
        Entry *e = &entries[count++];
        e->path = malloc((size_t)length + 1);
        if (!e->path)
            return cat_fail("out of memory");
        if (cat_read(archive->fd, e->path, (size_t)length))
            return -1;
        e->path[length] = 0;
        remaining -= length;
        if (memchr(e->path, 0, (size_t)length) || !safe_path(e->path))
            return cat_fail("unsafe archive path");
        e->type = r[4];
        e->mode = (unsigned)un(r + 6, 2);
        e->size = size;
        e->payload_size = packed;
        e->payload_offset = payload_offset;
        memcpy(e->hash, r + 32, 32);
        if (e->type == 1 && (size || packed || memcmp(e->hash, (uint8_t[32]){0}, 32)))
            return cat_fail("directory carries file data");
        /* Even raw blocks have nine bytes of framing; reject impossible length
         * claims before spending CPU on malformed small archives. */
        uint64_t blocks = size / archive_block_max + (size % archive_block_max != 0);
        if (e->type == 2 && blocks > packed / 10)
            return cat_fail("impossible file/block size claim");
        for (size_t j = 0; j < i; j++)
            if (!strcmp(entries[j].path, e->path))
                return cat_fail("duplicate archive path");
        char *slash = strrchr(e->path, '/');
        if (slash) {
            size_t parent_length = (size_t)(slash - e->path);
            int found = 0;
            for (size_t j = 0; j < i; j++)
                if (entries[j].type == 1 && strlen(entries[j].path) == parent_length &&
                    !memcmp(entries[j].path, e->path, parent_length))
                    found = 1;
            if (!found)
                return cat_fail("missing or non-directory parent");
        } else if (i && version < 7)
            return cat_fail("multiple archive roots");
        total += size;
        payload_remaining -= packed;
        payload_offset += packed;
    }
    if (remaining || payload_remaining)
        return cat_fail("unreferenced manifest/payload bytes");
    for (size_t i = 0; i < count; i++)
        if (entries[i].type == 2) {
            if (cat_seek(archive->fd, entries[i].payload_offset) ||
                decode_file(archive->fd, &entries[i], decoded))
                return -1;
        }
    return 0;
}
static int load_archive(const char *path, cat_spool **out, uint64_t *stored, int *gzipped,
                        cat_spool *decoded) {
    struct stat before, opened, after;
    if (lstat(path, &before))
        return cat_syserr("stat archive");
    if (!S_ISREG(before.st_mode) || before.st_size < 0 || (uint64_t)before.st_size > max_archive)
        return cat_fail("archive input must be a regular file within its byte budget");
    /* Nonblocking is ignored for regular files, but prevents a FIFO swapped
     * into the namespace between lstat/open from hanging before verification. */
    int fd = open(path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK | O_NOCTTY);
    if (fd < 0)
        return cat_syserr("open archive");
    int rc = 0;
    cat_spool *raw = NULL;
    if (fstat(fd, &opened) || !same_stat(&before, &opened))
        rc = cat_fail("archive changed before reading");
    if (!rc) {
        raw = cat_spool_new();
        if (!raw)
            rc = -1;
    }
    if (!rc) {
        *stored = (uint64_t)before.st_size;
        rc = cat_copy(fd, raw, *stored);
    }
    if (!rc && (fstat(fd, &after) || !same_stat(&before, &after)))
        rc = cat_fail("archive changed while reading");
    close(fd);
    if (rc)
        return -1;
    uint8_t prefix[2] = {0};
    if (cat_seek(raw->fd, 0))
        return -1;
    if (raw->size >= 2 && cat_read(raw->fd, prefix, 2))
        return -1;
    *gzipped = prefix[0] == 0x1f && prefix[1] == 0x8b;
    if (*gzipped) {
        cat_spool *plain = cat_spool_new();
        if (!plain)
            return -1;
        if (cat_seek(raw->fd, 0) || cat_gzip_stream(raw->fd, raw->size, plain, max_archive, 1))
            return -1;
        cat_spool_close(raw);
        raw = plain;
    }
    *out = raw;
    return parse(raw, decoded);
}
/* Resolve archive parents only under an already-open extraction root. */
static int parent_fd(int root, const char *path, char **leaf) {
    char *copy = strdup(path);
    if (!copy)
        return -1;
    int fd = dup(root);
    char *part = copy, *slash;
    while (fd >= 0 && (slash = strchr(part, '/'))) {
        *slash = 0;
        int next = openat(fd, part, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        close(fd);
        fd = next;
        part = slash + 1;
    }
    *leaf = strdup(part);
    free(copy);
    if (!*leaf) {
        if (fd >= 0)
            close(fd);
        return -1;
    }
    return fd;
}
static int unsupported(int reason) {
    return reason == ENOTSUP || reason == EOPNOTSUPP || reason == ENOSYS || reason == EINVAL;
}
static int exclusive_rename(const char *source, const char *destination, int directory) {
#ifdef CAT_TESTING
    if (getenv("CAT_TEST_PORTABLE")) {
        errno = ENOTSUP;
        return -1;
    }
#endif
#ifdef __APPLE__
    (void)directory;
    return renamex_np(source, destination, RENAME_EXCL);
#else
#ifdef SYS_renameat2
    if (!syscall(SYS_renameat2, AT_FDCWD, source, AT_FDCWD, destination, 1))
        return 0;
    if (!unsupported(errno))
        return -1;
#endif
    if (!directory) {
        if (!link(source, destination)) {
            unlink(source);
            return 0;
        }
        return -1;
    }
    errno = ENOTSUP;
    return -1;
#endif
}
static int sync_parent(const char *path) {
    char *copy = strdup(path);
    if (!copy)
        return cat_fail("out of memory after publication");
    char *slash = strrchr(copy, '/');
    const char *parent = ".";
    if (slash) {
        if (slash == copy)
            parent = "/";
        else {
            *slash = 0;
            parent = copy;
        }
    }
    int fd = open(parent, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    free(copy);
    if (fd < 0)
        return cat_syserr("output published but cannot open parent for sync");
    int rc = cat_sync(fd, 1);
    close(fd);
    return rc;
}
static int owned_path(const char *path, int fd) {
    struct stat a, b;
    return !fstat(fd, &a) && !lstat(path, &b) && a.st_dev == b.st_dev && a.st_ino == b.st_ino;
}
/* On filesystems lacking no-replace rename, exclusive create still prevents
 * clobbering other files. Publish magic only after the complete body is synced.
 * SIGKILL/power loss can leave an invalid output: --require-atomic disallows it. */
static int portable_publish_file(const char *source, const char *destination) {
    int input = open(source, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (input < 0)
        return cat_syserr("open staged archive");
    int output = open(destination, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (output < 0) {
        close(input);
        return cat_syserr("reserve archive destination without overwrite");
    }
    cat_test_hook("destination-reserved");
    struct stat st;
    int rc = 0;
    uint8_t prefix[8];
    if (fstat(input, &st) || st.st_size < 8)
        rc = cat_fail("invalid staged archive");
    if (!rc && (cat_read(input, prefix, 8) || cat_write(output, (uint8_t[8]){0}, 8)))
        rc = -1;
    uint64_t left = !rc ? (uint64_t)st.st_size - 8 : 0;
    uint8_t buffer[32768];
    while (left && !rc) {
        size_t n = left > sizeof(buffer) ? sizeof(buffer) : (size_t)left;
        if (cat_read(input, buffer, n) || cat_write(output, buffer, n))
            rc = -1;
        left -= n;
    }
    if (!rc)
        rc = cat_sync(output, 0);
    if (!rc && (cat_seek(output, 0) || cat_write(output, prefix, 8) || cat_sync(output, 0)))
        rc = -1;
    if (rc && owned_path(destination, output))
        unlink(destination);
    if (close(output) && !rc)
        rc = cat_syserr("close published archive");
    close(input);
    return rc;
}
static int publish(const char *stage, const char *destination, int directory, int *committed) {
    cat_test_hook("publish-ready");
    if (cat_check_cancel())
        return -1;
    if (exclusive_rename(stage, destination, directory)) {
        int reason = errno;
        if (!unsupported(reason) || require_atomic) {
            errno = reason;
            return cat_syserr(require_atomic ? "atomic publication required"
                                             : "publish without overwrite");
        }
        if (directory) {
            if (mkdir(destination, 0700))
                return cat_syserr("reserve extraction destination without overwrite");
            int fd = open(destination, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
            if (fd < 0) {
                rmdir(destination);
                return cat_syserr("open extraction reservation");
            }
            cat_test_hook("destination-reserved");
            int rc = cat_check_cancel();
            if (!rc && !owned_path(destination, fd))
                rc = cat_fail("extraction destination changed during publication");
            if (!rc && rename(stage, destination))
                rc = cat_syserr("publish extraction");
            if (rc && owned_path(destination, fd))
                rmdir(destination);
            close(fd);
            if (rc)
                return -1;
        } else if (portable_publish_file(stage, destination))
            return -1;
    }
    *committed = 1;
    cat_test_hook("published");
    int sync_result = sync_parent(destination);
    if (sync_result) {
        char previous[sizeof(cat_error)];
        memcpy(previous, cat_error, sizeof(previous));
        snprintf(cat_error, sizeof(cat_error),
                 "output published, but parent sync did not complete: %.400s", previous);
    }
    return sync_result;
}
static int save_archive(const char *destination, cat_spool *archive) {
    size_t length = strlen(destination) + 16;
    char *name = malloc(length);
    if (!name)
        return cat_fail("out of memory");
    snprintf(name, length, "%s.tmp.XXXXXX", destination);
    int fd = mkstemp(name);
    if (fd < 0) {
        free(name);
        return cat_syserr("create temporary archive");
    }
    cat_test_hook("archive-copy");
    cat_spool staging = {fd, 0};
    int rc = cat_seek(archive->fd, 0);
    if (!rc)
        rc = cat_copy(archive->fd, &staging, archive->size);
    if (!rc)
        rc = cat_sync(fd, 0);
    if (!rc)
        cat_test_hook("archive-staged");
    cat_spool_close(&staging);
    int committed = 0;
    if (!rc)
        rc = publish(name, destination, 0, &committed);
    unlink(name);
    free(name);
    return rc;
}
static void cleanup_tree(int root, size_t made) {
    /* Cleanup must run after cancellation, without cancellation-aware I/O. */
    for (size_t i = 0; i < made; i++)
        if (entries[i].type == 1) {
            char *leaf = NULL;
            int parent = parent_fd(root, entries[i].path, &leaf);
            if (parent >= 0) {
                fchmodat(parent, leaf, 0700, 0);
                close(parent);
            }
            free(leaf);
        }
    for (size_t i = made; i-- > 0;) {
        char *leaf = NULL;
        int parent = parent_fd(root, entries[i].path, &leaf);
        if (parent >= 0) {
            unlinkat(parent, leaf, entries[i].type == 1 ? AT_REMOVEDIR : 0);
            close(parent);
        }
        free(leaf);
    }
}
static int apply_mode(int fd, unsigned mode) {
    if (!restore_permissions)
        return 0;
#ifdef CAT_TESTING
    if (getenv("CAT_TEST_CHMOD_FAIL")) {
        errno = EPERM;
        return cat_syserr("injected permission failure");
    }
#endif
    if (fchmod(fd, (mode_t)mode))
        return cat_syserr("restore permissions");
    struct stat current;
    if (fstat(fd, &current))
        return cat_syserr("verify restored permissions");
    if ((current.st_mode & 0777) != mode)
        return cat_fail("target filesystem cannot preserve permission bits (use --no-permissions "
                        "intentionally)");
    return 0;
}
static int extract(const char *destination, cat_spool *decoded) {
    struct stat st;
    if (!lstat(destination, &st))
        return cat_fail("extraction destination already exists");
    if (errno != ENOENT)
        return cat_syserr("check extraction destination");
    if (cat_temp_claim(total))
        return -1;
    size_t length = strlen(destination) + 16;
    char *stage = malloc(length);
    if (!stage) {
        cat_temp_release(total);
        return cat_fail("out of memory");
    }
    snprintf(stage, length, "%s.tmp.XXXXXX", destination);
    if (!mkdtemp(stage)) {
        free(stage);
        cat_temp_release(total);
        return cat_syserr("create extraction staging directory");
    }
    int root = open(stage, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (root < 0) {
        rmdir(stage);
        free(stage);
        cat_temp_release(total);
        return cat_syserr("open extraction staging directory");
    }
    cat_test_hook("extraction-copy");
    int rc = 0, committed = 0;
    size_t made = 0;
    for (size_t i = 0; i < count && !rc; i++) {
        if (cat_check_cancel()) {
            rc = -1;
            break;
        }
        Entry *e = &entries[i];
        char *leaf = NULL;
        int parent = parent_fd(root, e->path, &leaf);
        if (parent < 0) {
            free(leaf);
            rc = cat_syserr("open extraction parent");
            break;
        }
        if (e->type == 1) {
            if (mkdirat(parent, leaf, 0700))
                rc = cat_syserr("create archived directory");
            else
                made = i + 1;
        } else {
            int fd =
                openat(parent, leaf, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
            if (fd < 0)
                rc = cat_syserr("create restored file");
            else {
                made = i + 1;
                rc = cat_seek(decoded->fd, e->data_offset);
                uint64_t remaining = e->size;
                uint8_t buffer[32768];
                cat_sha256_ctx hash;
                cat_sha256_init(&hash);
                while (remaining && !rc) {
                    size_t n = remaining > sizeof(buffer) ? sizeof(buffer) : (size_t)remaining;
                    if (cat_read(decoded->fd, buffer, n) || cat_write(fd, buffer, n))
                        rc = -1;
                    else
                        cat_sha256_update(&hash, buffer, n);
                    remaining -= n;
                }
                uint8_t digest[32];
                cat_sha256_final(&hash, digest);
                if (!rc && memcmp(digest, e->hash, 32))
                    rc = cat_fail("temporary decoded content changed");
                if (!rc)
                    rc = apply_mode(fd, e->mode);
                if (!rc)
                    rc = cat_sync(fd, 0);
                if (close(fd) && !rc)
                    rc = cat_syserr("close restored file");
            }
        }
        close(parent);
        free(leaf);
    }
    cat_test_hook("extraction-staged");
    if (!rc)
        for (size_t i = count; i-- > 0;)
            if (entries[i].type == 1) {
                char *leaf = NULL;
                int parent = parent_fd(root, entries[i].path, &leaf);
                int fd = parent < 0 ? -1
                                    : openat(parent, leaf,
                                             O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
                if (fd < 0)
                    rc = cat_syserr("open restored directory");
                else
                    rc = apply_mode(fd, entries[i].mode);
                if (!rc)
                    rc = cat_sync(fd, 1);
                if (fd >= 0)
                    close(fd);
                if (parent >= 0)
                    close(parent);
                free(leaf);
                if (rc)
                    break;
            }
    if (!rc)
        rc = cat_sync(root, 1);
    if (!rc)
        rc = publish(stage, destination, 1, &committed);
    if (!committed)
        cleanup_tree(root, made);
    close(root);
    if (!committed)
        rmdir(stage);
    free(stage);
    cat_temp_release(total);
    return rc;
}
/* An archive path may contain terminal controls or invalid UTF-8. Escape raw
 * bytes on inspect so untrusted filenames cannot emit terminal commands. */
static void print_path(const char *path) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)path; *p; p++) {
        if (*p == '\\' || *p == '"')
            printf("\\%c", *p);
        else if (*p < 32 || *p >= 127)
            printf("\\x%02x", *p);
        else
            putchar(*p);
    }
    putchar('"');
}
static void usage(void) {
    puts("catc " CAT_VERSION " (CAT format v0.7)\n"
         "Usage: catc -e INPUT... -o OUTPUT.cat\n"
         "       catc -eg INPUT... --output OUTPUT.cat.gz\n"
         "       catc -e INPUT OUTPUT.cat  (single-input compatibility form)\n"
         "       catc -d INPUT.cat NEW_OUTPUT_DIR\n"
         "       catc -i INPUT.cat\n"
         "       catc -v INPUT.cat\n\n"
         "  -e, --encode, encode     Encode a file or directory\n"
         "  -d, --decode, decode     Extract (auto-detects gzip)\n"
         "  -i, --inspect, inspect   List and validate archive entries\n"
         "  -v, --verify, verify     Validate archive contents\n"
         "  -g, --gzip               Gzip the complete CAT archive (encode only)\n"
         "  -o, --output FILE        Name the output archive (encode only)\n"
         "  -x, --exclude PATTERN    Exclude matching relative paths (repeatable)\n"
         "  -h, --help               Show this help\n"
         "      --version            Show tool and format version\n"
         "      --max-bytes N        Original byte budget (default 64 GiB)\n"
         "      --max-archive-bytes N Stored/inflated archive budget (default 64 GiB)\n"
         "      --max-temp-bytes N   Temporary disk budget (default 192 GiB)\n"
         "      --require-atomic     Refuse filesystems without atomic no-replace publication\n"
         "      --no-permissions     Restore content without original mode bits (decode only)\n"
         "  Encode accepts multiple files/directories; duplicate basenames are rejected.\n"
         "  Short flags may be grouped: -eg or -ge. -- ends options.\n"
         "Limits: 4096 entries, depth 64, 2 MiB manifest; symlinks/special files rejected.\n"
         "TMPDIR selects scratch storage. Budgets are decimal byte counts, not preallocations.");
}
static int action(const char *arg) {
    if (!strcmp(arg, "encode") || !strcmp(arg, "--encode"))
        return 1;
    if (!strcmp(arg, "decode") || !strcmp(arg, "--decode"))
        return 2;
    if (!strcmp(arg, "inspect") || !strcmp(arg, "--inspect"))
        return 3;
    if (!strcmp(arg, "verify") || !strcmp(arg, "--verify"))
        return 4;
    return 0;
}
static int budget(const char *text, uint64_t *value) {
    if (!*text)
        return -1;
    uint64_t n = 0;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        if (*p < '0' || *p > '9' || n > ((uint64_t)INT64_MAX - (*p - '0')) / 10)
            return -1;
        n = n * 10 + (*p - '0');
    }
    if (!n)
        return -1;
    *value = n;
    return 0;
}
#ifndef CAT_FUZZING
int main(int argc, char **argv) {
    int operation = 0, gzip_option = 0, end_options = 0, npaths = 0;
    const char *paths[argc > 0 ? argc : 1];
    const char *output_path = NULL;
    for (int i = 1; i < argc; i++) {
        const char *arg = argv[i];
        if (!end_options && (!strcmp(arg, "--help") || !strcmp(arg, "-h"))) {
            usage();
            return 0;
        }
        if (!end_options && !strcmp(arg, "--version")) {
            printf("catc %s format=0.7 xf=%s zlib=%s\n", CAT_VERSION, xf_version(), zlibVersion());
            return 0;
        }
        if (!end_options && !strcmp(arg, "--")) {
            end_options = 1;
            continue;
        }
        if (!end_options && !strncmp(arg, "--output=", 9)) {
            if (output_path || !arg[9]) {
                usage();
                return 2;
            }
            output_path = arg + 9;
            continue;
        }
        if (!end_options && !strcmp(arg, "--output")) {
            if (output_path || ++i == argc) {
                usage();
                return 2;
            }
            output_path = argv[i];
            continue;
        }
        if (!end_options && !strcmp(arg, "--no-permissions")) {
            restore_permissions = 0;
            continue;
        }
        if (!end_options && !strcmp(arg, "--require-atomic")) {
            require_atomic = 1;
            continue;
        }
        if (!end_options && !strncmp(arg, "--exclude=", 10)) {
            if (add_exclude_pattern(arg + 10)) {
                usage();
                return 2;
            }
            continue;
        }
        if (!end_options && !strcmp(arg, "--exclude")) {
            if (++i == argc || add_exclude_pattern(argv[i])) {
                usage();
                return 2;
            }
            continue;
        }
        if (!end_options && (!strcmp(arg, "--max-bytes") || !strcmp(arg, "--max-archive-bytes") ||
                             !strcmp(arg, "--max-temp-bytes"))) {
            uint64_t *target = !strcmp(arg, "--max-bytes")           ? &max_bytes
                               : !strcmp(arg, "--max-archive-bytes") ? &max_archive
                                                                     : &cat_temp_limit;
            if (++i == argc || budget(argv[i], target)) {
                usage();
                return 2;
            }
            continue;
        }
        if (!end_options && arg[0] == '-' && arg[1] && arg[1] != '-') {
            for (size_t j = 1; arg[j]; j++) {
                if (arg[j] == 'h') {
                    usage();
                    return 0;
                }
                if (arg[j] == 'g') {
                    gzip_option = 1;
                    continue;
                }
                if (arg[j] == 'x') {
                    if (++i == argc || add_exclude_pattern(argv[i])) {
                        usage();
                        return 2;
                    }
                    continue;
                }
                if (arg[j] == 'o') {
                    if (output_path || ++i == argc) {
                        usage();
                        return 2;
                    }
                    output_path = argv[i];
                    continue;
                }
                int chosen = arg[j] == 'e'   ? 1
                             : arg[j] == 'd' ? 2
                             : arg[j] == 'i' ? 3
                             : arg[j] == 'v' ? 4
                                             : 0;
                if (!chosen || operation) {
                    usage();
                    return 2;
                }
                operation = chosen;
            }
            continue;
        }
        if (!end_options && !strcmp(arg, "--gzip")) {
            gzip_option = 1;
            continue;
        }
        int chosen = !end_options ? action(arg) : 0;
        if (chosen && !operation) {
            operation = chosen;
            continue;
        }
        if (!end_options && arg[0] == '-' && arg[1]) {
            usage();
            return 2;
        }
        paths[npaths++] = arg;
    }
    int encoding = operation == 1, decoding = operation == 2, inspect = operation == 3;
    /* Keep the former single-input encode form working. Multiple inputs always
     * require -o/--output so the archive name cannot be mistaken for an input. */
    if (encoding && !output_path && npaths == 2) {
        output_path = paths[1];
        npaths = 1;
    }
    if (!operation || (encoding ? (npaths < 1 || !output_path)
                                : decoding ? (npaths != 2 || output_path)
                                           : (npaths != 1 || output_path)) ||
        (gzip_option && !encoding) || (!restore_permissions && !decoding) ||
        (exclude_count && !encoding)) {
        usage();
        return 2;
    }
    struct timespec start, end;
    clock_gettime(CLOCK_MONOTONIC, &start);
    int rc = cat_io_init(1);
    if (!rc)
        rc = cat_transform_init();
    uint64_t stored_size = 0, cat_size = 0;
    int gzipped = gzip_option;
    cat_spool *archive = NULL, *decoded = NULL;
    if (!rc && encoding) {
        cat_spool *payload = cat_spool_new();
        archive = cat_spool_new();
        if (!payload || !archive)
            rc = -1;
        if (!rc)
            rc = inventory(paths, (size_t)npaths, payload);
        if (!rc)
            rc = serialize(payload, archive);
        cat_spool_close(payload);
        uint64_t saved_trees = tree_blocks, saved_raw = raw_blocks;
        if (!rc) {
            clear_entries();
            rc = parse(archive, NULL);
        }
        if (!rc) {
            tree_blocks = saved_trees;
            raw_blocks = saved_raw;
            cat_size = archive->size;
        }
        if (!rc && gzip_option) {
            cat_spool *packed = cat_spool_new();
            if (!packed)
                rc = -1;
            if (!rc && (cat_seek(archive->fd, 0) ||
                        cat_gzip_stream(archive->fd, archive->size, packed, max_archive, 0)))
                rc = -1;
            if (!rc) {
                cat_spool_close(archive);
                archive = packed;
            }
        }
        if (!rc) {
            stored_size = archive->size;
            rc = save_archive(output_path, archive);
        }
    } else if (!rc) {
        if (decoding) {
            decoded = cat_spool_new();
            if (!decoded)
                rc = -1;
        }
        if (!rc)
            rc = load_archive(paths[0], &archive, &stored_size, &gzipped, decoded);
        if (archive)
            cat_size = archive->size;
        if (!rc && decoding)
            rc = extract(paths[1], decoded);
        if (!rc && inspect)
            for (size_t i = 0; i < count; i++) {
                printf("%zu\t%s\t%" PRIu64 "\t%04o\t", i, entries[i].type == 1 ? "dir" : "file",
                       entries[i].size, entries[i].mode);
                print_path(entries[i].path);
                putchar('\n');
            }
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    if (rc)
        fprintf(stderr, "catc: %s\n", cat_error[0] ? cat_error : "operation failed");
    else {
        double seconds =
            (double)(end.tv_sec - start.tv_sec) + (double)(end.tv_nsec - start.tv_nsec) / 1e9;
        fprintf(stderr,
                "CAT: entries=%zu input_bytes=%" PRIu64 " archive_bytes=%" PRIu64
                " tree_blocks=%" PRIu64 " raw_blocks=%" PRIu64 " seconds=%.6f",
                count, total, stored_size, tree_blocks, raw_blocks, seconds);
        if (encoding && exclude_count) {
            fprintf(stderr, " excluded_paths=%zu", excluded_path_count);
            if (!excluded_path_count)
                fputs(" warning=no_exclusion_patterns_matched", stderr);
        }
        if (total)
            fprintf(stderr, " ratio=%.6f", (double)stored_size / (double)total);
        else
            fputs(" ratio=n/a", stderr);
        fprintf(stderr, " gzip=%s cat_bytes=%" PRIu64, gzipped ? "on" : "off", cat_size);
        struct rusage usage;
        if (!getrusage(RUSAGE_SELF, &usage)) {
#ifdef __APPLE__
            uint64_t rss = (uint64_t)usage.ru_maxrss;
#else
            uint64_t rss = (uint64_t)usage.ru_maxrss * 1024;
#endif
            fprintf(stderr, " peak_rss_bytes=%" PRIu64, rss);
        }
        fputc('\n', stderr);
    }
    clear_entries();
    clear_exclude_patterns();
    cat_spools_close();
    cat_transform_close();
    return cat_cancelled ? 128 + cat_cancelled : rc ? 1 : 0;
}
#else
/* libFuzzer exercises the real streaming parser without extraction. */
int cat_fuzz_input(const uint8_t *data, size_t length) {
    cat_cancelled = 0;
    cat_error[0] = 0;
    max_bytes = 1024 * 1024;
    max_archive = 1024 * 1024;
    cat_temp_limit = 4 * 1024 * 1024;
    if (cat_io_init(0) || cat_transform_init())
        return 0;
    cat_spool *raw = cat_spool_new();
    if (raw && !cat_spool_write(raw, data, length)) {
        if (length >= 2 && data[0] == 0x1f && data[1] == 0x8b) {
            cat_spool *plain = cat_spool_new();
            if (plain && !cat_seek(raw->fd, 0) &&
                !cat_gzip_stream(raw->fd, length, plain, max_archive, 1))
                parse(plain, NULL);
        } else
            parse(raw, NULL);
    }
    clear_entries();
    cat_spools_close();
    cat_transform_close();
    return 0;
}
#endif
