"""Cross-platform GUI decoder checks using archives made by the current C encoder."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
import cat_archive

root = Path(__file__).resolve().parent
manifest = json.loads((root / 'golden/gui-fixture-manifest.json').read_text())
source_files = manifest['source_files']
expected_paths = set(manifest['directories']) | set(source_files)

for archive_name, expected in manifest['archives'].items():
    archive = root / 'golden' / archive_name
    info = cat_archive.inspect_archive(archive)
    assert info.version == expected['version'], (archive_name, info.version)
    assert info.gzipped == expected['gzipped'], archive_name
    assert hashlib.sha256(archive.read_bytes()).hexdigest() == expected['sha256'], archive_name
    assert {entry.path for entry in info.entries} == expected_paths, archive_name
    assert info.total_bytes == sum(meta['size'] for meta in source_files.values()), archive_name

    with tempfile.TemporaryDirectory(prefix='cats-gui-portable-') as temporary:
        destination = Path(temporary) / 'restored with spaces'
        cat_archive.extract_archive(archive, destination)
        for relative in manifest['directories']:
            assert destination.joinpath(*relative.split('/')).is_dir(), (archive_name, relative)
        for relative, meta in source_files.items():
            restored = destination.joinpath(*relative.split('/'))
            data = restored.read_bytes()
            assert len(data) == meta['size'], (archive_name, relative)
            assert hashlib.sha256(data).hexdigest() == meta['sha256'], (archive_name, relative)
            if os.name != 'nt':
                assert restored.stat().st_mode & 0o777 == meta['mode'], (archive_name, relative)

print('PASS: portable GUI reader verified v0.7/v0.8 plain/gzip fixtures, paths, bytes, and supported modes')
