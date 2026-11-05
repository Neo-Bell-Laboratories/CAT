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
