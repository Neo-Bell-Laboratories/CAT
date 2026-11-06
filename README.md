# CATS — Compression Aggregate Tree System

CATS is a serial C/XF file and directory archiver with repeatable path exclusions
and an optional gzip stage.
XF and its vendored LambdaScript runtime are statically linked; ByteLang is
excluded. The canonical CLI is `cats`; `catc` remains a compatibility alias for
existing integrations. Tool version is `0.4.0`. Archives use the CAT wire format: v0.7 by
default, or compact v0.8 with `-c`. Readers support versions v0.1 through v0.8.
See `docs/release-validation.json` for platform validation and known limits.

From the CATS source directory:

```sh
make
./bin/cats -eg /path/to/input /path/to/other --output archive.cat.gz
./bin/cats -e --exclude build -x '*.o' /path/to/input --output archive.cat
./bin/cats -v archive.cat.gz
./bin/cats -i archive.cat.gz
./bin/cats -d archive.cat.gz restored
./bin/cats --version
```

The archive destination and extraction directory must not exist. Extraction
creates `restored/<original-basename>`. The existing `encode`, `decode`, `inspect`
and `verify` commands and their long flags still work. `-eg` and `-ge` mean encode
with gzip; decoding detects gzip from contents, independent of filename extension.
`-c` and `--compress` select CAT format v0.8, which stores each block’s original
and encoded lengths in two bytes instead of four. This saves four bytes per block;
`-e -c -g` applies compact framing before gzip. Use `-d -c` to extract a v0.8
archive; the CLI requires this explicit decode flag. Gzip is auto-detected and
removed before compact-frame decoding. Inspect and verify recognize both formats
from the archive header.
`--` ends option parsing. The Python GUI recognizes v0.7 and compact v0.8
archives from their headers. Inspect escapes filenames so terminal control bytes and
invalid UTF-8 cannot emit terminal commands.
Encoding accepts multiple files and directories. Each is archived under its
basename, and duplicate basenames are rejected. Use `-o FILE` or `--output FILE`
to name the archive explicitly when passing multiple inputs. The former
`INPUT OUTPUT` form remains supported for one input. CAT formats v0.7 and v0.8 support
multiple top-level entries; older CAT readers may not read these archives.
An extension-less output name gets `.cat`, or `.cat.gz` when `-g` is enabled.
Recognized `.cat` and `.cat.gz` suffixes are adjusted to match the `-g` setting;
other explicit suffixes are preserved.

`--exclude PATTERN` and `-x PATTERN` can be repeated when encoding. Patterns are
matched against paths relative to each input root. `*`, `?`, and bracket patterns
do not cross `/` and can match leading dots; patterns without `/` also match
basenames at any depth. There is no special `**` recursive-wildcard syntax:
excluding a directory prunes its contents, so a basename pattern such as `build`
excludes matching directories at any depth. The input root remains in the archive.
Encoding reports how many paths matched and warns when none did. Exclusion
patterns are not stored in the archive, so keep the command or patterns with the
archive if you need an audit trail.

## Streaming and resource controls

File data, SHA-256, archive validation and gzip are processed in chunks.
Aggregate-tree encoding runs in native C. Decoding passes at most one 8192-byte
block through XF at a time. Payloads and validated decoded bytes are
spooled to anonymous temporary files, not held as whole-file memory buffers.
Inspect and verify validate bytes without retaining decoded content. `TMPDIR`
selects scratch storage. Available disk space, not just RAM, matters.

Defaults are limits, not preallocations:

| Resource | Default |
| --- | --- |
| Original file bytes, total | 64 GB (64,000,000,000 bytes) |
| Stored or inflated archive bytes | 64 GiB each |
| Temporary disk logical bytes | 192 GiB |
| Manifest | 2 MiB |
| Entries | 4096 |
| Regular files | 2000 |
| Path length | Less than 4096 bytes |
| Depth including root | 64 |

Override byte budgets with decimal counts, for example:

```sh
./bin/cats -eg --max-bytes 1073741824 --max-archive-bytes 2147483648 \
  --max-temp-bytes 4294967296 input output.cat.gz
```

`--max-bytes` can lower the 64 GB total-input ceiling; it cannot raise it.

The temporary budget accounts for live scratch spools and extraction staging
content. Output staging is also bounded by archive size. These are logical-byte
budgets; filesystem allocation overhead and allocator/RSS overhead are separate.
Use smaller budgets on a constrained Pi or for untrusted archives. Encoding does
not create a filesystem snapshot: inputs are checked for changes during their
individual ingestion, not frozen globally.

