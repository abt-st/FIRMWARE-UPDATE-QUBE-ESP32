# Investigación: Integración del Encoder del Péndulo en QUBE Servo (ESP32)

**Fuente:** `old resources/INVESTIGACION_INTEGRACION_ENCODER_PENDULO.md` (2026-05-07)  
**Objetivo:** Agregar un segundo canal de encoder en cuadratura para habilitar control de péndulo invertido

---

## 1. Estado Actual del Sistema

- Control motor por L298N (GPIO26/GPIO27)
- Encoder motor en cuadratura A/B (GPIO34/GPIO35)
- INA219 por I2C (GPIO21/GPIO22)
- Decodificación de encoder por polling LUT (X4), período de control 200 Hz
- El conjunto Premotec tiene dos conectores de encoder: servo y péndulo

**Sin ángulo de péndulo no es posible implementar swing-up + estabilización vertical.**

---

## 2. Objetivo Técnico

Agregar un segundo canal de encoder cuadratura (péndulo) con:

- Lectura confiable de ángulo absoluto relativo
- Derivada angular filtrada para control
- Carga de CPU baja y latencia predecible
- Compatibilidad eléctrica con ESP32 (3.3 V lógica)

---

## 3. Arquitectura Recomendada

### Opción A (recomendada): Dual encoder con PCNT en ESP32

Descripción: Ambos encoders decodificados por periférico PCNT (contador de pulsos). El loop de control solo lee contadores atómicos y calcula ángulos/velocidades.

| Ventajas | Riesgos |
|----------|---------|
| Menor jitter que polling puro | Requiere refactor de capa de lectura |
| Menor uso de CPU que ISR por flanco | Configuración PCNT debe probarse con ruido |
| Escalable para frecuencias de borde altas | |

### Opción B (intermedia): Mantener polling para base + ISR para péndulo

| Ventajas | Riesgos |
|----------|---------|
| Cambios mínimos al firmware existente | Mayor carga de CPU, más sensibilidad a jitter |

### Opción C (no recomendada): Polling para ambos

| Riesgos |
|---------|
| Probabilidad alta de perder transiciones a mayor velocidad |
| Precisión de velocidad angular degradada |

---

## 4. Pines Sugeridos

| Señal | GPIO | Notas |
|-------|------|-------|
| PEND_A | GPIO32 | Entrada digital, evitar pines de boot (0, 2, 12, 15) |
| PEND_B | GPIO33 | Entrada digital |
| PEND_Z | GPIO39 | Opcional (index), solo entrada |

---

## 5. Acondicionamiento Eléctrico

Primero identificar tipo de salida del encoder del péndulo:

**Actualización (2026-05-13):** El encoder del servo se validó como compatible con push-pull 5V. Esta conclusión **no se extrapola** al encoder del péndulo.

### Caso 1: Open-drain

```
3V3 ESP32 → 4.7kΩ → nodo señal → GPIO32/33
                           |
                      salida encoder (NPN open-drain)
                           |
                          GND común
```

### Caso 2: Push-pull a 5V

Divisor resistivo (ej. 4.7k serie + 8.2k a GND) para limitar a ~3.2 V.

### Filtro RC recomendado (si hay ruido)

Por canal, cerca del ESP32:
- R serie 100 Ω
- C a GND 10 nF
- Frecuencia de corte: ~159 kHz

---

## 6. Variables de Firmware

```cpp
// Nuevo estado
volatile long pendCount;
float pendCountsPerRev;
int pendDir;
float pendOffsetDeg;
float pendFilteredVel;

// Nuevas funciones
float getPendRawDeg();
float getPendDeg();
void zeroPendHere();
void updatePendEncoder();
```

**Convenciones de ángulo:**
- 0°: péndulo colgando hacia abajo
- Rango [-180°, +180°] para control y telemetría
- Wrap aplicado para evitar saltos al cruzar ±180°

---

## 7. Estrategia de Control por Fases

### Fase 1: Medición y telemetría
- Incorporar lectura del péndulo sin cambiar el controlador actual
- Publicar en JSON: `pend_deg`, `pend_vel_dps`, `pend_cnt`

### Fase 2: Seguridad y validación
- Límites de ángulo para corte de motor
- Verificar coherencia de signo (`pendDir`) con movimiento real

### Fase 3: Control dual
- Mantener lazo de posición base
- Agregar controlador de péndulo:
  - Swing-up energético cuando lejos del equilibrio
  - Estabilización (LQR o PID acoplado) cerca del equilibrio

---

## 8. Plan de Implementación

1. **Cableado y validación eléctrica** — Conectar PEND_A/PEND_B a GPIO32/33 con topología correcta
2. **Lectura en firmware (sin control)** — Contador de péndulo y conversión a grados
3. **Calibración** — Medir CPR real, ajustar `pendCountsPerRev` y `pendDir`
4. **Filtrado y velocidad** — Derivada + filtro EMA para `pend_vel`
5. **Integración de control** — Agregar modo m3, mantener fallback a m2

---

## 9. Checklist de Validación

### Eléctrico
- [ ] Nivel alto estable > 2.6 V en GPIO del ESP32
- [ ] Nivel bajo < 0.4 V
- [ ] No hay picos > 3.3 V en pines ESP32

### Firmware
- [ ] `pend_cnt` cambia monotónicamente al mover péndulo
- [ ] `pend_deg` recorre rango esperado sin saltos espurios
- [ ] `pend_vel` no presenta ruido excesivo en reposo

### Control
- [ ] Sistema puede operar en modo base-only sin regresiones
- [ ] Nuevo modo con péndulo no rompe telemetría ni comandos existentes

---

*Documento preparado: 2026-05-07 | Actualizado: 2026-05-26*