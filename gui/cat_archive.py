"""Portable, lossless CAT archive validation and extraction for the GUI."""
from contextlib import contextmanager
import ctypes
import errno
from dataclasses import dataclass
import gzip
import hashlib
import os
from pathlib import Path
import shutil
import stat
import struct
import sys
import tempfile
import unicodedata
import zlib

MAX_ENTRIES = 4096
MAX_FILES = 2000
MAX_DEPTH = 64
MAX_PATH_BYTES = 4096
MAX_MANIFEST = 2 * 1024 * 1024
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024 * 1024
MAX_INPUT_BYTES = 64_000_000_000
HEADER_BYTES = 32
RECORD_BYTES = 64
BLOCK_MAX = {1: 4096, 2: 16384, 3: 65536, 4: 32768,
             5: 131072, 6: 8192, 7: 8192, 8: 8192}
ZERO_HASH = bytes(32)


class ArchiveError(Exception):
    """The archive is invalid, unsupported, or cannot be extracted safely."""


@dataclass
class Entry:
    path_bytes: bytes
    path: str
    kind: int
    mode: int
    size: int
    payload_size: int
    digest: bytes
    payload_offset: int


@dataclass
class ArchiveInfo:
    path: str
    version: int
    entries: list
    total_bytes: int
    gzipped: bool


def _read_exact(stream, count):
    chunks = []
    left = count
    while left:
        chunk = stream.read(left)
        if not chunk:
            raise ArchiveError('truncated archive')
        chunks.append(chunk)
        left -= len(chunk)
    return b''.join(chunks)


def _safe_path(raw):
    if not raw or len(raw) >= MAX_PATH_BYTES or raw.startswith(b'/') or b'\0' in raw:
        raise ArchiveError('archive contains an unsafe path')
    parts = raw.split(b'/')
    if len(parts) > MAX_DEPTH or any(part in (b'', b'.', b'..') for part in parts):
        raise ArchiveError('archive contains an unsafe path or excessive depth')
    try:
        display = raw.decode('utf-8')
    except UnicodeDecodeError:
        display = os.fsdecode(raw)
    return display


def _validate_windows_names(entries):
    if os.name != 'nt':
        return
    forbidden = set('<>:"|?*')
    reserved = {'CON', 'PRN', 'AUX', 'NUL'}
    reserved.update('COM%d' % n for n in range(1, 10))
    reserved.update('LPT%d' % n for n in range(1, 10))
    seen = set()
    for entry in entries:
        try:
            path = entry.path_bytes.decode('utf-8')
        except UnicodeDecodeError:
            raise ArchiveError('this archive has a filename Windows cannot represent')
        if '\\' in path:
            raise ArchiveError('this archive has a backslash filename Windows cannot restore safely')
        components = path.split('/')
        for component in components:
            stem = unicodedata.normalize('NFKC', component.split('.', 1)[0]).upper()
            if (not component or component.endswith((' ', '.')) or
                    any(ord(ch) < 32 or ch in forbidden for ch in component) or stem in reserved):
                raise ArchiveError('this archive has a filename Windows cannot restore safely')
        key = '/'.join(unicodedata.normalize('NFKC', c).casefold() for c in components)
        if key in seen:
            raise ArchiveError('archive paths collide on a case-insensitive filesystem')
        seen.add(key)
        entry.path = path


