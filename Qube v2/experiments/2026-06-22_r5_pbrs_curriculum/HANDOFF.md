# HANDOFF DE EMERGENCIA — R4 + R5 en paralelo (QUBE swing-up + balance DRL)

**Escrito:** 2026-06-22 ~02:47  ·  **Branch:** `DRL_IMP`  ·  Máquina: 4 cores físicos, sin CUDA usable (GPU = GTX 1050 2 GB, torch es build `+cpu`).

## TL;DR
Hay **dos entrenamientos SAC corriendo en paralelo** (R4 y R5). OneDrive está **pausado** y la UI de MLflow **apagada** para liberar CPU/disco. Solo hay que **esperar** a que terminen (ambos con `ALL DONE` en su log). Si algo se cae, abajo están los comandos exactos para relanzar y para leer el progreso.

---

## 1. Qué está corriendo AHORA

| | **R4** (confirmación) | **R5** (nuevas ideas) |
|---|---|---|
| Script | `experiments/2026-06-19_r4_curriculum/run_r4.py` | `experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py` |
| Comando | `--budget-hours 10 --timesteps 500000 --seeds 0 1 2` | `--budget-hours 10 --timesteps 500000 --seeds 0 1 2 --mlflow-uri sqlite:///mlflow_r5.db` |
| Reward / lever | `linear_alpha` + `near_upright_prob=0.4` | apex-gated reward + energy PBRS + currículo recocido (3 experimentos) |
| MLflow DB | `mlflow.db` (exp `qube_r4_curriculum`) | `mlflow_r5.db` (exp `qube_r5_pbrs_curriculum`) |
| Log vivo | `experiments/2026-06-19_r4_curriculum/run_r4_2026-06-22.log` | `experiments/2026-06-22_r5_pbrs_curriculum/run_r5_2026-06-22.log` |
| Modelos | `experiments/2026-06-19_r4_curriculum/models/r3_*_s*.zip` | `experiments/2026-06-22_r5_pbrs_curriculum/models/r5_*_s*.zip` |
| Deadline presupuesto | ~10:43 (lanzado 00:43:34) | ~12:45 (lanzado 02:45:38) |

- **Config fija ambos:** SAC `[64,64]` (ESP32), buffer 500k, γ=0.995, gSDE on.
- **PIDs al escribir** (cambian si se relanzan): R4 winpid 21852, R5 winpid 5760. **No te fíes del PID**; identifica por línea de comando (`run_r4.py` / `run_r5.py`).
- **Snapshot 02:47:** R4 ~263k/500k (~53 %, fps ~69). R5 ~3k/500k (arrancando, fps ~56).

> ⚠️ NO lanzar un tercer entrenamiento en paralelo. Dos llenan los 4 cores; un tercero los haría competir y RAM podría apretar.

---

## 2. Cómo ver el progreso (sin UI de MLflow)

Lectura **solo-lectura** del/los `mlflow*.db` (no interfiere con el writer):

```bash
cd "C:/Users/Anton/OneDrive/Desktop/Uni/~TESIS/QUBE"
.venv/Scripts/python.exe -c "
import sqlite3
def fps(db, exp):
    con=sqlite3.connect(f'file:{db}?mode=ro&immutable=1',uri=True,timeout=2); cur=con.cursor()
    cur.execute('SELECT r.run_uuid FROM runs r JOIN experiments e ON r.experiment_id=e.experiment_id WHERE e.name=? AND r.status=\"RUNNING\" ORDER BY r.start_time DESC LIMIT 1',(exp,))
    row=cur.fetchone()
    if not row: print(exp,'sin run RUNNING'); return
    cur.execute('SELECT step,MIN(timestamp) FROM metrics WHERE run_uuid=? GROUP BY step ORDER BY step',(row[0],))
    p=cur.fetchall(); con.close()
    w=p[-15:]; rec=(w[-1][0]-w[0][0])/((w[-1][1]-w[0][1])/1000) if len(w)>1 and w[-1][1]>w[0][1] else 0
    print(f'{exp}: paso {p[-1][0]:,}/500,000  fps {rec:.1f}')
fps('mlflow.db','qube_r4_curriculum'); fps('mlflow_r5.db','qube_r5_pbrs_curriculum')
"
```

Estado por log (cada seed escribe `done ...: balance=X%`):
```bash
tail -5 experiments/2026-06-19_r4_curriculum/run_r4_2026-06-22.log
tail -5 experiments/2026-06-22_r5_pbrs_curriculum/run_r5_2026-06-22.log
```
**Terminado** = la línea `ALL DONE. Final report: ...` aparece en el log.

---

## 3. EMERGENCIAS — qué hacer si algo falla

### A) Un run murió (proceso desaparecido y el log NO dice `ALL DONE`)
La causa histórica fue **cerrar la sesión que lo lanzó** o **suspensión del PC**. Relanzar (siguen siendo idempotentes; sobrescriben reportes/modelos del run):
```bash
cd "C:/Users/Anton/OneDrive/Desktop/Uni/~TESIS/QUBE"
# R4:
nohup .venv/Scripts/python.exe experiments/2026-06-19_r4_curriculum/run_r4.py \
  --budget-hours 10 --timesteps 500000 --seeds 0 1 2 \
  > experiments/2026-06-19_r4_curriculum/run_r4_2026-06-22b.log 2>&1 &
# R5:
nohup .venv/Scripts/python.exe experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py \
  --budget-hours 10 --timesteps 500000 --seeds 0 1 2 --mlflow-uri sqlite:///mlflow_r5.db \
  > experiments/2026-06-22_r5_pbrs_curriculum/run_r5_2026-06-22b.log 2>&1 &
```
> No hay warm-start ni checkpoints intermedios: relanzar **reinicia ese run desde 0**. Los seeds ya completados (con su `done` en el log y su `.zip`) no se pierden, pero el script reentrena toda la matriz salvo que edites `--seeds`/`EXPERIMENTS`.

