#include "gzip.h"
#include <zlib.h>
int cat_gzip_stream(int input, uint64_t remaining, cat_spool *output, uint64_t limit,
                    int decompress) {
    z_stream z = {0};
    int status = decompress ? inflateInit2(&z, 31)
                            : deflateInit2(&z, 9, Z_DEFLATED, 31, 8, Z_DEFAULT_STRATEGY);
    if (status != Z_OK)
        return cat_fail("cannot initialize zlib");
    gz_header header = {0};
    header.os = 255;
    if (!decompress && deflateSetHeader(&z, &header) != Z_OK) {
        deflateEnd(&z);
        return cat_fail("cannot initialize gzip header");
    }
    uint8_t in[32768], out[32768];
    uint64_t produced_total = 0;
    int rc = -1;
    for (;;) {
        if (cat_check_cancel())
            break;
        if (!z.avail_in && remaining) {
            size_t n = remaining > sizeof(in) ? sizeof(in) : (size_t)remaining;
            if (cat_read(input, in, n))
                break;
            remaining -= n;
            z.next_in = in;
            z.avail_in = (uInt)n;
        }
        z.next_out = out;
        z.avail_out = sizeof(out);
        status =
            decompress ? inflate(&z, Z_NO_FLUSH) : deflate(&z, remaining ? Z_NO_FLUSH : Z_FINISH);
        if (status != Z_OK && status != Z_STREAM_END) {
            cat_fail("invalid or truncated gzip stream");
            break;
        }
        size_t n = sizeof(out) - z.avail_out;
        if (n > limit - produced_total) {
            cat_fail("gzip output byte budget exceeded");
            break;
        }
        if (cat_spool_write(output, out, n))
            break;
        produced_total += n;
        if (status == Z_STREAM_END) {
            if (remaining || z.avail_in)
                cat_fail("trailing bytes or concatenated gzip members");
            else
                rc = 0;
            break;
        }
        if (decompress && !remaining && !z.avail_in && !n) {
            cat_fail("truncated gzip stream");
            break;
        }
    }
    if (decompress)
        inflateEnd(&z);
    else
        deflateEnd(&z);
    return rc;
}
