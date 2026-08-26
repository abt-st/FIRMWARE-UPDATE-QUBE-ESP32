# R7 — Reproduce R6 balance, keep best checkpoint

**Updated:** 2026-06-24 11:26:38 · reward=linear_alpha · theta=±100° · net=[64,64]

Baseline (audit_eval.py): mejor previo = **R6 s0 step400k = 93.3% balance** (el final 500k cayó a 40%).
Cada run reporta su **mejor checkpoint** (no el final), defensa contra la degradación de late-training.
`balance` = fracción de episodios que sostuvieron el invertido (lento) ≥1 s.

| Run | curric | seed | best@step | balance% | upright% | hold_best(s) | reach% | apex% | min |
|-----|--------|------|-----------|----------|----------|--------------|--------|-------|-----|
| cur0.3_s0 | 0.3 | 0 | 300000 | 90 | 84 | 9.34 | 100 | 95 | 89 |
| cur0.3_s1 | 0.3 | 1 | 400000 | 65 | 78 | 8.90 | 100 | 65 | 87 |
| cur0.3_s2 | 0.3 | 2 | 400000 | 57 | 75 | 8.76 | 100 | 53 | 86 |
| cur0.3_s3 | 0.3 | 3 | 450000 | 0 | 1 | 0.40 | 100 | 0 | 83 |
| cur0.4_s0 | 0.4 | 0 | 400000 | 5 | 53 | 1.56 | 100 | 0 | 87 |
| cur0.4_s1 | 0.4 | 1 | 350000 | 0 | 55 | 0.66 | 100 | 0 | 87 |
| cur0.4_s2 | 0.4 | 2 | 450000 | 13 | 45 | 8.24 | 100 | 3 | 83 |
| cur0.4_s3 | 0.4 | 3 | 450000 | 0 | 14 | 0.40 | 100 | 0 | 83 |
| cur0.5_s0 | 0.5 | 0 | 350000 | 90 | 85 | 8.98 | 100 | 80 | 87 |
| cur0.5_s1 | 0.5 | 1 | 200000 | 27 | 30 | 1.42 | 100 | 20 | 84 |
| cur0.5_s2 | 0.5 | 2 | 350000 | 97 | 83 | 9.30 | 100 | 80 | 83 |
| cur0.5_s3 | 0.5 | 3 | 300000 | 40 | 76 | 9.38 | 100 | 47 | 83 |

## Mejor candidato global (por balance, desempate hold_best)

- **`cur0.5_s2`** @ step 350000 — balance=97%, hold_best=9.30s, upright=83%
- Modelo: `C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE\experiments\2026-06-23_r7_curriculum_sweep\models\r7_cur0.5_s2_best.zip`

Desplegar: `python -m qube_rl.export_rltools --model <zip> --output src/firmware/esp32_qube/policy_weights.h` → verificar fwd vs predict → flashear → modo 7.