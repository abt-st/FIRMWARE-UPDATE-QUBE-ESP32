# Bill of Materials (BOM) — QUBE ESP32

Lista completa de componentes con especificaciones y costos.

## Componentes principales

| Componente                    | Especificación                               | Cantidad | Precio aprox.     |
| ----------------------------- | --------------------------------------------- | -------- | ----------------- |
| **ESP32-WROOM-32**      | Dual-core 240 MHz, WiFi+BLE                   | 1        | $6–10 USD        |
| **BTS7960**             | Dual Half-Bridge (IBT-2), 43A pico, 10A cont. | 1        | $2–5 USD         |
| **INA219**              | Monitor I2C, 0–26 V, ±3.2 A                 | 1        | $2–4 USD         |
| **LM2596**              | Buck converter ajustable, 3 A                 | 1        | $1–3 USD         |
| **CD40106BE**           | Hex Schmitt Trigger Inverter, DIP-14          | 1        | ~$0.50 USD        |
| **Motor DC + reductor** | 15 V, 25 W, 100–300 RPM                      | 1        | $15–30 USD       |
| **Encoder servo**       | Incremental, open-drain, ≥200 CPR            | 1        | Incluido en motor |
| **Encoder péndulo**    | Incremental, open-drain, ≥200 CPR            | 1        | $5–15 USD        |

## Componentes pasivos (acondicionamiento de señal)

| Componente         | Valor               | Cantidad | Notas                                  |
| ------------------ | ------------------- | -------- | -------------------------------------- |
| Resistores 4.7 kΩ | Pull-up encoder     | 4        | Un por canal (servo A/B + péndulo A/B) |
| Resistores 10 kΩ  | Serie filtro RC     | 4        | Post-Schmitt                           |
| Capacitores 10 nF  | Filtro RC a GND     | 4        | Post-Schmitt                           |
| Capacitor 100 nF   | Bypass Vcc          | 1        | Lo más cerca del CD40106BE             |
| Capacitor 100 µF   | Filtro salida LM2596 | 1       | En rail 5V                             |
| Capacitor 470 µF   | Bypass rail 5V      | 1        | Estabilización                         |

## Fuente de alimentación

| Opción                    | Especificación                  | Notas                         |
| ------------------------- | ------------------------------- | ----------------------------- |
| LiPo 4S                   | 14.8V nominal, ≥3A              | Recomendado para portabilidad |
| PSU de laboratorio        | 15V DC, ≥3A                     | Para bancada de trabajo       |

## Requisitos de potencia

- Cable de retorno motor: AWG 16 mínimo (R < 0.05 Ω)
- GND común en topología estrella (NO en cadena)
- Bypass capacitors: 470 µF + 100 µF en rail 5V
- Capacitor 100 nF cerca del BTS7960 (bypass)

## Costo total estimado (sin fuente)

**$35–70 USD**

Comparación: Quanser QUBE Servo = $2,500–$3,500 USD
