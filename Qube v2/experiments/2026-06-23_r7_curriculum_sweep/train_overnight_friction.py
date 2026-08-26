"""Overnight (~6 h) friction-adaptation sweep — fine-tune the deployed R7 winner
to the REAL rig's higher friction, so it arrives at the apex controllably.

What we learned this session (2026-06-24/25 bench) drives the design:
  - The deployed R7 (r7_cur0.3_s0_best, 95% balance in NORMAL-friction sim) drops
    to ~35-75% under 100× friction → real friction is a big part of the sim2real
    HOLD gap. Friction-matched fine-tuning is well motivated.
  - The friction system-ID was preliminary (n=1, "inflated by arm coupling"), so
    the true multiplier is uncertain (somewhere ~20-130×). Betting on a single
    100× is risky → SWEEP the multiplier and keep several deployable candidates.
  - Late-training DEGRADES the policy → keep-BEST-by-balance per run, never the
    final checkpoint.

Strategy: for each (friction_mult, seed), load the R7 winner, continue SAC at a
low LR in a sim whose friction matches that multiplier (with wide domain
randomisation so the policy is robust to a range), checkpoint by batches, eval
every checkpoint at the MATCHED friction, and keep the best. Each best is a net-64
candidate ready for export→flash→mode 7 once the bench power is sorted.

Robust + unattended (terminal can be closed):
  - CheckpointCallback every --checkpoint-freq steps (batched saves; crash-safe).
  - keep-best per run; append to results_overnight.json + REPORT_overnight.md
    IMMEDIATELY (progress persists run-by-run).
  - Resume-safe: a (mult, seed) already recorded is SKIPPED.
  - Per-run try/except; model/env freed + gc'd between runs.
  - Wall-clock budget (~6 h): no NEW run is STARTED past the soft deadline, so the
    process winds down on its own near 6 h.
  - OneDrive sync paused for the whole run (always resumed on exit/Ctrl-C/crash).

Usage::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/train_overnight_friction.py
    # smoke: --timesteps 4000 --checkpoint-freq 2000 --friction-mults 50 --seeds 0 \
    #        --eval-episodes 5 --budget-hours 0.2
"""
from __future__ import annotations

import argparse
import contextlib
import gc
import json
import math
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
MODELS_DIR = REPORT_DIR / "models"
CKPT_DIR = REPORT_DIR / "checkpoints_overnight"
RESULTS_JSON = REPORT_DIR / "results_overnight.json"
REPORT_MD = REPORT_DIR / "REPORT_overnight.md"
BASE_MODEL = MODELS_DIR / "r7_cur0.3_s0_best.zip"  # the deployed R7 winner (95% normal-friction)
THETA_LIMIT_DEG = 100.0           # matches the real firmware servo brake
NEAR_UPRIGHT_PROB = 0.3           # cur0.3 was the winning curriculum
# Nominal sim friction (QubeDynamics defaults); the sweep scales these.
DR_NOMINAL = 5e-6
DP_NOMINAL = 1e-6


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def _load_results() -> list[dict]:
    if RESULTS_JSON.exists():
        with contextlib.suppress(Exception):
            return json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    return []


