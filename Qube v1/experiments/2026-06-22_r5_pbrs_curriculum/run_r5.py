"""R5 DRL training: apex-gated stabilise reward + energy PBRS + annealed curriculum.

Builds on the R3/R4 verdict (see docs/research/METODOS_ALTERNATIVOS_RL_BALANCE.md):
- ``linear_alpha`` solves swing-up (100 % reach) but never holds >=1 s (balance 0 %);
  the reverse curriculum (``near_upright_prob=0.4``) was the breakthrough lever
  (R3 config 03: upright 30.4 %, hold 0.92 s, 0.08 s short of the 1 s threshold).
- Velocity penalties over a wide gate (R2 ``linear_alpha_balance``, R3
  ``linear_alpha_stabilise`` gated at ``|alpha|>pi/2``) **kill the swing-up**.

R5 tests two orthogonal, low-risk levers and an ablation:

1. **Apex-gated stabilise reward** (``linear_alpha_apex_stabilise``): the velocity
   damping is gated to within ~30 deg of the apex (not pi/2), where a successful
   swing-up only spends an instant — so it makes slow balance the optimum without
   starving the energy pump. Kept the continuous Gaussian hold bonus.
2. **Energy PBRS** (``potential="energy"``): policy-invariant shaping (Ng 1999)
   onto the goal energy manifold (EBERL/Astrom). Cannot break swing-up by design.
3. **Annealed reverse curriculum**: ``near_upright_prob`` decays from ``p_start``
   to ``p_end`` over ``anneal_frac`` of training (Florensa CoRL'17 reverse
   curriculum), giving dense balance practice early then re-teaching the full task.

Network fixed at [64, 64] (ESP32). gamma=0.995, threaded into both the agent and
the PBRS wrapper (required for the policy-invariance guarantee).

Usage::

    .venv/Scripts/python.exe experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py \\
        --budget-hours 10 --timesteps 500000 --seeds 0 1 2

    # quick local smoke test (no MLflow, tiny buffer/steps):
    .venv/Scripts/python.exe experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py \\
        --timesteps 600 --seeds 0 --buffer-size 8000 --eval-episodes 2 \\
        --budget-hours 0.3 --no-mlflow
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
REPO_ROOT = REPORT_DIR.parent.parent
MLFLOW_EXPERIMENT = "qube_r5_pbrs_curriculum"

# R5 experiment matrix. Order puts the main bet (apex reward + annealed curriculum)
# first so its 3 seeds finish before budget bites.
EXPERIMENTS: list[dict] = [
    # Main bet: apex-tight stabilise reward + curriculum annealed 0.6 -> 0.2.
    {"name": "01_apex_anneal", "reward": "linear_alpha_apex_stabilise",
     "potential": None, "energy_weight": 0.0, "p_start": 0.6, "p_end": 0.2},
    # Recommendation A in isolation: linear_alpha + energy PBRS + same curriculum.
    {"name": "02_pbrs_energy_anneal", "reward": "linear_alpha",
     "potential": "energy", "energy_weight": 1.0, "p_start": 0.6, "p_end": 0.2},
    # Ablation: apex reward with the proven *static* 0.4 curriculum (no anneal),
    # to isolate the contribution of annealing vs the reward change.
    {"name": "03_apex_static", "reward": "linear_alpha_apex_stabilise",
     "potential": None, "energy_weight": 0.0, "p_start": 0.4, "p_end": 0.4},
]

ANNEAL_FRAC = 0.7  # fraction of training over which near_upright_prob decays


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def make_curriculum_callback(total_timesteps: int, p_start: float, p_end: float):
    """SB3 callback that anneals ``near_upright_prob`` on the training env(s).

    Returns ``None`` if SB3 is unavailable (training would have failed earlier).
    """
    try:
        from stable_baselines3.common.callbacks import BaseCallback
    except ImportError:
        return None

    class CurriculumAnneal(BaseCallback):
        """Linearly decay near_upright_prob from p_start to p_end over ANNEAL_FRAC."""

        def __init__(self, total: int, ps: float, pe: float, set_every: int = 2000) -> None:
            super().__init__()
            self.total = max(1, int(total))
            self.ps = float(ps)
            self.pe = float(pe)
            self.set_every = int(set_every)

        def _set_prob(self, p: float) -> None:
            # DummyVecEnv exposes .envs; reach the inner QubeSimEnv via .unwrapped
            # (gym.Wrapper does not forward attribute *writes* to the base env).
            for e in self.training_env.envs:
                e.unwrapped.near_upright_prob = float(p)

        def _on_training_start(self) -> None:
            self._set_prob(self.ps)

        def _on_step(self) -> bool:
            if self.n_calls % self.set_every == 0:
                frac = min(1.0, self.num_timesteps / (ANNEAL_FRAC * self.total))
                self._set_prob(self.ps + frac * (self.pe - self.ps))
            return True

    return CurriculumAnneal(total_timesteps, p_start, p_end)


def train_one_seed(
    *,
    reward: str,
    potential: str | None,
    energy_weight: float,
    p_start: float,
    p_end: float,
    seed: int,
    timesteps: int,
    net_arch: int,
    buffer_size: int,
    gamma: float,
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

    def _make():
        return make_sim_env(
            reward=reward,
            potential=potential,
            potential_gamma=gamma,  # MUST match the agent gamma for PBRS invariance
            potential_energy_weight=energy_weight,
            near_upright_prob=p_start,
        )

    train_env = DummyVecEnv([_make])
    train_env.seed(seed)

    model = SAC(
        "MlpPolicy",
        train_env,
        learning_rate=cfg.learning_rate,
        buffer_size=buffer_size,
        batch_size=cfg.batch_size,
        tau=cfg.tau,
        gamma=gamma,
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
    params["near_upright_prob_start"] = p_start
    params["near_upright_prob_end"] = p_end
    params["anneal_frac"] = ANNEAL_FRAC
    params["energy_weight"] = energy_weight
    params["gamma"] = gamma

    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)
    model_path = models_dir / f"r5_{run_name}.zip"

    callbacks = []
    cb_curr = make_curriculum_callback(timesteps, p_start, p_end)
    if cb_curr is not None:
        callbacks.append(cb_curr)
    cb_metrics = make_metrics_callback(enabled=mlflow_kw["enabled"])
    if cb_metrics is not None:
        callbacks.append(cb_metrics)

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw) as run:
        model.learn(
            total_timesteps=timesteps,
            progress_bar=False,
            callback=callbacks or None,
        )
        elapsed = time.time() - t0
        model.save(str(model_path))

        ep_infos = list(model.ep_info_buffer or [])
        ep_rewards = [ep["r"] for ep in ep_infos]
        ep_lengths = [ep["l"] for ep in ep_infos]

        # Evaluate on a CLEAN env (base reward, no PBRS, HANGING reset — the true
        # task) so the metric is comparable to R1-R4 regardless of the curriculum
        # or shaping used during training.
        eval_reward = "linear_alpha" if potential else reward
        eval_env = make_sim_env(reward=eval_reward)
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
        f"- **Recompensa:** `{exp['reward']}`  |  **PBRS:** `{exp['potential']}`  "
        f"|  **energy_weight:** {exp['energy_weight']}  "
        f"|  **near_upright_prob:** {exp['p_start']} -> {exp['p_end']} (anneal {ANNEAL_FRAC})",
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
    elif agg["max_hold_s_best_mean"] >= 0.8:
        lines.append(f"**Muy cerca del balance.** Hold max {agg['max_hold_s_best_mean']:.2f}s - subir steps o tunear bono/gate.")
    elif agg["reach_rate_mean"] >= 0.5:
        lines.append("**Llega arriba pero no se queda.** Swing-up funciona; falta la transicion a balance.")
    else:
        lines.append("**No resuelve el swing-up** con este presupuesto de pasos (revisar gate/damping).")
    lines += [
        "",
        f"> Modelos: `{REPORT_DIR.name}/models/r5_{exp['name']}_s*.zip`  |  MLflow exp: `{MLFLOW_EXPERIMENT}`",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_final_report(
    all_results: list[dict], started: float, budget_hours: float, finished_early: bool,
) -> Path:
    path = REPORT_DIR / "FINAL_REPORT.md"
    elapsed = time.time() - started
    n_done = len(all_results)

    lines = [
        "# INFORME FINAL - R5 DRL (apex-gated reward + energy PBRS + currículo recocido)",
        "",
        f"- **Inicio:** {datetime.fromtimestamp(started):%Y-%m-%d %H:%M:%S}  |  **Fin:** {_now()}",
        f"- **Tiempo total:** {str(timedelta(seconds=int(elapsed)))}  (presupuesto: {budget_hours:.1f} h)",
        f"- **Experimentos completados:** {n_done}/{len(EXPERIMENTS)}  "
        f"{'(presupuesto agotado)' if finished_early else ''}",
        "",
        "Metrica de exito = **balance_rate** (pendulo invertido <=12 deg y lento "
        "<=1 rad/s durante >=1 s continuo). Benchmark R1-R4: **0 %** (mejor hold 0.92 s).",
        "",
        "## Hipotesis R5",
        "",
        "- **Apex-gated reward:** damping gateado a ~30 deg del apice (no pi/2) -> "
        "hace del balance lento el optimo sin matar el swing-up.",
        "- **Energy PBRS:** shaping policy-invariante hacia la variedad de energia "
        "del objetivo (EBERL/Astrom); no puede romper el swing-up por diseno.",
        "- **Currículo recocido:** near_upright_prob 0.6 -> 0.2 (Florensa CoRL'17).",
        "",
        "## Ranking de configuraciones (por balance, luego hold, luego upright)",
        "",
        "| # | Experimento | reward | PBRS | currículo | balance % | reach % | upright % | hold max (s) | ep_rew |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    ranked = sorted(
        all_results,
        key=lambda r: (r["agg"]["balance_rate_mean"], r["agg"]["max_hold_s_best_mean"],
                       r["agg"]["upright_fraction_mean"]),
        reverse=True,
    )
    for i, res in enumerate(ranked, 1):
        a, e = res["agg"], res["exp"]
        curr = f"{e['p_start']}->{e['p_end']}"
        lines.append(
            f"| {i} | {e['name']} | `{e['reward']}` | {e['potential']} | {curr} "
            f"| {a['balance_rate_mean'] * 100:.1f}+/-{a['balance_rate_std'] * 100:.1f} "
            f"| {a['reach_rate_mean'] * 100:.0f} | {a['upright_fraction_mean'] * 100:.1f} "
            f"| {a['max_hold_s_best_mean']:.2f} | {a['ep_rew_mean_mean']:.2f} |"
        )

    lines += ["", "## Conclusiones", ""]
    if ranked:
        best = ranked[0]
        ba = best["agg"]
        lines.append(
            f"- **Mejor configuracion:** `{best['exp']['name']}` (reward=`{best['exp']['reward']}`, "
            f"PBRS={best['exp']['potential']}). balance **{ba['balance_rate_mean'] * 100:.1f}%**, "
            f"reach {ba['reach_rate_mean'] * 100:.0f}%, upright {ba['upright_fraction_mean'] * 100:.1f}%, "
            f"hold max {ba['max_hold_s_best_mean']:.2f} s."
        )
        if ba["balance_rate_mean"] >= 0.10:
            lines.append("- **Objetivo alcanzado** (balance >=10 %). Siguiente: 1M steps multi-seed -> export ESP32 + A/B vs hibrido LQR.")
        elif ba["balance_rate_mean"] > 0:
            lines.append("- **Balance roto por primera vez (>0 %).** Subir a 1M pasos o ensanchar levemente el gate/bono.")
        else:
            lines.append("- **Balance sigue en 0%.** Ver arbol de decision en docs/research/METODOS_ALTERNATIVOS_RL_BALANCE.md (fallback hibrido LQR).")
    lines += [
        "",
        "## Como inspeccionar",
        "",
        "```bash",
        f"uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: {MLFLOW_EXPERIMENT}",
        "```",
        "",
        f"Reportes por experimento: `{REPORT_DIR.name}/report_*.md`.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="R5 DRL training (apex reward + energy PBRS + annealed curriculum)")
    parser.add_argument("--budget-hours", type=float, default=10.0)
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    parser.add_argument("--net-arch", type=int, default=64)
    parser.add_argument("--buffer-size", type=int, default=500_000)
    parser.add_argument("--gamma", type=float, default=0.995)
    parser.add_argument("--eval-episodes", type=int, default=30)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    parser.add_argument("--no-mlflow", action="store_true", help="disable MLflow (clean local smoke test)")
    args = parser.parse_args()

    mlflow_kw = {"enabled": not args.no_mlflow, "uri": args.mlflow_uri, "experiment": MLFLOW_EXPERIMENT}
    started = time.time()
    deadline = started + args.budget_hours * 3600
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"R5 run start. budget={args.budget_hours}h timesteps/seed={args.timesteps:,} "
        f"seeds={args.seeds} net=[{args.net_arch}]x2 buffer={args.buffer_size:,} "
        f"gamma={args.gamma} mlflow={'off' if args.no_mlflow else 'on'} "
        f"deadline={datetime.fromtimestamp(deadline):%H:%M:%S}")

    all_results: list[dict] = []
    finished_early = False

    for idx, exp in enumerate(EXPERIMENTS, 1):
        if time.time() >= deadline:
            log("Budget reached before starting next experiment; finalizing.")
            finished_early = True
            break
        log(f"=== Experiment {idx}/{len(EXPERIMENTS)}: {exp['name']} "
            f"(reward={exp['reward']}, pbrs={exp['potential']}, "
            f"curriculum={exp['p_start']}->{exp['p_end']}) ===")
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
                    energy_weight=exp["energy_weight"],
                    p_start=exp["p_start"],
                    p_end=exp["p_end"],
                    seed=seed,
                    timesteps=args.timesteps,
                    net_arch=args.net_arch,
                    buffer_size=args.buffer_size,
                    gamma=args.gamma,
                    run_name=run_name,
                    mlflow_kw=mlflow_kw,
                    eval_episodes=args.eval_episodes,
                )
                per_seed.append(r)
                log(f"  done {run_name}: balance={r['balance_rate'] * 100:.0f}% "
                    f"reach={r['reach_rate'] * 100:.0f}% upright={r['upright_fraction'] * 100:.1f}% "
                    f"hold_max={r['max_hold_s_best']:.2f}s ({r['elapsed_s'] / 60:.1f} min)")
            except Exception as exc:
                log(f"  ERROR in {run_name}: {exc}\n{traceback.format_exc()}")

        if per_seed:
            agg = aggregate(per_seed)
            rpath = write_experiment_report(exp, per_seed, agg, idx, len(EXPERIMENTS),
                                            time.time() - started)
            all_results.append({"exp": exp, "per_seed": per_seed, "agg": agg})
            log(f"  report written: {rpath.name} | agg balance={agg['balance_rate_mean'] * 100:.1f}%")
            write_final_report(all_results, started, args.budget_hours, finished_early)
        if finished_early:
            break

    fpath = write_final_report(all_results, started, args.budget_hours, finished_early)
    log(f"ALL DONE. Final report: {fpath}")


if __name__ == "__main__":
    main()
