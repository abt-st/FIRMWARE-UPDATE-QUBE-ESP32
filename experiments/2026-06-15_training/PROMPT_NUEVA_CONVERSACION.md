# Prompt para nueva conversación — DRL Training Autónomo (SOLO SIMULACIÓN)

Copia y pega esto como mensaje inicial en una nueva conversación:

---

## RESTRICCIÓN CRÍTICA

**NO USAR EL PÉNDULO FÍSICO.** Todo el entrenamiento es en SIMULACIÓN.
No flashees firmware, no te conectes al ESP32, no uses `QubeRealEnv`.
Solo usar `QubeSimEnv` (simulación analítica en PC).

Si el agente futuro sugiere usar hardware, RECHAZA. Solo simulación.

---

## Contexto

Soy el asistente del proyecto QUBE Servo ESP32 (`C:\Users\Anton\OneDrive\Desktop\Uni\~TESIS\QUBE`).
Hay un entrenamiento de Deep RL (SAC) corriendo o por correr. Mi tarea es monitorearlo cada 10 minutos, analizar convergencia, y ajustar si es necesario. **Solo simulación, nunca hardware.**

## Qué se implementó hoy

- `src/qube_rl/` — Paquete completo: entornos, wrappers, rewards, train, inference, finetune
- `src/qube_rl/auto_train.py` — Loop autónomo de 3 runs (50K + 50K + 100K steps)
- Firmware modo 6 (NO flashear, solo existe en código)
- MCP tools RL (NO usar durante entrenamiento)
- Tests: 46/46 pasan
- Handoff: `experiments/2026-06-15_training/HANDOFF.md`

## Resultados parciales (run1, step 12,756)

```
Step      Ep Len    Ep Len (s)   Reward
  214      53.5       1.07s       7.76
  598      74.8       1.50s       8.73
  999      83.3       1.67s       9.29
 5,646    352.9       7.06s      39.11
12,756    531.5      10.63s      47.25   ← ¡CONVERGE!
```

## Tu tarea cada 10 minutos

### 1. Leer métricas
```bash
"C:/Users/Anton/OneDrive/Desktop/Uni/~TESIS/QUBE/.venv-train/Scripts/python.exe" -c "
from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
from pathlib import Path
for run_dir in sorted(Path('C:/Users/Anton/OneDrive/Desktop/Uni/~TESIS/QUBE/runs').glob('run*')):
    ea = EventAccumulator(str(run_dir)); ea.Reload()
    print(f'\n=== {run_dir.name} ===')
    for tag in ['rollout/ep_len_mean', 'rollout/ep_rew_mean', 'time/fps']:
        evts = ea.Scalars(tag)
        if evts: print(f'{tag}: step={evts[-1].step}, val={evts[-1].value:.2f}')
"
```

### 2. Verificar proceso activo
```bash
tasklist /FI "IMAGENAME eq python.exe" /FI "MEMUSAGE gt 300000"
```

### 3. Evaluar convergencia
- Ep Len > 500 (10s) = ✅ Converge — guardar modelo
- Ep Len 200-500 (4-10s) = ⚠️ Progresando
- Ep Len < 200 (<4s) = ❌ Ajustar params

### 4. Si el job terminó
Leer `experiments/2026-06-15_training/training_progress.md` y reportar resultados.

### 5. Si no converge después de 3 runs
Re-entrenar con estos ajustes (SOLO SIMULACIÓN):
- Reducir perturbación inicial: `0.001 * randn(4)` en `qube_sim.py` línea 124
- Probar reward `exp_alpha_4`
- Aumentar a 200K steps

### 6. Si converge (ep_len > 500)
El modelo se guarda automáticamente en `models/qube_sac_run*.zip`.
Reportar: "Entrenamiento convergió. Modelo en models/. Próximo paso: fine-tuning en hardware (requiere ESP32 conectado)."

## Archivos clave

| Archivo | Qué es |
|---------|--------|
| `src/qube_rl/auto_train.py` | Loop autónomo de entrenamiento |
| `runs/` | Logs TensorBoard |
| `models/` | Modelos guardados |
| `experiments/2026-06-15_training/HANDOFF.md` | Handoff detallado |
| `experiments/2026-06-15_training/RESULTS.md` | Resultados parciales |

## Python

- `uv run python` — Python 3.14 (proyecto principal)
- `.venv-train/Scripts/python.exe` — Python 3.13 + PyTorch CUDA (entrenamiento)
- La GPU NO ayuda (benchmark: CPU 42fps > GPU 35fps). Usar CPU.

---

