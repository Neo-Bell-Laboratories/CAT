#ifndef CAT_GZIP_H
#define CAT_GZIP_H
#include "io.h"
/* Streams one gzip member between disk spools. No input-size allocation. */
int cat_gzip_stream(int input, uint64_t input_bytes, cat_spool *output, uint64_t output_limit,
                    int decompress);
#endif
