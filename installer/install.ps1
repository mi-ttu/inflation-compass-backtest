# Standalone installer for the Inflation Compass Backtest dashboard.
#
# Installs into the current user's profile (no admin rights needed):
#   1. Copies this package's app\ folder (ingest/transform/backtest source)
#      to the install directory.
#   2. Downloads a self-contained, isolated Python runtime (the official
#      "embeddable" distribution) -- no system Python required, and this
#      app never touches or depends on any Python already on the machine.
#   3. Installs the app's dependencies into that runtime.
#   4. Runs the app once immediately (first-time database bootstrap --
#      pulls ~36 years of public market data, takes a few minutes).
#   5. Registers a Windows Scheduled Task, Mon-Fri at 2:30 PM (current-
#      user scope, no stored credentials) so the dashboard stays current
#      going forward. The task fires every weekday; run_daily.py itself
#      checks the NYSE trading calendar and no-ops on holidays, since a
#      Task Scheduler weekly trigger alone can't skip those.
#   6. Drops a desktop shortcut to the dashboard.
#
# Usage:  powershell -ExecutionPolicy Bypass -File install.ps1
# Re-running this later (e.g. after a code update) is safe -- it will not
# touch an existing database, only refresh the app source and re-register
# the scheduled task.

param(
    # Override the install location (mainly for testing). Defaults to a
    # per-user folder that needs no admin rights.
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA "InflationCompass")
)

$ErrorActionPreference = "Stop"

# ---- Configuration ----
$PythonVersion = "3.13.5"
$PythonEmbedUrl = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
$GetPipUrl = "https://bootstrap.pypa.io/get-pip.py"
$TaskName = "InflationCompassDailyRefresh"
# 2:30 PM local system time -- 30 min before the NYSE close, matching the
# MaxAlpha backtest project's schedule. On this machine's Central Time
# config that's 2:30 PM CST/CDT.
$DailyTime = "2:30PM"

$SourceApp = Join-Path $PSScriptRoot "app"
if (-not (Test-Path $SourceApp)) {
    throw "Expected an 'app' folder next to install.ps1 (got: $SourceApp) -- this script must be run from inside the release package."
}

Write-Host "Installing to $InstallDir ..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null

# ---- 1. Copy app source (never touches an existing data\ folder from a prior install) ----
$DestApp = Join-Path $InstallDir "app"
Write-Host "Copying app files ..."
robocopy $SourceApp $DestApp /E /XD data __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NC /NS | Out-Null

# ---- 2. Download + set up the isolated Python runtime (skip if already done) ----
$RuntimeDir = Join-Path $InstallDir "python-runtime"
$PythonExe = Join-Path $RuntimeDir "python.exe"

if (-not (Test-Path $PythonExe)) {
    Write-Host "Downloading Python $PythonVersion runtime (isolated, no system Python used) ..."
    $zipPath = Join-Path $env:TEMP "python-embed-$PythonVersion.zip"
    Invoke-WebRequest -Uri $PythonEmbedUrl -OutFile $zipPath
    New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
    Expand-Archive -Path $zipPath -DestinationPath $RuntimeDir -Force
    Remove-Item $zipPath -Force

    # The embeddable distribution's ._pth file puts the interpreter in an
    # isolated path mode: PYTHONPATH and the usual "script's own directory"
    # auto-insertion are BOTH ignored, only exactly what's listed here is
    # used. Enable site-packages, and add app\backtest explicitly since its
    # scripts import each other as siblings (e.g. `from _levered_common
    # import ...`) -- nothing else in the app does that.
    $pthFile = Join-Path $RuntimeDir "python313._pth"
    $pthContent = Get-Content $pthFile
    $pthContent = $pthContent -replace '#import site', 'import site'
    $pthContent += "..\app\backtest"
    # ascii, not utf8 -- Windows PowerShell 5.1's "utf8" writes a BOM,
    # which corrupts the file's first line and breaks Python's own
    # bootstrap (it can no longer find python313.zip, so not even the
    # `encodings` module loads). Plain ASCII paths need no BOM at all.
    Set-Content -Path $pthFile -Value $pthContent -Encoding ascii

    Write-Host "Installing pip ..."
    $getPipPath = Join-Path $env:TEMP "get-pip.py"
    Invoke-WebRequest -Uri $GetPipUrl -OutFile $getPipPath
    & $PythonExe $getPipPath --no-warn-script-location --quiet
    Remove-Item $getPipPath -Force
}

# ---- 3. Install dependencies ----
Write-Host "Installing dependencies ..."
& $PythonExe -m pip install -r (Join-Path $DestApp "requirements.txt") --no-warn-script-location --quiet

# ---- 4. First run (bootstraps the database if this is a fresh install, else just refreshes) ----
$dbPath = Join-Path $DestApp "data\curated.duckdb"
if (-not (Test-Path $dbPath)) {
    Write-Host "Building the database for the first time -- this pulls ~36 years of" -ForegroundColor Yellow
    Write-Host "public market data and will take a few minutes ..." -ForegroundColor Yellow
}
& $PythonExe (Join-Path $DestApp "backtest\run_daily.py")
if ($LASTEXITCODE -ne 0) {
    throw "First run failed (exit code $LASTEXITCODE) -- see the output above."
}

# ---- 5. Register the Mon-Fri Scheduled Task ----
Write-Host "Registering refresh task (Mon-Fri, $DailyTime) ..."
$action = New-ScheduledTaskAction -Execute $PythonExe -Argument "`"$(Join-Path $DestApp 'backtest\run_daily.py')`"" -WorkingDirectory $DestApp
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $DailyTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings | Out-Null
} else {
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
        -RunLevel Limited -Description "Inflation Compass backtest: refresh + allocation-change email, trading days at 2:30 PM" | Out-Null
}

# ---- 6. Desktop shortcut ----
$chartPath = Join-Path $DestApp "backtest\interactive_chart.html"
$shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Inflation Compass Dashboard.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $chartPath
$shortcut.Description = "Inflation Compass backtest dashboard"
$shortcut.Save()

Write-Host ""
Write-Host "Done." -ForegroundColor Green
Write-Host "Dashboard: $chartPath"
Write-Host "Desktop shortcut created."
Write-Host "Refresh scheduled Mon-Fri at $DailyTime, local time (task: $TaskName)."
