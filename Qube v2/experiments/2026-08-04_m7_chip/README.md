# m7 — Deep RL en chip: primer criterio y primera medición

**Criterio escrito ANTES de medir.** Firmware v1.58.6.

## Por qué esta campaña

m7 es el modo con menos evidencia de los ocho. Lo único verificado hasta hoy es
`inference_active` (`pwm_std > 5`): **que el motor se mueve**. Los "9,9–10,0 s" que
aparecen en la campaña de bring-up son la **duración de la ventana de grabación**, no un
tiempo de balanceo.

Y es el de mayor leverage: corre la inferencia **en la ESP32, a la frecuencia del lazo**,
así que es el único despliegue que no arrastra los 14,3 Hz del enlace HTTP
([P20](../../docs/REGISTRO_PROBLEMAS.md#p20)).

## Qué política está flasheada

Se determinó por comparación numérica de los pesos del header contra todos los modelos
del repo — el header no registra su origen, así que hasta hoy nadie lo sabía:

| | |
|---|---|
| modelo | **`r7_cur0.3_s0_best.zip`** (coincidencia exacta, `dif_max = 0,000000`) |
| SHA256 modelo | `28BD7F7F1C4A4EE658797227B15DAC9B…` |
| SHA256 `policy_weights.h` | `21ABD5C49332EF0459C0F5F8B5D55059…` |
| exportado | 2026-06-24 |
| arquitectura | 36 → 64 → 64 → 1 (6593 parámetros) |

**No es `r7_ft_fr100_s0_best`**, que era el "mejor candidato confirmado" de junio con
re-evaluación a 100 episodios. Es un checkpoint del currículum, sin fine-tuning.

Aun así **sirve**: en la sim con el `Dp` medido da 5/5 al ápice y hold 8,62–9,60 s
(media 9,14 s), sin saturación. Comparable a `r7_ft_fr100_s0_best` (9,43 s). Por eso no
se re-exporta: la que está flasheada es una candidata válida.

## El descubrimiento que define el diseño

**El modo 7 traspasa a la MISMA ley LQR del modo 4** cuando `|α| ≥ hybrid_enter_deg`
(default 165°). O sea que **el balanceo de m7 es el de m4**, que hoy sostiene ~0,5 s
([P4](../../docs/REGISTRO_PROBLEMAS.md#p4)).

Medir m7 tal cual **vuelve a medir el LQR, no la política**. Por eso el A/B:

| condición | `he` | quién balancea |
|---|---|---|
| **A — híbrido** | 165 (default) | la política sube, el **LQR** balancea |
| **B — política sola** | 179 | el traspaso casi no dispara: **la política** balancea |

La condición B es la prueba sim2real honesta que P20 pedía: una política de 50 Hz,
corriendo a la frecuencia del lazo, sin HTTP en el medio.

`hybrid_enter_deg` y `hybrid_exit_deg` existían desde hace tiempo pero **sólo por
Serial**, y abrir el serial reinicia la placa: en la práctica eran inalcanzables. v1.58.6
los expone como `?he=` y `?hx=`, y agrega `hybrid_lqr` a `/state` — sin eso no se puede
saber si un intento lo balanceó la política o el LQR.

## Criterio (fijado antes de medir)

**m7 se considera funcional si**, desde péndulo colgando y con n = 5:

1. **Alcanza la vertical** (`|α − 180°| < 15°` en algún momento) en **≥ 3 de 5** intentos.
2. **Sostiene** `|α − 180°| < 15°` durante **≥ 3 s continuos** en **≥ 3 de 5** intentos.
3. **El lazo no se degrada**: `loop_overruns = 0` y `loop_dt_max_us` sin excursiones — la
   inferencia on-chip no puede romper los 500 Hz. Si los rompe, m7 tiene un problema
   propio, distinto de P20.

**Se registra por intento:** `hybrid_lqr` (quién balanceó), `pend_wraps`, `swing_ceiling_hits`,
`loop_dt_max_us`, `loop_overruns` y la traza de α.

> **Un FAIL documentado también cierra la etapa.** El objetivo es que m7 tenga un
> veredicto medido contra un criterio escrito antes, no que apruebe.

## Predicción, anotada de antemano

- **Condición A** debería fallar el criterio 2, porque el balanceo es el LQR de P4
  (~0,5 s). Si aguanta mucho más, entonces el LQR del m7 y el del m4 no son equivalentes
  y hay que entender por qué.
- **Condición B** es genuinamente incierta. Es la primera vez que se mide esta política
  sobre el hardware sin el cuello del enlace.

## Resultados — 2026-08-04

**m7 FALLA su criterio**, en las dos condiciones.

| | A — híbrido (`he=165`) | B — política sola (`he=179`) |
|---|---|---|
| 1. alcanza la vertical | 4/5 ✅ | **2/5** ❌ |
| 2. sostiene ≥ 3 s | **0/5** ❌ | **0/5** ❌ |
| 3. lazo sin overruns | **❌** | **❌** |
| holds (s) | 0,0 · 0,07 · 0,18 · 1,29 · 1,97 | 0,0 · 0,0 · 0,0 · 0,10 · 0,17 |

**La predicción de la condición A se cumplió:** el balanceo es el LQR del modo 4, y
sostiene lo que sostiene P4 (~0,5 s). En 4 de 5 intentos balanceó el LQR.

## El hallazgo: la inferencia en chip rompe el lazo de 500 Hz

No estaba previsto, y es lo que más importa de la campaña.

`loop_dt_max_us` dio **17–23 ms en los diez intentos**, contra los 2000 µs nominales:
paradas de **diez períodos**. Y los `overruns` salieron bimodales — {22, 31, 32, 36}
contra {262, 271, 284, 286, 287} — así que se midió el tiempo real pasado en cada rama:

| `he` | rep | s en rama política | overruns |
|---|---|---|---|
| 165 | 1 | 24,4 | 284 |
| 165 | 2 | 25,0 | 287 |
| 165 | 3 | 0,2 | 31 |
| 165 | 4 | 0,1 | 22 |
| 165 | 5 | 0,1 | 32 |
| 179 | 1 | 25,0 | 271 |
| 179 | 2 | 25,0 | 262 |
| 179 | 3 | 11,0 | 137 |
| 179 | 4 | 2,9 | 36 |
| 179 | 5 | 25,0 | 286 |

```
corr(segundos en rama política, overruns) = +0,996   (n = 10)
```

Prácticamente lineal: **~10,6 overruns por cada segundo de inferencia**. Los intentos
dominados por el LQR se quedan en 22–32, que es la línea base por conmutación del motor
ya documentada en [P15](../../docs/REGISTRO_PROBLEMAS.md#p15) (19–32). **La rama del LQR
es barata; la de la política no.**

A 50 Hz de tick, 10,6 overruns/s significa que **~21% de las inferencias atrasan el lazo
más de 10 ms**. Para una red de 36→64→64→1 —unas 6.464 multiplicaciones— en un ESP32 a
240 MHz, eso es del orden de **100× más lento** de lo esperable. No es el costo natural de
la red: hay algo patológico en cómo se ejecuta.

## Lo que esto permite y NO permite concluir

**Permite:** m7 no cumple su criterio, y la causa está instrumentada.

**No permite** decir que la política no transfiere. Una política de 50 Hz cuyo lazo se
atasca 10 ms en una de cada cinco decisiones no está corriendo a 50 Hz. Es el mismo
problema que [P20](../../docs/REGISTRO_PROBLEMAS.md#p20) —el despliegue no sostiene la
frecuencia de diseño— pero adentro del chip en vez de en el enlace.

**El sim2real sigue sin medirse.** Van dos caminos de despliegue y los dos fallan por
frecuencia antes de llegar a la pregunta.

## Qué sigue

1. **Medir cuánto tarda una inferencia**, con un contador alrededor de la llamada. Es el
   dato que falta para saber si el problema es la red, el acceso a los pesos en flash, o
   algo del armado de la observación.
2. Recién con eso se puede decidir: optimizar la inferencia, bajar la frecuencia de
   inferencia por debajo de 50 Hz (y re-entrenar a esa frecuencia), o achicar la red.
3. **No re-exportar ni re-entrenar nada hasta entonces.** Cambiar la política no puede
   arreglar un problema de tiempo de ejecución.
