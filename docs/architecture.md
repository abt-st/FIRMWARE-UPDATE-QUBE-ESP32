# Arquitectura del Sistema QUBE Servo Modernizado

> Diagramas, pinout, flujo de datos y especificaciones técnicas de la plataforma.

---

## 1. Diagrama de Bloques

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     ARQUITECTURA QUBE SERVO MODERNIZADO                  │
│                     ESP32 + LM2596 + INA219 + L298N                      │
└─────────────────────────────────────────────────────────────────────────┘

ENTRADA: 12V (batería LiPo 3S o PSU de laboratorio)
    │
    ├── [LM2596 Buck Converter] ──→ 5V rail para lógica
    │       │
    │       ├── ESP32 VIN (5V → 3.3V interno AMS1117)
    │       ├── L298N 5V (lógica del driver)
    │       └── Encoder VCC (5V)
    │
    ├── [INA219] High-side current sensing
    │       VIN+ ← 12V fuente
    │       VIN- → L298N VS (12V motor)
    │       I2C: SDA=GPIO21, SCL=GPIO22
    │
    ├── [ESP32-WROOM-32] Núcleo de control
    │       ├── Core 1: Control PID @ 200 Hz
    │       ├── Core 0: Telemetría + WiFi
    │       ├── GPIO26 → L298N IN1 (PWM+)
    │       ├── GPIO27 → L298N IN2 (PWM-)
    │       ├── GPIO34 → Encoder Servo A (pull-up 4.7kΩ)
    │       ├── GPIO35 → Encoder Servo B (pull-up 4.7kΩ)
    │       ├── GPIO32 → Encoder Péndulo A (futuro)
    │       ├── GPIO33 → Encoder Péndulo B (futuro)
    │       └── USB-UART → PC (depuración + GUI)
    │
    ├── [L298N Dual H-Bridge] Etapa de potencia
    │       ├── IN1/IN2: Dirección + PWM (jumper ENA habilitado)
    │       ├── OUT1/OUT2 → Motor DC (+/-)
    │       └── VS: 12V desde INA219 VIN-
    │
    └── [Motor DC + Encoder] Actuador
            ├── M+ / M- (OUT1/OUT2 del L298N)
            └── Encoder: A/B + GND + VCC (5V)
```

---

## 2. Flujo de Datos

```
Referencia (setpoint en °)
    │
    ▼
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  GUI Python  │◄───►│  ESP32 HTTP  │◄───►│  Firmware    │
│  (monitoreo) │     │  /state      │     │  (FreeRTOS)  │
│              │     │  /cmd        │     │              │
│  - Tkinter   │     │              │     │  - PID @200Hz│
│  - CSV log   │     │  WiFi AP     │     │  - Encoder   │
│  - Tiempo    │     │  192.168.4.1 │     │  - INA219    │
│    real      │     │              │     │  - Telemetry │
└──────────────┘     └──────────────┘     └──────┬───────┘
                                                 │
                    ┌────────────────────────────┼────────────┐
                    │                            │            │
                    ▼                            ▼            ▼
            ┌──────────────┐            ┌──────────────┐
            │   L298N PWM  │            │  Encoder A/B │
            │   (GPIO 26)  │            │  (GPIO 34/35)│
            │              │            │              │
            │  Motor DC ◄─┤            │  Cuadratura  │
            │              │            │  X4 decoder  │
            └──────────────┘            └──────┬───────┘
                                               │
                                               ▼
                                        ┌──────────────┐
                                        │  INA219 I2C  │
                                        │  (GPIO 21/22)│
                                        │              │
                                        │  V, I, P     │
                                        └──────────────┘
