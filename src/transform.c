#include "transform.h"
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
void cat_transform_close(void) {
    initialized = 0;
    xf_value_release(input); input = xf_val_null();
    xf_value_release(captured); captured = xf_val_null();
}
static int run(xf_Value value, int inverse) {
    const char *tail = inverse
        ? "\nBEGIN { cat_capture(cat_table_to_bytes(cat_tree_to_table(cat_input()))) }\n"
        : "\nBEGIN { cat_capture(cat_table_to_tree(cat_table_from_bytes(cat_input()))) }\n";
    size_t len = strlen(cat_table_source) + strlen(tail) + 1;
    char *source = malloc(len);
    if (!source) return -1;
    snprintf(source, len, "%s%s", cat_table_source, tail);
    xf_value_release(input); input = xf_value_retain(value);
    xf_value_release(captured); captured = xf_val_null(); captures = 0;
    if (xf_driver_init(&driver)) { free(source); return -1; }
    int rc = 0;
    if (!bind("cat_input", inverse ? XF_TYPE_MAP : XF_TYPE_ARR, host_input) ||
        !bind("cat_capture", XF_TYPE_VOID, host_capture)) rc = -1;
    if (!rc) rc = xf_driver_load_string(&driver, source, "CAT/Table.xf");
    if (!rc) rc = xf_driver_run_loaded(&driver);
    if (!rc) rc = xf_driver_run_end(&driver);
    if (rc || xf_driver_had_error(&driver) || captures != 1) {
        fprintf(stderr, "CAT XF transform failed: %s\n", xf_driver_last_error(&driver));
        rc = -1;
    }
    xf_driver_free(&driver);
    free(source);
    xf_value_release(input); input = xf_val_null();
    return rc;
}
static xf_Value get(xf_map_t *map, const char *name) {
    xf_Str *key = xf_str_from_cstr(name);
    if (!key) return xf_val_null();
    xf_Value v = xf_map_get(map, key);
    xf_str_release(key);
    return v;
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
            if ((shift && !(b & 127)) || v > CAT_BLOCK_MAX) return -1;
            *out = v; return 0;
        }
    }
    return -1;
}
static size_t varint_size(size_t v) { size_t n=1; while(v>=128) { v>>=7; n++; } return n; }
/* Exact serialized tree size, computed in C. This avoids starting an XF driver
 * for blocks whose current bucket/run representation cannot beat raw bytes. */
size_t cat_tree_estimate(const uint8_t *bytes, size_t n) {
    if(n>CAT_BLOCK_MAX) return SIZE_MAX;
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
    }
    return size;
}
int cat_tree_encode(const uint8_t *bytes, size_t n, uint8_t **out, size_t *out_n) {
    if (n > CAT_BLOCK_MAX || !initialized) return -1;
    xf_arr_t *a = xf_arr_new();
    if (!a) return -1;
    for (size_t i = 0; i < n; i++) xf_arr_push(a, xf_val_ok_num(bytes[i]));
    xf_Value av = xf_val_ok_arr(a); xf_arr_release(a);
    int rc = run(av, 0); xf_value_release(av);
    if (rc || captured.type != XF_TYPE_MAP || captured.state != XF_STATE_OK) return -1;
    xf_Value buckets = get(captured.data.map, "buckets");
    if (buckets.type != XF_TYPE_MAP || buckets.state != XF_STATE_OK) {
        xf_value_release(buckets); return -1;
    }
    /* Worst case: one run per byte, with two bounded varints per run. */
    uint8_t *buf = malloc(8 * n + 2048);
    if (!buf) { xf_value_release(buckets); return -1; }
    size_t pos = 0, count = xf_map_count(buckets.data.map);
    put(buf, &pos, n); put(buf, &pos, count);
    uint8_t seen[CAT_BLOCK_MAX] = {0};
    size_t total = 0;
    for (unsigned byte = 0; byte < 256; byte++) {
        char key[4]; snprintf(key, sizeof(key), "%u", byte);
        xf_Value offsets = get(buckets.data.map, key);
        if (offsets.state != XF_STATE_OK) { xf_value_release(offsets); continue; }
        if (offsets.type != XF_TYPE_ARR || !offsets.data.arr->len) { rc = -1; xf_value_release(offsets); break; }
        xf_arr_t *xs = offsets.data.arr;
        buf[pos++] = (uint8_t)byte;
        size_t runs = 0, previous = 0;
        for (size_t i = 0; i < xs->len; i++) {
            size_t off;
            if (number(xs->items[i], n ? n - 1 : 0, &off) ||
                (i && off <= previous) || off >= n || seen[off] || bytes[off] != byte) { rc = -1; break; }
            if (!i || off != previous + 1) runs++;
            seen[off] = 1; total++; previous = off;
        }
        put(buf, &pos, runs);
        size_t end = 0;
        for (size_t i = 0; !rc && i < xs->len;) {
            size_t start = (size_t)xs->items[i].data.num, j = i + 1;
            while (j < xs->len && xs->items[j].data.num == xs->items[j-1].data.num + 1) j++;
            put(buf, &pos, start - end); put(buf, &pos, j - i);
            end = start + j - i; i = j;
        }
        xf_value_release(offsets);
        if (rc) break;
    }
    xf_value_release(buckets);
    if (rc || total != n) { free(buf); return -1; }
    *out = buf; *out_n = pos; return 0;
}
int cat_tree_decode(const uint8_t *data, size_t n, size_t expected, uint8_t **out) {
    if (expected > CAT_BLOCK_MAX || !initialized) return -1;
    size_t pos = 0, length, buckets_n, total = 0;
    if (take(data,n,&pos,&length) || length != expected || take(data,n,&pos,&buckets_n) || buckets_n > 256) return -1;
    xf_map_t *buckets = xf_map_new(), *tree = xf_map_new();
    if (!buckets || !tree) { if (buckets) xf_map_release(buckets); if (tree) xf_map_release(tree); return -1; }
    uint8_t seen[CAT_BLOCK_MAX] = {0};
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
    if (!rc) rc = run(tv, 1);
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
