# API HTTP — QUBE ESP32

Referencia completa de los endpoints HTTP del firmware.

## Dirección base

- **SoftAP puro (rol por defecto desde v1.56.0):** `http://192.168.4.1` — siempre la
  misma, sin router ni DHCP. El PC debe estar asociado a la red `QUBE-ESP32`.
- **Modo AP+STA** (`pio run -e esp32dev_apsta`): además `http://192.168.100.50` por la
  red local.

Los scripts del repositorio aceptan la variable de entorno `QUBE_IP` para apuntar a
una placa con el rol anterior sin editar código.

## GET /state

Retorna JSON con el estado completo del sistema (servo + péndulo + INA219 + Kalman):

```json
{
  "mode": 2,
  "count": 1024, "enc_a": 1, "enc_b": 0, "encoder_dir": 1, "counts_per_rev": 2048.0,
  "raw_position_deg": 180.0, "position_deg": 15.2, "offset_deg": 164.8,
  "setpoint_deg": 20.0, "error_deg": 4.8,
  "pend_count": -128, "pend_raw_position_deg": 157.7, "pend_position_deg": -2.3, "pend_offset_deg": 160.0,
  "pwm": 45, "gain_scheduling": false, "gain_mode": 0,
  "ina_ok": true, "v_bus": 11.8, "v_shunt_mv": 12.5, "i_ma": 350.0, "p_mw": 4130.0,
  "servo_ff_pwm": 0.0, "vel_alpha": 0.12,
  "kf_enabled": false, "kf_theta": 15.1, "kf_alpha": -2.2, "kf_dtheta": 0.5, "kf_dalpha": -1.2
}
```

### Campos

