import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

cat = Path(__file__).resolve().parent.parent
binary = str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='cat-package-test-') as td:
    t = Path(td)

    def package(kind, name):
        output = t / name
        subprocess.run([sys.executable, str(cat / 'tools/package.py'), kind,
                        '--binary', binary, '--output', str(output)], check=True, capture_output=True)
        assert output.with_name(output.name + '.sha256').read_text().split()[0] == hashlib.sha256(output.read_bytes()).hexdigest()
        return output

    a = package('source', 'a.tar.gz')
    b = package('source', 'b.tar.gz')
    assert a.read_bytes() == b.read_bytes(), 'source bundle is not reproducible'
    binary_bundle = package('binary', 'binary.tar.gz')
    for archive in [a, binary_bundle]:
        with tarfile.open(archive, 'r:gz') as tar:
            members = tar.getmembers()
            assert all(m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts for m in members)
            manifests = [m for m in members if m.name.endswith('/BUILD-MANIFEST.json')]
            assert len(manifests) == 1
            manifest = json.load(tar.extractfile(manifests[0]))
            prefix = manifests[0].name.removesuffix('BUILD-MANIFEST.json')
            for name, digest in manifest['sha256'].items():
                assert hashlib.sha256(tar.extractfile(prefix + name).read()).hexdigest() == digest

    windows_a = t / 'windows-a.zip'
    windows_b = t / 'windows-b.zip'
    command = [sys.executable, str(cat / 'tools/package_windows_gui.py')]
    subprocess.run(command + ['--output', str(windows_a)], check=True, capture_output=True)
    subprocess.run(command + ['--output', str(windows_b)], check=True, capture_output=True)
    assert windows_a.read_bytes() == windows_b.read_bytes(), 'Windows GUI bundle is not reproducible'
    assert windows_a.with_name(windows_a.name + '.sha256').read_text().split()[0] == hashlib.sha256(windows_a.read_bytes()).hexdigest()
    with zipfile.ZipFile(windows_a) as archive:
        names = archive.namelist()
        assert all(not name.startswith('/') and '..' not in Path(name).parts for name in names)
        manifests = [name for name in names if name.endswith('/BUILD-MANIFEST.json')]
        assert len(manifests) == 1
        manifest_path = manifests[0]
        manifest = json.loads(archive.read(manifest_path))
        prefix = manifest['bundle'] + '/'
        for name, digest in manifest['sha256'].items():
            assert hashlib.sha256(archive.read(prefix + name)).hexdigest() == digest
        expected = {
            'README.txt', 'LICENSE', 'THIRD_PARTY.md',
            'gui/cat_gui.py', 'gui/cat_archive.py',
            'packaging/windows/install-gui.ps1', 'packaging/windows/CATDoc.ico',
        }
        assert expected.issubset(set(manifest['sha256']))
        assert any(name.startswith('licenses/') for name in manifest['sha256'])

    # Build the complete extracted source without relying on the workspace's
    # original XF path. All members were validated as regular relative files.
    unpacked = t / 'unpacked'
    unpacked.mkdir()
    with tarfile.open(a, 'r:gz') as tar:
        for member in tar:
            target = unpacked / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
    source_cat = next(unpacked.glob('*/CAT'))
    build_env = dict(os.environ)
    for name in ('MAKEFLAGS', 'MFLAGS', 'MAKEOVERRIDES'):
        build_env.pop(name, None)
    build = subprocess.run(['make', '-C', str(source_cat), '-j2', 'all'],
                           capture_output=True, env=build_env)
    assert build.returncode == 0, build.stderr.decode(errors='replace')[-4000:]
    canonical_version = subprocess.check_output([str(source_cat / 'bin/cats'), '--version'], text=True)
    legacy_version = subprocess.check_output([str(source_cat / 'bin/catc'), '--version'], text=True)
    assert canonical_version.startswith('cats ') and legacy_version == canonical_version
    assert (source_cat / 'bin/catc').is_symlink()
print('PASS: deterministic source, binary, and Windows GUI bundles; checksums and standalone source build')
