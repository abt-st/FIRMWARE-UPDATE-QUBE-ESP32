# HANDOFF — Entrenamiento Overnight QUBE Servo RL

**Fecha:** 2026-06-16
**Objetivo:** Entrenar agente SAC que haga swing-up + balance del péndulo QUBE Servo
**Estrategia:** Dejar correr entrenamiento con monitoreo cada ~20 min

---

## Estado Actual del Proyecto

### Pipeline completo implementado
```
Entrenamiento (Python/SB3) → Exportación (SB3→C++) → Firmware (ESP32/RLtools) → Hardware
     ↓                           ↓                          ↓
   sim env                 policy_weights.h            modo 7 (on-device)
```

### Archivos clave modificados hoy
| Archivo | Cambio |
|---------|--------|
| `src/qube_rl/rewards.py` | 3 rewards nuevas: `swingup_balance`, `linear_alpha`, `linear_alpha_dense` |
| `src/qube_rl/train.py` | Default [64,64], `--net-arch` flag, default reward configurable |
| `src/qube_rl/fast_train.py` | Refactor: delega a train.py, [64,64] default |
| `src/qube_rl/export_rltools.py` | **Nuevo** — exporta pesos SB3 → header C++ RLtools |
| `src/qube_rl/envs/qube_real.py` | Fix: obs 8 dims (match sim), grados→radianes |
| `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino` | Modo 7: inferencia on-device [36→64→64→1] |
| `src/firmware/esp32_qube_l298n/policy_weights.h` | Pesos del modelo fine-tuned |

### Bugs corregidos hoy
1. **Real env obs mismatch** — era 6 dims (sin raw angles), ahora 8 (match sim)
2. **Grados vs Radianes** — `/rl_state` retorna grados, el env ahora convierte con `np.radians()`
3. **handleCmd mode limit** — `m <= 6` cambiado a `m <= 7`
4. **swingup_balance reward invertida** — `upright` calculaba al revés, corregido

### Resultados de entrenamiento hasta ahora

| Experimento | Reward | Net | Steps | Resultado |
|------------|--------|-----|-------|-----------|
| rltools_v1 | swingup_balance | [64,64] | 50K | ❌ reward negativa (-5.68), no aprende |
| cos_alpha_64 | cos_alpha | [64,64] | 50K | ⚠️ reward +0.21, max_alpha 41° sim |
| cos_alpha_64_v2 | cos_alpha | [64,64] | 50K | ⚠️ ep_len ~37, reward +0.2 |
| finetune real | cos_alpha | [64,64] | 5K | ❌ theta=-136° (bug grados/rad, ya fixeado) |

### Problema raíz identificado
El modelo **no aprende swing-up** porque:
1. `cos_alpha` tiene gradiente ~0 cuando el péndulo cuelga (25x menor que `linear_alpha`)
2. El agente necesita descubrir la estrategia de "bombear" energía — requiere gradiente fuerte
3. 50K steps es insuficiente — necesita 500K+

### Solución preparada
Nueva reward `linear_alpha`: gradiente **25x más fuerte** near hanging position.
Comprobado:
```
cos_alpha gradient at 0°→2.9°:  0.00062  (casi cero)
linear_alpha gradient at 0°→2.9°: 0.01592  (25x más fuerte)
```

---

## Plan de Entrenamiento Overnight

### Paso 1: Entrenamiento principal (3-4 horas)
```bash
uv run python -m qube_rl.train --timesteps 500000 --reward linear_alpha --net-arch 64 --lr 3e-4
```
- **Reward:** `linear_alpha` (gradiente 25x fuerte near hanging)
- **Red:** [64, 64] (compatible RLtools/ESP32, ~17KB flash)
- **Timesteps:** 500K (10x más que antes)
- **Modelo guardado:** `models/qube_sac_64x2.zip`
- **TensorBoard:** `runs/` — monitorear `ep_rew_mean` y `ep_len_mean`
- **Tiempo estimado:** ~3-4 horas en CPU

### Paso 2: Monitoreo cada ~20 min
Verificar en TensorBoard o con:
```bash
uv run tensorboard --logdir runs
```
Métricas a vigilar:
- **`rollout/ep_rew_mean`** — debe subir consistentemente. Meta: > 0.5 a las 200K steps
- **`rollout/ep_len_mean`** — debe subir. Si llega a ~200+ steps (4+ segundos), el agente está haciendo algo
- **`train/entropy`** — debe bajar lentamente (agente explorando menos)
- Si `ep_rew_mean` no sube a las 100K → parar y probar otra reward

