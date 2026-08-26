# Reporte de experimento - 01_apex_anneal

- **Fecha:** 2026-06-22 09:27:48
- **Recompensa:** `linear_alpha_apex_stabilise`  |  **PBRS:** `None`  |  **energy_weight:** 0.0  |  **near_upright_prob:** 0.6 -> 0.2 (anneal 0.7)
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 500,000
- **Progreso:** experimento 1/3  |  **Tiempo total:** 6:42:10

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | 18.80 | 62 | 135.0 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | 349.12 | 63 | 133.1 |
| 2 | 0 | 0 | 0.0 | 0.00 | 0.00 | -6.71 | 62 | 133.9 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 0.0% +/- 0.0%
- **upright_fraction:** 0.0% +/- 0.0%
- **hold max (mejor semilla):** 0.00 s
- **ep_rew_mean:** 120.41 +/- 162.06

## Analisis automatico

**No resuelve el swing-up** con este presupuesto de pasos (revisar gate/damping).

> Modelos: `2026-06-22_r5_pbrs_curriculum/models/r5_01_apex_anneal_s*.zip`  |  MLflow exp: `qube_r5_pbrs_curriculum`