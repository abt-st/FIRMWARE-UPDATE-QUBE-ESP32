# ⚡ Informe Técnico: Acondicionamiento de Señal del Encoder del Péndulo

**Fecha:** 2026-05-29  
**Problema:** El encoder del péndulo presenta 3.6V en nivel alto con Vcc = 3.3V  
**Riesgo:** Daño permanente al ESP32 (GPIOs no toleran > 3.3V)

---

## 🔴 Diagnóstico del Problema

### Síntoma

| Medición | Valor | Límite seguro ESP32 | Estado |
|----------|-------|---------------------|--------|
| Nivel alto encoder péndulo | **3.6V** | 3.3V (VDD_IO) | ❌ **FUERA DE RANGO** |
| Nivel bajo encoder péndulo | ~0V | 0V | ✅ OK |
| Vcc del encoder | 3.3V (medido) | — | Inconsistente con 3.6V de salida |

### Análisis de Causa Raíz

El nivel alto de 3.6V excediendo Vcc (3.3V) indica que **el encoder no está alimentado exclusivamente a 3.3V**, o que hay una fuente alternativa energizando la salida:

1. **Causa más probable:** El encoder está conectado a **5V** (alimentación del L298N o bus de potencia) y su salida push-pull llega a ~4.7-5V. El voltaje medido de 3.6V podría ser:
   - Promedio RMS de una señal PWM/conmutada
   - Lectura en multímetro digital (respondiendo al duty cycle efectivo)
   - Señal con caída por carga/divisor no intencional

2. **Causa alternativa:** El encoder tiene alimentación interna separada (batería/otra fuente) que supera los 3.3V del rail del ESP32.

3. **Posible efecto en cascada:** Si el encoder alimentado a 5V está conectado directamente a GPIO32/33 sin acondicionamiento, está **sobrevoltando** el ESP32, lo que puede causar:
   - Activación de diodos de protezione internos
   - Corriente parasitaria al rail de 3.3V
   - Daño gradual o catastrófico del GPIO

### Riesgo Inmediato

| Nivel de Riesgo | Consecuencia |
|----------------|-------------|
| **CRÍTICO** | Daño permanente del ESP32 si se opera sostenidamente a 3.6V en GPIO |
| **ALTO** | Activación de protecciones internas → consumo excesivo, calentamiento |
| **MEDIO** | Degradación de lifespan del microcontrolador |

---

## 🛡️ Solución Propuesta: CD40106BE Schmitt Trigger

### Topología

```
                         3.3V (desde regulador ESP32)
                          │
                         ─┴─ 100nF (bypass)
                         ─┬─
                          │
                  ┌───────────────┐
                  │   CD40106BE   │
                  │  Vcc = 3.3V  │
                  │               │
ENC_PEND_A (5V?)──R_series──┬────┤1 IN1    Vcc│14──3.3V
                  2.2kΩ     │    │             │
                            │    └┤2 OUT1      │
                           R_pd   │            │
                           10kΩ   └──────┬─────┘── GPIO32
                            │            │
                           GND     100nF ─┴─ GND
                                      ─┬─

ENC_PEND_B (5V?)──R_series──┬────┤3 IN2    OUT1│ (doble inversión)
                  2.2kΩ     │    │             │
                            │    └┤4 OUT2      │
                           R_pd   │            │
                           10kΩ   └──────┬─────┘── GPIO33
                            │            │
                           GND     100nF ─┴─ GND
                                      ─┬─
```

### Por qué funciona

| Propiedad | Explicación |
|-----------|-------------|
| **Vin > Vcc tolerable** | El CD40106BE a 3.3V tiene umbrales VT+ ≈ 2.3V, VT- ≈ 1.0V. Una señal de 5V supera VT+ con amplio margen |
| **Salida limitada a Vcc** | La salida del CMOS NO puede exceder Vcc (3.3V), protegiendo automáticamente el GPIO del ESP32 |
| **Histéresis** | ~0.5V a 3.3V → elimina rebote y ruido de conmutación del motor |
| **Flancos limpios** | Tiempo de propagación < 120ns → transiciones instantáneas para el encoder |

### Ventaja clave: **LIMITACIÓN AUTOMÁTICA DE VOLTAJE**

Incluso si la entrada del encoder llega a 5V, 10V o cualquier valor, **la salida del CD40106BE NUNCA excederá Vcc (3.3V)**. Esto protege inherentemente el ESP32.

