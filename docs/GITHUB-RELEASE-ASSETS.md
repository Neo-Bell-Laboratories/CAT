# GitHub release assets

Run `make github-release-assets` after the platform CLI binaries are present in
`bin/cats`, `bin/linux-x64/cats`, and `bin/linux-aarch64/cats`. The target builds
the current macOS app, source archive, and Linux/Windows GUI packages, then
stages the upload files under `bin/github-release/CATS-0.4.0/`.

The folder contains source, macOS ARM64, Linux x86_64, Linux AArch64, and GUI
assets, with `ASSETS.json`, `RELEASE-STATUS.txt`, and `SHA256SUMS`. The Arch
x86_64 application check passed with the staged binary hash verified and 281
checks reported. Native Windows CLI runtime validation is deferred by user
preference; the Windows x64 cross-build and Windows GUI runtime passed. Remote
matrix automation is scheduled for 0.5. The MinGW-w64 cross-build links CAT,
XF, LambdaScript, zlib, and PCRE2, and CAT has a Windows filesystem
implementation for safe traversal, extraction, and publication. Run
`python3 tools/release_check.py` before staging production assets.

The Linux x86_64 CLI is built with the glibc 2.17 cross sysroot and the same
artifact passed all 201 integration checks on Ubuntu 26.04 and Debian 13. The
Linux AArch64 CLI was built and tested natively on the Pi Zero 2 W. The Linux
GUI package is architecture-independent Python/Tk source; the Windows GUI ZIP
is likewise a Python/Tk package.

The production version is `0.4.0`; regenerate the release assets from that
version before tagging the commit `v0.4.0`.
