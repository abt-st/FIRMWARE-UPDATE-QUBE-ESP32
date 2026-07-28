# finetune_measured.ps1 - STEP 3: directed fine-tune at the MEASURED friction.
#
# Run this only AFTER:
#   1) diagnose_real_vs_sim.py confirmed the real-hold gap is friction/torque, and
#   2) measure_friction_spindown.py gave you a friction multiplier (avg of 3+ captures).
#
# It fine-tunes the R7 winner at that ONE multiplier across several seeds (the
# 25-06 lesson: the seed mattered more than the friction, so don't trust one),
# selecting the best checkpoint by balance at 100 ep, then re-confirms at 100 ep.
# NOT another blind sweep - a single measured target.
#
# Use:  .\finetune_measured.ps1 -FrictionMult 43
#       .\finetune_measured.ps1 -FrictionMult 43 -Seeds 0,1,2,3 -BudgetHours 3

param(
    [Parameter(Mandatory = $true)]
    [double]$FrictionMult,                 # the measured friction multiplier from the spin-down
    [int[]]$Seeds = @(0, 1, 2),            # >=3 seeds; the winner is picked across them
    [int]$Timesteps = 180000,
    [int]$EvalEpisodes = 100,              # 100-ep keep-best from the start (no 20-ep noise)
    [double]$BudgetHours = 3.0
)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
Set-Location $repo
$exp = "experiments/2026-06-23_r7_curriculum_sweep"

# Keep the machine awake for the unattended run (plugged in).
Write-Host "Disabling sleep/hibernate on AC power..."
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0

$seedArg = ($Seeds | ForEach-Object { "$_" }) -join " "
Write-Host ""
Write-Host "STEP 3 - directed fine-tune at friction x$FrictionMult"
Write-Host "  seeds=$seedArg  timesteps=$Timesteps  eval_episodes=$EvalEpisodes  budget=${BudgetHours}h"
Write-Host ""

# 1) Fine-tune at the measured multiplier (keep-best per seed @ 100 ep).
#    train_overnight_friction.py is resume-safe: a (mult, seed) already in
#    results_overnight.json is skipped, so re-running after a crash continues.
$train = "$exp/train_overnight_friction.py"
Write-Host "Launching: uv run python $train --friction-mults $FrictionMult --seeds $seedArg ..."
& uv run python $train `
    --friction-mults $FrictionMult `
    --seeds $Seeds `
    --timesteps $Timesteps `
    --eval-episodes $EvalEpisodes `
    --budget-hours $BudgetHours
if ($LASTEXITCODE -ne 0) { Write-Host "Fine-tune exited $LASTEXITCODE - stopping."; exit $LASTEXITCODE }

# 2) Re-confirm every ft candidate at 100 ep, each at its matched friction.
Write-Host ""
Write-Host "Re-evaluating candidates at 100 ep (matched friction)..."
& uv run python "$exp/reeval_overnight_100ep.py" --episodes 100
if ($LASTEXITCODE -ne 0) { Write-Host "Re-eval exited $LASTEXITCODE."; exit $LASTEXITCODE }

# 3) Next steps (manual - needs the bench).
$best = "$exp/models/r7_ft_fr$([int]$FrictionMult)_s$($Seeds[0])_best.zip"
Write-Host ""
Write-Host "================================================================"
Write-Host "DONE. Best per seed is in $exp/REEVAL_overnight_100ep.md"
Write-Host "Pick the highest-balance seed there (don't assume seed 0), then:"
Write-Host ""
Write-Host "  uv run python -m qube_rl.export_rltools --model <that_zip> --output src/firmware/esp32_qube/policy_weights.h"
Write-Host "  uv run python $exp/verify_export.py        # fwd vs predict"
Write-Host "  # flash the ESP32, then mode 7"
Write-Host ""
Write-Host "Example zip for seed $($Seeds[0]): $best"
Write-Host "================================================================"
Read-Host "Press Enter to close (training already finished)"
