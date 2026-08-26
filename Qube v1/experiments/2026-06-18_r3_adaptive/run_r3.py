"""R3 DRL training: swing-up + balance with linear_alpha_stabilise reward.

Tests the gated-damping + Gaussian-hold-bonus reward that addresses both
failure modes seen in R1 (no balance incentive) and R2 (global velocity
penalty killed swing-up).

Network fixed at [64, 64] (ESP32 constraint).

Usage::

    .venv/Scripts/python.exe experiments/2026-06-18_r3_adaptive/run_r3.py \\
        --budget-hours 7 --timesteps 200000 --seeds 0 1 2
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

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
MLFLOW_EXPERIMENT = "qube_r3_adaptive"

# R3 experiment matrix -- ordered by expected informativeness.
EXPERIMENTS: list[dict] = [
    # Primary: gated damping + Gaussian hold bonus (200k)
    {"name": "01_stabilise_200k", "reward": "linear_alpha_stabilise", "potential": None, "timesteps": 200_000},
    # Longer run: same reward, 500k steps
    {"name": "02_stabilise_500k", "reward": "linear_alpha_stabilise", "potential": None, "timesteps": 500_000},
    # Control: linear_alpha baseline (200k, same as R2 config 2)
    {"name": "03_linear_control", "reward": "linear_alpha", "potential": None, "timesteps": 200_000},
    # R2 failure case for comparison
    {"name": "04_balance_r2fail", "reward": "linear_alpha_balance", "potential": None, "timesteps": 200_000},
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
        seed=seed, reward=reward, potential=str(potential), timesteps=timesteps,
        net_arch=net_arch, buffer_size=buffer_size, run_name=run_name,
    )
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / f"r3_{run_name}.zip"

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
            for key in ("fps", "ep_rew_mean", "ep_len_mean", "reach_rate", "balance_rate",
                        "upright_fraction", "max_hold_s"):
                run.log_metric(f"final/{key}", float(result[key]))
            with contextlib.suppress(Exception):
                run.log_artifact(str(model_path))
    return result


def aggregate(per_seed: list[dict]) -> dict:
    keys = ("ep_rew_mean", "reach_rate", "balance_rate", "upright_fraction",
            "max_hold_s", "max_hold_s_best", "fps")
    agg: dict = {}
    for k in keys:
        vals = [r[k] for r in per_seed]
        agg[f"{k}_mean"] = float(np.mean(vals)) if vals else 0.0
        agg[f"{k}_std"] = float(np.std(vals)) if vals else 0.0
    return agg


def write_experiment_report(
    exp: dict, per_seed: list[dict], agg: dict, idx: int, n_total: int,
    elapsed_total: float,
) -> Path:
    path = REPORT_DIR / f"report_{exp['name']}.md"
    lines = [
        f"# Reporte de experimento - {exp['name']}",
        "",
        f"- **Fecha:** {_now()}",
        f"- **Recompensa:** `{exp['reward']}`  |  **PBRS:** `{exp['potential']}`",
        f"- **Semillas:** {[r['seed'] for r in per_seed]}  |  **Timesteps/semilla:** {per_seed[0]['timesteps']:,}",
        f"- **Progreso:** experimento {idx}/{n_total}  |  **Tiempo total:** {str(timedelta(seconds=int(elapsed_total)))}",
        "",
        "## Resultados por semilla",
        "",
        "| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in per_seed:
        lines.append(
            f"| {r['seed']} | {r['balance_rate'] * 100:.0f} | {r['reach_rate'] * 100:.0f} "
            f"| {r['upright_fraction'] * 100:.1f} | {r['max_hold_s']:.2f} | {r['max_hold_s_best']:.2f} "
            f"| {r['ep_rew_mean']:.2f} | {r['fps']:.0f} | {r['elapsed_s'] / 60:.1f} |"
        )
    lines += [
        "",
        "## Agregado (media +/- std)",
        "",
        f"- **balance_rate:** {agg['balance_rate_mean'] * 100:.1f}% +/- {agg['balance_rate_std'] * 100:.1f}%",
        f"- **reach_rate:** {agg['reach_rate_mean'] * 100:.1f}% +/- {agg['reach_rate_std'] * 100:.1f}%",
        f"- **upright_fraction:** {agg['upright_fraction_mean'] * 100:.1f}% +/- {agg['upright_fraction_std'] * 100:.1f}%",
        f"- **hold max (mejor semilla):** {agg['max_hold_s_best_mean']:.2f} s",
        f"- **ep_rew_mean:** {agg['ep_rew_mean_mean']:.2f} +/- {agg['ep_rew_mean_std']:.2f}",
        "",
        "## Analisis automatico",
        "",
    ]
    if agg["balance_rate_mean"] > 0:
        lines.append(f"**Balance logrado:** {agg['balance_rate_mean'] * 100:.1f}% de episodios balancean >=1s.")
    elif agg["max_hold_s_best_mean"] >= 0.5:
        lines.append(f"**Cerca del balance.** Hold max {agg['max_hold_s_best_mean']:.2f}s.")
    elif agg["reach_rate_mean"] >= 0.5:
        lines.append("**Llega arriba pero no se queda.** Swing-up funciona; falta transicion a balance.")
    else:
        lines.append("**No resuelve el swing-up.**")
    lines.append(
        f"\n> Modelos: `experiments/2026-06-18_r3_adaptive/models/r3_{exp['name']}_s*.zip`  |  MLflow: `qube_r3_adaptive`"
    )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_final_report(
    all_results: list[dict], started: float, budget_hours: float, finished_early: bool,
) -> Path:
    path = REPORT_DIR / "FINAL_REPORT.md"
    elapsed = time.time() - started
    n_done = len(all_results)

    lines = [
        "# INFORME FINAL - R3 Entrenamiento DRL (QUBE swing-up/balance)",
        "",
        f"- **Inicio:** {datetime.fromtimestamp(started):%Y-%m-%d %H:%M:%S}  |  **Fin:** {_now()}",
        f"- **Tiempo total:** {str(timedelta(seconds=int(elapsed)))}  (presupuesto: {budget_hours:.1f} h)",
        f"- **Experimentos completados:** {n_done}/{len(EXPERIMENTS)}  {'(presupuesto agotado)' if finished_early else ''}",
        "",
        "Metrica de exito = **balance_rate** (>=1s hold).",
        "Benchmark R1: 0% balance. R2: 0% balance (velocity penalty killed swing-up).",
        "",
        "## Ranking (por balance, luego upright, luego reach)",
        "",
        "| # | Experimento | reward | timesteps | balance % | reach % | upright % | hold max (s) | ep_rew |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, res in enumerate(all_results, 1):
        a = res["agg"]
        ts = res["per_seed"][0]["timesteps"] if res["per_seed"] else 0
        lines.append(
            f"| {i} | {res['exp']['name']} | `{res['exp']['reward']}` | {ts:,} "
            f"| {a['balance_rate_mean'] * 100:.1f}+/-{a['balance_rate_std'] * 100:.1f} "
            f"| {a['reach_rate_mean'] * 100:.0f}+/-{a['reach_rate_std'] * 100:.0f} "
            f"| {a['upright_fraction_mean'] * 100:.1f} "
            f"| {a['max_hold_s_best_mean']:.2f} "
            f"| {a['ep_rew_mean_mean']:.2f} |"
        )

    lines += ["", "## Conclusiones", ""]
    if all_results:
        best = max(all_results, key=lambda r: r["agg"]["balance_rate_mean"])
        ba = best["agg"]
        lines.append(
            f"- **Mejor:** `{best['exp']['name']}` ({best['exp']['reward']}). "
            f"balance **{ba['balance_rate_mean'] * 100:.1f}%**, "
            f"reach {ba['reach_rate_mean'] * 100:.0f}%, "
            f"upright {ba['upright_fraction_mean'] * 100:.1f}%, "
            f"hold max {ba['max_hold_s_best_mean']:.2f}s."
        )
        if ba["balance_rate_mean"] > 0:
            lines.append("- **Balance logrado.** Proceder a deploy en hardware real.")
        elif ba["max_hold_s_best_mean"] >= 1.0:
            lines.append("- **Hold >=1s alcanzado pero inconsistente.** Mas steps o fine-tuning.")
        elif ba["reach_rate_mean"] >= 0.8:
            lines.append("- **Swing-up OK, balance pendiente.** Probar curriculo (fine-tune desde este modelo).")
        else:
            lines.append("- **Swing-up degradado.** Revisar penalizacion de velocidad.")
    lines += [
        "", "## Inspeccion", "",
        "```bash",
        "uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r3_adaptive",
        "```",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="R3 DRL training for QUBE balance")
    parser.add_argument("--budget-hours", type=float, default=7.0)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--net-arch", type=int, default=64)
    parser.add_argument("--buffer-size", type=int, default=500_000)
    parser.add_argument("--eval-episodes", type=int, default=30)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    parser.add_argument("--gamma", type=float, default=0.995)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    if args.smoke:
        args.seeds = [0]
        args.eval_episodes = 5
        args.budget_hours = 0.3

    mlflow_kw = {"enabled": True, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}
    started = time.time()
    deadline = started + args.budget_hours * 3600
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    total_steps = sum(e["timesteps"] * len(args.seeds) for e in EXPERIMENTS)
    log(f"R3 start. budget={args.budget_hours}h seeds={args.seeds} "
        f"net=[{args.net_arch}]x2 buffer={args.buffer_size:,} gamma={args.gamma} "
        f"total_steps={total_steps:,} deadline={datetime.fromtimestamp(deadline):%H:%M:%S}")

    all_results: list[dict] = []
    finished_early = False

    for idx, exp in enumerate(EXPERIMENTS, 1):
        if time.time() >= deadline:
            log("Budget reached; finalizing.")
            finished_early = True
            break
        ts = exp["timesteps"]
        if args.smoke:
            ts = 1200
        log(f"=== {idx}/{len(EXPERIMENTS)}: {exp['name']} "
            f"(reward={exp['reward']}, steps={ts:,}, pbrs={exp['potential']}) ===")
        per_seed: list[dict] = []
        for seed in args.seeds:
            if time.time() >= deadline:
                log(f"  Budget mid-experiment; stopping.")
                finished_early = True
                break
            run_name = f"{exp['name']}_s{seed}"
            try:
                log(f"  training {run_name} ...")
                r = train_one_seed(
                    reward=exp["reward"], potential=exp["potential"], seed=seed,
                    timesteps=ts, net_arch=args.net_arch, buffer_size=args.buffer_size,
                    run_name=run_name, mlflow_kw=mlflow_kw, eval_episodes=args.eval_episodes,
                )
                per_seed.append(r)
                log(f"  done {run_name}: balance={r['balance_rate'] * 100:.0f}% "
                    f"reach={r['reach_rate'] * 100:.0f}% "
                    f"upright={r['upright_fraction'] * 100:.1f}% "
                    f"hold_max={r['max_hold_s_best']:.2f}s ({r['elapsed_s'] / 60:.1f}m)")
            except Exception as exc:
                log(f"  ERROR {run_name}: {exc}\n{traceback.format_exc()}")

        if per_seed:
            agg = aggregate(per_seed)
            write_experiment_report(exp, per_seed, agg, idx, len(EXPERIMENTS), time.time() - started)
            all_results.append({"exp": exp, "per_seed": per_seed, "agg": agg})
            write_final_report(all_results, started, args.budget_hours, finished_early)
            log(f"  agg: balance={agg['balance_rate_mean'] * 100:.1f}% reach={agg['reach_rate_mean'] * 100:.0f}%")
        if finished_early:
            break

    fpath = write_final_report(all_results, started, args.budget_hours, finished_early)
    log(f"ALL DONE. {fpath}")


if __name__ == "__main__":
    main()
