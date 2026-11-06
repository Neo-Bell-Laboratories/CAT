# Windows GUI final hardening pass

Status: Windows GUI portable-reader and Tk fixture tests passed on the Windows 11 guest. The current package installed and `.cat` double-click launched the GUI successfully. `.cat.gz` is supported through the installed Start menu shortcut and GUI Browse; Windows routes its compound suffix through the generic `.gz` handler.

SSH was not required. The CLI-independent bundle ran under Python 3.14.10 x64 with Tk. `py.exe` was not on the PowerShell PATH, so tests were invoked through the installed interpreter at `%LOCALAPPDATA%\Programs\Python\Python314\python.exe`. The portable test verified all v0.7/v0.8 plain/gzip fixtures, paths, exact bytes, hashes, and supported metadata. The Tk smoke test inspected and extracted the current-format fixture and verified exact bytes and SHA-256.

## Guest-side portable smoke tests

Extract `%TEMP%\windows-validation.zip` to a writable directory, then run these
commands in PowerShell from that extracted directory:

```powershell
$python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
& $python -c "import tkinter; print('Tk', tkinter.TkVersion)"
& $python .\tests\gui_archive_portable.py
& $python .\tests\gui_fixture_smoke.py
```

Both scripts should print `PASS`. Both checks passed on the Windows 11 guest using Python 3.14.10 x64 with Tk. The bundle contains the standalone app package and current v0.7/v0.8 plain/gzip fixtures.

## Install and association

1. Build `releases/cats-gui-windows.zip` with `make windows-gui-package`
   and verify the adjacent `.sha256` file.
2. In the full CAT source tree, run the CLI-independent tests first:

   ```powershell
   $python = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python314\python.exe'
   & $python .\tests\gui_archive_portable.py
   & $python .\tests\gui_fixture_smoke.py
   ```

   The fixture archives were produced by the current native encoder, so these
   GUI tests do not depend on a Windows CLI build.
3. Extract the ZIP on the Windows 11 guest and run
   `powershell -ExecutionPolicy Bypass -File .\packaging\windows\install-gui.ps1`.
4. Confirm Python 3 with Tk is detected, then verify the installed GUI script,
   icon, license files, `.cat` per-user ProgID, icon path, and quoted
   `pythonw.exe` open command. Confirm the default `.gz` application was not
   replaced.
5. Confirm the Start menu shortcut launches the GUI. Double-click a `.cat` and
   confirm the CAT inspector opens. For `.cat.gz`, launch the installed GUI and
   use Browse; Explorer dispatches the compound
   suffix through `.gz`, so the GUI is not the double-click default. Confirm
   both archives show the expected entries. The `.cat` double-click and the
   gzip fixture inspection/extraction passed on the Windows 11 guest.

## Extraction behavior

1. Use both an older golden archive and the current v0.7/v0.8 fixtures with nested
   directories, an empty directory, a zero-byte file, and binary bytes.
2. Extract into a new destination; compare file lengths and SHA-256 values and
   confirm the directory tree. Windows does not restore POSIX mode bits.
3. Try an existing destination and an archive with an unsafe path; verify the
   GUI refuses extraction and leaves existing files unchanged.
4. Record Windows build, Python/Tk versions, package SHA-256, and results in
   `docs/release-validation.json`. Change `windows_gui` to `passed` only after
   these runtime checks succeed. The current Windows 11 run passed installer
launch, the Start menu entry, `.cat` double-click, and GUI fixture decoding and
extraction; `.cat.gz` was passed to the GUI directly by the fixture smoke test.

## CLI cross-build status

The Homebrew `mingw-w64` 14.0.0_3 package provides
`x86_64-w64-mingw32-gcc` 16.2.0 and its Windows CRT/linker. A static zlib 1.4
library was cross-built successfully with zlib's `win32/Makefile.gcc` into a
separate temporary tree, and LambdaScript compiled into a PE x86_64 static
library. PCRE2 10.49's POSIX compatibility library also built as a PE static
library. XF selects it through `XF_USE_PCRE2_POSIX`; its Windows glob implementation
and source fixes for `M_PI`/`M_E` and the one-argument Windows `mkdir` API allow the
entire static XF archive to compile and link. CAT now has a reproducible
`windows-x64-cross` Make target. It cross-builds LambdaScript, XF, and CAT with
Homebrew MinGW-w64, the Windows-target zlib/PCRE2 static libraries, and produces
a static PE x86_64 console executable. The latest artifact is staged for runtime
validation in `/tmp/cats-win-validation` through the authorized Alienware relay.

CAT's Win32 filesystem layer uses `NtCreateFile` relative to open directory
handles, rejects reparse points during traversal/extraction, enumerates opened
directory handles, uses no-replace `MoveFileW` publication, and creates temporary
files/directories with owner-restricted ACLs and cryptographic random names.
Windows archives do not restore POSIX permission bits. The executable cross-builds and has only Windows system DLL imports, but its CLI
runtime smoke suite has not run on Windows. The user has de-prioritized this native
CLI check for v0.4.0; no native runtime claim is made. Current VM metadata says
Windows boots from its installed disk and reaches the lock screen; interactive
account sign-in and SSH setup would be needed to run the test later. Windows GUI
runtime validation passed separately.

A separate MinGW smoke executable successfully linked a pthread worker and
zlib compression statically. `objdump` showed only Windows system CRT/kernel
imports, with no `winpthread` or zlib DLL dependency. This verifies the target
toolchain and those libraries, not CAT runtime behavior; the smoke executable
has not been run on Windows.
