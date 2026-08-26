# Reporte de experimento — 01_swingup_balance_base

- **Fecha:** 2026-06-18 04:00:21
- **Recompensa:** `swingup_balance`  |  **PBRS:** `None`
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 150000
- **Progreso:** experimento 1/6  |  **Tiempo total transcurrido:** 1:13:38

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.71 | 67 | 37.4 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.73 | 69 | 36.1 |

## Agregado (media ± std)

- **balance_rate:** 0.0% ± 0.0%  (fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)
- **reach_rate:** 0.0% ± 0.0%
- **upright_fraction:** 0.0% ± 0.0%
- **hold máximo (mejor semilla):** 0.00 s
- **ep_rew_mean:** -1.72 ± 0.01

## Análisis automático

❌ **No resuelve el swing-up** con este presupuesto de pasos.

> Modelos: `models/qube_overnight_01_swingup_balance_base_s*.zip`  |  MLflow exp: `qube_overnight`