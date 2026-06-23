# Sim2Real del QUBE: del "nunca balancea" al swing-up real

**Fecha:** 2026-06-22 → 23 · **Modelo:** `r6_theta100_s0_step250000.zip` (SAC `[64,64]`, 50% balance en sim) · **Rig:** Furuta pendulum sobre ESP32 (BTS7960), control a 50 Hz.

Este documento explica, paso a paso, cómo se transfirió una política DRL entrenada en simulación al péndulo de Furuta físico. Histórico previo: **toda** prueba en hardware fallaba y el síntoma era un `avg_alpha ≈ 0.0001` sin explicación (ver `experiments/2026-06-22_r4_real/`). Se diagnosticaron y corrigieron **siete** problemas en cadena; el resultado final es swing-up real hasta vertical, estable y con el brazo acotado.

---

## 1. Punto de partida y método

El modelo R6 funciona en simulación (50% balance, 100% reach, hold 6.28 s) y está alineado con el límite mecánico real (±100°). Pero al desplegarlo en hardware no hacía nada útil. En vez de "probar y ver", se aplicó un **bring-up por etapas con el motor apagado primero** (`experiments/2026-06-22_r6_real_aligned/hw_bringup.py`):

1. `ping` — ¿responde el ESP32? ¿qué devuelve `/rl_state`?
2. `sensors` — motor apagado, mover el péndulo a mano: ¿los encoders leen? ¿en qué unidades?
3. `estop` — verificar el corte de motor.
4. `deploy` (con `--dry-run`) — la política lee el estado real y calcula su acción **sin energizar el motor**.
5. `deploy` en vivo / `mode7` — control real, con watchdog de θ y e-stop por Ctrl+C.

Cada hipótesis se confirmó con datos **antes** de tocar nada. Las observaciones (θ, α) y la convención de signos se contrastaron siempre contra una referencia: la **trayectoria del modelo en simulación** desde colgando.

---

## 2. Los siete problemas

### Problema 1 — Doble conversión de unidades (la "causa" del α≈0)
El firmware (`handleRlState`) ya entrega `/rl_state` **en radianes** (`getPositionDeg()*DEG_TO_RAD`). Pero `qube_real.py` y `train_real_v4.py` hacían `np.radians()` **encima**, dividiendo todo por 57.3. La política veía un estado casi-nulo siempre → de ahí el `avg_alpha ≈ 0.0001` histórico.
**Fix:** leer los valores crudos (ya en radianes) y envolver α con `wrap_angle`. (`qube_real.py` `step`/`reset`.)

### Problema 2 — Referencia de encoder descalibrada
Girar el péndulo a mano (en la etapa `sensors`) hace que el contador acumule vueltas (se vio α llegar a +60 rad). En reposo, "colgando" leía 123° en vez de 0°.
**Fix:** `/rl_cmd?r=1` con el péndulo colgando quieto re-zera ambos encoders (convención: colgando = 0, invertido = ±π). `hw_bringup deploy/mode7 --reset-encoders`.

### Problema 3 — Signo de la acción invertido
Prueba en lazo abierto: una acción constante **+0.2** movía θ a **−67°** en el rig, pero a **+49°** en simulación. El motor está cableado al revés respecto a la convención de sim.
**Fix:** `QubeRealEnv(invert_action=True)` niega el comando **en la frontera de hardware** (después de los wrappers, para que el historial de acciones que ve la política siga en convención de sim).

