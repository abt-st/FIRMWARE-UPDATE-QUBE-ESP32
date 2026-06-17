"""Autonomous training loop with self-supervision.

Trains SAC, analyzes results, adjusts parameters if needed, and retries.
Writes progress to training_progress.md for the user to review.
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
from stable_baselines3 import SAC
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.envs.qube_sim import QubeSimEnv
from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper


def make_env(reward: str = "cos_alpha", vel_clamp: float = 50.0) -> object:
    """Build environment with Monitor for episode metrics."""
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
    env = DeadZone(env, deadzone=0.2, center=0.01, max_act=0.75)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


def train_and_evaluate(
    timesteps: int = 50_000,
    reward: str = "cos_alpha",
    lr: float = 3e-4,
    net_size: int = 256,
    vel_clamp: float = 50.0,
    run_name: str = "auto",
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


def write_progress(results: list[dict], status: str) -> None:
    """Write training progress to markdown file."""
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

    Path("experiments/2026-06-15_training").mkdir(parents=True, exist_ok=True)
    Path("experiments/2026-06-15_training/training_progress.md").write_text("\n".join(lines))


def main() -> None:
    results = []

    # Run 1: Baseline (50K steps)
    print("=" * 60)
    print("RUN 1: Baseline — 50K steps, cos_alpha, lr=3e-4, net=256")
    print("=" * 60)
    r1 = train_and_evaluate(timesteps=50_000, run_name="run1_baseline")
    results.append(r1)
    write_progress(results, f"Run 1 done — ep_len_mean={r1['ep_len_mean']:.1f}")
    print(f"  Episodes: {r1['episodes']}, Avg len: {r1['ep_len_mean']:.1f}, Avg rew: {r1['ep_rew_mean']:.2f}")

    # Run 2: More aggressive reward (50K steps)
    print("=" * 60)
    print("RUN 2: exp_alpha_4 reward — 50K steps")
    print("=" * 60)
    r2 = train_and_evaluate(timesteps=50_000, reward="exp_alpha_4", run_name="run2_exp_reward")
    results.append(r2)
    write_progress(results, f"Run 2 done — ep_len_mean={r2['ep_len_mean']:.1f}")
    print(f"  Episodes: {r2['episodes']}, Avg len: {r2['ep_len_mean']:.1f}, Avg rew: {r2['ep_rew_mean']:.2f}")

    # Run 3: Best config so far, longer training (100K steps)
    best_reward = "exp_alpha_4" if r2["ep_len_mean"] > r1["ep_len_mean"] else "cos_alpha"
    print("=" * 60)
    print(f"RUN 3: Best ({best_reward}) — 100K steps")
    print("=" * 60)
    r3 = train_and_evaluate(timesteps=100_000, reward=best_reward, run_name="run3_best_long")
    results.append(r3)
    write_progress(results, f"Run 3 done — ep_len_mean={r3['ep_len_mean']:.1f}")
    print(f"  Episodes: {r3['episodes']}, Avg len: {r3['ep_len_mean']:.1f}, Avg rew: {r3['ep_rew_mean']:.2f}")

    # Final summary
    write_progress(results, "All runs complete")
    print("\n" + "=" * 60)
    print("TRAINING COMPLETE — see experiments/2026-06-15_training/training_progress.md")
    print("=" * 60)


if __name__ == "__main__":
    main()
