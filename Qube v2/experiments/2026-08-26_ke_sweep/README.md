# 2026-08-26 — Barrido de `ke`, salud del enlace y frecuencia de oscilación

Campaña de banco de una sola sesión. Firmware v1.63.0 (árbol de trabajo, con los cambios
sin commitear del LED de estado). Todas las trazas son del DAQ del chip a 500 Hz
(`/daq`), marcadas por el tick que produjo cada muestra.

> **Aviso de comparabilidad.** Todo es de la MISMA sesión, en el orden en que está
> numerado, con homing entre cada tanda. El banco deriva dentro de una sesión
> ([P12](../../docs/REGISTRO_PROBLEMAS.md#p12)), así que estas tandas se comparan entre sí
> y **no** contra campañas de otro día.
>
> **Y las tandas se tomaron sondeando `/state` a 4 Hz**, que según
> [P28](../../docs/REGISTRO_PROBLEMAS.md#p28) le cuesta al lazo una resincronización por
> petición. Se dejó a **tasa fija en todas las tandas** para que la carga sea una
> constante del experimento y no un confundente entre tandas — pero está ahí.

## Qué hay

| archivo | qué es |
|---|---|
| `campana.py` | Corre las tandas de `ke`: homing, parámetros, `m5`, DAQ y salud del enlace |
| `caida_multiple.py` | N sueltas seguidas con el brazo retenido, para medir `f_n` |
| `analisis.py` | Consolida tandas, enlace y frecuencia por banda de amplitud |
| `data/registro_*.jsonl` | Un registro por tanda: parámetros, latches del firmware, enlace, DAQ |
| `data/*.csv` | Trazas a 500 Hz |

## Resultado 1 — el traspaso NO es lo que falla; el brazo llega al tope

Línea base (`ke` adaptativo, `tn=162`, `rt=0`):

| campo | valor |
|---|---|
| `swing_trans_reason` | **8 = energy** — el criterio bueno, no `forced` |
| `swing_trans_alpha` | −165,23° |
| `swing_trans_energy` | 0,984 |
| `lqr_alive_ms` | 576 ms |
| `swing_fail_reason` | **3 = el brazo llegó al tope** |
| θ máx | **134,65°** = el tope mecánico |

La secuencia de eventos lo dice entera:

```
t=5,116 s   modo 4, traspaso reason=8   θ = −2,64°    ← el brazo entra CENTRADO
t=6,004 s   modo 0, fail=3              θ = +130,08°  ← 0,89 s después, en el tope
```

El swing-up entrega bien: péndulo a 15° de la vertical, casi detenido, con la energía
justa, y el brazo centrado. **Lo que falla es el LQR: en 0,89 s manda el brazo de −2,6° a
130°.** Es el síntoma que [P26](../../docs/REGISTRO_PROBLEMAS.md#p26) predice —los cuatro
términos de «empujar al centro» sin `MOTOR_DIR`, con `homing_pwm_sign = −1` medido en las
cinco tandas de esta sesión.

## Resultado 2 — LA SESIÓN DERIVÓ, y eso invalida todo barrido de parámetros de hoy

**Esto se descubrió al final y reencuadra los Resultados 2 a 4. Va primero a propósito.**

| hora | etiqueta | `ec` | `cg` | traspaso | `ceil` | α máx | θ máx | `homing_range` | centro |
|---|---|---|---|---|---|---|---|---|---|
| 13:03 | base | 1,15 | 0 | **8 = energy** | 38 | 180,0 | 134,7 | 268,94 | −41,31 |
| 13:04 | ke 0,40 | 1,15 | 0 | 0 | 31 | 180,0 | 103,3 | 269,82 | −41,57 |
| 13:04 | ke 0,90 | 1,15 | 0 | 0 | 23 | 179,1 | 104,9 | 270,35 | −42,19 |
| 13:24 | ec_comp ×3 | 0,64 | 0 | 0 · 0 · 0 | 307/476/69 | ~179,8 | 85–136 | 270,2–270,4 | −41,8 |
| 13:26 | p26_cg ×3 | 1,15 | 1 | 0 · 0 · 0 | 0/34/0 | 119–180 | 112–119 | 270,2–270,4 | −41,9 |
| **13:28** | **base_control ×3** | **1,15** | **0** | **0 · 0 · 0** | 6/0/1 | 127–180 | 112–135 | 270,4–270,5 | −42,0 |

La línea base de control de las 13:28 tiene **exactamente los mismos parámetros** que la de
las 13:03. Pasó de **1/1 traspasos a 0/3** en 25 minutos y ~30 corridas de motor.

Y la deriva **no es de calibración ni de alimentación**:

- `homing_range` 268,94–270,53° (dispersión 1,6°) — el recorrido no se movió.
- `homing_center` −41,31 a −42,19° (dispersión 0,9°) — el cero tampoco.
- `v_bus` 14,968–14,992 V, `safety_action` = 0, `i_ma` en reposo sin tendencia.

Lo que cambió es **dónde va la energía**: el brazo sigue llegando a 112–135° (el tope), pero
el péndulo ya no sube — `ceiling_hits` cae de 23–38 a 0–6 con el mismo techo `ec`. El bombeo
está metiendo energía en el brazo en vez de en el péndulo, y cada vez peor.

Es [P12](../../docs/REGISTRO_PROBLEMAS.md#p12) («depende del estado»: con banco fresco no es
defecto; tras corridas, sí) reproducido dentro de una sola sesión, y con
[P24](../../docs/REGISTRO_PROBLEMAS.md#p24) como candidato de fondo. **Causa no identificada
en esta campaña.**

### El reposo no lo recupera

Seis minutos sin energizar el motor, y después la misma línea base: **0/3 otra vez**
(α máx 175,3 / 133,4 / 167,0; `ceil` 0/0/23; θ máx 122–135). El reposo corto **no**
restituye el comportamiento, lo que argumenta en contra de una causa térmica en esa escala
de tiempo y a favor de algo persistente dentro de la sesión.

### Intento de aislar el pivote, y por qué no concluye

Se repitió la medición de caída libre al final de la sesión para comparar la disipación del
pivote contra la de las 13:1x. El decremento de amplitud por medio ciclo —que para fricción
de Coulomb es constante y proporcional al par seco— dio:

| tanda | segmentos | decremento mediano | dispersión |
|---|---|---|---|
| temprano 13:1x | 10 | 36,7° | 4,7 – 131,8 |
| tarde 13:4x | 6 | 10,4° | 0,0 – 63,5 |

**Esta comparación no vale y no se usa.** Las sueltas tempranas se hicieron desde amplitudes
mucho más altas (hasta 170°, con el péndulo pasando por arriba y girando) y las tardías
desde 88–135°: los decrementos se midieron sobre movimientos distintos. La dispersión
enorme del grupo temprano es justamente esa contaminación. Para que sirviera habría que
soltar desde la **misma** amplitud antes y después — es el experimento que falta.

> **Por lo tanto:** los 0/3 de `ec=0,64` y de `cg=1` **no son atribuibles a esos
> parámetros**. Son indistinguibles de la deriva. Las dos pruebas hay que repetirlas con
> línea base intercalada —una base cada dos tandas, no una por sesión— o con el banco
> descansado. Lo que sigue se lee con esa advertencia puesta.

## Resultado 3 — `ke`: lo que se puede y no se puede decir

| `ke` | traspaso | E/E\* | `ceiling_hits` | θ máx | muestras >95° |
|---|---|---|---|---|---|
| adaptativo (0,75) | **8 = energy** | 0,984 | 38 | 134,65° | 286 |
| 0,40 | 0 — no hubo | — | 31 | 103,27° | 67 |
| 0,90 | 0 — no hubo | — | 23 | 104,94° | 91 |
| 0,65 | tanda abortada: homing falló (rango 257,5°) | | | | |

Con `n = 1` por valor esto **no** establece un óptimo, y con la deriva del Resultado 2
encima **tampoco establece que `ke` no importe**: las tandas de 0,40 y 0,90 se corrieron
después de la única que traspasó, y una línea base de esos mismos minutos habría hecho
falta para separar las dos cosas. No la hay.

Lo único defendible de esta tabla: en las tres tandas el intento terminó con `fail=3`
(el brazo llegó al tope), no por falta ni por exceso de bombeo.

## Resultado 4 — el péndulo NO tiene frecuencia natural medible hoy

12 sueltas con el brazo retenido (`m2 s=0`, que aísla el pivote de la reacción del brazo),
primer medio ciclo de cada una, con corrección no lineal por integral elíptica:

```
n = 9 sueltas utilizables
mediana f_0 = 1,438 Hz
media       = 1,522 Hz     sd = 0,565 Hz     min 0,638   max 2,537
```

**Una desviación del 37 % sobre la media no es imprecisión: es la respuesta.** Un péndulo
con `f_n` bien definida no produce estimaciones entre 0,64 y 2,54 Hz. El pivote está en el
estado de [P24](../../docs/REGISTRO_PROBLEMAS.md#p24) —fricción seca dominante— y la
oscilación muere antes de establecer un período:

| t [s] | amplitud | período |
|---|---|---|
| 0,06 | 47,6° | 0,697 s |
| 0,40 | 20,0° | 0,784 s |
| 0,80 | **5,8°** | 1,088 s |

De 47,6° a 5,8° en **0,8 s, menos de dos ciclos**, y el período **crece** al bajar la
amplitud. Un péndulo lineal hace exactamente lo contrario. Es la firma de fricción de
Coulomb: la adherencia retiene el péndulo cerca del punto de retorno y estira el medio
período medido. Por eso los medios ciclos tardíos sesgan `f_n` hacia abajo y sólo sirve el
primero de cada suelta.

Lo que sí se puede afirmar: **todas las mediciones de amplitud moderada o alta caen entre
1,15 y 1,60 Hz**, y la frecuencia del bombeo en modo 5 —donde el péndulo no se detiene y
hay muchos ciclos— da **1,64–1,99 Hz** (mediana ≈ 1,7 Hz por valor de `ke`). Ninguna se
acerca a los 2,283 Hz que el firmware supone.

## Resultado 5 — la consecuencia: `E/E*` está mal escalada, y se puede acotar

Las constantes del firmware:

```
PEND_MASS   = 0,025 kg     ← marcada «SIN identificar»
PEND_LENGTH = 0,065 m      ← marcada «SIN identificar»
PEND_INERTIA= 7,75e−5 kg·m²← «de wn medido»
```

En `E/E* = ω²/(4·ω_n²) + (1 − cos α)/2` **la masa y el largo se cancelan**: sólo entra
`ω_n² = mgl/I`. Eso es una buena noticia — de las tres constantes en duda por
[P5](../../docs/REGISTRO_PROBLEMAS.md#p5), sólo importa su combinación.

```
ω_n² implícita en el firmware = 1,594e−2 / 7,75e−5 = 205,7  →  f_n = 2,283 Hz
```

Contra los 1,70 Hz de referencia, el firmware sobrestima `ω_n²` en **1,80×**, así que
**subpondera el término cinético por ese mismo factor**. Recalculado sobre las trazas
reales de esta sesión (p95 durante el bombeo, enmascarando los recortes de vuelta entera):

| traza | E/E\* firmware | si f_n = 1,70 | si f_n = 1,44 |
|---|---|---|---|
| base (ke adapt.) | 1,08 | **1,34** | 1,59 |
| ke = 0,40 | 0,99 | **1,38** | 1,76 |
| ke = 0,90 | 1,00 | 1,00 | 1,24 |

El firmware corta el bombeo creyendo estar en ~1,0–1,08 de la energía necesaria (techo
`ec` = 1,15) cuando la energía real ya es hasta **1,38× la que hace falta para llegar a la
vertical**. Sobra energía, el péndulo pasa por arriba y gira — y eso es lo que muestran las
trazas: 1–2 recortes de vuelta entera por corrida, y `ceiling_hits` de 23 a 38.

**Esto no está verificado como causa**, sólo cuantificado como consecuencia aritmética de
una `ω_n` que las mediciones de hoy no respaldan. El experimento que lo cerraría es fijar
`ec` compensado por 1,80 (≈ 0,64) y ver si desaparecen las vueltas.

## Resultado 6 — el enlace se degrada por CARGA, no por tiempo

RTT de `/rl_state` (el endpoint barato: 0,00 overruns por petición, contra 0,97 de
`/state`):

| `ke` | antes | durante | después | factor |
|---|---|---|---|---|
| adaptativo | 44,8 ms | **105,6** | 45,5 | 2,36× |
| 0,40 | 70,7 ms | **156,2** | 50,9 | 2,21× |
| 0,90 | 58,5 ms | **87,0** | 49,6 | 1,49× |

**El RTT se duplica durante la adquisición y se recupera entero al terminar.** No hay
degradación acumulativa a lo largo de la sesión: es carga instantánea del stack AsyncTCP
compitiendo con el streaming del DAQ y el sondeo de `/state`.

Del lado del lazo, con 0 muestras perdidas en todas las tandas:

| tanda | tasa DAQ efectiva | huecos >3 ms | dt máx | `loop_overruns` |
|---|---|---|---|---|
| base | 476,6 Hz (−4,7 %) | 131 | 18,4 ms | 27 |
| ke 0,40 | 482,7 Hz (−3,5 %) | 122 | 18,2 ms | 26 |
| ke 0,90 | 477,5 Hz (−4,5 %) | 110 | 18,9 ms | 25 |

Los overruns (25–27) contra las peticiones a `/state` de cada tanda (≈22–30 a 4 Hz) dan
**≈0,9 overruns por petición: P28 reproducido en esta sesión**, con el número que la ficha
declara. La tasa efectiva del DAQ queda 3,5–4,7 % por debajo de los 500 Hz nominales por la
misma causa.

`v_bus` se mantuvo en 14,98–14,99 V en todas las tandas y `safety_action` en 0: ni corte ni
derate. La alimentación no participa de nada de lo anterior.

## Defectos corregidos durante la campaña

Tres, y los tres eran del instrumental, no del banco:

1. **Contadores monotónicos leídos sólo al final.** `pend_wraps` sólo se reinicia al
   arrancar la placa; leerlo al final mide la sesión, no la tanda, y las tandas tardías
   parecerían peores por ser tardías. Ahora se lee antes y se resta.
2. **`lqr_alive_ms` rancio.** No se limpia entre intentos —sobrevive a la caída a
   propósito— así que las tres primeras tandas reportaron el mismo «576 ms», que era el
   latch de la primera. Ahora se anula si no hubo traspaso en ese intento.
3. **Sueltas con el péndulo aún en movimiento.** Esperar 0,8 s entre sueltas dejaba que el
   re-cero de P22 corriera contra un péndulo oscilando: las sueltas se asentaron en +158°,
   −310°, +29° y −49°, que es la deriva del cero, no el péndulo. Ahora se espera quietud
   real (±0,6° durante 1,5 s) y se verifica `swing_zero_ok`.

Y uno de documentación: `docs/http_api.md` decía que el homing acepta un recorrido de
**250–290°**; el firmware exige **262–278** (`HOMING_RANGE_MIN/MAX_DEG`). La tanda de
`ke=0,65` abortó con 257,5° — dentro de lo documentado, fuera de lo real. Corregido.

## Lo que NO se verificó

- **Ningún efecto de parámetro quedó establecido.** Ni `ke`, ni `ec`, ni `cg`. La deriva
  del Resultado 2 los confunde a todos, y la campaña no tuvo líneas base intercaladas —
  ese es el defecto de diseño de esta sesión, y es el que hay que corregir primero en la
  próxima: una base cada dos tandas.
- **La causa de la deriva no se identificó.** El reposo corto no la revierte; la
  calibración del brazo y la alimentación quedaron descartadas con medición; el intento de
  aislar el pivote no fue comparable. Queda abierto.
- **`ec = 0,64` sí produjo un hallazgo estructural**, y ése no depende de la deriva: con el
  techo por debajo de 1,0 el criterio de traspaso `energy` es **inalcanzable por
  construcción**, porque `energyReady` exige que la E computada esté cerca de E\*. `ec` y el
  criterio de traspaso están acoplados por la misma E mal escalada, así que compensar uno
  rompe el otro. La corrección tendría que ir en `PEND_INERTIA`, que reescala ambos.
- **P26 no se corrigió ni se probó corregido.** El Resultado 1 es consistente con él y con
  `homing_pwm_sign = −1`, pero eso no es una prueba causal.
- **El escalado de `ec` no se probó.** El Resultado 4 es aritmética sobre trazas, no un
  experimento.
- **`f_n` no quedó determinada.** Se acotó a 1,15–1,60 Hz por caída libre y ≈1,7 Hz por
  bombeo, con la dispersión que se declara arriba. Mientras el pivote esté como está
  (P24), no hay un número que defender.