```

---

## 3. Pinout Completo

### 3.1 ESP32-WROOM-32

| GPIO | Función | Tipo | Destino | Notas |
|------|---------|------|---------|-------|
| GPIO21 | I2C SDA | Bidireccional | INA219 SDA | Pull-up interno 10kΩ |
| GPIO22 | I2C SCL | Salida (open-drain) | INA219 SCL | Pull-up interno 10kΩ |
| GPIO26 | L298N IN1 | Salida (PWM) | Control dirección + PWM | LEDC channel 1 |
| GPIO27 | L298N IN2 | Salida (PWM) | Control dirección + PWM | LEDC channel 2 |
| GPIO32 | Encoder péndulo A | Entrada | Futuro | Evitar pines de boot |
| GPIO33 | Encoder péndulo B | Entrada | Futuro | Evitar pines de boot |
| GPIO34 | Encoder servo A | Entrada (input-only) | Pull-up 4.7kΩ a 3.3V | ⚠️ Sin pull-up interno |
| GPIO35 | Encoder servo B | Entrada (input-only) | Pull-up 4.7kΩ a 3.3V | ⚠️ Sin pull-up interno |
| EN | Reset | Entrada | Botón reset | Pull-up interno |
| 3V3 | 3.3V output | Salida | Pull-ups encoder, INA219 VCC | AMS1117, ~800mA |

### 3.2 L298N

| Pin | Conectado a | Notas |
|-----|-------------|-------|
| VS (pin 8) | INA219 VIN- (12V motor) | Alimentación del motor |
| VSS (pin 9) | LM2596 5V | Lógica del driver |
| GND | GND común (estrella) | |
| IN1 | ESP32 GPIO26 | PWM + dirección |
| IN2 | ESP32 GPIO27 | PWM + dirección |
| ENA | Jumper habilitado | Sin cable al ESP32 |
| OUT1 | Motor M+ | Terminal positivo |
| OUT2 | Motor M- | Terminal negativo |

### 3.3 INA219

| Pin | Conectado a | Notas |
|-----|-------------|-------|
| VIN+ | Fuente 12V (+) | High-side sensing |
| VIN- | L298N VS | Después del shunt |
| SDA | ESP32 GPIO21 | I2C |
| SCL | ESP32 GPIO22 | I2C |
| VCC | ESP32 3V3 | 3V, no 5V |
| GND | GND común | |
| A0 | GND | Dirección 0x40 |
| A1 | GND | Dirección 0x40 |

### 3.4 Encoder Servo (Premotec 990412016913)

| Pin | Señal | Conectado a | Componente |
|-----|-------|-------------|------------|
| 1 | +5V | Fuente 5V | Alimentación encoder |
| 2 | Canal A | GPIO34 | Pull-up 4.7kΩ a 3.3V |
| 3 | GND | GND común | |
| 4 | Canal B | GPIO35 | Pull-up 4.7kΩ a 3.3V |
| 5 | Index | Sin conectar | No requerido |

### 3.5 LM2596

| Pin | Conectado a | Notas |
|-----|-------------|-------|
| IN+ | Fuente 12V (+) | Entrada de potencia |
| IN- | GND común | |
| OUT+ | L298N VSS, ESP32 VIN | 5V regulado |
| OUT- | GND común | |
| Adj | Potenciómetro | Ajustar a 5.00V |

---

## 4. Conexión de Potencia

```
                    ┌──────────────────────────────────────┐
                    │          TOPOLOGÍA DE POTENCIA        │
                    └──────────────────────────────────────┘

Fuente 12V (+) ──┬── VIN+ [INA219] VIN- ──── L298N VS (12V motor)
                 │
                 ├── LM2596 IN+
                 │      └── LM2596 OUT+ (5V) ──── ESP32 VIN
                 │                             ──── L298N VSS (lógica)
                 │                             ──── Encoder VCC (5V)
                 │
Fuente GND  ─────┴── GND común (STAR POINT)
                    ├── L298N GND
                    ├── LM2596 IN-
                    ├── ESP32 GND (pin GND)
                    ├── INA219 GND
                    └── Encoder GND
```

**Requerimientos:**
- Cable de retorno motor: AWG 16 mínimo (R < 0.05Ω)
- GND común en topología estrella (NO en cadena)
- Bypass capacitors: 470µF + 100µF en rail 5V
- Capacitor 100µF cerca del L298N

---

## 5. Acondicionamiento de Encoder

### 5.1 Encoder Servo (HW-FIX-1)

El encoder Premotec 990412016913 tiene salida open-drain. La solución implementada:

```
ESP32 3V3 (pin)
    │
    ├──[4.7kΩ]──┬── GPIO34 (INPUT)
    │            │
    │     Encoder A (open-drain) ──→ GND en estado bajo
    │            │                  → Hi-Z en estado alto
    │           GND
    │
    └──[4.7kΩ]──┬── GPIO35 (INPUT)
                 │
          Encoder B (open-drain) ──→ GND en estado bajo
                 │                  → Hi-Z en estado alto
                GND
