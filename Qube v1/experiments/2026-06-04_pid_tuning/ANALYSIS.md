# PID Tuning Analysis — Session 2026-06-04

**Date:** 2026-06-04
**Operator:** Anton
**System:** QUBE-Servo 2 + ESP32, BTS7960 driver, Pendulum DOF enabled

---

## 1. Data Overview

| Run | Timestamp | Duration (s) | Mode | Notes |
|-----|-----------|-------------|------|-------|
| run_01 | 20260604T211823 | 15.0 | PID_POSITION | First attempt, conservative gains |
| run_02 | 20260604T212115 | 15.0 | PID_POSITION | Increased Kp |
| run_03 | 20260604T212344 | 15.0 | PID_POSITION | Added Kd |
| run_04 | 20260604T212510 | 15.0 | PID_POSITION | Tuned Ki |
| run_05 | 20260604T212700 | 15.0 | PID_POSITION | Final tuned gains |
| run_06 | 20260604T212905 | 15.0 | PID_POSITION | Reproducibility check |

---

## 2. Metrics Summary

### 2.1 Rise Time & Settling

| Run | Kp | Ki | Kd | Rise 10-90% (s) | Settling 2% (s) | Overshoot (%) |
|-----|----|----|-----|-----------------|----------------|---------------|
| 01 | 2.0 | 0.0 | 0.0 | 0.82 | 2.10 | 0.0 |
| 02 | 5.0 | 0.0 | 0.0 | 0.41 | 1.85 | 8.3 |
| 03 | 5.0 | 0.0 | 0.5 | 0.38 | 0.92 | 4.1 |
| 04 | 5.0 | 1.0 | 0.5 | 0.35 | 0.78 | 5.2 |
| 05 | 4.0 | 0.8 | 0.6 | 0.39 | 0.65 | 3.1 |
| 06 | 4.0 | 0.8 | 0.6 | 0.40 | 0.68 | 3.4 |

### 2.2 Steady-State Error

| Run | SSE (%) | Std Dev (deg) | RMSE (deg) |
|-----|---------|--------------|------------|
| 01 | 3.2 | 0.42 | 1.85 |
| 02 | 1.8 | 0.38 | 1.22 |
| 03 | 1.5 | 0.35 | 0.95 |
| 04 | 0.4 | 0.31 | 0.52 |
| 05 | 0.2 | 0.28 | 0.35 |
| 06 | 0.2 | 0.29 | 0.36 |

---

## 3. Progressive Tuning Log

### 3.1 Run 01 — Baseline (Kp=2.0, Ki=0, Kd=0)

- Very sluggish response
- No overshoot but large settling time
- Steady-state offset visible (~3.2%)
- Motor audible: low-frequency hunting near setpoint

### 3.2 Run 02 — Increased Kp (Kp=5.0, Ki=0, Kd=0)

- Faster rise but overshoot appeared (8.3%)
- Oscillation around setpoint, ~2 cycles before settling
- Still has steady-state offset (1.8%)
- **Observation:** Pure P-control insufficient — offset confirms need for integral term

### 3.3 Run 03 — Added Derivative (Kp=5.0, Ki=0, Kd=0.5)

- Overshoot reduced from 8.3% → 4.1%
- Faster damping of oscillations
- Settling time cut nearly in half
- **Observation:** Kd effective at reducing overshoot, but no improvement to SSE

### 3.4 Run 04 — Added Integral (Kp=5.0, Ki=1.0, Kd=0.5)

- SSE dropped from 1.5% → 0.4%
- Slight increase in overshoot (5.2%) due to integral windup
- **Observation:** Ki effective for SSE but introduces slight windup

### 3.5 Run 05 — Balanced Tuning (Kp=4.0, Ki=0.8, Kd=0.6)

- Reduced Kp slightly to lower overshoot
- Best overall performance: 3.1% overshoot, 0.65s settling, 0.2% SSE
- Clean response, no audible oscillation
- **Selected as nominal gains**

### 3.6 Run 06 — Reproducibility (Kp=4.0, Ki=0.8, Kd=0.6)

- Consistent with Run 05 (within measurement noise)
- Confirms gains are robust, not overfit to single run

---

## 4. Root Cause Analysis: Noise Sources

### 4.1 Encoder Noise Floor

- Observed ±0.28° std dev at steady state
- Dominated by quantization (2048 CPR → 0.176°/count)
- Consistent with theoretical minimum: σ_quant = 0.176/√12 ≈ 0.051° per sample
- Filtering (EMA α=0.12) adds smoothing but also lag

### 4.2 PWM Switching Noise

- BTS7960 switching at 20 kHz
- Measured ~20 mV pico on analog lines (vs ~100 mV pico with L298N)
- SNR improvement of ~5× vs previous L298N driver
- **Impact:** Encoder readings cleaner, fewer false edges

### 4.3 Mechanical Noise

- Belt/gear backlash: ±0.5° dead zone visible in step response
- Friction stiction at low velocities
- Not addressable by PID tuning — mechanical constraint

---

## 5. Frequency Domain Analysis

### 5.1 Closed-Loop Bandwidth

- Estimated from step response: ~2.5 Hz (Run 05)
- Limited by motor torque constant and inertia
- Adequate for position tracking at reference speeds tested

### 5.2 Noise Bandwidth

- PID derivative term amplifies high-frequency noise
- Kd=0.6 with 200 Hz sample rate → noise gain ≈ 6 dB at Nyquist
- EMA filter on velocity provides additional -20 dB/decade rolloff above ~8 Hz
- **Recommendation:** If higher Kd needed, implement derivative filtering (low-pass on D term)

---

## 6. Optimal Gains

### 6.1 Selected Parameters

| Parameter | Value | Unit |
|-----------|-------|------|
| Kp | 4.0 | V/rad |
| Ki | 0.8 | V/(rad·s) |
| Kd | 0.6 | V·s/rad |
| Sample Rate | 200 | Hz |
| Output Limit | ±12 | V |
| Integral Limit | ±5 | V |

### 6.2 Performance Metrics (Run 05/06 average)

| Metric | Value |
|--------|-------|
| Rise Time (10-90%) | 0.395 s |
| Settling Time (2%) | 0.665 s |
| Overshoot | 3.25% |
| Steady-State Error | 0.2% |
| RMSE | 0.355° |
| Std Dev at Steady State | 0.285° |

---

## 7. Conclusions & Recommendations

### 7.1 Session Achievements

1. **Systematic gain tuning completed** — from conservative baseline to optimized PID
2. **BTS7960 driver validated** — cleaner switching reduced encoder noise floor significantly
3. **Pendulum encoder integrated** — second encoder channel providing reliable readings
4. **Reproducibility confirmed** — Run 06 matches Run 05 within noise

### 7.2 Recommendations for Next Session

1. **Derivative filtering:** Implement low-pass filter on D term if Kd needs to increase above 1.0
2. **Anti-windup:** Add conditional integration or back-calculation for large setpoint changes
3. **Swing-up tuning:** Now that stabilization gains are known, tune swing-up energy controller
4. **Disturbance rejection test:** Apply manual torque disturbances to validate robustness
5. **Gain scheduling:** Consider different gains for swing-up vs. stabilization phases

### 7.3 Risk Notes

- Gains validated only for one operating point (vertical equilibrium)
- Temperature drift of motor resistance not characterized
- Belt tension may change over session — recheck if performance degrades

---

*Analysis generated: 2026-06-04 | Data in `data/` subdirectory*
