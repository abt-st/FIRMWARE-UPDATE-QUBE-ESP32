# Reporte de experimento — 04_swingup_balance_pbrs

- **Fecha:** 2026-06-18 07:01:01
- **Recompensa:** `swingup_balance`  |  **PBRS:** `upright`
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 150000
- **Progreso:** experimento 4/6  |  **Tiempo total transcurrido:** 4:14:17

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.74 | 89 | 28.2 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.72 | 89 | 28.1 |

## Agregado (media ± std)

- **balance_rate:** 0.0% ± 0.0%  (fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)
- **reach_rate:** 0.0% ± 0.0%
- **upright_fraction:** 0.0% ± 0.0%
- **hold máximo (mejor semilla):** 0.00 s
- **ep_rew_mean:** -1.73 ± 0.01

## Análisis automático

❌ **No resuelve el swing-up** con este presupuesto de pasos.

> Modelos: `models/qube_overnight_04_swingup_balance_pbrs_s*.zip`  |  MLflow exp: `qube_overnight`