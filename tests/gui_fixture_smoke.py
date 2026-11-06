"""Exercise Tk inspection and extraction without requiring a native CATS CLI."""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

repo = Path(__file__).resolve().parent.parent
gui_dir = Path(os.environ.get('CATS_GUI_DIR', repo / 'gui')).resolve()
sys.path.insert(0, str(gui_dir))
from cat_gui import CatWindow, messagebox  # noqa: E402

manifest = json.loads((repo / 'tests/golden/gui-fixture-manifest.json').read_text())
archive = repo / 'tests/golden/gui-v07.cat.gz'
expected = manifest['source_files']
errors = []
messagebox.showerror = lambda *args, **kwargs: errors.append(args)
messagebox.showinfo = lambda *args, **kwargs: None

import tkinter as tk

root = tk.Tk()
window = CatWindow(root, str(archive))
try:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        root.update()
        if not window.busy and (window.info is not None or errors):
            break
        time.sleep(0.02)
    assert window.info is not None, errors
    assert window.info.version == 7
    assert window.info.gzipped
    assert str(window.extract_button['state']) == 'normal'

    with tempfile.TemporaryDirectory(prefix='cats-gui-fixture-smoke-') as temporary:
        parent = Path(temporary) / 'output location'
        parent.mkdir()
        window.parent_var.set(str(parent))
        window.folder_var.set('restored with spaces')
        window.extract()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            root.update()
            if not window.busy:
                break
            time.sleep(0.02)
        assert not errors, errors
        destination = parent / 'restored with spaces'
        for relative, meta in expected.items():
            restored = destination.joinpath(*relative.split('/'))
            data = restored.read_bytes()
            assert len(data) == meta['size']
            assert hashlib.sha256(data).hexdigest() == meta['sha256']
            if os.name != 'nt':
                assert restored.stat().st_mode & 0o777 == meta['mode']
        assert (destination / 'fixture/empty/nested').is_dir()
finally:
    root.destroy()

print('PASS: Tk GUI inspected and extracted a current-format fixture with exact bytes')
