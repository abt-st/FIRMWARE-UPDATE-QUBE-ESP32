# API HTTP — QUBE ESP32

Referencia completa de los endpoints HTTP del firmware.

## Dirección base

- **Modo AP:** `http://192.168.4.1`
- **Modo STA:** `http://<IP_del_ESP32>`

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

## GET /rl_state

Estado compacto de baja latencia para el agente RL (ángulos en radianes):

```json
{"th": 0.2654, "al": 3.0912, "thd": 0.0087, "ald": -0.0214}
```

| Campo  | Tipo   | Descripción                        |
| ------ | ------ | ---------------------------------- |
| `th`  | float  | θ del servo (radianes)            |
| `al`  | float  | α del péndulo (radianes)          |
| `thd` | float  | θ' (velocidad angular, rad/s)     |
| `ald` | float  | α' (velocidad angular, rad/s)     |

## GET /cmd

Envía comandos de configuración y control.

| Parámetro                   | Tipo   | Descripción               |
| ---------------------------- | ------ | -------------------------- |
| `m`                        | 0–7   | Modo de operación (ver tabla abajo) |
| `s`                        | float  | Setpoint servo (grados)    |
| `sp`                       | int    | PWM máx. swing-up (10–100) |
| `p`                        | int    | PWM manual (−255 a 255)   |
| `kp`, `ki`, `kd`       | float  | PID gains servo            |
| `va`                       | float  | Alpha filtro EMA velocidad servo |
| `ff`                       | float  | Feedforward PWM (compensación gravitacional) |
| `gs`                       | 0/1    | Toggle gain scheduling dual-mode |
| `kpf`, `kif`, `kdf`    | float  | PID gains modo fino (requiere `gs=1`) |
| `kpc`, `kic`, `kdc`    | float  | PID gains modo grueso (requiere `gs=1`) |
| `lqr1`–`lqr4`           | float  | LQR gains                  |
| `kf`                       | 0/1    | Toggle filtro de Kalman (LQG) |
| `ke`                       | float  | Ganancia swing-up          |
| `bt`                       | float  | Umbral transición LQR (grados) |
| `cpr`                      | float  | CPR encoder servo          |
| `cprp`                     | float  | CPR encoder péndulo        |
| `ed`                       | −1, 1 | Dirección encoder servo    |
| `edp`                      | −1, 1 | Dirección encoder péndulo  |
| `o`                        | float  | Offset posición servo (grados) |
| `op`                       | float  | Offset posición péndulo (grados) |
| `z`                        | 1      | Zero position servo        |
| `zp`                       | 1      | Zero position péndulo     |
| `tp`                       | int    | Período de telemetría (ms, 50–5000) |
| `x`                        | 1      | Paro de emergencia         |
| `r`                        | 1      | Reset encoders + PID       |
| `wifi_ssid`, `wifi_pass` | str    | Guardar credenciales WiFi  |
| `wifi_reconnect`           | 1      | Reconectar WiFi            |

### Modos de operación

| Código | Nombre | Descripción |
| ------ | ------ | ----------- |
| 0 | Libre | Motor deshabilitado, encoders activos |
| 1 | PWM manual | PWM fijo, sin lazo |
| 2 | PID servo | Setpoint en grados, lazo cerrado |
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

# Modos: m0=stop, m1=PWM, m2=PID servo, m4=LQR, m5=swing-up, m6=RL HTTP, m7=RL on-device (m3/PID péndulo fue removido)
curl "http://192.168.4.1/cmd?m=2&s=20"        # PID servo, setpoint 20°
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
curl "http://192.168.4.1/cmd?m=5&ke=0.75&bt=20"

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