@contextmanager
def _inner_archive(path):
    source = open(path, 'rb')
    temporary = None
    try:
        source_size = os.fstat(source.fileno()).st_size
        if source_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError('stored archive exceeds the 64 GiB limit')
        signature = source.read(2)
        source.seek(0)
        if signature != b'\x1f\x8b':
            yield source, False
            return

        temporary = tempfile.TemporaryFile(mode='w+b')
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        output_size = 0
        while True:
            chunk = source.read(65536)
            if not chunk:
                break
            pending = chunk
            while pending:
                before = len(pending)
                capacity = MAX_ARCHIVE_BYTES - output_size + 1
                decoded = inflater.decompress(pending, capacity)
                if decoded:
                    output_size += len(decoded)
                    if output_size > MAX_ARCHIVE_BYTES:
                        raise ArchiveError('inflated archive exceeds the 64 GiB limit')
                    temporary.write(decoded)
                if inflater.unused_data:
                    raise ArchiveError('concatenated gzip members or trailing bytes are not supported')
                pending = inflater.unconsumed_tail
                if pending and len(pending) == before and not decoded:
                    raise ArchiveError('invalid gzip stream')
                if inflater.eof and pending:
                    raise ArchiveError('trailing data after gzip member')
        if not inflater.eof:
            raise ArchiveError('truncated gzip stream')
        tail = inflater.flush()
        output_size += len(tail)
        if output_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError('inflated archive exceeds the 64 GiB limit')
        if tail:
            temporary.write(tail)
        temporary.seek(0)
        yield temporary, True
    except (OSError, zlib.error) as error:
        raise ArchiveError('cannot read archive: %s' % error)
    finally:
        source.close()
        if temporary is not None:
            temporary.close()


def _archive_digest(stream, file_size):
    remaining = file_size - 32
    if remaining < HEADER_BYTES:
        raise ArchiveError('archive is too small')
    stream.seek(0)
    digest = hashlib.sha256()
    while remaining:
        chunk = stream.read(min(65536, remaining))
        if not chunk:
            raise ArchiveError('truncated archive while checking its digest')
        digest.update(chunk)
        remaining -= len(chunk)
    stored = _read_exact(stream, 32)
    if digest.digest() != stored:
        raise ArchiveError('archive SHA-256 check failed')


def _manifest(stream, file_size):
    stream.seek(0)
    header = _read_exact(stream, HEADER_BYTES)
    version = header[4]
    if version not in BLOCK_MAX or header[:4] != b'CAT\0' or header[5:8] != bytes(3):
        raise ArchiveError('unsupported CAT format or header flags')
    if struct.unpack('>I', header[12:16])[0] != 0:
        raise ArchiveError('unsupported CAT header flags')
    count = struct.unpack('>I', header[8:12])[0]
    manifest_size, payload_size = struct.unpack('>QQ', header[16:32])
    if (not count or count > MAX_ENTRIES or manifest_size > MAX_MANIFEST or
            manifest_size > file_size - HEADER_BYTES - 32 or
            payload_size != file_size - HEADER_BYTES - 32 - manifest_size):
        raise ArchiveError('invalid archive bounds')

    remaining = manifest_size
    payload_remaining = payload_size
    payload_offset = HEADER_BYTES + manifest_size
    total = 0
    file_count = 0
    entries = []
    by_path = {}
    block_max = BLOCK_MAX[version]
    frame_width = 2 if version == 8 else 4
    for index in range(count):
        if remaining < RECORD_BYTES:
            raise ArchiveError('truncated archive manifest')
        record = _read_exact(stream, RECORD_BYTES)
        remaining -= RECORD_BYTES
        entry_id = struct.unpack('>I', record[0:4])[0]
        kind, scheme = record[4], record[5]
        mode = struct.unpack('>H', record[6:8])[0]
        path_length = struct.unpack('>I', record[8:12])[0]
        reserved = struct.unpack('>I', record[12:16])[0]
        size, packed = struct.unpack('>QQ', record[16:32])
        file_hash = record[32:64]
        if (entry_id != index or reserved or not path_length or
                path_length >= MAX_PATH_BYTES or path_length > remaining or
                kind not in (1, 2) or scheme != (1 if kind == 2 else 0) or
                mode > 0o777 or size > MAX_INPUT_BYTES - total or
                (kind == 2 and file_count == MAX_FILES) or
                packed > payload_remaining):
            raise ArchiveError('invalid archive manifest record')
        path_bytes = _read_exact(stream, path_length)
        remaining -= path_length
        display = _safe_path(path_bytes)
        if path_bytes in by_path:
            raise ArchiveError('duplicate path in archive')
        if kind == 1 and (size or packed or file_hash != ZERO_HASH):
            raise ArchiveError('directory record carries file data')
        if kind == 2:
            blocks = (size + block_max - 1) // block_max
            if blocks > packed // (2 + 2 * frame_width):
                raise ArchiveError('impossible file/block size claim')
        parent_bytes = path_bytes.rpartition(b'/')[0]
        if parent_bytes:
            parent = by_path.get(parent_bytes)
            if parent is None or parent.kind != 1:
                raise ArchiveError('missing or non-directory parent path')
        elif index and version < 7:
            raise ArchiveError('multiple roots require CAT format v0.7')
        entry = Entry(path_bytes, display, kind, mode, size, packed, file_hash, payload_offset)
        entries.append(entry)
        by_path[path_bytes] = entry
        total += size
        if kind == 2:
            file_count += 1
        payload_remaining -= packed
        payload_offset += packed
    if remaining or payload_remaining:
        raise ArchiveError('unreferenced manifest or payload bytes')
    _validate_windows_names(entries)
    return version, entries, total, block_max, frame_width


