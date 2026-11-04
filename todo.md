# CAT — Compression Development Roadmap

**Project:** Compressed Aggregate Tree (CAT)  
**Scope:** General-purpose, lossless file/directory archiving and compression  
**Development host:** macOS  
**Portability target:** Linux / Raspberry Pi Zero 2 W  
**Out of scope for now:** CAAT audio format, playback, audio devices, eSpeak, and media-specific codecs

## Objective and acceptance criteria

Implement a lossless CAT archive that can capture a file or directory tree, encode file content using existing XF vectorization and aggregate-tree facilities, merge the resulting per-file trees into one serialized binary aggregate tree, then reconstruct the original file tree **byte for byte**. Measure whether the representation actually compresses the input rather than merely repackaging it.

**Initial success:** Source files match restored files exactly; all directories and intended manifest metadata are recovered; validation detects malformed/corrupted archives; and encoding/decoding statistics are reported. **Compression success:** The final archive is smaller than the input on at least some clearly identified test classes, with overhead and counterexamples reported honestly.

## Proposed end-to-end pipeline

```
ENCODE
Input path(s)
  -> recursive directory inventory (stable relative paths, file IDs, metadata)
  -> sealed/versioned manifest (immutable once finalized)
  -> bounded XF worker queue (one logical task per file)
  -> read raw file bytes -> vectorize -> reverse-column representation
  -> per-file aggregate tree + associated file ID
  -> deterministic merge of per-file trees
  -> binary aggregate-tree serialization
  -> optional CAT compression stages / deduplication
  -> single .cat archive (header + manifest + payload + integrity records)

DECODE
.cat archive
  -> validate header, bounds, version, manifest, integrity records
  -> decode/decompress binary aggregate tree
  -> split merged tree by file ID
  -> aggregate tree -> XF table -> inverse reverse-column transform
  -> devectorize to original raw file bytes
  -> bounded XF worker queue writes reconstructed files
  -> restore safe directory hierarchy and supported metadata
  -> verify hashes and byte-for-byte equality in tests
```

The exact ordering of compression and binary serialization must be established experimentally. The above is an **architecture sketch**, not a claim about existing XF APIs.

* * *

## Phase 0 — Define the contract and inspect existing XF components

-   Record which XF functions already implement vectorization, reverse indexing, aggregate trees, binary serialization, and aggregate-tree-to-table conversion.
-   Identify actual C headers, library names, ownership rules, error interfaces, thread-safety constraints, and target-platform dependencies. Do not invent wrappers until the interfaces are confirmed.
-   Define the CAT v0.1 input model: a single regular file or a directory, with recursive contents.
-   Define losslessness as **exact byte reconstruction**, including NUL bytes, invalid UTF-8, and original line endings.
-   Decide the initial metadata contract: relative paths, file/directory type, file length, and optionally permissions and timestamps. Document anything explicitly not preserved.
-   Set resource budgets: max concurrent workers, in-flight bytes, maximum tree depth, archive/header size limits, and temporary disk usage.
-   Specify whether symbolic links are rejected, skipped with warning, or stored as links; do not follow links by default.

**Exit test:** Written CAT v0.1 contract plus a small compile/link smoke test invoking the real XF APIs.

## Phase 1 — Directory map and manifest

-   Implement recursive directory traversal without modifying source files.
-   Normalize stored names to safe **relative** paths; reject absolute paths, `..` traversal, duplicates, and unsafe extraction destinations.
-   Assign deterministic file IDs independent of worker scheduling; record empty directories and zero-byte files.
-   Define the manifest schema: archive version, entries, parent/relative path, type, size, payload/file ID, metadata flags, and content digest.
-   Detect source files that change during ingestion; fail or explicitly retry rather than silently produce inconsistent archives.
-   Finalize and **seal** the manifest after inventory and payload mapping are complete; serialize it inside the archive so `.cat` is self-contained.
-   Add round-trip tests for nested directories, whitespace and Unicode filenames, empty directories, and same-named files in different directories.

