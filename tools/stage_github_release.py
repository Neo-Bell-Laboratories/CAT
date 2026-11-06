"""Assemble the locally built CATS assets into checksummed release staging."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output', type=Path,
                    default=ROOT / 'bin/github-release/CATS-0.4.0')
parser.add_argument('--mac-binary', type=Path, default=ROOT / 'bin/cats')
parser.add_argument('--linux-x64-binary', type=Path, default=ROOT / 'bin/linux-x64/cats')
parser.add_argument('--linux-arm64-binary', type=Path, default=ROOT / 'bin/linux-aarch64/cats')
parser.add_argument('--windows-x64-binary', type=Path, default=ROOT / 'bin/windows-x64/cats.exe')
parser.add_argument('--mac-app', type=Path, default=ROOT / 'build/release/macos/CAT.app')
parser.add_argument('--source', type=Path, default=ROOT / 'releases/cats-source.tar.gz')
parser.add_argument('--linux-gui', type=Path, default=ROOT / 'releases/cats-gui-linux.tar.gz')
parser.add_argument('--windows-gui', type=Path, default=ROOT / 'releases/cats-gui-windows.zip')
args = parser.parse_args()

version = re.search(r'#define CAT_VERSION "([^"]+)"', (ROOT / 'src/catc.c').read_text()).group(1)
assets = {
    'source': args.source,
    'gui_linux': args.linux_gui,
    'gui_windows': args.windows_gui,
    'macos_arm64': args.mac_binary,
    'linux_x86_64': args.linux_x64_binary,
    'linux_aarch64': args.linux_arm64_binary,
    'windows_x86_64': args.windows_x64_binary,
}
for label, path in assets.items():
    if path.is_symlink() or not path.is_file():
        raise SystemExit(f'missing regular release input {label}: {path}')
if not args.mac_app.is_dir() or args.mac_app.is_symlink():
    raise SystemExit(f'missing macOS application bundle: {args.mac_app}')

def file_description(path):
    return subprocess.check_output(['file', '-b', str(path)], text=True).strip()

for label, expected in [('macos_arm64', 'Mach-O 64-bit executable arm64'),
                        ('linux_x86_64', 'ELF 64-bit LSB executable, x86-64'),
                        ('linux_aarch64', 'ELF 64-bit LSB pie executable, ARM aarch64')]:
    description = file_description(assets[label])
    if expected not in description:
        raise SystemExit(f'{label} has unexpected binary type: {description}')
windows_description = file_description(assets['windows_x86_64'])
if 'PE32+ executable (console) x86-64, for MS Windows' not in windows_description:
    raise SystemExit(f'windows_x86_64 has unexpected binary type: {windows_description}')

def tar_bytes(binary, target):
    if target == 'macOS ARM64':
        runtime = 'Requires macOS on Apple Silicon; uses the macOS system runtime and zlib.'
    elif target.startswith('Linux x86_64'):
        runtime = 'Requires x86_64 Linux with glibc 2.17 or newer; zlib is linked statically.'
    else:
        runtime = 'Requires AArch64 Linux with glibc 2.36 or newer and system zlib.'
    files = {
        'cats': binary.read_bytes(),
        'catc': binary.read_bytes(),
        'README.txt': (
            f'CATS {version} command-line release for {target}.\n\n'
            f'{runtime}\n\n'
            'Commands: cats --version; cats -e INPUT --output OUTPUT.cat; '
            'cats -v ARCHIVE; cats -d ARCHIVE DESTINATION.\n'
            'The catc command is included as a compatibility alias.\n'
            'See LICENSE, THIRD_PARTY.md, and the project documentation.\n'
        ).encode(),
        'LICENSE': (ROOT / 'LICENSE').read_bytes(),
        'THIRD_PARTY.md': (ROOT / 'THIRD_PARTY.md').read_bytes(),
    }
    for license_path in sorted((ROOT / 'licenses').glob('[!._]*.txt')):
        files['licenses/' + license_path.name] = license_path.read_bytes()
    metadata = {
        'product': 'CATS', 'version': version, 'target': target,
        'format': '0.7', 'compact_format': '0.8',
        'binary': file_description(binary),
        'sha256': {name: hashlib.sha256(data).hexdigest()
                   for name, data in sorted(files.items())},
    }
    files['BUILD-MANIFEST.json'] = (json.dumps(metadata, indent=2, sort_keys=True) + '\n').encode()
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0, compresslevel=9) as gz:
        with tarfile.open(fileobj=gz, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for name, data in sorted(files.items()):
                info = tarfile.TarInfo(f'cats-{version}/{name}')
                info.size = len(data)
                info.mode = 0o755 if name in ('cats', 'catc') else 0o644
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mtime = 0
                archive.addfile(info, io.BytesIO(data))
    return output.getvalue(), metadata

def windows_zip_bytes(binary):
    files = {
        'cats.exe': binary.read_bytes(),
        'catc.exe': binary.read_bytes(),
        'README.txt': (
            f'CATS {version} command-line release for Windows x64.\n\n'
            'Requires Windows 10 or newer. Windows system CRT, NTDLL, ADVAPI32, '
            'and BCRYPT are used; zlib, PCRE2, XF, and LambdaScript are linked '
            'into the executable. POSIX permission bits are not restored.\n\n'
            'Commands: .\\cats.exe --version; .\\cats.exe -e INPUT --output OUTPUT.cat; '
            '.\\cats.exe -v ARCHIVE; .\\cats.exe -d ARCHIVE DESTINATION.\n'
            'The catc.exe command is included as a compatibility alias.\n'
            'See LICENSE, THIRD_PARTY.md, and the project documentation.\n'
        ).encode(),
        'LICENSE': (ROOT / 'LICENSE').read_bytes(),
        'THIRD_PARTY.md': (ROOT / 'THIRD_PARTY.md').read_bytes(),
    }
    for license_path in sorted((ROOT / 'licenses').glob('[!._]*.txt')):
        files['licenses/' + license_path.name] = license_path.read_bytes()
    metadata = {
        'product': 'CATS', 'version': version, 'target': 'Windows x86_64',
        'format': '0.7', 'compact_format': '0.8',
        'binary': file_description(binary),
        'sha256': {name: hashlib.sha256(data).hexdigest()
                   for name, data in sorted(files.items())},
    }
    files['BUILD-MANIFEST.json'] = (json.dumps(metadata, indent=2, sort_keys=True) + '\n').encode()
    output = io.BytesIO()
    with zipfile.ZipFile(output, mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(f'cats-{version}-windows-x64/{name}', (2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0
            archive.writestr(info, data)
    return output.getvalue(), metadata

out = args.output.resolve()
if out.exists() and any(out.iterdir()):
    old_manifest = out / 'ASSETS.json'
    try:
        old = json.loads(old_manifest.read_text())
    except (OSError, json.JSONDecodeError):
        raise SystemExit(f'refusing to replace a non-generated directory: {out}')
    if (old.get('product') != 'CATS' or old.get('version') != version or
            old.get('channel') != 'GitHub release staging'):
        raise SystemExit(f'refusing to replace a non-generated directory: {out}')
    shutil.rmtree(out)
out.mkdir(parents=True, exist_ok=True)
artifact_records = []
for label, target, binary in [
    ('macos_arm64', 'macOS ARM64', args.mac_binary),
    ('linux_x86_64', 'Linux x86_64 (glibc 2.17 baseline)', args.linux_x64_binary),
    ('linux_aarch64', 'Linux AArch64 (Raspberry Pi OS/glibc 2.36 baseline)', args.linux_arm64_binary),
]:
    name = f'CATS-{version}-{label}.tar.gz'
    data, metadata = tar_bytes(binary, target)
    (out / name).write_bytes(data)
    artifact_records.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest(),
                             'bytes': len(data), 'target': target,
                             'binary': metadata['binary']})

windows_name = f'CATS-{version}-windows-x86_64.zip'
windows_data, windows_metadata = windows_zip_bytes(args.windows_x64_binary)
(out / windows_name).write_bytes(windows_data)
artifact_records.append({'name': windows_name, 'sha256': hashlib.sha256(windows_data).hexdigest(),
                         'bytes': len(windows_data), 'target': 'Windows x86_64 CLI',
                         'binary': windows_metadata['binary']})

for name, source, target in [
    (f'CATS-{version}-Source.tar.gz', args.source, 'portable source'),
    (f'CATS-{version}-GUI-Linux.tar.gz', args.linux_gui, 'Linux Python/Tk GUI'),
    (f'CATS-{version}-GUI-Windows.zip', args.windows_gui, 'Windows Python/Tk GUI'),
]:
    shutil.copyfile(source, out / name)
    data = (out / name).read_bytes()
    artifact_records.append({'name': name, 'sha256': hashlib.sha256(data).hexdigest(),
                             'bytes': len(data), 'target': target})

app_zip = out / f'CATS-{version}-GUI-macOS-ARM64.zip'
subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                str(args.mac_app), str(app_zip)], check=True)
app_data = app_zip.read_bytes()
artifact_records.append({'name': app_zip.name, 'sha256': hashlib.sha256(app_data).hexdigest(),
                         'bytes': len(app_data), 'target': 'macOS ARM64 CAT.app'})

validation = {
    'macOS ARM64': 'Native current-source make test passed: 201 CLI, 34 failure-injection, eight GUI archive checks, portable fixtures, compatibility, and static XF smoke.',
    'Linux x86_64 (glibc 2.17 baseline)': 'Production 0.4.0 cross-build passed all 201 integration checks on Ubuntu x86_64; artifact hash is recorded in docs/linux-x64-production-validation.json.',
    'Linux AArch64 (Raspberry Pi OS/glibc 2.36 baseline)': 'Production 0.4.0 native Pi build passed: 201 CLI, 34 failure-injection, eight GUI archive checks, transforms, and static XF smoke (docs/pi-aarch64-production-validation.json).',
    'Windows x86_64 CLI': 'Current-source PE x86_64 cross-build via make windows-x64-cross; native CLI runtime testing is deferred by user preference and is not claimed as runtime-tested (docs/release-validation.json).',
    'portable source': 'Deterministic source archive and standalone extracted-source build pass tests/packaging.py.',
    'Linux Python/Tk GUI': 'Linux package manifest and DESTDIR installation validated; native Pi Tk inspect/extract and Debian 13 portable reader fixture checks are recorded in docs/linux-gui-native-validation.json and docs/current-linux-x64-artifact-validation.json.',
    'Windows Python/Tk GUI': 'Windows 11 install, Start menu launch, .cat association, fixture inspection/extraction validated in docs/release-validation.json.',
    'macOS ARM64 CAT.app': 'Native app plist, UTI, icon, and executable bundle validation passed.',
}
for record in artifact_records:
    record['validation'] = validation[record['target']]

manifest = {
    'product': 'CATS', 'version': version, 'format': '0.7', 'compact_format': '0.8',
    'channel': 'GitHub release staging',
    'release_gate': 'required release validations are recorded as passed; native Windows CLI runtime is deferred by user preference and remote matrix automation is scheduled for 0.5',
    'artifacts': artifact_records,
    'deferred_checks': [{'target': 'Windows x64 CLI runtime', 'reason': 'The user deferred native Windows CLI runtime testing for 0.4; the x64 cross-build and Windows GUI runtime are validated.'}],
}
(out / 'ASSETS.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
(out / 'RELEASE-STATUS.txt').write_text(
    f'CATS {version} production release assets.\n'
    'Required release validations are recorded in docs/release-validation.json.\n'
    'Native Windows CLI runtime testing is deferred by user preference; no native\n'
    'Windows CLI runtime claim is made. Remote matrix automation is scheduled for 0.5.\n'
)
names = sorted(p.name for p in out.iterdir() if p.is_file() and p.name != 'SHA256SUMS')
names = [name for name in names if not name.startswith('._')]
(out / 'SHA256SUMS').write_text(''.join(
    f'{hashlib.sha256((out / name).read_bytes()).hexdigest()}  {name}\n' for name in names))
for sidecar in out.glob('._*'):
    if sidecar.is_file() or sidecar.is_symlink():
        sidecar.unlink()
print(f'Staged {len(artifact_records)} GitHub release assets in {out}')
