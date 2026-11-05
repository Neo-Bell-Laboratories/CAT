"""Reproducible source and private development bundles with per-file SHA-256."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import tarfile

parser=argparse.ArgumentParser()
parser.add_argument('kind',choices=['source','binary'])
parser.add_argument('--output',required=True)
parser.add_argument('--binary',default='bin/catc')
args=parser.parse_args()
cat=Path(__file__).resolve().parent.parent;workspace=cat.parent
version=re.search(r'#define CAT_VERSION "([^"]+)"',(cat/'src/catc.c').read_text()).group(1)
root=f'catc-{version}'
epoch=int(os.environ.get('SOURCE_DATE_EPOCH','0'))
files={}
def collect(path):
    if path.is_symlink():raise ValueError(f'symlink in package input: {path}')
    if path.is_dir():
        for child in sorted(path.iterdir()):
            if child.name.startswith('._') or child.name in ['.DS_Store','__pycache__']:continue
            collect(child)
    elif path.is_file():files[str(path.relative_to(workspace))]=path.read_bytes()
if args.kind=='source':
    for name in ['src','lib','gui','tests','tools','docs','packaging','Makefile','README.md','LICENSE','THIRD_PARTY.md','licenses']:
        collect(cat/name)
    for name in ['src','include','public','lib/api.c','lib/api.h','lib/driver.c','lib/driver.h',
                 'vendor/lambdaScript/src','vendor/lambdaScript/include']:
        collect(workspace/'XF'/name)
    workflow=workspace/'.github/workflows/cat.yml'
    if workflow.exists():collect(workflow)
    for path in [workspace/'XF/LICENSE',workspace/'XF/vendor/lambdaScript/LICENSE']:
        if path.exists():collect(path)
else:
    binary=Path(args.binary).resolve()
    files['bin/catc']=binary.read_bytes()
    for name in ['LICENSE','THIRD_PARTY.md']:files[name]=(cat/name).read_bytes()
    files['README.md']=(
        '# catc development binary bundle\n\n'
        'Platform: '+platform.system()+' '+platform.machine()+'\n\n'
        'No compilation is needed for this bundle. From this directory:\n\n'
        '```sh\n./bin/catc --version\n./bin/catc -eg INPUT OUTPUT.cat.gz\n'
        './bin/catc -d OUTPUT.cat.gz NEW_OUTPUT_DIRECTORY\n```\n\n'
        'The binary requires compatible system libc/math/pthreads/zlib libraries; '
        'BUILD-MANIFEST.json records dependencies and file hashes.\n\n'
        'See docs/PROJECT.md for the preservation contract, limits and source build '
        'instructions, and THIRD_PARTY.md for license notices. '
        'Review recorded validation results before production use; packaging does not publish a release.\n').encode()
    files['docs/PROJECT.md']=(cat/'README.md').read_text().replace('](docs/', '](').encode()
    for path in (cat/'licenses').glob('[!._]*.txt'):files['licenses/'+path.name]=path.read_bytes()
    for path in (cat/'docs').iterdir():
        if path.is_file() and not path.name.startswith('._') and path.suffix in ['.md','.json']:files['docs/'+path.name]=path.read_bytes()
metadata={
    'version':version,'kind':args.kind,'status':'development-validation; production release requires completed release gates',
    'platform':platform.system()+'-'+platform.machine() if args.kind=='binary' else 'portable-source',
    'format':'0.1','source_date_epoch':epoch,'build_os_release':platform.release(),
    'license_review':{'CAT':'MIT','XF':'MIT first-party; project-owner confirmation recorded' if (workspace/'XF/LICENSE').exists() else 'missing license/provenance confirmation',
                      'LambdaScript':'MIT first-party; project-owner confirmation recorded' if (workspace/'XF/vendor/lambdaScript/LICENSE').exists() else 'missing license/provenance confirmation','zlib':'system dependency; zlib license','stb':'original embedded notices'},
    'sha256':{name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())},
}
if args.kind=='binary':
    metadata['runtime_version']=subprocess.check_output([str(binary),'--version'],text=True).strip()
    command=['otool','-L',str(binary)] if platform.system()=='Darwin' else ['ldd',str(binary)]
    metadata['runtime_dependencies']=subprocess.check_output(command,text=True).replace(str(binary),'bin/catc')
files['BUILD-MANIFEST.json']=(json.dumps(metadata,indent=2,sort_keys=True)+'\n').encode()
output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
temp=output.with_name(output.name+'.tmp')
try:
    with temp.open('wb') as f,gzip.GzipFile(fileobj=f,mode='wb',filename='',mtime=epoch) as gz,tarfile.open(fileobj=gz,mode='w',format=tarfile.USTAR_FORMAT) as tar:
        for name,data in sorted(files.items()):
            info=tarfile.TarInfo(root+'/'+name);info.size=len(data);info.mtime=epoch
            info.mode=0o755 if name=='bin/catc' else 0o644
            tar.addfile(info,io.BytesIO(data))
    os.replace(temp,output)
finally:
    temp.unlink(missing_ok=True)
digest=hashlib.sha256(output.read_bytes()).hexdigest()
output.with_name(output.name+'.sha256').write_text(digest+'  '+output.name+'\n')
print(f'{output}  sha256={digest}')
