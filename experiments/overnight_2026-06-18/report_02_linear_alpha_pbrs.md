# Reporte de experimento — 02_linear_alpha_pbrs

- **Fecha:** 2026-06-18 05:07:14
- **Recompensa:** `linear_alpha`  |  **PBRS:** `upright`
- **Semillas:** [0, 1]  |  **Timesteps/semilla:** 150000
- **Progreso:** experimento 2/6  |  **Tiempo total transcurrido:** 2:20:31

## Resultados por semilla

| Semilla | balance % | reach % | upright % | hold prom (s) | hold máx (s) | ep_rew | fps | min |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 100 | 0.2 | 0.01 | 0.08 | 298.60 | 69 | 36.3 |
| 1 | 0 | 100 | 4.7 | 0.08 | 0.16 | 322.00 | 84 | 29.9 |

## Agregado (media ± std)

- **balance_rate:** 0.0% ± 0.0%  (fracción de episodios que mantienen invertido-y-lento ≥1 s — éxito real)
- **reach_rate:** 100.0% ± 0.0%
- **upright_fraction:** 2.4% ± 2.3%
- **hold máximo (mejor semilla):** 0.12 s
- **ep_rew_mean:** 310.30 ± 11.70

## Análisis automático

⚠️ **Llega arriba pero no se queda.** El swing-up funciona; falta la transición a balance (más pasos / mejor reward / currículo).

> Modelos: `models/qube_overnight_02_linear_alpha_pbrs_s*.zip`  |  MLflow exp: `qube_overnight`