#include <cats/transform.h>
#include "driver.h"
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "table_source.h"

static xf_Driver driver;
static int initialized;
static xf_Value input, captured;
static unsigned captures;
static int session_active, session_inverse;

/* Cache the most recent successful block transform during a multi-block
 * session. Repeated blocks are common in padded, sparse-looking, and highly
 * repetitive inputs. Keep independent copies so callers may immediately
 * release or reuse their buffers. Cache allocation failure is only a missed
 * optimization and must never fail a transform. */
typedef struct {
    int valid, inverse;
    size_t input_n, expected_n, output_n;
    uint8_t *input, *output;
} BlockCache;
static BlockCache block_cache;

static void block_cache_clear(void) {
    free(block_cache.input);
    free(block_cache.output);
    memset(&block_cache, 0, sizeof(block_cache));
}

static int block_cache_get(int inverse, const uint8_t *bytes, size_t n,
                           size_t expected_n, uint8_t **out, size_t *out_n) {
    if (!block_cache.valid || block_cache.inverse != inverse ||
        block_cache.input_n != n || block_cache.expected_n != expected_n ||
        !n || memcmp(block_cache.input, bytes, n)) return 0;
    uint8_t *copy = malloc(block_cache.output_n ? block_cache.output_n : 1);
    if (!copy) return 0;
    if (block_cache.output_n) memcpy(copy, block_cache.output, block_cache.output_n);
    *out = copy;
    if (out_n) *out_n = block_cache.output_n;
    return 1;
}

static void block_cache_put(int inverse, const uint8_t *bytes, size_t n,
                            size_t expected_n, const uint8_t *result, size_t result_n) {
    if (!n || !result_n) return;
    uint8_t *input_copy = malloc(n), *output_copy = malloc(result_n);
    if (!input_copy || !output_copy) {
        free(input_copy);
        free(output_copy);
        return;
    }
    memcpy(input_copy, bytes, n);
    memcpy(output_copy, result, result_n);
    block_cache_clear();
    block_cache.valid = 1;
    block_cache.inverse = inverse;
    block_cache.input_n = n;
    block_cache.expected_n = expected_n;
    block_cache.output_n = result_n;
    block_cache.input = input_copy;
    block_cache.output = output_copy;
}

