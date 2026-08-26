# Acondicionamiento de Señal — 2× CD40106BE Schmitt Trigger + RC

Referencia completa del circuito de acondicionamiento de señal para los **dos encoders** (servo y péndulo), con **doble inversión** en cada canal sobre **dos** CD40106BE.

## Problema: encoders open-drain

Los encoders (Premotec 990412016913) tienen salida **open-drain (NPN)**:

- **Estado bajo:** el transistor de salida **conduce** → línea a 0 V (lo fija el encoder).
- **Estado alto:** el transistor **corta** → la línea queda **flotando** (Hi-Z) y la sube el **pull-up** hasta el rail al que esté conectado. El encoder **no** entrega tensión en alto: el nivel alto lo decide el pull-up.

Por eso el pull-up va a **3.3 V** (no a 5 V): así el alto reposa en 3.3 V = Vcc del Schmitt, sin corriente de clamp en la entrada. Tirar a 5 V contra un chip alimentado a 3.3 V mete corriente continua por el diodo de clamp (~(5−3.3−0.7)/R ≈ 0.45 mA con 2k2), peor aún cuando el eje queda parado en un tope y la línea se queda en alto estático.

Sin acondicionamiento, la señal es susceptible a ruido de conmutación PWM, rebotes mecánicos y glitches que generan cuentas espurias en el encoder.

## Arquitectura: 2 chips, 4 canales, doble inversión

Cada canal usa **2 inversores** (doble inversión → preserva la polaridad). 4 canales × 2 = **8 inversores**, que no caben en un solo CD40106BE (6 inversores), por lo que se usan **dos chips**:

- **U1 → encoder SERVO** (canales A/B → GPIO34/GPIO35)
- **U2 → encoder PÉNDULO** (canales A/B → GPIO32/GPIO33)

```
   ENCODER SERVO (open-drain, alim. 5V)        ENCODER PÉNDULO (open-drain, alim. 5V)
        A          B                                A          B
        │          │                                │          │
   [2k2→3V3]   [2k2→3V3]                        [2k2→3V3]   [2k2→3V3]
        │          │                                │          │
   ┌────▼──────────▼────┐                      ┌────▼──────────▼────┐
   │   U1  CD40106BE    │                      │   U2  CD40106BE    │
   │  (doble inversión) │                      │  (doble inversión) │
   │  A: INV_A + INV_B  │                      │  A: INV_A + INV_B  │
   │  B: INV_C + INV_D  │                      │  B: INV_C + INV_D  │
   │  Vcc=3V3 + 100nF   │                      │  Vcc=3V3 + 100nF   │
   └────┬──────────┬────┘                      └────┬──────────┬────┘
     OUT_B      OUT_D                            OUT_B      OUT_D
     [10k]      [10k]                            [10k]      [10k]
       ├─[10n]    ├─[10n]                          ├─[10n]    ├─[10n]
       │   │      │   │                            │   │      │   │
     GPIO34 GND GPIO35 GND                       GPIO32 GND GPIO33 GND
```

### Circuito por canal (replicado ×4, doble inversión)

```
                                CD40106BE
                              ┌───────────┐
Encoder ──[2k2 → 3V3]──► IN1  │  INV_x    │
            (pull-up)   (pinA)│           │──► OUT1 (pinB) ──┐
                              │  INV_(x+1)│                   │ (jumper)
                              │           │◄── IN2  (pinC) ◄──┘
                              │           │
                              │           │──► OUT2 (pinD) ──[10kΩ]──┬──► GPIO
                                            (doble inversión)         │
                                                                   [10nF]
                                                                      │
                                                                     GND
```

## Mapa de pines — U1 (encoder SERVO)

```
            +--------+
   IN_A  1  |        | 14  Vcc (3.3V)
  OUT_A  2  |        | 13  F_IN
   IN_B  3  |        | 12  F_OUT
  OUT_B  4  |  U1    | 11  E_IN
   IN_C  5  | 40106  | 10  E_OUT
  OUT_C  6  |        |  9  IN_D
    GND  7  |        |  8  OUT_D
            +--------+
```

