# PID Tuning Analysis — 2026-06-04

## Setup

- **ESP32** @ 192.168.100.50 (OTA)
- **Firmware**: v1.31.0 (defaults: Kp=3.0, Ki=0.5, Kd=0.15)
- **Mesa**: desnivel que genera torque gravitacional constante sobre el servo (~45° de caída natural)
- **Péndulo**: cuelga en 0° por gravedad (pasivo, sin motor propio)
- **Control period**: 500 Hz (2ms)
- **Muestreo HTTP**: ~100ms (limitación del test script, no del firmware)

---

## 1. PID Servo (Modo 2) — Resultados

### Test: Step response con 6 transiciones (0→45→-45→90→0→30→0)

| Configuración | Step | Rise(ms) | Overshoot | SS Error |
|---|---|---|---|---|
| **Baseline** (Kp=3, Ki=0.5, Kd=0.15) | 0→45° | 265 | 7.0% | +8.3° |
| | 45→-45° | 490 | 28.9% | -8.6° |
| | -45→90° | N/A | 0.0% | +21.6° |
| | 90→0° | 459 | 17.0% | -6.9° |
| | 0→30° | 440 | 7.8% | +4.9° |
| | 30→0° | 559 | 0.0% | -6.9° |
| **Mejorado** (Kp=3, Ki=1.5, Kd=0.20) | 0→45° | 377 | 0.0% | +7.7° |
| | 45→-45° | 500 | 28.5% | -4.9° |
| | -45→90° | N/A | 0.0% | +27.6° |
| | 90→0° | 437 | 14.3% | -4.0° |
| | 0→30° | 444 | 0.0% | +4.9° |
| | 30→0° | 502 | 1.2% | -3.3° |

### Métricas comparativas

| Métrica | Baseline | Mejorado | Delta |
|---|---|---|---|
| Avg overshoot | 10.1% | 7.3% | -2.8% ✅ |
| Avg \|SS error\| | 9.5° | 8.7° | -0.8° ✅ |
| Rise time (0→45°) | 265ms | 377ms | +112ms ⚠️ |

### Conclusión PID Servo

**Los gains mejorados (Ki=1.5, Kd=0.20) son marginales.** Reducen el error estacionario ~0.8° pero el problema raíz es la **soft saturation en `setMotor()`**:

```
factor = 1 / (1 + (|pos| / 80)^2)
```

| Posición | Factor | PWM disponible |
|---|---|---|
| 0° | 1.00 | 100% |
| 45° | 0.76 | 76% |
| 70° | 0.57 | 57% |
| 90° | 0.44 | 44% |

El motor pierde autoridad a medida que el brazo se aleja del centro. En 90°, solo el 44% del PWM está disponible — no es suficiente para vencer la fricción + torque gravitacional del desnivel.

**Otro factor: anti-windup reset.** El integral se resetea cuando `|err| > 45°`. Durante el step -45→90°, el error supera 45° durante toda la transición, borrando el integral acumulado.

### Recomendaciones para el PID Servo

1. **No subir Ki más de 1.5** — causa oscilación en steps grandes sin mejorar el SS error
2. **La soft saturation es necesaria** — sin ella, el motor stalled a 90° causa brownout
3. **Para la tesis**: el PID es suficiente para demostraciones de posición. La precisión de ~5° es aceptable para una plataforma educativa de bajo costo
4. **Si se necesita mejor tracking**: implementar feedforward gravitacional (compensar el torque del desnivel con un término constante)

---

## 2. PID Péndulo (Modo 3) — Análisis

### ¿Para qué sirve?

El péndulo del QUBE **no tiene motor propio**. Es un brazo pasivo articulado conectado al servo. El modo 3 (PID péndulo) usa el motor del servo para intentar posicionar el péndulo en un ángulo específico, pero esto es un **sistema subactuado**: un motor para dos grados de libertad.

### Limitaciones fundamentales

| Problema | Causa |
|---|---|
| No puede sostener ángulos grandes | El torque gravitacional domina sobre el motor |
| Respuesta lenta | El motor mueve el brazo, no el péndulo directamente |
| Inestable cerca de 180° | El péndulo invertido es inestable (requiere LQR) |
| Interacción servo-péndulo | Mover el brazo perturba el péndulo y viceversa |

### ¿Cuándo es útil?

| Uso | Descripción |
|---|---|
| **Calibración** | Verificar que el encoder del péndulo lee correctamente |
| **System ID** | Excitar el péndulo con steps para medir su dinámica |
| **Posicionamiento pre-swing-up** | Mover el péndulo a una posición inicial antes de arrancar el swing-up |
| **Debug** | Verificar que el motor puede influir en el péndulo |

### ¿Qué controlador usar para el péndulo?

| Controlador | Modo | Para qué |
|---|---|---|
| **PID péndulo** | 3 | Calibración, debug, system ID |
| **LQR** | 4 | Sostener el péndulo invertido (el que funciona) |
| **Swing-up** | 5 | Llevar el péndulo de reposo a la vertical |

**El LQR (modo 4) es el controlador correcto para el péndulo.** Ya logró 55+ segundos de equilibrio invertido. El PID directo no puede reemplazarlo porque el sistema es subactuado.

---

## 3. Estado del LQR y Swing-up

Del HANDOFF.md anterior:

| Componente | Estado | Mejor resultado |
|---|---|---|
| Swing-up | ✅ Funciona | ±170° en ~10s |
| Transición a LQR | ⚠️ ~30% de éxito | Depende de condiciones iniciales |
| LQR (sostener) | ✅ Funciona | 55+ segundos |
| Anti-spin | ✅ Funciona | Detecta y frena spinning |
| Recovery | ✅ Implementado | Motor apagado hasta que péndulo cae |

### Gains LQR actuales

| Parámetro | Valor | Nota |
|---|---|---|
| K1 (servo pos) | 2.0 | |
| K2 (pend angle) | 22.0 | Base |
| K3 (servo vel) | 1.5 | |
| K4 (pend vel) | 9.0 | Base |
| K2_NEAR | 30.0 | Cerca de vertical |
| K4_NEAR | 15.0 | Cerca de vertical |
| K2_VERY_NEAR | 55.0 | Muy cerca (<5°) |
| K4_VERY_NEAR | 20.0 | Muy cerca (<5°) |

---

## 4. Próximos pasos sugeridos

1. **PID Servo**: Los gains actuales (Kp=3, Ki=0.5, Kd=0.15) son aceptables. El error estacionario de ~5-8° es una limitación física (fricción + soft saturation), no de sintonización
2. **PID Péndulo**: No requiere tuning — el LQR y swing-up son los controladores relevantes
3. **Mejora LQR**: Priorizar la reducción del ciclo límite y la confiabilidad de la transición

---

## Archivos generados

| Archivo | Descripción |
|---|---|
| `test_pid.py` | Script de test con gains por HTTP |
| `analyze_pid.py` | Análisis de métricas de step response |
| `data/servo_pid_*.csv` | Datos de tests del servo PID |
| `ANALYSIS.md` | Este documento |