static xf_Value host_input(xf_Value *args, size_t argc) {
    (void)args; (void)argc;
    return xf_value_retain(input);
}
static xf_Value host_capture(xf_Value *args, size_t argc) {
    if (argc == 1) {
        xf_value_release(captured);
        captured = xf_value_retain(args[0]);
        captures++;
    }
    return xf_val_null();
}
static int bind(const char *name, uint8_t ret, xf_Value (*fn)(xf_Value *, size_t)) {
    xf_Value v = xf_val_native_fn(name, ret, fn);
    int ok = sym_define_builtin(&driver.syms, name, XF_TYPE_FN, v) != NULL;
    xf_value_release(v);
    return ok;
}
int cat_transform_init(void) {
    if (initialized) return 0;
    input = captured = xf_val_null();
    initialized = 1;
    return 0;
}
int cat_transform_session_begin(int inverse) {
    if (!initialized || session_active) return -1;
    block_cache_clear();
    if (xf_driver_init(&driver)) return -1;
    if (!bind("cat_input_bytes", XF_TYPE_ARR, host_input) ||
        !bind("cat_input_tree", XF_TYPE_MAP, host_input) ||
        !bind("cat_capture", XF_TYPE_VOID, host_capture)) {
        xf_driver_free(&driver);
        return -1;
    }
    const char *tail = inverse
        ? "\n{ cat_capture(cat_table_to_bytes(cat_tree_to_table(cat_input_tree()))) }\n"
        : "\n{ cat_capture(cat_table_to_tree(cat_table_from_bytes(cat_input_bytes()))) }\n";
    size_t len = strlen(cat_table_source) + strlen(tail) + 1;
    char *source = malloc(len);
    if (!source) {
        xf_driver_free(&driver);
        return -1;
    }
    snprintf(source, len, "%s%s", cat_table_source, tail);
    int rc = xf_driver_load_string(&driver, source, "CAT/Table.xf");
    free(source);
    if (rc || xf_driver_had_error(&driver)) {
        fprintf(stderr, "CAT XF session load failed: %s\n", xf_driver_last_error(&driver));
        xf_driver_free(&driver);
        return -1;
    }
    session_inverse = inverse;
    session_active = 1;
    return 0;
}
int cat_transform_session_end(void) {
    if (!session_active) return 0;
    int rc = xf_driver_run_end(&driver);
    if (rc || xf_driver_had_error(&driver)) {
        fprintf(stderr, "CAT XF session end failed: %s\n", xf_driver_last_error(&driver));
        rc = -1;
    }
    session_active = 0;
    xf_driver_free(&driver);
    xf_value_release(input); input = xf_val_null();
    xf_value_release(captured); captured = xf_val_null();
    captures = 0;
    block_cache_clear();
    return rc;
}
int cat_transform_session_is_active(void) {
    return session_active;
}
void cat_transform_close(void) {
    if (session_active) cat_transform_session_end();
    if (initialized) xf_driver_free(&driver);
    initialized = 0;
    xf_value_release(input); input = xf_val_null();
    xf_value_release(captured); captured = xf_val_null();
    block_cache_clear();
}
static int run_block(xf_Value value, int inverse) {
    if (!session_active || session_inverse != inverse) return -1;
    xf_value_release(input); input = xf_value_retain(value);
    xf_value_release(captured); captured = xf_val_null(); captures = 0;
    int rc = xf_driver_feed_line(&driver, "x");
    if (rc || xf_driver_had_error(&driver) || captures != 1) {
        fprintf(stderr, "CAT XF transform failed: %s\n", xf_driver_last_error(&driver));
        rc = -1;
    }
    xf_value_release(input); input = xf_val_null();
    return rc;
}
static void set(xf_map_t *map, const char *name, xf_Value value) {
    xf_Str *key = xf_str_from_cstr(name);
    if (key) { xf_map_set(map, key, value); xf_str_release(key); }
}
static int number(xf_Value v, size_t max, size_t *out) {
    if (v.state != XF_STATE_OK || v.type != XF_TYPE_NUM ||
        !isfinite(v.data.num) || v.data.num < 0 || v.data.num > (double)max ||
        floor(v.data.num) != v.data.num) return -1;
    *out = (size_t)v.data.num;
    return 0;
}
/* Canonical unsigned LEB128, bounded by the 65536-byte experimental transform block. */
static void put(uint8_t *out, size_t *n, size_t v) {
    do { uint8_t b = v & 127; v >>= 7; out[(*n)++] = b | (v ? 128 : 0); } while (v);
}
static int take(const uint8_t *data, size_t n, size_t *pos, size_t *out) {
    size_t v = 0;
    for (unsigned shift = 0; shift <= 14; shift += 7) {
        if (*pos == n) return -1;
        uint8_t b = data[(*pos)++];
        v |= (size_t)(b & 127) << shift;
        if (!(b & 128)) {
            if ((shift && !(b & 127)) || v > CATS_BLOCK_MAX) return -1;
            *out = v; return 0;
        }
    }
    return -1;
}
static size_t varint_size(size_t v) { size_t n=1; while(v>=128) { v>>=7; n++; } return n; }
/* Exact serialized tree size, computed in C. This avoids starting an XF driver
 * for blocks whose current bucket/run representation cannot beat raw bytes. */
