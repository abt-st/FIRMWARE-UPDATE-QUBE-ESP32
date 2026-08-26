"""R4 real-hardware v4: random exploration → fine-tune + MLflow tracking.

v4 adds:
- MLflow tracking for both phases
- Proper gym.Wrapper for action clipping
- Direct HTTP in phase 1 (bypasses DeadZone)

Usage::

    uv run python experiments/2026-06-22_r4_real/train_real_v4.py
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


def get_state(esp32_ip: str) -> dict:
    import requests
    r = requests.get(f"http://{esp32_ip}/rl_state", timeout=3)
    return r.json()


def send_action(esp32_ip: str, action: float) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/rl_cmd?a={action:.4f}", timeout=3)


def send_reset(esp32_ip: str) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/rl_cmd?r=1", timeout=3)


def set_mode(esp32_ip: str, mode: int) -> None:
    import requests
    requests.get(f"http://{esp32_ip}/cmd?m={mode}", timeout=3)


def reward_linear_alpha(alpha_rad: float) -> float:
    # Matches sim rewards.linear_alpha: |alpha|/pi -> 0 hanging, 1 inverted.
    # The old (cos(alpha)+1)/2 was INVERTED (it peaked at alpha=0 = hanging).
    al = float(np.mod(alpha_rad + np.pi, 2 * np.pi) - np.pi)
    return abs(al) / np.pi


def main() -> None:
    parser = argparse.ArgumentParser(description="R4 real v4: MLflow tracked")
    parser.add_argument("--esp32-ip", type=str, default="192.168.100.50")
    parser.add_argument("--model", type=str, default=str(BASE_MODEL))
    parser.add_argument("--random-steps", type=int, default=3_000)
    parser.add_argument("--finetune-steps", type=int, default=15_000)
    parser.add_argument("--lr", type=float, default=5e-5)
    parser.add_argument("--ep-steps", type=int, default=200)
    parser.add_argument("--action-scale", type=float, default=0.15)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--mlflow-uri", default="sqlite:///mlflow.db")
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

    def _sigint(_sig: int, _frame: object) -> None:
        log("\nCtrl+C -- emergency stop!")
        emergency_stop(ip)
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    # ── MLflow setup ────────────────────────────────────────────────────
    import mlflow
    mlflow.set_tracking_uri(args.mlflow_uri)
    mlflow.set_experiment(MLFLOW_EXPERIMENT)

    # ── Set RL mode ─────────────────────────────────────────────────────
    set_mode(ip, 6)
    time.sleep(0.2)

    total_steps = args.random_steps + args.finetune_steps
    log("=" * 60)
    log("R4 REAL v4: MLflow tracked")
    log(f"  ESP32: {ip}")
    log(f"  Phase 1: {args.random_steps:,} random steps (PWM ±{args.action_scale:.0%})")
    log(f"  Phase 2: {args.finetune_steps:,} fine-tune steps")
    log(f"  Episode: {args.ep_steps} steps ({args.ep_steps / 50:.1f}s)")
    log(f"  MLflow: {args.mlflow_uri} / {MLFLOW_EXPERIMENT}")
    log("=" * 60)

    # ==================================================================
    # PHASE 1: Random exploration — direct HTTP, logged to MLflow
    # ==================================================================
    log("\n--- PHASE 1: Random exploration ---")
    t0 = time.time()
    step = 0
    ep_count = 0
    max_pwm = args.action_scale

    with mlflow.start_run(run_name=f"r4_real_s{args.seed}"):
        # Log params
        mlflow.log_params({
            "phase": "random_explore+finetune",
            "esp32_ip": ip,
            "model": str(args.model),
            "random_steps": args.random_steps,
            "finetune_steps": args.finetune_steps,
            "lr": args.lr,
            "ep_steps": args.ep_steps,
            "action_scale": args.action_scale,
            "seed": args.seed,
            "reward": "linear_alpha",
            "total_steps": total_steps,
        })

        try:
            send_reset(ip)
            time.sleep(1.0)

            ep_reward = 0.0
            ep_step = 0
            ep_theta_sum = 0.0
            ep_alpha_sum = 0.0

            while step < args.random_steps:
                action_val = np.random.uniform(-max_pwm, max_pwm)
                send_action(ip, action_val)
                time.sleep(0.02)

                data = get_state(ip)
                # /rl_state is ALREADY in radians — do NOT np.radians() it again
                # (the old double-conversion shrank angles ~57x and broke r4_real).
                theta = float(data["th"])
                alpha = float(np.mod(data["al"] + np.pi, 2 * np.pi) - np.pi)  # wrap to [-pi, pi]
                rwd = reward_linear_alpha(alpha)
                ep_step += 1
                ep_reward += rwd
                ep_theta_sum += abs(np.degrees(theta))
                ep_alpha_sum += abs(np.degrees(alpha))
                step += 1

                terminated = abs(theta) > np.pi * 0.55
                truncated = ep_step >= args.ep_steps

                if terminated or truncated:
                    ep_count += 1
                    elapsed = time.time() - t0
                    sps = step / elapsed if elapsed > 0 else 0
                    avg_theta = ep_theta_sum / ep_step
                    avg_alpha = ep_alpha_sum / ep_step

                    mlflow.log_metrics({
                        "random/ep_reward": ep_reward,
                        "random/ep_steps": ep_step,
                        "random/avg_theta_deg": avg_theta,
                        "random/avg_alpha_deg": avg_alpha,
                        "random/sps": sps,
                    }, step=ep_count)

                    log(f"  step {step:>6}/{args.random_steps:,} | ep {ep_count:>3} | "
                        f"rew={ep_reward:.1f} | avg_theta={avg_theta:.0f} | "
                        f"avg_alpha={avg_alpha:.0f} | {sps:.1f} sps")
                    ep_reward = 0.0
                    ep_step = 0
                    ep_theta_sum = 0.0
                    ep_alpha_sum = 0.0
                    # No encoder reset — servo stays where it is
                    time.sleep(0.1)

            log(f"Phase 1 done: {step} steps, {ep_count} episodes in {time.time() - t0:.0f}s")
            mlflow.log_metric("random/total_episodes", ep_count)

        except Exception as exc:
            log(f"Phase 1 error at step {step}: {exc}")
            emergency_stop(ip)
            mlflow.log_param("error", str(exc))
            import traceback
            traceback.print_exc()
            return

        # ==================================================================
        # PHASE 2: Fine-tune sim policy on real env
        # ==================================================================
        log("\n--- PHASE 2: Fine-tune sim policy on real data ---")

        from qube_rl.envs.factory import make_real_env
        from qube_rl.mlflow_tracking import make_metrics_callback
        import gymnasium as gym
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
        mlflow.log_param("lr_finetune", args.lr)

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

        cb_metrics = make_metrics_callback(enabled=True, log_freq=500)

        ckpt_every = 2000
        remaining = args.finetune_steps
        step2_total = 0

        try:
            while remaining > 0:
                chunk = min(ckpt_every, remaining)
                log(f"  Fine-tuning {step2_total:,} to {step2_total + chunk:,} ...")
                model.learn(
                    total_timesteps=chunk,
                    reset_num_timesteps=False,
                    progress_bar=True,
                    callback=cb_metrics,
                )
                step2_total += chunk
                remaining -= chunk

                ckpt_path = models_dir / f"r4_real_s{args.seed}_step{args.random_steps + step2_total}.zip"
                model.save(str(ckpt_path))
                log(f"  Checkpoint: {ckpt_path.name}")

                # Log checkpoint to MLflow
                mlflow.log_metric("finetune/checkpoint_step", step2_total)
                with contextlib.suppress(Exception):
                    mlflow.log_artifact(str(ckpt_path))

        except Exception as exc:
            log(f"Phase 2 error: {exc}")
            mlflow.log_param("error_phase2", str(exc))
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
        log(f"\nTotal time: {elapsed:.0f}s ({elapsed / 60:.1f} min)")


if __name__ == "__main__":
    main()
