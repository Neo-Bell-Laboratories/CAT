"""Small reproducible corpus; tar+gzip provides the same file-tree capability."""
import argparse
import fnmatch
import gzip
import io
import json
from pathlib import Path
import random
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('binary', help='CATS executable to benchmark')
parser.add_argument('--tree', type=Path, help='also benchmark a real file or directory tree')
parser.add_argument('--exclude', action='append', default=[],
                    help='relative path pattern to omit from --tree (repeatable)')
args = parser.parse_args()
binary = str(Path(args.binary).resolve())
zstd_binary = shutil.which('zstd')
rows = []

def command(*args):
    p = subprocess.run([binary, *map(str,args)], capture_output=True, check=True)
    values = dict(re.findall(r'(\w+)=([\w.]+)', p.stderr.decode()))
    return values

def zstd_roundtrip(payload, level):
    started = time.perf_counter()
    encoded = subprocess.run(
        [zstd_binary, '-q', '-'+str(level), '-c'], input=payload,
        capture_output=True, check=True).stdout
    encode_seconds = time.perf_counter() - started
    started = time.perf_counter()
    restored = subprocess.run(
        [zstd_binary, '-q', '-d', '-c'], input=encoded,
        capture_output=True, check=True).stdout
    decode_seconds = time.perf_counter() - started
    assert restored == payload
    return encoded, round(encode_seconds, 6), round(decode_seconds, 6)

