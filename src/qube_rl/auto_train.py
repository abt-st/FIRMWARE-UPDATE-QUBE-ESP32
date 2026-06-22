"""Autonomous training loop with self-supervision.

Trains SAC, analyzes results, adjusts parameters if needed, and retries.
Writes progress to training_progress.md for the user to review.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.config import set_global_seeds
from qube_rl.envs.factory import make_sim_env


def make_env(reward: str = "cos_alpha", potential: str | None = None) -> object:
    """Build the bounded training environment (delegates to the env factory).

    Uses the standard bounded layout (8-D obs, theta ±120°, alpha non-terminating
    + TimeLimit) so the reported episode metrics are meaningful and match the
    deployment observation contract.
    """
    return make_sim_env(reward=reward, potential=potential)


def train_and_evaluate(
    timesteps: int = 50_000,
    reward: str = "cos_alpha",
    lr: float = 3e-4,
    net_size: int = 256,
    run_name: str = "auto",
    seed: int | None = None,
    mlflow_kw: dict | None = None,
) -> dict:
    """Train SAC for one seed and return episode + balance metrics.

    When ``mlflow_kw`` enables tracking, each seed is logged as its own MLflow
    run: hyperparameters, SB3 training curves (via the metrics callback), the
    final balance metrics and the saved model artifact.
    """
    from qube_rl.metrics import evaluate_balance
    from qube_rl.mlflow_tracking import build_params, make_metrics_callback, mlflow_run

    mlflow_kw = mlflow_kw or {"enabled": False, "uri": None, "experiment": "qube_sac_auto"}

    set_global_seeds(seed)
    vec_env = DummyVecEnv([lambda: make_env(reward)])
    if seed is not None:
        vec_env.seed(seed)

    model = SAC(
        "MlpPolicy",
        vec_env,
        learning_rate=lr,
        buffer_size=100_000,
        batch_size=256,
        tau=0.005,
        gamma=0.99,
        use_sde=True,
        use_sde_at_warmup=True,
        train_freq=1,
        gradient_steps=1,
        learning_starts=1000,
        seed=seed,
        verbose=0,
        policy_kwargs=dict(net_arch=dict(pi=[net_size, net_size], qf=[net_size, net_size])),
    )

    params = build_params(seed=seed, reward=reward, timesteps=timesteps, net_size=net_size, lr=lr, run_name=run_name)
    save_dir = Path("models")
    save_dir.mkdir(exist_ok=True)
    model_path = save_dir / f"qube_sac_{run_name}.zip"

    t0 = time.time()
    with mlflow_run(run_name, params, **mlflow_kw) as run:
        # The metrics callback logs SB3's scalars (losses, ep_rew_mean, …) into
        # the active per-seed run while training.
        model.learn(
            total_timesteps=timesteps,
            progress_bar=False,
            callback=make_metrics_callback(enabled=mlflow_kw["enabled"]),
        )
        elapsed = time.time() - t0

        # Save model (seed-suffixed so multi-seed runs do not overwrite each other)
        model.save(str(model_path))

        # Episode metrics from SB3's rolling buffer (recent ~100 episodes).
        ep_infos = list(model.ep_info_buffer or [])
        ep_lengths = [ep["l"] for ep in ep_infos]
        ep_rewards = [ep["r"] for ep in ep_infos]

        # Balance-aware evaluation (the real success signal, not just ep length).
        balance = evaluate_balance(model, make_env(reward), n_episodes=10, control_freq=50)

        result = {
            "run_name": run_name,
            "timesteps": timesteps,
            "seed": seed,
            "elapsed_s": elapsed,
            "fps": timesteps / elapsed if elapsed > 0 else 0,
            "model_path": str(model_path),
            "episodes": len(ep_lengths),
            "ep_len_mean": float(np.mean(ep_lengths)) if ep_lengths else 0,
            "ep_len_max": float(np.max(ep_lengths)) if ep_lengths else 0,
            "ep_rew_mean": float(np.mean(ep_rewards)) if ep_rewards else 0,
            "ep_rew_max": float(np.max(ep_rewards)) if ep_rewards else 0,
            "reach_rate": balance["reach_rate"],
            "balance_rate": balance["balance_rate"],
            "upright_fraction": balance["upright_fraction"],
            "max_hold_s": balance["max_hold_s"],
        }

        if run:
            for key in ("fps", "ep_len_mean", "ep_rew_mean", "reach_rate", "balance_rate", "upright_fraction", "max_hold_s"):
                run.log_metric(f"final/{key}", float(result[key]))
            run.log_artifact(str(model_path))

    return result


def evaluate_over_seeds(
    seeds: list[int | None],
    *,
    timesteps: int,
    reward: str,
    run_name: str,
    lr: float = 3e-4,
    net_size: int = 256,
    mlflow_kw: dict | None = None,
) -> dict:
    """Run ``train_and_evaluate`` once per seed and aggregate mean ± std.

    Single-seed comparisons are not statistically meaningful for SAC (high
    inter-seed variance), so the autonomous loop now reports the spread across
    seeds.  Pass ``--seeds 0 1 2 3 4`` (>=5 recommended) for a real comparison.
    """
    per_seed = [
        train_and_evaluate(
            timesteps=timesteps,
            reward=reward,
            lr=lr,
            net_size=net_size,
            run_name=f"{run_name}_s{seed}",
            seed=seed,
            mlflow_kw=mlflow_kw,
        )
        for seed in seeds
    ]
    agg: dict = {"run_name": run_name, "timesteps": timesteps, "n_seeds": len(seeds), "per_seed": per_seed}
    for key in ("ep_len_mean", "ep_rew_mean", "reach_rate", "balance_rate", "upright_fraction", "max_hold_s", "fps"):
        vals = [r[key] for r in per_seed]
        agg[f"{key}_mean"] = float(np.mean(vals))
        agg[f"{key}_std"] = float(np.std(vals))
    return agg


def log_run_to_mlflow(result: dict, *, enabled: bool, uri: str | None, experiment: str) -> None:
    """Log one aggregated run's params and mean/std metrics to MLflow (no-op if disabled)."""
    from qube_rl.mlflow_tracking import mlflow_run

    params = {
        "run_name": result["run_name"],
        "timesteps": result["timesteps"],
        "n_seeds": result.get("n_seeds", 1),
    }
    with mlflow_run(result["run_name"], params, enabled=enabled, uri=uri, experiment=experiment) as run:
        if run:
            for key, value in result.items():
                if key.endswith(("_mean", "_std")) and isinstance(value, (int, float)):
                    run.log_metric(key, float(value))