### Problema 4 — Signo de α invertido
Con la acción ya corregida, la telemetría del primer paso fue θ−46/**α+26**… pero medido contra sim debía ser θ−35/**α+37**: cuando el brazo se mueve, α en el rig iba al revés que en sim. El argumento decisivo fue el **acoplamiento**: en sim `−θ ↔ +α`; el dato real mostraba `−θ ↔ −α`, es decir el encoder del péndulo está espejado.
**Fix:** `QubeRealEnv(invert_alpha=True)` invierte α y α̇. Con ambos signos, el paso 1 real (θ−46/α+26) cuadra con la trayectoria de sim (θ−35/α+37).

> **Nota de simetría:** el péndulo de Furuta es invariante bajo `(θ,α,u)→(−θ,−α,−u)`. Las dos correcciones válidas (acción + α) son una sola corrección física salvo ese espejo global; θ se deja tal cual.

### Problema 5 — ★ Causa raíz: la frecuencia de control
Incluso con todos los signos correctos, el brazo se fugaba al límite. Medición del lazo PC-en-el-lazo por HTTP/WiFi:

```
50 ciclos en 3.77 s  ->  13.3 Hz efectivos   (entrenado a 50 Hz)
  send /rl_cmd:   mediana 40 ms
  read /rl_state: mediana 34 ms
  por ciclo:      ~71 ms  (se necesitan <=20 ms para 50 Hz)
```

**Cada acción se mantiene ~3.5× más tiempo del que la política espera** → el brazo recorre ~3.5× por decisión → la política (entrenada a 50 Hz) no alcanza a corregir → runaway garantizado, sin importar signos ni torque. **Esta es la razón real por la que toda prueba de hardware había fallado.**

**Solución: inferencia on-device (modo 7).** Correr la red **en el ESP32 a 50 Hz**, sin WiFi en el lazo (ver §3).

### Problema 6 — Activación de salida (al portar al modo 7)
El scaffolding del firmware (`rl_forward`) aplicaba `Hardtanh(−2,2)` y el modo 7 multiplicaba `×0.5` — convención de otra librería (RLtools). SB3-SAC determinista usa `acción = tanh(mu)`. Son funciones distintas (en mu=2: `tanh=0.96` vs `0.5·clamp=1.0`).
**Verificación numérica** (reimplementando la forward del firmware en Python contra `model.predict` sobre obs de un rollout sim):

```
con tanh (fix):           error máx 1.7e-07   (exacto)
con Hardtanh*0.5 (viejo): error máx 2.7e-01   (equivocado)
```

**Fix:** `rl_forward` → `return tanhf(raw_out)`; modo 7 sin el `×0.5`.

### Problema 7 — Signo + filtro de velocidad (la pieza final)
El firmware computaba la velocidad como `−(x−prev)/dt` (negativo líder). En una rampa de θ creciente, esto da velocidad **negativa**, mientras que el sim (filtro `VelocityFilter`, `+d/dt`) da **positiva**: la velocidad que veía la política estaba **con el signo invertido**. La política amortiguaba cuando debía bombear. No se cazó antes porque los tests previos (a 13 Hz) eran demasiado cortos y la velocidad cerca de colgar es ~0.

Además el filtro era distinto: el sim usa el filtro derivativo discreto `H(s)=50s/(s+50)` @ dt=0.02; el firmware usaba una EMA afinada para 500 Hz.
**Fix:** en el modo 7, replicar el filtro **exacto** del sim:

```
v[n] = 50·(x[n] − x[n−1]) + 0.36788·v[n−1]
```

aplicado al ángulo en convención de sim (θ = `pos·DEG_TO_RAD`; α = `−pendPosRaw·DEG_TO_RAD`, **sin envolver** para la derivada, envuelto solo para las features de posición). La diferencia positiva `(x[n]−x[n−1])` da el signo correcto `+d/dt`. Verificado contra `qube_rl.utils.VelocityFilter`.

---

## 3. Arquitectura del modo 7 (inferencia on-device)

La política corre en el firmware (`esp32_qube.ino`, bloque `mode == 7`), a 50 Hz, sin PC en el lazo. El PC solo monitorea y puede hacer e-stop.

**Pipeline por tick (50 Hz):**
1. **Gate de 50 Hz** con zero-order hold: el loop de control corre a 500 Hz (`CONTROL_PERIOD_US=2000`); sin gate, la red de 50 Hz iría 10× rápido y el historial/velocidad estarían a la escala temporal equivocada. Entre ticks se mantiene el último PWM.
2. **Observación en convención de sim:** θ = `pos·DEG_TO_RAD`; α = `wrap(−pendPosRaw·DEG_TO_RAD)`; velocidades por el filtro del §2.7 (α̇ con α invertido).
3. **Buffer de historial 4×9 = 36** (`[θ,α,cosθ,sinθ,cosα,sinα,θ̇,α̇,action]` × 4 pasos, oldest-first), idéntico al `HistoryWrapper` del entrenamiento (`obs_t` emparejado con `a_{t−1}`).
4. **Forward** `36→64→64→1`, ReLU, `tanh` → acción ∈ [−1,1].
5. **Motor:** `setMotor(−acción · PWM_MAX · rl_pwm_scale)` (acción negada por el torque espejado; el historial guarda la acción **sin** negar).
6. **Seguridad:** freno si |θ|>90°; `ENABLE_COMMAND_TIMEOUT=false` (banco) → corre autónomo; parar con `/cmd?m=0`.

**Pesos:** `qube_rl/export_rltools.py` extrae el actor SB3-SAC (`actor.latent_pi.0/2`, `actor.mu`) a `policy_weights.h`. **Siempre verificar numéricamente** forward==`model.predict` antes de flashear.

**Tuning en runtime:** `/rl_cmd?scale=X` (0..1) escala el PWM del modo 7 sin reflashear.

---

## 4. Resultados

| Configuración | α máximo | Brazo | Hold |
|---|---|---|---|
| PC-en-el-lazo (mode 6, 13 Hz) | runaway (12–35°) | se fuga | — |
| Modo 7, scale 1.0, **sin** fix de velocidad | 83–124° | se fuga | — |
| **Modo 7, scale 0.85, con fix de velocidad** | **179° (1° del invertido)** | **acotado (±48°, 15 s)** | ~0.1–0.2 s |
| Modo 7, scale 0.8 / 0.9 | 180° | acotado | ≤0.12 s |

A **scale 0.85** el rig hace **swing-up tras swing-up hasta vertical**, con el brazo controlado, de forma estable durante los 15 s. **El sim2real transfirió.**

**Lo que falta — el balance hold (≥1 s):** el barrido de torque (0.8/0.85/0.9) mostró que **todos llegan al tope pero ninguno mantiene**. El scale no desbloquea el catch. La razón: el modelo R6 es **50% balance en sim** — sabe subir, no atrapa de forma fiable. Es el **problema abierto del proyecto** (`balance_rate`), ahora aislado: ya no es integración ni sim2real, es **calidad de modelo de balance**.

---

## 5. Próximos pasos

1. **Entrenar un modelo de mejor balance** — más pasos y/o el currículo inverso que dio mejor hold en sim (`memory/qube-r3-r4-balance-findings`). El pipeline `export_rltools → modo 7` ya está validado: un modelo mejor entra directo cambiando `policy_weights.h`.
2. **Opcional:** subir el freno de θ del firmware de ±90° → ±100° (límite de sim) para no recortar el catch.
3. **(Riguroso) system-ID:** medir inercia/torque/fricción reales y ajustar el modelo de sim, para cerrar el gap de dinámica residual que dificulta el catch.

## 6. Archivos clave
- `experiments/2026-06-22_r6_real_aligned/hw_bringup.py` — bring-up por etapas (`ping`/`sensors`/`estop`/`deploy`/`mode7`).
- `experiments/2026-06-22_r6_real_aligned/HANDOFF.md` — operativa (comandos para retomar).
- `src/qube_rl/envs/qube_real.py`, `envs/factory.py` — fixes de unidades y signos.
- `src/firmware/esp32_qube/esp32_qube.ino` (bloque `mode == 7`) + `policy_weights.h`.
- `src/qube_rl/export_rltools.py` — exportador SB3→firmware.
- `CHANGELOG.md` 1.46.0 (integración) + 1.47.0 (modo 7).
