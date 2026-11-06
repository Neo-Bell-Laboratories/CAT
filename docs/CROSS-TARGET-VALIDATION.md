# Cross-target validation with NBL

NBL's assembler and linker provide an additional cross-target object and
executable-format check for CAT's release process. They do not currently build
the CAT application itself: CAT is C code and depends on XF, LambdaScript,
zlib, pthreads, POSIX filesystem operations, and platform startup/runtime
libraries. NBL's native linker implements a freestanding native core subset;
it does not provide a C compiler, a libc/sysroot, or CAT's runtime dependencies.

Run the NBL checks from the NBL project root:

```sh
python3 tests/check_native_tools.py
python3 tests/check_native_tools.py --baseline
python3 tests/check_cli_toolchain.py
```

The current native matrix covers 16 OS/CPU target tuples: macOS ARM64;
Windows ARM64, x86, and x64; Linux ARM64, x86, and x64; and ARM64, x86, and x64
for FreeBSD, OpenBSD, and NetBSD. UXI-16 is a separate non-native target. The
Linux assembler/linker also test seven distro metadata profiles for each Linux
CPU target. These profile tags do not imply that distro libraries or a matching
runtime were linked.

The current NBL native-tool check completed with 16 target rows, 182 negative
cases, and 19 independent LLVM object/encoding oracles. It executes the macOS
ARM64 smoke executable on the host; other emitted formats are inspected and
linked but are not thereby proven to run on every target OS. Use matching-OS CAT
builds and runtime tests for CAT release claims.


## CAT application targets

The native C application has current-source release and test evidence on macOS
ARM64, Ubuntu x86_64, Debian 13 x86_64, Arch x86_64, and Raspberry Pi Linux
ARM64. On Arch, the release x86_64 binary's SHA-256 was verified and the user
reported 281 integration checks passed; see
`docs/arch-x64-manual-validation.json`. These are native runtime checks on
matching environments; they are not all emitted by a cross-target `make`. The default `make` now builds the native CLI and a
host-specific GUI artifact: CAT.app on macOS, a self-contained Linux GUI package
on Linux, or the Windows GUI package on Windows. The Windows GUI package can be
built on other hosts as a source bundle; its Windows 11 runtime, installer,
Start menu shortcut and `.cat` association now pass. Windows `.cat.gz` files are
opened through the GUI Browse button because Explorer dispatches the compound
suffix through `.gz`. Debian 13 x86_64 also passed the portable-reader fixture
suite and Tk inspect/extract smoke test under Xvfb; see
`docs/debian-gui-validation.json`.

A Linux x86_64 cross-build has now been produced on the macOS ARM64 host using
Homebrew's `x86_64-unknown-linux-gnu-gcc`, its glibc 2.17 sysroot, and a separately
built static zlib 1.4. The binary ran on Ubuntu 26.04 x86_64, resolved its runtime
libraries, and passed all 201 `tests/integration.py` checks. The local and remote
binary SHA-256 values matched. See `docs/remote-alienware-x64-validation.json`.

The `linux-x64-cross` Make target now reproduces the Linux x86_64 CLI build when
given a matching compiler, archiver, and static zlib root. For example:

```sh
make linux-x64-cross \
  LINUX_X64_CC=/path/to/x86_64-linux-gnu-gcc \
  LINUX_X64_AR=/path/to/x86_64-linux-gnu-ar \
  LINUX_X64_ZLIB_ROOT=/path/to/linux-x86_64-zlib
```

It emits `bin/linux-x64/cats`; the produced artifact passed all 201 integration
checks on Ubuntu 26.04 x86_64 and Debian 13 x86_64, using the identical SHA-256
artifact in each runtime. Required application target checks are complete for
macOS ARM64, Linux x86_64 (Ubuntu, Debian, and Arch), Linux AArch64, and the
Windows x86_64 cross-build. Native Windows CLI runtime testing is deferred by
user preference; the Windows GUI runtime passes. Debian 13 x86_64 passes the
complete `make test` target; see `docs/debian-native-build-current-source.json`.
The manual Arch x86_64 application check is recorded in
`docs/arch-x64-manual-validation.json`. Remote-host matrix orchestration is
deferred to the 0.5 roadmap. CAT has a reproducible `windows-x64-cross` target using Homebrew's
MinGW-w64 compiler and target-built static zlib/PCRE2 libraries. It produces a
static PE x86_64 CLI. CAT's Win32 filesystem layer uses handle-relative opens
and directory enumeration, rejects reparse points, and publishes without
replacing existing destinations. Native Windows CLI runtime testing is deferred
by user preference and is scheduled as a 0.5 follow-up. NBL's Windows adapters assemble/link the
documented native core subset; they do not compile the CAT C application.
Windows GUI runtime validation passes separately. See
`docs/release-validation.json` for the current gate.

Homebrew supplies the MinGW-w64 compiler, linker, CRT, and Windows libraries used
for this cross-build. LambdaScript, zlib 1.4, PCRE2 10.49's POSIX compatibility
library, the full XF static library, and CAT compile and link as PE x86_64 with
MinGW-w64. XF's new
`XF_USE_PCRE2_POSIX` shim and Windows glob implementation were used for a static
XF smoke executable; its imports are limited to Windows system CRT/kernel DLLs.
The XF smoke executable and CAT CLI have not yet been run on Windows. CAT's
target-specific filesystem implementation and Make target now cross-build, but
the Windows CLI runtime smoke and automated remote application matrix are
deferred follow-ups, independent of the already validated Windows GUI package.
