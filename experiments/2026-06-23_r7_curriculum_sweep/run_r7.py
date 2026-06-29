"""R7: reproduce + harden the R6 balance success, KEEPING THE BEST CHECKPOINT.

Data-driven design (audit_eval.py, 2026-06-23): the real best model is
R6 s0 @ step400k = 93.3% sim balance — NOT the 50% the R6 HANDOFF claimed, and
the 500k FINAL degraded to 40%. So:
  - sim balance is essentially solved with near_upright_prob=0.4, ~400k steps;
  - training PAST the peak DEGRADES the policy (late-training instability);
  - the bottleneck is sim->real transfer of the hold (today's A4 firmware fix).

This run therefore reproduces the proven config across a short curriculum spread
and seeds, and — crucially — evaluates ALL checkpoints of each run and keeps the
BEST one (by balance, then hold), defending against the degradation we observed.
Output: several deployable net-64 candidates for export -> flash -> mode 7.

Config (inherited from R6, sim2real-validated): reward=linear_alpha,
theta_limit=100 deg, net_arch=[64,64], history_steps=4 (36-dim obs).
Sweep: near_upright_prob in {0.3, 0.4, 0.5} x seeds {0, 1}.

Robustness (unattended overnight — DATA MUST NOT BE LOST):
  - CheckpointCallback every --checkpoint-freq steps (crash keeps partial models).
  - After each run: eval every checkpoint, keep the best, append to results.json +
    REPORT.md IMMEDIATELY (progress persists run-by-run).
  - Per-run try/except: one failing run never kills the rest.
  - Resume-safe: a run whose result is already recorded is SKIPPED.
  - Model/env freed + gc'd between runs (6 sequential runs must not OOM).
  - MLflow per run (sqlite).

Usage::

    # Smoke test first (verify pipeline end-to-end + measure FPS, ~minutes):
    uv run python experiments/2026-06-23_r7_curriculum_sweep/run_r7.py \
        --timesteps 4000 --checkpoint-freq 2000 --near-upright-probs 0.4 --seeds 0 --eval-episodes 5

    # Full overnight run (size --timesteps from the smoke FPS):
    uv run python experiments/2026-06-23_r7_curriculum_sweep/run_r7.py \
        --timesteps 450000 --checkpoint-freq 50000
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

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
MODELS_DIR = REPORT_DIR / "models"
CKPT_DIR = REPORT_DIR / "checkpoints"
RESULTS_JSON = REPORT_DIR / "results.json"
REPORT_MD = REPORT_DIR / "REPORT.md"
MLFLOW_EXPERIMENT = "qube_r7_curriculum_sweep"
THETA_LIMIT_DEG = 100.0  # matches the real firmware servo brake (R6 alignment)


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
    """Rewrite results.json + REPORT.md after every run (no data loss on crash)."""
    tmp = RESULTS_JSON.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2), encoding="utf-8")
    tmp.replace(RESULTS_JSON)

    lines = [
        "# R7 — Reproduce R6 balance, keep best checkpoint",
        "",
        f"**Updated:** {_now()} · reward=linear_alpha · theta=±{THETA_LIMIT_DEG:.0f}° · net=[64,64]",
        "",
        "Baseline (audit_eval.py): mejor previo = **R6 s0 step400k = 93.3% balance** (el final 500k cayó a 40%).",
        "Cada run reporta su **mejor checkpoint** (no el final), defensa contra la degradación de late-training.",
        "`balance` = fracción de episodios que sostuvieron el invertido (lento) ≥1 s.",
        "",
        "| Run | curric | seed | best@step | balance% | upright% | hold_best(s) | reach% | apex% | min |",
        "|-----|--------|------|-----------|----------|----------|--------------|--------|-------|-----|",
    ]
    for r in sorted(results, key=lambda x: (x.get("near_upright_prob", 0), x.get("seed", 0))):
        if r.get("status") != "ok":
            lines.append(f"| {r.get('run_name','?')} | {r.get('near_upright_prob','?')} | "
                         f"{r.get('seed','?')} | — | **{r.get('status','?').upper()}** | — | — | — | — | — |")
            continue
        b = r["best"]
        apex = r.get("best_apex", {})
        lines.append(
            f"| {r['run_name']} | {r['near_upright_prob']} | {r['seed']} | {r['best_step']} | "
            f"{b['balance_rate']*100:.0f} | {b['upright_fraction']*100:.0f} | {b['max_hold_s_best']:.2f} | "
            f"{b['reach_rate']*100:.0f} | {apex.get('balance_rate', float('nan'))*100:.0f} | {r['elapsed_s']/60:.0f} |"
        )

    ok = [r for r in results if r.get("status") == "ok"]
    if ok:
        best = max(ok, key=lambda r: (r["best"]["balance_rate"], r["best"]["max_hold_s_best"]))
        lines += [
            "",
            "## Mejor candidato global (por balance, desempate hold_best)",
            "",
            f"- **`{best['run_name']}`** @ step {best['best_step']} — balance={best['best']['balance_rate']*100:.0f}%, "
            f"hold_best={best['best']['max_hold_s_best']:.2f}s, upright={best['best']['upright_fraction']*100:.0f}%",
            f"- Modelo: `{best['best_model_path']}`",
            "",
            "Desplegar: `python -m qube_rl.export_rltools --model <zip> "
            "--output src/firmware/esp32_qube/policy_weights.h` → verificar fwd vs predict → flashear → modo 7.",
        ]
    REPORT_MD.write_text("\n".join(lines), encoding="utf-8")


def train_one(*, seed: int, near_upright_prob: float, timesteps: int, checkpoint_freq: int,
              eval_episodes: int, mlflow_kw: dict) -> dict:
    """Train one (curriculum, seed), then eval ALL checkpoints and keep the best."""
    from stable_baselines3 import SAC
    from stable_baselines3.common.callbacks import CallbackList, CheckpointCallback
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance, format_balance_metrics
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    set_global_seeds(seed)
    cfg = SACConfig()
    theta_rad = math.radians(THETA_LIMIT_DEG)
    run_name = f"cur{near_upright_prob:.1f}_s{seed}"

    def _make():
        return make_sim_env(reward="linear_alpha", potential=None,
                            near_upright_prob=near_upright_prob, angle_limits=[theta_rad, math.pi])

    train_env = DummyVecEnv([_make])
    train_env.seed(seed)
    model = SAC(
        "MlpPolicy", train_env,
        learning_rate=cfg.learning_rate, buffer_size=cfg.buffer_size, batch_size=cfg.batch_size,
        gamma=cfg.gamma, tau=cfg.tau, use_sde=cfg.use_sde, use_sde_at_warmup=cfg.use_sde_at_warmup,
        sde_sample_freq=cfg.sde_sample_freq, train_freq=cfg.train_freq, gradient_steps=cfg.gradient_steps,
        learning_starts=cfg.learning_starts, policy_kwargs=dict(net_arch=[cfg.net_arch, cfg.net_arch]),
        verbose=0, seed=seed,
    )

    params = build_params(seed=seed, reward="linear_alpha", potential="None",
                          timesteps=timesteps, net_arch=cfg.net_arch, run_name=run_name)
    params["theta_limit_deg"] = THETA_LIMIT_DEG
    params["near_upright_prob"] = near_upright_prob

    ckpt_path = CKPT_DIR / run_name
    ckpt_path.mkdir(parents=True, exist_ok=True)
    callbacks = CallbackList([
        make_metrics_callback(enabled=mlflow_kw.get("enabled", True)),
        CheckpointCallback(save_freq=checkpoint_freq, save_path=str(ckpt_path), name_prefix=run_name),
    ])

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw):
        model.learn(total_timesteps=timesteps, progress_bar=False, callback=callbacks)
    elapsed = time.time() - t0

    MODELS_DIR.mkdir(exist_ok=True)
    final_path = MODELS_DIR / f"r7_{run_name}_final.zip"
    model.save(str(final_path))
    log(f"  trained {timesteps:,} in {elapsed/60:.1f} min ({timesteps/elapsed:.0f} fps); scanning checkpoints…")

    # Candidate set: every checkpoint on disk + the final model. Deduplicate by
    # step (CheckpointCallback also saves at `timesteps`, == the final model).
    cand: dict[int, Path] = {}
    for ck in sorted(ckpt_path.glob(f"{run_name}_*_steps.zip")):
        with contextlib.suppress(Exception):
            cand[int(ck.stem.split("_")[-2])] = ck
    cand.setdefault(timesteps, final_path)
    candidates = sorted(cand.items())

    best = None
    eval_env = make_sim_env(reward="linear_alpha", angle_limits=[theta_rad, math.pi])
    for step, path in candidates:
        with contextlib.suppress(Exception):
            m = SAC.load(str(path))
            bal = evaluate_balance(m, eval_env, n_episodes=eval_episodes, control_freq=50)
            log(f"    step {step:>7}: {format_balance_metrics(bal)}")
            key = (bal["balance_rate"], bal["max_hold_s_best"])
            if best is None or key > (best["bal"]["balance_rate"], best["bal"]["max_hold_s_best"]):
                best = {"step": step, "path": path, "bal": bal}
    if best is None:
        raise RuntimeError("no checkpoint could be evaluated")

    # Persist the winning checkpoint as the deployable model + an apex diagnostic on it.
    best_model_path = MODELS_DIR / f"r7_{run_name}_best.zip"
    SAC.load(str(best["path"])).save(str(best_model_path))
    best_apex: dict = {}
    with contextlib.suppress(Exception):
        apex_env = make_sim_env(reward="linear_alpha", angle_limits=[theta_rad, math.pi])
        best_apex = evaluate_balance(SAC.load(str(best_model_path)), apex_env,
                                     n_episodes=eval_episodes, control_freq=50,
                                     reset_options={"near_upright": True})
    log(f"  BEST @ step {best['step']}: {format_balance_metrics(best['bal'])} -> {best_model_path.name}")

    return {
        "status": "ok", "run_name": run_name, "seed": seed, "near_upright_prob": near_upright_prob,
        "timesteps": timesteps, "elapsed_s": elapsed, "best_step": best["step"],
        "best_model_path": str(best_model_path), "final_model_path": str(final_path),
        "best": best["bal"], "best_apex": best_apex,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="R7: reproduce R6 balance, keep best checkpoint")
    parser.add_argument("--timesteps", type=int, default=450_000)
    parser.add_argument("--near-upright-probs", type=float, nargs="+", default=[0.3, 0.4, 0.5])
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1])
    parser.add_argument("--checkpoint-freq", type=int, default=50_000)
    parser.add_argument("--eval-episodes", type=int, default=20)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    parser.add_argument("--keep-onedrive", action="store_true",
                        help="do NOT pause OneDrive during the sweep (default: pause it)")
    args = parser.parse_args()

    from qube_rl.onedrive_guard import onedrive_paused

    mlflow_kw = {"enabled": True, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}
    grid = [(c, s) for c in args.near_upright_probs for s in args.seeds]

    log("=" * 64)
    log("R7: reproduce R6 balance + keep best checkpoint")
    log(f"  near_upright_probs={args.near_upright_probs}  seeds={args.seeds}  -> {len(grid)} runs (sequential)")
    log(f"  timesteps/run={args.timesteps:,}  checkpoint every {args.checkpoint_freq:,}  eval_eps={args.eval_episodes}")
    log("=" * 64)

    results = _load_results()
    done = {(r["near_upright_prob"], r["seed"]) for r in results if r.get("status") == "ok"}

    # Pause OneDrive sync for the whole sweep: the project (incl. mlflow.db and
    # the checkpoints/) lives in a synced folder, and sync contention slows runs
    # and risks DB corruption. Always resumed on exit (even on Ctrl-C / crash).
    with onedrive_paused(enabled=not args.keep_onedrive):
        if not args.keep_onedrive:
            log("OneDrive sync PAUSED for the run (use --keep-onedrive to disable)")
        for i, (cur, seed) in enumerate(grid, 1):
            if (cur, seed) in done:
                log(f"[{i}/{len(grid)}] SKIP cur={cur} seed={seed} (already done)")
                continue
            log(f"[{i}/{len(grid)}] TRAIN cur={cur} seed={seed}")
            try:
                r = train_one(seed=seed, near_upright_prob=cur, timesteps=args.timesteps,
                              checkpoint_freq=args.checkpoint_freq, eval_episodes=args.eval_episodes,
                              mlflow_kw=mlflow_kw)
            except Exception as exc:  # noqa: BLE001 — overnight: one failure must not kill the sweep
                log(f"  ERROR cur={cur} seed={seed}: {exc}")
                traceback.print_exc()
                r = {"status": "error", "run_name": f"cur{cur:.1f}_s{seed}", "seed": seed,
                     "near_upright_prob": cur, "timesteps": args.timesteps, "error": str(exc)}
            results = [x for x in results if not (x.get("near_upright_prob") == cur and x.get("seed") == seed)]
            results.append(r)
            _persist(results)
            log(f"  persisted -> {RESULTS_JSON.name} / {REPORT_MD.name}")
            gc.collect()

    log("ALL DONE — see REPORT.md (OneDrive sync resumed)")


if __name__ == "__main__":
    main()
