"""Run native validation sequentially. No package installation or host configuration changes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import time

parser=argparse.ArgumentParser()
parser.add_argument('--cc',default='cc')
parser.add_argument('--jobs',type=int,default=1)
parser.add_argument('--modes',default='release,lsan,asan,tsan')
args=parser.parse_args()
if args.jobs<1:parser.error('jobs must be positive')
modes=args.modes.split(',')
if any(m not in ['release','lsan','asan','tsan'] for m in modes):parser.error('invalid mode')
cat=Path(__file__).resolve().parent.parent
os.chdir(cat);build=cat/'build';build.mkdir(exist_ok=True)
report=build/'native-validation.json'
result={'platform':platform.platform(),'machine':platform.machine(),'compiler':subprocess.check_output([args.cc,'--version'],text=True).splitlines()[0],
        'modes':{},'policy':'single-job by default; dedicated persistent LSan checks; native ASan uses detect_leaks=0 because LSan is separate'}
model=Path('/proc/device-tree/model')
if model.exists():result['model']=model.read_text().strip('\0\n')
# Fingerprint the actual code/build inputs, excluding docs, binaries and metadata sidecars.
paths=[]
for root in [cat/'src',cat.parent/'XF/src',cat.parent/'XF/include',cat.parent/'XF/public',
             cat.parent/'XF/vendor/lambdaScript/src',cat.parent/'XF/vendor/lambdaScript/include']:
    paths += [p for p in root.rglob('*') if p.is_file() and not p.name.startswith('._') and p.suffix in ['.c','.h']]
paths += [cat/'Makefile',cat/'lib/Table.xf']+[cat.parent/'XF/lib'/name for name in ['api.c','api.h','driver.c','driver.h']]
h=hashlib.sha256()
for path in sorted(paths):h.update(str(path.relative_to(cat.parent)).encode()+b'\0'+path.read_bytes()+b'\0')
result['code_sha256']=h.hexdigest()
def save():report.write_text(json.dumps(result,indent=2)+'\n')
def run(command,log,env,timeout=1800):
    with log.open('wb') as output:
        child=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:return child.wait(timeout=timeout)
        except (subprocess.TimeoutExpired,KeyboardInterrupt):
            os.killpg(child.pid,signal.SIGTERM)
            try:child.wait(timeout=10)
            except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
            raise
for mode in modes:
    env=dict(os.environ,UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    if mode=='asan':env['ASAN_OPTIONS']='detect_leaks=0:quarantine_size_mb=16:thread_local_quarantine_size_kb=256'
    if mode=='lsan':env['LSAN_OPTIONS']='exitcode=23'
    if mode=='tsan':env['TSAN_OPTIONS']='halt_on_error=1'
    if mode in ['asan','tsan']:
        probe=build/('probe-'+mode);source=build/'sanitizer-probe.c';source.write_text('int main(void){return 0;}\n')
        log=build/('probe-'+mode+'.log');flag='address,undefined' if mode=='asan' else 'thread'
        code=run([args.cc,'-fsanitize='+flag,str(source),'-o',str(probe)],log,env)
        if not code:code=run([str(probe)],log,env,60)
        if code:
            result['modes'][mode]={'status':'unsupported','exit_code':code,'log':log.name,'detail':log.read_text(errors='replace')[-3000:]}
            save();print(mode,'runtime probe failed:',result['modes'][mode]['detail'],flush=True);continue
    target='leak-test' if mode=='lsan' else 'test'
    log=build/('native-'+mode+'.log');started=time.monotonic()
    code=run(['make',f'-j{args.jobs}','CC='+args.cc,'MODE='+mode,'BUILD=build/gcc-'+mode,
              'BIN=bin/gcc-'+mode+'/cats',target],log,env)
    result['modes'][mode]={'status':'passed' if code==0 else 'failed','exit_code':code,'seconds':round(time.monotonic()-started,3),'target':target,'log':log.name}
    save();print(mode,result['modes'][mode],flush=True);print(log.read_text(errors='replace')[-3500:],flush=True)
print('Native report:',report,flush=True)
raise SystemExit(int(any(item['status']!='passed' for item in result['modes'].values())))
