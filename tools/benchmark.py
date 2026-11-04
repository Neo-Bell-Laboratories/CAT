"""Small reproducible corpus; tar+gzip provides the same file-tree capability."""
import gzip
import io
import json
from pathlib import Path
import random
import platform
import re
import subprocess
import sys
import tarfile
import tempfile

binary = str(Path(sys.argv[1]).resolve())
rows = []

def command(*args):
    p = subprocess.run([binary, *map(str,args)], capture_output=True, check=True)
    values = dict(re.findall(r'(\w+)=([\w.]+)', p.stderr.decode()))
    return values

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
    for name, data in cases.items():
        source = root/name
        if data is None:
            source.mkdir()
            data = random_bytes[:8192]
            (source/'a').write_bytes(data); (source/'b').write_bytes(data)
        else: source.write_bytes(data)
        paths = [source] + (sorted(source.rglob('*')) if source.is_dir() else [])
        original = sum(p.stat().st_size for p in paths if p.is_file())
        tarbuf = io.BytesIO()
        with tarfile.open(fileobj=tarbuf,mode='w',format=tarfile.USTAR_FORMAT) as tar:
            for p in paths:
                info=tarfile.TarInfo(str(p.relative_to(root)))
                info.mode=p.stat().st_mode&0o777;info.mtime=0
                if p.is_dir():info.type=tarfile.DIRTYPE;tar.addfile(info)
                else:
                    contents=p.read_bytes();info.size=len(contents);tar.addfile(info,io.BytesIO(contents))
        out=root/(name+'.cat')
        enc=command('encode',source,out)
        dec=command('decode',out,root/(name+'-restored'))
        for p in paths:
            restored=root/(name+'-restored')/p.relative_to(root)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        archive_bytes=out.stat().st_size
        gzout=root/(name+'.cat.gz')
        gzenc=command('-eg',source,gzout)
        gzdec=command('-d',gzout,root/(name+'-gzip-restored'))
        for p in paths:
            restored=root/(name+'-gzip-restored')/p.relative_to(root)
            assert restored.is_dir() if p.is_dir() else restored.read_bytes()==p.read_bytes()
        rows.append({
            'dataset':name,'input_bytes':original,'cat_bytes':archive_bytes,
            'cat_gzip_bytes':gzout.stat().st_size,'cat_gzip_ratio':round(gzout.stat().st_size/original,6),
            'gzip_encode_seconds':float(gzenc['seconds']),'gzip_decode_seconds':float(gzdec['seconds']),
            'gzip_encode_peak_rss_bytes':int(gzenc['peak_rss_bytes']),'gzip_decode_peak_rss_bytes':int(gzdec['peak_rss_bytes']),
            'ratio':round(archive_bytes/original,6),'tar_gzip_bytes':len(gzip.compress(tarbuf.getvalue(),compresslevel=9,mtime=0)),
            'tree_blocks':int(enc['tree_blocks']),'raw_blocks':int(enc['raw_blocks']),
            'encode_seconds':float(enc['seconds']),'decode_seconds':float(dec['seconds']),
            'encode_bytes_per_second':round(original/float(enc['seconds'])),
            'decode_bytes_per_second':round(original/float(dec['seconds'])),
            'encode_peak_rss_bytes':int(enc['peak_rss_bytes']), 'decode_peak_rss_bytes':int(dec['peak_rss_bytes']),
        })
print(json.dumps({'host':platform.system()+' '+platform.machine()+'; release build; small synthetic corpus; timings are single-run observations',
    'baseline':'deterministic USTAR file tree compressed with Python gzip level 9; includes archive metadata',
    'results':rows},indent=2))
