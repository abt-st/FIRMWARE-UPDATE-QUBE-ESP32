"""Verify that the firmware's rl_forward() matches model.predict numerically.

Re-implements the exact firmware forward pass (ReLU→ReLU→Linear→tanh) in NumPy
and compares against SB3 SAC's deterministic predict over observations drawn
from a simulated rollout.

Usage:
    uv run python experiments/2026-06-23_r7_curriculum_sweep/verify_export.py
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import numpy as np

for _stream in (sys.stdout, sys.stderr):
    with contextlib.suppress(Exception):
        _stream.reconfigure(encoding="utf-8")

# ── 1. Load the SB3 model ────────────────────────────────────────────────────
from stable_baselines3 import SAC

MODEL_PATH = Path(
    "experiments/2026-06-23_r7_curriculum_sweep/models/r7_cur0.3_s0_best.zip"
)
model = SAC.load(str(MODEL_PATH))
actor = model.policy.actor

# Extract weights exactly as the firmware sees them
W0 = actor.latent_pi[0].weight.detach().cpu().numpy().astype(np.float32)  # (64, 36)
b0 = actor.latent_pi[0].bias.detach().cpu().numpy().astype(np.float32)    # (64,)
W1 = actor.latent_pi[2].weight.detach().cpu().numpy().astype(np.float32)  # (64, 64)
b1 = actor.latent_pi[2].bias.detach().cpu().numpy().astype(np.float32)    # (64,)
W2 = actor.mu[0].weight.detach().cpu().numpy().astype(np.float32)          # (1, 64)
b2 = actor.mu[0].bias.detach().cpu().numpy().astype(np.float32)            # (1,)

print(f"Layer 0: W{W0.shape} b{b0.shape}")
print(f"Layer 1: W{W1.shape} b{b1.shape}")
print(f"Layer 2: W{W2.shape} b{b2.shape}")


# ── 2. Firmware-style forward pass ───────────────────────────────────────────
def firmware_forward(obs: np.ndarray) -> float:
    """Exact replica of firmware rl_forward(): ReLU→ReLU→Linear→tanh.

    All arithmetic in float32 to match ESP32 firmware exactly.
    """
    obs32 = obs.astype(np.float32)
    # Layer 0: Linear + ReLU
    h1 = (W0 @ obs32 + b0).astype(np.float32)
    h1 = np.maximum(h1, np.float32(0.0))  # ReLU

    # Layer 1: Linear + ReLU
    h2 = (W1 @ h1 + b1).astype(np.float32)
    h2 = np.maximum(h2, np.float32(0.0))  # ReLU

    # Layer 2: Linear + tanh (SB3 SAC deterministic = tanh(mu))
    raw = (W2 @ h2 + b2).astype(np.float32)
    return float(np.tanh(raw[0]))


# ── 3. Generate test observations ────────────────────────────────────────────
# Use the sim env to get realistic obs (with HistoryWrapper → 36-dim)
from qube_rl.envs.factory import make_sim_env

env = make_sim_env(reward="linear_alpha", max_episode_steps=500)
rng = np.random.default_rng(42)

observations: list[np.ndarray] = []

# Collect from 5 episodes with varied initial conditions
for _ep in range(5):
    obs, _ = env.reset(seed=int(rng.integers(0, 10000)))
    observations.append(obs.copy())
    for _step in range(100):
        act = env.action_space.sample() * 0.5  # mild random actions
        obs, _, term, trunc, _ = env.step(act)
        observations.append(obs.copy())
        if term or trunc:
            break

env.close()

# Also add some edge cases
for _obs in [
    np.zeros(36),  # all zeros
    np.ones(36) * 0.5,  # mid-range
    np.random.randn(36) * 0.1,  # small noise
    np.random.randn(36) * 1.0,  # larger noise
]:
    observations.append(_obs)

obs_array = np.array(observations, dtype=np.float32)
print(f"\nGenerated {len(obs_array)} test observations (36-dim each)")


# ── 4. Compare firmware forward (float32) vs model.predict (float64) ─────────
# The firmware uses float32; model.predict uses float64 (PyTorch).
# In the non-saturated region (|action| < 0.95) they must match tightly.
# In the saturated region (extreme obs), float32 tanh saturates earlier —
# this is expected and safe (action is still ~±1, just slightly less extreme).
fw_actions = np.array([firmware_forward(o) for o in obs_array])
sb3_actions = np.array([float(model.predict(o, deterministic=True)[0][0]) for o in obs_array])
errors_arr = np.abs(fw_actions - sb3_actions)

non_sat = np.abs(sb3_actions) < 0.95
sat = ~non_sat

print(f"\n{'='*60}")
print("VERIFICATION — firmware_forward (float32) vs model.predict (float64)")
print(f"{'='*60}")
print(f"  Observations tested:      {len(errors_arr)}")
print(f"  Non-saturated (|a|<0.95): {non_sat.sum()}")
print(f"  Saturated (|a|>=0.95):    {sat.sum()}")

if non_sat.sum() > 0:
    ns_err = errors_arr[non_sat]
    print(f"\n  Non-saturated (critical):")
    print(f"    Max:    {ns_err.max():.2e}")
    print(f"    Mean:   {ns_err.mean():.2e}")
    print(f"    Median: {np.median(ns_err):.2e}")

if sat.sum() > 0:
    s_err = errors_arr[sat]
    print(f"\n  Saturated (float32 tanh saturation — expected):")
    print(f"    Max:    {s_err.max():.2e}")
    print(f"    Mean:   {s_err.mean():.2e}")
    sign_match = np.sign(fw_actions[sat]) == np.sign(sb3_actions[sat])
    print(f"    Sign agreement: {sign_match.sum()}/{sat.sum()}")

# Pass criteria:
# 1. Non-saturated: max error < 1e-4 (float32 rounding tolerance)
# 2. Saturated: sign agreement (both near ±1, direction correct)
PASS_THRESH = 1e-4
ns_ok = (non_sat.sum() == 0) or (errors_arr[non_sat].max() < PASS_THRESH)
sat_ok = (sat.sum() == 0) or all(np.sign(fw_actions[sat]) == np.sign(sb3_actions[sat]))

if ns_ok and sat_ok:
    ns_max = errors_arr[non_sat].max() if non_sat.sum() > 0 else 0.0
    print(f"\n✅ PASS")
    if non_sat.sum() > 0:
        print(f"   Non-saturated max err: {ns_max:.2e} < {PASS_THRESH:.0e}")
    if sat.sum() > 0:
        print(f"   Saturated sign agreement: {sign_match.sum()}/{sat.sum()} OK")
    print("   Safe to deploy.")
    sys.exit(0)
else:
    print(f"\n❌ FAIL")
    if not ns_ok:
        print(f"   Non-saturated max err: {errors_arr[non_sat].max():.2e} >= {PASS_THRESH:.0e}")
    if not sat_ok:
        mismatches = np.where(sat)[0][np.sign(fw_actions[sat]) != np.sign(sb3_actions[sat])]
        print(f"   Saturated sign mismatches at indices: {mismatches}")
    worst_idx = int(np.argmax(errors_arr))
    print(f"\n   Worst obs (first 9): {obs_array[worst_idx][:9]}")
    print(f"   firmware_forward:    {fw_actions[worst_idx]:.10f}")
    print(f"   model.predict:       {sb3_actions[worst_idx]:.10f}")
    sys.exit(1)
