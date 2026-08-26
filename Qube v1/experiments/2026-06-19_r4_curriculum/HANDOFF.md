# HANDOFF — R4 currículo (QUBE swing-up + balance DRL)

**Escrito:** 2026-06-19 ~08:10  |  **Branch:** DRL_IMP

## TL;DR
Hay un entrenamiento **corriendo en segundo plano** (PID/ID de Claude `b8nziscfb`, deadline **14:02**).
Cuando vuelvas: lee los resultados (§3), aplica el árbol de decisión (§4), lanza el siguiente run.

---

## 1. Dónde estamos (contexto en una línea)
El swing-up está **resuelto** (`linear_alpha`, 100% reach). El problema abierto es el **balance sostenido ≥1s** (histórico: 0%). La noche del 18→19 demostró que:
- ❌ **Penalización de velocidad en la reward = mata el swing-up** (R2 `linear_alpha_balance` y R3 `linear_alpha_stabilise`, ambas 0% reach). Descartada.
- ⭐ **Currículo de reset (`near_upright_prob`) es la palanca ganadora.** R3 config 03 (`linear_alpha` + 0.4, 300k, 1 seed): **upright 30.4%, hold 0.92s** — mejor del proyecto, a 0.08s del umbral de 1s.

R4 dobla la apuesta en el currículo y abandona la reward con velocidad.

## 2. Qué está corriendo AHORA
- **Script:** `experiments/2026-06-19_r4_curriculum/run_r4.py`
- **Comando:** `--budget-hours 6 --timesteps 500000 --seeds 0 1 2`
- **Matriz:**
  - `01_curriculum04` — `linear_alpha` + `near_upright_prob=0.4`, 500k × 3 seeds (confirma R3 + más pasos)
  - `02_curriculum06` — `linear_alpha` + `near_upright_prob=0.6`, corre si sobra presupuesto
- **Config fija:** SAC `[64,64]` (ESP32), buffer 500k, γ=0.995
- **Log vivo:** `experiments/2026-06-19_r4_curriculum/run_r4_2026-06-19.log`
- **MLflow:** experimento `qube_r4_curriculum`

## 3. Cómo leer los resultados al volver
```bash
# Estado / progreso
cat experiments/2026-06-19_r4_curriculum/run_r4_2026-06-19.log | grep -E "done|report|Budget|ALL DONE"

# Resúmenes por run (tabla por-seed: balance/reach/upright/hold/ep_rew)
cat experiments/2026-06-19_r4_curriculum/report_01_curriculum04.md
cat experiments/2026-06-19_r4_curriculum/report_02_curriculum06.md
cat experiments/2026-06-19_r4_curriculum/FINAL_REPORT.md

# Dashboard
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # exp: qube_r4_curriculum
```
Modelos: `experiments/2026-06-19_r4_curriculum/models/r3_*_s*.zip` (prefijo `r3_` es cosmético, heredado del script base).

**Métrica clave = `balance_rate`** (péndulo invertido ≤12° y lento ≤1 rad/s durante ≥1s continuo). Histórico = 0%. Métrica de "casi": `max_hold_s` (mejor seed) y `upright_fraction`.

## 4. Árbol de decisión para el siguiente run
| Resultado R4 (config 0.4, agregado 3 seeds) | Acción siguiente |
|---|---|
| **balance > 0%** | 🎉 Roto por primera vez. Subir a 1M steps para robustez multi-seed → luego export a ESP32 (`export_rltools.py`) + A/B vs híbrido LQR. |
| **balance 0% pero hold ≥ 0.95s** | Punto dulce: término de velocidad **diminuto** (coef ~0.005, 1 orden bajo el 0.03 que falló) SOLO cerca del ápice, o subir steps a 1M. |
| **balance 0%, hold ~0.9s, 0.6 ≥ 0.4 en upright** | El currículo más agresivo ayuda: barrer `near_upright_prob` 0.6/0.8, 1M steps. |
| **se estanca < 0.9s en todos los seeds** | Activar fallback híbrido: RL hace swing-up → firmware conmuta a **LQR modo 4** al llegar arriba. Ver firmware `esp32_qube.ino`. |

## 5. Cómo lanzar el siguiente run (plantilla)
Editar `EXPERIMENTS` en un nuevo `run_r5.py` (copiar de `run_r4.py`, cambiar `MLFLOW_EXPERIMENT`), luego:
```bash
.venv/Scripts/python.exe experiments/<nueva_dir>/run_r5.py --budget-hours N --timesteps 1000000 --seeds 0 1 2
```

## 6. Deuda técnica / notas
- **Bug LR warm-start (sin corregir):** `model.learning_rate = lr` tras `SAC.load` NO actualiza `model.lr_schedule` → el override no surte efecto. Solo afectaba la config 04 de R3 (eliminada en R4). Corregir antes de volver a usar warm-start.
- Prefijo de modelos `r3_` en R4 es cosmético (no toqué la f-string heredada).
- Los `report_*.md` y `FINAL_REPORT.md` de R4 traen datos del **smoke test** hasta que cada experimento real termina y los sobreescribe — no leer como definitivos hasta ver el log "report written" con tiempos reales (>50 min/seed).

## 7. Memoria persistente actualizada
`memory/qube-r3-r4-balance-findings.md` (índice en `memory/MEMORY.md`) — resume estos hallazgos para futuras sesiones.
