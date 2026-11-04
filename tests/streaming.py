"""Larger-than-v0.1-limit round trip with bounded archiver RSS."""
import hashlib
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import tempfile

binary=str(Path(sys.argv[1]).resolve())
input_bytes=int(sys.argv[2]) if len(sys.argv)>2 else 24*1024*1024
assert input_bytes>16*1024*1024
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(65536),b''):h.update(chunk)
    return h.hexdigest()
def run(*args):
    p=subprocess.run([binary,*map(str,args)],capture_output=True,check=True)
    return dict(re.findall(r'(\w+)=([\w.]+)',p.stderr.decode()))
with tempfile.TemporaryDirectory(prefix='cat-streaming-') as td:
    root=Path(td);source=root/'large.bin'
    # Real lengths, not allocated disk usage. Repeated chunks still contain
    # arbitrary byte values; the CAT run codec falls back to raw blocks.
    data=random.Random(20261103).randbytes(65536)
    with source.open('wb') as f:
        remaining=input_bytes
        while remaining:
            n=min(remaining,len(data));f.write(data[:n]);remaining-=n
    results=[]
    for gzip in [False,True]:
        archive=root/('large.cat.gz' if gzip else 'large.cat')
        encoded=run('-eg' if gzip else '-e',source,archive)
        output=root/('gzip-out' if gzip else 'plain-out')
        decoded=run('-d',archive,output)
        subprocess.run(['cmp',str(source),str(output/source.name)],check=True)
        assert digest(source)==digest(output/source.name)
        assert int(encoded['peak_rss_bytes'])<64*1024*1024, encoded
        assert int(decoded['peak_rss_bytes'])<64*1024*1024, decoded
        results.append({'gzip':gzip,'encode':encoded,'decode':decoded})
print(json.dumps({'input_bytes':input_bytes,'round_trip':'cmp and SHA-256 match','rss_limit_bytes':64*1024*1024,'runs':results},indent=2))