with tempfile.TemporaryDirectory(prefix='cat-benchmark-') as td:
    root = Path(td)
    rng = random.Random(20261103)
    random_bytes = rng.randbytes(65536)
    cases = {
        'zero-runs': bytes(65536),
        'repetitive-text': (b'CAT lossless archive sample line\r\n'*2048),
        'random-bytes': random_bytes,
        'already-compressed': gzip.compress(random_bytes,mtime=0),
        'duplicate-files': None,
    }
    if args.tree:
        cases['real-tree'] = None
    for name, data in cases.items():
        tree_mode = name == 'real-tree'
        source = args.tree.resolve() if tree_mode else root/name
        if name == 'duplicate-files':
            source.mkdir()
            data = random_bytes[:8192]
            (source/'a').write_bytes(data); (source/'b').write_bytes(data)
        elif tree_mode:
            if not source.exists():
                parser.error('--tree does not exist: ' + str(source))
        else:
            source.write_bytes(data)
        paths = [source]
        if source.is_dir():
            for path in sorted(source.rglob('*')):
                relative = path.relative_to(source).as_posix()
                components = Path(relative).parts
                excluded = any(
                    fnmatch.fnmatchcase(relative, pattern) or
                    (('/' not in pattern) and any(fnmatch.fnmatchcase(part, pattern)
                                                   for part in components)) or
                    any(fnmatch.fnmatchcase('/'.join(components[:i]), pattern)
                        for i in range(1, len(components)))
                    for pattern in (args.exclude if tree_mode else ()))
                if not excluded:
                    paths.append(path)
        original = sum(p.stat().st_size for p in paths if p.is_file())
        tarbuf = io.BytesIO()
        tar_start = time.perf_counter()
        with tarfile.open(fileobj=tarbuf,mode='w',format=tarfile.USTAR_FORMAT) as tar:
            for p in paths:
                info=tarfile.TarInfo(str(p.relative_to(source.parent)))
                info.mode=p.stat().st_mode&0o777;info.mtime=0
                if p.is_dir():info.type=tarfile.DIRTYPE;tar.addfile(info)
                else:
                    contents=p.read_bytes();info.size=len(contents);tar.addfile(info,io.BytesIO(contents))
        tar_encode_seconds = time.perf_counter() - tar_start
        tar_bytes = tarbuf.getvalue()
        tar_gzip_start = time.perf_counter()
        tar_gzip_bytes = gzip.compress(tar_bytes,compresslevel=9,mtime=0)
        tar_gzip_encode_seconds = time.perf_counter() - tar_gzip_start
        zstd_results = {}
        if zstd_binary:
            for level in (3, 19):
                zstd_encoded, zstd_encode_seconds, zstd_decode_seconds = zstd_roundtrip(tar_bytes, level)
                zstd_results[level] = {
                    'bytes': len(zstd_encoded),
                    'encode_seconds': zstd_encode_seconds,
                    'decode_seconds': zstd_decode_seconds,
                }
        zipbuf = io.BytesIO()
        zip_start = time.perf_counter()
        with zipfile.ZipFile(zipbuf,mode='w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for p in paths:
                relative = str(p.relative_to(source.parent)) + ('/' if p.is_dir() else '')
                info = zipfile.ZipInfo(relative, date_time=(1980,1,1,0,0,0))
                info.external_attr = (p.stat().st_mode & 0xffff) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, b'' if p.is_dir() else p.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        zip_encode_seconds = time.perf_counter() - zip_start
        gzip_payload_start = time.perf_counter()
        gzip_payload_bytes = sum(len(gzip.compress(p.read_bytes(), compresslevel=9, mtime=0))
                                 for p in paths if p.is_file())
        gzip_payload_encode_seconds = time.perf_counter() - gzip_payload_start
        out=root/(name+'.cat')
        exclude_args = [arg for pattern in args.exclude for arg in ('--exclude', pattern)] if tree_mode else []
        enc=command('encode',*exclude_args,source,out)
        dec=command('decode',out,root/(name+'-restored'))
        for p in paths:
            restored=root/(name+'-restored')/p.relative_to(source.parent)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        archive_bytes=out.stat().st_size
        gzout=root/(name+'.cat.gz')
        gzenc=command('-eg',*exclude_args,source,gzout)
        gzdec=command('-d',gzout,root/(name+'-gzip-restored'))
        for p in paths:
            restored=root/(name+'-gzip-restored')/p.relative_to(source.parent)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        compact_out=root/(name+'-compact.cat')
        compact_enc=command('-ec',*exclude_args,source,compact_out)
        compact_dec=command('-dc',compact_out,root/(name+'-compact-restored'))
        for p in paths:
            restored=root/(name+'-compact-restored')/p.relative_to(source.parent)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        cats_zstd_results = {}
        if zstd_binary:
            for label, archive in (('v07', out), ('v08', compact_out)):
                payload = archive.read_bytes()
                for level in (3, 19):
                    encoded, encode_seconds, decode_seconds = zstd_roundtrip(payload, level)
                    cats_zstd_results[(label, level)] = {
                        'bytes': len(encoded), 'encode_seconds': encode_seconds,
                        'decode_seconds': decode_seconds,
                    }
        compact_gzout=root/(name+'-compact.cat.gz')
        compact_gzenc=command('-ecg',*exclude_args,source,compact_gzout)
        compact_gzdec=command('-dc',compact_gzout,root/(name+'-compact-gzip-restored'))
        for p in paths:
            restored=root/(name+'-compact-gzip-restored')/p.relative_to(source.parent)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        rows.append({
            'dataset':name,'input_bytes':original,'cat_bytes':archive_bytes,
            'cat_gzip_bytes':gzout.stat().st_size,'cat_gzip_ratio':round(gzout.stat().st_size/original,6),
            'cat_compact_bytes':compact_out.stat().st_size,
            'cat_compact_gzip_bytes':compact_gzout.stat().st_size,
            'compact_encode_seconds':float(compact_enc['seconds']),
            'compact_decode_seconds':float(compact_dec['seconds']),
            'compact_gzip_encode_seconds':float(compact_gzenc['seconds']),
            'compact_gzip_decode_seconds':float(compact_gzdec['seconds']),
            'tar_encode_seconds':round(tar_encode_seconds,6),
            'tar_gzip_encode_seconds':round(tar_gzip_encode_seconds,6),
            'zip_encode_seconds':round(zip_encode_seconds,6),
            'gzip_payload_encode_seconds':round(gzip_payload_encode_seconds,6),
            'gzip_encode_seconds':float(gzenc['seconds']),'gzip_decode_seconds':float(gzdec['seconds']),
            'gzip_encode_peak_rss_bytes':int(gzenc['peak_rss_bytes']),'gzip_decode_peak_rss_bytes':int(gzdec['peak_rss_bytes']),
            'ratio':round(archive_bytes/original,6),'tar_bytes':len(tar_bytes),
            'tar_gzip_bytes':len(tar_gzip_bytes),
            'zip_bytes':len(zipbuf.getvalue()),'gzip_payload_bytes':gzip_payload_bytes,
            'tree_blocks':int(enc['tree_blocks']),'raw_blocks':int(enc['raw_blocks']),
            'encode_seconds':float(enc['seconds']),'decode_seconds':float(dec['seconds']),
            'encode_bytes_per_second':round(original/float(enc['seconds'])),
            'decode_bytes_per_second':round(original/float(dec['seconds'])),
            'encode_peak_rss_bytes':int(enc['peak_rss_bytes']), 'decode_peak_rss_bytes':int(dec['peak_rss_bytes']),
        })
        for level, result in zstd_results.items():
            rows[-1][f'tar_zstd_{level}_bytes'] = result['bytes']
            rows[-1][f'tar_zstd_{level}_encode_seconds'] = result['encode_seconds']
            rows[-1][f'tar_zstd_{level}_decode_seconds'] = result['decode_seconds']
        for (label, level), result in cats_zstd_results.items():
            rows[-1][f'cat_{label}_zstd_{level}_bytes'] = result['bytes']
            rows[-1][f'cat_{label}_zstd_{level}_encode_seconds'] = result['encode_seconds']
            rows[-1][f'cat_{label}_zstd_{level}_decode_seconds'] = result['decode_seconds']
print(json.dumps({'host':platform.system()+' '+platform.machine()+'; release build; timings are single-run observations',
    'baseline':'deterministic USTAR, USTAR+gzip level 9, ZIP deflate level 9, per-file gzip level 9, USTAR+zstd levels 3/19, and outer zstd levels 3/19 on CAT v0.7/v0.8 when zstd is installed; gzip payload size excludes tree metadata',
    'zstd_version':subprocess.run([zstd_binary,'--version'],capture_output=True,text=True,check=True).stdout.splitlines()[0] if zstd_binary else None,
    'tree_input':str(args.tree.resolve()) if args.tree else None,
    'tree_excludes':args.exclude if args.tree else [],
    'results':rows},indent=2))
