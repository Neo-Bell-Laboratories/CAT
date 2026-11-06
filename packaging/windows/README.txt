CATS GUI extractor for Windows

Requirements: Windows 10 or newer and Python 3 installed with Tcl/Tk.

1. Extract this ZIP file.
2. Open PowerShell in the extracted CATS-GUI-Windows folder.
3. Run:

   powershell -ExecutionPolicy Bypass -File .\packaging\windows\install-gui.ps1

The installer is per-user. It copies the CATS archive viewer into your local
Programs folder and registers .cat for the current Windows user and creates a CATS Archive Start
menu shortcut.
Double-click a .cat archive to inspect and extract it. To inspect a .cat.gz
archive, launch CATS Archive from the Start menu and choose the archive with
Browse. Windows handles .cat.gz through its final .gz suffix, so CATS does not
replace the default application for unrelated .gz files.
