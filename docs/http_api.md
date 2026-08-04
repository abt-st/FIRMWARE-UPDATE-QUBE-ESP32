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
| `homing_range`      | float  | Recorrido total medido (grados). Medido en banco: **270°**; se acepta 250–290, fuera de eso aborta con `homing_fail=1` |
| `homing_center`     | float  | Centro calculado, adoptado como `offset_deg` |
| `pend_wraps`        | int    | Veces que se acotó la lectura del péndulo restando vueltas enteras. **Monotónico** (sólo se reinicia al arrancar): leerlo antes y después y sacar la diferencia. Un valor >0 en una corrida indica que el péndulo giró |
| `swing_trans_reason`| int    | Bitmask del criterio que disparó el traspaso m5→m4: `1`=near+slow, `2`=peak, `4`=forced, `8`=energy. `0` = no hubo traspaso en el intento en curso. Pueden coincidir varios |
| `swing_trans_alpha` | float  | `pendPos` **en el instante** del traspaso (muestrear el modo desde el cliente llega tarde y da otro ángulo) |
| `swing_trans_vel`   | float  | \|α̇\| en el traspaso (°/s) |
| `swing_trans_energy`| float  | `E/E*` en el traspaso; `1.0` = energía justa para llegar a vertical |
| `swing_trans_ms_ago`| int    | ms desde el traspaso; `0` = no hubo. `setMode(5)` limpia el latch |
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
| `lqr1`–`lqr4`           | float  | LQR gains                  |
| `lc`                       | 0–2000 | Duración del catch del LQR en ms (def. 400). **Durante el catch el LQR no corre** (la rama termina en `return`): con ω_n = 14,34 rad/s una desviación crece ×155 en 400 ms. `lc=0` lo desactiva y el LQR controla desde el primer tick (P4/H2) |
| `cg`                       | 0/1    | Periodo de gracia del centering en m4 (def. 0 = comportamiento histórico). Con `cg=1` el centering espera 2 s tras el catch y rampa en otros 2, que es lo que el código decía hacer y nunca hizo (P4/H6) |
| `kf`                       | 0/1    | Toggle filtro de Kalman (LQG) |
| `ke`                       | float  | Ganancia swing-up (⚠ ver nota) |
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
| `x`                        | 1      | Paro de emergencia         |
| `r`                        | 1      | Reset encoders + PID       |
| `wifi_ssid`, `wifi_pass` | str    | Guardar credenciales WiFi  |
| `wifi_reconnect`           | 1      | Reconectar WiFi            |

> **`bt` fue eliminado (2026-07-28).** Existía desde v1.20 y era configurable,
> pero ningún lazo leía `balance_threshold` desde que la transición del modo 5 se
> reescribió con umbrales fijos. Cualquier barrido de `bt` — incluido
> `experiments/2026-06-08_swing/sweep_bt.py` — midió ruido. El umbral real vive
> ahora en `SWINGUP_TRANS_NEAR_DEG` (firmware) y no está expuesto por HTTP.
>
> **`ke` no está calibrado.** Hasta la misma fecha vivía dentro de una rama
> inalcanzable del modo 5 (la velocidad del péndulo era idénticamente cero), así
> que tampoco afectaba al comportamiento. Ahora sí actúa, pero hay que
> caracterizarlo desde cero en banco. Ver `docs/auditoria_firmware.md`, F1.

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
