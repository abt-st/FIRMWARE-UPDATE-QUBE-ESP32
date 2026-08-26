# Bill of Materials (BOM) — QUBE ESP32

Lista completa de componentes con especificaciones y costos.

> **Driver vigente: L298N.** Hubo un intento de migración a BTS7960 (2026-06-08 – 2026-07-27) revertido por errores de implementación del usuario; ver [`CHANGELOG.md`](../../CHANGELOG.md).

## Componentes principales

| Componente                    | Especificación                               | Cantidad | Precio aprox.     |
| ----------------------------- | --------------------------------------------- | -------- | ----------------- |
| **ESP32-WROOM-32**      | Dual-core 240 MHz, WiFi+BLE                   | 1        | $6–10 USD        |
| **L298N**               | Dual H-Bridge, 2 A/canal, 5–35 V             | 1        | $1.5–3 USD       |
| **INA219**              | Monitor I2C, 0–26 V, ±3.2 A                 | 1        | $2–4 USD         |
| **LM2596**              | Buck converter ajustable, 3 A                 | 2        | $2–6 USD         |
| **CD40106BE**           | Hex Schmitt Trigger Inverter, DIP-14          | 2        | ~$1.00 USD        |
| **Motor DC + reductor** | 15 V, 25 W, 100–300 RPM                      | 1        | $15–30 USD       |
| **Encoder servo**       | Incremental, open-drain, ≥200 CPR            | 1        | Incluido en motor |
| **Encoder péndulo**    | Incremental, push-pull 5V, ≥200 CPR          | 1        | $5–15 USD        |

> Los dos LM2596 regulan rieles de 5 V independientes: uno alimenta la lógica del L298N, el VCC de los encoders y el acondicionamiento (pull-ups + filtro RC); el otro alimenta únicamente la ESP32, aislada del ruido de conmutación del resto del circuito. Detalle completo: [`pinout.md`](pinout.md).

## Componentes pasivos (acondicionamiento de señal, ×2 CD40106BE)

| Componente         | Valor               | Cantidad | Notas                                  |
| ------------------ | -------------------- | -------- | -------------------------------------- |
| Resistores 2.2 kΩ | Pull-up encoder (a 3V3) | 4    | Un por canal (servo A/B + péndulo A/B) |
| Resistores 10 kΩ  | Serie filtro RC     | 4        | Post-Schmitt                           |
| Capacitores 10 nF  | Filtro RC a GND     | 4        | Post-Schmitt                           |
| Capacitores 100 nF | Bypass Vcc          | 2        | Uno por CD40106BE, lo más cerca del chip |

Detalle del circuito y mapa de pines: [`signal_conditioning.md`](signal_conditioning.md).

## Condensadores de rail (bulk + bypass)

| Componente         | Valor               | Cantidad | Rail / ubicación                        |
| ------------------ | -------------------- | -------- | ---------------------------------------- |
| Electrolítico       | 1000 µF / 10 V       | 1        | 5 V ESP32 (LM2596 #2 OUT) — anti-brownout |
| Electrolítico       | 470 µF / 10 V        | 1        | 5 V lógica (LM2596 #1 OUT)              |
| Electrolítico       | 470 µF / 25 V        | 1        | 15 V (L298N VS)                          |
| Electrolítico       | 10 µF                | 1        | 3.3 V (pin 3V3 ESP32)                    |
| Cerámico            | 100 nF               | ~5       | Bypass en cada rail (5V×2, 15V, 3.3V, motor) |

Detalle completo (por qué cada valor y su prioridad): [`pinout.md`](pinout.md#condensadores-de-desacople-y-bulk).

## Fuente de alimentación

| Opción                    | Especificación                  | Notas                         |
| ------------------------- | -------------------------------- | ----------------------------- |
| Transformador 15V-2A       | 15 V DC, 2 A                    | Fuente vigente                |
| LiPo 4S                   | 14.8V nominal, ≥3A              | Alternativa portátil          |
| PSU de laboratorio        | 15V DC, ≥3A                     | Para bancada de trabajo       |

## Requisitos de potencia

- Cable de retorno motor: AWG 16 mínimo (R < 0.05 Ω)
- GND común en topología estrella (NO en cadena)
- INA219 en serie entre la fuente y el L298N VS (high-side sensing)
- Capacitor 100 nF cerca del L298N (bypass)

## Costo total estimado (sin fuente)

**$35–70 USD**

Comparación: Quanser QUBE Servo = $2,500–$3,500 USD