The current-source 24 MiB seeded pseudo-random streaming test round-tripped
plain and gzip archives with `cmp` and SHA-256. On macOS, plain encode/decode
measured 0.28/0.20 seconds and gzip encode/decode 0.56/0.20 seconds, with peak
RSS below 3 MiB. On the Pi Zero 2 W, plain encode/decode measured 8.08/7.69
seconds and gzip encode/decode 13.07/7.54 seconds, with peak RSS about 15.7 MB (15.0 MiB).
The archive expanded this incompressible input by 0.11% without gzip and 0.14%
with gzip. These are single-run measurements for this seeded corpus, not broad
throughput guarantees. See [docs/streaming-macos.json](docs/streaming-macos.json)
and [docs/streaming-pi.json](docs/streaming-pi.json), which record the tested
source hash. `docs/benchmark-pi.json` contains separate older synthetic-corpus
measurements and is not directly comparable.

## Preservation and failure behavior

The archive contract preserves regular-file bytes, relative path bytes, empty
directories, file lengths, and permission bits 0777. Symlinks and special files
are rejected. Ownership, timestamps, ACLs, extended attributes/resource forks,
sparse allocation and hard-link relationships are not preserved. Existing
AppleDouble `._*` files are treated as ordinary inputs; macOS/filesystems/editors
can generate or modify sidecars separately. There is no semantic AppleDouble
metadata preservation guarantee. Target-filesystem naming/permission restrictions
can cause extraction to fail safely rather than silently merge names.
Mode preservation is checked after chmod; use `--no-permissions` on decode only
when you intentionally want content without original permission bits.
The Python GUI extractor restores those POSIX mode bits on macOS and Linux; on
Windows it preserves file contents and paths but does not apply POSIX modes.

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
make macos-app             # build the CATS-branded CAT.app bundle
make macos-app-test        # validate CATS GUI, plist and icons
make gui                   # start the cross-platform archive GUI
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

`make macos-app` builds a `CAT.app` bundle branded CATS with a native Cocoa interface, a
Finder document icon, and `.cat` document registration. Double-clicking a
`.cat` file opens its inspector. The Python GUI is designed to run on Linux and
Windows with Tk installed. Linux GUI inspect/extract passed under Xvfb on the
Pi; Windows GUI runtime validation remains deferred. Extraction validates the
archive before writing and refuses to overwrite an existing destination.

On Linux, `sh packaging/linux/install-gui.sh /usr/local` installs the Python GUI,
desktop entry, MIME declaration, icons, and license notices; `DESTDIR` can stage
the install. Select “CATS Archive Extractor” as the `application/x-cat` handler in
the desktop environment. On Windows, `make windows-gui-package` creates a
standalone ZIP containing the GUI, icon, installer, and license notices. Extract
it and run this from the extracted folder to install for the current user and
register `.cat` and `.cat.gz`:

```powershell
powershell -ExecutionPolicy Bypass -File .\packaging\windows\install-gui.ps1
```

Python 3 with Tk is required on both systems. Windows may
require selecting CATS Archive under Settings > Apps > Default apps if its existing
per-user file association takes precedence. The installer also finds Python via
the `py` launcher when `python.exe` is not on `PATH`.

```sh
make package source-package windows-gui-package  # development bundles plus SHA-256 manifests
make release-check                              # fails if required evidence/licenses are missing
make install PREFIX=/chosen/prefix
```

Peer projects use the shared `cats` command rather than copying CAT object
files. See [CLI integration](docs/CLI-INTEGRATION.md) for the seven-project
inventory, install procedure, and dependency check.

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
claiming a compression advantage. Parallel workers, deduplication, and
Zstandard integration are deferred to the [0.5 roadmap](docs/ROADMAP-v0.5.md).

The C adapter currently uses confirmed XF internal typed APIs and one driver
session per archive. A one-block cache reuses the previous transform for
identical consecutive blocks; the archive bytes remain unchanged. It must be
rebuilt with matching XF sources. LambdaScript's native bridge is
linked/smoke-tested but does not perform the current byte codec.
[docs/FORMAT-v0.7.md](docs/FORMAT-v0.7.md) specifies default archives and
[docs/FORMAT-v0.8.md](docs/FORMAT-v0.8.md) specifies compact archives;
[docs/FORMAT-v0.1.md](docs/FORMAT-v0.1.md) documents the original version.