def write_progress(results: list[dict], status: str, out_dir: Path) -> None:
    """Write training progress (mean ± std across seeds) to a markdown file."""
    lines = [
        "# Training Progress — Autonomous Loop",
        f"**Status:** {status}",
        f"**Last update:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "Metrics are **mean ± std across seeds** (single-seed numbers are not "
        "statistically meaningful for SAC). `balance_rate` = fraction of episodes "
        "that held the pendulum inverted-and-slow for ≥1 s — the real success signal.",
        "",
        "## Runs",
        "",
        "| Run | Steps | Seeds | Reach % | Balance % | Upright % | Hold (s) | Ep Rew |",
        "|-----|-------|-------|---------|-----------|-----------|----------|--------|",
    ]
    for r in results:
        lines.append(
            f"| {r['run_name']} | {r['timesteps']} | {r.get('n_seeds', 1)} | "
            f"{r['reach_rate_mean'] * 100:.0f}±{r['reach_rate_std'] * 100:.0f} | "
            f"{r['balance_rate_mean'] * 100:.0f}±{r['balance_rate_std'] * 100:.0f} | "
            f"{r['upright_fraction_mean'] * 100:.0f}±{r['upright_fraction_std'] * 100:.0f} | "
            f"{r['max_hold_s_mean']:.2f}±{r['max_hold_s_std']:.2f} | "
            f"{r['ep_rew_mean_mean']:.2f}±{r['ep_rew_mean_std']:.2f} |"
        )

    if results:
        last = results[-1]
        lines.extend(
            [
                "",
                "## Analysis (last run)",
                "",
                f"- **Balance rate:** {last['balance_rate_mean'] * 100:.0f}% "
                f"± {last['balance_rate_std'] * 100:.0f}% (held ≥1 s inverted)",
                f"- **Reach rate:** {last['reach_rate_mean'] * 100:.0f}% "
                f"± {last['reach_rate_std'] * 100:.0f}%",
                f"- **Mean upright time fraction:** {last['upright_fraction_mean'] * 100:.0f}%",
                "",
            ]
        )
        if last["balance_rate_mean"] > 0.5:
            lines.append("✅ **Majority of episodes balance — strong policy.**")
        elif last["reach_rate_mean"] > 0.3:
            lines.append("⚠️ **Reaches the top but rarely holds — needs better balance / longer training.**")
        else:
            lines.append("❌ **Rarely reaches the top — swing-up not solved yet.**")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "training_progress.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    import argparse
    import contextlib
    import sys

    # Windows consoles default to cp1252, which crashes on the non-ASCII chars in
    # the progress prints (em dash, arrows). Emit UTF-8 instead of raising.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(Exception):
            stream.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Autonomous SAC training loop for QUBE")
    parser.add_argument(
        "--seeds",
        type=int,
        nargs="+",
        default=[0],
        help="Random seeds to average over (>=5 recommended for a real comparison, e.g. --seeds 0 1 2 3 4)",
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for progress report (default: experiments/<today>_training)",
    )
    parser.add_argument("--steps", type=int, default=50_000, help="Timesteps for runs 1 & 2 (baseline / reward sweep)")
    parser.add_argument("--long-steps", type=int, default=100_000, help="Timesteps for run 3 (best config, longer)")
    parser.add_argument("--mlflow", action="store_true", help="Log each run's metrics to MLflow")
    parser.add_argument(
        "--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite:///mlflow.db or env var)"
    )
    parser.add_argument("--mlflow-experiment", default="qube_sac_auto", help="MLflow experiment name")
    args = parser.parse_args()

    seeds: list[int | None] = list(args.seeds)
    out_dir = Path(args.out_dir) if args.out_dir else Path("experiments") / f"{datetime.now():%Y-%m-%d}_training"
    mlflow_kw = {"enabled": args.mlflow, "uri": args.mlflow_uri, "experiment": args.mlflow_experiment}
    if args.mlflow:
        from qube_rl.mlflow_tracking import resolve_tracking_uri

        print(f"[mlflow] tracking enabled -> {resolve_tracking_uri(args.mlflow_uri)} (experiment: {args.mlflow_experiment})")
    results = []

    def announce(title: str) -> None:
        print("=" * 60)
        print(title)
        print("=" * 60)

    announce(f"RUN 1: Baseline — {args.steps} steps, cos_alpha, net=256, seeds={seeds}")
    r1 = evaluate_over_seeds(seeds, timesteps=args.steps, reward="cos_alpha", run_name="run1_baseline", mlflow_kw=mlflow_kw)
    results.append(r1)
    log_run_to_mlflow(r1, **mlflow_kw)
    write_progress(results, f"Run 1 done — balance={r1['balance_rate_mean'] * 100:.0f}%", out_dir)

    announce(f"RUN 2: linear_alpha reward — {args.steps} steps, seeds={seeds}")
    r2 = evaluate_over_seeds(
        seeds, timesteps=args.steps, reward="linear_alpha", run_name="run2_linear_alpha", mlflow_kw=mlflow_kw
    )
    results.append(r2)
    log_run_to_mlflow(r2, **mlflow_kw)
    write_progress(results, f"Run 2 done — balance={r2['balance_rate_mean'] * 100:.0f}%", out_dir)

    # Pick the better reward by BALANCE rate (the real objective), not ep length.
    best_reward = "linear_alpha" if r2["balance_rate_mean"] >= r1["balance_rate_mean"] else "cos_alpha"
    announce(f"RUN 3: Best ({best_reward}) — {args.long_steps} steps, seeds={seeds}")
    r3 = evaluate_over_seeds(
        seeds, timesteps=args.long_steps, reward=best_reward, run_name="run3_best_long", mlflow_kw=mlflow_kw
    )
    results.append(r3)
    log_run_to_mlflow(r3, **mlflow_kw)
    write_progress(results, f"Run 3 done — balance={r3['balance_rate_mean'] * 100:.0f}%", out_dir)

    # Final summary
    write_progress(results, "All runs complete", out_dir)
    print("\n" + "=" * 60)
    print(f"TRAINING COMPLETE — see {out_dir / 'training_progress.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
