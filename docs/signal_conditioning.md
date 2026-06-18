# Acondicionamiento de Señal — CD40106BE Schmitt Trigger + RC

Referencia completa del circuito de acondicionamiento de señal para encoders open-drain.

## Problema: encoders open-drain

Los encoders (Premotec 990412016913) tienen salida **open-drain (NPN)**:

- **Estado bajo:** transistor conduce → 0 V
- **Estado alto:** transistor corta → línea flota (Hi-Z)

Sin acondicionamiento, la señal es susceptible a ruido de conmutación PWM, rebotes mecánicos y glitches que generan cuentas espurias en el encoder.

## Circuito: CD40106BE + filtro RC

El circuito combina **Schmitt Trigger** (histéresis para rechazo de ruido) con un **filtro RC pasivo** (atenuación de alta frecuencia) en cada canal del encoder:

```
                                     CD40106BE
                                ┌──────────────────┐
Encoder A (~5V) ────────────────┤ pin 1  (IN_A)    │
                		│        (OUT_A) pin 2 ├──┐
  		                │                  │   │  │
   	                        │       (IN_B) pin 3 ◄─┘
                                │    (OUT_B) pin 4 ├──► 10kΩ ──┬──► GPIO34
                                │                  │           │
                                │                  │          10nF
                                │                  │           │
                                │                  │          GND
                                │                  │
Encoder B (~5V) ────────────────┤ pin 5  (IN_C)    │
                                │        (OUT_C) pin 6 ├──┐
                                │                  │   │  │
                                │       (IN_D) pin 9 ◄─┘
                                │    (OUT_D) pin 8 ├──► 10kΩ ──┬──► GPIO35
                                │                  │           │
                                │                  │          10nF
                                │                  │           |
				|		   |	      GND
         GND ───────────────────┤ pin 7      pin 14├──── 3.3V  
                                └──────────────────┘
                                       │
                                   100nF (bypass Vcc)
                                       │
                                      GND
```

### Circuito por canal (replicado ×4)

```
                            CD40106BE                    Filtro RC
                           ┌─────────┐
			   │         │
Encoder (~5V) ──► IN_A ──► │ INV_A   │
                  (pin 1)  │         │──► OUT_A (pin 2) ──┐
                           │  INV_B  │                     │
                           │         │◄── IN_B (pin 3) ◄──┘
                           │         │
                           │         │──► OUT_B (pin 4) ──[10kΩ]──┬──► GPIO
                                                   (doble inversión) │
                                                                 [10nF]
                                                                     │
                                                                    GND
```

## ¿Por qué este circuito?

| Etapa                                  | Función                                | Efecto                          |
| -------------------------------------- | --------------------------------------- | ------------------------------- |
| **Pull-up 4.7 kΩ**              | Convierte open-drain a niveles lógicos | Señal: 0 V / 3.3 V             |
| **Schmitt Trigger (doble inv.)** | Histéresis ~0.5 V (a 3.3 V Vcc)        | Elimina glitches y rebotes      |
| **Filtro RC (10 kΩ + 10 nF)**   | Atenuación de alta frecuencia          | Filtro anti-alias, τ = 100 µs |

### Filtro RC

- τ = R × C = 10 kΩ × 10 nF = **100 µs**
- f_c = 1 / (2π × τ) ≈ **1.59 kHz**
- Atenua ruido de conmutación PWM (>20 kHz) y transitorios de alta frecuencia
- No afecta señales de encoder en rango operativo (<50 kHz para 400 RPM)

### Schmitt Trigger

| Parámetro                   | CD40106BE @ 3.3 V Vcc | Efecto                                                    |
| ---------------------------- | --------------------- | --------------------------------------------------------- |
| Umbral alto (VT+)            | ~2.3 V                | Se activa cuando la señal **supera** este valor     |
| Umbral bajo (VT−)           | ~1.0 V                | Se desactiva cuando la señal **baja** de este valor |
| **Histéresis (ΔVT)** | **~1.3 V**      | **Zona muerta que rechaza ruido**                   |
| Tiempo de propagación       | ~80–150 ns           | Salida digital limpia y rápida                           |

