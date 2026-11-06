# CAT archive format v0.7

This document specifies the archive written by CATS 0.4.0. Integers in the
archive are unsigned big-endian values. The format stores regular files and
directories, their relative path bytes, and permission bits 0777. It does not
store timestamps, ownership, ACLs, extended attributes, symlinks, special files,
sparse allocation, or hard-link relationships. SHA-256 detects accidental
corruption; it does not authenticate an archive's source.

## Header and archive checksum

The 32-byte header is followed by the manifest, payload, and a 32-byte SHA-256
digest over all preceding archive bytes. No trailing bytes are permitted.

| Offset | Width | Value |
| --- | --- | --- |
| 0 | 8 | `43 41 54 00 07 00 00 00` |
| 8 | 4 | Manifest entry count |
| 12 | 4 | Reserved flags; zero |
| 16 | 8 | Manifest length in bytes |
| 24 | 8 | Payload length in bytes |

The entry count is 1 through 4096, of which at most 2000 may be regular files.
Manifest length is at most 2 MiB. Total original file bytes are capped at
64,000,000,000 bytes. Payload and temporary byte limits are controlled by the
reader's resource budgets.

## Manifest

Each entry has a 64-byte fixed record followed by its path bytes:

| Offset | Width | Meaning |
| --- | --- | --- |
| 0 | 4 | Entry ID, equal to its zero-based manifest index |
| 4 | 1 | Type: 1 directory, 2 regular file |
| 5 | 1 | Payload scheme: 0 directory, 1 block sequence |
| 6 | 2 | Permission bits, at most 0777 |
| 8 | 4 | Path byte length |
| 12 | 4 | Reserved; zero |
| 16 | 8 | Original file length; zero for directories |
| 24 | 8 | Encoded file payload length; zero for directories |
| 32 | 32 | SHA-256 of original file bytes; zero for directories |

Paths are non-empty relative byte strings shorter than 4096 bytes. NUL, absolute
paths, empty components, `.` and `..` components, and paths deeper than 64
components are invalid. The manifest is in deterministic traversal order;
parents precede descendants. Duplicate paths are invalid. Version 0.7 permits
multiple top-level entries, allowing an encode operation to include several
files or directory roots. Earlier versions permit only one root.

## File payloads

File payloads occur in manifest order. Each file is split into blocks of at most
8192 original bytes. Every block starts with a 9-byte frame:

| Offset | Width | Meaning |
| --- | --- | --- |
| 0 | 1 | Codec: 0 identity, 1 aggregate-tree encoding |
| 1 | 4 | Original block length |
| 5 | 4 | Encoded block length |

Codec 0 stores the original bytes and requires equal original and encoded
lengths. Codec 1 stores the validated CAT aggregate-tree representation and
requires the encoded length to be smaller than the original block. The decoder
requires blocks to cover exactly the declared file length. The per-file
SHA-256 is checked over reconstructed bytes.

The aggregate-tree representation and canonical integer encoding are described
in [FORMAT-v0.1.md](FORMAT-v0.1.md); those tree and manifest definitions remain
applicable to v0.7. The v0.7 changes are the version byte, 8192-byte maximum
block size, and support for multiple top-level roots.

## Optional gzip wrapper

`-g` wraps the complete CAT archive in one gzip member. The inner CAT header and
both archive/file SHA-256 checks remain present. Readers detect gzip by its
signature rather than the filename. Concatenated gzip members and trailing
bytes are rejected. Gzip is an optional transport wrapper and is not part of the
CAT archive version itself.
