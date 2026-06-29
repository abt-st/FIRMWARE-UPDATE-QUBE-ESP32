"""Unattended launcher: finish R7 + add seeds to pin down the seed variance.

One command, no flags to remember. Trains the curricula × seeds below in a
SINGLE uninterrupted process (no manual relaunch gaps), with:
  - OneDrive sync auto-paused for the whole run (run_r7 does this),
  - keep-best-checkpoint (defends against late-training degradation),
  - resume-safe: runs already in results.json are SKIPPED, so it is safe to
    re-launch after a crash / reboot and it picks up where it left off.

Why these points: 2026-06-24 analysis found balance is high-variance by seed
(cur0.4 collapsed to 0-5% while R6 got 93% at the same prob), and reward is
saturated/useless near the optimum. So we add seeds {2,3} across ALL three
curricula to (a) disambiguate the 0.4 valley and (b) harvest more ~90% net-64
deployment candidates. ~7 new runs × ~90 min ≈ 10-11 h.

Run it (from the repo root):

    uv run python experiments/2026-06-23_r7_curriculum_sweep/run_robust.py

To also re-precise the final pick afterwards, eval the chosen .zip with more
episodes (see audit_eval.py / evaluate_balance n_episodes).
"""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Curricula × seeds to cover. run_r7 skips the (cur, seed) pairs already in
# results.json, so listing the originals here is harmless — only the new
# combinations actually train.
NEAR_UPRIGHT_PROBS = ["0.3", "0.4", "0.5"]
SEEDS = ["0", "1", "2", "3"]
TIMESTEPS = "450000"
CHECKPOINT_FREQ = "50000"
EVAL_EPISODES = "30"  # per-checkpoint scan; re-eval the winner with more later

if __name__ == "__main__":
    sys.argv = [
        "run_r7.py",
        "--near-upright-probs", *NEAR_UPRIGHT_PROBS,
        "--seeds", *SEEDS,
        "--timesteps", TIMESTEPS,
        "--checkpoint-freq", CHECKPOINT_FREQ,
        "--eval-episodes", EVAL_EPISODES,
        # OneDrive is paused by default; pass --keep-onedrive to disable.
    ]
    runpy.run_path(str(HERE / "run_r7.py"), run_name="__main__")
