# Reporte de experimento — 05_linear_alpha_dense

- **Fecha:** 2026-06-18 07:57:59
- **Recompensa:** `linear_alpha_dense`  |  **PBRS:** `None`
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 150000
- **Progreso:** experimento 5/6  |  **Tiempo total transcurrido:** 5:11:16

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 0 | 0.0 | 0.00 | 0.00 | 150.98 | 88 | 28.5 |
| 1 | 0 | 0 | 0.0 | 0.00 | 0.00 | 6.25 | 89 | 28.2 |

## Agregado (media ± std)

- **balance_rate:** 0.0% ± 0.0%  (fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)
- **reach_rate:** 0.0% ± 0.0%
- **upright_fraction:** 0.0% ± 0.0%
- **hold máximo (mejor semilla):** 0.00 s
- **ep_rew_mean:** 78.62 ± 72.37

## Análisis automático

❌ **No resuelve el swing-up** con este presupuesto de pasos.

> Modelos: `models/qube_overnight_05_linear_alpha_dense_s*.zip`  |  MLflow exp: `qube_overnight`