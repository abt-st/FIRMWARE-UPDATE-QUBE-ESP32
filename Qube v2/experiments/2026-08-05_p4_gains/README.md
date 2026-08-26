# P4 — el LQR pierde el péndulo en menos de 90 ms

**Criterio escrito ANTES de medir.** Firmware v1.58.8. Etapa 5 de `PLAN_MODOS_FUNCIONALES.md`.

## Lo que ya está medido, sin banco

Las 10 trazas del m5 de `2026-08-04_m5_swingup/` **contienen el modo 4 completo a 500 Hz**:
el DAQ siguió grabando después del traspaso. Es mejor dato que todas las campañas de m4
anteriores, que muestrearon por HTTP a ~14 Hz (5 a 20 muestras por intento).

### H3 — CONFIRMADA

Saturación de la salida en modo 4, contra el techo efectivo por muestra
`int(LQR_PWM_MAX / (1 + (|θ|/200)²))` y descartando los 400 ms del catch:

| | mín | mediana | máx |
|---|---|---|---|
| fracción del modo 4 con la salida en su techo | 43,6% | **70,4%** | 100% |

n = 8. Coincide con el 68,8% que daban las trazas de 14 Hz. **Con la salida clavada, las
cuatro ganancias no pueden influir: lo que corre es un relé.** La prueba ingenua contra
`LQR_PWM_MAX` da 0,0% en las ocho, por la atenuación por posición de `setMotor` — el mismo
error que hizo falta corregir en el bombeo.

### El orden de los sucesos

Desde la entrada al modo 4 (t=0 en el traspaso):

| | |
|---|---|
| el péndulo sale de ±20° de la vertical | **0 – 86 ms** (10/10) |
| el brazo llega a 60° | 0 – 1272 ms (mediana ~600) |
| quién se va primero | **el péndulo, en 9 de 10** |
| θ final | ±94,0 – ±94,8 en 8/8, tope 95 |

**El péndulo se pierde en menos de 90 ms.** El brazo topando es la consecuencia. Y esos
90 ms caen **dentro de la ventana del catch** (`LQR_CATCH_MS` = 400), donde el LQR no
ejecuta ni un tick y el motor recibe lo que decide la rama del catch.

