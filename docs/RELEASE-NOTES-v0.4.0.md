# CATS 0.4.0 release notes

Release notes for the production v0.4.0 release.

## Highlights

- Renames the command-line executable to `cats`; `catc` remains available as a compatibility alias.
- Adds compact CAT v0.8 framing with `-c` / `--compress`. The default remains the compatible v0.7 format. Gzip remains optional with `-g` and is applied after compact framing.
- Supports encoding multiple files and directories into one archive, explicit output names with `-o` / `--output`, and repeatable path exclusions with `-x` / `--exclude`.
- Adds streaming encode, decode, inspect, verify, and gzip paths with configurable archive and temporary-storage budgets. Default limits include 64,000,000,000 input bytes and 2,000 regular files.
- Provides GUI archive inspection and extraction for macOS, Linux, and Windows.
- Ships statically linked XF and LambdaScript integration, public C support headers, and pkg-config metadata for downstream C projects.

## Compatibility and preservation

CATS reads CAT formats v0.1 through v0.8. It preserves file bytes, relative paths, empty directories, and supported 0777 permission bits. Symlinks and special files are rejected. Ownership, timestamps, ACLs, extended attributes, resource forks, sparse allocation, and hard-link relationships are not preserved. Compact v0.8 extraction requires `-c` / `--compress` on the CLI; the GUI detects the format from its archive header.

## Release validation

See `docs/release-validation.json` and the per-platform evidence files for validated targets and known platform-specific limitations. Native Windows CLI runtime testing is deferred by user preference; the Windows x64 cross-build and GUI runtime are validated. Optional compression, worker, and remote matrix automation work is scheduled for 0.5.
