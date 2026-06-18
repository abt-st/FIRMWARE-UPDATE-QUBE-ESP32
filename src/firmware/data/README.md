# GUI Web embebida — QUBE ESP32

Dashboard HTML servido directamente por el ESP32 desde **SPIFFS**. Permite
monitorear y controlar el péndulo rotatorio desde cualquier navegador conectado
a la red del microcontrolador, sin instalar nada en el PC.

> Esta es la única GUI del proyecto. La antigua GUI de escritorio Tkinter
> (`gui/app.py`, `src/qube_ui/`) fue eliminada; esta GUI web la reemplaza.

---

## Archivos

```
src/firmware/data/            ← data_dir de PlatformIO (lo que se sube a SPIFFS)
├── index.html                ← GUI web activa
├── chart.min.js              ← Chart.js v4.5.1 (local, sin CDN)
└── README.md                 ← este archivo
```

`platformio.ini` no define `data_dir`, por lo que PlatformIO usa por defecto
`<dir-del-platformio.ini>/data` = `src/firmware/data/`. **Solo el contenido de
esta carpeta llega al ESP32.**

> Histórico: existía una copia divergente en `esp32_qube_l298n/data/` que no se
> subía a SPIFFS; se consolidó en este directorio y se eliminó.

---

## Cómo se sirve

El firmware monta SPIFFS y registra las rutas en `setup()`
(`esp32_qube_l298n.ino`):

```cpp
server.on("/", HTTP_GET, ...) → request->send(SPIFFS, "/index.html", "text/html");
server.serveStatic("/", SPIFFS, "/").setDefaultFile("index.html");
```

### Subir la GUI al ESP32

```bash
cd src/firmware
pio run --target buildfs      # empaqueta data/ → spiffs.bin
pio run --target uploadfs     # flashea la imagen SPIFFS
```

(Subir el firmware con `pio run --target upload` **no** actualiza la GUI;
hace falta `uploadfs` por separado.)

---

## Acceso

1. Flashear firmware + filesystem (arriba).
2. Conectar el PC a la red WiFi del ESP32:
   - **SSID:** `QUBE-ESP32`  ·  **Pass:** `qube1234`  ·  canal 6, máx. 4 clientes.
3. Abrir `http://192.168.4.1/` en el navegador.

> En modo STA (si `ENABLE_STA`), el ESP32 también es accesible por su IP en la
> red local (IP estática `192.168.100.50`).

---

## Endpoints que usa la GUI

| Recurso          | Método | Uso en la GUI                                              |
| ---------------- | ------ | --------------------------------------------------------- |
| `/`              | GET    | Carga `index.html`                                        |
| `/ws`            | WS     | Telemetría en vivo (~10 Hz) → gráficas y grabación CSV    |
| `/cmd?<params>`  | GET    | Cambiar modo, setpoint, PWM, ganancias PID/LQR/swing-up   |
| `/rl_cmd?a=` `r=`| GET    | Enviar acción RL / reset de episodio (modo 6)             |
| `/rl_state`      | GET    | Leer estado compacto `{th,al,thd,ald}` en rad (botón)     |

Parámetros de `/cmd` emitidos por los paneles actuales: `m`, `s`, `p`, `x`,
`z`, `zp`, `r`, `kp/ki/kd`, `lqr1..4`, `ke`, `bt`, `gs`, `kpf/kif/kdf`,
`kpc/kic/kdc`. La API HTTP completa está en
[`docs/http_api.md`](../../../docs/http_api.md).

---

## Paneles