---

## 🔧 Implementación Paso a Paso

### Materiales necesarios

| Componente | Cantidad | Costo | Notas |
|------------|----------|-------|-------|
| CD40106BE (DIP-14) | 1 | ~$0.50 | Hex Schmitt Trigger Inverter |
| Resistencia 2.2kΩ 1/4W | 2 | ~$0.04 | Limitación de corriente |
| Resistencia 10kΩ 1/4W | 2 | ~$0.04 | Pull-down |
| Capacitor 100nF cerámico | 3 | ~$0.15 | Bypass + filtro |
| Protoboard pequeño | 1 | ~$0.50 | Para montaje temporal |
| **Total** | | **~$1.23** | |

### Pasos de montaje

1. **Alimentar el CD40106BE a 3.3V**
   - Pin 14 (Vcc) → 3.3V del ESP32 (regulador on-board)
   - Pin 7 (GND) → GND común
   - Capacitor 100nF entre pin 14 y pin 7 (lo más cerca posible del IC)

2. **Conectar canal A (encoder péndulo)**
   - Encoder canal A → R_series (2.2kΩ) → Pin 1 (IN1) del CD40106BE
   - Pin 1 → R_pd (10kΩ) → GND
   - Pin 1 → C_filtro (100nF) → GND
   - Pin 2 (OUT1) → GPIO32 del ESP32

3. **Conectar canal B (encoder péndulo)**
   - Encoder canal B → R_series (2.2kΩ) → Pin 3 (IN2) del CD40106BE
   - Pin 3 → R_pd (10kΩ) → GND
   - Pin 3 → C_filtro (100nF) → GND
   - Pin 4 (OUT2) → GPIO33 del ESP32

4. **Verificar con multímetro**
   - Medir voltaje en pin 14: debe ser ~3.3V
   - Girar encoder manualmente y medir voltaje en pin 2 y pin 4
   - **Resultado esperado:** Pulsos entre ~0V y ~3.3V (NUNCA > 3.3V)

5. **Verificar en firmware**
   - Cargar firmware y activar modo de lectura de encoder péndulo
   - Verificar que `encoderCount` se incrementa/decrementa correctamente
   - Verificar que no hay conteos erráticos (falsos flancos)

### Nota sobre inversión

El CD40106BE es un **inversor**: la salida es lógica opuesta a la entrada. Para un encoder incremental, esto generalmente **no afecta** la decodificación de cuadratura, ya que:
- Los algoritmos de cuadratura (LUT 4×4) solo detectan **transiciones**, no polaridad absoluta
- La inversión afecta **ambos canales por igual**, manteniendo la relación de fase

Si se necesita polaridad original, usar doble inversión:
```
ENC_A → INV1 (pin 1→2) → INV2 (pin 3→4) → GPIO32
ENC_B → INV3 (pin 5→6) → INV4 (pin 9→8) → GPIO33
```
Esto usa 4 de los 6 inversores, dejando 2 disponibles para otros usos.

---

## 📊 Verificación Esperada

### Antes del acondicionamiento

| Parámetro | Valor medido |
|-----------|-------------|
| Nivel alto | 3.6V ❌ (supera 3.3V) |
| Flanco de subida | Lento (depende de pull-up) |
| Ruido | Presente (conmutación L298N) |
| Histéresis | 0V (sin protección) |
| Falsos conteos | Probables |

### Después del acondicionamiento

| Parámetro | Valor esperado |
|-----------|---------------|
| Nivel alto | ~3.3V ✅ (limitado por Vcc) |
| Flanco de subida | < 120ns ✅ (Schmitt trigger) |
| Ruido | Eliminado por histéresis |
| Histéresis | ~0.5V ✅ |
| Falsos conteos | Eliminados |

---

## ⚠️ Consideraciones Importantes

1. **NO conectar directamente el encoder a GPIO32/33 sin acondicionamiento** mientras el voltaje supere 3.3V
2. **El CD40106BE es una protección intrínseca**: su salida NUNCA excederá Vcc, sin importar la entrada
3. **Alimentar el CD40106BE desde el ESP32** (3.3V) para garantizar compatibilidad de niveles
4. **El bypass 100nF es obligatorio** para evitar oscilaciones del chip
5. **Usar GND común** entre potencia (motor, L298N) y lógica (ESP32, CD40106BE)

---

*Generado: 2026-05-29 | Problema reportado por usuario*