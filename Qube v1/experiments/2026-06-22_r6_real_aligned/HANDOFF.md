# HANDOFF — R6 sim2real / modo 7 on-device (QUBE swing-up real)

**Escrito:** 2026-06-23 ~00:45 · **Branch:** `DRL_IMP` · **Máquina:** 4 cores, sin CUDA usable.
**Estado del rig:** ESP32 en `192.168.100.50`, modo 0 (motor apagado). Flasheado con el firmware nuevo (v1.47.0).

> Doc técnico completo (el porqué de cada arreglo): `docs/SIM2REAL_BRINGUP.md`.

---

## TL;DR
El rig real **hace swing-up hasta vertical** (1° del invertido), repetido y estable, con el brazo acotado, corriendo la política **en el ESP32 a 50 Hz (modo 7)**. Toda la cadena de integración sim2real está resuelta y verificada. **Lo único que falta es el balance hold (≥1 s)** — y eso es calidad de modelo (el R6 es 50% balance en sim), NO integración. Para que aguante: entrenar un modelo de mejor balance y soltarlo en el modo 7 (pipeline ya validado).

---

## 1. Cómo correr el modo 7 (prueba on-device)
Con el brazo **centrado a mano** y el péndulo colgando:
```bash
cd "C:/Users/Anton/OneDrive/Desktop/Uni/~TESIS/QUBE"
.venv/Scripts/python.exe experiments/2026-06-22_r6_real_aligned/hw_bringup.py \
  --ip 192.168.100.50 --stage mode7 --reset-encoders --scale 0.85 --seconds 15
```
- El ESP32 corre la red a 50 Hz; el PC **solo monitorea**. Ctrl+C o `/cmd?m=0` = e-stop. Firmware frena solo más allá de ±90°.
- `--scale` (0..1) ajusta el torque **en vivo** (endpoint `/rl_cmd?scale=`), sin reflashear. Mejor punto hasta ahora: **0.85**.
- Otras etapas del bring-up: `ping`, `sensors` (mueve el péndulo a mano), `estop`, `deploy` (PC-en-el-lazo, **obsoleto**: solo 13 Hz).

## 2. Compilar / flashear firmware (PlatformIO)
```bash
pio run -d src/firmware -e esp32dev                      # compilar (~30s)
pio run -d src/firmware -e esp32dev_ota --target upload  # flashear por WiFi (~1-2min, a .50)
```
Tras flashear el ESP32 reinicia (~10-20 s) y vuelve al WiFi en modo 0. Verifica:
`requests.get('http://192.168.100.50/state').json()` → `mode=0`.

## 3. Cambiar el modelo (cuando entrenes uno mejor)
```bash
.venv/Scripts/python.exe -m qube_rl.export_rltools \
  --model <ruta_modelo.zip> --output src/firmware/esp32_qube/policy_weights.h
```
**Antes de flashear, verifica numéricamente** que la forward del firmware == `model.predict`
(script inline usado: extrae pesos con `export_rltools.extract_actor_weights`, reimplementa
`relu→relu→linear→tanh`, compara con `model.predict` sobre obs de un rollout sim; debe dar
error < 1e-6). Requisitos del modelo: SB3-SAC, `net_arch=[64,64]`, `history_steps=4`
(input 36-dim). Si cambia la arquitectura, ajustar `RL_HISTORY_STEPS/RL_OBS_PER_STEP` en el firmware.

## 4. Qué hacer ahora (siguiente sesión)
1. **Entrenar un modelo de mejor balance** — más pasos y/o el currículo inverso que dio mejor hold en sim (ver `memory/qube-r3-r4-balance-findings`). El R6 actual solo aguanta 50% en sim.
2. `export_rltools` → flashear → `--stage mode7`. El pipeline ya está validado, el modelo nuevo entra directo.
3. **Opcional:** subir el freno de θ del firmware de ±90° → ±100° (límite de sim) para que no recorte el catch. Está en el bloque `mode == 7` de `esp32_qube.ino` (`if (fabsf(pos) > 90.0f)`).

---

## 5. Estado del código (ya commiteable)
- `src/qube_rl/envs/qube_real.py` — fix unidades (radianes, sin doble conversión), `invert_action`, `invert_alpha` (defaults `True`).
- `src/qube_rl/envs/factory.py` — `make_real_env` propaga `invert_action`/`invert_alpha`.
- `src/firmware/esp32_qube/esp32_qube.ino` — modo 7: tanh, signos, gate 50 Hz, filtro de velocidad del sim, `/rl_cmd?scale=`.
- `src/firmware/esp32_qube/policy_weights.h` — pesos del R6.
- `experiments/2026-06-22_r4_real/train_real_v4.py` — mismos fixes de unidades + recompensa `|α|/π`.
- `experiments/2026-06-22_r6_real_aligned/hw_bringup.py` — bring-up por etapas.
- `CHANGELOG.md` 1.46.0 + 1.47.0; `docs/SIM2REAL_BRINGUP.md`.

## 6. Seguridad / gotchas
- **Recentra el brazo a mano antes de cada run** (el `--reset-encoders` pone ese punto como 0; si está descentrado, el 0 queda con offset y el firmware centra al lugar equivocado).
- **Girar el péndulo a mano descalibra la referencia** (overflow del contador): `--reset-encoders` (o `/rl_cmd?r=1` colgando) la restaura.
- El ESP32 **se cae del WiFi a veces** al manipularlo: si `192.168.100.50` no responde, revisar serial / power-cycle (puede cambiar de IP por DHCP).
- `ENABLE_COMMAND_TIMEOUT=false` (modo banco) → el modo 7 corre autónomo. Para operación segura real, ponerlo en `true` y mandar keep-alives.
