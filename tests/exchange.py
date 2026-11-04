"""Cross-machine exchange using a canonical fixture and the saved v0.1 archive."""
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

mode,binary,directory=sys.argv[1:4]
binary=str(Path(binary).resolve());root=Path(directory).resolve();root.mkdir(parents=True,exist_ok=True)
corpus=Path(__file__).resolve().parent/'golden'
manifest=json.loads((corpus/'manifest.json').read_text())
if mode=='generate':
    source=root/'fixture.bin';source.write_bytes(bytes(8192)+b'CAT golden\x00\xff\r\n');source.chmod(0o640)
    for flags,name in [('-e','exchange.cat'),('-eg','exchange.cat.gz')]:
        subprocess.run([binary,flags,str(source),str(root/name)],check=True,capture_output=True)
elif mode!='receive':raise SystemExit('mode must be generate or receive')
assert (root/'exchange.cat').read_bytes()==(corpus/'v01.cat').read_bytes(),'canonical raw archive differs across builds'
for name in ['exchange.cat','exchange.cat.gz']:
    restored=root/(name+'-restored')
    subprocess.run([binary,'-d',str(root/name),str(restored)],check=True,capture_output=True)
    file=restored/manifest['path']
    assert file.stat().st_size==manifest['size']
    assert file.stat().st_mode&0o777==manifest['mode']
    assert hashlib.sha256(file.read_bytes()).hexdigest()==manifest['sha256']
result={'status':'passed','mode':mode,'platform':platform.system()+'-'+platform.machine(),
        'version':subprocess.check_output([binary,'--version'],text=True).strip(),
        'raw_archive_byte_identical_to_v01':True,'restored_bytes_modes_and_sha256_match':True}
(root/'exchange-report.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