def _persist(results: list[dict]) -> None:
    """Rewrite results_overnight.json + REPORT_overnight.md after every run."""
    tmp = RESULTS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2), encoding="utf-8")
    tmp.replace(RESULTS_JSON)

    lines = [
        "# Overnight friction-adaptation sweep — fine-tune R7 to real friction",
        "",
        f"**Updated:** {_now()} · base=r7_cur0.3_s0_best · reward=linear_alpha · "
        f"theta=±{THETA_LIMIT_DEG:.0f}° · net=[64,64]",
        "",
        "Fine-tune the deployed R7 (95% in normal-friction sim) at higher friction matching the "
        "real rig. Each run keeps its **best checkpoint** (by balance, then hold), evaluated at the "
        "MATCHED friction. `balance` = fraction of episodes holding inverted ≥1 s.",
        "",
        "| Run | friction× | seed | best@step | balance% | upright% | hold_best(s) | reach% | min |",
        "|-----|-----------|------|-----------|----------|----------|--------------|--------|-----|",
    ]
    for r in sorted(results, key=lambda x: (x.get("friction_mult", 0), x.get("seed", 0))):
        if r.get("status") != "ok":
            lines.append(f"| {r.get('run_name','?')} | {r.get('friction_mult','?')} | "
                         f"{r.get('seed','?')} | — | **{r.get('status','?').upper()}** | — | — | — | — |")
            continue
        b = r["best"]
        lines.append(
            f"| {r['run_name']} | {r['friction_mult']} | {r['seed']} | {r['best_step']} | "
            f"{b['balance_rate']*100:.0f} | {b['upright_fraction']*100:.0f} | {b['max_hold_s_best']:.2f} | "
            f"{b['reach_rate']*100:.0f} | {r['elapsed_s']/60:.0f} |"
        )

    ok = [r for r in results if r.get("status") == "ok"]
    if ok:
        best = max(ok, key=lambda r: (r["best"]["balance_rate"], r["best"]["max_hold_s_best"]))
        lines += [
            "",
            "## Mejor candidato global (por balance @ fricción matcheada)",
            "",
            f"- **`{best['run_name']}`** (friction×{best['friction_mult']}) @ step {best['best_step']} — "
            f"balance={best['best']['balance_rate']*100:.0f}%, hold_best={best['best']['max_hold_s_best']:.2f}s, "
            f"upright={best['best']['upright_fraction']*100:.0f}%",
            f"- Modelo: `{best['best_model_path']}`",
            "",
            "Desplegar: `python -m qube_rl.export_rltools --model <zip> "
            "--output src/firmware/esp32_qube/policy_weights.h` → verify_export.py → flashear → modo 7.",
        ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def _make_friction_dyn(mult: float):
    """QubeDynamics with friction scaled by `mult` and wide domain randomisation."""
    from qube_rl.envs.qube_dynamics import QubeDynamics
    # Wide DR (std ~ mean) so each policy is robust to a friction range, not a point.
    return QubeDynamics(
        Dr=DR_NOMINAL * mult, Dr_std=DR_NOMINAL * mult,
        Dp=DP_NOMINAL * mult, Dp_std=0.5 * DP_NOMINAL * mult,
    )


def _make_env(mult: float, *, train: bool):
    """Friction-adjusted sim env (same wrapper stack as the R7/finetune pipeline)."""
    from gymnasium.wrappers import TimeLimit
    from stable_baselines3.common.monitor import Monitor

    from qube_rl.envs.qube_sim import QubeSimEnv
    from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

    theta_rad = math.radians(THETA_LIMIT_DEG)
    env = QubeSimEnv(
        dyn=_make_friction_dyn(mult), control_freq=50, reward="linear_alpha",
        angle_limits=[theta_rad, math.pi], speed_limits=[50.0, 400.0],
        velocity_filter_order=2,
        near_upright_prob=(NEAR_UPRIGHT_PROB if train else 0.0),
    )
    env = TimeLimit(env, max_episode_steps=500)
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=train)
    return env


