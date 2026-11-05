# Windows GUI final hardening pass

Status: not run yet; scheduled for the final hardening pass.

## Install and association

1. Build `releases/cat-gui-windows-0.4.0-dev.zip` with `make windows-gui-package`
   and verify the adjacent `.sha256` file.
2. Extract the ZIP on the Windows 11 guest and run
   `powershell -ExecutionPolicy Bypass -File .\packaging\windows\install-gui.ps1`.
3. Confirm Python 3 with Tk is detected, then verify the installed GUI script,
   icon, license files, `.cat` and `.cat.gz` per-user ProgIDs, icon path, and
   quoted `pythonw.exe` open command.
4. Open a `.cat` and a `.cat.gz` by double-clicking them. Confirm the CAT
   inspector launches and shows the expected entries.

## Extraction behavior

1. Use both an older golden archive and a current v0.7 archive with nested
   directories, an empty directory, a zero-byte file, and binary bytes.
2. Extract into a new destination; compare file lengths and SHA-256 values and
   confirm the directory tree. Windows does not restore POSIX mode bits.
3. Try an existing destination and an archive with an unsafe path; verify the
   GUI refuses extraction and leaves existing files unchanged.
4. Record Windows build, Python/Tk versions, package SHA-256, and results in
   `docs/release-validation.json`. Change `windows_gui` to `passed` only after
   these runtime checks succeed.
