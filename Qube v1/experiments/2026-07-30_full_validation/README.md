# 2026-07-30 — Validación exhaustiva de los 8 modos

## Objetivo

Verificar que el firmware funciona bien tras una jornada de cambios (homing en `m3`,
gancho en `QubeRealEnv`, telemetría de traspaso). A diferencia del barrido del mismo
día, acá **cada modo se corre 3 veces y tiene un criterio de aprobación escrito**:
"funciona bien" es una condición evaluable, no una impresión mirando números.

## Método

Cada repetición arranca con homing, así que `position_deg` es comparable entre
repeticiones y entre modos. El homing **reintenta una vez**: su modo de falla conocido
(`fail=1`, recorrido fuera de tolerancia) también aparece cuando la mecánica se traba
de verdad, y ahí hay que parar, no insistir.

Muestreo a ~25 Hz con pausa deliberada entre peticiones: sin ella el stack AsyncTCP
del ESP32 deja de responder (comprobado en esta misma jornada).

### Protocolo y criterio por modo

| modo | protocolo | criterio de aprobación |
|---|---|---|
| m0 STOP | 5 s en reposo | PWM ≡ 0 |
| m1 PWM | ±50 en pasos de 1,2 s | \|PWM reportado − pedido\| ≤ 2 **y** movió en ambos sentidos |
| m2 PID | escalones 20° → −20° → 0° | error en régimen < 8° y sin cortes por límite |
| m3 Homing | rutina completa | `homing_ok` y recorrido 269,65 ± 3° |
| m4 LQR | 10 s | acciona el motor (>5% del tramo) |
| m5 Swing-up | 10 s | traspasa a LQR en todas; se registra el criterio |
| m6 RL HTTP | acciones ±0,35 y 0 | **una acción no nula mueve el motor** |
| m7 RL chip | 10 s | inferencia activa (σ(PWM) > 5) |

Nota sobre `m6`: mandar sólo acción 0,0 —como hizo el barrido anterior— comprueba el
transporte HTTP, no que la acción llegue al actuador. Acá se mandan acciones no nulas
alternadas y se exige que el PWM responda.

Los pasos de `m1` duran menos de 2 s a propósito: ese modo tiene un deadman de 2,5 s
y un paso más largo se cortaría solo a mitad de medición.

## Archivos

```
scripts/validate.py    # campaña: --reps N --only 0,2,3
scripts/analyze.py     # re-analiza sin volver a mover el hardware
data/m{modo}_rep{n}.csv
data/reps.json         # métricas por repetición (guardado incremental)
data/verdicts.json     # pass/fail por modo
```

## Resultados

Ver `RESULTADOS.md` (generado tras la campaña).
