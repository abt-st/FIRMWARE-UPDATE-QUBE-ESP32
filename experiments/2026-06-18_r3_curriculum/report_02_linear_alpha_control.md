# Reporte de experimento - 02_linear_alpha_control

- **Fecha:** 2026-06-19 06:44:20
- **Recompensa:** `linear_alpha`  |  **PBRS:** `None`  |  **near_upright_prob:** 0.0  |  **warm-start:** False
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 300,000
- **Progreso:** experimento 2/4  |  **Tiempo total:** 5:25:15

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold max (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 0.2 | 0.01 | 0.18 | 297.98 | 60 | 82.7 |
| 1 | 0 | 100 | 8.3 | 0.17 | 0.82 | 337.46 | 67 | 75.0 |

## Agregado (media +/- std)

- **balance_rate:** 0.0% +/- 0.0%
- **reach_rate:** 100.0% +/- 0.0%
- **upright_fraction:** 4.2% +/- 4.0%
- **hold max (mejor semilla):** 0.50 s
- **ep_rew_mean:** 317.72 +/- 19.74

## Analisis automatico

**Llega arriba pero no se queda.** Swing-up funciona; falta la transicion a balance.

> Modelos: `experiments/2026-06-18_r3_curriculum/models/r3_02_linear_alpha_control_s*.zip`  |  MLflow exp: `qube_r3_curriculum`