# Pinout y Conexiones — QUBE ESP32

Referencia completa de conexiones pin por pin.

**Placa:** DOIT ESP32 DevKit V1, **30 pines** (módulo ESP32-WROOM-32). Es la única placa del proyecto desde el 2026-08-01; reemplazó a la variante de 38 pines sin cambiar ni un número de GPIO (ver `CHANGELOG.md` v1.57.1).

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
| LED de estado    | ESP32 GPIO13             | 330 Ω → ánodo LED verde; cátodo a GND                | ~3,6 mA desde el nivel alto de 3,3 V |
| Debug serial     | USB ESP32                | PC / monitor serie                                     | UART0 por USB                        |

## Configuración de pines ESP32

La columna **Posición** cuenta desde el extremo del conector USB (el pin 1 de cada fila es el más cercano al USB), para poder cablear contando posiciones en vez de buscar el serigrafiado con lupa.

| Pin     | Función               | Tipo         | Posición        | Notas                                |
| ------- | --------------------- | ------------ | --------------- | ------------------------------------ |
| GPIO13  | LED de estado         | Salida       | izq. #3 (D13)   | 330 Ω en serie; contiguo al GND de izq. #2 |
| GPIO21  | I2C SDA               | Bidireccional| der. #11 (D21)  | Pull-up interno                      |
| GPIO22  | I2C SCL               | Salida       | der. #14 (D22)  | Pull-up interno                      |
| GPIO25  | L298N ENA (PWM)        | Salida      | izq. #8 (D25)   | **Sin conectar en el montaje actual** (opción A). Solo se cablea en opción B, con el jumper ENA retirado |
| GPIO26  | L298N IN1              | Salida      | izq. #7 (D26)   | PWM adelante                         |
| GPIO27  | L298N IN2              | Salida      | izq. #6 (D27)   | PWM reversa                          |
| GPIO32  | Encoder péndulo A     | Entrada      | izq. #10 (D32)  | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO33  | Encoder péndulo B     | Entrada      | izq. #9 (D33)   | Schmitt + RC (10 kΩ/10 nF)         |
| GPIO34  | Encoder servo A       | Entrada      | izq. #12 (D34)  | Schmitt + RC (10 kΩ/10 nF), input-only |
| GPIO35  | Encoder servo B       | Entrada      | izq. #11 (D35)  | Schmitt + RC (10 kΩ/10 nF), input-only |
| VIN     | Entrada 5 V           | Alimentación | izq. #1         | Desde LM2596 #2 (riel dedicado)      |
| 3V3     | Salida 3.3 V          | Alimentación | der. #1         | Vcc de los CD40106BE ×2 + pull-ups 2.2 kΩ ×4 |
| GND     | Tierra                | Alimentación | izq. #2 / der. #2 | Cualquiera de las dos; una sola bajada al GND común (estrella) |

> **Nota:** GPIO34 y GPIO35 son pines input-only en el ESP32-WROOM-32. No soportan `INPUT_PULLUP` por firmware — los pull-ups deben ser externos.

### Mapa completo de los 30 pines

Tarjeta imprimible para el banco: **[`pinout_esp32_30.png`](pinout_esp32_30.png)** (se
regenera con `uv run python docs/hardware/pinout_esp32_30.py`). Es la misma información
que la tabla de abajo, dibujada en orden físico y con las trampas marcadas.

Vista desde arriba, con el USB hacia arriba. Posición #1 = el pin más cercano al USB.

| # | Fila izquierda | Asignación QUBE | # | Fila derecha | Asignación QUBE |
|---|---|---|---|---|---|
| 1 | `VIN` | **5 V ← LM2596 #2** (riel dedicado, anti-brownout) | 1 | `3V3` | **Vcc CD40106BE ×2 + pull-ups 2.2 kΩ ×4** |
| 2 | `GND` | **GND común** (estrella) | 2 | `GND` | **GND común** (basta una bajada) |
| 3 | `D13` | **LED de estado** → 330 Ω → LED verde → GND | 3 | `D15` | libre |
| 4 | `D12` | libre | 4 | `D2` | libre |
| 5 | `D14` | libre | 5 | `D4` | libre |
| 6 | `D27` | **L298N IN2** (PWM reversa) | 6 | `RX2` (GPIO16) | libre |
| 7 | `D26` | **L298N IN1** (PWM adelante) | 7 | `TX2` (GPIO17) | libre |
| 8 | `D25` | **L298N ENA** — sin conectar (opción A) | 8 | `D5` | libre |
| 9 | `D33` | **Encoder péndulo B** ← J4 | 9 | `D18` | libre |
| 10 | `D32` | **Encoder péndulo A** ← J4 | 10 | `D19` | libre |
| 11 | `D35` | **Encoder servo B** ← J4 (input-only) | 11 | `D21` | **INA219 SDA** |
| 12 | `D34` | **Encoder servo A** ← J4 (input-only) | 12 | `RX0` (GPIO3) | ⚠ UART0 del USB — no cablear |
| 13 | `VN` (GPIO39) | libre (input-only) | 13 | `TX0` (GPIO1) | ⚠ UART0 del USB — no cablear |
| 14 | `VP` (GPIO36) | libre (input-only) | 14 | `D22` | **INA219 SCL** |
| 15 | `EN` | reset — no cablear | 15 | `D23` | libre |

