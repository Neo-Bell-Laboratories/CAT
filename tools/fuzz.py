"""Run bounded coverage-guided fuzzing and retain crashes/logs for review."""
import argparse
import os
import shutil
import tempfile
from pathlib import Path
import subprocess
import sys

parser=argparse.ArgumentParser()
parser.add_argument('binary')
parser.add_argument('corpus')
parser.add_argument('--seconds',type=int,default=60)
args=parser.parse_args()
binary=Path(args.binary).resolve();corpus=Path(args.corpus).resolve();corpus.mkdir(parents=True,exist_ok=True)
artifact_root=binary.parent/'fuzz-artifacts';artifact_root.mkdir(exist_ok=True)
artifacts=Path(tempfile.mkdtemp(prefix=binary.name+'-',dir=artifact_root))
log=artifacts/'run.log'
env=dict(os.environ)
env['ASAN_OPTIONS']=env.get('ASAN_OPTIONS','')+':quarantine_size_mb=32:thread_local_quarantine_size_kb=256'
symbolizer=Path('/opt/homebrew/opt/llvm/bin/llvm-symbolizer')
if symbolizer.exists():env['ASAN_SYMBOLIZER_PATH']=str(symbolizer)
with log.open('w') as output:
    result=subprocess.run([str(binary),str(corpus),f'-max_total_time={args.seconds}',
        '-max_len=65536','-timeout=10','-rss_limit_mb=512','-print_final_stats=1',f'-artifact_prefix={artifacts}/'],
        stdout=output,stderr=subprocess.STDOUT,env=env)
lines=log.read_text(errors='replace').splitlines()
print('\n'.join(lines[-12:]))
print(f'Fuzz log: {log}')
if result.returncode: sys.exit(result.returncode)
assert not any(p.name!='run.log' and not p.name.startswith('._') and p.name!='.DS_Store' for p in artifacts.iterdir()),f'fuzz findings in {artifacts}'
