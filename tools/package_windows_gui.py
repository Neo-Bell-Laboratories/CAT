"""Build a deterministic, checksummed Windows CATS GUI extractor bundle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
import zipfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', required=True)
args = parser.parse_args()
cat = Path(__file__).resolve().parent.parent
version = re.search(r'#define CAT_VERSION "([^"]+)"', (cat / 'src/catc.c').read_text()).group(1)
bundle = 'CATS-GUI-Windows-' + re.sub(r'[^A-Za-z0-9._-]', '_', version)
paths = [
    'gui/cat_gui.py',
    'gui/cat_archive.py',
    'packaging/windows/install-gui.ps1',
    'packaging/windows/CATDoc.ico',
    'LICENSE',
    'THIRD_PARTY.md',
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
files['README.txt'] = (cat / 'packaging/windows/README.txt').read_bytes()
manifest = {
    'bundle': bundle,
    'kind': 'windows-gui-extractor',
    'version': version,
    'requires': 'Windows 10 or newer; Python 3 with Tcl/Tk',
    'source_date_epoch': int(os.environ.get('SOURCE_DATE_EPOCH', '0')),
    'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
}
manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
epoch = manifest['source_date_epoch']
zip_time = time.gmtime(max(315532800, min(epoch, 4354819198)))[:6]
output = Path(args.output).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
temporary = output.with_name(output.name + '.tmp')
try:
    with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(bundle + '/' + name, zip_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        info = zipfile.ZipInfo(bundle + '/BUILD-MANIFEST.json', zip_time)
        info.compress_type = zipfile.ZIP_DEFLATED
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        archive.writestr(info, manifest_bytes, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    os.replace(temporary, output)
finally:
    temporary.unlink(missing_ok=True)
digest = hashlib.sha256(output.read_bytes()).hexdigest()
output.with_name(output.name + '.sha256').write_text(digest + '  ' + output.name + '\n')
print(f'{output}  sha256={digest}')
