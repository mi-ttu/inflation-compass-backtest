# Assembles a distributable release package: installer\install.ps1 plus a
# clean copy of the app source (ingest/transform/backtest, no data/, no
# __pycache__, no .venv) under app\, ready to zip and hand to someone else.
#
# Usage: powershell -ExecutionPolicy Bypass -File installer\build_release.ps1

$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ReleaseDir = Join-Path $ProjectRoot "dist\InflationCompassRelease"
$AppDir = Join-Path $ReleaseDir "app"

if (Test-Path $ReleaseDir) {
    Remove-Item $ReleaseDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null

foreach ($sub in @("ingest", "transform", "backtest")) {
    $dest = Join-Path $AppDir $sub
    # email_config.json is a local secret (Gmail app password) -- it must
    # never ship in a distributed package. Only the .example template does.
    robocopy (Join-Path $ProjectRoot $sub) $dest /E /XD data __pycache__ refresh_logs `
        /XF "*.pyc" "email_config.json" "last_allocation.json" /NFL /NDL /NJH /NJS /NC /NS | Out-Null
}

$leakedSecret = Join-Path $AppDir "backtest\email_config.json"
if (Test-Path $leakedSecret) {
    throw "SAFETY CHECK FAILED: $leakedSecret exists in the release package -- aborting before zipping."
}
Copy-Item (Join-Path $ProjectRoot "requirements.txt") $AppDir
Copy-Item (Join-Path $ProjectRoot "installer\install.ps1") $ReleaseDir

$zipPath = Join-Path $ProjectRoot "dist\InflationCompassRelease.zip"
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $ReleaseDir -DestinationPath $zipPath

Write-Host "Release package built: $ReleaseDir"
Write-Host "Zipped: $zipPath"
