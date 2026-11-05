#ifndef CAT_TRANSFORM_H
#define CAT_TRANSFORM_H
#include <stddef.h>
#include <stdint.h>
/* Bounded serial adapter; buffers returned to the caller are malloc-owned. */
#define CAT_BLOCK_MAX 8192u
#define CAT_BLOCK_V02_MAX 16384u
#define CAT_BLOCK_V01_MAX 4096u
int cat_transform_init(void);
void cat_transform_close(void);
int cat_transform_session_begin(int inverse);
int cat_transform_session_end(void);
int cat_transform_session_is_active(void);
size_t cat_tree_estimate(const uint8_t *bytes, size_t n);
int cat_tree_may_compress(const uint8_t *bytes, size_t n);
int cat_tree_encode(const uint8_t *bytes, size_t n, uint8_t **out, size_t *out_n);
int cat_tree_decode(const uint8_t *data, size_t n, size_t expected,
                    uint8_t **out);
#endif