def train_one(*, mult: float, seed: int, timesteps: int, checkpoint_freq: int,
              eval_episodes: int, lr: float) -> dict:
    """Fine-tune the R7 winner at friction `mult`, keep the best checkpoint."""
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import CheckpointCallback
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import set_global_seeds
    from qube_rl.metrics import evaluate_balance, format_balance_metrics

    set_global_seeds(seed)
    run_name = f"fr{int(mult)}_s{seed}"

    train_env = DummyVecEnv([lambda: _make_env(mult, train=True)])
    train_env.seed(seed)

    model = SAC.load(str(BASE_MODEL))
    model.set_env(train_env)
    model.learning_rate = lr
    model.batch_size = 256

    ckpt_path = CKPT_DIR / run_name
    ckpt_path.mkdir(parents=True, exist_ok=True)
    callback = CheckpointCallback(save_freq=checkpoint_freq, save_path=str(ckpt_path),
                                  name_prefix=run_name)

    t0 = time.time()
    model.learn(total_timesteps=timesteps, progress_bar=False,
                reset_num_timesteps=False, callback=callback)
    elapsed = time.time() - t0

    MODELS_DIR.mkdir(exist_ok=True)
    final_path = MODELS_DIR / f"r7_ft_{run_name}_final.zip"
    model.save(str(final_path))
    log(f"  trained {timesteps:,} in {elapsed/60:.1f} min ({timesteps/elapsed:.0f} fps); scanning checkpoints…")

    # Candidate set: every checkpoint on disk + the final model.
    cand: dict[int, Path] = {}
    for ck in sorted(ckpt_path.glob(f"{run_name}_*_steps.zip")):
        with contextlib.suppress(Exception):
            cand[int(ck.stem.split("_")[-2])] = ck
    cand.setdefault(timesteps, final_path)

    best = None
    eval_env = _make_env(mult, train=False)
    for step, path in sorted(cand.items()):
        with contextlib.suppress(Exception):
            m = SAC.load(str(path))
            bal = evaluate_balance(m, eval_env, n_episodes=eval_episodes, control_freq=50)
            log(f"    step {step:>7}: {format_balance_metrics(bal)}")
            key = (bal["balance_rate"], bal["max_hold_s_best"])
            if best is None or key > (best["bal"]["balance_rate"], best["bal"]["max_hold_s_best"]):
                best = {"step": step, "path": path, "bal": bal}
    eval_env.close()
    if best is None:
        raise RuntimeError("no checkpoint could be evaluated")

    best_model_path = MODELS_DIR / f"r7_ft_{run_name}_best.zip"
    SAC.load(str(best["path"])).save(str(best_model_path))
    log(f"  BEST @ step {best['step']}: {format_balance_metrics(best['bal'])} -> {best_model_path.name}")

    return {
        "status": "ok", "run_name": run_name, "seed": seed, "friction_mult": mult,
        "timesteps": timesteps, "elapsed_s": elapsed, "best_step": best["step"],
        "best_model_path": str(best_model_path), "final_model_path": str(final_path),
        "best": best["bal"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Overnight friction-adaptation sweep (~6 h)")
    parser.add_argument("--friction-mults", type=float, nargs="+", default=[20, 40, 70, 100])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--timesteps", type=int, default=180_000)
    parser.add_argument("--checkpoint-freq", type=int, default=45_000)
    parser.add_argument("--eval-episodes", type=int, default=20)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--budget-hours", type=float, default=6.0)
    parser.add_argument("--per-run-minutes", type=float, default=45.0,
                        help="estimate used to stop starting new runs before the budget")
    parser.add_argument("--keep-onedrive", action="store_true")
    args = parser.parse_args()

    if not BASE_MODEL.exists():
        log(f"ERROR: base model not found: {BASE_MODEL}")
        sys.exit(1)

    from qube_rl.onedrive_guard import onedrive_paused

    # Order: cover EVERY friction with seed[0] first, then seed[1], … so an early
    # stop still leaves one candidate per friction.
    grid = [(m, s) for s in args.seeds for m in args.friction_mults]

    log("=" * 64)
    log("Overnight friction-adaptation sweep (fine-tune R7 winner)")
    log(f"  base={BASE_MODEL.name}")
    log(f"  friction_mults={args.friction_mults}  seeds={args.seeds}  -> {len(grid)} runs (sequential)")
    log(f"  timesteps/run={args.timesteps:,}  checkpoint every {args.checkpoint_freq:,}  "
        f"eval_eps={args.eval_episodes}  lr={args.lr:.0e}")
    log(f"  budget={args.budget_hours:.1f} h  (stop starting new runs past the soft deadline)")
    log("=" * 64)

    results = _load_results()
    done = {(r["friction_mult"], r["seed"]) for r in results if r.get("status") == "ok"}

    t_start = time.time()
    budget_s = args.budget_hours * 3600.0
    per_run_s = args.per_run_minutes * 60.0

    with onedrive_paused(enabled=not args.keep_onedrive):
        if not args.keep_onedrive:
            log("OneDrive sync PAUSED for the run (use --keep-onedrive to disable)")
        for i, (mult, seed) in enumerate(grid, 1):
            if (mult, seed) in done:
                log(f"[{i}/{len(grid)}] SKIP friction×{mult} seed={seed} (already done)")
                continue
            elapsed = time.time() - t_start
            if elapsed + per_run_s > budget_s:
                log(f"[{i}/{len(grid)}] STOP starting new runs: {elapsed/3600:.2f} h elapsed, "
                    f"a new ~{per_run_s/60:.0f} min run would exceed the {args.budget_hours:.1f} h budget.")
                break
            log(f"[{i}/{len(grid)}] TRAIN friction×{mult} seed={seed}  "
                f"(elapsed {elapsed/3600:.2f} h)")
            try:
                r = train_one(mult=mult, seed=seed, timesteps=args.timesteps,
                              checkpoint_freq=args.checkpoint_freq,
                              eval_episodes=args.eval_episodes, lr=args.lr)
            except Exception as exc:  # noqa: BLE001 — overnight: one failure must not kill the sweep
                log(f"  ERROR friction×{mult} seed={seed}: {exc}")
                traceback.print_exc()
                r = {"status": "error", "run_name": f"fr{int(mult)}_s{seed}", "seed": seed,
                     "friction_mult": mult, "timesteps": args.timesteps, "error": str(exc)}
            results = [x for x in results
                       if not (x.get("friction_mult") == mult and x.get("seed") == seed)]
            results.append(r)
            _persist(results)
            log(f"  persisted -> {RESULTS_JSON.name} / {REPORT_MD.name}")
            gc.collect()

    total_h = (time.time() - t_start) / 3600.0
    log(f"ALL DONE in {total_h:.2f} h — see {REPORT_MD.name} (OneDrive sync resumed)")


if __name__ == "__main__":
    main()
