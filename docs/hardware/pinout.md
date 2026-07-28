# Pinout y Conexiones — QUBE ESP32

Referencia completa de conexiones pin por pin.

## Tabla completa

| Subsistema       | Origen                   | Destino                                                | Notas                                |
| ---------------- | ------------------------ | ------------------------------------------------------ | ------------------------------------ |
| Potencia motor   | Transformador 15 V-2 A (+) | INA219 VIN+ → VIN− → L298N VS                       | 15 V directo, sin regular; en serie con INA219 |
| Potencia motor   | GND fuente               | L298N GND                                              | GND común obligatorio               |
| Lógica L298N    | LM2596 #1 (riel "lógica") | L298N VSS                                             | Lógica del módulo (jumper ENA puesto) |
| Motor DC         | L298N OUT1               | Motor terminal (+)                                     | Salida de potencia                   |
| Motor DC         | L298N OUT2               | Motor terminal (−)                                    | Salida de potencia                   |
| Control motor    | ESP32 GPIO26             | L298N IN1                                              | PWM adelante                         |
| Control motor    | ESP32 GPIO27             | L298N IN2                                              | PWM reversa                          |
| Encoder servo    | Canal A                  | 2.2 kΩ pull-up (3V3) → Schmitt → 10 kΩ + 10 nF → GPIO34 | Ver acondicionamiento                |
| Encoder servo    | Canal B                  | 2.2 kΩ pull-up (3V3) → Schmitt → 10 kΩ + 10 nF → GPIO35 | Ver acondicionamiento                |
| Encoder servo    | GND / +5V                | GND común / LM2596 #1 (riel "lógica")                | Referencia compartida                |
| Encoder péndulo | Canal A                  | 2.2 kΩ pull-up (3V3) → Schmitt → 10 kΩ + 10 nF → GPIO32 | Ver acondicionamiento                |
| Encoder péndulo | Canal B                  | 2.2 kΩ pull-up (3V3) → Schmitt → 10 kΩ + 10 nF → GPIO33 | Ver acondicionamiento                |
| Encoder péndulo | GND / +5V                | GND común / LM2596 #1 (riel "lógica")                | Referencia compartida                |
| INA219           | ESP32 GPIO21             | INA219 SDA                                             | I2C datos                            |
| INA219           | ESP32 GPIO22             | INA219 SCL                                             | I2C reloj                            |
| INA219           | ESP32 3V3                | INA219 VCC                                             | No conectar a 5 V                    |
| INA219           | GND común               | INA219 GND                                             | Referencia común                    |
| INA219           | Transformador 15V-2A (+) | INA219 VIN+                                            | Antes del L298N                      |
| INA219           | L298N VS                 | INA219 VIN−                                           | Después del shunt                   |
| Alimentación ESP32 | LM2596 #2 (riel dedicado) | ESP32 VIN                                           | Aislado del riel de lógica/encoders (anti-brownout) |
| Schmitt          | U1/U2 CD40106BE pin 14   | ESP32 3V3                                              | Vcc = 3.3 V (2 chips: U1 servo, U2 péndulo), toma el 3V3 del regulador interno de la ESP32 |
| Schmitt          | U1/U2 CD40106BE pin 7    | GND común                                             | Tierra de ambos chips                |
| Schmitt          | 100 nF ×2                | Pin 14 a pin 7 (uno por chip)                         | Bypass, lo más cerca de cada chip   |
| Debug serial     | USB ESP32                | PC / monitor serie                                     | UART0 por USB                        |

## Configuración de pines ESP32

| Pin     | Función               | Tipo         | Notas                                |
| ------- | --------------------- | ------------ | ------------------------------------ |
| GPIO21  | I2C SDA               | Bidireccional| Pull-up interno                      |
| GPIO22  | I2C SCL               | Salida       | Pull-up interno                      |
| GPIO25  | L298N ENA (PWM)        | Salida      | Solo opción A, jumper ENA retirado  |
| GPIO26  | L298N IN1              | Salida      | PWM adelante                         |
| GPIO27  | L298N IN2              | Salida      | PWM reversa                          |
| GPIO32  | Encoder péndulo A     | Entrada      | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO33  | Encoder péndulo B     | Entrada      | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO34  | Encoder servo A       | Entrada      | Schmitt + RC (10 kΩ/10 nF), input-only |
| GPIO35  | Encoder servo B       | Entrada      | Schmitt + RC (10 kΩ/10 nF), input-only |

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.

## Cableado de ENA (L298N)

| Opción                   | Jumper ENA   | Conexión ENA                | Cuándo usar          |
| ------------------------- | ------------ | ---------------------------- | ---------------------- |
| **A (recomendada, en uso)** | Dejar puesto | No conectar al ESP32       | PWM directo por IN1/IN2 |
| B (alternativa)           | Retirar      | ESP32 GPIO25 → ENA (señal) | PWM por ENA, IN1/IN2 solo fijan dirección |

> **Importante:** el bloque ENA del L298N tiene 2 pines físicos: ENA (señal) y +5V, puenteados por el jumper. Con el jumper puesto (opción A, la usada), el PWM se aplica directamente en IN1/IN2 y GPIO25 queda libre. Si se retira el jumper (opción B), GPIO25 va solo al pin ENA (señal), nunca al pin +5V.
>
> El firmware (`esp32_qube.ino`) ya está actualizado a L298N (comentarios e `IN1`/`IN2`); solo conserva referencias históricas a BTS7960 donde documenta la migración revertida (ver `CHANGELOG.md` v1.52.0). GPIO25 se sigue dejando en HIGH en `setup()` por herencia de esa etapa (era R_EN/L_EN del BTS7960); en el L298N actual (opción A, jumper puesto) esa salida no está conectada a nada — es inofensiva pero no cumple ninguna función.

