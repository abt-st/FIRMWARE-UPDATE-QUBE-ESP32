# INFORME FINAL - R2 Entrenamiento DRL (QUBE swing-up/balance)

- **Inicio:** 2026-06-18 12:06:05  |  **Fin:** 2026-06-18 17:58:17
- **Tiempo total:** 5:52:12  (presupuesto: 6.5 h)
- **Experimentos completados:** 3/3  

Metrica de exito = **balance_rate** (fraccion de episodios que mantienen el pendulo invertido-y-lento >=1 s).
El benchmark de R1 era **0% de balance**.

## Parametros R2 (vs R1)

| Parametro | R1 (overnight) | R2 (actual) |
|-----------|---------------|-------------|
| reward | `linear_alpha` | `linear_alpha_balance` (nuevo) |
| timesteps/seed | 150,000 | 200,000 |
| buffer_size | 200,000 | 500,000 |
| gamma | 0.99 | 0.995 |
| net_arch | [64, 64] | [64, 64] (ESP32 fijo) |

## Ranking de configuraciones (por balance, luego upright, luego reach)

| # | Experimento | reward | balance % | reach % | upright % | hold max (s) | ep_rew |
|---|---|---|---|---|---|---|---|
| 1 | 01_linear_alpha_balance | `linear_alpha_balance` | 0.0+/-0.0 | 0+/-0 | 0.0 | 0.00 | -1.41 |
| 2 | 02_linear_alpha_control | `linear_alpha` | 0.0+/-0.0 | 100+/-0 | 13.3 | 0.63 | 342.18 |
| 3 | 03_cos_alpha_historical | `cos_alpha` | 0.0+/-0.0 | 100+/-0 | 3.9 | 0.23 | 326.97 |

## Conclusiones

- **Mejor configuracion:** `01_linear_alpha_balance` (reward=`linear_alpha_balance`). balance **0.0%** +/- 0.0%, reach 0%, upright 0.0%, hold max 0.00 s.
- **Balance sigue en 0%.** Siguientes pasos: mas timesteps (500k), curriculo (reset cerca del invertido), o RL residual sobre LQR.

## Como inspeccionar

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r2_balance
```

Reportes por experimento: `experiments/2026-06-18_r2_balance/report_*.md`.
