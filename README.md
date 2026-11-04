# CAT — Compressed Aggregate Tree

CAT is a serial C/XF file and directory archiver with repeatable path exclusions
and an optional gzip stage.
XF and its vendored LambdaScript runtime are statically linked; ByteLang is
excluded. Tool version is `0.2.0-dev`; new archives use CAT format v0.6 and
readers retain compatibility with v0.1 through v0.5.
This is a development build with explicit release gates, not a production label.

From `CAT/`:

```sh
make
./bin/catc -eg /path/to/input archive.cat.gz
./bin/catc -e --exclude build -x '*.o' /path/to/input archive.cat
./bin/catc -v archive.cat.gz
./bin/catc -i archive.cat.gz
./bin/catc -d archive.cat.gz restored
./bin/catc --version
```

The archive destination and extraction directory must not exist. Extraction
creates `restored/<original-basename>`. The existing `encode`, `decode`, `inspect`
and `verify` commands and their long flags still work. `-eg` and `-ge` mean encode
with gzip; decoding detects gzip from contents, independent of filename extension.
`--` ends option parsing. Inspect escapes filenames so terminal control bytes and
invalid UTF-8 cannot emit terminal commands.
`--exclude PATTERN` and `-x PATTERN` can be repeated when encoding. Patterns are
matched against paths relative to the input root; patterns without `/` also match
basenames at any depth. Excluding a directory prunes its contents, and the input
root remains in the archive.

## Streaming and resource controls

File data, SHA-256, archive validation and gzip are processed in chunks. At most
one 8192-byte block enters XF at a time. Payloads and validated decoded bytes are
spooled to anonymous temporary files, not held as whole-file memory buffers.
Inspect and verify validate bytes without retaining decoded content. `TMPDIR`
selects scratch storage. Available disk space, not just RAM, matters.

Defaults are limits, not preallocations:

| Resource | Default |
| --- | --- |
| Original file bytes, total | 64 GiB |
| Stored or inflated archive bytes | 64 GiB each |
| Temporary disk logical bytes | 192 GiB |
| Manifest | 2 MiB |
| Entries | 4096 |
| Path length | Less than 4096 bytes |
| Depth including root | 64 |

Override byte budgets with decimal counts, for example:

```sh
./bin/catc -eg --max-bytes 1073741824 --max-archive-bytes 2147483648 \
  --max-temp-bytes 4294967296 input output.cat.gz
```

The temporary budget accounts for live scratch spools and extraction staging
content. Output staging is also bounded by archive size. These are logical-byte
budgets; filesystem allocation overhead and allocator/RSS overhead are separate.
Use smaller budgets on a constrained Pi or for untrusted archives. Encoding does
not create a filesystem snapshot: inputs are checked for changes during their
individual ingestion, not frozen globally.

The saved 24 MiB streaming test round-tripped plain and gzip archives using cmp
and SHA-256, with approximately 9 MiB encode RSS and 2 MiB decode RSS on the Mac.
See [docs/streaming-macos.json](docs/streaming-macos.json).
The Pi also round-tripped 18 MiB in plain/gzip modes at about 15 MiB reported RSS.
Encoding took roughly six minutes: throughput is a remaining practical limitation
for large/interactive Pi workloads. See `docs/streaming-pi.json` and
`docs/benchmark-pi.json` (synthetic, single-run observations).

## Preservation and failure behavior

The v0.1 contract preserves regular-file bytes, relative path bytes, empty
directories, file lengths, and permission bits 0777. Symlinks and special files
are rejected. Ownership, timestamps, ACLs, extended attributes/resource forks,
sparse allocation and hard-link relationships are not preserved. Existing
AppleDouble `._*` files are treated as ordinary inputs; macOS/filesystems/editors
can generate or modify sidecars separately. There is no semantic AppleDouble
metadata preservation guarantee. Target-filesystem naming/permission restrictions
can cause extraction to fail safely rather than silently merge names.
Mode preservation is checked after chmod; use `--no-permissions` on decode only
when you intentionally want content without original permission bits.

The full archive and file hashes are checked before extraction staging starts.
Files and directories are written under a private staging root and synced before
publication. Errors, SIGINT and SIGTERM clean up owned staging on a best-effort
basis. Scratch files are unlinked as soon as created, so closing/killing a process
reclaims them. SIGKILL, power loss, filesystem faults or external mutations can
still leave output staging/reservations; no crash-proof filesystem guarantee is
claimed.

Atomic no-replace publication is preferred. For mounted filesystems that do not
support it, the portable file fallback exclusively creates the destination, writes
and syncs its body before its magic, and refuses existing paths. The directory
fallback reserves a new empty directory before publishing. Interrupted fallback
publication can leave an invalid file or empty directory. Add `--require-atomic`
to refuse those filesystems. Directory fsync is attempted; unsupported directory
sync is reported as a warning. SHA-256 and gzip CRC detect corruption, not sender
authenticity or malicious replacement of an entire valid archive.

## Build and validation

