# Reporte de experimento - 01_curriculum04

- **Fecha:** 2026-06-22 08:19:15
- **Recompensa:** `linear_alpha`  |  **PBRS:** `None`  |  **near_upright_prob:** 0.4  |  **warm-start:** False
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 500,000
- **Progreso:** experimento 1/2  |  **Tiempo total:** 7:35:41

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 63.6 | 0.33 | 0.72 | 471.54 | 44 | 187.3 |
| 1 | 93 | 100 | 84.0 | 4.43 | 8.98 | 479.85 | 62 | 133.7 |
| 2 | 60 | 100 | 70.5 | 3.44 | 9.14 | 474.02 | 63 | 133.2 |

## Agregado (media +/- std)

- **balance_rate:** 51.1% +/- 38.6%
- **reach_rate:** 100.0% +/- 0.0%
- **upright_fraction:** 72.7% +/- 8.5%
- **hold max (mejor semilla):** 6.28 s
- **ep_rew_mean:** 475.14 +/- 3.49

## Analisis automatico

**Balance logrado:** 51.1% de episodios balancean >=1s.

> Modelos: `experiments/2026-06-18_r3_curriculum/models/r3_01_curriculum04_s*.zip`  |  MLflow exp: `qube_r4_curriculum`