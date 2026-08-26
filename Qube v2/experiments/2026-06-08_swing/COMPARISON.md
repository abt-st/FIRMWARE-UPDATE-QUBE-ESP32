# Comparativa Historica — Swing-Up QUBE Servo

## Evolucion temporal (4 sesiones)

| Sesion | Driver | ke | Mejor Hold | Catch Rate | Mejor Max | Problema principal |
|---|---|---|---|---|---|---|
| 2026-06-01 | L298N | 0.45 | 0.5s | ~0% | 0.2° de vertical | LQR no sostiene, servo desborda |
| 2026-06-03 | L298N | 0.45-0.5 | 11.3s | ~0% | 181.2° | Brownout, spinning, offset drift |
| 2026-06-04 | L298N | 0.5 | 7.7s | ~0% | 170° | Hardware danado, alpha discontinuo |
| **2026-06-08** | **BTS7960** | **0.65** | **88s** | **25-36%** | **518°** | **Crash brownout 20%, catch rate bajo** |

## Mejoras logradas por sesion

### Sesion 2026-06-01 (L298N, primer swing-up)
- Fix signo de energia (bug critico)
- Kick alternante para iniciar oscilacion
- normalizeAngle() para LQR
- Fallback automatico LQR -> swing-up
- Hard stop de servo
- Filtro velocidad EMA
- Subio de 200Hz a 500Hz
- **Mejor**: LQR atrapo a 0.2° de vertical pero solo 5 muestras (0.5s)

### Sesion 2026-06-03 (L298N, iteracion LQR)
- else if fix en cadena de modos (critico)
- Disipacion de energia en 3 rangos
- Anti-spin con cooldown
- LQR gains: K2_NEAR=30, K4_NEAR=15
- Catch mode 400ms, ±60 PWM
- Soft saturation implementada
- **Mejor**: LQR sostuvo 55+ segundos (un solo intento)
- **Problemas**: Brownout cada ~10s, crash loop

### Sesion 2026-06-04 (L298N, noche)
- Alpha continuo (elimina discontinuidad)
- Recovery persistente en swing-up
- Servo protection direction-aware
- Dead zone ajustada 172°->160°
- Damping progresivo 150°-180°
- **Mejor**: LQR sostuvo 11.3s
- **Problemas**: Hardware danado (diodo, capacitor), INA219 danado

### Sesion 2026-06-08 (BTS7960, esta sesion)
- Driver BTS7960 (RDS 166x menor que L298N)
- Filtro EMA para swing-up alpha_dot
- setMotorDirect() bypass soft saturation
- Modulacion por posicion del servo
- Centering suave del servo
- Sweep automatizado ke/bt via HTTP
- Python scripts de analisis
- **Mejor**: LQR sostuvo 88s, 25-36% catch rate, 518° max
- **Problemas**: Crash brownout 20%, catch rate 25-36%

## Comparacion L298N vs BTS7960

| Metrica | L298N (mejor) | BTS7960 (mejor) | Factor |
|---|---|---|---|
| Mejor hold | 55s | 88s | 1.6x |
| Hold promedio | ~8s | 82s | 10x |
| Catch rate | ~0% (1 intento) | 36% | infinito |
| Max angle | 181° | 518° | 2.9x |
| Crash rate | ~50% | 20% | 2.5x mejor |
| Servo max | ~87° | ~100° | similar |
| ke sweet spot | 0.45-0.50 | 0.65 | +30-45% |

## Bugs corregidos a lo largo de todas las sesiones

1. **Signo de energia invertido** (2026-06-01) - energy_sign = (Er > E)
2. **normalizeAngle para LQR** (2026-06-01) - alpha en [-180,180]
3. **if vs else if en modos** (2026-06-03) - cadena if/else if
4. **Energia con angulo raw >360°** (2026-06-03) - usar wrapped
5. **Alpha discontinuo en LQR** (2026-06-04) - aritmetica modular
6. **Recovery no persistente** (2026-06-04) - variable global
7. **Velocidad sin filtrar en swing-up** (2026-06-08) - EMA filter
8. **Soft sat mata PWM de frenado** (2026-06-08) - setMotorDirect
9. **Servo sin centering** (2026-06-08) - kp=0.15 centering
10. **Modulacion agresiva** (2026-06-08) - cutoff 200°

## Parametros finales (BTS7960, v1.36.1)

### Swing-up
```
ke_gain = 0.65
MOTOR_DIR = -1
kick_duty = 0.7 (50 PWM)
kick_period = 250ms
damping threshold = 165°
modulation cutoff = 200°
centering kp = 0.15
hard stop = 150° motor-shaft
```

### LQR
```
K1=2.0, K2=22, K3=1.5, K4=9
K2_NEAR=30, K4_NEAR=15 (|alpha|<25°)
K2_VERY_NEAR=55, K4_VERY_NEAR=20 (|alpha|<5°)
DAMPING=0.3 (|alpha|<25°)
PWM limit = ±70
centering = 1.0
```

### Transicion
```
hemisferio > 130°
velocidad < 80°/s
dist_from_up < 25°
balance_threshold = 1.0°
```

### Protecciones
```
soft_sat k = 120°
servo hard stop = 120° (setMotorDirect)
anti-spin = 360° raw delta
```

## Resultados de experimentacion (Fase 4)

| Cambio probado | Efecto en catch rate | Efecto en crash rate | Veredicto |
|---|---|---|---|
| Peak detection (alpha_dot zero crossing) | Sin cambio | Sin cambio | DESCARTADO |
| Forced transition a 165°+ | Sin cambio | Sin cambio | DESCARTADO |
| Ramp-down desde 60° | PEOR: 0% | PEOR: 30% | DESCARTADO |
| Angle-limit 30% a 90° | PEOR: 0% | 10% | DESCARTADO |
| Angle-limit 50% a 90° | PEOR: 0% | 10% | DESCARTADO |
| Centering=0.05 | PEOR: 10% | 10% | DESCARTADO |
| Sin modulacion | PEOR: 0% | PEOR: 30% | DESCARTADO |

### Conclusion de la Fase 4
Cualquier intento de limitar PWM cerca del limite MATA la transferencia de energia.
El servo necesita autoridad completa para bombear energia al pendulo.
El brownout es un problema de hardware que requiere un capacitor 470-1000uF en rail 5V.

### Distribucion de max angle (173 ensayos)
| Rango | Ensayos | Catches | Catch Rate |
|---|---|---|---|
| 0-50 | 47 | 0 | 0% |
| 50-100 | 72 | 0 | 0% |
| 100-150 | 27 | 0 | 0% |
| 150-200 | 21 | 6 | 28% |
| 200+ | 4 | 4 | 100% |

**Hallazgo**: Catch SOLO ocurre a 150°+. 85% de intentos no llegan.

## Proximos pasos recomendados

### Prioridad 1: Hardware (brownout)
- **Capacitor 470-1000uF en rail 5V del ESP32** — unico fix para brownout
- Sin capacitor, 20% de crashes es inevitable

### Prioridad 2: Mas tiempo por intento
- 90s en vez de 45s — el pendulo necesita mas ciclos para llegar a 150°+
- Los intentos que llegan a 150°+ tienen 28-100% catch rate

### Prioridad 3: Energy dissipation controller
- Cuando el pendulo llega a 120-150°, reducir amplitud ANTES de intentar equilibrar
- Podria mejorar el catch rate de 28% a 50%+ en el rango 150-180°

### Prioridad 4: Arquitectura
- Kalman filter para mejor estimacion de estado
- MPC o sliding mode para control no-lineal
- System identification para ganancias LQR optimas
