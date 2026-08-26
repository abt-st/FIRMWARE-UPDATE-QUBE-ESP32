# INFORME FINAL - R3 Entrenamiento DRL (QUBE swing-up/balance)

- **Inicio:** 2026-06-18 21:11:58  |  **Fin:** 2026-06-19 06:28:07
- **Tiempo total:** 9:16:09  (presupuesto: 7.0 h)
- **Experimentos completados:** 2/4  (presupuesto agotado)

Metrica de exito = **balance_rate** (>=1s hold).
Benchmark R1: 0% balance. R2: 0% balance (velocity penalty killed swing-up).

## Ranking (por balance, luego upright, luego reach)

| # | Experimento | reward | timesteps | balance % | reach % | upright % | hold max (s) | ep_rew |
|---|---|---|---|---|---|---|---|---|
| 1 | 01_stabilise_200k | `linear_alpha_stabilise` | 200,000 | 0.0+/-0.0 | 0+/-0 | 0.0 | 0.00 | 1.58 |
| 2 | 02_stabilise_500k | `linear_alpha_stabilise` | 500,000 | 0.0+/-0.0 | 0+/-0 | 0.0 | 0.00 | 1.87 |

## Conclusiones

- **Mejor:** `01_stabilise_200k` (linear_alpha_stabilise). balance **0.0%**, reach 0%, upright 0.0%, hold max 0.00s.
- **Swing-up degradado.** Revisar penalizacion de velocidad.

## Inspeccion

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r3_adaptive
```
