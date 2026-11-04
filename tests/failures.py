"""Fault hooks exist only in the CAT_TESTING binary, never the release binary."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

binary, production = map(lambda p:str(Path(p).resolve()), sys.argv[1:3])
checks = 0

def run(*args, env=None, expected=1, executable=binary):
    global checks
    variables = dict(os.environ, UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
    variables.update(env or {})
    p = subprocess.run([executable, *map(str,args)], capture_output=True, env=variables, timeout=30)
    assert p.returncode == expected, (args,p.returncode,p.stderr)
    assert b'Sanitizer' not in p.stderr and b'runtime error:' not in p.stderr, p.stderr
    checks += 1
    return p

def stopped(args, hook, mutate=None, terminate=False, extra=None):
    global checks
    env = dict(os.environ, CAT_TEST_HOOK=hook, UBSAN_OPTIONS='halt_on_error=1')
    env.update(extra or {})
    p = subprocess.Popen([binary,*map(str,args)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
    deadline = time.monotonic()+30
    try:
        while time.monotonic()<deadline:
            got,status = os.waitpid(p.pid,os.WNOHANG|os.WUNTRACED)
            if got:
                assert os.WIFSTOPPED(status), (hook,status)
                break
            time.sleep(.01)
        else: raise AssertionError(f'no hook stop: {hook}')
        if mutate: mutate()
        if terminate: p.send_signal(signal.SIGTERM)
        p.send_signal(signal.SIGCONT)
        _,error = p.communicate(timeout=30)
        assert p.returncode == (143 if terminate else 1), (hook,p.returncode,error)
        assert b'Sanitizer' not in error and b'runtime error:' not in error,error
        checks += 1
    finally:
        if p.poll() is None:
            p.kill();p.communicate()

def no_stages(root):
    assert not list(root.glob('*.tmp.*')), list(root.glob('*.tmp.*'))
    assert not list(root.glob('catc-spool.*')), 'anonymous scratch file was not unlinked'

with tempfile.TemporaryDirectory(prefix='cat-failures-') as td:
    t=Path(td);source=t/'source';source.mkdir()
    (source/'data').write_bytes(b'archive content\x00\xff'*500)
    archive=t/'good.cat'
    run('-eg',source,archive,expected=0)
    for limits in [('--max-bytes','1'),('--max-archive-bytes','16'),('--max-temp-bytes','1')]:
        run('-eg',*limits,source,t/'limited.cat');assert not (t/'limited.cat').exists();no_stages(t)
    for flag in ['--max-bytes','--max-archive-bytes','--max-temp-bytes']:
        for value in ['0','-1','1x','18446744073709551616']:
            run('-e',flag,value,source,t/'bad.cat',expected=2)
    for stage in [None,'archive-copy']:
        env={'CAT_TEST_WRITE_LIMIT':'64','TMPDIR':str(t)}
        if stage:env['CAT_TEST_WRITE_STAGE']=stage
        p=run('-e',source,t/'full.cat',env=env)
        assert b'disk-full' in p.stderr
        assert not (t/'full.cat').exists();no_stages(t)
    run('-e',source,t/'sync.cat',env={'CAT_TEST_SYNC_FAIL':'1'})
    assert not (t/'sync.cat').exists();no_stages(t)
    run('-d',archive,t/'full-out',env={'CAT_TEST_WRITE_STAGE':'extraction-copy','CAT_TEST_WRITE_LIMIT':'100'})
    assert not (t/'full-out').exists();no_stages(t)
    run('-d',archive,t/'permission-out',env={'CAT_TEST_CHMOD_FAIL':'1'})
    assert not (t/'permission-out').exists();no_stages(t)
    # Existing destinations survive every failure path.
    sentinel=t/'existing.cat';sentinel.write_bytes(b'keep me')
    run('-e',source,sentinel,env={'CAT_TEST_PORTABLE':'1'})
    assert sentinel.read_bytes()==b'keep me'
    # Source mutation is coordinated at a deterministic point, rather than racing.
    mutable=t/'mutable';mutable.write_bytes(b'a'*128)
    stopped(['-e',mutable,t/'changed.cat'],'source-read',mutate=lambda:mutable.write_bytes(b'b'*128))
    assert not (t/'changed.cat').exists();no_stages(t)
    stopped(['-e',source,t/'interrupted.cat'],'archive-staged',terminate=True)
    assert not (t/'interrupted.cat').exists();no_stages(t)
    stopped(['-d',archive,t/'interrupted-out'],'extraction-staged',terminate=True)
    assert not (t/'interrupted-out').exists();no_stages(t)
    stopped(['-e',source,t/'published.cat'],'published',terminate=True)
    run('-v',t/'published.cat',expected=0)
    stopped(['-d',archive,t/'published-out'],'published',terminate=True)
    assert (t/'published-out'/'source'/'data').read_bytes()==(source/'data').read_bytes()
    no_stages(t)
    # Exercise the mounted-filesystem fallback independently of host capabilities.
    stopped(['-e',source,t/'reserved.cat'],'destination-reserved',terminate=True,extra={'CAT_TEST_PORTABLE':'1'})
    assert not (t/'reserved.cat').exists();no_stages(t)
    stopped(['-d',archive,t/'reserved-out'],'destination-reserved',terminate=True,extra={'CAT_TEST_PORTABLE':'1'})
    assert not (t/'reserved-out').exists();no_stages(t)
    run('-e','--require-atomic',source,t/'atomic.cat',env={'CAT_TEST_PORTABLE':'1'})
    assert not (t/'atomic.cat').exists();no_stages(t)
    run('-e',source,t/'portable.cat',env={'CAT_TEST_PORTABLE':'1'},expected=0)
    run('-d',t/'portable.cat',t/'portable-out',env={'CAT_TEST_PORTABLE':'1'},expected=0)
    assert (t/'portable-out'/'source'/'data').read_bytes()==(source/'data').read_bytes()
    # Production builds must ignore all test-only environment hooks.
    run('-e',source,t/'production.cat',env={'CAT_TEST_WRITE_LIMIT':'0','CAT_TEST_SYNC_FAIL':'1','CAT_TEST_CHMOD_FAIL':'1'},expected=0,executable=production)
    no_stages(t)
print(f'PASS: {checks} failure checks; disk-full/sync errors, source mutation, cancellation, cleanup, no-overwrite, atomic policy and budgets')
