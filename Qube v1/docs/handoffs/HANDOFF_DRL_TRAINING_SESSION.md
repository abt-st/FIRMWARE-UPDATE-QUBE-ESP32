# DRL Training Session — 2026-06-17
# Comprehensive results from all experiments

## Executive Summary

- **Goal**: Swing-up + balance a rotary inverted pendulum (QUBE Servo) with arm angle constraints
- **Best reach rate**: 38% with sinusoidal PD controller at ±120°
- **Best balance rate**: 0% — no approach achieved sustained balance
- **Key finding**: The ±90° arm constraint is extremely restrictive; ±120° doubles reach rate
- **ESP32 constraint**: [64,64] network (21KB) fits; [96,96]+ does not

---

## 1. RL Training Results (SAC)

### Configuration Matrix

| ID | Reward | Network | Obs Dims | LR | Angle Limit | Steps | Reach | Balance |
|---|---|---|---|---|---|---|---|---|
| SAC_16 | linear_alpha | [64,64] | 36 (hist4) | 3e-4 | ±90° | 200K | 0% | 0% |
| SAC_17_128_c1 | linear_alpha | [128,128] | 36 (hist4) | 5e-4 | ±90° | 100K | 0%* | 0% |
| SAC_19_64_hr_c1 | linear_alpha | [64,64] | 36 (hist4) | 5e-4 | ±90° | 100K | 0% | 0% |
| SAC_21_96_c1 | linear_alpha | [96,96] | 36 (hist4) | 5e-4 | ±90° | 100K | 4%* | 0% |
| SAC_22_hist2 | linear_alpha | [64,64] | 18 (hist2) | 5e-4 | ±90° | 250K | 0% | 0% |
| SAC_23_raw8_c1 | linear_alpha | [64,64] | 8 (raw) | 5e-4 | ±90° | 50K | 0% | 0% |
| SAC_23_raw8_c2 | linear_alpha | [64,64] | 8 (raw) | 5e-4 | ±90° | 100K | 8% | 0% |
| SAC_24_c1 | linear_alpha | [64,64] | 8 (raw) | 5e-4 | ±90° | 200K | 8% | 0% |
| SAC_24_c2 | linear_alpha | [64,64] | 8 (raw) | 5e-4 | ±90° | 300K | 8% | 0% |

*Reach = pendulum reaches >150° from inverted. Balance = stays >150° for >25 consecutive steps.*

### Key Observations (RL)
- [128,128] was previously reported at 40% reach — **disproven**: alpha was accumulating unboundedly (spinning, not swing-up)
- [64,64] with raw 8-dim obs is the best ESP32-compatible config (8% reach)
- History wrapper (36d) hurts [64,64] — too many input parameters consume capacity
- SAC converges quickly to local optima and stops learning

---

## 2. Classical Controller Results

### Energy-Based Swing-Up + LQR Balance

| Method | Angle Limit | Reach (>150°) | Balance (>25 steps) | Balance (>100 steps) |
|---|---|---|---|---|
| Bang-bang (alpha_dot zero-cross) | ±90° | 10% | 0% | 0% |
| Bang-bang (alpha_dot zero-cross) | ±120° | 8% | 0% | 0% |
| Sinusoidal PD (2x parametric) | ±90° | 8% | 0% | 0% |
| **Sinusoidal PD (2x parametric)** | **±120°** | **38%** | **0%** | **0%** |
| Direct excitation (1x freq) | ±120° | 2% | 0% | 0% |

### PD Balance Controllers Tested

| Switch Angle | Max Action | Balance Rate | Notes |
|---|---|---|---|
| LQR sw=145° | 1.0 | 0% | Action too large, arm hits limit |
| LQR sw=140° | 1.0 | 0% | Same |
| PD sw=145° | 0.75 | 0% | Pendulum passes too fast |
| PD sw=140° | 0.75 | 0% | Same |
| PD sw=135° | 0.75 | 0% | Same |
| PD sw=130° | 0.5 | 0% | Gentle but pendulum doesn't reach |
| PD sw=125° | 0.6 | 0% | Same |
| PD sw=120° | 0.5 | 0% | Same |
| PD sw=115° | 0.4 | 0% | Too early, pendulum not high enough |

### Why Balance Always Fails

