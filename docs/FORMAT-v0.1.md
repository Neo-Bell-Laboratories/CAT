# CAT v0.1 serial prototype contract

CAT is general-purpose and lossless for supported regular files and directory
trees. CAAT/audio is outside this implementation. The executable is `catc`,
avoiding the Unix `cat` name. This is an experimental schema-specific binary
aggregate tree, not a general XF value serializer.

## Input and metadata

One regular file or directory is accepted. Its basename is stored as the single
archive root. Children are inventoried depth-first in bytewise filename order;
IDs are consecutive entry indices, independent of scheduling. Empty directories
and zero-byte files are retained. Paths are POSIX relative byte strings; NUL,
absolute names, empty components, `.` and `..` are rejected. Unicode and invalid
UTF-8 filename bytes need no text conversion. Backslashes are ordinary POSIX
filename characters. Root basenames `.`/`..` and `/` are not accepted.

Metadata preserved: path bytes, regular-file/directory type, original file byte
count, and permission bits 0777. Ownership, ACLs, extended attributes/resource
forks, birth/access/modification timestamps, setuid/setgid/sticky bits, sparse
allocation, and hard-link relationships are not preserved. Hard-linked regular
files are archived independently. Symlinks, sockets, devices, and FIFOs are
rejected, not followed or skipped. Explicitly supplied input ancestor paths use
normal OS path resolution; traversal within the selected root uses verified
non-following directory descriptors.

Files are opened without following links and fstat is checked against inventory,
then size, device/inode, mode, mtime and ctime are checked after reading. A change
fails encoding. Directory state is also checked before/after traversal. This is
not a filesystem snapshot; a file may change after its own ingestion completes.

## Reversible transform

Files are split into canonical blocks of 4096 bytes, except the final shorter
block. The C/XF adapter supplies an array of integers 0..255 to the embedded
`lib/Table.xf`:

```
bytes -> table rows {offset, byte}
      -> core.ds.agg(rows, "byte", "offset")
      -> {length, buckets: byte value -> ordered offsets}
      -> binary tree with runs of consecutive positions
```

Decode reconstructs the XF aggregate map, runs `cat_tree_to_table`, then
`cat_table_to_bytes`. C validates the tree before passing it to XF. All positions
must be in range, unique, and cover the block exactly. File ID, block order and
manifest size retain file boundaries. The merged root is the ordered sequence of
file-ID namespaces described by the manifest; there is no lossy cross-file join.
Merge/split is represented by manifest payload lengths and concatenation.

If tree bytes are not smaller than raw block bytes, the identity block encoding
is selected. Raw blocks restore bytes directly; the XF inverse is used for tree
blocks. Every block is transformed on encode before making that selection.
Repeated positions are run encoded, but repeated arbitrary strings and duplicate
files are not yet dictionary encoded or deduplicated. LambdaScript is statically
linked and its native bridge is smoke-tested; it has no artificial role in the
byte codec at this stage.

## Binary layout

All fixed-width integers are unsigned, big endian. No native structs are written.

| Header offset | Width | Meaning |
| --- | --- | --- |
| 0 | 8 | `43 41 54 00 01 00 00 00` (magic + version) |
| 8 | 4 | Entry count |
| 12 | 4 | Reserved feature flags, zero |
| 16 | 8 | Manifest byte length |
| 24 | 8 | Payload byte length |

The 32-byte header is followed by the manifest, payload, and a 32-byte SHA-256
of the entire preceding archive. No trailing bytes are allowed. SHA-256 detects
corruption; it does not authenticate the sender.

Each manifest entry contains a 64-byte record immediately followed by its raw
path bytes:

| Record offset | Width | Meaning |
| --- | --- | --- |
| 0 | 4 | Stable entry/file ID |
| 4 | 1 | Type: 1 directory, 2 regular file |
| 5 | 1 | Payload scheme: 0 directory, 1 block sequence |
| 6 | 2 | Permission bits, maximum 0777 |
| 8 | 4 | Path byte length |
| 12 | 4 | Reserved, zero |
| 16 | 8 | Original file length, zero for directory |
| 24 | 8 | File payload length, zero for directory |
| 32 | 32 | SHA-256 of original bytes; all zero for directory |

Parents must precede descendants; duplicate paths and multiple roots are invalid.
Payloads occur in manifest order. A file payload is a sequence of block frames:
codec byte (0 identity, 1 tree), original block length u32, encoded length u32,
then encoded bytes. Empty files have no blocks. Identity encoded length equals
original length. Tree encoded length must be strictly smaller than the original.

A binary tree block uses canonical unsigned LEB128 for integer fields:

```
original block length
bucket count
for each nonempty bucket in increasing byte-value order:
    byte value (one raw byte)
    run count
    for each run in increasing position order:
        gap from previous run end (initial end = 0)
        run length
```

Run lengths are positive. Gaps after the first run must be positive (adjacent
runs would be a noncanonical split). Values and positions must remain unique;
all original positions must be covered exactly. Varints permit at most three
bytes and values at most 4096, with overlong representations rejected. Bucket
counts are additionally capped at 256. Tree shape has fixed depth.

## Optional outer gzip encoding

