# INFORME FINAL - R3 DRL (currículo de reset + recompensa estabilizadora)

- **Inicio:** 2026-06-19 01:19:05  |  **Fin:** 2026-06-19 07:39:09
- **Tiempo total:** 6:20:03  (presupuesto: 6.0 h)
- **Experimentos completados:** 3/4  (presupuesto agotado)

Metrica de exito = **balance_rate** (episodios que mantienen el pendulo invertido-y-lento >=1 s). Benchmark R1/R2: **0 %**.

## Diagnostico Fase 0 (motivacion)

Incluso *colocada en el apice*, la politica `linear_alpha` cae en ~0.56 s (balance 0 %). `linear_alpha` no tiene termino de velocidad -> el cuello de botella es la **estabilizacion**, no la posicion inicial. R3 lo ataca con damping gateado + bono continuo, y currículo de reset.

## Parametros R3 (vs R2)

| Parametro | R2 | R3 |
|-----------|----|----|
| reward (primario) | `linear_alpha_balance` | `linear_alpha_stabilise` (nuevo) |
| currículo (near_upright_prob) | N/A | 0.4 |
| warm-start | N/A | config 04 (desde mejor R2) |
| gamma | 0.99* (declarado 0.995, no cableado) | cableado correctamente |
| buffer_size | 500,000 | 500,000 |
| net_arch | [64, 64] | [64, 64] (ESP32 fijo) |

## Ranking de configuraciones (por balance, luego hold, luego upright)

| # | Experimento | reward | currículo | warm | balance % | reach % | upright % | hold max (s) | ep_rew |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 03_linear_alpha_curriculum | `linear_alpha` | 0.4 | False | 0.0+/-0.0 | 100 | 30.4 | 0.92 | 391.01 |
| 2 | 02_linear_alpha_control | `linear_alpha` | 0.0 | False | 0.0+/-0.0 | 100 | 4.2 | 0.50 | 317.72 |
| 3 | 01_stabilise_curriculum | `linear_alpha_stabilise` | 0.4 | False | 0.0+/-0.0 | 0 | 0.0 | 0.00 | -22.88 |

## Conclusiones

- **Mejor configuracion:** `03_linear_alpha_curriculum` (reward=`linear_alpha`). balance **0.0%**, reach 100%, upright 30.4%, hold max 0.92 s.
- **Balance sigue en 0%.** Priorizar el fallback hibrido (RL swing-up -> LQR modo 4 del firmware).

## Como inspeccionar

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r3_curriculum
```

Reportes por experimento: `experiments/2026-06-18_r3_curriculum/report_*.md`.
