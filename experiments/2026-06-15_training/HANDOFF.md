# HANDOFF — Training Session 2026-06-15

## Estado del hardware
- ESP32 IP: `192.168.100.50`
- Driver: BTS7960
- INA219: **DESCONECTADO** (ina_ok=false, v_bus=0.0V)
- **Encoders reconectados** al final de la sesión (se desconectaron durante flash)
- Pendulum encoder: GPIO32/33
- Servo encoder: GPIO34/35
- Schmitt Trigger: CD40106BE

## Firmware actual

Último firmware desplegado con transición modificada:
- **Transición LQR:** >120° (±60° de vertical), era >160° (±20°)
- **Forced transition:** >125°
- **Catch mode:** gain=0.25, limit ±25 (era ±100)
- **Centering gain:** 0.5
- **ke_gain:** 0.65 (base), 0.75 (boost)
- **KE_GAIN_BOOST:** 1.5

## Resumen de la sesión

### 1. Bracket Test: sp=58 vs 60 vs 62

| SP | Catch | Chatter | Trans | Miss | Clean% | Eff% | N |
|----|-------|---------|-------|------|--------|------|---|
| 58 | 5 | 4 | 1 | 0 | 50% | 90% | 10 |
| **60** | **21** | **5** | **3** | **0** | **72%** | **90%** | **29** |
| 62 | 3 | 5 | 0 | 0 | 38% | 100% | 8 |

### 2. Stability Test 10min sp=60

| Métrica | Valor |
|---------|-------|
| CATCH | 13/17 (76%) |
| CHATTER | 3/17 (18%) |
| MISS | 1/17 (6%) |
| Effective | 94% |
| Degradación | -26% (mejoró) |

### 3. Extended Training 20min sp=60

| Métrica | Valor |
|---------|-------|
| CATCH | 21/29 (72%) |
| CHATTER | 5/29 (17%) |
| TRANSIENT | 3/29 (10%) |
| MISS | 0/29 (0%) |

**Patrón:** Chatter siempre por overshoot >200°. TRANSIENT = LQR pierde equilibrio después de catch.

### 4. Constrained Test ±90°

#### Con transición original (>160°) y sp=60
- 0% catch — pendulum no llega a 160°

#### Con transición ±45° (>135°) y sp=80
- 11% catch (2/19), 21% escape, 68% miss
- Los 2 catches fueron estables: 28.8s y 28.6s dentro de ±90°

#### Con transición ±60° (>120°) y sp=90
- 6% catch (1/17), 12% escape
- Primer intento: CATCH con 29.0s estable
- Después: encoder se desconectó (hardware)

### 5. Problema de hardware

Los encoders se desconectaron durante flash repetido. Verificado:
- `pend_count=0`, `pend_position_deg=0.0°` incluso después de mover servo
- **Reconectados al final de la sesión**

## Hallazgos clave

### Overshoot = Chatter
```
max_angle > 200° → 100% chatter
max_angle ≤ 200° → 88% catch limpio, 0% miss
```

### Transición más temprana mejora catch rate
| Umbral transición | Catch rate (con ±90°) |
|---|---|
| >160° (original) | 0% (pendulum no llega) |
| >135° (±45°) | 11% (sp=80) |
| >120° (±60°) | 6% (sp=90, limitado por hardware) |

### sp=80 necesario para ±90° constraint
- sp=60: solo llega a 58-132°, insuficiente para transición
- sp=80: llega a 135°+, transiciona correctamente
- sp=90: funciona pero overshoot posible

### Servo centering durante reset interfiere
- El centering (m=2, s=0) mueve el péndulo antes de empezar
- Reset simple (x=1 + wait 3s + r=1) es más confiable

## Próximos pasos

### 1. Verificar encoders reconectados
```bash
curl "http://192.168.100.50/state"
# Verificar pend_count != 0 al mover péndulo manualmente
```

### 2. Repetir constrained test con sp=90
Los encoders ya están reconectados. El primer intento del test anterior dio CATCH (29s estable).

### 3. Si funciona, documentar como sweet spot final
- sp=90 con transición >120°
- Restricción ±90° en fase LQR
- Target: >30% constrained catch rate

### 4. Si no funciona, ajustar
- Probar sp=85, 95
- Ajustar ke_gain (subir a 0.8 o 0.9)
- Verificar INA219 (reconectar para monitoreo de voltaje)

## Archivos generados

```
experiments/2026-06-15_training/
├── stability_test.py           # Test estabilidad 10min
├── extended_training.py        # Training combinado
├── constrained_test.py         # Test con restricción ±90°
├── HANDOFF.md                  # Este archivo
└── data/
    ├── stability_20260615T140354/   # sp=60 10min (76% catch)
    ├── training_20260615T152942/    # sp=60 20min (72% catch)
    ├── bracket_20260615T154949/     # sp=58,62 (50%, 38%)
    ├── constrained_20260615T165908/ # ±90° sp=60 (0%)
    ├── constrained_20260615T171835/ # ±90° sp=60 (0%)
    ├── constrained_20260615T172933/ # ±90° sp=80 (0%)
    ├── constrained_20260615T174014/ # ±90° sp=80 (11%)
    ├── constrained_20260615T175300/ # ±90° sp=80 (0%)
    ├── constrained_20260615T180325/ # ±90° sp=90 (6%)
    └── constrained_20260615T181344/ # ±90° sp=90 (0% — encoder broken)
```

## Cambios de firmware realizados

```cpp
// ANTES (transición original):
bool nearVertical = fabsf(pendPos) > 160.0f;
bool forcedTransition = fabsf(pendPos) > 165.0f;

// DESPUÉS (transición ±60°):
bool nearVertical = fabsf(pendPos) > 120.0f;
bool forcedTransition = fabsf(pendPos) > 125.0f;
```

## Comandos para la próxima sesión

```bash
# Verificar encoders
curl "http://192.168.100.50/state"

# Test rápido sp=90
curl "http://192.168.100.50/cmd?r=1" && sleep 3 && curl "http://192.168.100.50/cmd?sp=90" && sleep 0.1 && curl "http://192.168.100.50/cmd?m=5"

# Ejecutar constrained test
uv run python experiments/2026-06-15_training/constrained_test.py

# Analizar resultados
uv run python experiments/2026-06-15_sweep_v3/analyze_sweep.py experiments/2026-06-15_training/data
```
