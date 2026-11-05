CATS GUI extractor for Windows

Requirements: Windows 10 or newer and Python 3 installed with Tcl/Tk.

1. Extract this ZIP file.
2. Open PowerShell in the extracted CATS-GUI-Windows folder.
3. Run:

   powershell -ExecutionPolicy Bypass -File .\packaging\windows\install-gui.ps1

The installer is per-user. It copies the CATS archive viewer into your local
Programs folder and registers .cat and .cat.gz for the current Windows user.
Double-click a CATS archive to inspect and extract it. If another application
keeps the default association, select CATS Archive in Settings > Apps > Default
apps.
