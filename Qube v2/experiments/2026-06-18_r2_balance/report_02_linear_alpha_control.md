# Reporte de experimento - 02_linear_alpha_control

- **Fecha:** 2026-06-18 16:01:32
- **Recompensa:** `linear_alpha`  |  **PBRS:** `None`
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 200,000
- **Progreso:** experimento 2/3  |  **Tiempo total:** 3:55:27

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 2.2 | 0.06 | 0.58 | 321.60 | 84 | 39.8 |
| 1 | 0 | 100 | 28.0 | 0.28 | 0.56 | 371.92 | 83 | 40.2 |
| 2 | 0 | 100 | 9.7 | 0.25 | 0.74 | 333.01 | 85 | 39.4 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 100.0% +/- 0.0%
- **upright_fraction:** 13.3% +/- 10.8%
- **hold max (mejor semilla):** 0.63 s
- **ep_rew_mean:** 342.18 +/- 21.54

## Analisis automatico

**Cerca del balance.** Hold max 0.63s - necesita mas steps o ajuste.

> Modelos: `experiments/2026-06-18_r2_balance/models/r2_02_linear_alpha_control_s*.zip`  |  MLflow exp: `qube_r2_balance`