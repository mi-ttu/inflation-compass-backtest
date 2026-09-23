# Launcher for the Windows Scheduled Task -- runs run_daily.py (trading-day
# gated refresh + allocation-change email, see that file) via the project's
# own venv and logs full output to a timestamped file, since the task runs
# unattended and errors would otherwise go unnoticed.
#
# Not meant to be run directly by a person day-to-day; run
# backtest/run_daily.py yourself for that. This wrapper exists so the
# Scheduled Task has somewhere to send its output.

$ErrorActionPreference = "Stop"

$logDir = Join-Path $PSScriptRoot "refresh_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$logFile = Join-Path $logDir "refresh_$stamp.log"

$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$script = Join-Path $PSScriptRoot "run_daily.py"

try {
    & $python $script *>&1 | Out-File -FilePath $logFile -Encoding utf8
    if ($LASTEXITCODE -ne 0) {
        throw "run_daily.py exited with code $LASTEXITCODE"
    }
    "[run_refresh] succeeded at $(Get-Date -Format o)" | Add-Content -Path $logFile -Encoding utf8
}
catch {
    "[run_refresh] FAILED: $_" | Add-Content -Path $logFile -Encoding utf8
    throw
}

# Keep only the 20 most recent logs
Get-ChildItem $logDir -Filter "refresh_*.log" | Sort-Object LastWriteTime -Descending | Select-Object -Skip 20 | Remove-Item -Force
