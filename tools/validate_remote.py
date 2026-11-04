"""Explicitly invoked SSH validation; never changes known-host trust or installs packages."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shlex
import subprocess
import tempfile
import tarfile
import time

parser=argparse.ArgumentParser()
parser.add_argument('target',help='user@host (IPv6 with optional %interface is supported)')
parser.add_argument('--host-key-alias')
parser.add_argument('--ipv4',action='store_true',help='avoid link-local IPv6 routing issues')
parser.add_argument('--modes',default='release,asan,lsan,tsan')
parser.add_argument('--jobs',type=int,default=1)
parser.add_argument('--cc',default='cc')
parser.add_argument('--report',default='docs/remote-validation.json')
args=parser.parse_args()
if args.target.startswith('-') or args.jobs<1:parser.error('invalid target/jobs')
modes=args.modes.split(',')
if any(mode not in ['release','asan','lsan','tsan'] for mode in modes):parser.error('invalid mode')
cat=Path(__file__).resolve().parent.parent
ssh=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','StrictHostKeyChecking=yes','-o','ServerAliveInterval=15','-o','ServerAliveCountMax=3']
if args.ipv4:ssh+=['-4']
if args.host_key_alias:ssh+=['-o','HostKeyAlias='+args.host_key_alias]
ssh+=[args.target]
remote=f'.cache/catc-validation/run-{time.time_ns()}'
quote=shlex.quote
results={'time_utc':datetime.now(timezone.utc).isoformat(),'remote_directory':remote,'results':{}}
with tempfile.TemporaryDirectory(prefix='cat-remote-source-') as td:
    bundle=Path(td)/'source.tar.gz'
    subprocess.run(['python3',str(cat/'tools/package.py'),'source','--output',str(bundle)],check=True)
    with bundle.open('rb') as source:
        subprocess.run(ssh+[f'mkdir -p {quote(remote)} && tar -xzf - -C {quote(remote)}'],stdin=source,check=True)
    with tarfile.open(bundle,'r:gz') as tar:bundle_root=tar.getmembers()[0].name.split('/')[0]
    work=remote+'/'+bundle_root+'/CAT'
    for mode in modes:
        target='leak-test' if mode=='lsan' else 'test'
        command=(f'cd {quote(work)} && '
            'ASAN_OPTIONS=quarantine_size_mb=16:thread_local_quarantine_size_kb=256 '
            'UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 '
            f'make -j{args.jobs} CC={quote(args.cc)} MODE={mode} {target}')
        completed=subprocess.run(ssh+[command],stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log=cat/'build'/('remote-'+mode+'.log');log.parent.mkdir(exist_ok=True);log.write_bytes(completed.stdout)
        results['results'][mode]={'exit_code':completed.returncode,'log':str(log.relative_to(cat))}
        print(mode,completed.returncode,completed.stdout.decode(errors='replace')[-2000:],flush=True)
report=cat/args.report;report.parent.mkdir(parents=True,exist_ok=True);report.write_text(json.dumps(results,indent=2)+'\n')
raise SystemExit(int(any(result['exit_code'] for result in results['results'].values())))
