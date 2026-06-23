"""Continue R4 real fine-tune from last checkpoint (step 7000 → 15000).

Usage::

    uv run python experiments/2026-06-22_r4_real/continue_finetune.py
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
MLFLOW_EXPERIMENT = "qube_r4_real"


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Continue R4 real fine-tune")
    parser.add_argument("--esp32-ip", type=str, default="192.168.100.50")
    parser.add_argument("--checkpoint", type=str,
                        default=str(REPORT_DIR / "models/r4_real_s1_step7000.zip"))
    parser.add_argument("--remaining-steps", type=int, default=8_000,
                        help="Steps remaining to reach 15k total")
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--ep-steps", type=int, default=200)
    parser.add_argument("--action-scale", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
    args = parser.parse_args()

    from qube_rl.config import set_global_seeds
    set_global_seeds(args.seed)

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

    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -- emergency stop!")
        emergency_stop(ip)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # ── Load checkpoint ─────────────────────────────────────────────────
    import gymnasium as gym
    from stable_baselines3 import SAC
    from stable_baselines3.common.vec_env import DummyVecEnv
    from qube_rl.envs.factory import make_real_env
    from qube_rl.mlflow_tracking import make_metrics_callback
    import mlflow

    ckpt_path = Path(args.checkpoint)
    if not ckpt_path.exists():
        log(f"ERROR: Checkpoint not found: {ckpt_path}")
        return

    log(f"Loading checkpoint: {ckpt_path}")
    model = SAC.load(str(ckpt_path))
    model.learning_rate = args.lr
    log(f"LR: {args.lr:.1e}")

    # ── Build real env ──────────────────────────────────────────────────
    def _make():
        return make_real_env(
            esp32_ip=ip,
            reward="linear_alpha",
            max_episode_steps=args.ep_steps,
            auto_set_mode=True,
        )

    class ActionClipWrapper(gym.Wrapper):
        def __init__(self, env: gym.Env, scale: float):
            super().__init__(env)
            self.scale = scale

        def step(self, action):
            clipped = np.clip(action, -self.scale, self.scale)
            return self.env.step(clipped)

    train_env = DummyVecEnv([lambda: ActionClipWrapper(_make(), args.action_scale)])
    model.set_env(train_env)

    # ── MLflow ──────────────────────────────────────────────────────────
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    cb_metrics = make_metrics_callback(enabled=True, log_freq=500)

    ckpt_every = 2000
    remaining = args.remaining_steps
    step_done = 0
    base_step = 7000  # already done

    log("=" * 60)
    log("CONTINUE R4 REAL FINE-TUNE")
    log(f"  Checkpoint: {ckpt_path.name}")
    log(f"  Remaining: {args.remaining_steps:,} steps")
    log(f"  Target: {base_step + args.remaining_steps:,} total")
    log("=" * 60)

    with mlflow.start_run(run_name=f"r4_real_s{args.seed}_cont"):
        mlflow.log_params({
            "phase": "finetune_continue",
            "checkpoint": ckpt_path.name,
            "remaining_steps": args.remaining_steps,
            "lr": args.lr,
            "action_scale": args.action_scale,
            "ep_steps": args.ep_steps,
            "seed": args.seed,
        })

        t0 = time.time()
        try:
            while remaining > 0:
                chunk = min(ckpt_every, remaining)
                log(f"  Fine-tuning {base_step + step_done:,} to {base_step + step_done + chunk:,} ...")
                model.learn(
                    total_timesteps=chunk,
                    reset_num_timesteps=False,
                    progress_bar=True,
                    callback=cb_metrics,
                )
                step_done += chunk
                remaining -= chunk

                ckpt_path_out = models_dir / f"r4_real_s{args.seed}_step{base_step + step_done}.zip"
                model.save(str(ckpt_path_out))
                log(f"  Checkpoint: {ckpt_path_out.name}")
                mlflow.log_metric("finetune/checkpoint_step", base_step + step_done)
                with contextlib.suppress(Exception):
                    mlflow.log_artifact(str(ckpt_path_out))

        except Exception as exc:
            log(f"Error: {exc}")
            import traceback
            traceback.print_exc()
        finally:
            emergency_stop(ip)
            final_path = models_dir / f"r4_real_s{args.seed}_final.zip"
            model.save(str(final_path))
            log(f"Final model: {final_path}")
            with contextlib.suppress(Exception):
                mlflow.log_artifact(str(final_path))

        elapsed = time.time() - t0
        mlflow.log_metric("total/elapsed_s", elapsed)
        log(f"\nDone: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
