# Build the in-game overlay (overlay\, a Tauri v2 app) and stage
# overlay\build-out\tapps-overlay.exe, where packaging\mtga_tracker.spec
# picks it up and ships it inside the tracker folder.
#
#   scripts\build_overlay.ps1          release build (what ships: fat LTO,
#                                      size-optimised; slow to relink)
#   scripts\build_overlay.ps1 -Fast    iteration build: the `fast` cargo
#                                      profile (no LTO, incremental) in its
#                                      own target\fast\ so it never evicts
#                                      the release cache.
#
# npm dependencies are installed only when package-lock.json changed.
#
# Needs Node 18+ and a Rust toolchain (https://rustup.rs) with the MSVC
# build tools. Without cargo the overlay is skipped with a warning and the
# tracker builds without it — set OVERLAY_REQUIRED=1 (CI does) to fail.

param([switch]$Fast)

$ErrorActionPreference = "Stop"

$RootDir = Split-Path -Parent $PSScriptRoot
$OverlayDir = Join-Path $RootDir "overlay"
$OutDir = Join-Path $OverlayDir "build-out"
$Profile = if ($Fast) { "fast" } else { "release" }
$CargoArgs = if ($Fast) { @("--", "--profile", "fast") } else { @() }

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    if ($env:OVERLAY_REQUIRED -eq "1") {
        throw "cargo not found and OVERLAY_REQUIRED=1 - install Rust from https://rustup.rs"
    }
    Write-Host "!! cargo not found - the in-game overlay is skipped (install Rust from https://rustup.rs to include it)"
    exit 0
}

Push-Location $OverlayDir
try {
    # `npm ci` wipes node_modules and reinstalls every time (~10 s); only do
    # it when the lockfile is newer than what is installed.
    $installed = Join-Path $OverlayDir "node_modules\.package-lock.json"
    if (-not (Test-Path $installed) -or (Get-Item "package-lock.json").LastWriteTime -gt (Get-Item $installed).LastWriteTime) {
        npm ci
        if ($LASTEXITCODE -ne 0) { throw "npm ci (overlay) failed" }
    } else {
        Write-Host "node_modules up to date (npm ci skipped)"
    }
    npm run tauri -- build --no-bundle @CargoArgs
    if ($LASTEXITCODE -ne 0) { throw "tauri build failed" }
    if (Test-Path $OutDir) { Remove-Item -Recurse -Force $OutDir }
    New-Item -ItemType Directory -Path $OutDir | Out-Null
    Copy-Item (Join-Path $OverlayDir "src-tauri\target\$Profile\tapps-overlay.exe") $OutDir
    Write-Host "Built ($Profile): $(Join-Path $OutDir 'tapps-overlay.exe')"
} finally {
    Pop-Location
}
