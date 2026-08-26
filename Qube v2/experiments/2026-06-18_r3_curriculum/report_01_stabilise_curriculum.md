# Reporte de experimento - 01_stabilise_curriculum

- **Fecha:** 2026-06-19 04:06:01
- **Recompensa:** `linear_alpha_stabilise`  |  **PBRS:** `None`  |  **near_upright_prob:** 0.4  |  **warm-start:** False
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 300,000
- **Progreso:** experimento 1/4  |  **Tiempo total:** 2:46:56

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | -59.26 | 60 | 83.8 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | 13.51 | 60 | 83.0 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 0.0% +/- 0.0%
- **upright_fraction:** 0.0% +/- 0.0%
- **hold max (mejor semilla):** 0.00 s
- **ep_rew_mean:** -22.88 +/- 36.39

## Analisis automatico

**No resuelve el swing-up** con este presupuesto de pasos.

> Modelos: `experiments/2026-06-18_r3_curriculum/models/r3_01_stabilise_curriculum_s*.zip`  |  MLflow exp: `qube_r3_curriculum`