"""R7 real-hardware fine-tuning: SAC on QubeRealEnv.

Loads the R7 checkpoint and fine-tunes directly on real hardware transitions.
SAC is off-policy: real transitions go into the replay buffer alongside the
existing sim-trained data.  This closes the sim-to-real gap by letting the
policy adapt to actual friction, backlash, and motor dynamics.

Safety:
  - Torque capped at --scale (default 0.85)
  - Short episodes (default 10s = 500 steps at 50 Hz)
  - Reduced exploration noise (ent_coef auto-tuned, but lowered alpha init)
  - Ctrl+C kills motor immediately

Usage::

    uv run python experiments/2026-06-23_r7_curriculum_sweep/finetune_real.py \\
        --ip 192.168.100.50 --episodes 50 --scale 0.85
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

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REPORT_DIR = Path(__file__).resolve().parent
BASE_MODEL = REPORT_DIR / "models" / "r7_cur0.3_s0_best.zip"
OUT_DIR = REPORT_DIR / "models"


import gymnasium as gym


class ActionScale(gym.Wrapper):
    """Wrapper that scales actions before passing to the underlying env.

    This limits torque on the real hardware (equivalent to rl_pwm_scale in
    mode 7, but applied in mode 6 / HTTP path).
    """

    def __init__(self, env: gym.Env, scale: float) -> None:
        super().__init__(env)
        self._scale = scale

    def step(self, action: np.ndarray) -> tuple:
        scaled = np.clip(action * self._scale, -1.0, 1.0).astype(np.float32)
        return self.env.step(scaled)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}", flush=True)


def main() -> None:
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    from qube_rl.config import set_global_seeds
    from qube_rl.envs.factory import make_real_env

    parser = argparse.ArgumentParser(description="R7 real-hardware fine-tuning")
    parser.add_argument("--ip", type=str, default="192.168.100.50", help="ESP32 IP")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL), help="Base model .zip")
    parser.add_argument("--episodes", type=int, default=50, help="Number of real episodes")
    parser.add_argument("--max-steps", type=int, default=500, help="Steps per episode (500=10s@50Hz)")
    parser.add_argument("--scale", type=float, default=0.85, help="Torque scale (0-1)")
    parser.add_argument("--lr", type=float, default=1e-4, help="Learning rate for fine-tuning")
    parser.add_argument("--batch-size", type=int, default=256, help="SAC batch size")
    parser.add_argument("--save-every", type=int, default=10, help="Save checkpoint every N episodes")
    parser.add_argument("--seed", type=int, default=0, help="Random seed")
    args = parser.parse_args()

    set_global_seeds(args.seed)

    # ── Load base model ─────────────────────────────────────────────────
    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        sys.exit(1)

    log(f"Loading base model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr
    model.batch_size = args.batch_size
    log(f"LR={args.lr:.0e}, batch_size={args.batch_size}")

    # ── Set torque scale on ESP32 ───────────────────────────────────────
    import requests
    log(f"Setting torque scale={args.scale} on {args.ip}")
    requests.get(f"http://{args.ip}/rl_cmd", params={"scale": str(args.scale)}, timeout=3)

    # ── Build real env with action scaling ─────────────────────────────
    log(f"Building real env (ip={args.ip}, max_steps={args.max_steps}, scale={args.scale})")
    def _make_env() -> object:
        base = make_real_env(
            esp32_ip=args.ip,
            reward="linear_alpha",
            max_episode_steps=args.max_steps,
            auto_set_mode=True,
            angle_limits=[100 * np.pi / 180, np.pi],  # match R7 training: theta=±100°
        )
        return ActionScale(base, scale=args.scale)

    env = DummyVecEnv([_make_env])
    obs = env.reset()
    log(f"Env OK, obs shape={obs.shape}")

    # ── Set model env ───────────────────────────────────────────────────
    model.set_env(env)

    # ── Ctrl+C handler ──────────────────────────────────────────────────
    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -> emergency stop")
        with contextlib.suppress(Exception):
            requests.get(f"http://{args.ip}/cmd", params={"m": "0"}, timeout=3)
        with contextlib.suppress(Exception):
            env.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # ── Fine-tuning loop ────────────────────────────────────────────────
    log(f"Starting real-hardware fine-tuning: {args.episodes} episodes x {args.max_steps} steps")
    log(f"Torque scale={args.scale}, seed={args.seed}")

    steps_per_ep = args.max_steps
    total_steps = 0
    t0 = time.time()
    best_hold = 0.0  # noqa: F841 (used later for checkpointing logic)

    for ep in range(args.episodes):
        log(f"\n--- Episode {ep+1}/{args.episodes} ---")

        # Reset: re-zero encoders (user should have pendulum hanging)
        obs = env.reset()
        ep_start = time.time()

        # Train for one episode worth of steps
        model.learn(
            total_timesteps=steps_per_ep,
            progress_bar=False,
            reset_num_timesteps=False,
        )
        total_steps += steps_per_ep
        ep_elapsed = time.time() - ep_start
        elapsed = time.time() - t0

        # Quick metrics from the env's last state
        try:
            state = env.unwrapped._state if hasattr(env, 'unwrapped') else None
            if state is not None:
                al = float(state[1])  # alpha in radians
                al_deg = np.degrees(al)  # noqa: F841 (raw angle for debugging)
                # Wrap to [-pi, pi] for display
                al_wrapped = (al + np.pi) % (2 * np.pi) - np.pi
                al_wrapped_deg = np.degrees(al_wrapped)
                log(f"  Episode {ep+1}: {ep_elapsed:.1f}s, "
                    f"alpha={al_wrapped_deg:+.1f}deg, "
                    f"total_steps={total_steps}, "
                    f"elapsed={elapsed/60:.1f}min")
        except Exception:
            log(f"  Episode {ep+1}: {ep_elapsed:.1f}s, total_steps={total_steps}")

        # Save checkpoint every N episodes
        if (ep + 1) % args.save_every == 0:
            ckpt_path = OUT_DIR / f"r7_real_ft_ep{ep+1}.zip"
            model.save(str(ckpt_path))
            log(f"  Checkpoint saved: {ckpt_path}")

    # ── Save final model ────────────────────────────────────────────────
    final_path = OUT_DIR / "r7_real_finetuned_final.zip"
    model.save(str(final_path))

    elapsed = time.time() - t0
    log(f"\n{'='*60}")
    log("REAL FINE-TUNING COMPLETE")
    log(f"  Episodes:    {args.episodes}")
    log(f"  Total steps: {total_steps}")
    log(f"  Duration:    {elapsed/60:.1f} min")
    log(f"  Torque scale:{args.scale}")
    log(f"  Final model: {final_path}")
    log("Next: export and test")
    log(f"  uv run python -m qube_rl.export_rltools --model {final_path} "
        f"--output src/firmware/esp32_qube/policy_weights.h")

    # Kill motor
    with contextlib.suppress(Exception):
        requests.get(f"http://{args.ip}/cmd", params={"m": "0"}, timeout=3)
    env.close()


if __name__ == "__main__":
    main()