| Pin | Nombre | Conexión                                              |
| --- | ------ | ----------------------------------------------------- |
| 1   | IN_A   | **Servo A** + pull-up 2k2 → 3V3                       |
| 2   | OUT_A  | jumper → pin 3                                        |
| 3   | IN_B   | ← jumper desde pin 2                                  |
| 4   | OUT_B  | → 10 kΩ → **GPIO34** (+ 10 nF → GND)               |
| 5   | IN_C   | **Servo B** + pull-up 2k2 → 3V3                       |
| 6   | OUT_C  | jumper → pin 9                                        |
| 7   | GND    | GND común                                            |
| 8   | OUT_D  | → 10 kΩ → **GPIO35** (+ 10 nF → GND)               |
| 9   | IN_D   | ← jumper desde pin 6                                  |
| 10  | E_OUT  | libre (dejar abierto)                                 |
| 11  | E_IN   | **a GND** (entrada CMOS no usada — no dejar flotando) |
| 12  | F_OUT  | libre (dejar abierto)                                 |
| 13  | F_IN   | **a GND** (entrada CMOS no usada — no dejar flotando) |
| 14  | Vcc    | 3.3 V + **100 nF** a pin 7 (bypass)                   |

## Mapa de pines — U2 (encoder PÉNDULO)

Idéntico a U1, cambiando las señales de entrada y las salidas a GPIO:

| Pin | Nombre | Conexión                                              |
| --- | ------ | ----------------------------------------------------- |
| 1   | IN_A   | **Péndulo A** + pull-up 2k2 → 3V3                     |
| 4   | OUT_B  | → 10 kΩ → **GPIO32** (+ 10 nF → GND)               |
| 5   | IN_C   | **Péndulo B** + pull-up 2k2 → 3V3                     |
| 8   | OUT_D  | → 10 kΩ → **GPIO33** (+ 10 nF → GND)               |
| 7   | GND    | GND común                                            |
| 14  | Vcc    | 3.3 V + **100 nF** a pin 7 (bypass)                   |
| 2,3,6,9 | —  | jumpers internos (igual que U1: 2→3, 6→9)            |
| 11,13   | E_IN/F_IN | **a GND** (no usados)                         |
| 10,12   | E_OUT/F_OUT | libres                                       |

## ¿Por qué este circuito?

| Etapa                                | Función                                  | Efecto                          |
| ------------------------------------ | ----------------------------------------- | ------------------------------- |
| **Pull-up 2.2 kΩ (a 3V3)**          | Fija el nivel alto del open-drain a 3.3 V | Señal: 0 V / 3.3 V             |
| **Schmitt Trigger (doble inv.)**     | Histéresis ~1.3 V (a 3.3 V Vcc)          | Elimina glitches y rebotes; conserva polaridad |
| **Filtro RC (10 kΩ + 10 nF)**       | Atenuación de alta frecuencia            | Anti-alias, τ = 100 µs        |

> **Valor del pull-up:** se usa **2.2 kΩ** (mejora el tiempo de subida del flanco open-drain, útil en transiciones bruscas). El comentario del firmware indica **4.7 kΩ**, que también funciona (menor consumo). Ambos válidos; sólo afecta velocidad de subida vs. corriente.

### Filtro RC

- τ = R × C = 10 kΩ × 10 nF = **100 µs**
- f_c = 1 / (2π × τ) ≈ **1.59 kHz**
- Atenúa ruido de conmutación PWM (>20 kHz) y transitorios de alta frecuencia
- No afecta señales de encoder en rango operativo (<50 kHz para 400 RPM)

### Schmitt Trigger (por chip)