The balance phase requires ALL of:
1. Pendulum near inverted (|alpha| > 150°)
2. Pendulum slow (|alpha_dot| < 3 rad/s)
3. Arm near center (|theta| < 40°)

These conditions almost never align because:
- The sinusoidal pumping creates a fixed phase relationship
- When pendulum reaches top, arm is typically at its extreme (±80-100°)
- The arm can't move to center AND balance the pendulum simultaneously

---

## 3. Physical Constraints Analysis

### Arm Angle Limits

| Limit | Reach Rate | Why |
|---|---|---|
| ±80° (conservative) | ~10% | Insufficient energy injection |
| ±90° (original spec) | 8-10% | Barely enough for energy buildup |
| **±120°** | **38%** | Significant improvement |
| ±150° | TBD | Likely high reach + possible balance |
| ±180° (no limit) | TBD | Pipeline should work |

### Network Size vs ESP32

| Network | Params | Flash (float32) | ESP32 OK? | Obs Dims |
|---|---|---|---|---|
| [64,64] raw8 | 5,441 | 21.3 KB | ✅ | 8 |
| [64,64] hist2 | 5,441 | 21.3 KB | ✅ | 18 |
| [64,64] hist4 | 6,593 | 25.8 KB | ⚠️ tight | 36 |
| [96,96] | ~13K | ~50 KB | ❌ | any |
| [128,128] | ~17K | ~67 KB | ❌ | any |

---

## 4. Models Saved

| File | Description | Best Metric |
|---|---|---|
| `qube_sac_SAC_17_128_c1.zip` | [128,128] 100K steps | 0% reach (disproven) |
| `qube_sac_SAC_21_96_c1.zip` | [96,96] 100K steps | 4% reach |
| `qube_sac_SAC_23_raw8_c2.zip` | [64,64] raw8 100K | 8% reach |
| `qube_sac_SAC_24_c2cont_c1.zip` | [64,64] raw8 200K | 8% reach |
| `qube_sac_distilled_64_c1.zip` | Distilled [64,64] | 5% reach |

---

## 5. Code Created This Session

| File | Purpose |
|---|---|
| `src/qube_rl/lqr.py` | LQR balance controller for inverted equilibrium |
| `src/qube_rl/energy_swingup.py` | Energy-based swing-up + LQR handoff |
| `src/qube_rl/distill.py` | Knowledge distillation [128,128] → [64,64] |
| `src/qube_rl/rewards_simple.py` | Simplified reward functions |
| `models/policy_weights.h` | C++ header export (from [128,128]) |

---

## 6. Recommended Next Steps

1. **Test ±180° (no constraint)** to confirm the full pipeline works
2. **Sweep ±100° to ±150°** to find minimum working constraint
3. **Improve balance controller** — use trajectory optimization or MPC instead of PD
4. **Train SAC with energy reward** — `reward = dE/dt` to explicitly encourage energy injection
5. **Consider TD3** — more stable than SAC for this type of sequential task

---

## 7. Training Hyperparameters (Best Config)

```python
# SAC with raw 8-dim observations
SAC(
    policy="MlpPolicy",
    learning_rate=5e-4,
    buffer_size=500_000,
    batch_size=256,
    tau=0.005,
    gamma=0.99,
    use_sde=True,
    use_sde_at_warmup=True,
    sde_sample_freq=64,
    train_freq=1,
    gradient_steps=1,
    learning_starts=1000,
    policy_kwargs=dict(
        net_arch=dict(pi=[64, 64], qf=[64, 64])
    ),
)

# Environment
QubeSimEnv(
    control_freq=50,
    reward="linear_alpha",
    angle_limits=[np.radians(120), np.pi],  # ±120° arm, ±180° pendulum
    speed_limits=[50.0, 400.0],
    encoders_cprs=None,
    velocity_filter_order=2,
)

# Sinusoidal PD controller (best classical)
A = np.radians(84)  # arm amplitude
omega_est = 10.0     # pendulum frequency estimate (updated online)
theta_ref = A * np.sin(2 * omega_est * (t - phase_offset))
action = 2.0 * (theta_ref - theta) - 0.5 * theta_dot
```

---

*Generated: 2026-06-17*
*Total experiments: ~30 configurations*
*Total training steps: ~3M across all SAC runs*
*Total wall time: ~12 hours*