def _varint(data, position):
    value = 0
    for index in range(3):
        if position >= len(data):
            raise ArchiveError('truncated aggregate-tree integer')
        byte = data[position]
        position += 1
        value |= (byte & 0x7f) << (index * 7)
        if not byte & 0x80:
            if (index and not (byte & 0x7f)) or value > 8192:
                raise ArchiveError('noncanonical or out-of-range aggregate-tree integer')
            return value, position
    raise ArchiveError('aggregate-tree integer is too long')


def _decode_tree(data, expected):
    if expected > 8192:
        raise ArchiveError('aggregate-tree block exceeds its decoder limit')
    position = 0
    length, position = _varint(data, position)
    buckets, position = _varint(data, position)
    if length != expected or buckets > 256:
        raise ArchiveError('invalid aggregate-tree header')
    output = bytearray(length)
    seen = bytearray(length)
    total = 0
    previous_byte = -1
    for _ in range(buckets):
        if position >= len(data):
            raise ArchiveError('truncated aggregate-tree bucket')
        value = data[position]
        position += 1
        if value <= previous_byte:
            raise ArchiveError('aggregate-tree buckets are not canonical')
        previous_byte = value
        run_count, position = _varint(data, position)
        if not run_count or run_count > length:
            raise ArchiveError('invalid aggregate-tree run count')
        end = 0
        for run_index in range(run_count):
            gap, position = _varint(data, position)
            run, position = _varint(data, position)
            if (not run or (run_index and not gap) or gap > length - end or
                    run > length - end - gap):
                raise ArchiveError('aggregate-tree run is out of bounds')
            start = end + gap
            end = start + run
            for offset in range(start, end):
                if seen[offset]:
                    raise ArchiveError('aggregate-tree positions overlap')
                seen[offset] = 1
                output[offset] = value
                total += 1
    if total != length or position != len(data):
        raise ArchiveError('aggregate-tree does not cover the block exactly')
    return bytes(output)


def _decode_file(stream, entry, block_max, frame_width, sink):
    remaining = entry.payload_size
    original = entry.size
    digest = hashlib.sha256()
    while remaining:
        frame_size = 1 + 2 * frame_width
        if remaining < frame_size:
            raise ArchiveError('truncated file block header')
        frame = _read_exact(stream, frame_size)
        remaining -= frame_size
        codec = frame[0]
        length = int.from_bytes(frame[1:1 + frame_width], 'big')
        packed = int.from_bytes(frame[1 + frame_width:], 'big')
        expected = min(original, block_max)
        if (not length or length != expected or packed > remaining or
                packed > block_max):
            raise ArchiveError('invalid file block bounds')
        encoded = _read_exact(stream, packed)
        if codec == 0:
            if packed != length:
                raise ArchiveError('invalid raw block length')
            decoded = encoded
        elif codec == 1:
            if packed >= length:
                raise ArchiveError('aggregate-tree block is not smaller than raw data')
            decoded = _decode_tree(encoded, length)
        else:
            raise ArchiveError('unsupported file block codec')
        digest.update(decoded)
        if sink is not None:
            sink.write(decoded)
        remaining -= packed
        original -= length
    if original:
        raise ArchiveError('file payload is missing blocks')
    if digest.digest() != entry.digest:
        raise ArchiveError('file SHA-256 check failed for %s' % entry.path)


