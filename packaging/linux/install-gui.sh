#!/bin/sh
set -eu

prefix=${1:-/usr/local}
destdir=${DESTDIR:-}
if ! command -v python3 >/dev/null 2>&1 || ! python3 -c 'import tkinter' >/dev/null 2>&1; then
    echo "Python 3 with Tk is required to install the CATS GUI" >&2
    exit 1
fi
case "$prefix" in
    /*) ;;
    *) echo "PREFIX must be an absolute path" >&2; exit 2 ;;
esac
case "$prefix" in
    *" "*) echo "PREFIX cannot contain spaces" >&2; exit 2 ;;
esac

source_root=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)
install_root=$destdir$prefix
install -d "$install_root/bin" \
    "$install_root/lib/cat/gui" \
    "$install_root/share/applications" \
    "$install_root/share/mime/packages" \
    "$install_root/share/doc/cats-gui" \
    "$install_root/share/icons/hicolor/scalable/apps" \
    "$install_root/share/icons/hicolor/scalable/mimetypes"
install -m 644 "$source_root/gui/cat_gui.py" "$source_root/gui/cat_archive.py" \
    "$install_root/lib/cat/gui/"
install -m 644 "$source_root/packaging/macos/CAT.svg" \
    "$install_root/share/icons/hicolor/scalable/apps/cat.svg"
install -m 644 "$source_root/packaging/macos/CATDoc.svg" \
    "$install_root/share/icons/hicolor/scalable/mimetypes/application-x-cat.svg"
install -m 644 "$source_root/LICENSE" "$source_root/THIRD_PARTY.md" \
    "$install_root/share/doc/cats-gui/"
install -m 644 "$source_root"/licenses/*.txt "$install_root/share/doc/cats-gui/"

cat > "$install_root/bin/cats-gui" <<'LAUNCHER'
#!/bin/sh
set -eu
base=$(CDPATH= cd -- "$(dirname -- "$0")/../lib/cat/gui" && pwd)
exec python3 "$base/cat_gui.py" "$@"
LAUNCHER
chmod 755 "$install_root/bin/cats-gui"
ln -sfn cats-gui "$install_root/bin/cat-gui"

cat > "$install_root/share/applications/cats-archive-extractor.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=CATS Archive Extractor
Comment=Inspect and extract CATS archives
Exec=$prefix/bin/cats-gui %f
Icon=cat
Terminal=false
Categories=Utility;Archiving;
MimeType=application/x-cat;
DESKTOP

cat > "$install_root/share/mime/packages/cat.xml" <<'MIME'
<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-cat">
    <comment>CATS archive</comment>
    <glob pattern="*.cat"/>
    <glob pattern="*.cat.gz"/>
    <magic priority="70"><match type="string" value="CAT" offset="0"/></magic>
  </mime-type>
</mime-info>
MIME

echo "Installed CATS Tk extractor under $prefix. Requires Python 3 with Tk; run cats-gui ARCHIVE.cat."
echo "For desktop integration, refresh the MIME/desktop caches and select cats-archive-extractor as the application for application/x-cat."