| Campo                | Tipo   | Descripción                                  |
| -------------------- | ------ | -------------------------------------------- |
| `mode`              | int    | Modo de operación actual (0–7)              |
| `count`             | int    | Cuentas del encoder servo                   |
| `enc_a`, `enc_b`   | int    | Estado de canales A/B del encoder servo     |
| `encoder_dir`       | int    | Dirección del encoder (+1 o −1)            |
| `counts_per_rev`    | float  | Resolución del encoder (CPR)                |
| `raw_position_deg`  | float  | Posición cruda del servo (grados)           |
| `position_deg`      | float  | Posición del servo con offset (grados)      |
| `offset_deg`        | float  | Offset de posición del servo                |
| `setpoint_deg`      | float  | Setpoint actual del servo                   |
| `error_deg`         | float  | Error de seguimiento (setpoint − posición) |
| `pend_count`        | int    | Cuentas del encoder péndulo                 |
| `pend_raw_position_deg` | float | Posición cruda del péndulo (grados)    |
| `pend_position_deg` | float  | Posición del péndulo con offset (grados)    |
| `pend_offset_deg`   | float  | Offset de posición del péndulo              |
| `pwm`               | int    | Señal de control PWM actual (−255 a +255)  |
| `gain_scheduling`   | bool   | Gain scheduling activo                      |
| `gain_mode`         | int    | Modo de gain scheduling (0=fino, 1=grueso) |
| `ina_ok`            | bool   | INA219 operativo                            |
| `v_bus`             | float  | Voltaje del bus (V)                         |
| `v_shunt_mv`        | float  | Voltaje en shunt (mV)                       |
| `i_ma`              | float  | Corriente (mA)                              |
| `p_mw`              | float  | Potencia (mW)                               |
| `servo_ff_pwm`      | float  | Feedforward PWM                             |
| `vel_alpha`         | float  | Alpha del filtro EMA de velocidad           |
| `kf_enabled`        | bool   | Filtro de Kalman activo                     |
| `kf_theta`          | float  | θ estimado por Kalman (grados)              |
| `kf_alpha`          | float  | α estimado por Kalman (grados)              |
| `kf_dtheta`         | float  | θ' estimado por Kalman (grados/s)           |
| `kf_dalpha`         | float  | α' estimado por Kalman (grados/s)           |
| `homing_phase`      | string | Fase del homing: `IDLE`, `WAIT_QUIET`, `SEEK_POS`, `BACKOFF_POS`, `TOUCH_POS`, `SEEK_NEG`, `BACKOFF_NEG`, `TOUCH_NEG`, `GOTO_CENTER`, `DONE`, `FAIL` |
| `homing_ok`         | bool   | Última calibración válida                   |
| `homing_fail`       | int    | 0=sin falla, 1=rango fuera de tolerancia, 2=timeout lado +, 3=timeout lado −, 4=timeout al centrar |
| `homing_stop_pos`   | float  | Tope positivo medido (grados crudos)        |
| `homing_stop_neg`   | float  | Tope negativo medido (grados crudos)        |
| `homing_range`      | float  | Recorrido total medido (grados). Medido en banco: **270°**; el firmware acepta **262–278** (`HOMING_RANGE_MIN/MAX_DEG`), fuera de eso aborta con `homing_fail=1` |
| `homing_center`     | float  | Centro calculado, adoptado como `offset_deg` |
| `homing_pwm_sign`   | int    | Sentido **medido** del motor contra el encoder del brazo, aprendido en el toque negativo del homing: `+1` = un PWM positivo hace crecer `pos`. `0` = todavía no se hizo homing. Publicado desde v1.63.0: el recentrado de P25 cierra el lazo con él, y leerlo tras un `m3` es el test de [P26](REGISTRO_PROBLEMAS.md#p26) |
| `homing_required`   | bool   | Compuerta de homing vigente (ver `/cmd?hr=`). Con `true` y `homing_ok=false`, `setMode()` **rechaza** los modos 2/4/5/6/7 |
| `ina_required`      | bool   | Compuerta del INA219 vigente (ver `/cmd?sf=`). Con `true` y `ina_ok=false`, `setMode()` **rechaza** los modos 1/2/4/5/6/7 |
| `mode_reject`       | int    | Por qué el último `?m=` **no tuvo efecto**: `0` ninguno · `1` fuera de rango · `2` falta homing · `3` INA219 caído. Queda puesto hasta el siguiente `setMode()` exitoso. Sin leerlo, un modo rechazado es indistinguible de uno aplicado: `setMode()` retorna sin hacer nada y el único aviso sale por Serial, que en este banco no se puede abrir sin reiniciar la placa |
| `safety_action`     | int    | Última intervención de la capa de seguridad: `0` nada · `1` derate por tensión · `2` corte por tensión · `3` corte por corriente · `4` corte por cordura del péndulo en m6/m7 ([P17]: `\|α\|` crudo o vueltas fuera de rango). Se limpia al tick siguiente |
| `safety_cuts`       | int    | Cortes acumulados desde el arranque |
| `safety_derates`    | int    | Derates acumulados. Van aparte porque `safety_action` se limpia solo y `safety_cuts` no cuenta escalados: sin este contador un derate por tensión es **invisible**, que es lo que escondió el fallo de homing del 2026-08-06 |
| `ke_gain`           | float  | Ganancia de energía del swing-up **vigente** (ver `/cmd?ke=`) |
| `ke_override`       | float  | Override manual de `ke_gain`; `< 0` = manda la rama adaptativa |
| `pend_wraps`        | int    | Veces que se acotó la lectura del péndulo restando vueltas enteras. **Monotónico** (sólo se reinicia al arrancar): leerlo antes y después y sacar la diferencia. Un valor >0 en una corrida indica que el péndulo giró |
| `swing_trans_reason`| int    | Bitmask del criterio que disparó el traspaso m5→m4: `1`=near+slow, `2`=peak, `4`=forced, `8`=energy. `0` = no hubo traspaso en el intento en curso. Pueden coincidir varios |
| `swing_trans_alpha` | float  | `pendPos` **en el instante** del traspaso (muestrear el modo desde el cliente llega tarde y da otro ángulo) |
| `swing_trans_vel`   | float  | \|α̇\| en el traspaso (°/s) |
| `swing_trans_energy`| float  | `E/E*` en el traspaso; `1.0` = energía justa para llegar a vertical |
| `swing_trans_ms_ago`| int    | ms desde el traspaso; `0` = no hubo. `setMode(5)` limpia el latch |
| `swing_zero_enabled`| 0/1    | Fase de quietud + re-cero del péndulo al entrar al modo 5 activa (ver `/cmd?sz=`) |
| `swing_zero_phase`  | int    | `1` = esperando quietud antes de bombear; `0` = bombeando |
| `swing_zero_ok`     | 0/1    | El último intento logró re-establecer el cero. `0` **después** de un intento significa que no se aquietó y el modo abortó a 0 — no se arranca a ciegas |
| `swing_retry_enabled`| 0/1   | Reintento automático del swing-up tras un intento de balanceo fallido (ver `/cmd?rt=`) |
| `swing_retry_count` | int    | Reintentos automáticos **consecutivos** ya consumidos. Lo reinicia cualquier modo pedido a mano y un balanceo que sobreviva 3 s. Sin este campo no se puede distinguir «enganchó al primer intento» de «enganchó al tercero», que es justo la diferencia que el reintento introduce en las tasas de éxito |
| `swing_retry_max`   | int    | Presupuesto vigente de reintentos consecutivos (def. 3, ver `/cmd?rtn=`) |
| `swing_fail_reason` | int    | Motivo del último intento abortado: `1` el péndulo se cayó · `2` dio una vuelta · `3` el brazo llegó al tope · `4` nunca llegó a la vertical · `5` el recentrado no pudo volver. `0` = ninguno desde el arranque |
| `swing_recenter_phase`| int  | `1` = el brazo está volviendo al centro antes de re-bombear; `0` = fase inactiva |
| `lqr_catch_ms`      | int    | Duración vigente del catch del modo 4 (ver `/cmd?lc=`) |
| `lqr_centering_grace`| 0/1   | Periodo de gracia del centering vigente (ver `/cmd?cg=`) |
| `lqr_alive_ms`      | int    | **Supervivencia del último intento de balanceo**: ms desde el fin del catch hasta la salida del modo 4. Cuenta desde el *fin* del catch porque durante el catch el LQR no corre. Deja de actualizarse solo al caer, así que leerlo después de la caída da el valor final; sobrevive a la caída a propósito, para poder leerse sin carrera. `0` = no hubo traspaso |
| `loop_dt_max_us`    | int    | Peor período real del lazo de control desde el último reset (µs) |
| `loop_overruns`     | int    | Veces que el atraso superó 5 períodos y hubo que re-sincronizar |
| `loop_dt_nom_us`    | int    | Período nominal del lazo (2000 µs = 500 Hz) |
| `daq_running`       | bool   | Adquisición por bloques activa (ver `/daq`) |
| `daq_available`     | int    | Muestras esperando en el buffer circular |
| `daq_dropped`       | int    | Muestras perdidas por buffer lleno desde el último `start`. **Distinto de 0 invalida la continuidad de la serie** |
| `serial_telemetry`  | bool   | Línea de telemetría por Serial activa (`/cmd?sv=`) |

Los tres campos `loop_*` son la evidencia de temporización del lazo: `loop_dt_nom_us`
es la constante del firmware y `loop_dt_max_us` lo que realmente ocurrió. Conviene
llamar `/cmd?rj=1` **al arrancar** cada captura, porque el peor caso del arranque
(escaneo WiFi bloqueante) domina si no se reinicia el contador.

## GET /rl_state

Estado compacto de baja latencia para el agente RL (ángulos en radianes):

```json
{"th": 0.2654, "al": 3.0912, "thd": 0.0087, "ald": -0.0214, "pv": 3}
```

| Campo  | Tipo   | Descripción                        |
| ------ | ------ | ---------------------------------- |
| `th`  | float  | θ del servo (radianes)            |
| `al`  | float  | α del péndulo (radianes)          |
| `thd` | float  | θ' (velocidad angular, rad/s)     |
| `ald` | float  | α' (velocidad angular, rad/s)     |
| `pv`  | int    | Versión de protocolo `/rl_state` (handshake). `qube_real.py` la valida en `reset()`; firmware y Python deben desplegarse juntos. |

## GET /rl_step

Endpoint combinado (proto v3): **fija la acción RL y devuelve el estado compacto en un
solo round-trip**, en vez de `/rl_cmd?a=` seguido de `/rl_state` (2 RTT ≈ 71 ms). Es la
ruta que usa `QubeRealEnv.step()` para reducir la latencia del lazo PC-en-el-lazo por
WiFi a ~1 RTT/paso. Sin el parámetro `a`, se comporta como `/rl_state` (solo lectura).

```bash
curl "http://192.168.4.1/rl_step?a=0.5"
```

Respuesta: el mismo JSON de `/rl_state` (`{th, al, thd, ald, pv}`).

| Parámetro | Tipo  | Descripción                    |
| --------- | ----- | ------------------------------ |
| `a`     | float | Acción RL [−1.0, 1.0] → PWM (opcional) |

## GET /daq — adquisición por bloques

Control de la captura. El ESP32 muestrea a la tasa del lazo (500 Hz / `decim`) en un
buffer circular de 2048 muestras (4,1 s a 500 Hz) y el PC se lleva bloques binarios por
`/daq/read`. Detalle del diseño en `docs/research/adquisicion_por_bloques.md`.

| Parámetro | Tipo | Descripción |
| --------- | ---- | ----------- |
| `start` | 1 | Arranca la captura. **Vacía el buffer**: nunca se mezclan dos sesiones |
| `stop` | 1 | Detiene la captura |
| `decim` | 1–500 | Decimación: 1 = 500 Hz, 10 = 50 Hz, 50 = 10 Hz |

Sin parámetros devuelve el estado. Respuesta (siempre JSON):

```json
{"pv":1,"running":true,"decim":1,"rate_hz":500.0,"capacity":2048,"max_block":512,
 "sample_bytes":16,"available":312,"produced":15840,"dropped":0}
```

## GET /daq/read

Devuelve el siguiente bloque **binario** (`application/octet-stream`), little-endian:
cabecera de 16 B (`magic` u32 = `QDAQ`, `pv` u8, `sample_bytes` u8, `n` u16, `dropped`
u32 acumulado, `t_now` u32) seguida de `n` muestras de 16 B: `t_us` u32, `th_deg` f32,
`al_deg` f32 (**sin envolver**), `pwm` i16, `mode` u8, `flags` u8.

`t_us` es el `micros()` **del tick que produjo la muestra**, no el del envío: por eso la
latencia del transporte no degrada la serie. Un bloque con `n=0` es normal — significa
que se preguntó antes de que hubiera muestras nuevas.

Contrato de **un solo consumidor**: una segunda petición concurrente recibe `503` con
`Retry-After` en vez de datos posiblemente pisados. `src/qube_daq/` ya lo maneja.

```bash
curl "http://192.168.4.1/daq?start=1&decim=1"
curl -s --output bloque.bin http://192.168.4.1/daq/read
curl "http://192.168.4.1/daq?stop=1"
```

## GET /cmd

Envía comandos de configuración y control.

| Parámetro                   | Tipo   | Descripción               |
| ---------------------------- | ------ | -------------------------- |
| `m`                        | 0–7   | Modo de operación (ver tabla abajo) |
| `s`                        | float  | Setpoint servo (grados)    |
| `sp`                       | int    | PWM máx. swing-up (10–100) |
| `ec`                       | float  | Techo de energía del bombeo, `E/E*` (0.2–3.0, def. 1.15). Por encima, el swing-up deja de inyectar. Sin esto la ley resonante se realimenta y el péndulo se embala (P18) |
| `p`                        | int    | PWM manual (−255 a 255)   |
| `kp`, `ki`, `kd`       | float  | PID gains servo            |
| `va`                       | float  | Alpha filtro EMA velocidad servo |
| `ff`                       | float  | Feedforward PWM (compensación gravitacional) |
| `se`                       | 0–15   | Kick anti-fricción m2: \|err\| mín. en grados para aplicarlo (def. 2) |
| `sk`                       | 0–60   | Kick anti-fricción m2: piso de PWM (def. 30) |
| `gs`                       | 0/1    | Toggle gain scheduling dual-mode |
| `kpf`, `kif`, `kdf`    | float  | PID gains modo fino (requiere `gs=1`) |
| `kpc`, `kic`, `kdc`    | float  | PID gains modo grueso (requiere `gs=1`) |
| `lqr1`, `lqr2`, `lqr3`, `lqr4` | float | Ganancias LQR K1–K4 (modos 4 y 7). También por serial desde v1.59.0: `lqr1<val>`…`lqr4<val>` — antes se anunciaban en la ayuda y no existía `case 'l'`, así que caían en `default` |
| `lqr2n`, `lqr4n`, `lqrnd` | float | Gain scheduling del LQR, banda *near*: K2, K4 y el umbral en grados |
| `lqr2vn`, `lqr4vn`, `lqrvnd` | float | Ídem banda *very near* |
| `lqrdamp`                  | float  | Término de amortiguamiento cerca de la vertical |
| `lpm`                      | 20–150 | **Techo de PWM del LQR** (def. 70). Hasta v1.58.9 `LQR_PWM_MAX` no era el límite operativo: un `70` literal re-acotaba la salida en las cinco ramas del centering, así que subir la constante no tenía efecto. Con el techo en 70 sobre `PWM_MAX=200` la salida está saturada el 93 % del tiempo y las cuatro ganancias no pueden influir (P4/H3) |
| `tn`                       | float  | Umbral de traspaso m5→m4 en grados (`swingupCatchDeg`, def. 155). Medido: el cruce por cero de la utilidad del traspaso cae en α ≈ 158°, o sea que 155 queda del lado inservible; `tn=162` mejora de forma reproducible |
| `tr`                       | 0/1    | Habilita el traspaso automático m5→m4 (def. 1). `tr=0` deja al swing-up bombeando sin entregar |
| `rt`                       | 0/1    | **Reintento automático del swing-up** tras un intento de balanceo fallido (def. **1**, activo). Con `rt=0` un intento fallido cae a modo 0 como antes de v1.63.0, que es el comportamiento contra el que se mide el A/B |
| `rtn`                      | 0–20   | Presupuesto de reintentos automáticos **consecutivos** (def. 3). Escribirlo pone el contador en 0. `rtn=0` deja el reintento habilitado pero sin presupuesto |
| `pl`                       | 0/1    | Ley de bombeo: 0 = resonante (histórica), 1 = energía (Åström-Furuta) |
| `pg`, `pn`, `pc`, `pr` | float  | Parámetros de la ley de bombeo: ganancia, ruido/umbral, recentrado y tope de la referencia de posición |
| `he`                       | 90–179 | Modo 7 híbrido: \|α\| en grados para **entrar** al LQR. Con `he=179` el traspaso prácticamente no dispara y la política balancea sola — la única prueba honesta de una política de 50 Hz sobre el hardware |
| `hx`                       | 60–175 | Modo 7 híbrido: \|α\| para **volver** a la política |
| `hcm`, `hcg`, `hcp`, `hca` | float | Catch del híbrido m7: duración (ms), ganancia, tope de PWM y ángulo. Hasta v1.59.2 existían **sólo** por serial (`L8`–`L11`) y, como abrir el serial reinicia la placa, eran inalcanzables durante una campaña: toda tanda de m7 corría con los defaults compilados |
| `lc`                       | 0–2000 | Duración del catch del LQR en ms (def. 400). **Durante el catch el LQR no corre** (la rama termina en `return`): con ω_n = 14,34 rad/s una desviación crece ×155 en 400 ms. `lc=0` lo desactiva y el LQR controla desde el primer tick (P4/H2) |
| `sz`                       | 0/1    | Fase de quietud + re-cero del péndulo al entrar al modo 5 (def. **1**, activa). Sin ella la referencia de α deriva entre intentos —medido: un péndulo colgando y quieto leía 82/97/91 y una vez −264°— y el bombeo trabaja contra un ángulo que no es el real (P22). `sz=0` reproduce el comportamiento previo a v1.58.8 |
| `cg`                       | 0/1    | Periodo de gracia del centering en m4 (def. 0 = comportamiento histórico). Con `cg=1` el centering espera 2 s tras el catch y rampa en otros 2, que es lo que el código decía hacer y nunca hizo (P4/H6) |
| `kf`                       | 0/1    | Toggle filtro de Kalman (LQG) |
| `ke`                       | float  | Ganancia de energía del swing-up. **≥ 0 fija un override manual** que la rama adaptativa respeta; **< 0 lo suelta** y devuelve el control a `KE_GAIN_BASE`/`BOOST`. El override sobrevive a `m=5` a propósito (⚠ ver nota) |
| `rj`                       | 1      | Reset de las métricas de salud del lazo (`loop_dt_max_us`, `loop_overruns`) |
| `cpr`                      | float  | CPR encoder servo          |
| `cprp`                     | float  | CPR encoder péndulo        |
| `ed`                       | −1, 1 | Dirección encoder servo    |
| `edp`                      | −1, 1 | Dirección encoder péndulo  |
| `o`                        | float  | Offset posición servo (grados) |
| `op`                       | float  | Offset posición péndulo (grados) |
| `z`                        | 1      | Zero position servo        |
| `zp`                       | 1      | Zero position péndulo     |
| `tp`                       | int    | Período de telemetría (ms, 50–5000) |
| `sv`                       | 0/1    | Línea de telemetría por Serial (def. 1). `sv=0` la apaga: son ~120 caracteres cada `tp`, unos 10 ms de UART a 115200 contra un período de lazo de 2 ms. Conviene apagarla durante una adquisición |
| `hr`                       | 0/1    | **Exigir homing antes de entrar a los modos 2/4/5/6/7** (def. **1**). `homing_ok` se escribía y publicaba desde v1.53 y ningún camino de código lo consultaba: se podía balancear con `positionOffsetDeg = 0`, o sea con toda la escalera de límites del servo (70/80/85/90/95°) medida contra un cero arbitrario. `hr=0` lo suelta para trabajo de banco, y `homing_required` queda en `/state` para que una campaña sepa con qué garantía midió |
| `sf`                       | 0/1    | **Exigir INA219 vivo** para energizar (def. **1**). Sin él, `applySafetyLimits()` saltea brownout y límite de corriente **enteros y en silencio** — el stub de la librería devuelve 0,0 en todo. `sf=0` lo suelta |
| `bcut`                     | 6–20 V | Tensión por debajo de la cual se corta el PWM (def. 12,5). Era un literal dentro de las ramas de m4 y m5, duplicado, y los scripts de campaña lo replicaban a mano |
| `bder`                     | 6–24 V | Tensión por debajo de la cual se escala el PWM linealmente hasta 0,3 (def. 13,5) |
| `ilim`                     | 0–5000 mA | Límite de corriente sostenida; **0 = desactivado**. Def. 2000 mA — observado en banco: 28 mA en reposo, 66 en m1, 278 de pico en m5. ⚠ El INA219 se lee a ~10 Hz, así que **no es un fusible rápido**: exige 3 lecturas seguidas por encima del límite (~300 ms) y sirve contra un calado, no contra un cortocircuito |
| `x`                        | 1      | Paro de emergencia         |
| `r`                        | 1      | Reset encoders + PID       |
| `wifi_ssid`, `wifi_pass` | str    | Guardar credenciales WiFi  |
| `wifi_reconnect`           | 1      | Reconectar WiFi            |

> **`bt` fue eliminado (2026-07-28).** Existía desde v1.20 y era configurable,
> pero ningún lazo leía `balance_threshold` desde que la transición del modo 5 se
> reescribió con umbrales fijos. Cualquier barrido de `bt` — incluido
> `experiments/2026-06-08_swing/sweep_bt.py` — midió ruido. El umbral real es hoy
> **`tn`** (`swingupCatchDeg`), y sí está expuesto por HTTP. (Este párrafo decía
> que vivía en `SWINGUP_TRANS_NEAR_DEG`; esa constante estaba muerta desde que las
> compuertas pasaron a `swingupCatchDeg` y se eliminó en v1.59.0.)
>
> **`ke` sigue sin calibrar, pero ya se puede barrer.** Hasta 2026-07-28 vivía
> dentro de una rama inalcanzable del modo 5. Después pasó a actuar, pero el propio
> lazo lo pisaba: `m=5` deja `swing_maxAngleAchieved` en 0 y el primer tick con
> \|α\| > 5° ejecutaba `ke_gain = KE_GAIN_BASE`, así que **todo barrido medía
> `KE_GAIN_BASE` contra sí mismo** (P23, cerrado en v1.59.0). Hoy `ke ≥ 0` fija un
> override que la rama adaptativa respeta, y `/state` publica `ke_gain` y
> `ke_override` para que una campaña verifique contra qué valor está midiendo —
> antes `ke_gain` no se publicaba en ninguna parte. Falta caracterizarlo en banco.
>
> **Los valores enviados por serial se validan desde v1.59.1.** `String::toFloat()`
> devuelve `0.0` ante cualquier basura: `qq` —un typo de `q<0..1>`— ponía la escala
> de par del modo 7 en **cero sin imprimir nada**. Lo mismo `s` (que en modo 2 mueve
> el brazo), `o` (el cero del servo) y `L6` (`lqr_K2`). Ahora se rechazan con un
> mensaje. Esto vale para el canal **serial**; los parámetros HTTP nunca tuvieron
> ese problema porque cada uno es un `hasParam` separado.

### Modos de operación

| Código | Nombre | Descripción |
| ------ | ------ | ----------- |
| 0 | Libre | Motor deshabilitado, encoders activos |
| 1 | PWM manual | PWM fijo, sin lazo |
| 2 | PID servo | Setpoint en grados, lazo cerrado |
| ~~3~~ | ~~PID péndulo~~ | **Código libre** — retirado en v1.34 (péndulo subactuado, PID directo no realizable). No se reutiliza: los IDs de modo son estables para no romper telemetría/datasets. |
| 4 | LQR | Control en espacio de estados (gain scheduling) |
| 5 | Swing-up | Levantamiento por energía |
| 6 | Deep RL (HTTP) | Control por agente SAC externo vía HTTP |
| 7 | Deep RL (on-device) | Inferencia on-device: red [36→64→64→1] en ESP32 |

## GET /rl_cmd

Envía acciones al agente RL (modo 6).

| Parámetro | Tipo  | Descripción                    |
| --------- | ----- | ------------------------------ |
| `a`     | float | Acción RL [−1.0, 1.0] → PWM  |
| `r`     | 1     | Reset encoders + estado RL     |
| `z`     | 1     | Zero encoder servo (offset, sin reset PID) |
| `zp`    | 1     | Zero encoder péndulo (offset)  |
| `scale` | 0–1  | Escala de par de la política RL. Lo leía **sólo el modo 7**; desde v1.59.0 también el 6, porque que la misma política vea una transferencia de par distinta según por dónde se despliegue es un riesgo de sim2real por sí mismo. Def. 1.0 = comportamiento anterior. Gemelo serial: `q<0..1>` |

## Comandos de uso frecuente

```bash
# Leer estado
curl -s http://192.168.4.1/state

# Modos: m0=stop, m1=PWM, m2=PID servo, m3=homing, m4=LQR, m5=swing-up, m6=RL HTTP, m7=RL on-device
curl "http://192.168.4.1/cmd?m=2&s=20"        # PID servo, setpoint 20°
curl "http://192.168.4.1/cmd?m=3"              # Homing por topes (mueve el brazo a ambos extremos)
curl "http://192.168.4.1/cmd?m=4"              # LQR péndulo invertido
curl "http://192.168.4.1/cmd?m=5"              # Swing-up
curl "http://192.168.4.1/cmd?m=6"              # Deep RL (agente externo)
curl "http://192.168.4.1/cmd?m=7"              # Deep RL (on-device)

# Ajustar PID servo
curl "http://192.168.4.1/cmd?kp=3.0&ki=0.5&kd=0.15"

# Ajustar LQR
curl "http://192.168.4.1/cmd?lqr1=2&lqr2=22&lqr3=1.5&lqr4=9"

# Activar filtro de Kalman
curl "http://192.168.4.1/cmd?kf=1"

# Swing-up
curl "http://192.168.4.1/cmd?m=5&ke=0.75"

# Leer estado RL (para agente SAC)
curl -s http://192.168.4.1/rl_state
curl "http://192.168.4.1/rl_cmd?a=0.5"

# Zeroear servo antes de ensayo RL
curl "http://192.168.4.1/rl_cmd?z=1"

# Zeroear péndulo
curl "http://192.168.4.1/rl_cmd?zp=1"


# Paro de emergencia
curl "http://192.168.4.1/cmd?x=1"
```
