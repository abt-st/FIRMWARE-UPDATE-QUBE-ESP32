# Reporte de experimento - 01_linear_alpha_balance

- **Fecha:** 2026-06-18 14:01:16
- **Recompensa:** `linear_alpha_balance`  |  **PBRS:** `None`
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 200,000
- **Progreso:** experimento 1/3  |  **Tiempo total:** 1:55:10

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.34 | 87 | 38.5 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.38 | 87 | 38.1 |
| 2 | 0 | 0 | 0.0 | 0.00 | 0.00 | -1.52 | 87 | 38.4 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 0.0% +/- 0.0%
- **upright_fraction:** 0.0% +/- 0.0%
- **hold max (mejor semilla):** 0.00 s
- **ep_rew_mean:** -1.41 +/- 0.08

## Analisis automatico

**No resuelve el swing-up** con este presupuesto de pasos.

> Modelos: `experiments/2026-06-18_r2_balance/models/r2_01_linear_alpha_balance_s*.zip`  |  MLflow exp: `qube_r2_balance`