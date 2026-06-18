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
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.config import WrapperConfig, set_global_seeds
from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper


def make_env(reward: str = "cos_alpha", vel_clamp: float = 50.0) -> object:
    """Build environment with Monitor for episode metrics."""
    wrap_cfg = WrapperConfig()
    env = QubeSimEnv(
        control_freq=50,
        reward=reward,
        angle_limits=[np.inf, np.inf],
        speed_limits=[vel_clamp, vel_clamp],
        encoders_cprs=None,
        velocity_filter_order=2,
    )
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=wrap_cfg.deadzone, center=wrap_cfg.deadzone_center, max_act=wrap_cfg.deadzone_max_act)
    env = HistoryWrapper(env, steps=wrap_cfg.history_steps, use_continuity_cost=wrap_cfg.use_continuity_cost)
    return env


def train_and_evaluate(
    timesteps: int = 50_000,
    reward: str = "cos_alpha",
    lr: float = 3e-4,
    net_size: int = 256,
    vel_clamp: float = 50.0,
    run_name: str = "auto",
    seed: int | None = None,
) -> dict:
    """Train SAC and return metrics."""
    vec_env = DummyVecEnv([lambda: make_env(reward, vel_clamp)])

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
        tensorboard_log="runs",
        verbose=0,
        policy_kwargs=dict(net_arch=dict(pi=[net_size, net_size], qf=[net_size, net_size])),
    )

    t0 = time.time()
    model.learn(total_timesteps=timesteps, progress_bar=False, tb_log_name=run_name)
    elapsed = time.time() - t0

    # Save model
    save_dir = Path("models")
    save_dir.mkdir(exist_ok=True)
    model_path = save_dir / f"qube_sac_{run_name}.zip"
    model.save(str(model_path))

    # Read TensorBoard metrics
    from tensorboard.backend.event_processing.event_accumulator import EventAccumulator

    run_dirs = sorted(Path("runs").glob(f"{run_name}_*"), key=lambda p: p.stat().st_mtime)
    if run_dirs:
        ea = EventAccumulator(str(run_dirs[-1]))
        ea.Reload()
        tags = ea.Tags().get("scalars", [])

        metrics = {}
        for tag in tags:
            events = ea.Scalars(tag)
            if events:
                metrics[tag] = {"last_step": events[-1].step, "last_value": events[-1].value, "count": len(events)}

        # Read episode data from monitor.csv
        monitor_files = list(run_dirs[-1].glob("*.monitor.csv"))
        ep_lengths = []
        ep_rewards = []
        if monitor_files:
            import csv

            with open(monitor_files[0]) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    ep_lengths.append(float(row["l"]))
                    ep_rewards.append(float(row["r"]))
    else:
        metrics = {}
        ep_lengths = []
        ep_rewards = []

    return {
        "run_name": run_name,
        "timesteps": timesteps,
        "elapsed_s": elapsed,
        "fps": timesteps / elapsed if elapsed > 0 else 0,
        "model_path": str(model_path),
        "metrics": metrics,
        "episodes": len(ep_lengths),
        "ep_len_mean": float(np.mean(ep_lengths)) if ep_lengths else 0,
        "ep_len_max": float(np.max(ep_lengths)) if ep_lengths else 0,
        "ep_rew_mean": float(np.mean(ep_rewards)) if ep_rewards else 0,
        "ep_rew_max": float(np.max(ep_rewards)) if ep_rewards else 0,
    }


def log_run_to_mlflow(result: dict, *, enabled: bool, uri: str | None, experiment: str) -> None:
    """Log one run's params and final scalar metrics to MLflow (no-op if disabled)."""
    from qube_rl.mlflow_tracking import mlflow_run

    params = {
        "run_name": result["run_name"],
        "timesteps": result["timesteps"],
    }
    metric_keys = ("fps", "episodes", "ep_len_mean", "ep_len_max", "ep_rew_mean", "ep_rew_max", "elapsed_s")
    with mlflow_run(result["run_name"], params, enabled=enabled, uri=uri, experiment=experiment) as run:
        if run:
            for key in metric_keys:
                if key in result:
                    run.log_metric(key, float(result[key]))


