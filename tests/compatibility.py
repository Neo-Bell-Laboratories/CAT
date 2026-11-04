import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

binary = str(Path(sys.argv[1]).resolve())
corpus = Path(__file__).parent/'golden'
manifest = json.loads((corpus/'manifest.json').read_text())
with tempfile.TemporaryDirectory(prefix='cat-compatibility-') as td:
    for filename, digest in manifest['archives'].items():
        archive = corpus/filename
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == digest
        output = Path(td)/filename
        subprocess.run([binary, '-d', str(archive), str(output)], check=True, capture_output=True)
        restored = output/manifest['path']
        assert restored.stat().st_size == manifest['size']
        assert restored.stat().st_mode & 0o777 == manifest['mode']
        assert hashlib.sha256(restored.read_bytes()).hexdigest() == manifest['sha256']
print('PASS: saved v0.1 plain/gzip golden archives decode with exact bytes and modes')
