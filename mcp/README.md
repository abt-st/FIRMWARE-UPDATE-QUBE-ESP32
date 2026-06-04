# MCP Server — QUBE ESP32

Server MCP (Model Context Protocol) para el proyecto QUBE Servo ESP32.
Proporciona herramientas para flasheo, control en vivo y análisis de datos.

## Requisitos

```bash
uv sync
```

## Ejecución

```bash
uv run python mcp/esp32_qube_server.py
```

El servidor se comunica por `stdio` (transporte estándar de MCP).

---

## Herramientas disponibles

### Firmware / PlatformIO

| Herramienta | Descripción | Ejemplo |
|---|---|---|
| `pio_compile` | Compila el firmware | `pio_compile(environment="esp32dev")` |
| `pio_upload` | Compila y sube por USB serial | `pio_upload()` |
| `pio_ota_flash` | Compila y flashea por WiFi (OTA) | `pio_ota_flash(ip="192.168.100.50")` |
| `pio_clean` | Limpia archivos de build | `pio_clean()` |
| `pio_serial_monitor` | Lee líneas del monitor serial | `pio_serial_monitor(baud=115200)` |
| `read_firmware_source` | Lee el código fuente completo | `read_firmware_source()` |
| `get_firmware_info` | Info del proyecto PlatformIO | `get_firmware_info()` |

### Control HTTP del ESP32 en vivo

| Herramienta | Descripción | Ejemplo |
|---|---|---|
| `qube_connect` | Configura IP y verifica conexión | `qube_connect(ip="192.168.100.50")` |
| `qube_get_state` | Estado actual (posición, modo, PWM, potencia) | `qube_get_state()` |
| `qube_send_command` | Envía comando genérico a `/cmd` | `qube_send_command(m=5, s=90)` |
| `qube_set_mode` | Cambia modo de operación | `qube_set_mode(mode=4)` |
| `qube_set_pid` | Configura parámetros PID | `qube_set_pid(kp=2.0, ki=0.5, kd=0.1)` |
| `qube_set_swing_up` | Configura swing-up (ke, threshold) | `qube_set_swing_up(ke=0.5, balance_threshold=20)` |
| `qube_stop_motor` | Detiene el motor (kill switch) | `qube_stop_motor()` |
| `qube_set_wifi` | Guarda credenciales WiFi en NVS | `qube_set_wifi(ssid="MiRed", password="clave1234")` |
| `qube_wifi_reconnect` | Reconecta WiFi con credenciales guardadas | `qube_wifi_reconnect()` |

### Análisis de datos

| Herramienta | Descripción | Ejemplo |
|---|---|---|
| `qube_list_experiments` | Lista CSVs de experimentos | `qube_list_experiments()` |
| `qube_read_csv` | Lee contenido de un CSV | `qube_read_csv(filename="test.csv")` |
| `qube_analyze_csv` | Extrae métricas (overshoot, settling, etc.) | `qube_analyze_csv(filename="test.csv")` |

### Recursos MCP

| Recurso URI | Descripción |
|---|---|
| `qube://project/structure` | Estructura del proyecto |
| `qube://firmware/changelog` | CHANGELOG del firmware |

---

## Modos de operación del ESP32

| Modo | Nombre | Descripción |
|---|---|---|
| 0 | STOP | Motor detenido |
| 1 | PWM Manual | Control directo de PWM (`p` parameter) |
| 2 | PID Servo | Control PID de posición del servo |
| 3 | PID Péndulo | Control PID de posición del péndulo |
| 4 | LQR Invertido | Controlador LQR para péndulo invertido |
| 5 | Swing-up | Bombeo de energía para llevar péndulo a vertical |

---

## Flasheo OTA (Over-The-Air)

El firmware incluye soporte ArduinoOTA para flasheo por WiFi sin cable USB.

### Primer flasheo (requiere USB)

```bash
pio run -e esp32dev --target upload
```

### Flasheos subsecuentes (WiFi)

```bash
# Desde terminal
pio run -e esp32dev_ota --target upload --upload-port 192.168.100.50

# Desde MCP
pio_ota_flash(ip="192.168.100.50")
```

### Requisitos OTA

- ESP32 conectado a la misma red que la PC
- Firmware con ArduinoOTA ya flasheado (el primer flash debe ser por USB)
- IP conocida (por defecto `192.168.100.50` en la configuración STA)

### Configuración OTA en `platformio.ini`

```ini
[env:esp32dev_ota]
extends = env:esp32dev
upload_protocol = espota
upload_port = 192.168.100.50
```

---

## Endpoint HTTP del ESP32

El ESP32 expone una API HTTP REST:

| Endpoint | Método | Descripción |
|---|---|---|
| `/state` | GET | Estado completo en JSON |
| `/cmd` | GET | Envía comandos (query params) |

### Parámetros de `/cmd`

| Param | Tipo | Descripción |
|---|---|---|
| `m` | int | Modo (0-5) |
| `s` | float | Setpoint en grados |
| `p` | int | PWM directo (-255 a 255) |
| `x` | int | Kill switch (1=stop) |
| `z` | int | Zero encoder |
| `kp` | float | Ganancia Kp |
| `ki` | float | Ganancia Ki |
| `kd` | float | Ganancia Kd |
| `ke` | float | Ganancia swing-up energía |
| `bt` | float | Umbral swing-up→LQR (grados) |
| `lqr1`-`lqr4` | float | Ganancias LQR |
| `cpr` | float | Cuentas por revolución |
| `ed` | int | Dirección encoder (±1) |

### Ejemplo con curl

```bash
# Leer estado
curl http://192.168.100.50/state

# Cambiar a swing-up
curl "http://192.168.100.50/cmd?m=5"

# Detener motor
curl "http://192.168.100.50/cmd?x=1"

# Ajustar PID
curl "http://192.168.100.50/cmd?kp=2.0&ki=0.5&kd=0.1"
```

---

## Arquitectura

```
mcp/esp32_qube_server.py
├── Herramientas PlatformIO (compile, upload, OTA)
├── Herramientas HTTP (connect, state, cmd, PID, WiFi)
├── Herramientas CSV (list, read, analyze)
└── Recursos (project structure, changelog)
```

El servidor MCP actúa como puente entre el agente AI y el ESP32:
1. **Flasheo**: invoca `pio` como subprocess para compilar/upload
2. **Control**: usa `requests` para HTTP GET al ESP32
3. **Análisis**: lee CSVs locales con métricas de control
