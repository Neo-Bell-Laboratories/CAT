#include <cats/transform.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
int main(void) {
    if (cat_transform_init()) return 1;
    uint8_t data[CATS_BLOCK_MAX];
    uint8_t *invalid_output = (uint8_t *)(uintptr_t)1;
    size_t invalid_size = 1;
    if (cat_tree_estimate(NULL, 1) != SIZE_MAX || cat_tree_may_compress(NULL, 1) ||
        cat_tree_encode(NULL, 1, &invalid_output, &invalid_size) == 0 ||
        invalid_output != NULL || invalid_size != 0) {
        fprintf(stderr,"invalid encode input was not rejected cleanly\n"); return 1;
    }
    invalid_output = (uint8_t *)(uintptr_t)1;
    if (cat_tree_decode(NULL, 1, 1, &invalid_output) == 0 || invalid_output != NULL) {
        fprintf(stderr,"invalid decode input was not rejected cleanly\n"); return 1;
    }
    unsigned state = 1234567;
    for (int kind = 0; kind < 5; kind++) {
        for (size_t i = 0; i < sizeof(data); i++) {
            state = state * 1664525u + 1013904223u;
            data[i] = kind == 0 ? 0 : kind == 1 ? 255 : kind == 2 ? (uint8_t)i : kind == 3 ? (uint8_t)(i/31) : (uint8_t)(state >> 24);
        }
        const size_t sizes[] = {0,1,17,256,CATS_BLOCK_MAX};
        for (size_t j = 0; j < sizeof(sizes)/sizeof(sizes[0]); j++) {
            size_t estimate = cat_tree_estimate(data, sizes[j]);
            if (cat_tree_may_compress(data, sizes[j]) != (estimate < sizes[j])) {
                fprintf(stderr,"compression estimate mismatch: kind=%d size=%zu\n",kind,sizes[j]); return 1;
            }
            uint8_t *tree = NULL, *restored = NULL; size_t n = 0;
            if (cat_tree_encode(data,sizes[j],&tree,&n) || cat_tree_decode(tree,n,sizes[j],&restored) || memcmp(data,restored,sizes[j])) {
                fprintf(stderr,"transform failed: kind=%d size=%zu\n",kind,sizes[j]); return 1;
            }
            free(restored); restored = NULL;
            if (cat_tree_decode(tree,n-1,sizes[j],&restored) == 0) return 1;
            free(tree);
        }
    }
    /* A CAT archive keeps one XF session across its blocks. Repeated full
     * blocks in that session must produce identical independent buffers. */
    memset(data, 0, sizeof(data));
    uint8_t *first = NULL, *second = NULL, *decoded = NULL;
    size_t first_n = 0, second_n = 0;
    if (cat_transform_session_begin(0) ||
        cat_tree_encode(data, sizeof(data), &first, &first_n) ||
        cat_tree_encode(data, sizeof(data), &second, &second_n) ||
        first_n != second_n || memcmp(first, second, first_n) ||
        cat_transform_session_end()) {
        fprintf(stderr,"repeated-block encode session failed\n"); return 1;
    }
    free(second); second = NULL;
    if (cat_transform_session_begin(1) ||
        cat_tree_decode(first, first_n, sizeof(data), &decoded) ||
        memcmp(data, decoded, sizeof(data))) {
        fprintf(stderr,"repeated-block decode session failed\n"); return 1;
    }
    free(decoded); decoded = NULL;
    if (cat_tree_decode(first, first_n, sizeof(data), &decoded) ||
        memcmp(data, decoded, sizeof(data)) || cat_transform_session_end()) {
        fprintf(stderr,"repeated-block decode cache session failed\n"); return 1;
    }
    free(first); free(decoded);
    cat_transform_close();
    puts("PASS: XF table/tree binary round trips and truncation checks");
    return 0;
}
