# Chainer: waits for the R4 training process to finish, then launches R5.
# Robust trigger = the run_r4.py python process disappearing (handles both a
# clean "ALL DONE" finish and a crash; either way R5 — the more promising run —
# should start). Detached: launched hidden so it survives the parent session.

$ErrorActionPreference = 'SilentlyContinue'
$repo = 'C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE'
$dir  = Join-Path $repo 'experiments\2026-06-22_r5_pbrs_curriculum'
$heartbeat = Join-Path $dir 'chain_r5.log'
$py   = Join-Path $repo '.venv\Scripts\python.exe'
$r5   = Join-Path $dir 'run_r5.py'
$out  = Join-Path $dir 'run_r5_2026-06-22.log'
$err  = Join-Path $dir 'run_r5_2026-06-22.err.log'

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Add-Content -Path $heartbeat -Encoding utf8 }

Log "chainer started; waiting for run_r4.py to finish ..."

while ($true) {
    $r4 = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
          Where-Object { $_.CommandLine -like '*run_r4.py*' }
    if (-not $r4) { break }
    Start-Sleep -Seconds 60
}

Log "run_r4.py no longer running. Waiting 15s, then launching R5 ..."
Start-Sleep -Seconds 15

# Guard: do not double-launch if an R5 is somehow already running.
$r5running = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
             Where-Object { $_.CommandLine -like '*run_r5.py*' }
if ($r5running) { Log "R5 already running; chainer exiting."; exit 0 }

$argList = @($r5,'--budget-hours','10','--timesteps','500000','--seeds','0','1','2')
Start-Process -FilePath $py -ArgumentList $argList -WorkingDirectory $repo `
    -RedirectStandardOutput $out -RedirectStandardError $err -WindowStyle Hidden

Log "R5 launched (500k x 3 seeds). stdout -> $out"
