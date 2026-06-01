# Swing-Up Tuning Log — 2026-06-01

## Cambios de Firmware Aplicados

### 1. Fix signo de energía en swing-up (Bug crítico)
**Archivo:** `esp32_qube_l298n.ino` — modo 5
- **Problema:** `E_err = E - Er` invertía el signo del torque
- **Fix:** `energy_sign = (Er > E) ? 1.0f : -1.0f` (ley Quanser/Åström-Furuta correcta)
- **Resultado:** El péndulo ahora SÍ oscila y llega cerca de la vertical

### 2. Kick alternante para iniciar oscilación
- **Problema:** Kick constante `MOTOR_DIR * PWM_MAX * 0.8` siempre en una dirección
- **Fix:** Alterna dirección cada 250ms (resonancia natural del péndulo)
- **Resultado:** El péndulo inicia oscilación desde el fondo

### 3. Normalización de ángulo del péndulo (Bug crítico LQR)
**Función:** `normalizeAngle(deg)` — normaliza a [-180, 180]
- **Problema:** LQR usaba `pendPos` crudo (acumula vueltas: -521°, 512°, etc.)
- **Fix:** `alpha = normalizeAngle(pendPos - 180.0f)` → 0=arriba, ±180=abajo
- **Resultado:** LQR ahora recibe ángulos correctos, la protección funciona

### 4. Fallback automático LQR → Swing-up
- **Problema:** Cuando el LQR fallaba, el péndulo caía al fondo y se quedaba en modo 4 muerto
- **Fix:** Si `|alpha| > 90°` por >2s, vuelve a modo 5 (swing-up)
- **Resultado:** El sistema ahora cicla swing-up → LQR → fallback → swing-up

### 5. Hard stop de servo en LQR
- **Problema:** El servo se desbordaba a ±175°+, crash mecánico
- **Fix:** `if (abs(pos) > 120) pwm = force toward center`
- **Resultado:** Previene crashes, pero el servo aún overshootea

### 6. Filtro de velocidad más rápido
- **Constante:** `VEL_ALPHA_PEND = 0.30f` (era 0.15)
- **Resultado:** El LQR reacciona más rápido a cambios de velocidad del péndulo

### 7. Balance threshold reducido
- **Constante:** `balance_threshold = 12.0f` (era 20.0)
- **Resultado:** Transición swing-up → LQR más cercana a la vertical

### 8. Velocidad gate en transición
- **Constante:** `vel_abs < 500.0f` deg/s para permitir transición
- **Resultado:** Evita transiciones cuando el péndulo se mueve demasiado rápido

---

## Iteraciones de Tuning LQR

### Iteración 1: K1=1.5, K2=25, K3=1.0, K4=3
- LQR sin normalizar ángulo → protección siempre activa → PWM=0
- **Resultado:** ❌ LQR nunca activa el motor

### Iteración 2: K1=1.0, K2=25, K3=0.5, K4=3 (con normalizeAngle)
- Péndulo oscila ±85°, LQR activo pero no amortigua
- **Resultado:** ❌ Oscilación sin estabilización

### Iteración 3: K1=1.5, K2=50, K3=1.0, K4=8
- Servo vuela a ±137°, se atasca contra clamp
- **Resultado:** ❌ Desborde del servo

### Iteración 4: K1=1.5, K2=25, K3=1.0, K4=10 (sin clamp servo)
- LQR atrapa péndulo a **norm=-0.2°** (¡casi perfecto!)
- Pero servo oscila salvajemente (52° → -85° en 0.3s)
- **Resultado:** ⚠️ Atrapa pero no sostiene

### Iteración 5: K1=3.0, K2=25, K3=1.5, K4=15
- LQR atrapa a **norm=-3.7°** pero servo llega a ±185°
- **Resultado:** ⚠️ Atrapa pero crash mecánico

### Iteración 6: K1=2.0, K2=15, K3=1.0, K4=10 (con hard stop ±120°)
- Swing-up no alcanza energía suficiente para llegar a upright
- Péndulo oscila pero nunca alcanza la zona de LQR
- **Resultado:** ❌ Demasiado conservador

---

## Mejor resultado hasta ahora

**Iteración 4** (K1=1.5, K2=25, K3=1.0, K4=10):
- LQR atrapó péndulo a **0.2° de la vertical**
- Fallback funciona (cicla entre swing-up y LQR)
- Péndulo permaneció <10° de upright por **5 muestras** (0.5s)

**Iteración 5** (K1=3.0, K2=25, K3=1.5, K4=15):
- LQR atrapó a **3.0°** y mantuvo <30° por más muestras
- Pero servo desbordaba

---

## Análisis del Problema Pendiente

### Por qué el LQR no puede sostener el péndulo:
1. **Retardo del filtro de velocidad:** EMA α=0.30 a 200Hz da τ≈17ms. El péndulo se mueve a ~300°/s cerca de upright, pero el filtro reporta ~100°/s.
2. **Servo demasiado lento:** El LQR comanda PWM=±100 pero el servo tarda ~200ms en responder. El péndulo cae ~40° en ese tiempo.
3. **Gains K2/K4 en conflicto:** K2 alto → servo se desborda. K2 bajo → péndulo cae. K4 alto → sobre-reacción. K4 bajo → no amortigua.
4. **Hard stop interfiere:** El clamp a ±120° en el cálculo de theta reduce la ganancia efectiva cuando el servo está lejos del centro.

