$ErrorActionPreference = 'Stop'

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$sourceGui = Join-Path $repoRoot 'gui'
$installRoot = Join-Path $env:LOCALAPPDATA 'Programs\CATS'
$guiRoot = Join-Path $installRoot 'gui'

$pythonExe = (Get-Command 'python.exe' -ErrorAction SilentlyContinue).Source
if (-not $pythonExe) {
    $launcher = Get-Command 'py.exe' -ErrorAction SilentlyContinue
    if ($launcher) {
        $pythonExe = (& $launcher.Source -3 -c 'import sys; print(sys.executable)' | Select-Object -Last 1).Trim()
        if ($LASTEXITCODE -ne 0) { $pythonExe = $null }
    }
}
if (-not $pythonExe -or -not (Test-Path -LiteralPath $pythonExe -PathType Leaf)) {
    throw 'Python 3 is required. Install Python from python.org, including Tcl/Tk, then rerun this script.'
}
$pythonw = Join-Path (Split-Path -Parent $pythonExe) 'pythonw.exe'
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    $pythonwCommand = Get-Command 'pythonw.exe' -ErrorAction SilentlyContinue
    if ($pythonwCommand) { $pythonw = $pythonwCommand.Source }
}
if (-not (Test-Path -LiteralPath $pythonw -PathType Leaf)) {
    throw 'Python 3 with pythonw.exe and Tcl/Tk is required; install Python from python.org, then rerun this script.'
}
& $pythonExe -c 'import tkinter'
if ($LASTEXITCODE -ne 0) {
    throw 'The selected Python does not include Tk. Install Python with Tcl/Tk and rerun this script.'
}

New-Item -ItemType Directory -Force -Path $guiRoot | Out-Null
Copy-Item -Force (Join-Path $sourceGui 'cat_gui.py') $guiRoot
Copy-Item -Force (Join-Path $sourceGui 'cat_archive.py') $guiRoot
Copy-Item -Force (Join-Path $PSScriptRoot 'CATDoc.ico') $installRoot
Copy-Item -Force (Join-Path $repoRoot 'LICENSE') $installRoot
Copy-Item -Force (Join-Path $repoRoot 'THIRD_PARTY.md') $installRoot
New-Item -ItemType Directory -Force -Path (Join-Path $installRoot 'licenses') | Out-Null
Copy-Item -Force (Join-Path $repoRoot 'licenses\*.txt') (Join-Path $installRoot 'licenses')

$archiveClass = 'CATArchive'
$classKey = "HKCU:\Software\Classes\$archiveClass"
$iconKey = "$classKey\DefaultIcon"
$openCommandKey = "$classKey\shell\open\command"
Set-Item -Path $classKey -Value 'CATS Archive'

# Remove development-era compound-suffix registrations. Windows resolves
# .cat.gz through the generic .gz handler, so these entries were ineffective.
$legacyCatGzipKey = 'HKCU:\Software\Classes\.cat.gz'
if (Test-Path -LiteralPath $legacyCatGzipKey) {
    $legacyClass = (Get-Item -LiteralPath $legacyCatGzipKey).GetValue('')
    if ($legacyClass -eq $archiveClass) {
        Remove-Item -LiteralPath $legacyCatGzipKey -Recurse -Force
    }
}
foreach ($legacyOpenWithKey in @(
    'HKCU:\Software\Classes\.gz\OpenWithProgids',
    'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.gz\OpenWithProgids'
)) {
    if (Test-Path -LiteralPath $legacyOpenWithKey) {
        Remove-ItemProperty -LiteralPath $legacyOpenWithKey -Name $archiveClass `
            -ErrorAction SilentlyContinue
    }
}
$legacyApplicationKey = 'HKCU:\Software\Classes\Applications\CATSArchive.exe'
if (Test-Path -LiteralPath $legacyApplicationKey) {
    Remove-Item -LiteralPath $legacyApplicationKey -Recurse -Force
}
foreach ($extension in @('.cat')) {
    $extensionKey = "HKCU:\Software\Classes\$extension"
    New-Item -Force -Path $extensionKey | Out-Null
    Set-Item -Path $extensionKey -Value $archiveClass
}
New-Item -Force -Path $iconKey | Out-Null
$iconPath = Join-Path $installRoot 'CATDoc.ico'
Set-Item -Path $iconKey -Value ('"{0}"' -f $iconPath)
New-Item -Force -Path $openCommandKey | Out-Null
$guiScript = Join-Path $guiRoot 'cat_gui.py'
$command = '"{0}" "{1}" "%1"' -f $pythonw, $guiScript
Set-Item -Path $openCommandKey -Value $command
$programsDirectory = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
New-Item -ItemType Directory -Force -Path $programsDirectory | Out-Null
$shortcutPath = Join-Path $programsDirectory 'CATS Archive.lnk'
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $pythonw
$shortcut.Arguments = '"{0}"' -f $guiScript
$shortcut.WorkingDirectory = $guiRoot
$shortcut.IconLocation = $iconPath
$shortcut.Save()

# Refresh Explorer's cached file associations after the per-user registry writes.
if (-not ('CatsShellNotify' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class CatsShellNotify {
    [DllImport("shell32.dll")]
    public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr item1, IntPtr item2);
}
'@
}
[CatsShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)

Write-Output "Installed CATS GUI to $installRoot"
Write-Output 'Registered the .cat open command for the current user. If Windows retains another default, choose CATS Archive from Settings > Apps > Default apps.'