With `-g` / `--gzip`, the complete CAT byte stream described above, including its
SHA-256 trailer, is wrapped in one standard gzip member. The CAT v0.1 inner schema
is unchanged. Encoding uses zlib level 9 and a header with time zero, no filename
or comment, and OS marker 255. Output is deterministic for the same inner archive
and zlib implementation; matching compressed bytes across different zlib versions
is not guaranteed. Original and wrapped archives are both accepted by magic-byte
auto-detection; filename extension is advisory.

The gzip stream is inflated incrementally to a private disk spool, using an
independent configurable output-byte budget. gzip CRC and length checks must
pass, all input must be consumed, and concatenated members or trailing bytes are
rejected. Normal CAT validation then runs before extraction staging is created.
The gzip layer uses the system zlib library, which is not instrumented as part
of CAT/XF's sanitizer rebuild. Runtime does not invoke the gzip command.

## Resource and extraction rules

Default byte budgets: 64 GB (64,000,000,000 bytes) total original input, 64 GiB
stored archive, 64 GiB inflated archive, and 192 GiB live logical temporary bytes. CLI options
`--max-bytes`, `--max-archive-bytes`, and `--max-temp-bytes` override these with
positive decimal byte counts. Limits are not preallocations. Source inode and
archive offsets use 64-bit file APIs. Archive inputs must be regular files;
nonblocking/no-follow opens and stat checks reject special-file namespace races
before reading. Metadata caps remain 4096 entries, depth 64,
path length below 4096 bytes and 2 MiB manifest. These policy changes do not alter
the v0.1 byte layout; older decoders may reject larger archives under their limits.

One 4096-byte block enters XF at a time. SHA-256 and gzip operate incrementally.
File payloads, archive bytes and decoded content use anonymous disk spools. Read
and write buffers are bounded; resident allocations depend on the bounded
manifest and XF block representations, not the total input length. There is no
hard RSS reservation. Inspect/verify do not retain decoded content. Temporary
logical-byte accounting covers scratch spools and decoded extraction staging;
filesystem allocation/metadata overhead is additional. `TMPDIR` selects scratch
storage. No workers or `--jobs` option are implemented.

Header, digest, manifest, paths, block bounds, tree structure and file hashes are
validated before extraction staging begins. Duplicate/missing parents and
impossible file/block length claims are rejected before decoding. Paths in
inspect output are quoted and byte-escaped; terminal controls are never emitted
literally. SHA-256 detects corruption, not sender authenticity.

Output must not exist. Extraction creates a private sibling staging directory,
uses dirfd-relative non-following opens and exclusive file creation, applies and
checks file modes, then applies directory modes last. File and directory syncs
precede publication. An inability to preserve requested modes fails extraction;
`--no-permissions` explicitly opts out on decode, leaving newly created private
files/directories instead. Target filesystem name restrictions/case collisions
also fail rather than silently merge entries. Ownership, timestamps, extended
attributes, ACLs and semantic AppleDouble metadata are not preserved.

Encoding validates the serialized CAT before staging output. Atomic no-replace
publication is preferred (exclusive rename, or an exclusive hard link for files
on compatible POSIX hosts). If unsupported, normal mode uses a portable fallback:
exclusive-create the archive destination, write and sync the complete body with
invalid magic, then write/sync the real magic. The directory fallback reserves a
new empty destination before moving the completed tree into it. Existing paths
are refused. `--require-atomic` disallows these non-atomic fallback paths. Output
parent directories should be controlled by the caller; this is not protection
against another process with the same credentials modifying the output namespace.

SIGINT/SIGTERM request cancellation; regular error paths close anonymous scratch
and clean only owned staging. SIGKILL, power loss or cleanup I/O failures can leave
staging/invalid outputs, and portable directory publication can leave an empty
reservation. Parent directory fsync is attempted after publication. Unsupported
directory fsync emits a warning; no universal crash-durability guarantee is made.
Cancellation or sync failure after a completed publish retains the valid output
and explicitly reports that it was published. A caller must check an existing
output before retrying. No source files are modified.

Exit codes: 0 success, 1 operation/validation failure, 2 CLI usage error, 130 for
SIGINT cancellation and 143 for SIGTERM cancellation. Statistics go to stderr;
inspect entries go to stdout. Ratio is actual stored archive bytes divided by
original file bytes, or n/a for empty input. `cat_bytes` reports the unwrapped CAT
length, and `gzip=on/off` identifies the detected encoding. Timing covers the
command, including encode validation and compression; RSS covers the process.

## Validation scope and compatibility

Saved pre-streaming v0.1 plain/gzip archives and their content/mode/digest manifest
are under `tests/golden/`. They must remain decodable; a layout change requires a
new format version and new fixtures, not silent rewriting of old archives.

Tests include independent SHA-256 vectors and a separately generated raw archive,
25 XF transform fixtures with truncation checks, 172 CLI checks, staged-failure
injection, cancellation before/after publication, disk/permission/sync failures,
source mutation, gzip interoperability/bounds and malformed archive paths/nodes.
Coverage-guided archive fuzzing repairs outer hashes to exercise deep validators;
a separate tree target covers transform inversion. These campaigns are evidence,
not proof that malformed inputs cannot expose other defects. RSS observations do
not replace LeakSanitizer. TSan's coverage remains serial until workers exist.

Current platform/test outcomes, compiler limitations and pending gates are in
`release-validation.json`. Native Linux/Pi runs, cross-platform exchange, CI
execution and dependency provenance must be evaluated independently. No public
production release is implied by the existence of a development binary/package.
