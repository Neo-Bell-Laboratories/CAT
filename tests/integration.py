"""Independent black-box archive checks. No third-party Python packages."""
import gzip
import hashlib
import os
from pathlib import Path
import random
import shutil
import stat
import struct
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
checks = 0

def run(*args, ok=True, code=None, timeout=120):
    global checks
    env = dict(os.environ, UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    p = subprocess.run([binary, *map(str, args)], capture_output=True, env=env, timeout=timeout)
    checks += 1
    assert p.returncode == (code if code is not None else (0 if ok else 1)), (args, p.returncode, p.stdout, p.stderr)
    assert b'Sanitizer' not in p.stderr and b'runtime error:' not in p.stderr, p.stderr
    return p

def seal(body):
    return body + hashlib.sha256(body).digest()

def archive(records):
    manifest = bytearray()
    payload = bytearray()
    for i, (path, kind, mode, data, packed) in enumerate(records):
        if isinstance(path, str): path = path.encode()
        digest = hashlib.sha256(data).digest() if kind == 2 else bytes(32)
        manifest += struct.pack('>IBBHI IQQ', i, kind, int(kind == 2), mode, len(path), 0, len(data), len(packed)) + digest + path
        payload += packed
    return seal(b'CAT\0' + bytes([int(os.environ.get('CAT_TEST_FORMAT_VERSION','6'))]) + b'\0\0\0' + struct.pack('>IIQQ', len(records), 0, len(manifest), len(payload)) + manifest + payload)

def block(data, codec=0, length=None):
    return bytes([codec]) + struct.pack('>II', len(data) if length is None else length, len(data)) + data

def snapshot(root):
    result = {}
    for path in sorted(root.rglob('*')):
        st = path.stat()
        result[str(path.relative_to(root))] = (path.is_dir(), stat.S_IMODE(st.st_mode), None if path.is_dir() else path.read_bytes())
    return result

with tempfile.TemporaryDirectory(prefix='cat-integration-') as td:
    t = Path(td)
    source = t/'source'
    (source/'nested'/'empty').mkdir(parents=True)
    (source/'other').mkdir()
    fixtures = {
        'zero': b'', 'one': b'\xff', 'nul-runs': bytes(13000),
        'all-bytes': bytes(range(256))*33,
        'invalid-utf8': b'\xff\xfe\x00\x80\r\n\n\r',
        'nested/same name': b'text\r\nwith\nline endings\r',
        'other/same name': b'other', 'unicode-λ.txt': 'hello λ\n'.encode(),
        'random': random.Random(47).randbytes(9001),
        'terminal-\x1b[31m.txt': b'control byte in filename',
    }
    for name, data in fixtures.items(): (source/name).write_bytes(data)
    os.chmod(source/'one', 0o751)
    os.chmod(source/'nested'/'empty', 0o750)
    expected = snapshot(t)  # capture before creating archives
    run('encode', source, t/'a.cat')
    run('encode', source, t/'b.cat')
    encoded = (t/'a.cat').read_bytes()
    assert encoded == (t/'b.cat').read_bytes(), 'nondeterministic archive'
    assert hashlib.sha256(encoded[:-32]).digest() == encoded[-32:], 'SHA implementation differs from hashlib'
    run('verify', t/'a.cat')
    p = run('inspect', t/'a.cat'); assert b'nested/empty' in p.stdout
    assert b'\x1b' not in p.stdout and b'\\x1b' in p.stdout
    run('decode', t/'a.cat', t/'restored')
    assert snapshot(t/'restored') == expected
    for name in fixtures:
        subprocess.run(['cmp', str(source/name), str(t/'restored'/'source'/name)], check=True)
        assert hashlib.sha256((source/name).read_bytes()).digest() == hashlib.sha256((t/'restored'/'source'/name).read_bytes()).digest()
    run('decode', t/'a.cat', t/'restored', ok=False)
    run('encode', source, t/'a.cat', ok=False)
    assert (t/'a.cat').read_bytes() == encoded
    run('encode', source/'one', t/'one.cat')
    run('decode', t/'one.cat', t/'one-out')
    assert (t/'one-out'/'one').read_bytes() == b'\xff'
    (t/'link').symlink_to(source/'one')
    run('encode', t/'link', t/'link.cat', ok=False)
    (source/'link').symlink_to(source/'one')
    run('encode', source, t/'links.cat', ok=False)
    assert not (t/'links.cat').exists(); (source/'link').unlink()
    os.mkfifo(source/'pipe')
    run('encode', source, t/'fifo.cat', ok=False)
    run('-v', source/'pipe', ok=False, timeout=30)
    run('-d', source/'pipe', t/'fifo-output', ok=False, timeout=30)
    assert not (t/'fifo-output').exists()
    run('-v', t/'link', ok=False)
    (source/'pipe').unlink()
    # A sparse input exercises the byte budget without allocating huge fixtures.
    with (t/'oversize').open('wb') as f: f.truncate(16*1024*1024+1)
    run('encode', '--max-bytes', str(16*1024*1024), t/'oversize', t/'oversize.cat', ok=False)
    data = b'\x00\xffa\r\n'
    golden = archive([('golden', 2, 0o640, data, block(data))])
    (t/'golden.cat').write_bytes(golden)
    run('decode', t/'golden.cat', t/'golden-out')
    assert (t/'golden-out'/'golden').read_bytes() == data
    invalid = []
    invalid += [encoded[:n] for n in [0, 1, 7, 31, 63, len(encoded)-1]]
    invalid += [b'BADMAGIC' + encoded[8:], encoded+b'junk']
    broken = bytearray(encoded); broken[-33] ^= 1; invalid.append(bytes(broken))
    for path in ['/escape', '../escape', 'a/../escape', 'a//b', 'a/', '.', b'a\0b']:
        invalid.append(archive([(path, 2, 0o600, b'x', block(b'x'))]))
    invalid += [
        archive([('a', 2, 0o600, b'a', block(b'a')), ('a', 2, 0o600, b'a', block(b'a'))]),
        archive([('a/b', 2, 0o600, b'a', block(b'a'))]),
        archive([('a', 2, 0o600, b'a', block(b'a')), ('a/b', 2, 0o600, b'a', block(b'a'))]),
        archive([('a', 1, 0o700, b'x', b'')]),
        archive([('a', 2, 0o600, b'x', block(b'y'))]),  # file hash mismatch, valid archive hash
        archive([('a', 2, 0o600, b'x', block(b'x', codec=2))]),
        archive([('a', 2, 0o600, b'x', block(b'x', length=4097))]),
        archive([('a', 2, 0o600, b'x', b'')]),
    ]
    # Validly hashed containers with malformed compressed trees must reach parser checks.
    for tree in [b'', b'\x80', b'\x80\x80\x80', b'\x80\x20\x00', b'\x80\x20\x01\x00\x01\x00\x00',
                 b'\x80\x20\x01\x00\x02\x00\x01\x00\x01',
                 b'\x80\x20\x02\x00\x01\x00\x80\x20\x01\x01\x00\x01']:
        invalid.append(archive([('a', 2, 0o600, bytes(4096), block(tree,1,4096))]))
    # Mutate header limits and flags, repairing the archive digest.
    for offset, value in [(4, 99), (12, 1), (16, 255), (24, 255), (32, 1), (36, 9), (37, 0), (44, 1)]:
        body = bytearray(golden[:-32]); body[offset] = value; invalid.append(seal(body))
    for i, bad in enumerate(invalid):
        path = t/'bad.cat'; path.write_bytes(bad)
        run('verify', path, ok=False)
        out = t/f'bad-out-{i}'
        run('decode', path, out, ok=False)
        assert not out.exists(), 'invalid archive created extraction output'
    # Both flag spellings, whole-archive gzip interoperability and auto-detection.
    for enc, dec, ins, ver, gz in [('-e','-d','-i','-v','-g'),
                                  ('--encode','--decode','--inspect','--verify','--gzip')]:
        suffix = 'short' if enc == '-e' else 'long'
        compressed = t/(suffix+'.cat.gz')
        run(enc, source, compressed, gz)
        compressed_bytes = compressed.read_bytes()
        assert gzip.decompress(compressed_bytes) == encoded
        assert compressed_bytes[4:8] == bytes(4), 'gzip timestamp is not deterministic'
        assert b'gzip=on' in run(ver, compressed).stderr
        run(ins, compressed)
        destination = t/(suffix+'-out')
        run(dec, compressed, destination)
        assert snapshot(destination) == expected
        again = t/(suffix+'-again.cat')
        run(gz, enc, source, again)
        assert again.read_bytes() == compressed_bytes, 'nondeterministic gzip'
        run(enc, source, compressed, gz, ok=False)
        assert compressed.read_bytes() == compressed_bytes
    # Grouped short flags are equivalent in either order.
    for flags in ['-eg', '-ge']:
        grouped = t/(flags[1:]+'.cat.gz')
        run(flags, source, grouped)
        assert grouped.read_bytes() == (t/'short.cat.gz').read_bytes()
        run('-v', grouped)
        destination = t/(flags[1:]+'-restored')
        run('-d', grouped, destination)
        assert snapshot(destination) == expected
    for flags in ['-ed', '-ee', '-dg', '-ig', '-vg', '-ez', '-geZ']:
        run(flags, source, t/'bad-group.cat', code=2)
    assert not (t/'bad-group.cat').exists()
    run('-d', '--no-permissions', t/'a.cat', t/'content-only')
    assert (t/'content-only'/'source'/'one').read_bytes() == b'\xff'
    assert (t/'content-only'/'source'/'one').stat().st_mode & 0o777 == 0o600
    assert (t/'content-only'/'source'/'nested'/'empty').stat().st_mode & 0o777 == 0o700
    run('-e', '--no-permissions', source, t/'bad-mode.cat', code=2)
    # Plain archives still accept all new aliases.
    run('-v', t/'a.cat'); run('--inspect', t/'a.cat')
    # Externally gzip-wrapped CAT archives are readable regardless of extension.
    external = t/'external.cat'
    external.write_bytes(gzip.compress(encoded, compresslevel=9, mtime=0))
    run('--verify', external)
    run('--decode', external, t/'external-out')
    assert snapshot(t/'external-out') == expected
    # Header/CRC/trailer truncation, concatenated members, trailing bytes and bombs.
    gzbytes = external.read_bytes()
    bad_crc = bytearray(gzbytes); bad_crc[-8] ^= 1
    gzip_bad = [gzbytes[:2], gzbytes[:10], gzbytes[:-1], bytes(bad_crc),
                gzbytes+b'junk', gzbytes+gzbytes,
                gzip.compress(bytes(32*1024*1024+1), mtime=0),
                gzip.compress(b'not a CAT archive',mtime=0)]
    for i, contents in enumerate(gzip_bad):
        bad = t/'bad-gzip.cat'; bad.write_bytes(contents)
        run('-v', '--max-archive-bytes', str(32*1024*1024), bad, ok=False)
        destination = t/f'bad-gzip-out-{i}'
        run('-d', '--max-archive-bytes', str(32*1024*1024), bad, destination, ok=False)
        assert not destination.exists()
    # Usage errors are distinct from archive errors; no ambiguous action flags.
    for args in [('-d', '--gzip', t/'a.cat', t/'unused'), ('-e', '-d', source),
                 ('--wat',), ('-e', source), ('-i', t/'a.cat', t/'unused')]:
        run(*args, code=2)
    # End-of-options supports literal paths beginning with a dash.
    p = subprocess.run([binary, '-e', '--gzip', '--', str(source/'one'), '-dash.cat'],
                       cwd=t, capture_output=True)
    assert p.returncode == 0, p.stderr
    run('-v', t/'-dash.cat')
    # Deterministic structure-aware mutation smoke fuzz: repair top-level hashes.
    rng = random.Random(2026)
    for _ in range(24):
        body = bytearray(golden[:-32]); pos = rng.randrange(32, len(body)); body[pos] ^= 1 << rng.randrange(8)
        (t/'mutated.cat').write_bytes(seal(body))
        p = subprocess.run([binary, 'verify', str(t/'mutated.cat')], capture_output=True)
        assert p.returncode in (0,1) and b'Sanitizer' not in p.stderr and b'runtime error:' not in p.stderr, p.stderr
        checks += 1
print(f'PASS: {checks} CLI checks; exact bytes/modes, deterministic archives, independent SHA/golden archive, corruption/path rejection, gzip interoperability/bounds and CLI aliases')
