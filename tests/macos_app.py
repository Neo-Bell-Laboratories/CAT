"""Validate the CATS-branded CAT.app metadata, native GUI executable, and Finder icon."""
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile

cat = Path(__file__).resolve().parent.parent
binary = Path(sys.argv[1]).resolve()
builder = cat / 'tools' / 'macos_app.py'
with tempfile.TemporaryDirectory(prefix='cat-macos-app-test-') as td:
    app = Path(td) / 'CAT.app'
    subprocess.run([
        sys.executable, str(builder), '--binary', str(binary), '--output', str(app)
    ], check=True, capture_output=True)
    contents = app / 'Contents'
    info_path = contents / 'Info.plist'
    assert (contents / 'PkgInfo').read_bytes() == b'APPL????'
    with info_path.open('rb') as f:
        info = plistlib.load(f)

    cli_version = subprocess.check_output([str(binary), '--version'], text=True).split()[1]
    assert info['CFBundleExecutable'] == 'CAT'
    assert info['CFBundleName'] == 'CATS'
    assert info['CFBundleDisplayName'].startswith('CATS —')
    assert info['CFBundleShortVersionString'] == cli_version
    assert info['CFBundlePackageType'] == 'APPL'
    assert info['CFBundleIconFile'] == 'CAT.icns'
    doc_type, = info['CFBundleDocumentTypes']
    assert doc_type['CFBundleTypeRole'] == 'Viewer'
    assert doc_type['CFBundleTypeIconFile'] == 'CATDoc.icns'
    uti, = info['UTExportedTypeDeclarations']
    assert uti['UTTypeIdentifier'] in doc_type['LSItemContentTypes']
    assert uti['UTTypeConformsTo'] == ['public.data', 'public.archive']
    assert uti['UTTypeIconFile'] == 'CATDoc.icns'
    assert 'UTTypeIcons' not in uti
    assert uti['UTTypeTagSpecification']['public.filename-extension'] == ['cat']

    icon = contents / 'Resources' / 'CAT.icns'
    document_icon = contents / 'Resources' / 'CATDoc.icns'
    assert icon.read_bytes()[:4] == b'icns'
    assert document_icon.read_bytes()[:4] == b'icns'
    for source in (icon, document_icon):
        iconset = Path(td) / f'{source.stem}.iconset'
        subprocess.run([
            'iconutil', '-c', 'iconset', str(source), '-o', str(iconset)
        ], check=True, capture_output=True)
        assert (iconset / 'icon_512x512.png').is_file()
    assert os.access(contents / 'MacOS' / 'CAT', os.X_OK)
    launcher_info = subprocess.check_output(['file', str(contents / 'MacOS' / 'CAT')], text=True)
    assert 'Mach-O' in launcher_info
    assert not (contents / 'Resources' / 'cat_gui.py').exists()
    assert (contents / 'Resources' / 'CATDoc.svg').is_file()
    assert os.access(contents / 'Resources' / 'cats', os.X_OK)
    for directory in (app, contents, contents / 'MacOS', contents / 'Resources'):
        assert directory.stat().st_mode & 0o777 == 0o755
    assert (contents / 'Info.plist').stat().st_mode & 0o777 == 0o644
    assert icon.stat().st_mode & 0o777 == 0o644
    subprocess.run(['plutil', '-lint', str(info_path)], check=True, capture_output=True)

print('PASS: CATS CAT.app plist, .cat UTI, icons, and native GUI executable')