## Topología de potencia

```
Transformador 15V-2A (+) ──┬── VIN+ [INA219] VIN- ──── L298N VS (15V motor, directo)
                           │                             └─ C: 470 µF electrolítico + 100 nF cerámico (en VS-GND)
                           │
                           ├── LM2596 #1 IN+ (riel "lógica")
                           │      └── LM2596 #1 OUT+ (5V) ──┬── L298N VSS (lógica)
                           │                                ├── Encoder VCC (5V, servo + péndulo)
                           │                                └─ C: 470 µF electrolítico + 100 nF cerámico (en 5V-GND)
                           │
                           ├── LM2596 #2 IN+ (riel dedicado ESP32)
                           │      └── LM2596 #2 OUT+ (5V) ──── ESP32 VIN
                           │                                └─ C: 1000 µF electrolítico + 100 nF cerámico (en 5V-GND)  ← anti-brownout
                           │
Fuente GND  ────────────────┴── GND común (topología estrella)
                              ├── L298N GND
                              ├── LM2596 #1 IN-
                              ├── LM2596 #2 IN-
                              ├── ESP32 GND (pin GND)
                              ├── INA219 GND
                              ├── CD40106BE GND (pin 7, ×2)
                              └── Encoder GND

Rail 3.3 V (regulador interno del ESP32 — pin 3V3):
ESP32 3V3 ──┬── U1/U2 CD40106BE Vcc (pin 14, ×2) ── C: 100 nF bypass por chip (pin 14-pin 7)
            ├── Pull-ups 2.2 kΩ ×4 de los encoders (fijan nivel alto = 3.3 V)
            └─ C: 10 µF electrolítico + 100 nF cerámico (en 3V3-GND, junto al pin 3V3)
```

> **Nota — dos LM2596, no uno:** antes había un solo LM2596 compartido entre la ESP32, la lógica del driver y los encoders. Ahora el riel "lógica" (LM2596 #1) alimenta el L298N y el VCC de los encoders, mientras que el riel dedicado (LM2596 #2) alimenta **únicamente** la ESP32. Separarlos aísla a la ESP32 del ruido de conmutación del L298N y de la corriente variable de los encoders, y deja el condensador anti-brownout de 1000 µF actuando solo sobre la carga que de verdad le preocupa (la ESP32).
>
> El pull-up de los encoders y el Vcc del CD40106BE van al rail **3.3 V** (pin 3V3 del ESP32), **no** al de 5 V — esto no cambió. El encoder se alimenta a 5 V, pero al ser open-drain su nivel alto lo fija el pull-up: tirar a 3.3 V deja la señal en 0/3.3 V (compatible con los GPIO) y evita la corriente de clamp que aparecería al tirar a 5 V contra un chip alimentado a 3.3 V.

## Condensadores de desacople y bulk

Cada rail necesita un condensador **bulk** (electrolítico, reserva de energía para picos de corriente) en paralelo con uno **cerámico** (100 nF, baja impedancia en alta frecuencia). El cerámico solo no basta para los transitorios del motor; el electrolítico solo es lento ante el ruido de conmutación.

| Rail / punto                    | Bulk (electrolítico) | HF (cerámico) | Función                                                                 |
| -------------------------------- | --------------------- | ------------- | ----------------------------------------------------------------------- |
| **5 V ESP32** (LM2596 #2 OUT)    | **1000 µF / 10 V**   | 100 nF        | **Anti-brownout:** sostiene el bus de la ESP32 durante el pico de corriente del swing-up (causa del 20 % de crashes). Lo más cerca del ESP32 VIN. |
| **5 V lógica** (LM2596 #1 OUT)   | 470 µF / 10 V         | 100 nF        | Sostiene el riel de lógica del L298N + encoders frente a la conmutación; ya no comparte carga con la ESP32. |
| **15 V** (L298N VS)              | 470 µF / 25 V        | 100 nF        | Absorbe los transitorios inductivos del motor; evita que la caída de VS llegue a los reguladores. En los bornes VS–GND del L298N. |
| **3.3 V** (pin 3V3)              | 10 µF                | 100 nF        | Estabiliza el rail lógico compartido por ESP32 y CD40106BE. Junto al pin 3V3. |
| **CD40106BE Vcc** (×2 chips)     | —                    | 100 nF ×2      | Bypass de conmutación del Schmitt. Entre pin 14 y pin 7, pegado a cada chip. |
| **Motor (opcional)**             | —                    | 100 nF ×3     | Supresión de ruido de escobillas: uno entre bornes M+/M− y uno de cada borne a la carcasa. Cerámicos de 100 V. |

> **Prioridad:** el condensador **1000 µF en el rail de 5 V de la ESP32 es el crítico** — es la solución directa al brownout documentado en el Capítulo 7 (instalar 470–1000 µF en el rail de 5 V). Un valor mayor da más margen; respetar la polaridad y un voltaje nominal ≥ 2× el del rail (≥ 10 V para 5 V, ≥ 25 V para 15 V).