```

**Validación:**
- Señal limpia 0V / 3.3V ✅
- CNT incrementa monótonamente ✅
- PID converge en 2-3 segundos ✅

### 5.2 Encoder Péndulo (Futuro)

Topología a definir según tipo de salida:
- **Open-drain:** Pull-up 4.7kΩ a 3.3V (igual que servo)
- **Push-pull 5V:** Divisor 10k/10k (~2.5V en GPIO)

---

## 6. Tasks FreeRTOS

| Task | Core | Prioridad | Período | Función | Carga estimada |
|------|------|-----------|---------|---------|----------------|
| `task_control` | 1 | 5 | 5ms (200Hz) | Leer encoders, PID, PWM | ~30% |
| `task_ina219` | 0 | 3 | 10ms (100Hz) | Leer INA219, filtrar | ~8% |
| `task_telemetry` | 0 | 2 | 100ms (10Hz) | JSON serial, HTTP | ~5% |
| `task_wifi` | 0 | 1 | Event-driven | Servidor WebSocket | <5% |

**Margen de seguridad:** ~45% para expansión (LQR, logging SD)

---

## 7. Especificaciones Técnicas

| Parámetro | Valor |
|-----------|-------|
| Frecuencia de control | 200 Hz (5ms) |
| Frecuencia de telemetría | 10 Hz (100ms) |
| Frecuencia INA219 | 100 Hz (10ms) |
| Resolución encoder | 2048 CPR × 4 (cuadratura X4) |
| Rango PWM | -255 a +255 (8-bit signed) |
| Rango setpoint | -180° a +180° |
| Banda muerta | ±0.8° |
| Anti-windup | INTEGRAL_LIMIT = 250 |
| Filtro derivativo | EMA, α = 0.12 |
| Comunicación | WiFi AP (192.168.4.1), HTTP REST |
| Peso firmware | ~150KB (con librerías) |

---

## 8. Diagrama de Estados del Firmware

```
         ┌─────────┐
         │  BOOT   │
         └────┬────┘
              │
              ▼
      ┌──────────────┐
      │   SETUP      │
      │  - WiFi AP   │
      │  - I2C scan  │
      │  - INA219    │
      │  - Encoders  │
      └──────┬───────┘
             │
             ▼
     ┌─────────────────┐
     │    LOOP MAIN    │
     │  (FreeRTOS)     │
     └────────┬────────┘
              │
     ┌────────┴────────┐
     │  Command Handler│
     │  (HTTP + Serial)│
     │                 │
     │  m0 → STOP      │
     │  m1 → PWM Manual│
     │  m2 → PID Pos.  │
     │  m3 → PID Pend. │
     │  m4 → LQR (fut) │
     └────────┬────────┘
              │
     ┌────────┴────────┐
     │  Control Loop   │
     │  (Core 1, 5ms)  │
     │                 │
     │  1. Read encoder │
     │  2. Compute PID  │
     │  3. Set PWM     │
     │  4. Update state │
     └──────────────────┘
```

---

## 9. Endpoints HTTP

### GET /state

```json
{
  "t": 1234567,
  "mode": 2,
  "count": 2048,
  "enc_a": 1,
  "enc_b": 0,
  "encoder_dir": 1,
  "counts_per_rev": 2048.0,
  "raw_position_deg": 45.2,
  "position_deg": 45.2,
  "offset_deg": 0.0,
  "setpoint_deg": 45.0,
  "error_deg": 0.2,
  "pwm": 12,
  "ina_ok": true,
  "v_bus": 11.8,
  "v_shunt_mv": 45.0,
  "i_ma": 380.5,
  "p_mw": 4490.0
}
```

### GET /cmd

| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `m` | 0-4 | Modo de operación |
| `s` | float | Setpoint en grados |
| `p` | int | PWM manual (-255 a 255) |
| `kp` | float | Ganancia proporcional |
| `ki` | float | Ganancia integral |
| `kd` | float | Ganancia derivativa |
| `cpr` | float | Counts per revolution |
| `ed` | -1, 1 | Dirección encoder |
| `z` | 1 | Zero position here |
| `x` | 1 | Emergency stop |

---

*Última actualización: Mayo 26, 2026*