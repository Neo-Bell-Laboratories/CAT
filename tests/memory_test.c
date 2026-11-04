#include "sha256.h"
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
extern int cat_fuzz_input(const uint8_t *,size_t);
int main(int argc,char **argv) {
    unsigned state=20261103;size_t cases=0;
    for(int arg=1;arg<argc;arg++) {
        FILE *file=fopen(argv[arg],"rb");if(!file)return 1;
        uint8_t original[65536],changed[65536];size_t n=fread(original,1,sizeof(original),file);
        if(ferror(file)||!feof(file)){fclose(file);return 1;}fclose(file);
        for(unsigned repeat=0;repeat<10;repeat++){cat_fuzz_input(original,n);cases++;}
        for(unsigned mutation=0;mutation<256;mutation++) {
            memcpy(changed,original,n);
            state=state*1664525u+1013904223u;
            size_t available=n>=64&&!memcmp(original,"CAT\0",4)?n-32:n;
            if(available)changed[state%available]^=(uint8_t)(1u<<((state>>16)&7));
            if(n>=64&&!memcmp(changed,"CAT\0",4))cat_sha256(changed,n-32,changed+n-32);
            cat_fuzz_input(changed,n);cases++;
        }
    }
    printf("PASS: %zu persistent valid/malformed archive memory cycles\n",cases);
    return 0;
}
