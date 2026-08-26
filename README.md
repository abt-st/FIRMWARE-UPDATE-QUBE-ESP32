# QUBE ESP32 — Plataforma de control de péndulo invertido rotatorio

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)](LICENSE)
[![CI](https://github.com/abt-st/FIRMWARE-UPDATE-QUBE-ESP32/actions/workflows/ci.yml/badge.svg)](https://github.com/abt-st/FIRMWARE-UPDATE-QUBE-ESP32/actions/workflows/ci.yml)

Plataforma educativa de control de péndulo rotatorio invertido basada en **ESP32 + L298N + INA219 + 2×LM2596 + 2×CD40106BE**. Alternativa open-source al Quanser QUBE-Servo por **~$70 USD** (frente a $2,500–$3,500 USD del original).

Control PID, LQR con gain scheduling, swing-up por energía, filtro de Kalman (LQG) y Deep Reinforcement Learning (SAC) con inferencia on-device a 500 Hz en el ESP32.

---

## Estructura

| Carpeta | Versión | Estado |
|---------|---------|--------|
| `Qube v1/` | Firmware + RL + DAQ + MCP server | Estable: experimentos jun–jul 2026 |
| `Qube v2/` | + App de escritorio, + CI/CD, más experimentos | Activa: desarrollo en curso |

Cada versión tiene su propio `README.md` con documentación completa de hardware, firmware, modos de operación y pipeline RL.

---

## Edge vs Cloud

El sistema soporta dos paradigmas complementarios, detallados en cada README:

| Paradigma | Modos | Frecuencia | Dependencia externa |
|-----------|-------|-----------|---------------------|
| **Edge** (on-device) | m0–m5, m7 | **500 Hz** | Ninguna (SoftAP puro) |
| **Cloud** (asistido por PC) | m6, entrenamiento, análisis | ~50 Hz | WiFi + PC |

Edge para control desplegado en tiempo real; Cloud para desarrollo, entrenamiento SAC y fine-tuning sim-to-real.

---

## CI

`.github/workflows/ci.yml` ejecuta lint (Ruff), tests (pytest) y build del firmware (PlatformIO) para **ambas versiones** en cada push a `main`/`master`/`DRL_IMP`.

---

## Comenzar rápido

```bash
git clone https://github.com/abt-st/FIRMWARE-UPDATE-QUBE-ESP32.git
cd FIRMWARE-UPDATE-QUBE-ESP32
```

Para trabajo nuevo → [`Qube v2/`](Qube v2/)
Para reproducir resultados v1 → [`Qube v1/`](Qube v1/)