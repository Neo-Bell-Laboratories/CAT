#include "transform.h"
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
int LLVMFuzzerTestOneInput(const uint8_t *data,size_t n) {
    if(n<2||n>32768)return 0;
    size_t original=((size_t)data[0]*256+data[1])%(CAT_BLOCK_MAX+1);
    if(cat_transform_init())return 0;
    uint8_t *out=NULL;
    cat_tree_decode(data+2,n-2,original,&out);
    free(out);cat_transform_close();return 0;
}
