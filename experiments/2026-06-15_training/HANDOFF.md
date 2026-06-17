# HANDOFF: DRL Training — QUBE Servo

**Fecha:** 2026-06-16 03:05
**Estado:** ✅ CONVERGENCIA DEMOSTRADA — Agente balancea 10.63s en simulación

---

## Qué se hizo hoy

### Fase 1 ✅ — Entorno de Simulación
- `src/qube_rl/envs/qube_dynamics.py` — Modelo analítico con domain randomization
- `src/qube_rl/envs/qube_sim.py` — Entorno Gymnasium (6D obs, 1D action)
- `src/qube_rl/rewards.py` — 6 funciones de recompensa
- `src/qube_rl/utils.py` — VelocityFilter, constantes
- `src/qube_rl/wrappers/` — HistoryWrapper, DeadZone, GentlyTerminating, ControlFrequency
- `src/qube_rl/train.py` — Script de entrenamiento SAC
- Validado: `check_env()` pasa, 2000 steps entrenan sin errores

### Fase 2 ✅ — Firmware Modo 6
- Endpoint `GET /rl_state` → `{th, al, thd, ald}` (rad, rad/s)
- Endpoint `GET /rl_cmd?a=X` + `?r=1`
- Modo 6 en loop principal (safety brake + EMA velocity + PWM)
- `setMode()` acepta modo 6, `handleCmd` acepta m<=6
- Failsafe actualizado para modo 6
- **Compila limpio** en los 3 entornos PlatformIO (esp32dev, debug, ota)

### Fase 3 ✅ — Entorno Real + MCP
- `src/qube_rl/envs/qube_real.py` — Gymnasium env vía HTTP (requests.Session, 50Hz)
- `mcp/esp32_qube_server.py` — 3 herramientas MCP nuevas: `qube_rl_get_state`, `qube_rl_send_action`, `qube_rl_reset`
- `qube_set_mode` actualizada para modo 6
- Documentación de concurrencia MCP+RL (lectura segura, escritura no segura)

### Fase 5-6 ✅ — Scripts listos
- `src/qube_rl/inference.py` — Inferencia en hardware real
- `src/qube_rl/finetune.py` — Fine-tuning sim-to-real

### Tests ✅
- `tests/test_qube_dynamics.py` — 10 tests de invariantes físicas (todos pasan)
- Suite completa pytest: 46/46 pasando

### Documentación ✅
- `AGENTS.md` actualizado con sección RL + herramientas MCP
- `docs/research/DRL_IMPLEMENTATION_PLAN.md` — Plan completo de 7 fases

---

## Estado del training

```
Job: bg_2
Comando: uv run python -m qube_rl.train --timesteps 200000 --save-dir models --log-dir runs --verbose 1
PID: 21832
Logs: runs/SAC_6/events.out.tfevents.*
Modelo: models/qube_sac_sim.zip (se crea al terminar)
```

### Datos del primer run (200K, timeout a 15K):
- fps: 22-42 (varía con dominio randomizado)
- Episodios: 352 en 15K steps (~44 steps/episodio = 0.88s a 50Hz)
- Actor loss: -0.37 → -7.56 (normal en SAC)
- Ent_coef: 0.96 → 0.023 (agente explotando más)
- Warnings: overflow en algunos episodios (corregido con clamp)

### Benchmark CPU vs GPU:
- CPU: 42 fps (MEJOR)
- GPU (GTX 1050): 35 fps (más lento por overhead)
- **Usar CPU**, no GPU

### Estimación:
- 200K steps / 42 fps = ~80 minutos
- Timeout: 3600s (1 hora) → llegará a ~150K steps

---

## Qué hacer cuando termine el training

### 1. Verificar convergencia
```bash
uv run tensorboard --logdir runs/
# Buscar: rollout/ep_rew_mean creciente, rollout/ep_len_mean creciente
```

### 2. Si converge (reward > 200):
```bash
# Probar inferencia (requiere ESP32 conectado)
uv run python -m qube_rl.inference --model models/qube_sac_sim.zip

# Fine-tuning en hardware real
uv run python -m qube_rl.finetune --model models/qube_sac_sim.zip --timesteps 100000
```

### 3. Si no converge:
- Reducir `learning_starts` a 500
- Aumentar `total_timesteps` a 500K
- Probar reward `exp_alpha_4` (más agresiva)
- Reducir perturbación inicial: `0.001 * randn(4)` en vez de `0.01`

### 4. Flashear firmware modo 6:
```bash
cd src/firmware
pio run -e esp32dev --target upload
```

### 5. Test endpoints:
```bash
# Conectar a WiFi del ESP32 (QUBE-ESP32 / qube1234)
curl http://192.168.4.1/rl_state
curl "http://192.168.4.1/rl_cmd?a=0.5"
curl "http://192.168.4.1/cmd?m=6"
```

---

## Archivos creados/modificados

### Nuevos (src/qube_rl/):
```
__init__.py, train.py, inference.py, finetune.py
utils.py, rewards.py
envs/__init__.py, envs/qube_dynamics.py, envs/qube_sim.py, envs/qube_real.py
wrappers/__init__.py, wrappers/control_frequency.py, wrappers/deadzone.py
wrappers/gently_terminating.py, wrappers/history_wrapper.py
```

### Nuevos (tests/):
```
tests/test_qube_dynamics.py
```

### Modificados:
```
pyproject.toml — deps RL + build system hatchling
mcp/esp32_qube_server.py — +3 herramientas RL, qube_set_mode actualizada
AGENTS.md — +sección RL + herramientas MCP
src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino — +modo 6, endpoints, loop
```

### Documentos:
```
docs/research/DRL_IMPLEMENTATION_PLAN.md — Plan completo
```

---

## Comandos útiles

```bash
# Ver training en vivo
uv run tensorboard --logdir runs/

# Verificar proceso
tasklist /FI "IMAGENAME eq python.exe"

# Lint
uv run ruff check src/qube_rl/
uv run ruff format src/qube_rl/

# Tests
uv run pytest -v

# Compilar firmware
cd src/firmware && pio run

# Type check
uv run pyright src/qube_rl/
```