| Panel                  | Función                                                      |
| ---------------------- | ----------------------------------------------------------- |
| **Gráficas (×4)**      | Servo (°), Péndulo (°), PWM (−255..255), Potencia (mW)      |
| **Control**            | Selector de modo, setpoint servo, PWM manual, Zero/Reset    |
| **Recolección de datos** | Grabar / Exportar CSV / Borrar (muestras desde el WebSocket) |
| **PID Servo**          | Kp, Ki, Kd                                                   |
| **LQR**                | K1..K4                                                       |
| **Swing-up**           | Ke (ganancia de energía), Thr (umbral de balanceo)          |
| **Deep RL**            | Acción manual, reset, "Set Mode 6", lectura de estado       |
| **Gain Scheduling**    | ON/OFF + ganancias modo fino (≤10°) y grueso (>10°)         |
| **Firmware OTA**       | Subir un `.bin` por web → `POST /update`, con barra de progreso |

### Modos en el selector

`0` STOP · `1` PWM · `2` PID Servo · `4` LQR · `5` Swing-up · `6` Deep RL (HTTP) · `7` Deep RL (chip).

> El firmware acepta `m=0..7`. El selector **no** expone `m3` (PID péndulo)
> porque ese modo será removido del firmware próximamente.

---

## Telemetría (`/ws`, JSON de `getStateJson()`)

Campos consumidos por la GUI: `mode`, `position_deg`, `setpoint_deg`,
`pend_position_deg`, `pwm`, `voltage_v`/`v_bus`, `i_ma`, `p_mw`,
`gain_scheduling`. El JSON completo incluye además `count`, `enc_a/b`,
`encoder_dir`, `counts_per_rev`, `raw_position_deg`, `error_deg`, `pend_count`,
`ina_ok`, `v_shunt_mv`, `kf_*`, etc.

> La columna CSV `voltage_v` se exporta desde `v_bus`. Cuando `ina_ok=false`
> las columnas de tensión/corriente/potencia quedan vacías (no se falsean con 0)
> y la gráfica de potencia muestra un hueco.

---

## Historial de auditoría / Plan de mejora

Auditoría de `index.html` (2026-06-18). Prioridad: 🔴 alta · 🟡 media · 🟢 baja.

### Resuelto en esta versión

| # | Hallazgo | Prio | Solución |
| - | -------- | ---- | -------- |
| 1 | Chart.js por CDN → no carga en modo AP (sin internet) | 🔴 | `chart.min.js` v4.5.1 local en `data/`, referenciado relativo |
| 2 | IDs `btnCSV` duplicados (uno muerto en la topbar) | 🔴 | Eliminado el botón muerto de la topbar |
| 3 | Dos `index.html` divergentes (`data/` vs `esp32_qube_l298n/data/`) | 🔴 | Consolidado en `data/`; carpeta legacy eliminada |
| 4 | CSV `voltage_v` no coincide con `v_bus` → columna vacía | 🟡 | Exporta desde `v_bus`; vacío si `ina_ok=false` |
| 5 | Falta panel OTA pese a que el firmware expone `/update` | 🟡 | Panel OTA reintegrado con barra de progreso |
| 6 | Modo `m7` ausente del selector | 🟡 | Añadido `7` Deep RL (chip) |
| 7 | "Set" de setpoint no forzaba `m2` | 🟡 | "Set Servo" envía `m=2&s=` y sincroniza el selector |
| 8 | Estado Deep RL solo por polling manual | 🟢 | `rlInfo` se actualiza en vivo desde el WebSocket |
| 11 | Sin favicon → 404 en cada carga | 🟢 | Favicon vacío vía `data:` URI |
| 12 | Sin guardas de `ina_ok=false` → se grafican 0 | 🟢 | Hueco en la gráfica y celdas CSV vacías |

### Pendiente

| # | Hallazgo | Prio | Notas |
| - | -------- | ---- | ----- |
| 9 | Sin autenticación / `ws://` plano | 🟢 | Aceptable solo en LAN aislada (AP del ESP32). No exponer a redes no confiables. |
| 10 | Handlers `onclick` inline (incompatibles con CSP estricta), sin `aria-label`/`<form>` | 🟢 | De-inlinar todos los handlers es un refactor amplio; diferido para no arriesgar la GUI compacta actual. |
| — | `m3` (PID péndulo) no expuesto en el selector | — | Intencional: el modo será removido del firmware próximamente. |
