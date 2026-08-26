"""Re-evaluate the OVERNIGHT friction-adapted candidates with MANY episodes.

The overnight sweep (train_overnight_friction.py) scanned each checkpoint with
only 20 episodes to pick the best one fast — enough to rank, but the balance%
carries big sampling noise (a 80% from 20 ep is +/- ~15pp, and seed-0 vs seed-1
at the same friction differed by 50pp, a red flag that the pick may be luck).

Before trusting any number / picking a model to flash, re-measure each
`r7_ft_fr{mult}_s{seed}_best.zip` at 100 episodes. Crucially, each model is
evaluated at ITS OWN matched friction (the multiplier it was fine-tuned at),
reusing the EXACT env builder from the sweep (`_make_env`) so friction, DR,
wrappers and theta limit are identical. Reports std (swing-up) + apex (stab-only).

Read-only w.r.t. training: only LOADS the saved best models.

Run::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/reeval_overnight_100ep.py
    uv run python experiments/2026-06-23_r7_curriculum_sweep/reeval_overnight_100ep.py --episodes 200
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

HERE = Path(__file__).resolve().parent
MODELS_DIR = HERE / "models"
# Reuse the sweep's env builder so friction / DR / wrappers are byte-identical.
sys.path.insert(0, str(HERE))
from train_overnight_friction import _make_env  # noqa: E402

# r7_ft_fr70_s0_best.zip -> mult=70, seed=0
_NAME_RE = re.compile(r"r7_ft_fr(\d+)_s(\d+)_best")


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-eval overnight friction candidates @ matched friction")
    parser.add_argument("--episodes", type=int, default=100,
                        help="episodes per evaluation (default 100; more = tighter balance%)")
    args = parser.parse_args()

    from stable_baselines3 import SAC

    from qube_rl.metrics import evaluate_balance

    models = sorted(MODELS_DIR.glob("r7_ft_fr*_best.zip"))
    print(f"[{_now()}] re-eval {len(models)} overnight candidates @ {args.episodes} ep "
          f"(std + apex), each at its MATCHED friction", flush=True)
    if not models:
        print("  (no r7_ft_fr*_best.zip found — nothing to do)", flush=True)
        return

    hdr = (f"{'model':14s} | {'fr':>4s} {'seed':>4s} | {'std bal':>8s} {'reach':>6s} {'upr':>5s} "
           f"{'hold_avg':>8s} {'hold*':>6s} | {'apex bal':>8s} {'apex hold*':>10s}")
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)

    rows: list[dict] = []
    for path in models:
        m = _NAME_RE.search(path.stem)
        if not m:
            print(f"{path.stem:14s} | UNPARSEABLE NAME — skip", flush=True)
            continue
        mult, seed = int(m.group(1)), int(m.group(2))
        label = f"fr{mult}_s{seed}"
        try:
            model = SAC.load(str(path))
        except Exception as exc:  # noqa: BLE001
            print(f"{label:14s} | LOAD ERROR: {exc}", flush=True)
            rows.append({"model": label, "friction_mult": mult, "seed": seed,
                         "path": str(path), "status": "load_error", "error": str(exc)})
            continue

        # Std swing-up reset at matched friction.
        env = _make_env(mult, train=False)
        std = evaluate_balance(model, env, n_episodes=args.episodes, control_freq=50)
        with contextlib.suppress(Exception):
            env.close()

        # Apex (stabilisation-only) reset at matched friction.
        apex = {"balance_rate": float("nan"), "max_hold_s_best": float("nan")}
        with contextlib.suppress(Exception):
            aenv = _make_env(mult, train=False)
            apex = evaluate_balance(model, aenv, n_episodes=args.episodes, control_freq=50,
                                    reset_options={"near_upright": True})
            aenv.close()

        print(f"{label:14s} | {mult:>4d} {seed:>4d} | {std['balance_rate']*100:7.1f}% "
              f"{std['reach_rate']*100:5.0f}% {std['upright_fraction']*100:4.0f}% "
              f"{std['max_hold_s']:7.2f} {std['max_hold_s_best']:5.2f} | "
              f"{apex['balance_rate']*100:7.1f}% {apex['max_hold_s_best']:9.2f}", flush=True)
        rows.append({"model": label, "friction_mult": mult, "seed": seed, "path": str(path),
                     "status": "ok", "episodes": args.episodes, "std": std, "apex": apex})

    ok = [r for r in rows if r.get("status") == "ok"]
    ok.sort(key=lambda r: (r["std"]["balance_rate"], r["std"]["max_hold_s_best"]), reverse=True)

    out_json = HERE / f"reeval_overnight_{args.episodes}ep.json"
    out_json.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = [
        f"# Overnight friction sweep — re-evaluación de candidatos a {args.episodes} episodios",
        "",
        f"**Updated:** {_now()} · reward=linear_alpha · theta=±100° · control_freq=50 · "
        f"n_ep={args.episodes} · cada modelo @ su fricción matcheada",
        "",
        "Re-medición de alta precisión de los `r7_ft_fr*_best.zip` (el sweep los eligió con 20 ep; "
        "esto los confirma con muchos más, a la MISMA fricción a la que se entrenaron). "
        "Ordenado por balance estándar.",
        "",
        "| Modelo | fr× | seed | balance% | upright% | hold_avg(s) | hold_best(s) | reach% | apex% |",
        "|--------|-----|------|----------|----------|-------------|--------------|--------|-------|",
    ]
    for r in ok:
        s, a = r["std"], r["apex"]
        lines.append(
            f"| {r['model']} | {r['friction_mult']} | {r['seed']} | {s['balance_rate']*100:.0f} | "
            f"{s['upright_fraction']*100:.0f} | {s['max_hold_s']:.2f} | {s['max_hold_s_best']:.2f} | "
            f"{s['reach_rate']*100:.0f} | {a.get('balance_rate', float('nan'))*100:.0f} |"
        )
    if ok:
        top = ok[0]
        lines += [
            "",
            "## Mejor candidato confirmado (mayor balance @ fricción matcheada, desempate hold_best)",
            "",
            f"- **`{top['model']}`** (friction×{top['friction_mult']}, seed {top['seed']}) — "
            f"balance={top['std']['balance_rate']*100:.0f}%, hold_best={top['std']['max_hold_s_best']:.2f}s, "
            f"upright={top['std']['upright_fraction']*100:.0f}% ({args.episodes} ep)",
            f"- Modelo: `{top['path']}`",
            "",
            "Desplegar: `python -m qube_rl.export_rltools --model <zip> "
            "--output src/firmware/esp32_qube/policy_weights.h` → verify_export.py → flashear → modo 7.",
        ]
    (HERE / f"REEVAL_overnight_{args.episodes}ep.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[{_now()}] DONE -> reeval_overnight_{args.episodes}ep.json / "
          f"REEVAL_overnight_{args.episodes}ep.md", flush=True)


if __name__ == "__main__":
    main()
