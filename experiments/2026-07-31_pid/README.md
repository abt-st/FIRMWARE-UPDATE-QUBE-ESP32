# 2026-07-31 — Ajuste del PID del servo (m2), P6

## Objetivo

Bajar el sobrepaso del PID de posición del brazo y cerrar el error de régimen de 4,8°,
distinguiendo qué parte del problema es ajuste y qué parte era instrumentación.

## Estado

**Barrido pendiente.** El banco no estaba accesible por HTTP cuando se preparó esta
campaña. Lo que sí está hecho y verificado por cálculo sobre las trazas del 30:

1. **La cifra de sobrepaso estaba inflada por la métrica.** `validate.py` normalizaba
   por `|setpoint|` en vez del tamaño del escalón y tomaba el pico de todo el segmento.
   Recalculado sobre las mismas trazas: **68,3–76,7% → 38,8–42,0%** en el escalón
   grande. Sigue siendo alto; deja de ser catastrófico.
2. **El kick anti-fricción no podía funcionar**: exigía `|err| > 8°` cuando la banda
   donde el brazo queda pegado es 0,8–8°, y aplicaba 12 PWM cuando el mecanismo
   necesita ~45 para arrancar (el homing usa `HOMING_PWM_MIN = 45`).

## Convención de la métrica (importante para comparar con el 30)

| métrica | definición |
|---|---|
| `overshoot_pct` | `(pico − sp) / (sp − θ₀)`, pico tomado **tras el primer cruce** del setpoint |
| `overshoot_legacy` | `(max\|θ\| − \|sp\|) / \|sp\|` — la del 2026-07-30, se conserva para empalmar |

En escalones que cruzan el cero la vieja da ~el doble. En escalones cortos da **menos**
que la nueva, porque ahí el escalón es menor que `|sp|`.

## Protocolo

Igual al de la campaña de validación, para que las cifras sean comparables: homing →
`m2` con setpoints 20° → −20° → 0°, 3,5 s cada uno, muestreo de `/state` a ~25 Hz.
Puntos intercalados por repetición, para que una deriva lenta del banco afecte a todos
por igual en vez de castigar al último.

```bash
# Sobrepaso: hipotesis principal, amortiguamiento derivativo (Td = Kd/Kp = 0,05 s)
python scripts/sweep_pid.py --kd 0.15,0.3,0.45,0.6 --reps 3
python scripts/sweep_pid.py --kp 2 --kd 0.3,0.45,0.6 --tag kp2   # si no baja de 20%

# Error de regimen: kick anti-friccion
python scripts/sweep_pid.py --sweep-stiction --sk 12,20,30,40 --tag sk
```

## Criterio de aprobación

Sobrepaso **< 20%** con la métrica nueva, sin degradar `sse_max` (hoy 4,8°) y **sin
hunting**.

El hunting se mide a propósito: subir el piso del kick puede cambiar un error de
régimen por un ciclo límite alrededor del setpoint, que es peor. Un punto con
sobrepaso bajo, `cruces` altos y `pwm_activo_frac ≈ 1,0` en régimen **no** es un punto
bueno — es un lazo que nunca se asienta.

## Archivos

| | |
|---|---|
| `scripts/sweep_pid.py` | barrido; reusa `Qube` y `step_overshoot` de la campaña del 30 |
| `data/{tag}_{punto}_r{n}.csv` | traza por corrida |
| `data/sweep_{tag}.json` | resumen por punto |
