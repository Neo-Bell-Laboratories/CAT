#ifndef CATS_TRANSFORM_H
#define CATS_TRANSFORM_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Stable C block-transform interface for applications embedding the CATS
 * aggregate-tree codec. The current transform payload format is version 1. */
#define CATS_TRANSFORM_API_VERSION 1u
#define CATS_TRANSFORM_FORMAT_VERSION 1u
#define CATS_BLOCK_MAX 8192u
#define CATS_BLOCK_V02_MAX 16384u
#define CATS_BLOCK_V01_MAX 4096u

/* Initialize the process-wide codec state before encoding or decoding.
 * Calls are not thread-safe; serialize codec access. */
int cat_transform_init(void);
void cat_transform_close(void);

/* Optional session controls amortize decoder setup across multiple blocks.
 * inverse is nonzero for a decode session. cat_tree_decode starts and ends a
 * temporary inverse session when no session is active. */
int cat_transform_session_begin(int inverse);
int cat_transform_session_end(void);
int cat_transform_session_is_active(void);

/* Estimate serialized size or determine whether the current transform can
 * represent this block in fewer bytes. A block may contain at most
 * CATS_BLOCK_MAX bytes. cat_tree_estimate returns SIZE_MAX for a nonempty
 * block with a NULL input pointer; cat_tree_may_compress returns false. */
size_t cat_tree_estimate(const uint8_t *bytes, size_t n);
int cat_tree_may_compress(const uint8_t *bytes, size_t n);

/* Encode/decode one aggregate-tree block. Output buffers are allocated by
 * the library and become caller-owned; release them with free(). On failure,
 * output pointers are set to NULL. */
int cat_tree_encode(const uint8_t *bytes, size_t n,
                    uint8_t **out, size_t *out_n);
int cat_tree_decode(const uint8_t *data, size_t n, size_t expected,
                    uint8_t **out);

#ifdef __cplusplus
}
#endif

#endif
