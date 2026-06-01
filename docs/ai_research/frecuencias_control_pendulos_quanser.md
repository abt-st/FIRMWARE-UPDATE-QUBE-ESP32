# Frecuencias de Control en Péndulos de Quanser

> Investigación realizada el 2026-06-01. Fuentes: documentación oficial Quanser, QUARC docs, MathWorks, blogs Quanser.

---

## 1. Límite de QUARC (Simulink + PC)

| Configuración | Frecuencia máxima | Período mínimo | Fuente |
|---|---|---|---|
| PC clock (bloques Immediate I/O) | **1 kHz** | 1 ms | [Quanser FAQ](https://www.quanser.com/faq/why-cant-i-set-my-sampling-rate-higher-than-1khz-below-1-ms-i-get-an-error-that-my-system-clock-does-not-support-this/) |
| DAQ timebase (HIL Read Timebase) | **>1 kHz** (depende de la DAQ) | < 1 ms | Mismo FAQ; requiere bloques `Timebase` en vez de `Immediate` |
| Q2-USB / Q8-USB en "Fast Mode" | >1 kHz | < 1 ms | Requiere configurar `update_rate` en Board-Specific Options |

> "The sampling rate is set in the fixed-step size field in the Simulink diagram Configuration Parameters" — el default típico para labs es **1 kHz** (step = 1e-3).

---

## 2. QUBE-Servo 2 — Frecuencias documentadas

| Aplicación | Frecuencia | Período | Fuente |
|---|---|---|---|
| Control de posición (disco inercia) — lab estándar | **500 Hz** | 2 ms | [Blog "Discrete Control with QUBE-Servo 2"](https://www.quanser.com/blog/control-systems/discrete-control-with-qube-servo-2/) |
| Control de posición (disco inercia) — baja frecuencia demo | **33.3 Hz** | 30 ms | Mismo blog |
| Control de estabilidad discreta | 33.3 Hz y 500 Hz | — | Blog "Discrete Stability" labs |
| LQR balance péndulo invertido | **500 Hz – 1 kHz** | 1–2 ms | Labs de curso de Quanser |
| Swing-up + balance péndulo | **500 Hz – 1 kHz** | 1–2 ms | [Blog "Rotary Pendulum Control Challenge"](https://www.quanser.com/blog/control-systems/rotary-pendulum-control-challenge-with-qube-servo/) |
| RL (TD3/SAC/PPO) — entrenamiento Simulink | **200 Hz** | 5 ms (Ts=0.005) | MathWorks: `Ts = 0.005` |
| RL — despliegue hardware via QUARC | **1 kHz** (típico) | 1 ms | Blog RL QUBE-Servo 3 |

### Detalle: Blog "Discrete Control with QUBE-Servo 2"

El blog de Quanser sobre control discreto demuestra explícitamente dos frecuencias de muestreo para el control de posición del disco de inercia:

- **500 Hz** — tasa de muestreo "alta", el rate estándar de operación.
- **33.3 Hz** — tasa "baja", diseñada para que los estudiantes observen los efectos de un muestreo insuficiente (aliasing, inestabilidad, oscilaciones).

Este es el punto de referencia más directo para el rate de control estándar del QUBE-Servo 2.

### Detalle: Labs de péndulo invertido

Los labs de balance y swing-up del QUBE-Servo 2 (PD, pole placement, LQR, energy-based swing-up) típicamente se ejecutan entre 500 Hz y 1 kHz. La frecuencia exacta depende del modelo de Simulink y la configuración de QUARC, pero **1 kHz es el default recomendado** por Quanser para labs de control de péndulo.

---

## 3. QUBE-Servo 3 — Datos adicionales

| Dato | Fuente |
|---|---|
| Encoder: 2 × 24-bit, cuadratura X4, **2048 CPR** | [QUBE-Servo 3 product page](https://www.quanser.com/products/qube-servo-3/) |
| Digital tachometer: 2 × 32-bit, resolución **13.8 ns** (counter de 72 MHz) | [QUARC docs](https://docs.quanser.com/quarc/documentation/qube_servo3_usb.html) |
| Python API: todos los ejemplos usan **`frequency = 1000.0`** Hz con `Clock.SYSTEM_CLOCK_1` | [Quanser Python API docs](https://docs.quanser.com/quarc/documentation/python/hardware/Functions/Task%20IO/control_functions.html) |
| RL blog: "Selecting the lowest sampling rate needed to perform the task will keep the training times reasonable" | [Blog Quanser 2026](https://www.quanser.com/blog/artificial-intelligence/using-the-reinforcement-learning-toolbox-to-balance-the-qube-servo-3-inverted-pendulum/) |

El QUBE-Servo 3 comparte la misma arquitectura DAQ integrada. El rate de control sigue siendo determinado por QUARC/Simulink, no por la DAQ interna (a diferencia de los DAQ externos como Q8-USB).

---

## 4. Rotary Inverted Pendulum (ROTPEN / QNET)

| Dato | Fuente |
|---|---|
| El QNET-ROTPEN usa NI myRIO o ELVIS III con QUARC/LabVIEW | NI docs, Quanser product page |
| Rate típico de balance: **1 kHz** (estándar de la industria para péndulos invertidos) | Papers académicos + docs Quanser |

---

## 5. Resumen de frecuencias por régimen

| Régimen | Frecuencia | Contexto |
|---|---|---|
| **Límite máximo PC clock** | **1 kHz** | QUARC con bloques inmediatos |
| **Límite máximo DAQ timebase** | **>1 kHz** | QUARC con bloques Timebase |
| **Python API (ejemplos)** | **1 kHz** | `task_start` con `SYSTEM_CLOCK_1` |
| **Péndulo invertido — balance LQR** | **500 Hz – 1 kHz** | Labs estándar |
| **Disco inercia — control posición** | **500 Hz** | Lab estándar |
| **Disco inercia — demo baja frecuencia** | **33.3 Hz** | Demo de efecto de muestreo |
| **RL entrenamiento (Simulink)** | **200 Hz** | `Ts = 0.005 s` (MathWorks) |
| **RL despliegue hardware** | **~1 kHz** | Via QUARC |

---

## 6. Comparación con nuestro firmware ESP32

| Parámetro | QUBE-Servo 2/3 (Quanser) | Nuestro ESP32 |
|---|---|---|
| Rate de control típico | 500 Hz – 1 kHz | **500 Hz** (`CONTROL_PERIOD_US = 2000`) |
| Encoder CPR (cuadratura X4) | 2048 | 2048 (Premotec 990412016913) |
| Resolución encoder tach | 13.8 ns (72 MHz counter) | Software (PCNT HW counter) |
| Driver motor | Amplificador integrado | L298N (H-bridge externo) |
| ADC corriente | 12-bit, filtrado sincronizado PWM | INA219 via I2C |

### Observaciones

1. **Nuestro ESP32 a 500 Hz está dentro del rango válido** de los labs de Quanser. No es sub-óptimo para la mayoría de aplicaciones de balance.

2. **Para alcanzar 1 kHz** sería necesario optimizar el loop del firmware (actualmente usa un `delay` basado en `micros()`). El ESP32 a 240 MHz tiene potencial suficiente, pero el overhead de WiFi, I2C (INA219), y el servidor HTTP async podrían introducir jitter.

3. **La degradación se vuelve seria por debajo de ~33 Hz**, según la demo de Quanser. Para el swing-up y balance, mantener ≥500 Hz es crítico.

4. **El tachometer de 13.8 ns** del QUBE-Servo 3 (basado en un counter de hardware de 72 MHz) es significativamente más preciso que nuestra estimación de velocidad derivada de la posición. Para LQR/estados de velocidad, la resolución del tachometer importa.

---

## Referencias

1. [Quanser FAQ — Why can't I set my sampling rate higher than 1kHz?](https://www.quanser.com/faq/why-cant-i-set-my-sampling-rate-higher-than-1khz-below-1-ms-i-get-an-error-that-my-system-clock-does-not-support-this/)
2. [Quanser Blog — Discrete Control with QUBE-Servo 2](https://www.quanser.com/blog/control-systems/discrete-control-with-qube-servo-2/)
3. [Quanser Blog — Rotary Pendulum Control Challenge with QUBE-Servo 2](https://www.quanser.com/blog/control-systems/rotary-pendulum-control-challenge-with-qube-servo/)
4. [Quanser Blog — RL to Balance the QUBE-Servo 3 Inverted Pendulum (2026)](https://www.quanser.com/blog/artificial-intelligence/using-the-reinforcement-learning-toolbox-to-balance-the-qube-servo-3-inverted-pendulum/)
5. [MathWorks — Train TD3 Agent to Control Quanser QUBE Pendulum](https://www.mathworks.com/help/reinforcement-learning/ug/train-td3-agent-to-control-quanser-qube-pendulum.html) — `Ts = 0.005`
6. [Quanser Python API — control_functions](https://docs.quanser.com/quarc/documentation/python/hardware/Functions/Task%20IO/control_functions.html) — `frequency = 1000.0`
7. [QUBE-Servo 3 Product Page](https://www.quanser.com/products/qube-servo-3/)
8. [QUARC Data Acquisition Card Support — QUBE-Servo 3](https://docs.quanser.com/quarc/documentation/qube_servo3_usb.html)
9. [MathWorks GitHub — RL Inverted Pendulum with QUBE-Servo2](https://github.com/mathworks/Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2)
