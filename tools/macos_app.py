"""Assemble a macOS Finder app bundle for CAT archive inspection."""
import argparse
from pathlib import Path
import plistlib
import platform
import re
import shutil
import subprocess
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--binary', default='bin/cats')
parser.add_argument('--output', default='build/macos/CAT.app')
args = parser.parse_args()

if platform.system() != 'Darwin':
    sys.exit('CATS.app packaging requires macOS')

cat = Path(__file__).resolve().parent.parent
binary = Path(args.binary).resolve()
output = Path(args.output).resolve()
packaging = cat / 'packaging' / 'macos'
if not binary.is_file():
    sys.exit(f'CATS binary not found: {binary}')
if any(not (packaging / name).is_file() for name in (
        'CAT.m', 'CAT.icns', 'CAT.svg', 'CATDoc.icns', 'CATDoc.svg')):
    sys.exit('macOS app resources are incomplete')
version_match = re.search(r'#define CAT_VERSION "([^"]+)"', (cat / 'src' / 'catc.c').read_text())
if not version_match:
    sys.exit('cannot determine CATS version')
version = version_match.group(1)
build_version = re.match(r'\d+(?:\.\d+)*', version)
if not build_version:
    sys.exit(f'CATS version cannot be represented as a bundle version: {version}')

contents = output / 'Contents'
macos = contents / 'MacOS'
resources = contents / 'Resources'
if output.exists():
    if output.is_symlink() or not output.is_dir():
        sys.exit(f'refusing to replace non-directory app output: {output}')
    shutil.rmtree(output)
macos.mkdir(parents=True)
resources.mkdir(parents=True)
output.chmod(0o755)
contents.chmod(0o755)
macos.chmod(0o755)
resources.chmod(0o755)

launcher = macos / 'CAT'
try:
    subprocess.run([
        'clang', '-fobjc-arc', '-Wall', '-Wextra', '-O2',
        str(packaging / 'CAT.m'), '-framework', 'Cocoa',
        '-framework', 'UniformTypeIdentifiers', '-o', str(launcher),
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
except (OSError, subprocess.CalledProcessError) as error:
    if isinstance(error, subprocess.CalledProcessError) and error.stderr:
        sys.stderr.write(error.stderr.decode('utf-8', errors='replace'))
    sys.exit('macOS app build requires clang and the macOS Cocoa SDK')
launcher.chmod(0o755)
cli = resources / 'cats'
shutil.copyfile(binary, cli)
cli.chmod(0o755)
for name in ('CAT.icns', 'CAT.svg', 'CATDoc.icns', 'CATDoc.svg'):
    shutil.copyfile(packaging / name, resources / name)
shutil.copyfile(cat / 'LICENSE', resources / 'LICENSE')
shutil.copyfile(cat / 'THIRD_PARTY.md', resources / 'THIRD_PARTY.md')
uti = 'com.kenseitehdev.cat-archive'
info = {
    'CFBundleDevelopmentRegion': 'en',
    'CFBundleExecutable': 'CAT',
    'CFBundleIconFile': 'CAT.icns',
    'CFBundleIdentifier': 'com.kenseitehdev.cat',
    'CFBundleInfoDictionaryVersion': '6.0',
    'CFBundleName': 'CATS',
    'CFBundleDisplayName': 'CATS — Compression Aggregate Tree System',
    'CFBundlePackageType': 'APPL',
    'CFBundleShortVersionString': version,
    'CFBundleVersion': build_version.group(0),
    'LSApplicationCategoryType': 'public.app-category.utilities',
    'CFBundleDocumentTypes': [{
        'CFBundleTypeName': 'CATS Archive',
        'CFBundleTypeIconFile': 'CATDoc.icns',
        'CFBundleTypeRole': 'Viewer',
        'LSHandlerRank': 'Owner',
        'LSItemContentTypes': [uti],
    }],
    'UTExportedTypeDeclarations': [{
        'UTTypeIdentifier': uti,
        'UTTypeDescription': 'CATS Compressed Aggregate Tree Archive',
        'UTTypeIconFile': 'CATDoc.icns',
        'UTTypeConformsTo': ['public.data', 'public.archive'],
        'UTTypeTagSpecification': {
            'public.filename-extension': ['cat'],
            'public.mime-type': ['application/x-cat'],
        },
    }],
}
with (contents / 'Info.plist').open('wb') as f:
    plistlib.dump(info, f, fmt=plistlib.FMT_XML, sort_keys=False)
(contents / 'Info.plist').chmod(0o644)
(contents / 'PkgInfo').write_bytes(b'APPL????')
(contents / 'PkgInfo').chmod(0o644)
for resource in resources.iterdir():
    resource.chmod(0o755 if resource.name == 'cats' else 0o644)
subprocess.run(['plutil', '-lint', str(contents / 'Info.plist')], check=True)
print(f'Built native macOS CATS archive extractor {output} with CAT {version}')
