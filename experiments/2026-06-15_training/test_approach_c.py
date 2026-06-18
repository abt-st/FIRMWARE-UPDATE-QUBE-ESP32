"""Approach C: Firmware swing-up (mode 3) + RL balance (mode 6)."""

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


def get_state() -> dict:
    r = requests.get(f"{BASE}/rl_state", timeout=2)
    return r.json()


def wait_for_inverted(timeout_s: float = 15.0) -> bool:
    """Wait until pendulum is near inverted (|alpha| > 150 deg)."""
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        data = get_state()
        al_deg = np.degrees(data["al"])
        if abs(al_deg) > 150:
            return True
        time.sleep(0.1)
    return False


# -- Phase 1: Swing-up via firmware mode 3 --
print("[swing-up] Centering servo...")
requests.get(f"{BASE}/cmd", params={"m": "2", "sp": "0"}, timeout=5)
time.sleep(5)

print("[swing-up] Reset encoder...")
requests.get(f"{BASE}/cmd", params={"m": "6"}, timeout=5)
requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
time.sleep(2)

print("[swing-up] Activating firmware swing-up (mode 3)...")
requests.get(f"{BASE}/cmd", params={"m": "3"}, timeout=5)

print("[swing-up] Waiting for inverted position (max 15s)...")
inverted = wait_for_inverted(timeout_s=15.0)
if inverted:
    print("[swing-up] Pendulum inverted! Switching to RL balance...")
else:
    print("[swing-up] Timed out — pendulum not inverted. Trying RL anyway...")

# -- Phase 2: Switch to mode 6 for RL balance --
requests.get(f"{BASE}/cmd", params={"m": "6"}, timeout=5)
requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
time.sleep(1)

# -- Phase 3: RL inference to maintain balance --
print("[balance] Starting RL inference...")
model = SAC.load("models/qube_sac_chunk2")

env = QubeRealEnv(esp32_ip=ESP32_IP, control_freq=10, http_timeout=5.0, auto_set_mode=False)
env = Monitor(env)
env = GentlyTerminating(env)
env = DeadZone(env, deadzone=0.15, center=0.01, max_act=0.5)
env = HistoryWrapper(env, steps=4, use_continuity_cost=True)

# Manually set mode 6 and initial state
requests.get(f"{BASE}/cmd", params={"m": "6"}, timeout=5)
requests.get(f"{BASE}/rl_cmd", params={"r": "1"}, timeout=5)
time.sleep(2)

obs, _ = env.reset()
total_reward = 0.0
steps = 0
MAX_STEPS = 300  # 30s at 10Hz
results = []

print("[balance] Running RL for up to 30s...")
t0 = time.time()
done = truncated = False
while not done and not truncated and steps < MAX_STEPS:
    action, _ = model.predict(obs, deterministic=True)
    obs, reward, done, truncated, info = env.step(action)
    total_reward += reward
    steps += 1
    if steps % 20 == 0:
        data = get_state()
        al_deg = np.degrees(data["al"])
        print(f"  step {steps}: al={al_deg:.1f} reward={total_reward:.1f}")

bal_s = steps / 10.0
hit = steps >= MAX_STEPS
tag = "BAL30s+" if hit else ("BAL" if bal_s > 2.0 else "MISS")
print(f"  result: {bal_s:.1f}s reward={total_reward:.1f} [{tag}]")
results.append({"bal_s": bal_s, "reward": total_reward, "tag": tag})

env.close()

avg_bal = np.mean([r["bal_s"] for r in results])
avg_rwd = np.mean([r["reward"] for r in results])
print(f"\n[C] SUMMARY: avg_bal={avg_bal:.1f}s avg_reward={avg_rwd:.1f} result={tag}")
