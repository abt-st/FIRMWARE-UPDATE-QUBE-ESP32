# ¿Qube v1 o Qube v2?

Ambas carpetas contienen el mismo proyecto QUBE ESP32 en distintos puntos de evolución. Esta guía ayuda a elegir.

## Comparación rápida

| Aspecto | Qube v1 | Qube v2 |
|---|---|---|
| **Estado** | Estable, experimentos archivados (may–jul 2026) | Desarrollo activo |
| **App de escritorio** (`qube_app`) | No | Sí, con trazas 500 Hz y control en vivo |
| **Tests** | 12 tests (DAQ, RL, análisis) | 20+ tests (app, firmware contract, RL freshness) |
| **CI** | Ruff lint + format + pytest | + Qt headless + `--extra app` |
| **Experimentos** | 32 experimentos (may–jul 2026) | 50+ experimentos (incluye los de v1 + sweeps recientes) |
| **Cobertura de firmware** | Misma base compartida | Misma base + optimizaciones |
| **Scripts** | `finetune_measured.ps1`, `watch_then_reeval.ps1` | Los mismos + `QUBE App.cmd` |
| **Ref/doc** | Datasheets, papers | Datasheets, papers + `backup_l298n/` (histórico) |

## ¿Cuál usar?

| Si quieres… | Usa |
|---|---|
| Trabajar en el proyecto hoy | **Qube v2** |
| Reproducir resultados de junio–julio 2026 | **Qube v1** |
| Usar la app de escritorio | **Qube v2** |
| Experimentar con RL (modo 6 y 7) | Ambos (mismo `qube_rl`, mismo firmware) |
| Ejecutar CI local sin Qt | **Qube v1** (no instala PySide6) |

## Nota

Ambos comparten la misma base de firmware (`src/firmware/`) y paquete RL (`src/qube_rl/`).
v2 añade `src/qube_app/` (app de escritorio con PySide6) y `src/qube_daq/` (DAQ refinado).
Si trabajas principalmente desde la terminal, v1 es suficiente; si quieres interfaz gráfica
de escritorio, necesitas v2.