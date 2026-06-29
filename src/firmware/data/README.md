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

| Recurso              | Método | Uso en la GUI                                                  |
| -------------------- | ------ | -------------------------------------------------------------- |
| `/`                  | GET    | Carga `index.html`                                            |
| `/ws`                | WS     | Telemetría en vivo → gráficas, badges KF/calibración, CSV     |
| `/cmd?<params>`      | GET    | Modo, setpoint, PWM, ganancias, calibración, KF, ff/va, tp, WiFi |
| `/rl_cmd?a=` `r=` `scale=` | GET | Acción RL / reset episodio / escala de PWM (sim2real)      |
| `/rl_state`          | GET    | Estado compacto `{th,al,thd,ald,pv}` en rad (botón + poll vivo) |
| `/update` (POST)     | POST   | Flashear firmware `.bin` (OTA) con barra de progreso          |
| `/fs` (POST)         | POST   | Subir archivos a SPIFFS (actualizar la GUI sin reflashear)    |
| `/restart`           | GET    | Reinicio del ESP32                                           |
| `/format`            | GET    | Formatear SPIFFS (con confirmación; borra la GUI)            |

Parámetros de `/cmd` emitidos por los paneles actuales: `m`, `s`, `p`, `x`,
`z`, `zp`, `r`, `kp/ki/kd`, `lqr1..4`, `ke`, `bt`, `sp` (PWM máx swing-up),
`gs`, `kpf/kif/kdf`, `kpc/kic/kdc`, `kf`, `ff`, `va`, `tp`, `o/op`, `ed/edp`,
`cpr/cprp`, `wifi_ssid/wifi_pass/wifi_reconnect`. `/rl_cmd`: `a`, `r`, `scale`.
La API HTTP completa está en [`docs/http_api.md`](../../../docs/http_api.md).

---

## Paneles

La GUI organiza los paneles en **pestañas** (Control · RL · Ctrl · Ajustes ·
Calib · Sistema · Datos) en la barra derecha; las 4 gráficas quedan fijas a la
izquierda con su valor instantáneo en el encabezado.