**Balance:** de los 30 pines, 14 están comprometidos (9 GPIO de señal + `D13` del LED de
estado + VIN + 3V3 + los dos GND) y 3 no son cableables (`EN` es el reset, `RX0`/`TX0` son
la UART0 del USB). Quedan **13 libres**: 11 GPIO de propósito general (`D12`, `D14`, `D15`,
`D2`, `D4`, `D5`, `D18`, `D19`, `D23`, más `RX2`/`TX2` si no se usa la UART2) y 2 input-only
sin pull-up (`VP`, `VN`). `D25` no cuenta como libre: queda reservado para la opción B del
ENA. `D18`/`D19`/`D22`/`D23` tampoco están del todo libres: son los que puentea el test
`test_encoder_pulse_loss` (ver `platformio.ini`).
`D2`, `D4`, `D5`, `D12` y `D15` son pines de strapping: usables, pero conviene dejarlos
para último si hace falta expandir, porque su nivel en el arranque decide el modo de boot.

> Verificar contra el serigrafiado de la placa antes de cablear: hay clones con las filas espejadas.

### Trampas de cableado de esta placa

- **IN1/IN2 quedan contiguos pero INVERTIDOS** (izq. #6-#7). El header baja `D27` (=IN2) y después `D26` (=IN1), mientras que el bloque del L298N va IN1, IN2. **Una cinta recta los permuta.** Y permutarlos no se nota hasta que se cierra un lazo: el modo 1 manual no aplica `MOTOR_DIR`, así que el brazo se mueve "bien", pero el PID, el LQR y el swing-up sí lo aplican y quedan en realimentación **positiva** — el brazo se fuga al tope. Con `MOTOR_DIR = -1` la relación correcta es **PWM crudo positivo → la posición BAJA**. Medido en banco el 2026-08-03: estaban permutados.
- **Los 4 canales de encoder ocupan 4 posiciones seguidas** (izq. #9 a #12), pero en el orden `33, 32, 35, 34` — que es **exactamente el inverso** del orden del conector J4 de la perfboard (`34, 35, 32, 33`, ver `perfboard_layout.py`). La cinta va cruzada extremo con extremo. Si se conecta "derecha", los dos encoders quedan intercambiados y el síntoma (el brazo mueve las cuentas del péndulo) no apunta al conector.
- **SDA y SCL no son contiguos:** entre GPIO21 (der. #11) y GPIO22 (der. #14) están RX0 y TX0. Correrse una posición desde SDA aterriza en la UART0 del USB — se pierde el flasheo por serie y el síntoma no parece un problema de I2C.
- **Pines que esta placa no expone:** GPIO0 y GPIO6–11 (flash SPI). Ninguno se usa en este montaje, por eso la migración desde la placa de 38 pines no requirió renumerar nada.
- **Ninguno de los GPIO en uso es pin de strapping** (0, 2, 4, 5, 12, 15), así que el cableado no puede dejar la placa en un modo de arranque equivocado. `D13` (LED de estado) se eligió por eso y porque cae contiguo al GND de izq. #2: el LED se cablea entre dos posiciones vecinas del header.
- **El LED de estado no es un "power on".** Queda apagado hasta que `setup()` configura el pin, así que *placa alimentada + LED apagado* significa que el firmware no llegó a `setup()`. Los patrones están en la tabla de `esp32_qube.ino` (`LED_PAT_*`): fijo = en reposo, 1 Hz = un modo con par, ~4 Hz = homing, doble destello = INA219 caído, ~8 Hz = corte de seguridad u homing FAIL, y tres destellos al arrancar.

> **Mecánica:** la DevKit V1 de 30 pines es más corta (y algo más angosta) que la de 38 pines. Si la placa va sobre zócalo o sobre una protoboard fija, medir el footprint antes de comprometer el montaje.

## Cableado de ENA (L298N)

| Opción                   | Jumper ENA   | Conexión ENA                | Cuándo usar          |
| ------------------------- | ------------ | ---------------------------- | ---------------------- |
| **A (recomendada, en uso)** | Dejar puesto | No conectar al ESP32       | PWM directo por IN1/IN2 |
| B (alternativa)           | Retirar      | ESP32 GPIO25 → ENA (señal) | PWM por ENA, IN1/IN2 solo fijan dirección |

> **Importante:** GPIO25 sí está expuesto en la DevKit V1 de 30 pines (izq. #8), así que la opción B sigue disponible en esta placa. El bloque ENA del L298N tiene 2 pines físicos: ENA (señal) y +5V, puenteados por el jumper. Con el jumper puesto (opción A, la usada), el PWM se aplica directamente en IN1/IN2 y GPIO25 queda libre. Si se retira el jumper (opción B), GPIO25 va solo al pin ENA (señal), nunca al pin +5V.
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
