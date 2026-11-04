from pathlib import Path
import gzip
import struct
import sys
root=Path(sys.argv[1]);archive=root/'archive-corpus';tree=root/'tree-corpus'
archive.mkdir(parents=True,exist_ok=True);tree.mkdir(parents=True,exist_ok=True)
for path in (Path(__file__).resolve().parent.parent/'tests/golden').glob('*.cat*'):
    (archive/path.name).write_bytes(path.read_bytes())
# Valid one-bucket 4096-byte tree: length, count, byte, runs, gap, run length.
(tree/'zeros').write_bytes(struct.pack('>H',4096)+b'\x80\x20\x01\x00\x01\x00\x80\x20')
(tree/'empty').write_bytes(b'\x00\x00\x00\x00')
(archive/'bad-gzip').write_bytes(b'\x1f\x8b\x08\x00')
(archive/'non-cat-gzip').write_bytes(gzip.compress(b'not a cat archive',mtime=0))
