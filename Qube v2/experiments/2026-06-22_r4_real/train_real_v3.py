"""R4 real-hardware v3: random exploration → fine-tune.

v3 fixes from v2:
- Bypasses DeadZone wrapper in phase 1 (direct HTTP, no gym wrappers)
- Action scale ±50% PWM (above BTS7960 deadzone)
- Episodes 200 steps (4s at 50Hz)

Usage::

    uv run python experiments/2026-06-22_r4_real/train_real_v3.py
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

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

REPORT_DIR = Path(__file__).resolve().parent
REPO_ROOT = REPORT_DIR.parent.parent
BASE_MODEL = REPO_ROOT / "experiments/2026-06-19_r4_curriculum/models/r3_01_curriculum04_s1.zip"


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def emergency_stop(esp32_ip: str) -> None:
    import requests
    try:
        requests.get(f"http://{esp32_ip}/rl_cmd?a=0", timeout=2)
        requests.get(f"http://{esp32_ip}/cmd?m=0", timeout=2)
        log("MOTOR KILLED + mode 0")
    except Exception:
        log("EMERGENCY STOP FAILED - kill motor manually!")


def get_state(esp32_ip: str) -> dict:
    import requests
    r = requests.get(f"http://{esp32_ip}/rl_state", timeout=3)
    return r.json()


def send_action(esp32_ip: str, action: float) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/rl_cmd?a={action:.1f}", timeout=3)


def send_reset(esp32_ip: str) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/rl_cmd?r=1", timeout=3)


def set_mode(esp32_ip: str, mode: int) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/cmd?m={mode}", timeout=3)


def reward_linear_alpha(alpha_rad: float) -> float:
    """Reward: 1.0 at inverted (alpha=pi), 0.0 at hanging (alpha=0)."""
    return float((np.cos(alpha_rad) + 1.0) / 2.0)


def main() -> None:
    parser = argparse.ArgumentParser(description="R4 real v3: direct HTTP, no wrappers")
    parser.add_argument("--esp32-ip", type=str, default="192.168.100.50")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL))
    parser.add_argument("--random-steps", type=int, default=3_000)
    parser.add_argument("--finetune-steps", type=int, default=15_000)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--ep-steps", type=int, default=200)
    parser.add_argument("--action-scale", type=float, default=0.50)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()

    from qube_rl.config import set_global_seeds
    set_global_seeds(args.seed)
    np.random.seed(args.seed)

    # ── Verify ESP32 ────────────────────────────────────────────────────
    try:
        import requests
        r = requests.get(f"http://{args.esp32_ip}/state", timeout=5)
        state = r.json()
        log(f"ESP32: mode={state['mode']}, theta={state['position_deg']:.1f}, alpha={state['pend_position_deg']:.1f}")
    except Exception as exc:
        log(f"ERROR: ESP32 unreachable: {exc}")
        return

    ip = args.esp32_ip
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)

    # ── Emergency stop on Ctrl+C ────────────────────────────────────────
    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -- emergency stop!")
        emergency_stop(ip)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # ── Set RL mode ─────────────────────────────────────────────────────
    set_mode(ip, 6)
    time.sleep(0.2)

    log("=" * 60)
    log("R4 REAL v3: Direct HTTP, no gym wrappers")
    log(f"  ESP32: {ip}")
    log(f"  Phase 1: {args.random_steps:,} random steps (PWM ±{args.action_scale:.0%})")
    log(f"  Phase 2: {args.finetune_steps:,} fine-tune steps")
    log(f"  Episode: {args.ep_steps} steps ({args.ep_steps / 50:.1f}s)")
    log("=" * 60)

    # ==================================================================
    # PHASE 1: Random exploration — direct HTTP, no wrappers
    # ==================================================================
    log("\n--- PHASE 1: Random exploration (direct HTTP) ---")
    t0 = time.time()
    step = 0
    ep_count = 0
    observations = []
    actions_list = []
    rewards_list = []
    dones_list = []

    max_pwm = args.action_scale * 1023  # Convert fraction to PWM

    try:
        send_reset(ip)
        time.sleep(1.0)  # Let pendulum settle

        ep_reward = 0.0
        ep_step = 0

        while step < args.random_steps:
            # Random action in [-max_pwm, +max_pwm]
            action_pwm = np.random.uniform(-max_pwm, max_pwm)
            send_action(ip, action_pwm)
            time.sleep(0.02)  # 50Hz

            # Read state
            data = get_state(ip)
            theta = np.radians(data["th"])
            alpha = np.radians(data["al"])
            thd = np.radians(data["thd"])
            ald = np.radians(data["ald"])

            obs = np.array([theta, alpha, thd, ald], dtype=np.float32)
            rwd = reward_linear_alpha(alpha)
            ep_step += 1
            ep_reward += rwd
            step += 1

            # Store transition
            observations.append(obs.copy())
            actions_list.append(np.array([action_pwm / 1023.0], dtype=np.float32))
            rewards_list.append(rwd)

            # Episode end: servo limit or time limit
            terminated = abs(theta) > np.pi * 0.65  # ~117°
            truncated = ep_step >= args.ep_steps
            done = terminated or truncated
            dones_list.append(done)

            if done:
                ep_count += 1
                elapsed = time.time() - t0
                sps = step / elapsed if elapsed > 0 else 0
                log(f"  step {step:>6}/{args.random_steps:,} | ep {ep_count:>3} | "
                    f"rew={ep_reward:.1f} | theta={np.degrees(theta):.0f} | "
                    f"alpha={np.degrees(alpha):.0f} | {sps:.1f} sps")
                ep_reward = 0.0
                ep_step = 0
                send_reset(ip)
                time.sleep(0.5)

        log(f"Phase 1 done: {step} steps, {ep_count} episodes in {time.time() - t0:.0f}s")

    except Exception as exc:
        log(f"Phase 1 error at step {step}: {exc}")
        emergency_stop(ip)
        import traceback
        traceback.print_exc()
        return

    # ==================================================================
    # PHASE 2: Fine-tune sim policy with real env (gym wrappers)
    # ==================================================================
    log("\n--- PHASE 2: Fine-tune sim policy on real data ---")

    from qube_rl.envs.factory import make_real_env
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        emergency_stop(ip)
        return

    log(f"Loading sim model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr

    # Build real env with longer episodes
    def _make():
        return make_real_env(
            esp32_ip=ip,
            reward="linear_alpha",
            max_episode_steps=args.ep_steps,
            auto_set_mode=True,
        )

    # Wrap with action clipping
    import gymnasium as gym

    class ActionClipWrapper(gym.Wrapper):
        def __init__(self, env: gym.Env, scale: float):
            super().__init__(env)
            self.scale = scale

        def step(self, action):
            clipped = np.clip(action, -self.scale, self.scale)
            return self.env.step(clipped)

    train_env = DummyVecEnv([lambda: ActionClipWrapper(_make(), args.action_scale)])
    train_env.seed(args.seed)
    model.set_env(train_env)

    ckpt_every = 2000
    remaining = args.finetune_steps

    try:
        while remaining > 0:
            chunk = min(ckpt_every, remaining)
            step2 = args.finetune_steps - remaining
            log(f"  Fine-tuning {step2:,} to {step2 + chunk:,} ...")
            model.learn(
                total_timesteps=chunk,
                reset_num_timesteps=False,
                progress_bar=True,
            )
            remaining -= chunk

            ckpt_path = models_dir / f"r4_real_s{args.seed}_step{args.random_steps + step2 + chunk}.zip"
            model.save(str(ckpt_path))
            log(f"  Checkpoint: {ckpt_path.name}")

    except Exception as exc:
        log(f"Phase 2 error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        emergency_stop(ip)
        final_path = models_dir / f"r4_real_s{args.seed}_final.zip"
        model.save(str(final_path))
        log(f"Final model: {final_path}")

    elapsed = time.time() - t0
    log(f"\nTotal time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