| Pestaña / Panel        | Función                                                      |
| ---------------------- | ----------------------------------------------------------- |
| **Gráficas (×4)**      | Servo (°), Péndulo (°), PWM (−255..255), Potencia (mW) + valor en vivo |
| **Control**            | Selector de modo, setpoint servo, PWM manual, Zero/Reset    |
| **RL**                 | Mode 6/7, obs en vivo, **slider `scale`** (PWM sim2real), acción manual, reset, poll vivo de `/rl_state` |
| **Ctrl**               | PID Servo, LQR, Swing-up (Ke/Thr/**PWMmax**), Gain Scheduling fino/grueso |
| **Ajustes**            | Toggle Kalman + telemetría KF, feedforward `ff`, filtro velocidad `va`, período de telemetría `tp` |
| **Calib**              | Lecturas raw/offset en vivo, offsets `o/op`, dirección `ed/edp`, counts-per-rev `cpr/cprp` |
| **An&aacute;lisis**          | Retrato de fase α vs α̇, m&eacute;trica de balance (% upright / hold actual / hold m&aacute;x) |
| **Sistema**            | OTA (`/update`), subir GUI a SPIFFS (`/fs`), WiFi STA, reiniciar / formatear |
| **Datos**              | Grabar / Exportar CSV (base o extendido) / Borrar (muestras desde el WebSocket) |

Extras de UX: badge **watchdog** (cuenta regresiva del auto-STOP en modo 1/6),
gr&aacute;fica de **acci&oacute;n RL aplicada**, y **presets** (localStorage) de
ganancias PID/LQR/swing-up/gain-scheduling/RL-scale.

> **Requiere firmware actualizado:** la acci&oacute;n RL (`rl_action`) y el badge de
> watchdog (`ms_since_cmd`) salen de campos nuevos en `getStateJson()`. Hay que
> reflashear el firmware (`pio run --target upload`) además de la GUI
> (`uploadfs`); si el firmware es viejo, esos widgets quedan en `--` sin romper
> el resto.

### Modos en el selector

`0` STOP · `1` PWM · `2` PID Servo · `4` LQR · `5` Swing-up · `6` Deep RL (HTTP) · `7` Deep RL (chip).

> El firmware acepta `m=0..7` (con un hueco en `m3`). El modo `m3` (PID péndulo)
> fue **removido** del firmware: el péndulo es un eslabón pasivo (sistema
> subactuado), por lo que un PID de posición directa sobre él no es realizable.

---

## Telemetría (`/ws`, JSON de `getStateJson()`)

Campos consumidos por la GUI: `mode`, `position_deg`, `setpoint_deg`,
`pend_position_deg`, `pwm`, `voltage_v`/`v_bus`, `i_ma`, `p_mw`,
`gain_scheduling`, `gain_mode`, `kf_enabled`, `kf_theta/alpha/dtheta/dalpha`,
`raw_position_deg`, `offset_deg`, `pend_raw_position_deg`, `pend_offset_deg`,
`encoder_dir`, `counts_per_rev`, `ina_ok`, `rl_action` (acción aplicada al
motor en modo 6/7), `ms_since_cmd` (edad del último comando → watchdog). El JSON
completo incluye además `count`, `enc_a/b`, `error_deg`, `pend_count`,
`v_shunt_mv`, etc.

> **Handshake de protocolo RL:** `/rl_state` devuelve `pv` (= `RL_PROTO_VERSION`,
> hoy `2`). La GUI lo muestra en un badge y avisa (amarillo) si no coincide con
> `EXPECTED_PV` en `index.html`. Al cambiar la convención sim de `/rl_state`,
> bumpeá `RL_PROTO_VERSION` en el firmware **y** `EXPECTED_PV` en la GUI.

> La columna CSV `voltage_v` se exporta desde `v_bus`. Cuando `ina_ok=false`
> las columnas de tensión/corriente/potencia quedan vacías (no se falsean con 0)
> y la gráfica de potencia muestra un hueco.

---

## Historial de auditoría / Plan de mejora

Auditoría de `index.html` (2026-06-18). Prioridad: 🔴 alta · 🟡 media · 🟢 baja.

### Actualización 2026-06-24 — sincronización + rediseño

Rediseño con pestañas y sincronización de la GUI con las capacidades del
firmware que estaban sin exponer:

| Área | Cambio |
| ---- | ------ |
| **RL sim2real** | Slider `rl_pwm_scale` (`/rl_cmd?scale=`); badge + chequeo de `pv` contra `EXPECTED_PV`; poll en vivo de `/rl_state` (obs en convención sim) |
| **Calibración** | Panel nuevo: offsets `o/op`, dirección `ed/edp`, counts-per-rev `cpr/cprp`, lecturas raw/offset en vivo |
| **Kalman / tuning** | Toggle `kf` + telemetría KF, feedforward `ff`, filtro velocidad `va`, `gain_mode` en badge, período `tp` |
| **Sistema** | `/restart`, subir GUI a SPIFFS (`/fs`), `/format` (con confirmación), WiFi STA (`wifi_ssid/pass/reconnect`) |
| **Swing-up** | Añadido `sp` (PWM máx) que faltaba |
| **Análisis** | Pestaña nueva: retrato de fase α vs α̇ (α̇ por diferencias finitas), métrica de balance (% upright / hold actual / hold máx con target/tol configurables) |
| **RL action** | Gráfica de `rl_action` aplicada + 2 campos de telemetría nuevos en firmware (`rl_action`, `ms_since_cmd`) |
| **Presets** | Guardar/cargar/borrar perfiles de ganancias en localStorage |
| **CSV** | Modo extendido opcional: `rl_action`, `alpha_dot`, `in_upright`, `kf_*` |
| **UX** | Badges de modo/gain/pv/watchdog; valor instantáneo en cada gráfica; tema con variables CSS; `aria-label`; colisión de id `sp`→`spt` resuelta |

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
| — | `m3` (PID péndulo) removido del firmware | — | Intencional: péndulo subactuado; control vía LQR (m4), swing-up (m5) y RL (m6/m7). |
