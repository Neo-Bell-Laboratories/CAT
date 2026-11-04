#include "transform.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    if (cat_transform_init()) return 1;
    uint8_t data[CAT_BLOCK_MAX];
    unsigned state = 1234567;
    for (int kind = 0; kind < 5; kind++) {
        for (size_t i = 0; i < sizeof(data); i++) {
            state = state * 1664525u + 1013904223u;
            data[i] = kind == 0 ? 0 : kind == 1 ? 255 : kind == 2 ? (uint8_t)i : kind == 3 ? (uint8_t)(i/31) : (uint8_t)(state >> 24);
        }
        const size_t sizes[] = {0,1,17,256,CAT_BLOCK_MAX};
        for (size_t j = 0; j < sizeof(sizes)/sizeof(sizes[0]); j++) {
            uint8_t *tree = NULL, *restored = NULL; size_t n = 0;
            if (cat_tree_encode(data,sizes[j],&tree,&n) || cat_tree_decode(tree,n,sizes[j],&restored) || memcmp(data,restored,sizes[j])) {
                fprintf(stderr,"transform failed: kind=%d size=%zu\n",kind,sizes[j]); return 1;
            }
            free(restored); restored = NULL;
            if (cat_tree_decode(tree,n-1,sizes[j],&restored) == 0) return 1;
            free(tree);
        }
    }
    cat_transform_close();
    puts("PASS: XF table/tree binary round trips and truncation checks");
    return 0;
}
