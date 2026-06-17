"""Approach B: Fine-tune at 5Hz — ultra-safe, lower timeout pressure."""
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
    env = QubeRealEnv(esp32_ip=ESP32_IP, control_freq=5, http_timeout=5.0)
    env = Monitor(env)
    env = GentlyTerminating(env)
    env = DeadZone(env, deadzone=0.15, center=0.01, max_act=0.5)
    env = HistoryWrapper(env, steps=4, use_continuity_cost=True)
    return env


# Load pre-trained model
print("[load] Loading qube_sac_chunk2...")
model = SAC.load("models/qube_sac_chunk2")
model.learning_rate = 1e-4

env = make_env()
model.set_env(env)
model.learning_starts = 200

print("[train] Starting 500-step fine-tune at 5Hz (max_act=0.5)...")
t0 = time.time()
try:
    model.learn(
        total_timesteps=500,
        reset_num_timesteps=False,
        tb_log_name="finetune_B",
        progress_bar=False,
    )
except Exception as e:
    print(f"[train] Error: {e}")
finally:
    model.save("models/qube_sac_finetuned_B.zip")
    elapsed = time.time() - t0
    print(f"[save] Saved to models/qube_sac_finetuned_B.zip ({elapsed:.0f}s)")

# -- Evaluate --
print("\n[eval] Testing fine-tuned model: 5 episodes, 20s max...")
eval_env = make_env()
MAX_STEPS = 100  # 20s at 5Hz
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
    bal_s = steps / 5.0
    hit = steps >= MAX_STEPS
    tag = "BAL20s+" if hit else ("BAL" if bal_s > 2.0 else "MISS")
    print(f"  ep{ep}: {bal_s:.1f}s reward={total_reward:.1f} [{tag}]")
    results.append({"bal_s": bal_s, "reward": total_reward, "tag": tag})
    requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
    time.sleep(4)

eval_env.close()

avg_bal = np.mean([r["bal_s"] for r in results])
avg_rwd = np.mean([r["reward"] for r in results])
bal_count = sum(1 for r in results if r["bal_s"] > 2.0)
print(f"\n[B] SUMMARY: avg_bal={avg_bal:.1f}s avg_reward={avg_rwd:.1f} balanced={bal_count}/5")