Requires a C11 GCC/Clang compiler, make, Python 3.9+, and zlib development headers
and library (`-lz`). Runtime does not invoke Python, external gzip or XF binaries.
System libraries including zlib remain dynamically linked. The default compiler is the platform `cc`; choose another
with `make CC=/path/to/compiler`; keep build directories separate when changing compilers.
The Pi's GCC 12 works with this source; its Clang 14 crashed compiling XF.

```sh
make test                  # smoke, transform, SHA, CLI, failure and golden checks
make asan                  # separate ASan + UBSan build
make tsan                  # separate TSan build; serial coverage only
make CC=cc lsan            # full suite on supported Linux hosts
make CC=cc MODE=lsan leak-test # persistent/focused native leak suite on the Pi
make streaming-test        # 24 MiB plain/gzip round trips and RSS check
make packaging-test        # checksums, reproducible source bundle, fresh build
make fuzz FUZZ_SECONDS=120 # libFuzzer + ASan/UBSan, archive and tree targets
```

Fault injection is compiled only into the test executable; its environment
variables have no effect on the shipped binary. Fuzzing repairs outer archive
hashes to reach deeper validators, retains logs/reproducers, and uses bounded
ASan quarantine. On this Mac, Homebrew LLVM supplies libFuzzer because Apple's
compiler lacks its runtime. `FUZZ_CC` and `FUZZ_BUILD` are configurable. The initial
512 MiB fuzz RSS-cap event was investigated by 1,000 replays; subsequent campaigns
with a smaller sanitizer quarantine stayed below the cap. Native Linux leak
checking is recorded separately, not inferred from those RSS observations.

Saved pre-streaming plain/gzip archives in `tests/golden/` are permanent
compatibility fixtures. See [docs/release-validation.json](docs/release-validation.json)
for recorded outcomes and remaining gates. The GitHub workflow in the workspace's
`.github/workflows/cat.yml` prepares Linux x64/arm64 and macOS test jobs. It must
actually run in a repository before its CI gate is passed.

To validate an explicitly selected remote host, without changing host-key trust
or installing packages:

```sh
python3 tools/validate_remote.py user@host --cc cc --jobs 1
```

## Packaging and licensing

```sh
make package source-package   # private development bundles plus SHA-256 manifests
make release-check            # fails if required evidence/licenses are missing
make install PREFIX=/chosen/prefix
```

Source bundles have deterministic member order, timestamps and file hashes;
binary bundles record platform, version and dynamic dependencies. Packages are
development artifacts until release gates pass; no upload, tag or public
publication is automatic. The same source/dependencies/toolchain are needed to
reproduce a binary; byte identity across different toolchains is not promised.

CAT first-party code is MIT licensed. Dependency notices are in THIRD_PARTY.md
and `licenses/`; the project owner confirmed XF/LambdaScript first-party ownership and MIT
licensing. Bundled third-party code retains its own terms.

## Codec and measurements

`lib/Table.xf` implements bytes -> table -> reverse byte index via `core.ds.agg`,
then aggregate tree -> table -> devectorized bytes. C validates and serializes byte
buckets as runs of original positions. A raw fallback prevents tree expansion
within a block; framing can still expand an archive. Optional gzip compresses the
complete serialized CAT, preserving inner SHA-256 checks. It is explicitly
selected even if it expands the result. Gzip output is deterministic for the same
input/options and zlib implementation, not guaranteed identical across zlib
versions. Concatenated gzip members and trailing bytes are rejected.

The original no-gzip synthetic benchmark is in `docs/benchmark-macos.json`; it
must not be interpreted as a gzip-enabled comparison. Compare identical file
sets, actual summed byte lengths, metadata policy, runtime and memory before
claiming a compression advantage. Workers and deduplication remain future work.

The C adapter currently uses confirmed XF internal typed APIs and a fresh driver
per block; it must be rebuilt with matching XF sources. LambdaScript's native
bridge is linked/smoke-tested but does not perform the current byte codec.
[docs/FORMAT-v0.1.md](docs/FORMAT-v0.1.md) is the on-disk specification.


## Block-size tuning experiment

The isolated 8 KiB prototype adds an exact C-side serialized-size estimate. It
skips XF when the aggregate tree cannot beat raw bytes, and uses 8 KiB blocks for
lower framing overhead. This is experimental format v0.2; v0.1 files remain
readable. See `benchmarks/block-sizes.json` for the same-directory comparison
across 8/16/32/64/128 KiB. The 32 KiB run did not improve over 8 KiB; 64 and 128
KiB used more memory, so 8 KiB is the current trial setting pending native Pi
measurements.


## Block-size tuning experiment

The active isolated trial uses 8 KiB blocks and an exact C-side serialized-size
estimate that skips XF when the aggregate tree cannot beat raw bytes. It writes
experimental format v0.2 and reads format v0.1 archives. The same-directory
comparison across 8/16/32/64/128 KiB is recorded in `benchmarks/block-sizes.json`.
The 32 KiB run did not improve over 8 KiB. Larger blocks compressed somewhat
better but raised peak memory sharply. Treat the results as host-specific until
measured natively on the Pi.
