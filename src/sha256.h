#ifndef CAT_SHA256_H
#define CAT_SHA256_H
#include <stddef.h>
#include <stdint.h>
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
#endif
