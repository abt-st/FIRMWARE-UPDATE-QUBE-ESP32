# 2026-07-30 — Intentos de swing-up (m5)

## Objetivo

Caracterizar qué tan lejos llega el swing-up del firmware y dónde exactamente falla,
con 5 intentos instrumentados y homing entre cada uno.

## Convención (importante para leer los números)

El péndulo mide **0° colgando** y **180° en vertical**. Un pico de 125° **no** es
"casi arriba": son **55° por debajo** de la vertical.

## Configuración

| | |
|---|---|
| Firmware | v1.53.2, L298N, `v_bus` ≈ 14.8 V |
| `ke_gain` | valor por defecto (0.65), **no** barrido — ver caveat abajo |
| Intentos | 5, con homing antes de cada uno |
| Duración máx | 20 s por intento |
| Muestreo | `/state`, 8–13 Hz efectivos |

## Resultados

Dos tandas: la primera a ciegas, la segunda con el criterio de traspaso latcheado en
`/state` (firmware v1.55.0, implementado a raíz de la primera).

### Tanda 2 — con telemetría del traspaso

| # | pico \|α\| | criterio | α al traspasar | velocidad | E/E* | desenlace |
|---|---|---|---|---|---|---|
| 1 | 123.6° | **`forced`** | 125.16° | 506 °/s | **0.812** | límite servo → `safeStop` |
| 2 | 127.6° | **`forced`** | 127.27° | 705 °/s | **0.850** | límite servo → `safeStop` |
| 3 | 125.7° | **`forced`** | 125.16° | 531 °/s | **0.815** | límite servo → `safeStop` |
| 4 | 129.2° | **`forced`** | 125.33° | 871 °/s | **0.862** | límite servo → `safeStop` |

**Siempre `forced`, sólo `forced`.** Los otros tres criterios no dispararon nunca.

## Diagnóstico

### `forcedTransition` prevalece sobre los criterios buenos, siempre

De las cuatro condiciones de traspaso, tres exigen que el péndulo vaya lento o que la
energía esté en tolerancia. `forcedTransition` **no exige ninguna de las dos**:

```c
bool forcedTransition = fabsf(pendPos) > SWINGUP_TRANS_FORCED_DEG;  // 125 deg
```

El péndulo cruza los 125° a 500–870 °/s con **81–86% de la energía necesaria**, y esa
única línea lo entrega al LQR ahí mismo. Como el umbral forzado (125°) está apenas por
encima del de cercanía (120°), se cruza antes de que las condiciones con compuerta
lleguen a cumplirse: **los criterios que sí verifican velocidad y energía quedan
efectivamente muertos**.

Un LQR linealizado en torno a la vertical recibe entonces un péndulo a 55° del punto
de operación y girando rápido. Aguanta 1–2,5 s empujando y el brazo cruza el límite
blando de 95°.

### El bombeo tampoco alcanza

Aun sin el traspaso prematuro, `E/E*` nunca pasó de 0.862: el swing-up no inyecta la
energía para llegar arriba. Son **dos fallas encadenadas**, y arreglar sólo el umbral
no basta.

### Corrección respecto de la primera tanda

La tanda 1 sugería que el ángulo de traspaso variaba entre 76° y 128°. **Era falso**,
producto del retraso de muestreo: el cliente muestrea a 8–13 Hz y ve el cambio de modo
hasta 120 ms tarde, con el péndulo ya cayendo. Los cuatro criterios exigen
`|pendPos| > 120`, así que un traspaso a 76° era imposible por construcción. Con el
valor latcheado por el firmware el ángulo real resulta **consistente en ~125–127°**,
justo pasando el umbral forzado.

Es el argumento a favor de latchear en el firmware en vez de inferir desde el cliente.

## Caveats

- **Muestreo a 8–13 Hz.** Es lento para un péndulo bombeando: el pico real de α puede
  ser mayor que el muestreado. Los picos de la tabla son **cotas inferiores**. La
  conclusión no cambia (faltan >50°, no 5°), pero los valores exactos no son finos.
- **`ke_gain` no se barrió.** Estaba documentado que en modo 5 la velocidad del
  péndulo se lee ≡0, lo que dejaría el bombeo por energía como rama muerta. **Esa nota
  parece desactualizada**: el firmware reporta 506–871 °/s en el instante del traspaso.
  Pero esas velocidades son sospechosamente altas para un péndulo subiendo a 125°
  —contrastadas con `E/E*` implican una frecuencia natural de ~4,5 Hz, bastante más
  que lo típico— así que el valor absoluto no es confiable todavía. **Conviene
  re-verificar antes de apoyarse en él.** No afecta la conclusión: si la velocidad
  está inflada, la `E/E*` real es aún **menor**.
- Los 5 intentos corrieron seguidos, con la misma mecánica y sin recalibrar más que el
  homing automático. No se probaron condiciones iniciales distintas.

## Lo que sí funcionó

El homing recuperó el cero después de cada intento, con recorrido 269.47–270.00°.
Sin eso estas tandas habrían requerido mover el brazo a mano entre cada intento.

### La validación de recorrido atrapó una falla mecánica real

Al final de la tanda 2 el péndulo **quedó enganchado** mecánicamente. El homing falló
con `fail=1` y midió un recorrido de **7.56°**, y —lo que importa— **no fijó el cero**.

| estado | recorrido medido | resultado |
|---|---|---|
| enganchado | 7.56° | `fail=1`, cero **no** fijado |
| liberado a mano | 269.648° | OK, cero fijado |

269.648° es exactamente el mismo valor que venía dando antes del enganche. La ventana
de 250–290° hizo justo lo que debía: negarse a calibrar contra un mecanismo trabado en
vez de generar un cero basura y seguir como si nada.

El síntoma diagnóstico fue el recorrido libre del brazo: `SEEK_POS` se calaba en un
extremo y `BACKOFF_POS` en el otro, con **PWM −55 sostenido 9 s moviendo un solo
conteo**. Una ventana de ~4° donde deberían haber 270 no es un tope, es un atasco.

## Archivos

```
scripts/swingup_attempt.py   # --attempts N --max-s S --ke X
data/attempt_XX.csv          # traza por intento
data/attempts.json           # métricas derivadas
```

## Próximos pasos sugeridos

1. ~~Exponer el criterio de transición en `/state`.~~ **Hecho** (v1.55.0). Es lo que
   permitió todo el diagnóstico de arriba.
2. **Poner compuerta de velocidad/energía a `forcedTransition`,** o subir su umbral
   bastante por encima de 125°. Hoy anula a los otros tres criterios. Es el cambio de
   una línea con mayor impacto pendiente.
3. **Re-verificar la velocidad del péndulo en modo 5.** El firmware reporta 506–871 °/s,
   lo que contradice la nota de que era ≡0, pero el valor absoluto es dudoso (implica
   ~4,5 Hz de frecuencia natural). Sin confiar en α̇ no se puede confiar en `E/E*`
   como criterio ni barrer `ke_gain` de forma atribuible.
4. **Recién ahí** subir la energía de bombeo. Adelantarlo es lo que ya se intentó
   antes sin resultados atribuibles.
