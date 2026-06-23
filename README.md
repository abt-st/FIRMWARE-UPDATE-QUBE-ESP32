# QUBE ESP32

[![License: CC BY 4.0](https://img.shields.io/badge/License-CC_BY_4.0-lightgrey.svg)](LICENSE)
[![Platform: ESP32](https://img.shields.io/badge/Platform-ESP32-000000.svg)](https://www.espressif.com/en/products/socs/esp32)
[![Firmware: PlatformIO](https://img.shields.io/badge/Firmware-PlatformIO-FF6F00.svg)](https://platformio.org/)
[![Python: 3.12+](https://img.shields.io/badge/Python-3.12+-3776AB.svg)](https://www.python.org/)
[![RL: SAC + SB3](https://img.shields.io/badge/RL-SAC%20+%20SB3-ff6f00.svg)](src/qube_rl/)

Plataforma de control educativo de péndulo rotatorio invertido basada en **ESP32 + BTS7960 + INA219 + LM2596 + CD40106BE**. Alternativa open-source al Quanser QUBE-Servo por **~$70 USD** (frente a $2,500–$3,500 USD del original).

Control PID, LQR con gain scheduling, swing-up por energía, filtro de Kalman (LQG), Deep Reinforcement Learning (SAC) con inferencia on-device, y servidor MCP para integración con agentes AI.

---

## Características

- **7 modos de operación** — libre, PWM, PID servo, LQR, swing-up, Deep RL (HTTP), Deep RL (on-device)
- **500 Hz** — control en lazo cerrado dual-core (FreeRTOS)
- **Encoders duales** — servo + péndulo con acondicionamiento Schmitt + RC
- **Telemetría INA219** — voltaje, corriente, potencia en tiempo real
- **WiFi** — HTTP REST + WebSocket + ArduinoOTA
- **Filtro de Kalman** — estimación LQG de velocidades sin ruido
- **Gain scheduling** — PID dual-mode (fino/grueso) y LQR 3 regímenes
- **Deep RL** — SAC sim-to-real con inferencia on-device (red [36→64→64→1] en ESP32)
- **Servidor MCP** — herramientas para flash, control HTTP, RL y análisis de datos

---

## Comparación

| Aspecto            | Quanser QUBE-Servo            | **QUBE ESP32**         |
| ------------------ | ----------------------------- | ---------------------- |
| **Costo**    | $2,500–$3,500 USD            | **$40–70 USD** |
| **Plataforma**   | DSP propietario               | ESP32 open-source      |
| **Software**     | MATLAB/Simulink (licencia)    | Python + Arduino IDE   |
| **Control**      | PID + LQR + Swing-up          | **+ DRL (SAC) on-device** |
| **Frecuencia**   | 1000 Hz                       | **500 Hz**       |
| **Conectividad** | Ethernet/USB                  | **WiFi**          |
| **OTA**          | No                            | **Sí**           |
| **MCP Server**   | No                            | **Sí**           |

---

## Arquitectura

```
┌──────────────────────────────────────────────────────────────┐
│                    QUBE SERVO MODERNIZADO                     │
│                    ESP32 + BTS7960 + INA219 + LM2596          │
└──────────────────────────────────────────────────────────────┘

ENTRADA: 15V (LiPo 4S o PSU de laboratorio)
    │
    ├── [LM2596] ──→ 5V rail
    │       ├── ESP32 VIN
    │       ├── BTS7960 VCC
    │       └── Encoder VCC
    │
    ├── [INA219] ── High-side sensing (I2C: GPIO21/22)
    │
    ├── [ESP32] ── Núcleo de control
    │       ├── Core 1: Control @ 500 Hz
    │       ├── Core 0: Telemetría + WiFi
    │       ├── GPIO26/27 → BTS7960 RPWM/LPWM
    │       ├── GPIO34/35 → Encoder Servo → Schmitt + RC
    │       └── GPIO32/33 → Encoder Péndulo → Schmitt + RC
    │
    └── [BTS7960] ── Motor DC
```

### Flujo de datos

```
                          ESP32 (FreeRTOS)
                         ┌──────────────────┐
Encoder Servo ─────►     │                  │
(GPIO34/35 + Schmitt)    │  task_control    │──► BTS7960 (PWM → Motor)
                         │  500 Hz          │
Encoder Péndulo ────►    │                  │
(GPIO32/33 + Schmitt)    └────────┬─────────┘
                                  │
                   INA219 (I2C)───┤──► task_ina219 (100 Hz)
                                  │
                                  ├──► task_telemetry (10 Hz)
                                  │         ├──► Serial (USB → PC)
                                  │         └──► WiFi (HTTP REST)
                                  │
                                  └──► task_wifi (event-driven)
```

---

## Hardware

| Componente                    | Cantidad | Precio aprox.  |
| ----------------------------- | -------- | -------------- |
| ESP32-WROOM-32                | 1        | $6–10 USD     |
| BTS7960 (IBT-2)              | 1        | $2–5 USD      |
| INA219                        | 1        | $2–4 USD      |
| LM2596 (buck converter)      | 1        | $1–3 USD      |
| CD40106BE (Schmitt Trigger)  | 1        | ~$0.50 USD    |
| Motor DC + encoder            | 1        | $15–30 USD    |
| Encoder péndulo               | 1        | $5–15 USD     |
| Pasivos (R, C)                | 14       | < $0.50 USD   |
| **Total (sin fuente)** |          | **$35–70 USD** |

> BOM completa con especificaciones: [`docs/bom.md`](docs/bom.md)

---

## Quick Start

### 1. Clonar

```bash
git clone https://github.com/abt-st/FIRMWARE-UPDATE-QUBE-ESP32.git
cd FIRMWARE-UPDATE-QUBE-ESP32
uv sync                           # Instalar dependencias Python
```

### 2. Ajustar LM2596

> ⚠️ **Antes de conectar el ESP32.** Medir con multímetro: girar potenciómetro hasta **5.00 V** exactos.

### 3. Compilar y flashear

```bash
cd src/firmware
pio pkg install
pio run --target upload
```

### 4. Verificar

```bash
pio device monitor --baud 115200
# Salida esperada:
# === QUBE ESP32 + BTS7960 + INA219 ===
# [ENC] Servo   CNT=0   POS=0.00°
# [ENC] Pendulo CNT=0   POS=0.00°
# [WIFI] Conectado a: QUBE-ESP32  IP: 192.168.4.1
# [MODO] Libre (m0)
```

### 5. Conectar y probar

```bash
# Leer estado
curl -s http://192.168.4.1/state

# Modo PID servo, setpoint 20°
curl "http://192.168.4.1/cmd?m=2&s=20"

# Swing-up
curl "http://192.168.4.1/cmd?m=5"

# Paro de emergencia
curl "http://192.168.4.1/cmd?x=1"
```

---

## Modos de operación

| Modo | Código | Descripción                              |
| ---- | ------ | ---------------------------------------- |
| Libre | `m0`  | Motor deshabilitado, encoders activos     |
| PWM manual | `m1`  | PWM fijo, sin lazo (`/cmd?p=100`)    |
| PID servo | `m2`  | Setpoint en grados, lazo cerrado (`/cmd?s=20`) |
| ~~PID péndulo~~ | ~~`m3`~~ | **Código libre.** Retirado en v1.34: el péndulo es un eslabón pasivo subactuado, un PID de posición directa no es realizable. No se reutiliza para mantener IDs estables. |
| LQR | `m4`  | Control en espacio de estados (gain scheduling) |
| Swing-up | `m5`  | Levantamiento por energía (`/cmd?m=5&ke=0.75`) |
| Deep RL (HTTP) | `m6`  | Control por agente SAC externo vía HTTP |
| Deep RL (on-device) | `m7`  | Inferencia on-device: red [36→64→64→1] en ESP32 |

> Documentación completa de parámetros: [`docs/http_api.md`](docs/http_api.md)

---

## Firmware

### Estructura

```
src/firmware/
├── esp32_qube/
│   ├── esp32_qube.ino   ← Firmware principal (~2290 líneas)
│   └── credentials.h          ← WiFi STA (gitignored)
├── data/                      ← GUI web embebida (SPIFFS) — ver data/README.md
│   └── index.html
└── platformio.ini             ← Configuración PlatformIO
```

> La **GUI web** servida por el ESP32 (`http://192.168.4.1/`) se documenta en
> [`src/firmware/data/README.md`](src/firmware/data/README.md).

### Tasks FreeRTOS

| Task               | Core   | Prioridad | Período       | Función                |
| ------------------ | ------ | --------- | -------------- | ----------------------- |
| `task_control`   | Core 1 | 5         | 2 ms (500 Hz)  | Leer encoders, PID/LQR, PWM |
| `task_ina219`    | Core 0 | 3         | 10 ms (100 Hz) | Leer INA219, filtrar    |
| `task_telemetry` | Core 0 | 2         | 100 ms (10 Hz) | JSON → Serial/WiFi     |

### Características del firmware

| Característica           | Descripción                                                       |
| ------------------------- | ----------------------------------------------------------------- |
| PCNT hardware             | Decodificación de encoder por hardware (X4 cuadratura)           |
| Gain scheduling           | PID dual-mode y LQR con 3 regímenes según \|α\|                  |
| Filtro de Kalman (LQG)    | Observador 4×2 para estimar velocidades sin ruido                 |
| Soft saturation           | Reducción gradual de PWM cerca de límites mecánicos              |
| Brake motor               | Frenado activo del H-bridge para parada rápida                   |
| INA219 watchdog           | Detección y auto-reconexión del sensor I2C                       |
| ArduinoOTA                | Actualización de firmware por WiFi                                |
| WebSocket                 | Endpoint `/ws` para comunicación bidireccional en tiempo real    |
| Feedforward               | PWM constante para compensar torque gravitacional                |
| On-device RL (modo 7)     | Forward pass de red neuronal [36→64→64→1] directamente en ESP32  |

### Parámetros PID por defecto

| Parámetro           | Servo (m2) | LQR (m4) |
| -------------------- | ---------- | -------- |
| `Kp`               | 3.0        | —       |
| `Ki`               | 0.5        | —       |
| `Kd`               | 0.15       | —       |
| `K1` (θ servo)    | —         | 2.0      |
| `K2` (α péndulo) | —         | 22.0     |
| `K3` (θ')         | —         | 1.5      |
| `K4` (α')         | —         | 9.0      |

### Gain scheduling LQR

| Régimen                  | Condición         | K2    | K4    |
| ------------------------- | ----------------- | ----- | ----- |
| Lejos del equilibrio     | \|α\| > 25°      | 22.0  | 9.0   |
| Cerca de la vertical     | \|α\| < 25°      | 30.0  | 15.0  |
| Muy cerca de la vertical | \|α\| < 5°       | 55.0  | 20.0  |

---

## Deep Reinforcement Learning

Pipeline completo sim-to-real con SAC (Soft Actor-Critic):

### Modo 6: RL por HTTP (entrenamiento + fine-tuning)

Agente SAC ejecuta en PC, se comunica con ESP32 a 50 Hz:

```bash
curl "http://192.168.4.1/cmd?m=6"          # Activar modo RL
curl -s http://192.168.4.1/rl_state        # Leer estado (rad)
curl "http://192.168.4.1/rl_cmd?a=0.5"    # Enviar acción
curl "http://192.168.4.1/rl_cmd?r=1"      # Reset episodio
```

### Modo 7: RL on-device (inferencia en ESP32)

Red neuronal exportada a C++ y compilada directamente en el firmware:

- **Arquitectura:** [36→64→64→1], ReLU, Hardtanh(-2, 2)
- **Observación:** 4 pasos × [θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇, action]
- **Pesos:** `models/policy_weights.h` (auto-generado por `export_rltools.py`)
- **Uso:** `curl "http://192.168.4.1/cmd?m=7"`

### Paquete `qube_rl`

```
src/qube_rl/
├── train.py              # Entrenamiento SAC con SB3
├── fast_train.py         # Entrenamiento rápido
├── auto_train.py         # Entrenamiento automatizado
├── finetune.py           # Fine-tuning en hardware real
├── inference.py          # Inferencia en hardware
├── export_rltools.py     # Exportar pesos a C++ (para modo 7)
├── rewards.py            # 8 funciones de recompensa configurables
├── envs/
│   ├── qube_sim.py       # Entorno Gymnasium simulado
│   ├── qube_real.py      # Entorno Gymnasium real (HTTP → ESP32)
│   └── qube_dynamics.py  # Modelo dinámico + domain randomization
└── wrappers/
    ├── history_wrapper.py      # Ventana de observaciones pasadas
    ├── control_frequency.py    # Control de frecuencia de muestreo
    ├── gently_terminating.py   # Terminación suave del episodio
    └── deadzone.py             # Zona muerta del actuador
```

#### Entrenamiento

```bash
uv run python -m qube_rl.train                           # Entrenar (200K steps default)
uv run python -m qube_rl.train --timesteps 500000        # Más pasos
uv run python -m qube_rl.train --reward swingup_balance  # Reward personalizado
```

#### Exportar a ESP32 (modo 7)

```bash
uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip
# Genera models/policy_weights.h → compilar firmware para incluir pesos
```

> Plan completo: [`docs/research/DRL_IMPLEMENTATION_PLAN.md`](docs/research/DRL_IMPLEMENTATION_PLAN.md)

---

## Paquetes Python

```
src/
├── firmware/                  ← Firmware ESP32 (PlatformIO) + GUI web (data/)
├── qube_rl/                   ← Deep RL (entrenamiento, inferencia, export)
└── qube_analysis/             ← Análisis de datos (plotter.py, metrics.py)
```

### MCP Server

Servidor MCP para integración con agentes AI (Claude, Cursor, etc.):

```bash
uv run mcp dev mcp/esp32_qube_server.py  # Desarrollo
```

**Herramientas disponibles:**

| Categoría     | Herramientas                                                          |
| ------------- | --------------------------------------------------------------------- |
| Firmware      | `pio_compile`, `pio_upload`, `pio_clean`, `pio_ota_flash`, `pio_serial_monitor` |
| Control HTTP  | `qube_connect`, `qube_get_state`, `qube_send_command`, `qube_set_pid`, `qube_stop_motor` |
| WiFi          | `qube_set_wifi`, `qube_wifi_reconnect`                               |
| Deep RL       | `qube_rl_get_state`, `qube_rl_send_action`, `qube_rl_reset`         |
| Análisis      | `read_csv_summary`, `analyze_pid_performance`, `list_experiments`     |

> Documentación completa: [`mcp/esp32_qube_server.py`](mcp/esp32_qube_server.py)

---

## GUI

La interfaz es una **GUI web embebida** servida por el propio ESP32 desde SPIFFS
(no requiere instalar nada en el PC).

1. Flashear firmware + filesystem (`pio run -t upload` y `pio run -t uploadfs`)
2. Conectar el PC a la red WiFi del ESP32 (`QUBE-ESP32` / `qube1234`)
3. Abrir `http://192.168.4.1/` en el navegador

**Panel de gráficas (4):** Servo (°), Péndulo (°), PWM (−255..255), Potencia (mW).
Incluye control de modos, recolección/exportación CSV, tuning PID/LQR/swing-up,
gain scheduling, Deep RL y flasheo OTA por web.

> Documentación completa: [`src/firmware/data/README.md`](src/firmware/data/README.md)
>
> _Nota: la antigua GUI de escritorio Tkinter (`gui/app.py`, `src/qube_ui/`) fue
> eliminada; la GUI web la reemplaza por completo._

---

## Comandos de desarrollo

```bash
make install     # uv sync
make lint        # uv run ruff check .
make format      # uv run ruff format .
make check       # lint + format (CI)
make typecheck   # uv run pyright .
make test        # uv run pytest -v
make clean       # Limpiar __pycache__, .pyc, etc.
make help        # Mostrar todos los goals
```

---

## Calibración

### Verificación de encoders

Al arrancar en modo `m0`, girar manualmente y verificar que `CNT` incremente/decremente correctamente.

### Dirección del motor

Si el encoder retrocede con PWM positivo, cambiar `MOTOR_DIR = -1` en firmware o invertir cables M+/M-.

### Sintonización PID (Ziegler-Nichols)

1. `Ki = 0`, `Kd = 0`
2. Incrementar `Kp` hasta oscilación con amplitud constante → `Ku`
3. Medir período de oscilación → `Tu`

$$K_p = 0.6 \cdot K_u \qquad K_i = \frac{2 K_p}{T_u} \qquad K_d = \frac{K_p \cdot T_u}{8}$$

---

## Solución rápida de problemas

| Síntoma                           | Causa probable                     | Solución                                         |
| ---------------------------------- | ---------------------------------- | ------------------------------------------------- |
| `CNT` no cambia al girar encoder | Falta pull-up o Schmitt trigger    | Verificar circuito de acondicionamiento ([docs](docs/signal_conditioning.md)) |
| Error de boot GPIO34/35           | `INPUT_PULLUP` en pin input-only  | Usar solo `INPUT` + pull-up externo             |
| PID diverge inmediatamente         | Motor invertido                    | Cambiar `MOTOR_DIR = -1` en firmware            |
| Derivativo oscila con ruido        | `Kd` demasiado alto              | Aumentar `alpha` del filtro EMA (0.12–0.20)    |
| ESP32 no responde por WiFi         | IP incorrecta                      | Verificar SSID/IP, usar modo AP `192.168.4.1`   |
| `VIN` se calienta                | Voltaje > 5.5 V                    | Ajustar LM2596 a 5.00 V con multímetro           |
| Modo 7 no responde                | Sin `policy_weights.h`            | Exportar pesos: `uv run python -m qube_rl.export_rltools` |

---

## Experimentos

Datos CSV organizados por experimento:

```
experiments/
├── 2026-05-07_pid_tuning/       ← Sintonización PID servo
├── 2026-05-13_encoder_test/     ← Prueba de encoders
├── 2026-06-01_swing/            ← Swing-up inicial
├── 2026-06-15_sweep_v3/         ← Sweep de parámetros
├── 2026-06-15_training/         ← Datos de entrenamiento RL
└── ...
```

> Ver [`experiments/README.md`](experiments/README.md) para detalles de cada experimento.

---

## Roadmap

- [x] Control PID posición servo (encoder 1)
- [x] Telemetría INA219 (V, I, P)
- [x] Acondicionamiento señal (Schmitt + RC)
- [x] Swing-up por energía (modo 5)
- [x] WiFi STA no-bloqueante + credenciales gitignored
- [x] GUI con modos LQR y Swing-up
- [x] Filtro de Kalman (LQG)
- [x] Gain scheduling (PID + LQR)
- [x] ArduinoOTA
- [x] Deep RL modo 6 (endpoints `/rl_state`, `/rl_cmd`)
- [x] Deep RL modo 7 (on-device inference, pesos en firmware)
- [x] Paquete `qube_rl` (entrenamiento, inferencia, export)
- [x] Servidor MCP (flash, control, RL, análisis)
- [x] Encoder de péndulo integrado (usado por LQR, swing-up y RL; el modo PID de péndulo fue descartado por subactuación)
- [ ] LQR péndulo invertido (modo 4) — validación
- [ ] SAC sim-to-real — fine-tuning completo en hardware
- [ ] Dashboard web en tiempo real (WebSocket)
- [ ] PCB Rev2.0 con acondicionamiento integrado

---

## Documentación

| Documento | Descripción |
| --- | --- |
| [`CHANGELOG.md`](CHANGELOG.md) | Historial de versiones del firmware |
| [`docs/bom.md`](docs/bom.md) | Bill of Materials completo |
| [`docs/pinout.md`](docs/pinout.md) | Conexiones pin por pin |
| [`docs/signal_conditioning.md`](docs/signal_conditioning.md) | Circuito CD40106BE Schmitt + RC |
| [`docs/http_api.md`](docs/http_api.md) | API HTTP completa (endpoints, parámetros) |
| [`docs/research/DRL_IMPLEMENTATION_PLAN.md`](docs/research/DRL_IMPLEMENTATION_PLAN.md) | Pipeline SAC sim-to-real |
| [`docs/MODELO_FISICO_SISTEMA_QUBE.md`](docs/MODELO_FISICO_SISTEMA_QUBE.md) | Ecuaciones del motor, encoder, péndulo |
| [`docs/research/`](docs/research/) | Papers, estado del arte |
| [`docs/validation/`](docs/validation/) | Marco científico, checklist |
| [`experiments/`](experiments/) | Datos CSV y notas de experimentos |

---

## Referencias

### Péndulos y control

- [Armandpl/furuta](https://github.com/Armandpl/furuta) — SAC + gSDE para Furuta pendulum (referencia principal DRL)
- [ebrahimabdelghfar/Rotary-Inverted-Pendulum](https://github.com/ebrahimabdelghfar/Rotary-Inverted-Pendulum) — LQR + Arduino
- [wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project](https://github.com/wjkaiser/Edukit_Rotary_Inverted_Pendulum_Project) — STM32 + MATLAB/Simulink
- [ferrolho/rotary-inverted-pendulum](https://github.com/ferrolho/rotary-inverted-pendulum) — Arduino + LQR

### RL y embebidos

- [ShawnHymel/pendulum-rl](https://github.com/ShawnHymel/pendulum-rl) — TinyRL en ESP32 real
- [mathworks/Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2](https://github.com/mathworks/Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2) — SAC + PPO para QUBE-Servo 2
- [rl-tools/rl-tools](https://github.com/rl-tools/rl-tools) — Librería C++ para RL en microcontroladores

### Papers clave

- Haarnoja et al. (2018). "Soft Actor-Critic." [ICML](https://arxiv.org/abs/1801.01290)
- Raffin et al. (2021). "Stable Baselines 3." [JMLR](https://jmlr.org/papers/v22/20-1364.html)
- Hazem & Bingül (2023). "Comprehensive review of pendulum structures." *IEEE Access*
- Quanser (2026). "Using RL Toolbox to Balance Qube-Servo 3." *Quanser Blog*

### Datasheets

- [BTS7960 — Infineon](https://www.infineon.com/dgdl/Infineon-BTS7960-DS-v01_00-en.pdf?fileId=5546d462518a448701518a525e3d3786)
- [LM2596 — TI](https://www.ti.com/product/LM2596)
- [INA219 — TI](https://www.ti.com/product/INA219)
- [CD40106B — TI](https://www.ti.com/lit/ds/symlink/cd40106b.pdf)

> Lista completa de papers académicos: [`docs/research/`](docs/research/)

---

## Licencia

CC BY 4.0 — ver [LICENSE](LICENSE) para detalles.
