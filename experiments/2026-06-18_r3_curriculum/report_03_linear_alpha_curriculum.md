# Reporte de experimento - 03_linear_alpha_curriculum

- **Fecha:** 2026-06-19 07:39:09
- **Recompensa:** `linear_alpha`  |  **PBRS:** `None`  |  **near_upright_prob:** 0.4  |  **warm-start:** False
- **Semillas:** [0]  |  **Timesteps/semilla:** 300,000
- **Progreso:** experimento 3/4  |  **Tiempo total:** 6:20:03

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 30.4 | 0.38 | 0.92 | 391.01 | 92 | 54.5 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 100.0% +/- 0.0%
- **upright_fraction:** 30.4% +/- 0.0%
- **hold max (mejor semilla):** 0.92 s
- **ep_rew_mean:** 391.01 +/- 0.00

## Analisis automatico

**Muy cerca del balance.** Hold max 0.92s - subir steps o tunear bono.

> Modelos: `experiments/2026-06-18_r3_curriculum/models/r3_03_linear_alpha_curriculum_s*.zip`  |  MLflow exp: `qube_r3_curriculum`