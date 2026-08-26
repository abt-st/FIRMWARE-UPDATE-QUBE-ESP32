# Reporte de experimento — 03_linear_alpha_base

- **Fecha:** 2026-06-18 06:04:41
- **Recompensa:** `linear_alpha`  |  **PBRS:** `None`
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 150000
- **Progreso:** experimento 3/6  |  **Tiempo total transcurrido:** 3:17:58

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 1.2 | 0.06 | 0.32 | 306.73 | 88 | 28.4 |
| 1 | 0 | 100 | 5.8 | 0.12 | 0.66 | 330.91 | 88 | 28.4 |

## Agregado (media ± std)

- **balance_rate:** 0.0% ± 0.0%  (fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)
- **reach_rate:** 100.0% ± 0.0%
- **upright_fraction:** 3.5% ± 2.3%
- **hold máximo (mejor semilla):** 0.49 s
- **ep_rew_mean:** 318.82 ± 12.09

## Análisis automático

⚠️ **Llega arriba pero no se queda.** El swing-up funciona; falta la transición a balance (más pasos / mejor reward / currículo).

> Modelos: `models/qube_overnight_03_linear_alpha_base_s*.zip`  |  MLflow exp: `qube_overnight`