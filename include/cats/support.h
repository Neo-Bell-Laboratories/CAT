#ifndef CATS_SUPPORT_H
#define CATS_SUPPORT_H

#include <signal.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define CATS_SUPPORT_API_VERSION 1u

/* Process-local disk spool used by streaming CATS components. The descriptor
 * and length are public so callers can compose their own container formats. */
typedef struct {
    int fd;
    uint64_t size;
} cat_spool;

extern volatile sig_atomic_t cat_cancelled;
extern uint64_t cat_temp_limit;
extern char cat_error[512];

int cat_fail(const char *message);
int cat_syserr(const char *operation);
int cat_io_init(int install_signals);
int cat_check_cancel(void);
cat_spool *cat_spool_new(void);
void cat_spool_close(cat_spool *spool);
void cat_spools_close(void);
int cat_seek(int fd, uint64_t offset);
int cat_read(int fd, void *data, size_t n);
int cat_write(int fd, const void *data, size_t n);
int cat_temp_claim(uint64_t n);
void cat_temp_release(uint64_t n);
int cat_spool_write(cat_spool *spool, const void *data, size_t n);
int cat_copy(int source, cat_spool *dest, uint64_t n);
int cat_sync(int fd, int directory);

typedef struct {
    uint32_t h[8];
    uint64_t bytes;
    uint8_t pending[64];
    size_t used;
} cat_sha256_ctx;
void cat_sha256_init(cat_sha256_ctx *ctx);
void cat_sha256_update(cat_sha256_ctx *ctx, const void *data, size_t n);
void cat_sha256_final(cat_sha256_ctx *ctx, uint8_t out[32]);
void cat_sha256(const void *data, size_t n, uint8_t out[32]);

/* Stream one gzip member between descriptors/spools. */
int cat_gzip_stream(int input, uint64_t input_bytes, cat_spool *output,
                    uint64_t output_limit, int decompress);

#ifdef __cplusplus
}
#endif

#endif