> **Corrección de una lectura anterior del mismo día.** Se había escrito lo contrario ("el
> péndulo no se cae, el brazo se va"), desde las 15 corridas de `2026-08-04_p4_catch/`. Ese
> análisis miró el **estado en la última muestra** en vez de la secuencia, sobre trazas de
> 14 Hz: no distingue "el péndulo aguanta" de "ya se cayó y la última muestra cayó antes".
> A 500 Hz el orden es el inverso.

### El criterio 1 del m5 predice exactamente si el LQR arranca con algo utilizable

En **5 de 10** corridas `t_loss = 0`: el péndulo ya estaba **fuera** de ±20° en el instante
del traspaso. Y cuáles son esas cinco no es casualidad:

| rep | \|α\| en la entrega | crit. 1 del m5 (≥165°) | `t_loss` |
|---|---|---|---|
| 4 | 178,9° | PASS | 74 ms |
| 5 | 173,5° | PASS | 86 ms |
| 1 | 173,3° | PASS | 72 ms |
| 6 | 169,6° | PASS | 38 ms |
| 3 | 165,6° | PASS | 36 ms |
| 10 | 158,2° | FAIL | **0** |
| 2 | 158,4° | FAIL | **0** |
| 7 | 158,4° | FAIL | **0** |
| 8 | 155,9° | FAIL | **0** |
| 9 | 155,4° | FAIL | **0** |

**Concordancia 10/10.** El umbral de 165° que se había fijado *antes* de medir —y que se
venía describiendo como "más estricto que el del propio firmware"— resulta ser **exactamente
la frontera en la que el LQR recibe un péndulo dentro de la banda**. No era arbitrario.

Consecuencias:

- **`SWINGUP_TRANS_NEAR = 155` es demasiado permisivo**: entrega en un estado que el LQR no
  puede usar. Subir `?tn=` es candidato barato y configurable por HTTP. Con el aviso de que
  el 2026-07-31 `tn=165/170/175` **no disparaban nunca** — pero eso fue **antes de P22**, y
  hoy 5 de 10 entregas ya superan 165 solas.
- **El r ≈ −0,09 entre calidad de entrega y supervivencia queda bajo sospecha.** Se calculó
  contra la supervivencia *total*, que mezcla intentos que murieron por causas distintas.
  Contra el arranque del LQR la relación no es débil: es perfecta en n=10.

## Por qué esta campaña mide el catch y no las ganancias

Con H3 confirmada, tocar ganancias es tocar un relé: no puede decir nada. Y el péndulo se
pierde **dentro** de la ventana del catch, que es territorio de H1 y H2.

**H2 figura como refutada** —acortar el catch empeoró: 0,567 → 0,461 → 0,406 s— pero esa
refutación se apoya en `lqr_alive_ms` con n=4 por condición y una dispersión intra-condición
de factor 33. Con una métrica así, un efecto real de 90 ms es invisible. **A 500 Hz hay una
métrica mucho más sensible: el tiempo desde el traspaso hasta perder el péndulo**, que se
mide con 45 muestras en vez de con una latch de milisegundos al final.

**H1 nunca se midió.** La rama del catch (`:2944-2955`) retorna antes de actualizar
`lqr_prevAlpha`, así que durante los 400 ms la referencia queda congelada y
`-(pendPosRaw - lqr_prevAlpha)/dt` divide por un solo tick todo el recorrido desde el
traspaso: 30° acumulados dan 15.000 °/s y `brake_pwm` satura contra `LQR_CATCH_PWM` = 25
casi de inmediato. Peor, la dirección se fija en los primeros 10 ms desde esa misma lectura,
que con una entrega buena (α̇ ≈ 0) es **ruido de un conteo de encoder**. Neto: 400 ms de
±25 PWM en un sentido esencialmente aleatorio, aplicados justo cuando hay que atrapar.

Eso es exactamente lo que predice "el péndulo se va en menos de 90 ms".

### H7 se mide de paso, y es la de menor prioridad

La ley (`:3592`) es `u = -(K1·θ + K2·α + K3·velTheta + K4·velAlpha)`, la forma `u = −K·x`.
Las dos velocidades se calculan negadas (`:3553-3554`). Para α se cancela —`alpha` ya viene
invertida en `:3546`, así que `−α̇_raw = +α̇`— pero para θ no: con `K3 = +1,5` el firmware
estaría **anti-amortiguando el brazo**. Las ganancias del CARE piden K1 y K3 negativas, o
sea lo mismo por otro camino (ver H5 en el registro).

Pero el brazo no es lo que mata la corrida, así que H7 baja de prioridad. Se incluye porque
cuesta una condición y `lqr3` es configurable por HTTP.

---

## Diseño

Tres condiciones, `n = 5`, **intercaladas** (rep externo, condición interno): el banco deriva
dentro de una sesión —quedó documentado en la Etapa 1 con las dos curvas de `kd` moviéndose
enteras en un día— y medir en bloques confunde deriva con efecto.

| condición | `lc` | `lqr3` | qué aísla |
|---|---|---|---|
| **control** | 400 | +1,5 | el comportamiento de hoy |
| **nocatch** | **0** | +1,5 | H1 + H2: quitar la ventana del catch entera |
| **h7** | 400 | **−1,5** | sólo el signo del amortiguamiento del brazo |

`cg=1` fijo en las tres: H6 se sostuvo y no conviene volver a medir con el defecto puesto.

`nocatch` no separa H1 de H2 —las dos viven en la misma ventana— y no pretende hacerlo. La
pregunta de esta tanda es si la ventana del catch es lo que pierde el péndulo, no cuál de
los dos defectos de adentro pesa más.

## Métrica primaria

**`t_loss`: milisegundos desde la entrada al modo 4 hasta que |180 − α| supera 20°**, medido
a 500 Hz. Reemplaza a `lqr_alive_ms` como métrica de decisión, por tres razones:

1. Resuelve 2 ms, no la latencia de un HTTP.
2. Mide lo que falla (perder el péndulo), no lo que pasa después.
3. `lqr_alive_ms` cuenta desde el **fin** del catch, así que con `lc=0` y con `lc=400` no
   mide la misma cosa. `t_loss` cuenta siempre desde el traspaso.

`lqr_alive_ms` se registra igual, para poder comparar con las campañas viejas.

## Criterios, fijados de antemano

1. **El control tiene que reproducir lo conocido.** Referencia (m5 a 500 Hz, n=10):
   `t_loss` entre 0 y 86 ms, saturación 43,6–100%, θ final ±94. Si el control cae fuera, el
   banco cambió y hay que rehacer la línea base antes de leer nada más.

2. **H3 (re-verificación).** Saturación del control **> 50%** del tiempo en modo 4. Ya está
   confirmada a 500 Hz; acá sólo se comprueba que la sesión reproduce.

3. **La ventana del catch se confirma como culpable** si en `nocatch` la mediana de `t_loss`
   **crece por un factor ≥ 3** respecto del control (de ~50 ms a ≥ 150 ms). El factor 3 sale
   de la dispersión conocida, que es de casi un factor 2 dentro de una condición.

   **Se evalúa sólo sobre los intentos con entrega buena** (`|α| ≥ 165°`, o sea error ≤ 15°).
   La razón está medida arriba: en las entregas malas el péndulo ya está fuera de la banda
   en el instante del traspaso, `t_loss = 0` y **no hay nada que el catch pueda haber
   arruinado**. Incluirlas diluiría el efecto con corridas que no pueden mejorar, y con la
   mitad de la muestra en cero la mediana no significaría nada. Esto se decide **antes** de
   ver los datos de la campaña; el conteo de entregas buenas por condición se reporta junto
   al veredicto para que se vea sobre cuántas se está comparando.

   - Si `t_loss` crece **y** la supervivencia total no mejora, el resultado igual vale: dice
     que el catch pierde el péndulo y que hay un segundo problema después.
   - Si `t_loss` **no** cambia, la ventana del catch queda descartada y la sospecha pasa
     entera a la saturación (H3) y a las ganancias.
   - **Si quedan menos de 3 entregas buenas por condición, el criterio no se evalúa** y hay
     que repetir con más reps. Un veredicto sobre n=2 no es un veredicto.

4. **H7 se confirma** si con `lqr3 = −1,5` la excursión máxima del brazo **baja** y `t_loss`
   no empeora. No se le pide mejorar la supervivencia: el brazo no es lo que mata la corrida.

5. **Sólo cuentan los intentos que traspasan.** Se reportan aparte y no se promedian.

6. **La calidad de la entrega es covariable, no ruido.** Cada intento registra
   `swing_trans_*`. Importa más que antes: el error de entrega medido va de 1,1° a 25,0° y
   determina si el péndulo cae en t=0 o a los 86 ms.

## Cómo correrlo

Con el PC asociado al SoftAP `QUBE-ESP32`, el paro de emergencia
(`Invoke-RestMethod "http://192.168.4.1/cmd?x=1"`) a mano en otra consola, y la GUI
**cerrada** (un solo consumidor de `/daq/read`):

```powershell
uv run python experiments/2026-08-05_p4_gains/scripts/m4_daq.py --reps 5
```

Antes, sin banco y sin motor, `selftest.py`: corre la métrica sobre las trazas del m5 y
verifica que reproduce el 70,4% y los ≤86 ms. Un error de métrica descubierto con el motor
girando cuesta la sesión.

El script aborta solo, **antes de tocar el motor**, en tres casos:

- `ina_ok` falso — sin INA219 no hay corte por calado.
- `v_bus < 12,5 V` — el firmware anularía todo comando de motor (ver abajo).
- `v_bus < 13,5 V` — el firmware escalaría el PWM por tensión y la saturación medida no
  sería atribuible.

## Resultados (2026-08-05, n=15, 15/15 traspasaron)

`v_bus` = 15,02 V, `selftest.py` en verde antes de energizar.

### El resultado de la tanda: nada de lo que se probó importa; la entrega lo explica todo

| | |
|---|---|
| `corr(error de entrega, t_loss)` | **−0,956** |
| R² | **0,914** |
| ajuste | `t_loss = −3,52·err + 76,8` ms |
| cruza cero en | err = 21,8° → **α = 158,2°** |

Los 15 intentos, ordenados por error de entrega, con la condición al lado:

```
err  3.5 -> t_loss 56    control      err 14.8 -> 32    h7
err  8.3 -> t_loss 42    nocatch      err 14.9 -> 28    h7
err 11.4 -> t_loss 42    control      err 17.2 -> 14    control
err 13.7 -> t_loss 32    nocatch      err 19.5 ->  4    control
err 13.7 -> t_loss 40    h7           err 20.2 ->  0    h7
err 14.1 -> t_loss 28    nocatch      err 20.7 ->  0    nocatch
err 14.4 -> t_loss 28    h7           err 21.1 ->  0    nocatch
                                      err 21.8 ->  0    control
```

Las etiquetas de condición están repartidas sin patrón. **Cuánto aguanta el péndulo lo
decide la entrega, y prácticamente nada más.**

### Criterio por criterio

| criterio | resultado |
|---|---|
| 1. el control reproduce (t_loss 0–86 ms) | `t_loss` mediana **14 ms** — OK |
| 2. H3, saturación del control > 50% | **93,3%** (rango 88,5–97,3) — reproduce, y por encima del 70,4% de las trazas del m5 |
| 3. ventana del catch, ≥3 entregas buenas por condición | **NO SE EVALÚA**: control 2/5, nocatch 3/5 |
| 4. H7 sobre el residuo | **NO CONFIRMADA** |
| 6. covariable | r = −0,956; hay que leer todo sobre el residuo |

**Residuos de `t_loss` tras descontar la entrega** (dispersión intra-condición ±11,4 ms):

| condición | residuo mediano |
|---|---|
| control | −2,3 ms |
| nocatch | −2,6 ms |
| h7 | +3,6 ms |

- **La ventana del catch no hace nada detectable.** Quitar los 400 ms enteros mueve el
  residuo de −2,3 a −2,6 ms. El criterio 3 no se evalúa formalmente por falta de entregas
  buenas, pero el residuo cubre las 15 corridas y no muestra efecto. Eso **re-refuta H2 con
  una métrica mucho mejor** que la de `lqr_alive_ms`, y de paso deja a **H1 sin margen**: su
  mecanismo entero vive en esa ventana.
- **H7 no se sostiene.** +3,6 ms de residuo contra una dispersión de ±11,4 con n=5. Las θ
  máximas (94,7 vs 94,3) están las dos contra el tope de 95: esa comparación no podía
  discriminar nada y fue un mal criterio de mi parte.

### El veredicto que el script dio mal, otra vez

La corrida imprimió `4. H7 ... CONFIRMADA`. **Es falso.** El criterio 4 comparaba medianas
crudas de `t_loss` y de θ máx, sin descontar la entrega — justo lo que el criterio 6, escrito
en este mismo documento antes de medir, dice que hay que hacer. A `h7` le tocaron 4/5
entregas buenas contra 2/5 del control, así que se veía mejor sin haber probado nada.

Corregido: el criterio 4 ahora se evalúa sobre el residuo, y el bloque de covariable se
imprime **antes** que las comparaciones entre condiciones. Es la segunda vez en dos días que
el criterio estaba bien escrito y mal implementado — la primera fue el `c1 >= 4` del m5.

### Corrección de la concordancia 10/10

Ayer, sobre las 10 trazas del m5, la concordancia entre "|α| ≥ 165" y "t_loss > 0" fue
perfecta, y de ahí salió que 165° era **la frontera** en que el LQR recibe algo utilizable.
Con estos 15 puntos se ve que **la relación es continua, no un escalón**: `t_loss` baja
3,5 ms por grado de error y llega a cero recién en err ≈ 21,8° (α ≈ 158°). Un intento con
err = 17,2° todavía dio `t_loss` = 14 ms.

Aquella concordancia perfecta era un artefacto de la muestra: las 10 entregas del m5 estaban
**partidas en dos grupos** (155–158 y 165–179) sin nada en el medio, y una rampa muestreada
sólo en sus extremos parece un escalón. Hoy las entregas cubren 3,5–21,8° de corrido.

Lo que sí se sostiene, y es lo importante: **la calidad de la entrega es la variable
dominante del modo 4**, y `SWINGUP_TRANS_NEAR = 155` entrega justo donde `t_loss` ya vale
cero.

### Qué queda descartado y qué sigue

Descartados con esta tanda: la ventana del catch (H1 y H2 juntas), el signo de K3 (H7). Y
H3 queda re-confirmada con más fuerza (86–98% en las tres condiciones).

Lo que sigue, en orden:

1. **Subir el umbral de traspaso** (`?tn=`). Es el mando que actúa sobre la única variable
   que resultó importar, y es HTTP. El riesgo conocido es que deje de disparar: el
   2026-07-31, `tn` de 165/170/175 no disparaba nunca — pero eso fue antes de P22.
2. **La saturación (H3).** `LQR_PWM_MAX = 70` sobre un `PWM_MAX` de 200: el LQR corre con el
   35% de la autoridad disponible y está contra el tope el 93% del tiempo. Es `const int`,
   así que exige reflashear.
3. Recién después, las ganancias (H5). Mientras la salida esté saturada, cambiarlas no puede
   medirse.

---

## Barrido del umbral de traspaso `?tn=` (2026-08-05, n=20)

El seguimiento directo del resultado anterior: si la entrega es lo único que importa, `tn`
es el mando que la gobierna. Criterio y techo esperado escritos antes de medir, en el
encabezado de `scripts/tn_sweep.py`.

**Métrica primaria: `t_loss` efectivo por intento**, contando los intentos sin traspaso
como 0. Un nivel que dispara 1 de 5 con una entrega perfecta no sirve, y promediar sólo los
traspasos lo premiaría.

| `tn` | traspasa | err de entrega | `t_loss` efectivo | mediana | bombeo |
|---|---|---|---|---|---|
| 155 (default) | **5/5** | 19,7 · 20,9 · 20,9 · 22,9 · 23,2 | 0 · 0 · 0 · 0 · 2 | **0 ms** | 6,3 s |
| **162** | **5/5** | 11,1 · 13,0 · 17,4 · 17,8 · 17,9 | 12 · 12 · 14 · 40 · 44 | **14 ms** | 6,4 s |
| 168 | 2/5 | 6,7 · 11,2 | 0 · 0 · 0 · 56 · 112 | 0 ms | 7,4 s |
| 175 | 2/5 | 0,9 · 4,7 | 0 · 0 · 0 · 58 · 96 | 0 ms | 9,5 s |

**`tn = 162` es el único nivel que mejora de forma fiable**: mantiene 5/5 traspasos y sube
la mediana del `t_loss` efectivo de 0 a 14 ms. Los niveles altos entregan mejor cuando
disparan (err de 0,9° a 11,2°, con los dos mejores resultados del día: 112 y 96 ms) pero
sólo disparan 2 de 5, y el bombeo se alarga hasta una mediana de 9,5 s con el brazo rozando
el tope (θ máx 94,5–94,9 en los intentos que no traspasan).

> El script imprime "x14.00" como factor de mejora. Es un artefacto del guardián
> `max(base, 1.0)` que evita dividir por cero — la mediana del control es 0. La lectura
> correcta es **0 → 14 ms**, no "catorce veces mejor".

### `tn = 155` es peor de lo que se creía

Las cinco entregas del control cayeron en **19,7–23,2° de error**, o sea del lado malo del
cruce por cero. El default traspasa siempre y siempre entrega algo que el LQR no puede usar:
4 de 5 con `t_loss` exactamente 0.

### El ajuste con los 29 traspasos de las dos campañas

Rango de entrega de 0,9° a 23,2°, mucho más ancho que el de la primera campaña:

| | n=15 (primera) | **n=29 (las dos)** |
|---|---|---|
| ajuste | `−3,52·err + 76,8` | **`−4,17·err + 90,2`** |
| r | −0,956 | **−0,865** |
| R² | 0,914 | **0,749** |
| cruza cero | err 21,8° (α 158,2°) | **err 21,6° (α 158,4°)** |

El cruce por cero es **notablemente estable** (158,2 vs 158,4) y es el número accionable:
por debajo de α ≈ 158 el traspaso no sirve para nada. El R² baja de 0,91 a 0,75 al ampliar
el rango — el 0,91 estaba inflado por una muestra estrecha, y 0,75 es la cifra honesta.

**El techo pre-registrado se superó.** Se había anunciado ~77 ms con entrega perfecta; el
ajuste con el rango completo da **90 ms** y hubo intentos de 112 y 96. La extrapolación
lineal fuera del rango medido subestimaba. Queda anotado: el pronóstico falló por unos
15 ms, en la dirección buena.

### Lo que esto NO resuelve

**Con la entrega casi perfecta el péndulo se pierde igual en ~90 ms.** El mejor intento de
todo el día, sobre 35 corridas, fue 112 ms. Subir `tn` mueve el modo 4 de "catastrófico" a
"catastrófico": es una mejora real y reproducible, pero el LQR sigue sin sostener nada.

La entrega explica el 75% de la varianza; el 25% restante y —sobre todo— la **ordenada de
90 ms** son del controlador. Con la salida saturada el 93% del tiempo (H3), el candidato que
queda es `LQR_PWM_MAX = 70` sobre un `PWM_MAX` de 200: el LQR corre con el 35% de la
autoridad disponible. Es `const int` y exige reflashear.

### Recomendación

Cambiar el default de `swingupCatchDeg` de 155 a **162**. Está medido con n=5 en una sola
sesión, así que conviene confirmarlo en otra antes de darlo por cerrado — pero el control
del mismo día es inequívoco y el cambio no tiene contraindicación: mismo número de
traspasos, mismo tiempo de bombeo, entregas mejores.

---

## Barrido del techo de PWM del LQR `?lpm=` (2026-08-05, n=20)

Último candidato de P4: `LQR_PWM_MAX = 70` sobre un `PWM_MAX` de 200 — el modo 4 corriendo
con el 35% de la autoridad disponible y saturado el 93% del tiempo. **¿Causa o síntoma?**

`tn = 162` fijo en los cuatro niveles (no es una condición: es el mejor punto de entrega
medido, y con el default 155 la mitad de los intentos entrega con `t_loss = 0` y no
discrimina nada). Niveles 70 (control) · 100 · 130 · 150, n=5 intercalados.

### Antes: el firmware tenía un segundo limitador con el 70 hardcodeado

`LQR_PWM_MAX` **no era el límite operativo.** El bloque de límites de servo del modo 4
(`:3647-3695`) re-acotaba la salida a un **70 literal en las cinco ramas**, sin mirar la
constante. Los dos valores coincidían, así que nunca se notó — pero subir `LQR_PWM_MAX` no
habría tenido ningún efecto, y el barrido habría dado "no hay efecto" por una razón falsa.

Tercer mando del proyecto con esta forma, después de `bt` y de `?ke=` ([P23](../../docs/REGISTRO_PROBLEMAS.md#p23)).

Corregido en v1.58.9: `lqrPwmMax` configurable por `?lpm=` (rango 20–150), **default 70 =
comportamiento histórico**, todo el bloque de límites expresado contra él, y el valor
vigente publicado en `/state` como `lqr_pwm_max`. Mismo patrón que `lc`/`cg`: el flasheo por
sí solo no cambia nada. Verificado en la placa tras el OTA.

### Resultado

| `lpm` | traspasa | `t_loss` mediano | saturación | θ máx | err de entrega |
|---|---|---|---|---|---|
| 70 | 4/5 | 64 ms | 97,4% | 94,3 | 3,6 |
| 100 | 4/5 | 40 ms | 98,0% | 94,8 | 8,0 |
| 130 | 3/5 | 40 ms | 98,1% | 94,9 | 11,6 |
| 150 | 5/5 | 60 ms | 98,6% | 94,5 | 8,6 |

Residuo de `t_loss` tras descontar el error de entrega (n=16 traspasos, ajuste
`−3,26·err + 86,2`):

| `lpm` | residuo mediano | n |
|---|---|---|
| 70 | −8,3 ms | 4 |
| 100 | −6,5 ms | 4 |
| 130 | +0,7 ms | 3 |
| 150 | −1,1 ms | 5 |

**H3 no es causal.** Con más del doble de autoridad (70 → 150) el residuo se mueve 9 ms
contra una dispersión intra-nivel de 13 a 68 ms. No hay efecto.

**Y la saturación no baja: sube.** 97,4 → 98,0 → 98,1 → **98,6%**. A cualquier techo probado
el lazo está pegado contra él el 98% del tiempo. Es coherente con las ganancias: `K2 = 22`
satura con 3,2° de error a techo 70 y con 6,8° a techo 150, así que el LQR **sigue siendo un
relé a cualquier autoridad** — sólo que uno más fuerte. Nunca se alcanzó el régimen lineal.

Seguridad: 0 intentos con brownout, `v_bus` en 15,0 en los veinte, θ máx 94,3–94,9 igual que
en todas las campañas. `lpm=150` no resultó violento.

### ⚠ El criterio 1 FALLÓ: esta tanda no es comparable con la anterior

El control (`lpm=70`, `tn=162`) dio **64 ms** de mediana, contra los 14 ms que el mismo
`tn=162` había dado una hora antes. Fuera del rango pre-registrado.

La causa se ve en las entregas:

| | err de entrega, mediana |
|---|---|
| `tn=162`, tanda anterior | **17,4°** |
| `lpm=70`, esta tanda (mismo `tn`) | **3,6°** |

**El swing-up entrega mucho mejor ahora que hace una hora**, con el mismo umbral. Es
deriva del banco, del mismo tipo que documentó la Etapa 1 con las dos curvas de `kd`
moviéndose enteras en un día — y llevamos 55 corridas encima. El modo 5 no se tocó en el
flasheo.

**Consecuencia:** las comparaciones **entre** sesiones de hoy no valen. La comparación
**dentro** de esta tanda sí, porque los cuatro niveles se midieron intercalados en la misma
sesión, y es sobre ella que se apoya el "H3 no es causal".

También hay que releer con esto el resultado de `tn`: la recomendación `155 → 162` se midió
en una sesión donde las entregas eran peores. Sigue en pie que 162 fue mejor que 155 **en su
propia tanda intercalada**, pero el número absoluto (0 → 14 ms) no es el de hoy.

### El segundo veredicto mal implementado de la tanda

El script imprimió `2. la saturacion baja al subir el techo: ... SI` sobre una serie que
**sube** (97 → 99%). La comprobación estaba escrita `sats[i] >= sats[i+1] - 0.05`, que
tolera un aumento de hasta 5 puntos. Corregido a una comparación punta a punta con caída
real. **Tercer criterio bien escrito y mal implementado en dos días**, después del
`c1 >= 4` del m5 y del criterio 4 de la campaña de la mañana. El patrón es claro y conviene
nombrarlo: el criterio se redacta en prosa, se traduce a una comparación, y la traducción no
se revisa contra un caso que deba fallar.

### Dónde queda P4

Descartadas hoy, todas con medición: **H1**, **H2**, **H7**, y ahora **H3 como causa** (sigue
siendo un hecho — la salida está saturada el 98% del tiempo — pero no es lo que impide
sostener).

Queda **H5, las ganancias**, y el barrido de hoy le agrega un argumento: si a techo 150 el
lazo sigue pegado el 98% del tiempo, el problema no es cuánta autoridad hay sino que las
ganancias piden saturación ante cualquier error realista. El diseño del CARE (`lqr.py`,
convertido: K1 −3,49 · K2 148,7 · K3 −4,07 · K4 12,2 contra los 2,0 · 22 · 1,5 · 9 que
corren) es otra escala entera, no un ajuste.

**Próximo paso:** cargar las ganancias diseñadas por HTTP (`lqr1..lqr4` son todas
configurables) y medir contra el mismo criterio. Y rehacer la línea base al empezar, porque
hoy quedó demostrado que las entregas se mueven dentro del día.

---

## Barrido de K2 — ABORTADO en la rep 1 (2026-08-05)

Diseño: K2 ∈ {8, 22, 60, 148} con `lpm=150` y `tn=162` fijos, n=5 intercalados en orden
ascendente. Los tres tiers del gain scheduling (`lqr2`, `lqr2n`, `lqr2vn`) escalan juntos
manteniendo sus proporciones — barrer sólo `lqr2` habría dejado el mismo K2 de 30 o 55 cerca
de la vertical, que es justo donde importa.

**Se cortó tras 5 intentos: 3 de los 4 de la rep 1 no traspasaron.** K2 no toca el modo 5, así
que no era el barrido — el swing-up había dejado de entregar.

### El swing-up se degradó a lo largo de la sesión

Las cuatro tandas del día, en orden cronológico:

| tanda | bombeo mediano | θ máx en bombeo | tope tocado | traspasos |
|---|---|---|---|---|
| m4 (1ª) | 5,5 s | **69,0°** | 0/15 | **15/15** |
| `tn` | 6,8 s | 79,9° | 6/20 | 14/20 |
| `lpm` | 6,2 s | 82,8° | 4/20 | 16/20 |
| **`k2` (abortada)** | **13,6 s** | **94,7°** | 3/5 | **2/5** |

El bombeo se duplicó y el brazo pasó de usar 69° a vivir contra el tope de 95. Con el
control (K2=22) sin producir dato, seguir habría gastado 16 intentos más en ceros.

`v_bus` se mantuvo en 15,0 durante todo el día, así que no es alimentación. Es la firma de
**más fricción** — la misma que la Etapa 1 documentó el 2026-08-04 con las dos curvas de
`kd` moviéndose enteras en un día de uso intensivo.

### Dos consecuencias que exceden esta tanda

1. **[P12](../../docs/REGISTRO_PROBLEMAS.md#p12) vuelve a estar vivo, como dependiente del
   estado.** Se cerró ayer con n=10 sobre banco fresco (θ 49,2–80,1°, 0/10 tocan el tope) y
   esa medición sigue siendo correcta — **para banco fresco**. Con 60 corridas encima, la
   mediana de θ en bombeo es 94,7° y el tope trunca. La conclusión no era falsa; le faltaba
   la condición.

2. **Hay que verificar la línea base del m5 antes de CADA tanda, no sólo al empezar el día.**
   Hoy el criterio 1 atrapó el problema dos veces —primero como entregas que mejoraban, después
   como un swing-up que no entrega— pero siempre después de gastar la tanda. Un chequeo de
   3 intentos al arranque de cada barrido cuesta 3 minutos y habría ahorrado dos.

### Estado en que quedó la placa

Paro de emergencia, modo 0, y todos los mandos de vuelta en sus defaults compilados:
`lqr2`=22, `lqr2n`=30, `lqr2vn`=55, `lpm`=70, `tn`=155, `lqr3`=1,5, `lc`=400, `cg`=0.
Verificado por `/state`. (El `finally` del script no corre cuando se lo mata, así que la
restauración se hizo a mano.)

## El signo de K3 (H7): se instrumentó en vez de inferirlo

Con el banco fuera de servicio se intentó resolver H7 desde las trazas, **ajustando
`pwm ~ θ, α, θ̇, α̇` sobre las muestras no saturadas del modo 4. No funcionó, dos veces:**

| intento | n | R² | coef. de α | esperado |
|---|---|---|---|---|
| todas las trazas del día | 2809 | 0,547 | **+0,05** | ±22 |
| subconjunto limpio (`cg=1`, \|θ\|<50, \|α\|<25, EMA como el firmware) | 207 | 0,282 | **+1,18** | −55 |

Signo cambiado y factor 50 en magnitud. La causa es estructural: **con la salida saturada
el 98% del tiempo, las únicas muestras no saturadas son los instantes en que la señal cruza
por cero** — una muestra minúscula y sesgada, y justo donde la reconstrucción de las
velocidades (gradiente numérico + EMA arrancada en cero, no el estado real del filtro) es
peor. Ninguna cantidad de cuidado en el ajuste arregla eso.

Insistir por inferencia habría sido el cuarto caso del día. **v1.58.10 publica en `/state`
lo que la ley consume de verdad:** `lqr_vel_theta`, `lqr_vel_alpha` y `lqr_alpha_err`, los
tres escritos en el mismo tick en que entran a `u`. Son espejos: ningún lazo los lee.

`scripts/sign_probe.py` hace el test, y **no necesita motor**: pone las nueve ganancias a
cero (`u = 0`), `lpm=20` y `cg=1` re-entrando al modo 4 cada 2 s para renovar el periodo de
gracia del centering. Verificado en la placa — PWM clavado en 0 y los espejos vivos. Se mueve
el brazo a mano y se lee:

| observación | conclusión |
|---|---|
| θ creciendo con `lqr_vel_theta` **negativa** | `velTheta_ctrl` = −θ̇ ⇒ **H7 CIERTA**, K3 anti-amortigua |
| θ creciendo con `lqr_vel_theta` **positiva** | H7 falsa, K3 ya amortigua bien |

Requiere una mano en el brazo, así que queda para la próxima sesión. De paso confirmó una
convención: con el péndulo colgando, `lqr_alpha_err` lee **180,0** — `alpha` es 0 en la
vertical invertida, como decía el comentario.

## Segundo intento del barrido de K2 — también abortado, y el ciclo de trabajo del banco

Tras ~40 min de reposo, la línea base (`scripts/baseline.py`, 3 intentos) dio **3/3
traspasos, bombeo 7,5 s, θ 84,7°**: por debajo de los umbrales de corte, así que se
reintentó con n=3 en vez de n=5 para que los 12 intentos entraran en la ventana buena.

**Resultado: 2 traspasos de 12.** El control (K2=22) dio 0/3, así que el criterio se negó a
evaluar — correctamente.

| K2 | región lineal | traspasa | `t_loss` |
|---|---|---|---|
| 8 | 18,8° | 1/3 | 58 ms |
| 22 (control) | 6,8° | **0/3** | — |
| 60 | 2,5° | 1/3 | **114 ms** |
| 148 | 1,0° | 0/3 | — |

Los dos traspasos murieron **dentro de la ventana del catch**, así que ni siquiera dejaron
dato de saturación.

### Lo que sí aporta: el ciclo de trabajo del banco

La línea base repetida al terminar dio **bombeo mediano 15,9 s, 2/3 traspasos**. O sea:

| momento | bombeo mediano | traspasos |
|---|---|---|
| mañana, banco fresco | 5,5 s | 15/15 |
| tras ~40 min de reposo | **7,5 s** | 3/3 |
| 12 corridas después | **15,9 s** | 2/3 |

**Cuarenta minutos de reposo compraron unas doce corridas.** La degradación es rápida y la
recuperación, parcial y lenta. Eso convierte lo que parecía deriva lenta de jornada en algo
más exigente: el swing-up tiene un **ciclo de trabajo de aproximadamente una docena de
intentos**, y cualquier campaña más larga que eso mide dos plantas distintas.

También explica por qué `tn=162` empeoró el cuadro: exige bombear hasta 162° en vez de 155°,
lo que alarga cada intento y consume el ciclo más rápido. El umbral que mejora la entrega y
el que permite completar una tanda están en conflicto sobre banco cansado.

### Un dato individual que vale anotar

El traspaso de K2=60 dio **`t_loss` = 114 ms con un error de entrega de 2,6°** — el mejor
resultado de las 87 corridas del día, y con la mejor entrega del día. El ajuste
`−4,17·ε + 90,2` predice 79 ms para ese error; se observaron 114. Sigue la línea de que la
ordenada está **subestimada**, no sobreestimada. Con n=1 no prueba nada sobre K2, pero
refuerza la reserva ya anotada sobre extrapolar la ecuación hacia errores pequeños.

## La hipótesis que unifica P4 con la degradación, y por qué quedó sin contrastar

Al final de la jornada apareció una lectura que no se había considerado. Las ganancias del
LQR se diseñan por CARE sobre un modelo cuyos dos términos disipativos son:

| parámetro | valor | procedencia |
|---|---|---|
| `Dp` (péndulo) | 7,52e-6 | medido **una vez**, 2026-08-04, n=2, **banco fresco** |
| `Dr` (brazo) | 5e-6 | **nunca medido** — el default de la clase, con `Dr_std` igual al valor |

Y la jornada demostró que la fricción real cambia lo suficiente **dentro de una hora** como
para que el swing-up deje de funcionar. Si el parámetro dominante se mueve así, el problema
no sería que las ganancias estén mal sintonizadas sino que **puede no existir un juego de
ganancias fijas que sirva** — lo que convertiría a P4 y a la degradación del banco en el
mismo problema, y explicaría por qué cinco hipótesis razonables cayeron una tras otra: todas
buscaban el error en el controlador.

**Es una hipótesis. No se pudo contrastar hoy**, y el recorrido de por qué vale más que el
intento fallido.

### Tres formas de medir mal un spin-down

`scripts/spindown_now.py` intenta repetir la medición de `Dp` con el banco cansado, usando
la excitación que deja el homing (efecto lateral descubierto en P22) para no necesitar una
mano. Falló tres veces, cada una por una razón distinta:

1. **Con `m=0` el brazo no está sujeto.** Se movió 13°, y con dos grados de libertad
   acoplados la energía del péndulo se trasvasa al brazo y vuelve: la envolvente deja de
   decaer. Dio λ = −0,0006 con R² = 0,02. La referencia del 2026-08-04 se tomó
   explícitamente *con el brazo sujeto* a mano.
2. **Sujetarlo con el PID (`m=2`) tampoco alcanzó del todo**, aunque sí después de unos 5 s
   de asentamiento. Pero el ajuste seguía sin cerrar, porque:
3. **La señal traía un offset de −26° y el ajuste no lo quitaba.** Fuera del modo 5 el
   firmware no re-establece el cero del péndulo —P22 se corrige sólo al entrar a m5—, así
   que `alpha` iba de −29,2 a −22,5 sin cruzar cero nunca. Los picos de `|alpha|` estaban
   dominados por el offset constante y la exponencial no veía el decaimiento.

Corregidos los tres, quedó el impedimento de fondo: **la excitación del homing es de 3,7 a
4,4°**, y la referencia se tomó con sueltas de 64° y 43°. No es un problema de precisión.
Por debajo de unos 20° manda la fricción seca, y el modelo $A(t) = A_0 e^{-\lambda t}$
ajusta la curva equivocada — de hecho fue justamente comparar 64° con 43° lo que permitió
*demostrar* en su momento que el amortiguamiento era viscoso. Las dos capturas dieron
λ = 0,159 y λ = 1,233: un factor 8 entre sí, con R² de 0,40 y 0,12.

### Lo que se hizo en vez de forzar un número

El script ahora **se niega a reportar** cuando no puede sostener el resultado, con tres
guardas que salieron de los tres fallos: amplitud mínima de 20°, R² mínimo de 0,85 y
descarte de los primeros 5 s de asentamiento, más un aviso si el brazo se mueve más de 4°.
Verificado contra casos sintéticos construidos **para que fallen**, no sólo para pasar.

Para obtener el número hace falta el protocolo manual del 2026-08-04, que es el único que
dio algo reproducible (dos sueltas coincidiendo al 0,4\%):

1. Sujetar el brazo a mano, firme, en el centro.
2. Levantar el péndulo unos 45–60° y soltarlo sin impulso.
3. Correr `spindown_now.py`; graba y ajusta solo.

Y queda anotado que **`Dr` no se puede medir por este camino**: el brazo cuelga del motor y
con el L298N en reposo las dos entradas quedan en bajo, o sea el motor en cortocircuito. Un
decaimiento del brazo mediría `Dr` más la disipación por back-EMF. Separarlas exige abrir el
circuito del motor.

### Un hallazgo lateral

En las capturas el péndulo osciló a **1,71 Hz**, no a los 2,28 Hz de la frecuencia natural
identificada el 2026-07-30 (que es de donde sale `PEND_INERTIA`). La discrepancia es grande
y no se investigó. Puede ser efecto del brazo no estar rígidamente sujeto, o algo más. Queda
como pendiente porque `PEND_INERTIA` alimenta el cálculo de energía del swing-up y el
criterio `E/E*`.

### H5 queda sin medir

Es la última hipótesis en pie de P4 y el barrido está escrito y probado en seco
(`scripts/k2_sweep.py`). Requiere banco descansado. Los 5 intentos que alcanzaron a correr
quedan en `data/k2_*_r1.csv` y **no sirven como resultado**: se conservan sólo como la
evidencia de la degradación.

---

**Intento previo del 2026-08-05.** La placa respondía (`mode=0`, `ina_ok=true`, `loop_overruns=2`)
pero con **`v_bus` = 4,01 V** estable en 6 lecturas y `i_ma` = 1,1: la ESP32 viva por USB y
la fuente del motor apagada. Con `ina_ok` verdadero la protección por tensión está activa en
los dos modos de la campaña (`:3722` para el LQR, `:4031` para el swing-up) y por debajo de
12,5 V hace `pwm = 0; setMotor(0); return`, así que los 15 intentos habrían corrido con el
motor mudo: ningún traspaso, `t_loss` sin definir, y un `sweep.json` de nulos indistinguible
de una campaña que falló de verdad.

De ahí salió el chequeo de `v_bus` de arriba, que antes no existía — el script sólo miraba
`ina_ok`.