### B) El PC se reinició / suspendió
Ambos runs mueren. Relanza con los comandos de (A). Verifica primero que no quedaron procesos zombi: `ps -W | grep python`.

### C) `database is locked` en algún run
No debería pasar (R4→`mlflow.db`, R5→`mlflow_r5.db`, separadas). Si pasa, relanza ese run con `--no-mlflow` (entrena igual, sin tracking) o con otra `--mlflow-uri`.

### D) Verificar que un proceso es R4 o R5 (PowerShell)
```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
  Where-Object { $_.CommandLine -like '*run_r*.py*' } |
  Select-Object ProcessId,CommandLine
```

### E) Reanudar servicios pausados
- **OneDrive:** ábrelo desde el menú Inicio (busca "OneDrive"). Estaba detenido para liberar CPU/disco; los archivos locales siguen intactos.
- **MLflow UI** (opcional): `nohup .venv/Scripts/python.exe -m mlflow ui --backend-store-uri sqlite:///mlflow.db --host 127.0.0.1 --port 5000 > experiments/mlflow_ui.log 2>&1 &` (para R5 usar `--port 5001 --backend-store-uri sqlite:///mlflow_r5.db`). **Ojo:** la UI consume CPU y ralentiza los entrenamientos; apágala mientras corren (mata los `python.exe` cuya línea de comando o cuyos workers `uvicorn`/`spawn` sirven el puerto — ver §3.F).

### F) Apagar la UI de MLflow del todo
Los workers de uvicorn NO llevan "mlflow" en su línea de comando (son procesos `spawn`, hijos del master). Mata por puerto:
```powershell
$o = (Get-NetTCPConnection -LocalPort 5000 -ErrorAction SilentlyContinue).OwningProcess
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.ParentProcessId -in $o -or $_.ProcessId -in $o } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

---

## 4. Cuando AMBOS terminen — cómo leer resultados

```bash
cat experiments/2026-06-19_r4_curriculum/FINAL_REPORT.md   # R4
cat experiments/2026-06-22_r5_pbrs_curriculum/FINAL_REPORT.md  # R5
# reportes por-seed: report_*.md en cada carpeta
```
**Métrica de éxito = `balance_rate`** (péndulo invertido ≤12° y lento ≤1 rad/s durante ≥1 s continuo). Histórico R1–R4: **0 %**; mejor `hold_max` previo = 0.92 s (R3 config 03).

> ⚠️ No leas el `FINAL_REPORT.md`/`report_*.md` como definitivo hasta que el log diga `ALL DONE`. Antes de eso pueden traer datos parciales o de smoke test.

---

## 5. Árbol de decisión para el siguiente run (post R4+R5)

| Resultado (mejor config, 3 seeds) | Acción |
|---|---|
| **balance > 0 %** | 🎉 Roto por primera vez. Subir a 1M steps multi-seed → export ESP32 (`export_rltools.py`) + A/B vs híbrido LQR. |
| **balance 0 %, hold ≥ 0.95 s** | Punto dulce: ensanchar levemente el gate del apex (0.52→0.7 rad) o el bono, o subir a 1M steps. |
| **R5 apex pierde reach (<50 %)** | El gate aún molesta al swing-up: subir `APEX_GATE` más cerca del ápice / bajar damping en `rewards.py::linear_alpha_apex_stabilise`. |
| **PBRS energy no aporta** | Esperado (PBRS es policy-invariante: acelera, no cambia el óptimo). El driver del balance es el reward apex, no el PBRS. |
| **se estanca < 0.9 s en todo** | Activar fallback híbrido: RL swing-up → **LQR modo 4** del firmware (`esp32_qube.ino`). |

Detalle completo de métodos y casos sim2real: `docs/research/METODOS_ALTERNATIVOS_RL_BALANCE.md`.

---

## 6. Contexto / deuda técnica
- **Swing-up resuelto** (`linear_alpha`, 100 % reach). El problema abierto es el **balance sostenido ≥1 s**.
- **Penalización de velocidad global mata el swing-up** (R2/R3). R5 lo corrige con damping gateado a ~30° del ápice.
- **Domain randomization YA activo** (`QubeDynamics.randomize()` por reset). gSDE y 50 Hz también — coinciden con la receta sim2real ganadora (EBERL / Furuta real).
- Bug LR warm-start sin corregir (`model.learning_rate=lr` tras `SAC.load` no actualiza `lr_schedule`). No afecta a R4/R5 (no usan warm-start).
- Prefijo de modelos `r3_` en R4 es cosmético (heredado del script base). R5 usa `r5_`.
- Memoria persistente: `memory/qube-r5-pipeline-2026-06-22.md` (índice en `memory/MEMORY.md`).
