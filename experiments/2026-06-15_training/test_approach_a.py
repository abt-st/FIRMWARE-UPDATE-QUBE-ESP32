"""Approach A: Fine-tune with aggressive settings — low learning_starts, high max_act."""
import io
import sys
import time

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import numpy as np
import requests
from stable_baselines3 import SAC
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv

from qube_rl.envs.qube_real import QubeRealEnv
from qube_rl.wrappers import DeadZone, GentlyTerminating, HistoryWrapper

ESP32_IP = "192.168.100.50"
BASE = f"http://{ESP32_IP}"

# -- Center servo first --
print("[setup] Centering servo via PID...")
requests.get(f"{BASE}/cmd", params={"m": "2", "sp": "0"}, timeout=5)
time.sleep(5)

# -- Switch to mode 6 + reset --
print("[setup] Switching to mode 6...")
requests.get(f"{BASE}/cmd", params={"m": "6"}, timeout=5)
requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
time.sleep(3)


def make_env() -> QubeRealEnv:
    env = QubeRealEnv(esp32_ip=ESP32_IP, control_freq=10, http_timeout=5.0)
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.15, center=0.01, max_act=0.7)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


# Load pre-trained model
print("[load] Loading qube_sac_chunk2...")
model = SAC.load("models/qube_sac_chunk2")
model.learning_rate = 5e-5  # very conservative

env = make_env()
model.set_env(env)

# Override learning_starts
model.learning_starts = 200

print("[train] Starting 500-step fine-tune (max_act=0.7, lr=5e-5, learning_starts=200)...")
t0 = time.time()
try:
    model.learn(
        total_timesteps=500,
        reset_num_timesteps=False,
        tb_log_name="finetune_A",
        progress_bar=False,
    )
except Exception as e:
    print(f"[train] Error: {e}")
finally:
    # Save
    model.save("models/qube_sac_finetuned_A.zip")
    elapsed = time.time() - t0
    print(f"[save] Saved to models/qube_sac_finetuned_A.zip ({elapsed:.0f}s)")

# -- Evaluate --
print("\n[eval] Testing fine-tuned model: 5 episodes, 20s max...")
eval_env = make_env()
MAX_STEPS = 200
results = []
for ep in range(1, 6):
    obs, _ = eval_env.reset()
    total_reward = 0.0
    steps = 0
    done = truncated = False
    while not done and not truncated and steps < MAX_STEPS:
        action, _ = model.predict(obs, deterministic=True)
        obs, reward, done, truncated, info = eval_env.step(action)
        total_reward += reward
        steps += 1
    bal_s = steps / 10.0
    hit = steps >= MAX_STEPS
    tag = "BAL20s+" if hit else ("BAL" if bal_s > 2.0 else "MISS")
    print(f"  ep{ep}: {bal_s:.1f}s reward={total_reward:.1f} [{tag}]")
    results.append({"bal_s": bal_s, "reward": total_reward, "tag": tag})
    # Reset between episodes
    requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
    time.sleep(3)

eval_env.close()

# Summary
avg_bal = np.mean([r["bal_s"] for r in results])
avg_rwd = np.mean([r["reward"] for r in results])
bal_count = sum(1 for r in results if r["bal_s"] > 2.0)
print(f"\n[A] SUMMARY: avg_bal={avg_bal:.1f}s avg_reward={avg_rwd:.1f} balanced={bal_count}/5")
