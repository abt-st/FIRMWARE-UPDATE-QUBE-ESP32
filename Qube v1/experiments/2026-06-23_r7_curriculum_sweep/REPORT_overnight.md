# Overnight friction-adaptation sweep — fine-tune R7 to real friction

**Updated:** 2026-06-25 06:45:36 · base=r7_cur0.3_s0_best · reward=linear_alpha · theta=±100° · net=[64,64]

Fine-tune the deployed R7 (95% in normal-friction sim) at higher friction matching the real rig. Each run keeps its **best checkpoint** (by balance, then hold), evaluated at the MATCHED friction. `balance` = fraction of episodes holding inverted ≥1 s.

| Run | friction× | seed | best@step | balance% | upright% | hold_best(s) | reach% | min |
|-----|-----------|------|-----------|----------|----------|--------------|--------|-----|
| fr20_s0 | 20 | 0 | 180000 | 65 | 67 | 9.28 | 100 | 31 |
| fr20_s1 | 20 | 1 | 345000 | 70 | 78 | 9.28 | 100 | 31 |
| fr40_s0 | 40 | 0 | 480000 | 50 | 61 | 9.22 | 95 | 31 |
| fr40_s1 | 40 | 1 | 480000 | 50 | 64 | 9.18 | 100 | 31 |
| fr70_s0 | 70 | 0 | 180000 | 80 | 76 | 9.46 | 95 | 31 |
| fr70_s1 | 70 | 1 | 435000 | 30 | 58 | 8.84 | 100 | 31 |
| fr100_s0 | 100 | 0 | 435000 | 70 | 72 | 9.32 | 100 | 31 |
| fr100_s1 | 100 | 1 | 345000 | 25 | 55 | 9.24 | 95 | 31 |

## Mejor candidato global (por balance @ fricción matcheada)

- **`fr70_s0`** (friction×70) @ step 180000 — balance=80%, hold_best=9.46s, upright=76%
- Modelo: `C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE\experiments\2026-06-23_r7_curriculum_sweep\models\r7_ft_fr70_s0_best.zip`

Desplegar: `python -m qube_rl.export_rltools --model <zip> --output src/firmware/esp32_qube/policy_weights.h` → verify_export.py → flashear → modo 7.