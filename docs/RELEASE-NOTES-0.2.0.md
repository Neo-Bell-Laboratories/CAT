# CAT 0.2.0 development candidate — closeout

The agreed CAT hardening and validation work is complete for offline archiving
on the tested macOS ARM64 host and Raspberry Pi Zero 2 W running 64-bit Linux.
Mac/Pi binaries and the source bundle are in `../releases/`, with SHA-256 files.
The detailed validation record is `release-validation.json`.

Hosted CI execution remains deferred by the owner's explicit request; the
workflow is prepared locally. This closeout does not publish or tag a release.
Existing format, metadata, filesystem and recovery limits remain documented in
`FORMAT-v0.1.md` and the project README.

## Pi timing context

After the benchmark, the owner reported configuring a development environment
on the Pi over SSH during the work. That may have introduced CPU, memory and
storage contention. The saved timings are observations under shared use, not
an isolated performance baseline or a production throughput guarantee. The
later screenshot showing idle CPU does not establish load during the runs.

The owner accepts longer encode times on the Zero 2 W for offline use. No
additional performance optimization is required to close the agreed scope.
This timing context does not change the successful byte comparisons, hashes,
compatibility checks or recorded sanitizer outcomes.
