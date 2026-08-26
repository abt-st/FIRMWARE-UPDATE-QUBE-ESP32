# Reporte de experimento - 03_cos_alpha_historical

- **Fecha:** 2026-06-18 17:58:17
- **Recompensa:** `cos_alpha`  |  **PBRS:** `None`
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 200,000
- **Progreso:** experimento 3/3  |  **Tiempo total:** 5:52:12

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 0.0 | 0.00 | 0.00 | 295.95 | 85 | 39.2 |
| 1 | 0 | 100 | 4.7 | 0.08 | 0.28 | 341.30 | 87 | 38.4 |
| 2 | 0 | 100 | 7.0 | 0.09 | 0.42 | 343.67 | 87 | 38.3 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 100.0% +/- 0.0%
- **upright_fraction:** 3.9% +/- 2.9%
- **hold max (mejor semilla):** 0.23 s
- **ep_rew_mean:** 326.97 +/- 21.96

## Analisis automatico

**Llega arriba pero no se queda.** Swing-up funciona; falta la transicion a balance.

> Modelos: `experiments/2026-06-18_r2_balance/models/r2_03_cos_alpha_historical_s*.zip`  |  MLflow exp: `qube_r2_balance`