static size_t tree_estimate(const uint8_t *bytes, size_t n, size_t stop_at) {
    if(n>CATS_BLOCK_MAX) return SIZE_MAX;
    size_t last_end[256]={0}, run_count[256]={0}, current_run[256]={0};
    uint8_t present[256]={0};
    size_t buckets=0, size=varint_size(n)+varint_size(0);
    for(size_t i=0;i<n;i++) {
        unsigned b=bytes[i];
        if(!present[b]) {
            present[b]=1; buckets++;
            size += varint_size(buckets)-varint_size(buckets-1);
            run_count[b]=1; current_run[b]=1;
            size += 1 + varint_size(1) + varint_size(i) + varint_size(1);
        } else if(i==last_end[b]) {
            size -= varint_size(current_run[b]); current_run[b]++;
            size += varint_size(current_run[b]);
        } else {
            size -= varint_size(run_count[b]); run_count[b]++;
            size += varint_size(run_count[b]);
            size += varint_size(i-last_end[b]) + varint_size(1);
            current_run[b]=1;
        }
        last_end[b]=i+1;
        /* The estimate only grows as buckets/runs are added or lengthened.
         * The encoder only needs to know whether it can beat raw bytes, so
         * stop as soon as that is impossible. */
        if(stop_at && size >= stop_at) return stop_at;
    }
    return size;
}
size_t cat_tree_estimate(const uint8_t *bytes, size_t n) {
    if (n && !bytes) return SIZE_MAX;
    return tree_estimate(bytes, n, 0);
}
int cat_tree_may_compress(const uint8_t *bytes, size_t n) {
    return bytes && n && n <= CATS_BLOCK_MAX && tree_estimate(bytes, n, n) < n;
}
static int tree_encode_active(const uint8_t *bytes, size_t n, uint8_t **out, size_t *out_n) {
    if (n > CATS_BLOCK_MAX || !initialized || (n && !bytes) || !out || !out_n) return -1;

    size_t counts[256] = {0}, starts[256], cursor[256];
    size_t bucket_count = 0;
    for (size_t i = 0; i < n; i++) counts[bytes[i]]++;
    size_t next = 0;
    for (size_t byte = 0; byte < 256; byte++) {
        starts[byte] = cursor[byte] = next;
        next += counts[byte];
        bucket_count += counts[byte] != 0;
    }
    if (next != n) return -1;

    /* CATS_BLOCK_MAX is 8192, so every source position fits in uint16_t. */
    uint16_t *positions = malloc((n ? n : 1) * sizeof(*positions));
    if (!positions) return -1;
    for (size_t i = 0; i < n; i++) {
        unsigned byte = bytes[i];
        positions[cursor[byte]++] = (uint16_t)i;
    }

    /* Worst case is one isolated run per input byte, with two bounded varints. */
    uint8_t *buf = malloc(8 * n + 2048);
    if (!buf) { free(positions); return -1; }
    size_t pos = 0;
    put(buf, &pos, n);
    put(buf, &pos, bucket_count);
    for (size_t byte = 0; byte < 256; byte++) {
        size_t count = counts[byte];
        if (!count) continue;
        size_t begin = starts[byte], limit = begin + count, runs = 0;
        for (size_t i = begin; i < limit; i++)
            if (i == begin || positions[i] != (uint16_t)(positions[i - 1] + 1)) runs++;

        buf[pos++] = (uint8_t)byte;
        put(buf, &pos, runs);
        size_t end = 0;
        for (size_t i = begin; i < limit;) {
            size_t j = i + 1;
            while (j < limit && positions[j] == (uint16_t)(positions[j - 1] + 1)) j++;
            size_t start = positions[i], length = j - i;
            put(buf, &pos, start - end);
            put(buf, &pos, length);
            end = start + length;
            i = j;
        }
    }
    free(positions);
    *out = buf;
    *out_n = pos;
    return 0;
}
int cat_tree_encode(const uint8_t *bytes, size_t n, uint8_t **out, size_t *out_n) {
    if (out) *out = NULL;
    if (out_n) *out_n = 0;
    if (!out || !out_n) return -1;
    if ((n && !bytes) || n > CATS_BLOCK_MAX) return -1;
    if (block_cache_get(0, bytes, n, n, out, out_n)) return 0;
    int rc = tree_encode_active(bytes, n, out, out_n);
    if (!rc) block_cache_put(0, bytes, n, n, *out, *out_n);
    return rc;
}
static int tree_decode_active(const uint8_t *data, size_t n, size_t expected, uint8_t **out) {
    if (expected > CATS_BLOCK_MAX || !initialized) return -1;
    size_t pos = 0, length, buckets_n, total = 0;
    if (take(data,n,&pos,&length) || length != expected || take(data,n,&pos,&buckets_n) || buckets_n > 256) return -1;
    xf_map_t *buckets = xf_map_new(), *tree = xf_map_new();
    if (!buckets || !tree) { if (buckets) xf_map_release(buckets); if (tree) xf_map_release(tree); return -1; }
    uint8_t seen[CATS_BLOCK_MAX] = {0};
    int previous_byte = -1, rc = 0;
    for (size_t b = 0; b < buckets_n && !rc; b++) {
        if (pos == n) { rc = -1; break; }
        unsigned byte = data[pos++]; size_t runs;
        if ((int)byte <= previous_byte || take(data,n,&pos,&runs) || !runs || runs > length) { rc = -1; break; }
        previous_byte = byte;
        xf_arr_t *offsets = xf_arr_new();
        if (!offsets) { rc = -1; break; }
        size_t end = 0;
        for (size_t r = 0; r < runs && !rc; r++) {
            size_t gap, run;
            if (take(data,n,&pos,&gap) || take(data,n,&pos,&run) || !run ||
                (r && !gap) || gap > length - end || run > length - end - gap) { rc = -1; break; }
            size_t start = end + gap; end = start + run;
            for (size_t i = start; i < end; i++) {
                if (seen[i]) { rc = -1; break; }
                seen[i] = 1; total++;
                xf_arr_push(offsets, xf_val_ok_num((double)i));
            }
        }
        char key[4]; snprintf(key,sizeof(key),"%u",byte);
        xf_Value v = xf_val_ok_arr(offsets); xf_arr_release(offsets);
        set(buckets,key,v); xf_value_release(v);
    }
    if (total != length || pos != n) rc = -1;
    set(tree,"length",xf_val_ok_num((double)length));
    xf_Value bv = xf_val_ok_map(buckets); xf_map_release(buckets);
    set(tree,"buckets",bv); xf_value_release(bv);
    xf_Value tv = xf_val_ok_map(tree); xf_map_release(tree);
    if (!rc) rc = run_block(tv, 1);
    xf_value_release(tv);
    uint8_t *bytes = NULL;
    if (!rc && captured.state == XF_STATE_OK && captured.type == XF_TYPE_ARR && captured.data.arr->len == expected) {
        bytes = malloc(expected ? expected : 1);
        if (!bytes) rc = -1;
        for (size_t i = 0; !rc && i < expected; i++) {
            size_t byte;
            if (number(captured.data.arr->items[i],255,&byte)) rc = -1;
            else bytes[i] = (uint8_t)byte;
        }
    } else rc = -1;
    if (rc) { free(bytes); return -1; }
    *out = bytes; return 0;
}
int cat_tree_decode(const uint8_t *data, size_t n, size_t expected, uint8_t **out) {
    if (!out) return -1;
    *out = NULL;
    if ((n && !data) || expected > CATS_BLOCK_MAX) return -1;
    int own_session = !session_active;
    if (own_session && cat_transform_session_begin(1)) return -1;
    int rc;
    if (block_cache_get(1, data, n, expected, out, NULL)) rc = 0;
    else {
        rc = tree_decode_active(data, n, expected, out);
        if (!rc) block_cache_put(1, data, n, expected, *out, expected);
    }
    if (own_session && cat_transform_session_end()) rc = -1;
    return rc;
}
