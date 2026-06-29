# R7 — Re-evaluación de finalistas a 100 episodios

**Updated:** 2026-06-24 11:48:51 · reward=linear_alpha · theta=±100° · control_freq=50 · n_ep=100

Re-medición de alta precisión de los `r7_*_best.zip` (el sweep los eligió con 20-30 ep; esto los confirma con muchos más). Ordenado por balance estándar.

| Modelo | balance% | upright% | hold_avg(s) | hold_best(s) | reach% | apex% |
|--------|----------|----------|-------------|--------------|--------|-------|
| cur0.3_s0 | 95 | 85 | 6.63 | 9.28 | 100 | 88 |
| cur0.5_s2 | 90 | 83 | 5.85 | 9.18 | 100 | 93 |
| cur0.5_s0 | 89 | 80 | 4.86 | 9.36 | 99 | 89 |
| cur0.3_s2 | 62 | 74 | 3.97 | 9.20 | 100 | 64 |
| cur0.3_s1 | 59 | 75 | 3.57 | 9.30 | 98 | 63 |
| cur0.5_s3 | 54 | 79 | 3.09 | 9.18 | 100 | 52 |
| cur0.5_s1 | 29 | 30 | 0.66 | 1.46 | 100 | 13 |
| cur0.4_s2 | 8 | 43 | 0.66 | 8.10 | 100 | 8 |
| cur0.4_s0 | 2 | 50 | 0.41 | 1.10 | 100 | 5 |
| cur0.4_s3 | 0 | 14 | 0.17 | 0.62 | 100 | 0 |
| cur0.4_s1 | 0 | 56 | 0.28 | 0.54 | 100 | 0 |
| cur0.3_s3 | 0 | 1 | 0.03 | 0.26 | 100 | 0 |

## Ganador confirmado (mayor balance, desempate hold_best)

- **`cur0.3_s0`** — balance=95%, hold_best=9.28s, upright=85% (100 ep)
- Modelo: `C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE\experiments\2026-06-23_r7_curriculum_sweep\models\r7_cur0.3_s0_best.zip`

Desplegar: `python -m qube_rl.export_rltools --model <zip> --output src/firmware/esp32_qube/policy_weights.h` → verificar fwd vs predict → flashear → modo 7.