### Posibles soluciones (pendientes):
1. **Calibrar modelo LQR:** Usar system identification para obtener matrices A, B reales y calcular ganancias K óptimas.
2. **Aumentar frecuencia de control:** De 200Hz a 400-500Hz para reducir retardo.
3. **Filtro de velocidad mejorado:** Usar derivada con filtro pass-bajo más agresivo, o kalman filter.
4. **Controlador no-lineal:** Usar sliding mode o backstepping en vez de LQR lineal.
5. **Feedforward:** Agregar término feedforward basado en la dinámica conocida del péndulo.

---

## Archivos de datos generados

| Archivo | Intentos | Resultado |
|---------|----------|-----------|
| `test_20260601T200449.csv` | Original (sin fixes) | Péndulo stuck |
| `test_20260601T200551.csv` | Original (sin fixes) | Péndulo stuck |
| `test_20260601T164649_attempt*.csv` | Con fixes básicos | LQR atrapa pero no sostiene |
| `test_20260601T170621_attempt*.csv` | + fallback + protection 140° | LQR activo, cycling |
| `test_20260601T171345_attempt*.csv` | + hard stop ±90° | PCNT stuck (upload) |
| `test_20260601T171605_attempt*.csv` | + K1=1.5 K2=25 K4=10 + vel α=0.3 | **Mejor: 0.2° upright** |
| `test_20260601T172349_attempt*.csv` | + K1=3 K2=35 K4=20 | Crash servo ±185° |
| `test_20260601T173154_attempt*.csv` | + K1=3 K2=25 K4=15 | Crash servo ±185° |
| `test_20260601T173854_attempt*.csv` | + K1=2 K2=15 K4=10 + hard stop 120° | Demasiado conservador |

---

## Parámetros actuales del firmware

```cpp
// Swing-up (modo 5)
// energy_sign = (Er > E) ? 1.0f : -1.0f  ✓ correcto
// kick alternante cada 250ms  ✓

// LQR (modo 4)
float lqr_K1 = 2.0f;    // posición servo
float lqr_K2 = 15.0f;   // ángulo péndulo
float lqr_K3 = 1.0f;    // velocidad servo
float lqr_K4 = 10.0f;   // velocidad péndulo

float VEL_ALPHA_PEND = 0.30f;  // filtro velocidad péndulo
float balance_threshold = 12.0f;  // umbral transición (grados)

// Protecciones
// - Péndulo: |alpha| > 140° → PWM=0
// - Servo: |pos| > 120° → forzar al centro
// - Fallback: |alpha| > 90° por >2s → volver a swing-up
```

## Iteración 7: 500 Hz + K1=1.5, K2=25, K3=1, K4=10

**Cambio principal:** Frecuencia de control 200 Hz → 500 Hz (`CONTROL_PERIOD_US = 2000`)

| Intento | Closest | <10° | <30° | Max servo | Resultado |
|---------|---------|------|------|-----------|-----------|
| 1 | 3.9° | 7 | 14 | 149.2° | LQR activo, no estabiliza |
| 2 | 9.3° | 1 | 1 | 184.6° | CRASH servo |
| 3 | 16.5° | 0 | 9 | 129.4° | LQR activo |
| 4 | 14.1° | 0 | 1 | 165.4° | LQR activo |
| 5 | — | — | — | — | No swing-up |
| 6 | 4.4° | 7 | 18 | 156.8° | LQR activo |

**Comparación con 200 Hz (mejor iteración anterior):**
- 200 Hz: closest=0.2°, <10°=5 muestras (0.5s), <30°=6 muestras
- 500 Hz: closest=3.9°, <10°=7 muestras (0.14s a 500Hz), <30°=18 muestras

**Conclusión:** A 500 Hz el péndulo pasa MÁS tiempo cerca de la vertical (18 vs 6 muestras dentro de 30°), pero el servo aún overshootea a ±185°. El cuello de botella es la **respuesta del motor**, no la frecuencia de control.

### Siguiente paso recomendado
La limitación es física: el motor L298N + DC motor no tiene suficiente torque/respuesta. Opciones:
1. **Gearbox en el motor** — más torque, respuesta más lenta pero más fuerza
2. **Motor con encoder integrado** — mejor feedback de posición
3. **Driver de motor mejorado** — MOSFET en vez de L298N (menor voltaje de saturación)
4. **Control predictivo** — usar modelo del sistema para predecir y anticipar

## Hardware: Cambio de driver de motor

**Problema:** L298N usa BJT con Rds~2Ω, caída ~2V, PWM max 25 kHz.
Con motor a 1A se disipan ~2W y el PWM a 25kHz causa vibraciones en el servo.

**Solución recomendada: BTS7960** (soporta 15V directo)
- Voltaje: 6-27V ✓ (acepta los 15V del transformador)
- Rds(on): ~0.012Ω (166x menos que L298N)
- Corriente: 43A max (overkill pero garantiza baja disipación)
- Disipación a 2A: ~0.048W vs ~8W en L298N
- Precio: ~$3-5 USD en módulos
- Pinout: RPWM/LPWM/EN por canal → adaptable al código actual

**Nota:** TB6612FNG (max 13.5V) y DRV8833 (max 10.8V) NO soportan 15V.
Si se quisiera PWM a 100 kHz, necesitaría buck converter a ≤12V + TB6612FNG.

**Alternativa premium:** VNH5019 (Pololu) — max 40V, Rds=0.019Ω, ~$15


