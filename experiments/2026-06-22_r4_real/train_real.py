"""R4 real-hardware fine-tune: sim→real transfer on physical QUBE Servo.

Loads the best R4 sim model and continues training on the real pendulum
via HTTP (ESP32 at 192.168.100.50, mode 6).

SAFETY:
- Short episodes (100 steps = 2s at 50Hz) initially
- Motor kill on Ctrl+C or exception
- Checkpoints every 5k steps
- Low LR to avoid catastrophic forgetting of sim policy

Usage::

    uv run python experiments/2026-06-22_r4_real/train_real.py
    uv run python experiments/2026-06-22_r4_real/train_real.py --timesteps 50000 --ep-steps 100
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Windows consoles default to cp1252 and crash on non-ASCII; emit UTF-8 instead.
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
    """Kill motor immediately."""
    import requests
    try:
        requests.get(f"http://{esp32_ip}/rl_cmd?a=0", timeout=2)
        log("MOTOR KILLED")
    except Exception:
        log("EMERGENCY STOP FAILED - kill motor manually!")


def main() -> None:
    parser = argparse.ArgumentParser(description="R4 real-hardware fine-tune")
    parser.add_argument("--esp32-ip", type=str, default="192.168.100.50")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL))
    parser.add_argument("--timesteps", type=int, default=20_000)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--ep-steps", type=int, default=100,
                        help="Steps per episode (100=2s at 50Hz)")
    parser.add_argument("--checkpoint-every", type=int, default=5000,
                        help="Save checkpoint every N steps")
    parser.add_argument("--reward", type=str, default="linear_alpha")
    args = parser.parse_args()

    from qube_rl.config import set_global_seeds
    set_global_seeds(args.seed)

    # ── Verify ESP32 connectivity ───────────────────────────────────────
    import requests
    try:
        r = requests.get(f"http://{args.esp32_ip}/state", timeout=5)
        state = r.json()
        log(f"ESP32 connected: mode={state['mode']}, theta={state.get('pend_position_deg', 0):.1f} deg")
    except Exception as exc:
        log(f"ERROR: Cannot reach ESP32 at {args.esp32_ip}: {exc}")
        return

    # ── Load sim model ──────────────────────────────────────────────────
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv

    model_path = Path(args.model)
    if not model_path.exists():
        log(f"ERROR: Model not found: {model_path}")
        return

    log(f"Loading sim model: {model_path}")
    model = SAC.load(str(model_path))
    model.learning_rate = args.lr
    log(f"LR: {args.lr:.1e}")

    # ── Build real env ──────────────────────────────────────────────────
    from qube_rl.envs.factory import make_real_env

    def _make():
        return make_real_env(
            esp32_ip=args.esp32_ip,
            reward=args.reward,
            max_episode_steps=args.ep_steps,
            auto_set_mode=True,
        )

    train_env = DummyVecEnv([_make])
    train_env.seed(args.seed)
    model.set_env(train_env)

    # ── Output ──────────────────────────────────────────────────────────
    models_dir = REPORT_DIR / "models"
    models_dir.mkdir(exist_ok=True)

    # ── Emergency stop on Ctrl+C ────────────────────────────────────────
    esp32_ip_ref = args.esp32_ip

    def _signal_handler(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -- emergency stop!")
        emergency_stop(esp32_ip_ref)
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)

    # ── Train with periodic checkpoints ─────────────────────────────────
    log("Starting real-hardware training:")
    log(f"  ESP32: {args.esp32_ip}")
    log(f"  Steps: {args.timesteps:,}")
    log(f"  Episode length: {args.ep_steps} steps ({args.ep_steps / 50:.1f}s at 50Hz)")
    log(f"  Checkpoint every: {args.checkpoint_every:,} steps")
    log(f"  Reward: {args.reward}")
    log(f"  LR: {args.lr:.1e}")

    t0 = time.time()
    remaining = args.timesteps
    step = 0

    try:
        while remaining > 0:
            chunk = min(args.checkpoint_every, remaining)
            log(f"  Training {step:,} to {step + chunk:,} ...")
            model.learn(
                total_timesteps=chunk,
                reset_num_timesteps=False,
                progress_bar=True,
            )
            step += chunk
            remaining -= chunk

            # Save checkpoint
            ckpt_path = models_dir / f"r4_real_s{args.seed}_step{step}.zip"
            model.save(str(ckpt_path))
            log(f"  Checkpoint saved: {ckpt_path.name}")

    except Exception as exc:
        log(f"\nTraining error: {exc}")
        import traceback
        traceback.print_exc()
    finally:
        # Always kill motor
        emergency_stop(esp32_ip_ref)

        # Save final model
        final_path = models_dir / f"r4_real_s{args.seed}_final.zip"
        model.save(str(final_path))
        log(f"  Final model: {final_path}")

    elapsed = time.time() - t0
    log(f"Done in {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
