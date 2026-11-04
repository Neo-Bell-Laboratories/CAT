import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

cat=Path(__file__).resolve().parent.parent
binary=str(Path(sys.argv[1]).resolve())
with tempfile.TemporaryDirectory(prefix='cat-package-test-') as td:
    t=Path(td)
    def package(kind,name):
        output=t/name
        subprocess.run([sys.executable,str(cat/'tools/package.py'),kind,'--binary',binary,'--output',str(output)],check=True,capture_output=True)
        assert output.with_name(output.name+'.sha256').read_text().split()[0]==hashlib.sha256(output.read_bytes()).hexdigest()
        return output
    a=package('source','a.tar.gz');b=package('source','b.tar.gz')
    assert a.read_bytes()==b.read_bytes(),'source bundle is not reproducible'
    binary_bundle=package('binary','binary.tar.gz')
    for archive in [a,binary_bundle]:
        with tarfile.open(archive,'r:gz') as tar:
            members=tar.getmembers()
            assert all(m.isfile() and not m.name.startswith('/') and '..' not in Path(m.name).parts for m in members)
            manifests=[m for m in members if m.name.endswith('/BUILD-MANIFEST.json')]
            assert len(manifests)==1
            manifest=json.load(tar.extractfile(manifests[0]))
            prefix=manifests[0].name.removesuffix('BUILD-MANIFEST.json')
            for name,digest in manifest['sha256'].items():
                assert hashlib.sha256(tar.extractfile(prefix+name).read()).hexdigest()==digest
    # Build the complete extracted source without relying on the workspace's
    # original XF path. All members were validated as regular relative files.
    unpacked=t/'unpacked';unpacked.mkdir()
    with tarfile.open(a,'r:gz') as tar:
        for member in tar:
            target=unpacked/member.name;target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
    source_cat=next(unpacked.glob('*/CAT'))
    build=subprocess.run(['make','-C',str(source_cat),'-j2','all'],capture_output=True)
    assert build.returncode==0,build.stderr.decode(errors='replace')[-4000:]
    subprocess.run([str(source_cat/'bin/catc'),'--version'],check=True)
print('PASS: deterministic source archive, binary bundle, per-file checksums and standalone source build')
