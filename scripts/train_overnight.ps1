# train_overnight.ps1 — launch the R7/R8 robustness sweep DETACHED.
#
# Runs experiments/2026-06-23_r7_curriculum_sweep/run_robust.py in a background
# process that survives closing this window / VSCode. OneDrive sync is paused by
# the runner itself and resumed when it finishes. Resume-safe: re-running this
# after a crash/reboot picks up where it left off (done runs are skipped).
#
# Use:  right-click -> "Run with PowerShell"   (or:  .\train_overnight.ps1)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

# 1) Keep the machine awake for the whole unattended run (plugged in).
Write-Host "Disabling sleep/hibernate on AC power..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

# 2) Timestamped log files so successive launches don't clobber each other.
$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stamp  = Get-Date -Format "yyyy-MM-dd_HHmmss"
$out    = Join-Path $logDir "r8_$stamp.log"
$err    = Join-Path $logDir "r8_$stamp.err"

# 3) Launch detached. -PassThru gives us the PID; the process is NOT tied to
#    this window, so closing the terminal / VSCode will not kill it.
$script = "experiments/2026-06-23_r7_curriculum_sweep/run_robust.py"
Write-Host "Launching: uv run python $script"
$proc = Start-Process -FilePath "uv" `
    -ArgumentList @("run", "python", $script) `
    -WorkingDirectory $repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError  $err `
    -PassThru

Write-Host ""
Write-Host "Started PID $($proc.Id). It will keep running if you close this window."
Write-Host "Follow progress:   Get-Content `"$out`" -Wait"
Write-Host "Check errors:      Get-Content `"$err`" -Tail 40"
Write-Host "Stop it:           Stop-Process -Id $($proc.Id)"
Write-Host ""
# Keep this window open so the info above is readable. The training runs in the
# detached process above, so closing this window does NOT stop it.
Read-Host "Press Enter to close this window (training keeps running)"
