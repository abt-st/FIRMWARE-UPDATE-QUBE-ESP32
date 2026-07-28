# watch_then_reeval.ps1 - wait for the R7 overnight sweep to finish, THEN run the
# high-episode re-evaluation of the winners. Does NOT touch the running sweep.
#
# Flow:
#   1) Find the sweep python process (run_robust.py / run_r7.py) and BLOCK until it exits.
#      (If none is running, assume it already finished and proceed immediately.)
#   2) Launch reeval_winners.py (100 episodes) - read-only, ~15-20 min.
#
# Launch it DETACHED so it survives closing this window (see the Start-Process at
# the bottom, or just: .\watch_then_reeval.ps1). Resume-safe: re-running it after
# the sweep is already done simply runs the re-eval again (harmless, overwrites
# the report).

param(
    [int]$Episodes = 100
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo

$logDir = Join-Path $repo "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$stamp = Get-Date -Format "yyyy-MM-dd_HHmmss"
$out   = Join-Path $logDir "reeval_$stamp.log"
$err   = Join-Path $logDir "reeval_$stamp.err"

# 1) Locate the running sweep by command line (robust to PID reuse / relaunch).
#    `uv run` spawns two python.exe (a thin .venv parent + the uv-managed worker);
#    both carry the script path on their command line and finish together, so we
#    wait on ALL of them.
$pids = @(Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'run_robust\.py|run_r7\.py' } |
    Select-Object -ExpandProperty ProcessId)

if ($pids.Count -gt 0) {
    Write-Host "Sweep is running (PID $($pids -join ', ')). Waiting for it to finish..."
    try {
        Wait-Process -Id $pids -ErrorAction Stop
    } catch {
        Write-Host "Wait-Process ended ($($_.Exception.Message)); proceeding."
    }
    Write-Host "Sweep finished."
} else {
    Write-Host "No running sweep found - assuming it already finished. Proceeding to re-eval."
}

# 2) Run the high-episode re-evaluation (read-only).
$script = "experiments/2026-06-23_r7_curriculum_sweep/reeval_winners.py"
Write-Host "Launching re-eval: uv run python $script --episodes $Episodes"
$proc = Start-Process -FilePath "uv" `
    -ArgumentList @("run", "python", $script, "--episodes", "$Episodes") `
    -WorkingDirectory $repo `
    -WindowStyle Hidden `
    -RedirectStandardOutput $out `
    -RedirectStandardError  $err `
    -PassThru -Wait

Write-Host "Re-eval finished (exit $($proc.ExitCode))."
Write-Host "Report:  experiments/2026-06-23_r7_curriculum_sweep/REEVAL_${Episodes}ep.md"
Write-Host "Log:     $out"
