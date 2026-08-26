# Overnight friction sweep — re-evaluación de candidatos a 100 episodios

**Updated:** 2026-06-25 22:58:03 · reward=linear_alpha · theta=±100° · control_freq=50 · n_ep=100 · cada modelo @ su fricción matcheada

Re-medición de alta precisión de los `r7_ft_fr*_best.zip` (el sweep los eligió con 20 ep; esto los confirma con muchos más, a la MISMA fricción a la que se entrenaron). Ordenado por balance estándar.

| Modelo | fr× | seed | balance% | upright% | hold_avg(s) | hold_best(s) | reach% | apex% |
|--------|-----|------|----------|----------|-------------|--------------|--------|-------|
| fr100_s0 | 100 | 0 | 62 | 68 | 3.40 | 9.14 | 96 | 73 |
| fr70_s0 | 70 | 0 | 60 | 70 | 2.71 | 9.42 | 96 | 66 |
| fr40_s0 | 40 | 0 | 56 | 65 | 2.77 | 9.48 | 100 | 58 |
| fr20_s0 | 20 | 0 | 55 | 64 | 1.53 | 9.18 | 100 | 51 |
| fr40_s1 | 40 | 1 | 49 | 66 | 2.71 | 9.34 | 99 | 48 |
| fr20_s1 | 20 | 1 | 47 | 67 | 2.75 | 9.38 | 100 | 43 |
| fr70_s1 | 70 | 1 | 45 | 61 | 1.26 | 9.08 | 100 | 51 |
| fr100_s1 | 100 | 1 | 24 | 50 | 1.52 | 8.82 | 96 | 36 |

## Mejor candidato confirmado (mayor balance @ fricción matcheada, desempate hold_best)

- **`fr100_s0`** (friction×100, seed 0) — balance=62%, hold_best=9.14s, upright=68% (100 ep)
- Modelo: `C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE\experiments\2026-06-23_r7_curriculum_sweep\models\r7_ft_fr100_s0_best.zip`

Desplegar: `python -m qube_rl.export_rltools --model <zip> --output src/firmware/esp32_qube/policy_weights.h` → verify_export.py → flashear → modo 7.