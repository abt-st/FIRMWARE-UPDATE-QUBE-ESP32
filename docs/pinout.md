# Pinout y Conexiones — QUBE ESP32

Referencia completa de conexiones pin por pin.

## Tabla completa

| Subsistema       | Origen                   | Destino                                                | Notas                                |
| ---------------- | ------------------------ | ------------------------------------------------------ | ------------------------------------ |
| Potencia motor   | Fuente 15 V (+)          | BTS7960 VS                                             | Alimentación del half-bridge        |
| Potencia motor   | GND fuente               | BTS7960 GND                                            | GND común obligatorio               |
| Lógica BTS7960  | LM2596 5 V               | BTS7960 VCC                                            | Lógica del módulo IBT-2            |
| Motor DC         | BTS7960 M+               | Motor terminal (+)                                     | Salida de potencia                   |
| Motor DC         | BTS7960 M-               | Motor terminal (−)                                    | Salida de potencia                   |
| Control motor    | ESP32 GPIO26             | BTS7960 RPWM                                           | PWM adelante                         |
| Control motor    | ESP32 GPIO27             | BTS7960 LPWM                                           | PWM reversa                          |
| Encoder servo    | Canal A                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO34 | Ver acondicionamiento                |
| Encoder servo    | Canal B                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO35 | Ver acondicionamiento                |
| Encoder servo    | GND / +5V                | GND común / Alimentación                             | Referencia compartida                |
| Encoder péndulo | Canal A                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO32 | Ver acondicionamiento                |
| Encoder péndulo | Canal B                  | 4.7 kΩ pull-up → Schmitt → 10 kΩ + 10 nF → GPIO33 | Ver acondicionamiento                |
| Encoder péndulo | GND / +5V                | GND común / Fuente auxiliar 5 V                       | Referencia compartida                |
| INA219           | ESP32 GPIO21             | INA219 SDA                                             | I2C datos                            |
| INA219           | ESP32 GPIO22             | INA219 SCL                                             | I2C reloj                            |
| INA219           | ESP32 3V3                | INA219 VCC                                             | No conectar a 5 V                    |
| INA219           | GND común               | INA219 GND                                             | Referencia común                    |
| INA219           | (+) batería / LM2596 IN | INA219 VIN+                                            | Antes del BTS7960                    |
| INA219           | BTS7960 VS               | INA219 VIN−                                           | Después del shunt                   |
| Schmitt          | CD40106BE pin 14         | ESP32 3V3                                              | Vcc = 3.3 V (salida compatible GPIO) |
| Schmitt          | CD40106BE pin 7          | GND común                                             | Tierra del chip                      |
| Schmitt          | 100 nF                   | Pin 14 a pin 7                                         | Bypass, lo más cerca del chip       |
| Debug serial     | USB ESP32                | PC / monitor serie                                     | UART0 por USB                        |

## Configuración de pines ESP32

| Pin     | Función               | Tipo         | Notas                                |
| ------- | --------------------- | ------------ | ------------------------------------ |
| GPIO21  | I2C SDA               | Bidireccional| Pull-up interno                      |
| GPIO22  | I2C SCL               | Salida       | Pull-up interno                      |
| GPIO25  | BTS7960 EN (habilitar) | Salida      | Solo opción B (pull-up interno)     |
| GPIO26  | BTS7960 RPWM           | Salida      | PWM adelante                         |
| GPIO27  | BTS7960 LPWM           | Salida      | PWM reversa                          |
| GPIO32  | Encoder péndulo A     | Entrada      | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO33  | Encoder péndulo B     | Entrada      | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO34  | Encoder servo A       | Entrada      | Schmitt + RC (10 kΩ/10 nF), input-only |
| GPIO35  | Encoder servo B       | Entrada      | Schmitt + RC (10 kΩ/10 nF), input-only |

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.

## Cableado de EN (BTS7960)

| Opción                   | Conexión EN                  | Cuándo usar                    |
| ------------------------- | ----------------------------- | ------------------------------- |
| **A (recomendada)** | No conectar (pull-up interno) | PWM directo por RPWM/LPWM       |
| B (alternativa)           | ESP32 GPIO25 → EN            | Control por software del enable |

> **Importante:** El módulo IBT-2 tiene pines R_EN y L_EN que habilitan cada half-bridge. Vienen pull-up por defecto. Solo conectar GPIO25 si necesitas control por software del enable.

## Topología de potencia

```
Fuente 15V (+) ──┬── VIN+ [INA219] VIN- ──── BTS7960 VS (15V motor)
                 │
                 ├── LM2596 IN+
                 │      └── LM2596 OUT+ (5V) ──── ESP32 VIN
                 │                             ──── BTS7960 VCC (lógica)
                 │                             ──── Encoder VCC (5V)
                 │                             ──── CD40106BE Vcc (3.3V)
                 │
Fuente GND  ─────┴── GND común (topología estrella)
                    ├── BTS7960 GND
                    ├── LM2596 IN-
                    ├── ESP32 GND (pin GND)
                    ├── INA219 GND
                    ├── CD40106BE GND (pin 7)
                    └── Encoder GND
```
