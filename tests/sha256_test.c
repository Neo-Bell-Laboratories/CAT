#include "sha256.h"
#include <stdio.h>
#include <string.h>

static int matches(const unsigned char digest[32], const char *expected) {
    char hex[65];
    for (unsigned i = 0; i < 32; i++) snprintf(hex + i * 2, 3, "%02x", digest[i]);
    return strcmp(hex, expected) == 0;
}
int main(void) {
    unsigned char hash[32];
    cat_sha256("", 0, hash);
    if (!matches(hash, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")) return 1;
    cat_sha256_ctx context;
    cat_sha256_init(&context);
    cat_sha256_update(&context, "a", 1);
    cat_sha256_update(&context, NULL, 0);
    cat_sha256_update(&context, "bc", 2);
    cat_sha256_final(&context, hash);
    if (!matches(hash, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")) return 1;
    char data[1000]; memset(data, 'a', sizeof(data));
    cat_sha256_init(&context);
    for (unsigned i = 0; i < 1000; i++) cat_sha256_update(&context, data, sizeof(data));
    cat_sha256_final(&context, hash);
    if (!matches(hash, "cdc76e5c9914fb9281a1c7e284d73e67f1809a48a497200e046d39ccc7112cd0")) return 1;
    puts("PASS: independent SHA-256 vectors, incremental boundaries and empty updates");
    return 0;
}