def _scan(stream, entries, block_max, frame_width, stage=None):
    for entry in entries:
        if entry.kind != 2:
            continue
        stream.seek(entry.payload_offset)
        sink = None
        output = None
        if stage is not None:
            target = stage.joinpath(*entry.path.split('/'))
            target.parent.mkdir(parents=True, exist_ok=True)
            output = open(target, 'xb')
            sink = output
        try:
            _decode_file(stream, entry, block_max, frame_width, sink)
        finally:
            if output is not None:
                output.close()
        if stage is not None and os.name != 'nt':
            os.chmod(target, entry.mode)


def _rename_directory_noreplace(source, destination):
    """Atomically publish a staged directory without replacing any path."""
    if os.name == 'nt':
        # Windows os.rename fails if the destination already exists.
        os.rename(str(source), str(destination))
        return

    libc = ctypes.CDLL(None, use_errno=True)
    old_path = os.fsencode(source)
    new_path = os.fsencode(destination)
    if sys.platform.startswith('linux'):
        rename = getattr(libc, 'renameat2', None)
        if rename is None:
            raise OSError(errno.ENOTSUP, 'atomic no-replace rename is unavailable', str(destination))
        rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int,
                           ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(-100, old_path, -100, new_path, 1)  # AT_FDCWD, RENAME_NOREPLACE
    elif sys.platform == 'darwin':
        rename = getattr(libc, 'renamex_np', None)
        if rename is None:
            raise OSError(errno.ENOTSUP, 'atomic no-replace rename is unavailable', str(destination))
        rename.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        rename.restype = ctypes.c_int
        result = rename(old_path, new_path, 0x00000004)  # RENAME_EXCL
    else:
        raise OSError(errno.ENOTSUP, 'atomic no-replace rename is unsupported on this OS', str(destination))

    if result != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), str(destination))


def _parse(stream, path, gzipped, destination=None):
    stream.seek(0, os.SEEK_END)
    file_size = stream.tell()
    if file_size > MAX_ARCHIVE_BYTES:
        raise ArchiveError('archive exceeds the 64 GiB limit')
    _archive_digest(stream, file_size)
    version, entries, total, block_max, frame_width = _manifest(stream, file_size)
    stage = None
    final_path = None
    try:
        if destination is not None:
            final_path = Path(destination).absolute()
            if os.path.lexists(str(final_path)):
                raise ArchiveError('extraction destination already exists')
            if not final_path.parent.is_dir():
                raise ArchiveError('extraction parent directory does not exist')
            stage = Path(tempfile.mkdtemp(prefix=final_path.name + '.tmp.',
                                          dir=str(final_path.parent)))
            for entry in entries:
                if entry.kind == 1:
                    target = stage.joinpath(*entry.path.split('/'))
                    target.mkdir(parents=True, exist_ok=True)
            _scan(stream, entries, block_max, frame_width, stage)
            if os.name != 'nt':
                for entry in reversed(entries):
                    if entry.kind == 1:
                        target = stage.joinpath(*entry.path.split('/'))
                        os.chmod(target, entry.mode)
            if os.path.lexists(str(final_path)):
                raise ArchiveError('extraction destination appeared during operation')
            _rename_directory_noreplace(stage, final_path)
            stage = None
        else:
            _scan(stream, entries, block_max, frame_width)
        return ArchiveInfo(os.fspath(path), version, entries, total, gzipped)
    except OSError as error:
        raise ArchiveError('extraction failed: %s' % error)
    finally:
        if stage is not None:
            shutil.rmtree(str(stage), ignore_errors=True)


def inspect_archive(path):
    """Validate all archive bytes and return the manifest for display."""
    try:
        with _inner_archive(path) as (stream, gzipped):
            return _parse(stream, path, gzipped)
    except ArchiveError:
        raise
    except OSError as error:
        raise ArchiveError('cannot open archive: %s' % error)


def extract_archive(path, destination):
    """Validate and extract to a new directory without overwriting existing data."""
    try:
        with _inner_archive(path) as (stream, gzipped):
            return _parse(stream, path, gzipped, destination)
    except ArchiveError:
        raise
    except OSError as error:
        raise ArchiveError('cannot open or extract archive: %s' % error)
