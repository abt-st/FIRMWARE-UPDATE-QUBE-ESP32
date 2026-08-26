"""Overnight DRL training + reporting for the QUBE swing-up/balance problem.

Runs a prioritized list of experiments (reward variants x optional PBRS shaping),
each across several seeds, under a wall-clock budget.  After EVERY experiment it
writes a deep markdown report; at the end (or when the budget runs out) it writes
a consolidated FINAL_REPORT.md.  MLflow tracks every per-seed run.

Self-contained: reuses qube_rl (env factory, balance metric, mlflow helpers).
Designed to be launched in the background and left to run overnight.

Usage::

    python -m experiments... NO — run directly with the venv python:
    .venv/Scripts/python.exe experiments/overnight_2026-06-18/run_overnight.py \
        --budget-hours 5 --timesteps 100000 --seeds 0 1 2
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# Windows consoles default to cp1252 and crash on non-ASCII; emit UTF-8 instead.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
MLFLOW_EXPERIMENT = "qube_overnight"

# Prioritized experiment matrix. The first ones run first, so put the most
# informative configs early in case the budget runs out.
EXPERIMENTS: list[dict] = [
    # Ordered by expected informativeness so a budget cut keeps the best comparison:
    {"name": "01_swingup_balance_base", "reward": "swingup_balance", "potential": None},  # default baseline to beat
    {"name": "02_linear_alpha_pbrs", "reward": "linear_alpha", "potential": "upright"},   # dense reward + correct shaping
    {"name": "03_linear_alpha_base", "reward": "linear_alpha", "potential": None},        # isolates the PBRS effect
    {"name": "04_swingup_balance_pbrs", "reward": "swingup_balance", "potential": "upright"},
    {"name": "05_linear_alpha_dense", "reward": "linear_alpha_dense", "potential": None},
    {"name": "06_cos_alpha_base", "reward": "cos_alpha", "potential": None},
]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def train_one_seed(
    *,
    reward: str,
    potential: str | None,
    seed: int,
    timesteps: int,
    net_arch: int,
    buffer_size: int,
    run_name: str,
    mlflow_kw: dict,
    eval_episodes: int,
) -> dict:
    """Train SAC for a single seed and return episode + balance metrics."""
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import SACConfig, set_global_seeds
    from qube_rl.envs.factory import make_sim_env
    from qube_rl.metrics import evaluate_balance
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    cfg = SACConfig()
    set_global_seeds(seed)

    train_env = DummyVecEnv([lambda: make_sim_env(reward=reward, potential=potential)])
    train_env.seed(seed)

    model = SAC(
        "MlpPolicy",
        train_env,
        learning_rate=cfg.learning_rate,
        buffer_size=buffer_size,
        batch_size=cfg.batch_size,
        tau=cfg.tau,
        gamma=cfg.gamma,
        use_sde=cfg.use_sde,
        use_sde_at_warmup=cfg.use_sde_at_warmup,
        sde_sample_freq=cfg.sde_sample_freq,
        train_freq=cfg.train_freq,
        gradient_steps=cfg.gradient_steps,
        learning_starts=cfg.learning_starts,
        seed=seed,
        verbose=0,
        policy_kwargs=dict(net_arch=dict(pi=[net_arch, net_arch], qf=[net_arch, net_arch])),
    )

    params = build_params(
        seed=seed, reward=reward, potential=str(potential), timesteps=timesteps, net_arch=net_arch, run_name=run_name
    )
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / f"qube_overnight_{run_name}.zip"

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw) as run:
        model.learn(
            total_timesteps=timesteps,
            progress_bar=False,
            callback=make_metrics_callback(enabled=mlflow_kw["enabled"]),
        )
        elapsed = time.time() - t0
        model.save(str(model_path))

        ep_infos = list(model.ep_info_buffer or [])
        ep_rewards = [ep["r"] for ep in ep_infos]
        ep_lengths = [ep["l"] for ep in ep_infos]

        # Evaluate on a CLEAN env (no shaping) so the metric reflects the true task.
        eval_env = make_sim_env(reward=reward)
        balance = evaluate_balance(model, eval_env, n_episodes=eval_episodes, control_freq=50)

        result = {
            "run_name": run_name,
            "seed": seed,
            "timesteps": timesteps,
            "elapsed_s": elapsed,
            "fps": timesteps / elapsed if elapsed > 0 else 0.0,
            "ep_rew_mean": float(np.mean(ep_rewards)) if ep_rewards else 0.0,
            "ep_len_mean": float(np.mean(ep_lengths)) if ep_lengths else 0.0,
            "reach_rate": balance["reach_rate"],
            "balance_rate": balance["balance_rate"],
            "upright_fraction": balance["upright_fraction"],
            "max_hold_s": balance["max_hold_s"],
            "max_hold_s_best": balance["max_hold_s_best"],
            "model_path": str(model_path),
        }
        if run:
            for key in ("fps", "ep_rew_mean", "ep_len_mean", "reach_rate", "balance_rate", "upright_fraction", "max_hold_s"):
                run.log_metric(f"final/{key}", float(result[key]))
            with contextlib.suppress(Exception):
                run.log_artifact(str(model_path))
    return result


def aggregate(per_seed: list[dict]) -> dict:
    keys = ("ep_rew_mean", "reach_rate", "balance_rate", "upright_fraction", "max_hold_s", "max_hold_s_best", "fps")
    agg: dict = {}
    for k in keys:
        vals = [r[k] for r in per_seed]
        agg[f"{k}_mean"] = float(np.mean(vals)) if vals else 0.0
        agg[f"{k}_std"] = float(np.std(vals)) if vals else 0.0
    return agg


def write_experiment_report(exp: dict, per_seed: list[dict], agg: dict, idx: int, n_total: int, elapsed_total: float) -> Path:
    path = REPORT_DIR / f"report_{exp['name']}.md"
    lines = [
        f"# Reporte de experimento — {exp['name']}",
        "",
        f"- **Fecha:** {_now()}",
        f"- **Recompensa:** `{exp['reward']}`  |  **PBRS:** `{exp['potential']}`",
        f"- **Semillas:** {[r['seed'] for r in per_seed]}  |  **Timesteps/semilla:** {per_seed[0]['timesteps'] if per_seed else '—'}",
        f"- **Progreso:** experimento {idx}/{n_total}  |  **Tiempo total transcurrido:** {timedelta(seconds=int(elapsed_total))}",
        "",
        "## Resultados por semilla",
        "",
        "| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in per_seed:
        lines.append(
            f"| {r['seed']} | {r['balance_rate'] * 100:.0f} | {r['reach_rate'] * 100:.0f} | "
            f"{r['upright_fraction'] * 100:.1f} | {r['max_hold_s']:.2f} | {r['max_hold_s_best']:.2f} | "
            f"{r['ep_rew_mean']:.2f} | {r['fps']:.0f} | {r['elapsed_s'] / 60:.1f} |"
        )
    lines += [
        "",
        "## Agregado (media ± std)",
        "",
        f"- **balance_rate:** {agg['balance_rate_mean'] * 100:.1f}% ± {agg['balance_rate_std'] * 100:.1f}%  "
        "(fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)",
        f"- **reach_rate:** {agg['reach_rate_mean'] * 100:.1f}% ± {agg['reach_rate_std'] * 100:.1f}%",
        f"- **upright_fraction:** {agg['upright_fraction_mean'] * 100:.1f}% ± {agg['upright_fraction_std'] * 100:.1f}%",
        f"- **hold máximo (mejor semilla):** {agg['max_hold_s_best_mean']:.2f} s",
        f"- **ep_rew_mean:** {agg['ep_rew_mean_mean']:.2f} ± {agg['ep_rew_mean_std']:.2f}",
        "",
        "## Análisis automático",
        "",
    ]
    br, rr = agg["balance_rate_mean"], agg["reach_rate_mean"]
    if br > 0.5:
        verdict = "✅ **Balance resuelto en la mayoría de episodios.** Esta config rompe el histórico 0% de balance."
    elif br > 0.1:
        verdict = "🟡 **Balance parcial.** Logra estabilizar en algunos episodios; aún inconsistente entre semillas."
    elif rr > 0.3:
        verdict = "⚠️ **Llega arriba pero no se queda.** El swing-up funciona; falta la transición a balance (más pasos / mejor reward / currículo)."
    else:
        verdict = "❌ **No resuelve el swing-up** con este presupuesto de pasos."
    lines.append(verdict)
    if agg["balance_rate_std"] > 0.2:
        lines.append("")
        lines.append("- Alta varianza entre semillas → el resultado depende mucho de la inicialización; se necesitan más semillas/pasos para concluir.")
    lines.append("")
    lines.append(f"> Modelos: `models/qube_overnight_{exp['name']}_s*.zip`  |  MLflow exp: `{MLFLOW_EXPERIMENT}`")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_final_report(all_results: list[dict], started: float, budget_hours: float, finished_early: bool) -> Path:
    path = REPORT_DIR / "FINAL_REPORT.md"
    elapsed = time.time() - started
    ranked = sorted(
        all_results,
        key=lambda a: (a["agg"]["balance_rate_mean"], a["agg"]["upright_fraction_mean"], a["agg"]["reach_rate_mean"]),
        reverse=True,
    )
    lines = [
        "# INFORME FINAL — Entrenamiento DRL nocturno (QUBE swing-up/balance)",
        "",
        f"- **Inicio:** {datetime.fromtimestamp(started):%Y-%m-%d %H:%M:%S}  |  **Fin:** {_now()}",
        f"- **Tiempo total:** {timedelta(seconds=int(elapsed))}  (presupuesto: {budget_hours} h)",
        f"- **Experimentos completados:** {len(all_results)}/{len(EXPERIMENTS)}"
        + ("  (presupuesto agotado antes de terminar todos)" if finished_early else ""),
        "",
        "Métrica de éxito = **balance_rate** (fracción de episodios que mantienen el péndulo "
        "invertido-y-lento ≥1 s). El histórico del proyecto era **0% de balance**; este es el número a batir.",
        "",
        "## Ranking de configuraciones (por balance, luego upright, luego reach)",
        "",
        "| # | Experimento | reward | PBRS | balance % | reach % | upright % | hold máx (s) | ep_rew |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, a in enumerate(ranked, 1):
        e, g = a["exp"], a["agg"]
        lines.append(
            f"| {i} | {e['name']} | `{e['reward']}` | `{e['potential']}` | "
            f"{g['balance_rate_mean'] * 100:.0f}±{g['balance_rate_std'] * 100:.0f} | "
            f"{g['reach_rate_mean'] * 100:.0f}±{g['reach_rate_std'] * 100:.0f} | "
            f"{g['upright_fraction_mean'] * 100:.1f} | {g['max_hold_s_best_mean']:.2f} | "
            f"{g['ep_rew_mean_mean']:.2f} |"
        )
    lines += ["", "## Conclusiones", ""]
    if ranked:
        best = ranked[0]
        bg = best["agg"]
        lines.append(f"- **Mejor configuración:** `{best['exp']['name']}` "
                     f"(reward=`{best['exp']['reward']}`, PBRS=`{best['exp']['potential']}`).")
        lines.append(f"  balance **{bg['balance_rate_mean'] * 100:.1f}%** ± {bg['balance_rate_std'] * 100:.1f}%, "
                     f"reach {bg['reach_rate_mean'] * 100:.0f}%, upright {bg['upright_fraction_mean'] * 100:.1f}%, "
                     f"hold máx {bg['max_hold_s_best_mean']:.2f} s.")
        if bg["balance_rate_mean"] > 0.1:
            lines.append("- ✅ **Los arreglos v1.44 (no terminar en la meta, TimeLimit, θ±120°, métrica correcta) "
                         "movieron el balance por encima de 0%.** Vale la pena escalar pasos/semillas en esta config.")
        elif max(a["agg"]["reach_rate_mean"] for a in ranked) > 0.3:
            lines.append("- ⚠️ **El swing-up funciona pero el balance sigue siendo el cuello de botella.** "
                         "Siguientes pasos sugeridos: más timesteps, currículo (resetear cerca del invertido), "
                         "warm-start desde el controlador energía+LQR, o RL residual sobre LQR.")
        else:
            lines.append("- ❌ **Con este presupuesto no se resolvió el swing-up.** Aumentar pasos y revisar exploración.")
    lines += [
        "",
        "## Cómo inspeccionar",
        "",
        "```bash",
        "uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # experimento: qube_overnight",
        "```",
        "",
        f"Reportes por experimento: `{REPORT_DIR.name}/report_*.md`. Modelos: `models/qube_overnight_*.zip`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Overnight DRL training + reporting for QUBE")
    parser.add_argument("--budget-hours", type=float, default=5.0, help="Wall-clock budget; stop starting new seeds after this")
    parser.add_argument("--timesteps", type=int, default=100_000, help="Timesteps per seed")
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2], help="Seeds per experiment")
    parser.add_argument("--net-arch", type=int, default=64, help="Hidden layer size (64 = ESP32-deployable)")
    parser.add_argument("--buffer-size", type=int, default=200_000, help="Replay buffer size")
    parser.add_argument("--eval-episodes", type=int, default=30, help="Episodes for balance evaluation")
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db", help="MLflow tracking URI")
    parser.add_argument("--smoke", action="store_true", help="Tiny run to validate the pipeline")
    args = parser.parse_args()

    if args.smoke:
        args.timesteps = 1200
        args.seeds = [0]
        args.eval_episodes = 5
        args.budget_hours = 0.2

    mlflow_kw = {"enabled": True, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}
    started = time.time()
    deadline = started + args.budget_hours * 3600
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"Overnight run start. budget={args.budget_hours}h timesteps/seed={args.timesteps} seeds={args.seeds} "
        f"net=[{args.net_arch}]x2 deadline={datetime.fromtimestamp(deadline):%H:%M:%S}")
    log(f"MLflow -> {args.mlflow_uri} (experiment: {MLFLOW_EXPERIMENT})")

    all_results: list[dict] = []
    finished_early = False

    for idx, exp in enumerate(EXPERIMENTS, 1):
        if time.time() >= deadline:
            log("Budget reached before starting next experiment; finalizing.")
            finished_early = True
            break
        log(f"=== Experiment {idx}/{len(EXPERIMENTS)}: {exp['name']} (reward={exp['reward']}, pbrs={exp['potential']}) ===")
        per_seed: list[dict] = []
        for seed in args.seeds:
            if time.time() >= deadline:
                log(f"Budget reached mid-experiment {exp['name']}; stopping seed loop.")
                finished_early = True
                break
            run_name = f"{exp['name']}_s{seed}"
            try:
                log(f"  training {run_name} ...")
                r = train_one_seed(
                    reward=exp["reward"],
                    potential=exp["potential"],
                    seed=seed,
                    timesteps=args.timesteps,
                    net_arch=args.net_arch,
                    buffer_size=args.buffer_size,
                    run_name=run_name,
                    mlflow_kw=mlflow_kw,
                    eval_episodes=args.eval_episodes,
                )
                per_seed.append(r)
                log(f"  done {run_name}: balance={r['balance_rate'] * 100:.0f}% reach={r['reach_rate'] * 100:.0f}% "
                    f"upright={r['upright_fraction'] * 100:.1f}% hold_max={r['max_hold_s_best']:.2f}s ({r['elapsed_s'] / 60:.1f} min)")
            except Exception as exc:  # overnight robustness: one failure must not kill the night
                log(f"  ERROR in {run_name}: {exc}\n{traceback.format_exc()}")

        if per_seed:
            agg = aggregate(per_seed)
            rpath = write_experiment_report(exp, per_seed, agg, idx, len(EXPERIMENTS), time.time() - started)
            all_results.append({"exp": exp, "per_seed": per_seed, "agg": agg})
            log(f"  report written: {rpath.name} | agg balance={agg['balance_rate_mean'] * 100:.1f}%")
            # Rewrite the final report after each experiment so a partial summary always exists.
            write_final_report(all_results, started, args.budget_hours, finished_early)
        if finished_early:
            break

    fpath = write_final_report(all_results, started, args.budget_hours, finished_early)
    log(f"ALL DONE. Final report: {fpath}")


if __name__ == "__main__":
    main()
