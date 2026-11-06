# Compression and speed benchmarks

Run the reproducible synthetic corpus and optionally a real file tree:

```sh
python3 tools/benchmark.py bin/cats \
  --tree /path/to/bytelang \
  --exclude .git --exclude build --exclude .DS_Store --exclude '._*'
```

The script round-trips CAT v0.7, v0.7+gzip, compact v0.8, and v0.8+gzip,
checking restored paths and file bytes. It records their sizes and CAT's
encode/decode times alongside deterministic USTAR, USTAR+gzip, ZIP deflate, and
per-file gzip payload sizes. The per-file gzip figure excludes tree metadata;
the other archive formats include their file-tree metadata.

## ByteLang sample

On macOS ARM64, the current `bl/bytelang` snapshot contained 179,644 input
bytes after excluding `.git`, `build`, `.DS_Store`, and AppleDouble `._*` files.
The exact results are in `benchmark-macos.json`.

| Format | Bytes | Relative to input |
| --- | ---: | ---: |
| CAT v0.7 | 183,478 | 102.13% |
| CAT v0.7 + gzip | 37,131 | 20.67% |
| CAT compact v0.8 | 183,286 | 102.03% |
| CAT compact v0.8 + gzip | 37,122 | 20.66% |
| tar | 215,040 | 119.70% |
| tar.gz | 36,197 | 20.15% |
| ZIP deflate | 45,211 | 25.17% |
| gzip of each file's payload | 41,107 | 22.88% |

For this snapshot, `-c` saves 192 bytes without gzip and 9 bytes with gzip.
CAT+gzip is 934 bytes larger than tar.gz, so this sample does not support a
claim that CAT consistently compresses smaller than established archive
formats. The size result depends on the source tree and exclusion patterns.

The single-run encode observations were CAT 5.39 ms, CAT+gzip 14.37 ms,
compact CAT 6.94 ms, compact CAT+gzip 15.08 ms, USTAR 11.42 ms, the separate
gzip pass 8.70 ms, ZIP 5.52 ms, and per-file gzip 4.65 ms. These are indicative
only: the CAT timer is reported by the C program, while baseline timers wrap
Python standard-library operations, and one small run is not enough to claim a
general speed ranking. Use repeated runs on representative trees before making
release performance claims.

The Pi Zero 2 W measurements and the synthetic incompressible/repetitive cases
remain in `benchmark-pi.json` and `benchmark-macos.json`. In particular, outer
gzip may increase the size of already-compressed or random data; callers should
measure representative input before enabling it by default.

## Zstandard experiment

`benchmark-zstd-macos.json` records the same deterministic synthetic corpus and
ByteLang snapshot with Zstandard 1.5.7. It includes tar.zst at levels 3 and 19,
and an external zstd wrapper around plain CAT v0.7 and compact v0.8 archives.
The harness checks that zstd restores the exact tar/CAT archive bytes before
counting a result. This is a benchmark only; CATS does not read or write zstd
wrappers, so wrapped CAT archives need `zstd -d` before CATS can inspect or
extract them.

| ByteLang format | Bytes |
| --- | ---: |
| CAT v0.7 + gzip | 37,131 |
| CAT compact v0.8 + gzip | 37,122 |
| CAT v0.7 + zstd -3 | 38,640 |
| CAT v0.8 + zstd -3 | 38,595 |
| CAT v0.7 + zstd -19 | 28,561 |
| CAT v0.8 + zstd -19 | 28,607 |
| tar.gz | 36,197 |
| tar.zst -3 | 37,143 |
| tar.zst -19 | 27,349 |

On this tree, zstd level 3 did not beat CAT+gzip or tar.gz for size. Level 19
made a plain CAT archive about 23% smaller than CAT+gzip, while tar.zst -19 was
about 24% smaller than tar.gz. The single-run measured CAT+gzip encode time was
12.5 ms; CAT v0.7 followed by external zstd -19 took about 44 ms including the
zstd process, and tar creation plus zstd -19 took about 41 ms. Process startup
is included in external zstd timings, so these are indicative rather than a
codec-only speed comparison. Level 3 wrapped around CAT took about 8.8 ms and
produced a 4% larger file than CAT+gzip in this run, suggesting a possible
speed-oriented option. On zero and repetitive inputs zstd produced much
smaller archives; on random or already-compressed input it was near identity
and sometimes added bytes. The results support zstd -19 as a possible optional
high-compression mode and level 3 as a possible speed-oriented mode, not a
default. Zstandard integration is deferred to the [0.5 roadmap](ROADMAP-v0.5.md);
it would require a versioned codec marker and a decoder path on every supported
platform.
