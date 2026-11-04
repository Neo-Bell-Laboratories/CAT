#include "sha256.h"
#include <stddef.h>
#include <stdint.h>
#include <string.h>
extern int cat_fuzz_input(const uint8_t *,size_t);
extern size_t LLVMFuzzerMutate(uint8_t *,size_t,size_t);
int LLVMFuzzerTestOneInput(const uint8_t *data,size_t size) {
    return size<=1024*1024?cat_fuzz_input(data,size):0;
}
size_t LLVMFuzzerCustomMutator(uint8_t *data,size_t size,size_t max,unsigned seed) {
    (void)seed;
    size=LLVMFuzzerMutate(data,size,max);
    /* Repair the outer digest so malformed manifests/tree nodes reach their
     * validators, rather than every mutation stopping at the checksum. */
    if(size>=64&&!memcmp(data,"CAT\0",4))cat_sha256(data,size-32,data+size-32);
    return size;
}
