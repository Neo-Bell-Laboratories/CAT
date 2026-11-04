"""Focused CLI leak paths; persistent harness avoids hundreds of LSan startups on Pi."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
binary,testing=map(lambda p:str(Path(p).resolve()),sys.argv[1:3])
env=dict(os.environ,LSAN_OPTIONS='exitcode=23')
with tempfile.TemporaryDirectory(prefix='cat-native-leaks-') as td:
    root=Path(td);source=root/'source';source.mkdir();(source/'data').write_bytes(bytes(8192)+b'leak check')
    def run(exe,*args,expected=0,extra=None):
        values=dict(env);values.update(extra or {})
        p=subprocess.run([exe,*map(str,args)],env=values,capture_output=True,timeout=180)
        assert p.returncode==expected,(args,p.returncode,p.stderr.decode(errors='replace'))
        assert b'LeakSanitizer' not in p.stderr and b'Sanitizer' not in p.stderr,p.stderr
    run(binary,'-eg',source,root/'archive.cat.gz')
    run(binary,'-v',root/'archive.cat.gz')
    run(binary,'-d',root/'archive.cat.gz',root/'out')
    assert (root/'out'/'source'/'data').read_bytes()==(source/'data').read_bytes()
    run(testing,'-d',root/'archive.cat.gz',root/'failed-out',expected=1,
        extra={'CAT_TEST_WRITE_STAGE':'extraction-copy','CAT_TEST_WRITE_LIMIT':'32'})
    assert not (root/'failed-out').exists()
    run(testing,'-e',source,root/'failed.cat',expected=1,extra={'CAT_TEST_WRITE_LIMIT':'32'})
    assert not (root/'failed.cat').exists()
    os.mkfifo(root/'pipe')
    run(binary,'-v',root/'pipe',expected=1)
    run(binary,'-d',root/'pipe',root/'pipe-out',expected=1)
    assert not (root/'pipe-out').exists()
print('PASS: native CLI leak paths: encode, gzip, verify, decode and failed staging cleanup')