### Paso 3: Si linear_alpha no funciona (a las 200K sin progreso)
Probar `linear_alpha_dense`:
```bash
uv run python -m qube_rl.train --timesteps 500000 --reward linear_alpha_dense --net-arch 64 --lr 3e-4
```
Esta reward añade **velocity shaping**: recompensa al_dot cuando el péndulo está en la mitad inferior (pumping) y penaliza al_dot en la mitad superior (desperdicio).

### Paso 4: Si ninguna funciona
Probar red [128, 128] (más capacidad, más rápido de aprender):
```bash
uv run python -m qube_rl.train --timesteps 500000 --reward linear_alpha --net-arch 128 --lr 3e-4
```
Nota: [128,128] es ~70KB flash — puede no caber en ESP32. Verificar:
```bash
cd src/firmware && pio run -e esp32dev 2>&1 | grep Flash
```
Si no cabe, se puede downsize después con knowledge distillation.

### Paso 5: Exportar y deploy (cuando el modelo funcione en sim)
```bash
# Exportar pesos a C++
uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip --output src/firmware/esp32_qube_l298n/policy_weights.h

# Compilar y subir firmware
cd src/firmware && pio run -e esp32dev --target upload

# Activar modo 7
uv run python -c "import requests; requests.get('http://192.168.100.50/cmd', params={'m': '7'}, timeout=3)"
```

### Paso 6: Fine-tuning en hardware (cuando sim funcione)
```bash
uv run python -m qube_rl.finetune --model models/qube_sac_64x2.zip --ip 192.168.100.50 --timesteps 50000 --lr 1e-4 --freq 10
```
**Importante:** El real env necesita IP `192.168.100.50` (no `192.168.4.1`).

---

## Verificación Rápida del Modelo

Para saber si el modelo funciona, evaluar en sim:
```bash
uv run python -c "
from qube_rl.train import make_env
from stable_baselines3 import SAC
from stable_baselines3.common.vec_env import DummyVecEnv
import numpy as np

vec_env = DummyVecEnv([lambda: make_env(reward='linear_alpha')])
model = SAC.load('models/qube_sac_64x2.zip')

for ep in range(10):
    obs = vec_env.reset()
    total_rew = 0
    max_alpha = 0
    for step in range(500):
        action, _ = model.predict(obs, deterministic=False)
        obs, reward, done, info = vec_env.step(action)
        if abs(obs[0][1]) > abs(max_alpha):
            max_alpha = obs[0][1]
        total_rew += reward[0]
        if done[0]:
            break
    print(f'Ep {ep+1}: {step+1} steps, rew={total_rew:.1f}, max_alpha={np.degrees(max_alpha):.1f}')
"
```

**Criterio de éxito:**
- `max_alpha` > 120° (cerca de invertido) en al menos 1 de 10 episodios
- `ep_len_mean` > 100 steps (2+ segundos)
- `ep_rew_mean` > 0.3

---

## Referencia Rápida

### Comandos útiles
```bash
# Entrenamiento
uv run python -m qube_rl.train --timesteps 500000 --reward linear_alpha --net-arch 64
uv run python -m qube_rl.fast_train --steps 50000 --reward linear_alpha --net-arch 64

# Exportar
uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip

# ESP32
cd src/firmware && pio run -e esp32dev --target upload
uv run python -c "import requests; print(requests.get('http://192.168.100.50/state', timeout=3).json())"

# Lint/Format
uv run ruff check src/qube_rl/ && uv run ruff format src/qube_rl/
uv run pytest tests/ -v
```

### ESP32 info
- **IP:** 192.168.100.50 (STA mode, static IP)
- **Modos:** 0=off, 1=PID, 6=RL HTTP, **7=RL on-device**
- **Endpoints:** `/state`, `/cmd?m=N`, `/rl_state`, `/rl_cmd?a=X`, `/rl_cmd?r=1`

### Observation space
- **Sim env:** 8 features `[θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇]`
- **Wrapped (HistoryWrapper):** 36 features (4 steps × 9 = 36, include action)
- **RL observation from `/rl_state`:** `{th, al, thd, ald}` in **degrees** → must convert to radians

### Constraints
- **Theta (brazo):** ±90° (`angle_limits=[np.pi/2, np.pi]`)
- **Alpha (péndulo):** ±180°
- **Control freq:** 50 Hz sim, 10 Hz real (WiFi)
- **Red [64,64]:** 25.8 KB flash, 75.5% total flash usage