def write_progress(results: list[dict], status: str, out_dir: Path) -> None:
    """Write training progress to a markdown file under ``out_dir``."""
    lines = [
        "# Training Progress — Autonomous Loop",
        f"**Status:** {status}",
        f"**Last update:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Runs",
        "",
        "| Run | Steps | FPS | Episodes | Ep Len Mean | Ep Len Max | Ep Rew Mean | Ep Rew Max |",
        "|-----|-------|-----|----------|-------------|------------|-------------|------------|",
    ]
    for r in results:
        lines.append(
            f"| {r['run_name']} | {r['timesteps']} | {r['fps']:.0f} | "
            f"{r['episodes']} | {r['ep_len_mean']:.1f} | {r['ep_len_max']:.0f} | "
            f"{r['ep_rew_mean']:.2f} | {r['ep_rew_max']:.2f} |"
        )

    if results:
        last = results[-1]
        lines.extend(
            [
                "",
                "## Analysis",
                "",
                f"- **Episode length mean:** {last['ep_len_mean']:.1f} steps ({last['ep_len_mean'] / 50:.2f}s at 50Hz)",
                f"- **Episode length max:** {last['ep_len_max']:.0f} steps ({last['ep_len_max'] / 50:.2f}s at 50Hz)",
                f"- **Reward mean:** {last['ep_rew_mean']:.2f}",
                "",
            ]
        )

        if last["ep_len_mean"] > 100:
            lines.append("✅ **Episodes > 2 seconds — agent is learning to balance!**")
        elif last["ep_len_mean"] > 50:
            lines.append("⚠️ **Episodes > 1 second — agent exploring but not stable yet**")
        else:
            lines.append("❌ **Episodes < 1 second — agent not learning yet**")

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "training_progress.md").write_text("\n".join(lines))


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Autonomous SAC training loop for QUBE")
    parser.add_argument("--seed", type=int, default=None, help="Random seed (omit for non-deterministic)")
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for progress report (default: experiments/<today>_training)",
    )
    parser.add_argument("--mlflow", action="store_true", help="Log each run's metrics to MLflow")
    parser.add_argument(
        "--mlflow-uri", default=None, help="MLflow tracking URI (default: sqlite:///mlflow.db or env var)"
    )
    parser.add_argument("--mlflow-experiment", default="qube_sac_auto", help="MLflow experiment name")
    args = parser.parse_args()

    set_global_seeds(args.seed)
    out_dir = Path(args.out_dir) if args.out_dir else Path("experiments") / f"{datetime.now():%Y-%m-%d}_training"

    results = []

    # Run 1: Baseline (50K steps)
    print("=" * 60)
    print("RUN 1: Baseline — 50K steps, cos_alpha, lr=3e-4, net=256")
    print("=" * 60)
    mlflow_kw = {"enabled": args.mlflow, "uri": args.mlflow_uri, "experiment": args.mlflow_experiment}

    r1 = train_and_evaluate(timesteps=50_000, run_name="run1_baseline", seed=args.seed)
    results.append(r1)
    log_run_to_mlflow(r1, **mlflow_kw)
    write_progress(results, f"Run 1 done — ep_len_mean={r1['ep_len_mean']:.1f}", out_dir)
    print(f"  Episodes: {r1['episodes']}, Avg len: {r1['ep_len_mean']:.1f}, Avg rew: {r1['ep_rew_mean']:.2f}")

    # Run 2: More aggressive reward (50K steps)
    print("=" * 60)
    print("RUN 2: exp_alpha_4 reward — 50K steps")
    print("=" * 60)
    r2 = train_and_evaluate(timesteps=50_000, reward="exp_alpha_4", run_name="run2_exp_reward", seed=args.seed)
    results.append(r2)
    log_run_to_mlflow(r2, **mlflow_kw)
    write_progress(results, f"Run 2 done — ep_len_mean={r2['ep_len_mean']:.1f}", out_dir)
    print(f"  Episodes: {r2['episodes']}, Avg len: {r2['ep_len_mean']:.1f}, Avg rew: {r2['ep_rew_mean']:.2f}")

    # Run 3: Best config so far, longer training (100K steps)
    best_reward = "exp_alpha_4" if r2["ep_len_mean"] > r1["ep_len_mean"] else "cos_alpha"
    print("=" * 60)
    print(f"RUN 3: Best ({best_reward}) — 100K steps")
    print("=" * 60)
    r3 = train_and_evaluate(timesteps=100_000, reward=best_reward, run_name="run3_best_long", seed=args.seed)
    results.append(r3)
    log_run_to_mlflow(r3, **mlflow_kw)
    write_progress(results, f"Run 3 done — ep_len_mean={r3['ep_len_mean']:.1f}", out_dir)
    print(f"  Episodes: {r3['episodes']}, Avg len: {r3['ep_len_mean']:.1f}, Avg rew: {r3['ep_rew_mean']:.2f}")

    # Final summary
    write_progress(results, "All runs complete", out_dir)
    print("\n" + "=" * 60)
    print(f"TRAINING COMPLETE — see {out_dir / 'training_progress.md'}")
    print("=" * 60)


if __name__ == "__main__":
    main()
