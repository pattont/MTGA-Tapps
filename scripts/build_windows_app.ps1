# Build the Windows MTGA Tracker app with PyInstaller and zip it for release.
#
# Usage (from anywhere, PowerShell 5+):
#   pwsh scripts/build_windows_app.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows_app.ps1
#
# Requirements: Python 3.9+ and Node 18+ on PATH.
# Output: dist\MTGA Tracker\MTGA Tracker.exe and dist\MTGA-Tracker-<version>-windows.zip

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
Set-Location $RootDir

# Prefer the repo virtualenv when present, otherwise whatever python is on PATH.
$Python = Join-Path $RootDir "venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "==> Building dashboard frontend (ui/dist)"
Push-Location (Join-Path $RootDir "ui")
npm ci
if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
npm run build
if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
Pop-Location

Write-Host "==> Installing Python build dependencies"
& $Python -m pip install -e ".[gui,build]"
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

Write-Host "==> Running PyInstaller"
& $Python -m PyInstaller --noconfirm --clean packaging/mtga_tracker.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$AppDir = Join-Path $RootDir "dist\MTGA Tracker"
$ExePath = Join-Path $AppDir "MTGA Tracker.exe"
if (-not (Test-Path $ExePath)) { throw "Build finished but $ExePath is missing" }

Write-Host "==> Zipping release archive"
# Version is derived from the git tag (setuptools-scm) and registered by the
# `pip install -e .` above. Anything that doesn't look like a version
# (errors, empty output) falls back to "dev" rather than poisoning filenames.
$Version = try {
    ("$(& $Python -c "from importlib.metadata import version; print(version('mtga-tracker'))" 2>&1)").Trim()
} catch { "" }
if ($Version -notmatch '^\d+(\.\d+)+') { $Version = "dev" }
$ZipPath = Join-Path $RootDir "dist\MTGA-Tracker-$Version-windows.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath

Write-Host "==> Building installer (Inno Setup)"
$Iscc = Get-Command iscc -ErrorAction SilentlyContinue
if ($Iscc) {
    $IsccPath = $Iscc.Source
} else {
    $IsccPath = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
}
$SetupPath = Join-Path $RootDir "dist\MTGA-Tracker-$Version-setup.exe"
if (Test-Path $IsccPath) {
    & $IsccPath /Qp "/DMyAppVersion=$Version" (Join-Path $RootDir "packaging\windows_installer.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup (ISCC) failed" }
    if (-not (Test-Path $SetupPath)) { throw "ISCC finished but $SetupPath is missing" }
} else {
    $SetupPath = $null
    Write-Host "!! Inno Setup not found - installer skipped. Install it with:"
    Write-Host "   choco install innosetup -y    (or from jrsoftware.org)"
}

Write-Host ""
Write-Host "Built: $ExePath"
Write-Host "Built: $ZipPath"
if ($SetupPath) { Write-Host "Built: $SetupPath" }
Write-Host ""
Write-Host "Users: run the -setup.exe for a normal install (Start Menu + uninstaller),"
Write-Host "or extract the zip anywhere for a portable run of 'MTGA Tracker.exe'."
Write-Host "SmartScreen will warn on unsigned builds - More info -> Run anyway."
