"""R4 real-hardware: random exploration → fine-tune.

Phase 1: Collect real-hardware data with small random actions.
Phase 2: Fine-tune the sim policy on the real replay buffer.

SAFETY:
- Actions clamped to ±20% PWM (±204 out of ±1023)
- Short episodes (50 steps = 1s at 50Hz)
- Motor kill on Ctrl+C or exception
- Checkpoints every 2k steps

Usage::

    uv run python experiments/2026-06-22_r4_real/train_real_v2.py
    uv run python experiments/2026-06-22_r4_real/train_real_v2.py --random-steps 10000 --finetune-steps 10000
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

# Windows consoles default to cp1252 and crash on non-ASCII; emit UTF-8 instead.
for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
REPO_ROOT = REPORT_DIR.parent.parent
BASE_MODEL = REPO_ROOT / "experiments/2026-06-19_r4_curriculum/models/r3_01_curriculum04_s1.zip"

# Safety: action range as fraction of full PWM (±1023)
ACTION_SCALE = 0.20  # ±20% = ±204 PWM


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def emergency_stop(esp32_ip: str) -> None:
    """Kill motor immediately."""
    import requests
    try:
        requests.get(f"http://{esp32_ip}/rl_cmd?a=0", timeout=2)
        requests.get(f"http://{esp32_ip}/cmd?m=0", timeout=2)
        log("MOTOR KILLED + mode 0")
    except Exception:
        log("EMERGENCY STOP FAILED - kill motor manually!")


def main() -> None:
    parser = argparse.ArgumentParser(description="R4 real: random explore + fine-tune")
    parser.add_argument("--esp32-ip", type=str, default="192.168.100.50")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL))
    parser.add_argument("--random-steps", type=int, default=5_000,
                        help="Phase 1: random exploration steps")
    parser.add_argument("--finetune-steps", type=int, default=15_000,
                        help="Phase 2: fine-tune on real buffer")
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--ep-steps", type=int, default=50,
                        help="Steps per episode (50=1s at 50Hz)")
    parser.add_argument("--action-scale", type=float, default=ACTION_SCALE,
                        help="Max action as fraction of full PWM")
    parser.add_argument("--reward", type=str, default="linear_alpha")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    from qube_rl.config import set_global_seeds
    set_global_seeds(args.seed)

    # ── Verify ESP32 ────────────────────────────────────────────────────
    import requests
    try:
        r = requests.get(f"http://{args.esp32_ip}/state", timeout=5)
        state = r.json()
        log(f"ESP32: mode={state['mode']}, theta={state['position_deg']:.1f}, alpha={state['pend_position_deg']:.1f}")
    except Exception as exc:
        log(f"ERROR: ESP32 unreachable: {exc}")
        return

    # ── Build real env ──────────────────────────────────────────────────
    from qube_rl.envs.factory import make_real_env

    raw_env = make_real_env(
        esp32_ip=args.esp32_ip,
        reward=args.reward,
        max_episode_steps=args.ep_steps,
        auto_set_mode=True,
    )

    # ── Output ──────────────────────────────────────────────────────────
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)

    # ── Emergency stop on Ctrl+C ────────────────────────────────────────
    ip_ref = args.esp32_ip

    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -- emergency stop!")
        emergency_stop(ip_ref)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    total_steps = args.random_steps + args.finetune_steps
    log("=" * 60)
    log("R4 REAL-HARDWARE: Random Explore + Fine-Tune")
    log(f"  ESP32: {args.esp32_ip}")
    log(f"  Phase 1: {args.random_steps:,} random steps (action scale ±{args.action_scale:.0%})")
    log(f"  Phase 2: {args.finetune_steps:,} fine-tune steps (LR={args.lr:.1e})")
    log(f"  Episode: {args.ep_steps} steps ({args.ep_steps / 50:.1f}s)")
    log(f"  Total: {total_steps:,} steps")
    log("=" * 60)

    # ==================================================================
    # PHASE 1: Random exploration with small actions
    # ==================================================================
    obs, _ = raw_env.reset()
    step = 0
    t0 = time.time()
    ep_reward = 0.0
    ep_count = 0

    try:
        while step < args.random_steps:
            action = np.array([np.random.uniform(-args.action_scale, args.action_scale)])
            obs, reward, terminated, truncated, _ = raw_env.step(action)
            ep_reward += reward
            step += 1

            if terminated or truncated:
                ep_count += 1
                elapsed = time.time() - t0
                sps = step / elapsed if elapsed > 0 else 0
                log(f"  step {step:>6}/{args.random_steps:,} | ep {ep_count:>3} | "
                    f"rew={ep_reward:.1f} | {sps:.1f} steps/s")
                ep_reward = 0.0
                obs, _ = raw_env.reset()

        log(f"Phase 1 done: {step} steps, {ep_count} episodes in {time.time() - t0:.0f}s")
        raw_env.close()

    except Exception as exc:
        log(f"Phase 1 error at step {step}: {exc}")
        emergency_stop(ip_ref)
        import traceback
        traceback.print_exc()
        return

    # ==================================================================
    # PHASE 2: Fine-tune sim policy on real replay buffer
    # ==================================================================
    log("\n--- PHASE 2: Fine-tune sim policy on real data ---")

    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        emergency_stop(ip_ref)
        return

    log(f"Loading sim model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr

    # Wrap env with action clipping for safety
    class ActionClipWrapper:
        """Clip actions to [-scale, +scale] range."""
        def __init__(self, env, scale: float):
            self.env = env
            self.scale = scale
            self.action_space = env.action_space
            self.observation_space = env.observation_space

        def reset(self, **kwargs):
            return self.env.reset(**kwargs)

        def step(self, action):
            clipped = np.clip(action, -self.scale, self.scale)
            return self.env.step(clipped)

    def _make():
        return make_real_env(
            esp32_ip=args.esp32_ip,
            reward=args.reward,
            max_episode_steps=args.ep_steps,
            auto_set_mode=True,
        )

    train_env2 = DummyVecEnv([lambda: ActionClipWrapper(_make(), args.action_scale)])
    train_env2.seed(args.seed)
    model.set_env(train_env2)

    ckpt_every = 2000
    remaining = args.finetune_steps
    t1 = time.time()

    try:
        while remaining > 0:
            chunk = min(ckpt_every, remaining)
            log(f"  Fine-tuning {args.finetune_steps - remaining:,} to "
                f"{args.finetune_steps - remaining + chunk:,} ...")
            model.learn(
                total_timesteps=chunk,
                reset_num_timesteps=False,
                progress_bar=True,
            )
            step2 = args.finetune_steps - remaining + chunk
            remaining -= chunk

            ckpt_path = models_dir / f"r4_real_s{args.seed}_step{args.random_steps + step2}.zip"
            model.save(str(ckpt_path))
            log(f"  Checkpoint: {ckpt_path.name}")

    except Exception as exc:
        log(f"Phase 2 error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        emergency_stop(ip_ref)
        final_path = models_dir / f"r4_real_s{args.seed}_final.zip"
        model.save(str(final_path))
        log(f"Final model: {final_path}")

    elapsed = time.time() - t0
    log(f"\nTotal time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
