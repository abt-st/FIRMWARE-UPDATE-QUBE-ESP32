# Session Log — 2026-06-08 Swing-Up BTS7960

## Sesion completa: ~6 horas de entrenamiento

### Resumen de resultados

| Metrica | Valor |
|---|---|
| Total ensayos analizados | 173 CSVs |
| Catch rate general | 6.9% (12/173) |
| Catch rate ke=0.65 | 25-36% (9/25 a 4/10) |
| Mejor hold | 88.4s (de 90s posibles) |
| Max angle | 518° (1.4 vueltas) |
| Crash rate | 19.7% (34/173) |
| Max angle promedio | 91.1° |

### Fases de entrenamiento

#### Fase 1: Sweep ke (COMPLETADA)
5 valores x 3-5 intentos x 30-45s. ke=0.70 seleccionado inicialmente.

| ke | avg max | best | catches |
|---|---|---|---|
| 0.20 | 5.0° | 8.8° | 0/5 |
| 0.30 | 4.5° | 5.1° | 0/5 |
| 0.40 | 38.4° | 51.9° | 0/4 |
| 0.50 | 46.9° | 50.8° | 0/3 |
| 0.55 | 53.1° | 80.5° | 0/3 |
| 0.60 | 114.6° | 163.7° | 1/3 |
| **0.65** | **159.8°** | **498.5°** | **5/20** |
| 0.70 | 112.1° | 271.2° | 2/3 |
| 0.80 | 38.8° | 41.0° | 0/3 |
| 0.90 | — | 473.2° | 1/3 (erratic) |

#### Fase 2: Sweep bt (COMPLETADA)
5 valores x 3-5 intentos x 45s.

| bt | catches | best max |
|---|---|---|
| **1** | **2/5** | **469°** |
| 3 | 0/5 | 178° |
| 5 | 1/5 | 446° |
| 8 | 0/3 | 0.4° |

#### Fase 3: LQR training (COMPLETADA)
ke=0.65 y ke=0.70, 10 intentos x 90s, multiples batches.

| Config | Batches | Catches | Catch Rate | Avg Hold |
|---|---|---|---|---|
| ke=0.70 | 5 | 5/50 | 10% | 76s |
| **ke=0.65** | **3** | **9/25** | **36%** | **82s** |

#### Fase 4: Optimizacion catch rate (COMPLETADA)
Intentos de mejorar el catch rate >150°:

| Cambio | Resultado |
|---|---|
| Peak detection (alpha_dot zero crossing) | Sin mejora significativa |
| Forced transition a 165°+ | Sin mejora significativa |
| Ramp-down desde 60° | PEOR: 0% catch |
| Angle-dependent PWM limit (30% a 90°) | PEOR: 0% catch |
| Angle-dependent PWM limit (50% a 90°) | PEOR: 0% catch |
| Centering=0.05 | PEOR: 10% catch |
| Sin modulacion | PEOR: 0% catch, 30% crash |

### Distribucion de max angle

| Rango | Ensayos | Catches | Catch Rate |
|---|---|---|---|
| 0-50° | 47 | 0 | 0% |
| 50-100° | 72 | 0 | 0% |
| 100-150° | 27 | 0 | 0% |
| **150-200°** | **21** | **6** | **28%** |
| **200°+** | **4** | **4** | **100%** |

**Hallazgo clave**: El catch SOLO ocurre cuando el pendulo supera 150°. Por debajo, 0% catch.

### Bugs corregidos en la sesion

1. Python 3.14: `urlopen(url, 5)` → `urlopen(url, timeout=5)`
2. test_lqr.py: ke es argumento CLI

### Cambios al firmware (vs inicio de sesion)

| Parametro | Antes | Despues | Razon |
|---|---|---|---|
| ke_gain | 0.55 | 0.65 | Sweep ke: 0.65 mejor hold |
| soft_sat k | 80° | 120° | BTS7960 se desplaza mas rapido |
| damping threshold | 120° | 165° | Mas alcance para el pendulo |
| LQR transition hemisferio | 165° | 130° | Mas oportunidades de catch |
| LQR transition velocidad | 10°/s | 80°/s | Mas tolerante |
| LQR transition distancia | 1° | 25° | Mas tolerante |
| Hard stop servo | 150° | 120° | Evitar brownout |
| servo modulation | — | 200° cutoff | Prevenir servo stuck |
| servo centering | 0.2 | 0.15 | Balance bombeo/centrado |

### Parametros finales del firmware

```
MOTOR_DIR = -1
ke_gain = 0.65
soft_sat k = 120°
damping threshold = 165°
LQR transition: hemisferio >130°, vel <80°/s, dist <25°
hard stop servo = 120° motor-shaft (setMotorDirect)
servo modulation cutoff = 200°
servo centering kp = 0.15
balance_threshold = 1.0°
```

### Problemas identificados

1. **Catch rate 25-36%**: El pendulo solo llega a 150°+ en ~20% de los intentos
2. **Crash brownout 20%**: El motor golpea el limite mecanico y el voltaje baja
3. **Angle-dependent PWM limit mata energia**: Cualquier intento de limitar PWM cerca del limite reduce la transferencia de energia

### Soluciones pendientes

1. **Hardware**: Capacitor 470-1000uF en rail 5V del ESP32 (prevenir brownout)
2. **Mas tiempo por intento**: 90s en vez de 45s (el pendulo necesita mas ciclos)
3. **Energy dissipation controller**: Reducir amplitud de oscilacion ANTES de intentar equilibrar
