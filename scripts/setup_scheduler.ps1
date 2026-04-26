# =============================================================================
# scripts/setup_scheduler.ps1
# Registers run_daily.py as a Windows Task Scheduler job.
#
# USAGE
# -----
#   Right-click this file -> "Run with PowerShell"
#   OR from a PowerShell prompt:
#     Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
#     .\scripts\setup_scheduler.ps1
#
# WHAT IT DOES
# ------------
#   Creates a scheduled task named "OptionsSentimentPipeline" that runs
#   run_daily.py Monday-Friday at 6:30 PM using the project's venv Python.
#   6:30 PM ET is chosen so same-day options data (which finalises at
#   market close, 4:00 PM ET) is available.
#
# PREREQUISITES
# -------------
#   * Run as Administrator (required to register a scheduled task)
#   * The .venv must already be set up (run: python -m venv .venv then
#     .venv\Scripts\pip install -r requirements.txt)
# =============================================================================

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Paths - derived from this script's location so they're always correct
# ---------------------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$PythonExe   = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$RunScript   = Join-Path $ProjectRoot "scripts\run_daily.py"
$LogsDir     = Join-Path $ProjectRoot "logs"

Write-Host ""
Write-Host "======================================================"
Write-Host "  Options Sentiment Pipeline - Scheduler Setup"
Write-Host "======================================================"
Write-Host ""
Write-Host "  Project root : $ProjectRoot"
Write-Host "  Python       : $PythonExe"
Write-Host "  Script       : $RunScript"
Write-Host "  Logs         : $LogsDir"
Write-Host ""

# ---------------------------------------------------------------------------
# Validate prerequisites
# ---------------------------------------------------------------------------
if (-not (Test-Path $PythonExe)) {
    Write-Host "ERROR: Virtual environment not found at:" -ForegroundColor Red
    Write-Host "  $PythonExe" -ForegroundColor Red
    Write-Host ""
    Write-Host "Create it first:"
    Write-Host "  cd `"$ProjectRoot`""
    Write-Host "  python -m venv .venv"
    Write-Host "  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

if (-not (Test-Path $RunScript)) {
    Write-Host "ERROR: run_daily.py not found at: $RunScript" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null

# ---------------------------------------------------------------------------
# Build the scheduled task components
# ---------------------------------------------------------------------------
$TaskName   = "OptionsSentimentPipeline"
$TaskDescr  = "Daily options sentiment + signal pipeline (Mon-Fri 6:30 PM)"

# The argument string: python.exe <script_path>
# Quotes around the script path handle spaces in the directory name.
$TaskArg    = "`"$RunScript`""

# Action: run python.exe with the script as its argument, from the project root
$Action = New-ScheduledTaskAction `
    -Execute    $PythonExe `
    -Argument   $TaskArg `
    -WorkingDirectory $ProjectRoot

# Trigger: every weekday at 18:30
# Task Scheduler uses the system's local time zone, so this will be 6:30 PM
# in whatever time zone the machine is set to.  On an EST machine it fires
# at 6:30 PM EST as requested.
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "6:30 PM"

# Settings: allow the task to start if it missed its window (e.g. machine
# was off at 6:30 PM), stop it if it runs longer than 2 hours.
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit  (New-TimeSpan -Hours 2) `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -MultipleInstances   IgnoreNew

# ---------------------------------------------------------------------------
# Register (or update if it already exists)
# ---------------------------------------------------------------------------
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Existing) {
    Write-Host "Task '$TaskName' already exists - updating..." -ForegroundColor Yellow
    Set-ScheduledTask `
        -TaskName $TaskName `
        -Action   $Action `
        -Trigger  $Trigger `
        -Settings $Settings | Out-Null
    Write-Host "Task updated." -ForegroundColor Green
} else {
    Register-ScheduledTask `
        -TaskName    $TaskName `
        -Description $TaskDescr `
        -Action      $Action `
        -Trigger     $Trigger `
        -Settings    $Settings `
        -RunLevel    Limited | Out-Null
    Write-Host "Task registered." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Verify and print confirmation
# ---------------------------------------------------------------------------
$Task = Get-ScheduledTask -TaskName $TaskName
$Info = $Task | Get-ScheduledTaskInfo

Write-Host ""
Write-Host "======================================================"
Write-Host "  Task registered successfully!" -ForegroundColor Green
Write-Host "======================================================"
Write-Host ""
Write-Host "  Task name   : $TaskName"
Write-Host "  Schedule    : Monday-Friday at 6:30 PM (local time)"
Write-Host "  Status      : $($Task.State)"
if ($Info.LastRunTime -and $Info.LastRunTime -ne ([datetime]"1/1/1900")) {
    Write-Host "  Last run    : $($Info.LastRunTime)"
} else {
    Write-Host "  Last run    : (never)"
}
Write-Host "  Next run    : $($Info.NextRunTime)"
Write-Host ""
Write-Host "  Useful commands:"
Write-Host ""
Write-Host "  # Run the task right now (for testing):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "  # Check the last run status:"
Write-Host "  Get-ScheduledTask '$TaskName' | Get-ScheduledTaskInfo | Select-Object LastRunTime, LastTaskResult"
Write-Host ""
Write-Host "  # Remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm"
Write-Host ""
Write-Host "  # View live logs after a run:"
Write-Host "  Get-Content `"$LogsDir\daily_summary.txt`""
Write-Host ""
