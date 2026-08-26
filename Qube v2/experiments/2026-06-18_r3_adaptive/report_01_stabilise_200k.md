# Reporte de experimento - 01_stabilise_200k

- **Fecha:** 2026-06-19 01:51:33
- **Recompensa:** `linear_alpha_stabilise`  |  **PBRS:** `None`
- **Semillas:** [0, 1, 2]  |  **Timesteps/semilla:** 200,000
- **Progreso:** experimento 1/4  |  **Tiempo total:** 4:39:35

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | 1.64 | 31 | 107.8 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | 1.70 | 37 | 90.7 |
| 2 | 0 | 0 | 0.0 | 0.00 | 0.00 | 1.40 | 41 | 80.8 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 0.0% +/- 0.0%
- **upright_fraction:** 0.0% +/- 0.0%
- **hold max (mejor semilla):** 0.00 s
- **ep_rew_mean:** 1.58 +/- 0.13

## Analisis automatico

**No resuelve el swing-up.**

> Modelos: `experiments/2026-06-18_r3_adaptive/models/r3_01_stabilise_200k_s*.zip`  |  MLflow: `qube_r3_adaptive`