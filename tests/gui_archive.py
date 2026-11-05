"""Cross-platform GUI decoder checks against CAT's native encoder."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import unittest.mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'gui'))
import cat_archive


class GuiArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='cat-gui-archive-')
        self.root = Path(self.temp.name)
        self.binary = Path(sys.argv[1]).resolve()
        self.source_file = self.root / 'song with spaces.bin'
        self.source_file.write_bytes(bytes(range(256)) * 80 + b'\x00tail')
        self.tree = self.root / 'tree'
        (self.tree / 'empty' / 'nested').mkdir(parents=True)
        (self.tree / 'mixed.txt').write_text('GUI extraction stays lossless\n')
        self.archive = self.root / 'multi.cat.gz'
        subprocess.run([str(self.binary), '-eg', str(self.source_file), str(self.tree),
                        '--output', str(self.archive)], check=True, capture_output=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_inspect_and_extract_multiroot_gzip(self):
        info = cat_archive.inspect_archive(self.archive)
        self.assertEqual(info.version, 7)
        self.assertTrue(info.gzipped)
        self.assertEqual(len(info.entries), 5)
        self.assertEqual(info.total_bytes,
                         self.source_file.stat().st_size + (self.tree / 'mixed.txt').stat().st_size)
        destination = self.root / 'restored'
        cat_archive.extract_archive(self.archive, destination)
        self.assertEqual((destination / self.source_file.name).read_bytes(),
                         self.source_file.read_bytes())
        self.assertEqual((destination / 'tree' / 'mixed.txt').read_bytes(),
                         (self.tree / 'mixed.txt').read_bytes())
        self.assertTrue((destination / 'tree' / 'empty' / 'nested').is_dir())

    def test_old_plain_and_gzip_golden_archives(self):
        golden = Path(__file__).resolve().parent / 'golden'
        for name in ('v01.cat', 'v01.cat.gz'):
            info = cat_archive.inspect_archive(golden / name)
            self.assertEqual(info.version, 1)
            out = self.root / (name.replace('.', '-') + '-out')
            cat_archive.extract_archive(golden / name, out)
            manifest = json.loads((golden / 'manifest.json').read_text())
            restored = out / manifest['path']
            self.assertEqual(restored.stat().st_size, manifest['size'])
            self.assertEqual(hashlib.sha256(restored.read_bytes()).hexdigest(), manifest['sha256'])

    def test_bad_outer_hash_fails_before_output(self):
        damaged = self.root / 'bad.cat'
        data = bytearray(gzip.decompress(self.archive.read_bytes()))
        data[-1] ^= 1
        damaged.write_bytes(data)
        output = self.root / 'should-not-exist'
        with self.assertRaises(cat_archive.ArchiveError):
            cat_archive.extract_archive(damaged, output)
        self.assertFalse(output.exists())

    def test_existing_destination_is_never_overwritten(self):
        destination = self.root / 'existing'
        destination.mkdir()
        (destination / 'keep.txt').write_text('keep')
        with self.assertRaises(cat_archive.ArchiveError):
            cat_archive.extract_archive(self.archive, destination)
        self.assertEqual((destination / 'keep.txt').read_text(), 'keep')

    def test_windows_path_restrictions(self):
        class FakeEntry:
            def __init__(self, path):
                self.path_bytes = path.encode('utf-8')
                self.path = path
        for name in ('folder/CON.txt', 'folder/has:colon', 'folder/trailing.'):
            with self.subTest(name=name), unittest.mock.patch.object(cat_archive.os, 'name', 'nt'):
                with self.assertRaises(cat_archive.ArchiveError):
                    cat_archive._validate_windows_names([FakeEntry(name)])


if __name__ == '__main__':
    unittest.main(argv=[sys.argv[0]], verbosity=2)
