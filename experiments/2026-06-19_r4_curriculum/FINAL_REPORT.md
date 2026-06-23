# INFORME FINAL - R3 DRL (currículo de reset + recompensa estabilizadora)

- **Inicio:** 2026-06-22 00:43:34  |  **Fin:** 2026-06-22 08:19:15
- **Tiempo total:** 7:35:41  (presupuesto: 10.0 h)
- **Experimentos completados:** 1/2  

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
| 1 | 01_curriculum04 | `linear_alpha` | 0.4 | False | 51.1+/-38.6 | 100 | 72.7 | 6.28 | 475.14 |

## Conclusiones

- **Mejor configuracion:** `01_curriculum04` (reward=`linear_alpha`). balance **51.1%**, reach 100%, upright 72.7%, hold max 6.28 s.
- **Objetivo R3 alcanzado** (balance >=10 %). Siguiente: exportar a ESP32 + A/B vs hibrido LQR.

## Como inspeccionar

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r4_curriculum
```

Reportes por experimento: `experiments/2026-06-18_r3_curriculum/report_*.md`.