**Exit test:** A decoded manifest reconstructs the same logical directory map without any payload data.

## Phase 2 — Per-file reversible transformations

-   Read inputs in binary mode (no text decoding or newline normalization).
-   Implement an XF adapter: bytes -> vectorized representation -> reverse-column representation -> per-file aggregate tree.
-   Implement the exact inverse: per-file aggregate tree -> table -> inverse reverse-column transform -> devectorized bytes.
-   Preserve element types, lengths, order, repetitions, and zero-valued bytes through every transformation.
-   Prove each stage's round trip independently before combining stages.
-   Associate each per-file tree with its stable manifest file ID and original byte count.
-   Test fixtures: empty, one-byte, repetitive text, random bytes, binary executables, PNG/JPEG, UTF-8 and non-UTF-8, large runs of `0x00`/\`0xFF\`.
-   Compare original vs decoded bytes using `cmp` and a cryptographic hash (e.g., SHA-256) in the test harness.

**Exit test:** Every per-file fixture reconstructs exactly, even if its tree encoding is larger than the source.

## Phase 3 — XF worker orchestration

-   Represent each ordinary file as one **logical work item**; use a bounded worker pool rather than spawning one OS thread/process per file.
-   Make worker count configurable (default based on CPU/memory, with `--jobs N`).
-   Enforce bounded work queues and in-flight memory/backpressure; cap open file descriptors.
-   Collect results with file IDs and merge in stable file-ID order, regardless of completion order.
-   Define cancellation, per-file failures, cleanup of temporary files, and error propagation.
-   Stress-test many tiny files, a few very large files, and mixed sizes at `--jobs 1`, `2`, and `N`.
-   **Defer the two-worker multimodal-video special case.** Keep media opaque initially. If later splitting video streams, specify a reversible container/stream decomposition that preserves every byte and piece of metadata; two workers alone cannot guarantee exact video-file reconstruction.

**Exit test:** Concurrency changes speed and resource usage, not decoded bytes or deterministic archive structure.

## Phase 4 — Merge, binary aggregate tree, and archive format

-   Specify a deterministic merge operation preserving per-file namespace/boundaries, ordering, and file IDs.
-   Prove split(merge(trees)) reproduces the original trees exactly.
-   Verify XF binary aggregate-tree serialization and deserialization, including type and length fidelity.
-   Define `.cat` binary layout: magic, version, feature flags, manifest length, payload length, payload encoding identifier, integrity data, and optionally an index for random access.
-   Serialize the sealed manifest and merged binary-tree payload together in one portable archive.
-   Use fixed-size integer encodings/defined byte order; handle overflow, truncated files, and unsupported versions explicitly.
-   Implement parser validation of all offsets, lengths, counts, nesting depth, and decompressed-size limits *before* allocating or writing files.
-   Reject malicious archive paths and unsafe symlinks on extraction; do not overwrite existing files silently.
-   Add corruption tests for bad magic, bad version, truncated payload, hash mismatch, invalid bounds, and malformed tree nodes.

**Exit test:** `cat encode` produces a self-contained `.cat` that `cat decode` can fully and safely reconstruct on a second machine.

## Phase 5 — Demonstrate real compression

-   Measure **representation-only** size first: manifest + aggregate-tree payload + archive framing versus original files.
-   Identify where the XF structure exposes repeated values, repeated columns/subtrees, shared strings, or other patterns.
-   Prototype one or more *reversible* size-reduction stages (e.g., subtree interning, dictionary encoding, run-length encoding, or entropy coding) where data supports them.
-   Track any auxiliary dictionaries and indexes inside the archive; reconstruction must not depend on state outside `.cat`.
-   Add a raw/identity block fallback when compression increases size or cost; record the selected encoding in the archive.
-   Measure compressed size **including** manifest, framing, dictionaries, indexes, and checksum overhead.
-   Benchmark against uncompressed input and conventional baselines such as `gzip` or `zstd` using equivalent datasets and settings.
-   Report encode time, decode time, peak memory, throughput, and compression ratio (`archive_bytes / original_total_bytes`); smaller is better.
-   Test highly compressible text, many duplicate files, random/incompressible bytes, and already-compressed images/media; do not imply universal size reduction.

**Exit test:** Documented datasets demonstrate when CAT compresses, when it expands, and how it compares to conventional approaches.

## Phase 6 — Command-line interface and verification

-   Implement the public commands (names provisional):

    ```
    cat encode INPUT OUTPUT.cat [--jobs N]
    cat decode INPUT.cat OUTPUT_DIR [--jobs N]
    cat inspect INPUT.cat
    cat verify INPUT.cat
    ```

-   Resolve CLI executable naming collisions with the standard Unix `cat` utility; consider `catc` or `cat-archive` for the binary while retaining `.cat` as the format.

-   Add predictable exit codes, progress/logging, error diagnostics, and `--help`.

-   Implement `verify` for internal archive checks; perform source-versus-restored `cmp`/SHA-256 in tests.

-   Ensure interrupted encoding does not leave a seemingly valid archive: write temporary output, validate, then atomically rename on success.

-   Define extraction overwrite policy and safe cleanup after partial failure.

**Exit test:** A user can archive, inspect, verify, and extract data without touching XF internals.

## Phase 7 — Validation and cross-platform deployment

-   Build and run all unit, integration, and end-to-end tests on macOS.
-   Audit C portability (POSIX calls, endian assumptions, struct packing, word sizes, threading, mmap/IO behavior).
-   Build the same portable sources **natively on the Pi** through SSH. Mac-mounted files are convenient for editing, but Linux headers alone do not produce Linux binaries with a standard macOS toolchain.
-   Run round-trip and corruption tests on Linux / Pi Zero 2 W.
-   Benchmark small inputs and tight memory/workers on the Pi; select device-appropriate limits.
-   Run sanitizers on supported hosts; add randomized/fuzz inputs for archive parsing and transform inversion.
-   Save a versioned test corpus and golden archives to detect backward compatibility regressions.
-   Publish the CAT format specification, limitations, and measured results.

**Exit test:** Independent builds can exchange CAT archives without loss, and documented resource limits are respected.

* * *

## First implementation sprint (small and concrete)

-   Locate and smoke-test the current XF C headers/libs.
-   Write the directory manifest struct and recursive walker.
-   Get **one file** through vectorize -> reverse index -> aggregate tree -> binary tree -> inverse pipeline.
-   Verify exact equality for a text file **and** arbitrary binary bytes.
-   Extend to **two files**, stable IDs, and a reversible tree merge/split.
-   Embed the manifest in a minimal `.cat` container and extract both files.
-   Add a bounded worker pool only after the serial path passes.
-   Record actual bytes-in, bytes-out, encode/decode durations, and peak memory.

## Deferred: separate CAAT project

-   Only once CAT has a stable, tested binary interface, specify CAAT's audio frame/container layout.
-   Test exact PCM/WAV round trips and selective audio access/streaming.
-   Add an audio decoding/playback backend appropriate to the Pi (e.g., ALSA).
-   Treat eSpeak music experiments as an optional, wonderfully cursed **synthesis mode**, not the lossless playback backend. :)

## Engineering invariants

1.  **Losslessness:** `decode(encode(bytes)) == bytes` for all supported inputs.
2.  **Self-containment:** One `.cat` archive includes every manifest and decoding dependency required by its declared feature set.
3.  **Determinism:** Same inputs/options yield a byte-identical archive (subject to explicitly controlled metadata).
4.  **Resource bounds:** Input file count must not imply unbounded parallelism or unbounded allocation.
5.  **Safe extraction:** Nothing in an archive may escape the chosen output directory.
6.  **Honest measurement:** A reversible representation is not necessarily compression; size wins must be established empirically.