## Características del CD40106BE

| Propiedad           | Valor                                       |
| ------------------- | ------------------------------------------- |
| Tipo                | Hex Schmitt Trigger Inverter (6 inversores) |
| Paquete             | DIP-14                                      |
| Alimentación       | 3 V a 18 V (rango completo CMOS)            |
| Corriente de salida | ~1.6 mA sink/source a 3.3 V                 |
| Disipación         | Muy baja (~µW en estático)                |
| Costo               | ~$0.50 USD                                  |

### Pinout (DIP-14)

```
          +--------+
  A_IN 1  |        | 14 Vcc (3.3V)
  A_OUT 2 |        | 13 F_IN
  B_IN 3  |        | 12 F_OUT
  B_OUT 4 |  40106 | 11 E_IN
  C_IN 5  |        | 10 E_OUT
  C_OUT 6 |        | 9  D_IN
   GND 7  |        | 8  D_OUT
          +--------+
```

### Uso de los 6 inversores

| Inversor      | Pines      | Uso                                                     | Estado          |
| ------------- | ---------- | ------------------------------------------------------- | --------------- |
| INV_A + INV_B | 1→2→3→4 | Encoder servo canal A (doble inversión + RC → GPIO34) | **Usado** |
| INV_C + INV_D | 5→6→9→8 | Encoder servo canal B (doble inversión + RC → GPIO35) | **Usado** |
| INV_E         | 11→10     | Reservado — oscilador watchdog / botón de paro        | Libre           |
| INV_F         | 13→12     | Reservado — debounce de botones / expansión           | Libre           |

> **Importante:** Alimentar el CD40106BE a **3.3 V** (desde el pin 3V3 del ESP32) para salida directa compatible con GPIO. La salida será **~3.3 V** (limitada por Vcc), seguro para los GPIO del ESP32 (máximo tolerado: 3.6 V).

## Alimentación y bypass

```
3.3V (ESP32) ──┬── CD40106BE pin 14 (Vcc)
               │
              100nF ── GND  (bypass, lo más cerca del pin 14)
               │
              GND ──── CD40106BE pin 7
```

> **Sobre el capacitor de bypass (100 nF):** Conectar **entre pin 14 (Vcc) y pin 7 (GND)**, lo más cerca posible del chip. Cuando las compuertas del CD40106BE conmutan, dibujan picos de corriente del rail 3.3V. Sin el capacitor, estos transitorios generan glitches en el voltaje de alimentación que pueden afectar al ESP32, ya que ambos comparten el mismo rail.

## Componentes del acondicionamiento (×4 canales)

| Componente         | Valor               | Cantidad | Costo                |
| ------------------ | ------------------- | -------- | -------------------- |
| CD40106BE          | Hex Schmitt Trigger | 1        | ~$0.50               |
| Resistores 4.7 kΩ | Pull-up encoder     | 4        | < $0.10              |
| Resistores 10 kΩ  | Serie filtro RC     | 4        | < $0.10              |
| Capacitores 10 nF  | Filtro RC a GND     | 4        | < $0.10              |
| Capacitor 100 nF   | Bypass Vcc          | 1        | < $0.05              |
| **Total**    |                     |          | **~$0.85 USD** |

## Comparativa de topologías

| Topología                       | Histéresis            | Glitches             | Filtro HF                | Velocidad max     | Costo            |
| -------------------------------- | ---------------------- | -------------------- | ------------------------ | ----------------- | ---------------- |
| Pull-up solamente                | No                     | Posibles             | No                       | ~10 kHz           | ~$0.05           |
| Pull-up + Schmitt                | Sí (~1.3 V)           | Eliminados           | No                       | >100 kHz          | ~$0.55           |
| **Pull-up + Schmitt + RC** | **Sí (~1.3 V)** | **Eliminados** | **Sí (1.59 kHz)** | **>50 kHz** | **~$0.85** |
