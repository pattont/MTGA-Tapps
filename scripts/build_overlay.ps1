# Build the in-game overlay (overlay\, a Tauri v2 app) and stage
# overlay\build-out\tapps-overlay.exe, where packaging\mtga_tracker.spec
# picks it up and ships it inside the tracker folder.
#
# Needs Node 18+ and a Rust toolchain (https://rustup.rs) with the MSVC
# build tools. Without cargo the overlay is skipped with a warning and the
# tracker builds without it — set OVERLAY_REQUIRED=1 (CI does) to fail.

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$OverlayDir = Join-Path $RootDir "overlay"
$OutDir = Join-Path $OverlayDir "build-out"

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    if ($env:OVERLAY_REQUIRED -eq "1") {
        throw "cargo not found and OVERLAY_REQUIRED=1 - install Rust from https://rustup.rs"
    }
    Write-Host "!! cargo not found - the in-game overlay is skipped (install Rust from https://rustup.rs to include it)"
    exit 0
}

Push-Location $OverlayDir
try {
    npm ci
    if ($LASTEXITCODE -ne 0) { throw "npm ci (overlay) failed" }
    npm run tauri -- build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    New-Item -ItemType Directory -Path $OutDir | Out-Null
    Copy-Item (Join-Path $OverlayDir "src-tauri\target\release\tapps-overlay.exe") $OutDir
    Write-Host "Built: $(Join-Path $OutDir 'tapps-overlay.exe')"
} finally {
    Pop-Location
}
