# CATS 0.5 roadmap

This list holds non-urgent work deferred from the 0.4 production release. None
of these items is a 0.4 release gate.

## Compression and throughput

- Evaluate optional Zstandard support, including a versioned codec marker,
  cross-platform decoder availability, compatibility behavior, and representative
  size/speed benchmarks. The current Zstandard measurements are experiments;
  CATS does not read or write Zstandard-wrapped archives.
- Design and validate XF-backed parallel workers for independent manifest files
  or blocks. Keep output deterministic and lossless, and add concurrent TSan
  coverage before enabling workers.
- Evaluate content deduplication across repeated blocks/files with explicit
  format framing and integrity coverage.
- Continue compression/layout experiments only when they preserve exact
  restoration and improve measured representative workloads.

## Portability and integration

- Automate remote application matrix orchestration across the supported
  operating systems and architectures.
- Run the staged native Windows CLI smoke suite when convenient. The Windows
  x64 cross-build passed; native Windows CLI runtime validation is deferred by
  user preference and is not a 0.4 release gate.
- Expand downstream integration guidance and compatibility checks as dependent
  projects adopt the installed C API and CLI.

## Preservation and GUI follow-ups

- Consider optional preservation of timestamps, ownership, ACLs, extended
  attributes, resource forks, sparse allocation, and hard-link relationships.
  These are not currently preserved and require format, security, and
  cross-platform design before implementation.
- Continue GUI usability improvements after the current platform extraction
  workflows are released.
