"""Re-evaluate every R7 best checkpoint with MANY episodes (default 100).

The overnight sweep scans each checkpoint with only 20-30 episodes to pick the
best one fast. That is enough to RANK checkpoints, but the resulting balance%
still carries sampling noise (a 90% from 20 episodes is +/- ~10pp). Before we
trust a number for the thesis / pick a model to flash, we re-measure the chosen
`r7_*_best.zip` models with a large episode budget so the balance% is precise.

Read-only w.r.t. training: it only LOADS the saved best models and evaluates
them in the SAME sim env as run_r7 (linear_alpha, theta=+/-100 deg), reporting
both the standard swing-up reset and the apex (stabilisation-only) reset.

Run (after the sweep finishes — watch_then_reeval.ps1 does this automatically):

    uv run python experiments/2026-06-23_r7_curriculum_sweep/reeval_winners.py
    uv run python experiments/2026-06-23_r7_curriculum_sweep/reeval_winners.py --episodes 200
"""
from __future__ import annotations

import argparse
import contextlib
import json
import math
import sys
import time
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
THETA_RAD = math.radians(100.0)  # same servo-brake limit as run_r7 / R6


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-eval R7 best checkpoints with many episodes")
    parser.add_argument("--episodes", type=int, default=100,
                        help="episodes per evaluation (default 100; more = tighter balance%)")
    args = parser.parse_args()

    from stable_baselines3 import SAC

    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance

    models = sorted(MODELS_DIR.glob("r7_*_best.zip"))
    print(f"[{_now()}] re-eval {len(models)} best models @ {args.episodes} episodes "
          f"(std + apex), theta=+/-100deg, linear_alpha", flush=True)
    if not models:
        print("  (no r7_*_best.zip found — nothing to do)", flush=True)
        return

    hdr = (f"{'model':22s} | {'std bal':>8s} {'reach':>6s} {'upr':>5s} {'hold_avg':>8s} "
           f"{'hold*':>6s} | {'apex bal':>8s} {'apex hold*':>10s}")
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)

    rows: list[dict] = []
    for path in models:
        label = path.stem.replace("r7_", "").replace("_best", "")
        try:
            model = SAC.load(str(path))
        except Exception as exc:  # noqa: BLE001
            print(f"{label:22s} | LOAD ERROR: {exc}", flush=True)
            rows.append({"model": label, "path": str(path), "status": "load_error", "error": str(exc)})
            continue

        env = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
        std = evaluate_balance(model, env, n_episodes=args.episodes, control_freq=50)

        apex = {"balance_rate": float("nan"), "max_hold_s_best": float("nan")}
        with contextlib.suppress(Exception):
            aenv = make_sim_env(reward="linear_alpha", angle_limits=[THETA_RAD, math.pi])
            apex = evaluate_balance(model, aenv, n_episodes=args.episodes, control_freq=50,
                                    reset_options={"near_upright": True})

        print(f"{label:22s} | {std['balance_rate']*100:7.1f}% {std['reach_rate']*100:5.0f}% "
              f"{std['upright_fraction']*100:4.0f}% {std['max_hold_s']:7.2f} {std['max_hold_s_best']:5.2f} | "
              f"{apex['balance_rate']*100:7.1f}% {apex['max_hold_s_best']:9.2f}", flush=True)
        rows.append({"model": label, "path": str(path), "status": "ok",
                     "episodes": args.episodes, "std": std, "apex": apex})

    # Persist JSON + a markdown report sorted by std balance (tie-break hold_best).
    ok = [r for r in rows if r.get("status") == "ok"]
    ok.sort(key=lambda r: (r["std"]["balance_rate"], r["std"]["max_hold_s_best"]), reverse=True)

    out_json = HERE / f"reeval_{args.episodes}ep.json"
    out_json.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = [
        f"# R7 — Re-evaluación de finalistas a {args.episodes} episodios",
        "",
        f"**Updated:** {_now()} · reward=linear_alpha · theta=±100° · control_freq=50 · n_ep={args.episodes}",
        "",
        "Re-medición de alta precisión de los `r7_*_best.zip` (el sweep los eligió con 20-30 ep; "
        "esto los confirma con muchos más). Ordenado por balance estándar.",
        "",
        "| Modelo | balance% | upright% | hold_avg(s) | hold_best(s) | reach% | apex% |",
        "|--------|----------|----------|-------------|--------------|--------|-------|",
    ]
    for r in ok:
        s, a = r["std"], r["apex"]
        lines.append(
            f"| {r['model']} | {s['balance_rate']*100:.0f} | {s['upright_fraction']*100:.0f} | "
            f"{s['max_hold_s']:.2f} | {s['max_hold_s_best']:.2f} | {s['reach_rate']*100:.0f} | "
            f"{a.get('balance_rate', float('nan'))*100:.0f} |"
        )
    if ok:
        top = ok[0]
        lines += [
            "",
            "## Ganador confirmado (mayor balance, desempate hold_best)",
            "",
            f"- **`{top['model']}`** — balance={top['std']['balance_rate']*100:.0f}%, "
            f"hold_best={top['std']['max_hold_s_best']:.2f}s, upright={top['std']['upright_fraction']*100:.0f}% "
            f"({args.episodes} ep)",
            f"- Modelo: `{top['path']}`",
            "",
            "Desplegar: `python -m qube_rl.export_rltools --model <zip> "
            "--output src/firmware/esp32_qube/policy_weights.h` → verificar fwd vs predict → flashear → modo 7.",
        ]
    (HERE / f"REEVAL_{args.episodes}ep.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[{_now()}] DONE -> reeval_{args.episodes}ep.json / REEVAL_{args.episodes}ep.md", flush=True)


if __name__ == "__main__":
    main()
