# Build the Windows MTGA Tracker app with PyInstaller and zip it for release.
#
# Usage (from anywhere, PowerShell 5+):
#   pwsh scripts/build_windows_app.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\build_windows_app.ps1
#
# Requirements: Python 3.9+ and Node 18+ on PATH.
# Output: dist\MTGA Tracker\MTGA Tracker.exe and dist\MTGA-Tracker-windows.zip

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
$ZipPath = Join-Path $RootDir "dist\MTGA-Tracker-windows.zip"
if (Test-Path $ZipPath) { Remove-Item $ZipPath }
Compress-Archive -Path $AppDir -DestinationPath $ZipPath

Write-Host ""
Write-Host "Built: $ExePath"
Write-Host "Built: $ZipPath"
Write-Host ""
Write-Host "Testers: extract the zip anywhere and run 'MTGA Tracker.exe'."
Write-Host "SmartScreen will warn on unsigned builds - More info -> Run anyway."
