"""Build a deterministic, checksummed Linux CATS GUI extractor bundle."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True)
args = parser.parse_args()
cat = Path(__file__).resolve().parent.parent
version = re.search(r'#define CAT_VERSION "([^"]+)"', (cat / 'src/catc.c').read_text()).group(1)
bundle = 'CATS-GUI-Linux-' + re.sub(r'[^A-Za-z0-9._-]', '_', version)
paths = [
    'gui/cat_gui.py',
    'gui/cat_archive.py',
    'packaging/linux/install-gui.sh',
    'packaging/macos/CAT.svg',
    'packaging/macos/CATDoc.svg',
    'LICENSE',
    'THIRD_PARTY.md',
    'packaging/linux/README.txt',
]
files = {}
for relative in paths:
    path = cat / relative
    if path.is_symlink() or not path.is_file():
        raise SystemExit('required regular package file is missing: ' + relative)
    files[relative] = path.read_bytes()
for path in sorted((cat / 'licenses').glob('*.txt')):
    if path.name.startswith('._') or path.is_symlink() or not path.is_file():
        continue
    files['licenses/' + path.name] = path.read_bytes()
if not any(name.startswith('licenses/') for name in files):
    raise SystemExit('no license notices found')
manifest = {
    'bundle': bundle,
    'kind': 'linux-gui-extractor',
    'version': version,
    'requires': 'Linux; Python 3 with Tk; shared-mime-info and a desktop environment for file associations',
    'source_date_epoch': int(os.environ.get('SOURCE_DATE_EPOCH', '0')),
    'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
}
manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
epoch = manifest['source_date_epoch']
output = Path(args.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
temporary = output.with_name(output.name + '.tmp')
try:
    with temporary.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw, mode='wb', filename='', mtime=epoch, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w', format=tarfile.USTAR_FORMAT) as archive:
                for name, data in sorted({**files, 'BUILD-MANIFEST.json': manifest_bytes}.items()):
                    info = tarfile.TarInfo(bundle + '/' + name)
                    info.size = len(data)
                    info.mtime = epoch
                    info.mode = 0o755 if name == 'packaging/linux/install-gui.sh' else 0o644
                    archive.addfile(info, io.BytesIO(data))
    os.replace(temporary, output)
finally:
    temporary.unlink(missing_ok=True)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_name(output.name + '.sha256').write_text(digest + '  ' + output.name + '\n')
print(f'{output}  sha256={digest}')
