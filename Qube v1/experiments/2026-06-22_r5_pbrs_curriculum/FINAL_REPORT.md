# INFORME FINAL - R5 DRL (apex-gated reward + energy PBRS + currículo recocido)

- **Inicio:** 2026-06-22 02:45:38  |  **Fin:** 2026-06-22 09:27:48
- **Tiempo total:** 6:42:10  (presupuesto: 10.0 h)
- **Experimentos completados:** 1/3  

Metrica de exito = **balance_rate** (pendulo invertido <=12 deg y lento <=1 rad/s durante >=1 s continuo). Benchmark R1-R4: **0 %** (mejor hold 0.92 s).

## Hipotesis R5

- **Apex-gated reward:** damping gateado a ~30 deg del apice (no pi/2) -> hace del balance lento el optimo sin matar el swing-up.
- **Energy PBRS:** shaping policy-invariante hacia la variedad de energia del objetivo (EBERL/Astrom); no puede romper el swing-up por diseno.
- **Currículo recocido:** near_upright_prob 0.6 -> 0.2 (Florensa CoRL'17).

## Ranking de configuraciones (por balance, luego hold, luego upright)

| # | Experimento | reward | PBRS | currículo | balance % | reach % | upright % | hold max (s) | ep_rew |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 01_apex_anneal | `linear_alpha_apex_stabilise` | None | 0.6->0.2 | 0.0+/-0.0 | 0 | 0.0 | 0.00 | 120.41 |

## Conclusiones

- **Mejor configuracion:** `01_apex_anneal` (reward=`linear_alpha_apex_stabilise`, PBRS=None). balance **0.0%**, reach 0%, upright 0.0%, hold max 0.00 s.
- **Balance sigue en 0%.** Ver arbol de decision en docs/research/METODOS_ALTERNATIVOS_RL_BALANCE.md (fallback hibrido LQR).

## Como inspeccionar

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db  # experimento: qube_r5_pbrs_curriculum
```

Reportes por experimento: `2026-06-22_r5_pbrs_curriculum/report_*.md`.
