"""Exercise CAT's Tk window under a real or virtual X display."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

repo = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo / 'gui'))
from cat_gui import CatWindow, messagebox  # noqa: E402

binary = str(Path(sys.argv[1]).resolve())
errors = []
messagebox.showerror = lambda *args, **kwargs: errors.append(args)
messagebox.showinfo = lambda *args, **kwargs: None


def pump_until(root, predicate, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError('GUI operation timed out')


with tempfile.TemporaryDirectory(prefix='cat-gui-smoke-') as temporary:
    root_dir = Path(temporary)
    source = root_dir / 'source file.bin'
    archive = root_dir / 'sample.cat'
    destination_parent = root_dir / 'output location'
    payload = b'CAT graphical smoke test\x00\xff\r\n' * 4096
    source.write_bytes(payload)
    source.chmod(0o640)
    subprocess.run([binary, '-e', str(source), '--output', str(archive)],
                   check=True, capture_output=True)

    import tkinter as tk
    root = tk.Tk()
    window = CatWindow(root, str(archive))
    try:
        pump_until(root, lambda: not window.busy and (window.info is not None or errors))
        assert window.info is not None, errors
        assert window.status_var.get().startswith('Verified CAT v')
        rows = window.tree.get_children()
        assert len(rows) == 1 and window.tree.item(rows[0], 'text') == source.name
        assert str(window.extract_button['state']) == 'normal'

        destination_parent.mkdir()
        window.parent_var.set(str(destination_parent))
        window.folder_var.set('restored with spaces')
        window.extract()
        pump_until(root, lambda: not window.busy)
        assert not errors, errors
        assert window.status_var.get().startswith('Extracted to ')
        restored = destination_parent / 'restored with spaces' / source.name
        assert restored.read_bytes() == payload
        assert restored.stat().st_mode & 0o777 == 0o640
    finally:
        root.destroy()

print('PASS: Tk GUI inspected and extracted a CAT archive with exact bytes and mode')