| Parámetro                   | CD40106BE @ 3.3 V Vcc | Efecto                                                    |
| ---------------------------- | --------------------- | --------------------------------------------------------- |
| Umbral alto (VT+)            | ~2.3 V                | Se activa cuando la señal **supera** este valor     |
| Umbral bajo (VT−)           | ~1.0 V                | Se desactiva cuando la señal **baja** de este valor |
| **Histéresis (ΔVT)** | **~1.3 V**      | **Zona muerta que rechaza ruido**                   |
| Tiempo de propagación       | ~80–150 ns           | Salida digital limpia y rápida                           |

## Condensadores

| Condensador      | Valor  | Cantidad | Ubicación / función                                        |
| ---------------- | ------ | -------- | ----------------------------------------------------------- |
| Bypass Vcc       | 100 nF | 2 (uno por chip) | Entre pin 14 y pin 7, pegado a cada CD40106BE        |
| Filtro RC a GND  | 10 nF  | 4 (uno por canal)| Nodo después del 10 kΩ a GND                       |

> Los condensadores **bulk** de los rails (1000 µF en 5 V anti-brownout, 470 µF en 15 V, 10 µF en 3V3) están documentados en `pinout.md` → "Condensadores de desacople y bulk". Esta placa de acondicionamiento sólo lleva los **2× 100 nF de bypass** y los **4× 10 nF del filtro RC**.

## Características del CD40106BE (×2)

| Propiedad           | Valor                                       |
| ------------------- | ------------------------------------------- |
| Tipo                | Hex Schmitt Trigger Inverter (6 inversores) |
| Paquete             | DIP-14                                      |
| Alimentación       | 3 V a 18 V (aquí 3.3 V)                     |
| Corriente de salida | ~1.6 mA sink/source a 3.3 V                 |
| Inversores usados   | 4 de 6 por chip (E/F libres, IN a GND)      |

---

## Layout en placa perforada (28 × 22)

Placa de **28 columnas (A…AB) × 22 filas (1…22)** = 616 puntos. Sólo va el acondicionamiento (CD40106 + pasivos + conectores); **ESP32 y L298N quedan fuera**, conectados por los headers.

### Presupuesto de espacio

| Componente            | Footprint (huecos) | Cant. | Subtotal |
| --------------------- | ------------------ | ----- | -------- |
| CD40106BE (DIP-14)    | 4 × 7              | 2     | 56       |
| Pull-up 2k2 (vertical)| 1 × 3              | 4     | 12       |
| Serie RC 10k          | 1 × 3              | 4     | 12       |
| Cap 10 nF             | 1 × 2              | 4     | 8        |
| Cap 100 nF bypass     | 1 × 2              | 2     | 4        |
| Headers (J1–J4)       | tiras de borde     | 4     | ~18      |
| **Total ocupado**     |                    |       | **~110 / 616** |

Sobra holgura (>80 % libre) para ruteo y rails. Cabe cómodo.

### Floorplan

```
 col:  A  B  C  D  E   F  G  H  I   J  K  L  M  N   O  P  Q  R   S  T  U  V   W  X  Y  Z AA AB
       ┌──────────────────────────────── placa 28 × 22 ───────────────────────────────────┐
 r1    │ ~~~~~~~~~~~~~~~~~~~~~~ 5V bus (alimentación de encoders) ~~~~~~~~~~~~~~~~~~~~~~~~~~ │
 r2    │ J1[ 5V GND  A   B ]  (encoder servo)        J2[ 5V GND  A   B ] (encoder péndulo) │
 r3    │ ++++++++++++++++++++++++++++++++ 3V3 bus +++++++++++++++++++++++++++++++++++++++++ │
 r5    │      Rpu Rpu                                     Rpu Rpu                           │
 r7    │      ┌─ U1 ─ CD40106 ─┐                          ┌─ U2 ─ CD40106 ─┐                │
 r8    │   1● │ IN_A     Vcc ● 14  Cb(100n)            1● │ IN_A     Vcc ● 14  Cb(100n)     │
 r9    │   2● │ OUT_A   F_IN ● 13                      2● │ OUT_A   F_IN ● 13               │
 r10   │   3● │ IN_B   F_OUT ● 12                      3● │ IN_B   F_OUT ● 12               │
 r11   │   4● │ OUT_B   E_IN ● 11 (→GND)               4● │ OUT_B   E_IN ● 11 (→GND)        │
 r12   │   5● │ IN_C   E_OUT ● 10                      5● │ IN_C   E_OUT ● 10               │
 r13   │   6● │ OUT_C   IN_D ● 9                       6● │ OUT_C   IN_D ● 9                │
 r14   │   7● │ GND    OUT_D ● 8                       7● │ GND    OUT_D ● 8                │
 r15   │      └─────────────────┘                         └─────────────────┘              │
 r17   │   Rs[10k] Cf[10n]   Rs[10k] Cf[10n]          Rs[10k] Cf[10n]  Rs[10k] Cf[10n]      │
 r20   │ ============================== GND bus =========================================== │
 r21   │ J3[ 5V 3V3 GND ] (a ESP32/power)      J4[ G34 G35 G32 G33 GND ] (a ESP32 GPIO)     │
       └────────────────────────────────────────────────────────────────────────────────┘
```

### Ruteo de buses (3 rails horizontales)

| Rail      | Fila | Origen        | Va hacia                                               |
| --------- | ---- | ------------- | ------------------------------------------------------ |
| **5V**    | r1   | J3 pin 5V     | J1/J2 (alimentación de los encoders)                  |
| **3V3**   | r3   | J3 pin 3V3    | Vcc de U1/U2 (pin 14) + los 4 pull-ups (2k2)           |
| **GND**   | r20  | J3 pin GND    | pin 7 de U1/U2, retorno de los 10 nF, E_IN/F_IN, J1–J4 |

### Conexiones por chip (jumpers de doble inversión)

Para cada canal: `pin2 → pin3` (jumper corto) y `pin6 → pin9` (jumper). La salida útil es **pin 4 (OUT_B)** y **pin 8 (OUT_D)**, cada una a su `10 kΩ` serie y `10 nF` a GND, y de ahí al GPIO por J4.

> **Recordatorio importante:** los pines **11 (E_IN) y 13 (F_IN)** de **ambos** chips van a **GND**. Una entrada CMOS flotando oscila y consume corriente; los inversores E/F no se usan pero sus entradas deben quedar a un nivel fijo.

## Componentes (BOM del acondicionamiento)

| Componente         | Valor               | Cantidad | Costo                |
| ------------------ | ------------------- | -------- | -------------------- |
| CD40106BE          | Hex Schmitt Trigger | 2        | ~$1.00               |
| Resistores 2.2 kΩ | Pull-up encoder (3V3)| 4       | < $0.10              |
| Resistores 10 kΩ  | Serie filtro RC     | 4        | < $0.10              |
| Capacitores 10 nF  | Filtro RC a GND     | 4        | < $0.10              |
| Capacitores 100 nF | Bypass Vcc (1/chip) | 2        | < $0.10              |
| Headers J1–J4      | tiras de pines      | 4        | < $0.20              |
| **Total**    |                     |          | **~$1.50 USD** |

## Comparativa de topologías

| Topología                       | Histéresis            | Glitches             | Filtro HF                | Velocidad max     | Costo            |
| -------------------------------- | ---------------------- | -------------------- | ------------------------ | ----------------- | ---------------- |
| Pull-up solamente                | No                     | Posibles             | No                       | ~10 kHz           | ~$0.05           |
| Pull-up + Schmitt                | Sí (~1.3 V)           | Eliminados           | No                       | >100 kHz          | ~$0.55           |
| **Pull-up + Schmitt + RC** | **Sí (~1.3 V)** | **Eliminados** | **Sí (1.59 kHz)** | **>50 kHz** | **~$1.50** |
