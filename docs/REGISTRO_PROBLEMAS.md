# Registro de problemas — QUBE Servo

Bitácora viva de defectos conocidos, su estado, y **cómo afrontarlos si siguen
abiertos**. Iniciada 2026-07-30 tras la campaña de validación exhaustiva.

Estados: `ABIERTO` · `EN CURSO` · `RESUELTO` · `MITIGADO` · `NO ES DEFECTO`

| id | problema | severidad | estado |
|---|---|---|---|
| [P1](#p1) | `forcedTransition` anula los otros 3 criterios de swing-up | alta | `RESUELTO` |
| [P2](#p2) | ~~El swing-up no alcanza la energía~~ → **sobra energía; el problema es la captura** | alta | `REFORMULADO` |
| [P3](#p3) | Homing se cala en un punto duro y acepta el cero corrido | alta | `RESUELTO` |
| [P4](#p4) | El LQR no sostiene ni con una entrega perfecta (α=178,4°, α̇=0, E/E*=1,000) | **alta** | `EN CURSO` — **H2 refutada** (2026-08-04): quitar el catch empeora. La calidad de la entrega **no correlaciona** con la supervivencia (r≈−0,09, n=19) ⇒ el cuello es el controlador (H3/H5), no la entrada |
| [P5](#p5) | Magnitud de α̇ dudosa → `E/E*` no confiable | alta | `RESUELTO` |
| [P6](#p6) | ~~m2 PID: sobrepaso 68–77%~~ → **39–42%**; la cifra estaba inflada por la métrica | baja | `RESUELTO` (2026-08-04) — `kd=0,45` es el default desde v1.58.0 y se re-verificó en v1.58.5: **1,2%** de sobrepaso, 0 hunting |
| [P7](#p7) | `sample_hz` inflado en modos multi-tramo (instrumentación) | baja | `RESUELTO` |
| [P8](#p8) | Homing: el brazo no siempre queda centrado | baja | `MITIGADO` |
| [P9](#p9) | El estimador de α̇ tiene ganancia 1,52, no 1 | media | `RESUELTO` |
| [P10](#p10) | Umbrales de traspaso cortaban el bombeo a mitad de subida | alta | `RESUELTO` |
| [P11](#p11) | El bombeo satura contra `swingupPwmMax`, anulando `ke_gain` | alta | `RESUELTO` (no era el cuello) |
| [P13](#p13) | `resetPendulumOffsetHere()` redefine el cero del péndulo en silencio | media | `RESUELTO` |
| [P12](#p12) | El límite del brazo trunca swing-ups | alta | `ABIERTO` — la "refutación" del 2026-08-04 se midió con la referencia de α corrida (P22). Con `zp=1` el brazo llega a **94,9°** en bombeo, contra un tope de 95 |
| [P22](#p22) | **La referencia angular del péndulo deriva y nadie la re-establece**: colgando y quieto leía 82/97/91 y una vez −264°, debiendo leer 0 | **alta** | `MITIGADO` (2026-08-04) — `zp=1` tras reposo verificado elimina el fallo total (0/5 contra 1/4) |
| [P14](#p14) | Las cuatro compuertas de traspaso comparaban un ángulo **sin acotar** | **alta** | `RESUELTO` (2026-08-03, v1.57.2) |
| [P15](#p15) | Con el motor bombeando, el lazo produce **256–330 Hz**, no 500, con paradas de hasta 0,49 s | **alta** | `NO REPRODUCIBLE` (2026-08-03) — 18/18 corridas limpias tras reiniciar |
| [P16](#p16) | ~~El encoder pierde cuentas por velocidad (filtro RC)~~ → **explicación refutada**; la deriva de α sólo aparece cuando el brazo golpea el tope | media | `ACOTADO` (2026-08-04) — sin deriva en 8 corridas hasta 1668 °/s |
| [P17](#p17) | **El contador del péndulo satura a las 16 vueltas** y α se vuelve basura, sin ninguna señal que lo denuncie | **alta** | `MITIGADO` (v1.58.4) — el bombeo ya no puede embalarse; falta el acumulador de desbordamiento |
| [P18](#p18) | **El bombeo no tenía techo de energía**: sin traspaso, el péndulo se embala sin límite | **alta** | `RESUELTO` (2026-08-04, v1.58.4) |
| [P19](#p19) | **`/rl_state` se congela en silencio** al salir de los modos 6/7: repite el último valor en vez de fallar | **alta** | `ABIERTO` |
| [P20](#p20) | **El lazo RL por HTTP corre a 14,3 Hz**, no a los 50 Hz para los que se entrena. El modo 6 no puede evaluar una política | **alta** | `ABIERTO` |
| [P21](#p21) | **La inferencia en chip (m7) rompe el lazo de 500 Hz**: ~21% de los ticks atrasan >10 ms, unas 100× más lento de lo esperable | **alta** | `ABIERTO` |

---

## P1 {#p1}
### `forcedTransition` anula los otros tres criterios de traspaso

**Severidad:** alta — es la causa directa de que el swing-up nunca capture.

**Evidencia.** Con la telemetría latcheada (v1.55.0), en 4 de 4 intentos el criterio
fue `forced` y sólo `forced`, con α ≈ 125–127°, α̇ de 506–871 °/s y `E/E*` de
0,81–0,86. En la campaña de validación: 2 de 3 `forced`, 1 `peak`.

**Causa.** De las cuatro condiciones, tres exigen péndulo lento o energía en
tolerancia. `forcedTransition = |pendPos| > 125` **no exige ninguna**. Y su umbral
(125°) está apenas sobre el de cercanía (120°), así que se cruza antes de que las
condiciones con compuerta lleguen a cumplirse.

**Estado:** `RESUELTO` — ver sección de cambios abajo.

---

## P2 {#p2}
### El bombeo no inyecta la energía necesaria

**Severidad:** alta — aunque se arregle P1, sin energía no hay captura.

**Evidencia.** `E/E*` nunca superó 0,87 en 7 intentos medidos (rango 0,75–0,87).
Picos de α de 117–130°, con vertical en 180°.

**Progreso medido:** `E/E*` en el ápice pasó de **0,765 → 0,904** (P10) y luego a
**0,966** (barrido fino de `swingupPwmMax`). Pico de α de 120–128° a **158,7°**.
Falta ~3,4% de energía para la vertical.

### Barrido fino de `swingupPwmMax`, con condición inicial controlada

El barrido grueso anterior había concluido que 50 era óptimo y que subir empeoraba.
**Era un artefacto**: las corridas heredaban energía del péndulo de la corrida previa
(el homing lo agita, no lo disipa) y sobre todo el offset del péndulo estaba corrompido
(P13), de modo que un péndulo colgando quieto leía 98° y "traspasaba" en 1 s.

Protocolo corregido: homing → esperar reposo **por estabilidad de α** (no por
proximidad a cero, que P13 rompe) → `zp=1` para re-fijar el cero → bombear.

| `sp` | n | α máx (mediana) | `E/E*` |
|---|---|---|---|
| 50 | 3 | 145,4° | 0,911 |
| 55 | 3 | 154,7° | 0,952 |
| 57 | 2 | 156,8° | 0,957 |
| 59 | 1 | 157,0° | 0,961 |
| **60** | 1 | **158,7°** | **0,966** |
| 70 | 2 | 150,2° | 0,939 — empeora |

Mejora **monótona** hasta 60 y después cae: por encima el brazo cruza los 95° y
`safeStop` mata la corrida antes de acumular (a `sp=70` dura 3,3 s). Repetibilidad
dentro de cada valor: menos de 1,5°. Adoptado `swingupPwmMax = 60` por defecto.

Todas las mediciones de energía se toman **en el ápice**, donde `E/E* = (1−cos α)/2`
es geometría pura y no depende de α̇ (ver P9).

### Lo que se probó y NO movió la aguja

Tres barridos independientes, todos planos, y en **todos** el PWM del bombeo quedó
saturado en 49/50 (`frac_saturado = 1,00`):

| parámetro barrido | valores | meseta resultante |
|---|---|---|
| `swingupPwmMax` (`sp`) | 50 / 65 / 80 / 100 | 144,0 / 141,9 / 122,5 / 80,6 — **empeora** |
| `swingupPumpRefMaxDeg` (`pr`) | 70 / 80 / 88 | 143,8 / 143,0 / 142,9 — plano |
| `swingupCenterGain` (`pc`) | 0 / 0,5 / 1 / 2 | 143,1 / 143,4 / 143,0 / 142,7 — plano |

Subir `pr` hace que el brazo oscile más ancho (θ máx 75→85) pero el péndulo no gana:
con el PWM topado en 50 el brazo no puede seguir una referencia mayor **más rápido**.
El recentrado corrige la deriva del centro (que existe: −18 a −36°) pero tampoco
aporta energía.

**Conclusión: el único parámetro que importa es el tope de PWM, y subirlo mata la
corrida** — el brazo cruza los 95° y salta `safeStop` antes de acumular energía.
A PWM 50 la energía inyectada por ciclo se equilibra con la fricción en α ≈ 143°.

### Ley de Åström–Furuta: probada y PEOR (resultado negativo)

Implementada como ley alternativa (`?pl=1`), con `u = k(E*−E)·sign(α̇·cos α)`. El
signo correcto se determinó por sondeo de baja potencia: `pn=+1` llega a α = 66–71°
en 6 s a PWM 35, mientras `pn=−1` se queda en 9,7° (amortigua en vez de bombear).

A/B en la misma tanda, con la resonante como control para no arrastrar deriva del
banco:

| ley | meseta | E/E* | pico máx |
|---|---|---|---|
| **resonante (actual)** | **142,7°** | **0,897** | 154,0° |
| energía `sp=50` | 72,5° | 0,350 | 84,9° |
| energía `sp=70` | 83,4° | 0,443 | 91,8° |

**Rinde la mitad.** Interpretación: la ley clásica supone un actuador de **par**
(entrada = aceleración del brazo). Acá el PWM sobre un motor DC con fricción se
comporta mucho más como un comando de **velocidad**, así que un bang-bang de
aceleración no transfiere la energía que la teoría predice.

Y eso explica por qué la heurística existente funciona mejor: `pump_ref = α̇·GAIN`
con un P sobre posición equivale a **pedir velocidad de brazo en fase con α̇**, que es
la forma en velocidad del mismo bombeo por energía — mejor emparejada al actuador
real. La ley "buena" ya estaba, en otra forma.

**Se deja `swingupPumpLaw = 0` (resonante) por defecto.** La rama 1 queda en el
firmware por si se pasa a control por par (p. ej. lazo de corriente), donde sí
debería ganar.

### ⚠ REFORMULADO (2026-07-31): no falta energía, sobra

Con el traspaso **desactivado** (`tr=0`, añadido para poder medir), el bombeo a
`sp=60` durante 30 s:

| rep | pico máx | `pend_wraps` | ciclos |
|---|---|---|---|
| 1 | **179,8°** | **1** | 23 |
| 2 | **179,8°** | **1** | 32 |
| 3 | 158,9° | 0 | 41 |

`pend_wraps = 1` significa que el péndulo **pasó de 180° y acumuló una vuelta**. O sea
que el bombeo alcanza la vertical y la sobrepasa en 2 de 3 corridas.

**La meseta de 157° nunca fue un techo de energía: era el umbral de traspaso cortando
la corrida.** Exactamente la trampa de P10 un nivel más arriba — con la diferencia de
que esta vez se sospechó y se midió, en vez de descubrirse por accidente.

Todas las conclusiones previas de "falta un X% de energía" quedan **anuladas**. El
problema deja de ser energético y pasa a ser de **captura**: el péndulo llega arriba
con velocidad de sobra y sigue de largo, en vez de llegar con α̇ ≈ 0.

**Qué siguió: barrido del ángulo de captura (`?tn=`, mando único del que se derivan
los tres umbrales).**

| `tn` | traspasos | t en LQR | t arriba | α al traspasar | `E/E*` |
|---|---|---|---|---|---|
| 155 | 2/2 | 0,52 s | 0,04 s | 159,6° | 0,968 |
| 165 | 0/2 | — | — | — | — |
| 170 | 0/2 | — | — | — | — |
| 175 | 1/2 | 0,86 s | 0,14 s | **−178,4°** | **1,000** |

**El swing-up SÍ puede entregar una condición perfecta**: 1,6° de la vertical, α̇ = 0,0 °/s,
energía exactamente 1,000. Y aun así el LQR sólo aguantó 0,86 s.

**Por qué mueren las demás:** 5 de 8 corridas terminan con el **brazo cruzando su
límite** (θ máx 87,9–102,0) mientras el péndulo va apenas por 155–160°. Es una
carrera: el brazo llega a 95° antes de que el péndulo llegue a 175°. Por eso `tn=165`
y `tn=170` no dispararon nunca.

### ⚠ Reserva sobre "sobra energía" (2026-07-31): n = 2 contra n = 4

La reformulación se apoya en **2 de 3** corridas con `tr=0` que llegaron a 179,8°. Las
**4 corridas posteriores con `tn=175` toparon en 159,1–160,5°** (`sweep_catch.json`),
todas con `murio = true`. La diferencia entre tandas no parece ser la energía
disponible sino **cuánto dura la corrida**: con `tr=0` bombeaban 30 s (23–41 ciclos);
con el traspaso armado mueren por límite del brazo a los pocos segundos.

O sea que "el bombeo alcanza la vertical" está medido **con 30 s de bombeo**, no dentro
de la ventana en que hay que capturar. Antes de construir encima conviene repetir el
`tr=0` con n ≥ 5: hoy la afirmación descansa en dos corridas y hay cuatro que no la
reproducen.

**Los dos bloqueantes quedan identificados con evidencia:**
1. **P12** — el recorrido del brazo trunca la mayoría de los intentos. Ya no es
   "desperdicio teórico": es la causa medida de 5 de 8 fallos.
2. **P4** — con la entrega ideal, el LQR no sostiene. Deja de ser "no evaluable hasta
   que el swing-up funcione": ya se evaluó, y es ahora el bloqueante real.

### Cómo afrontarlo (lo que queda)

1. **Más recorrido útil** (P12): subir `SERVO_HARD_LIMIT_DEG`. Medido, el sobrepaso
   tras el corte a PWM 50 es de **27°**, y el tope mecánico está en 134,8 — así que
   por encima de ~105 el margen se agota. Gana poco y arriesga bastante.
2. **Lazo de corriente / control por par**, que además habilitaría la ley de energía.
   Cambio grande.
3. **Reducir fricción.** Mecánico, fuera del alcance del firmware.

**No barrer `ke_gain`:** con el PWM saturado el 100% del tiempo, la ganancia
proporcional no puede influir en la salida. Ésa es una segunda razón, además del bug
F1, por la que sus barridos históricos no eran atribuibles.

---

## P3 {#p3}
### El homing acepta calibraciones malas tras modos energéticos

**Severidad:** alta — un cero corrido corrompe en silencio todo `theta` posterior.

**Evidencia.** De 24 corridas, 3 midieron 250,3–251,7° (≈19° cortas) y **la ventana
de 250–290 las aceptó**. Las 3 vienen justo después de `m1`. Con 24 muestras:
dispersión del tope negativo 0,70°, del positivo 20,56°.

**Estado:** `RESUELTO`.

### La causa NO era inercia residual

Hipótesis inicial (mía y de Antonio, desde la observación en banco): lanzar el homing
enseguida tras un intento dejaba inercia que falseaba el calado. **Se probó y es
falsa.** A/B con espera de 0 s vs 8 s tras un swing-up: **misma tasa de fallo**, y
disparar al instante nunca produjo el código 5 de "no se aquietó" — o sea que el
detector de quietud daba por quieto el mecanismo justo cuando el fallo ocurría.

### La causa real: un punto duro mecánico

Diagnóstico con 8 corridas registrando los topes crudos:

| | tope − | tope + |
|---|---|---|
| 5 éxitos | 168,40–168,57 | −101,25 a −101,60 |
| 3 fallos | 168,40–168,57 | **−85,08 a −85,61** |

Los fallos se calan en **−85,3 ± 0,3**, exactamente 16° antes del tope real, y tan
agrupados que no puede ser ruido: hay un **punto duro reproducible** a ~119° del
centro en el lado positivo. A veces el brazo lo vence y a veces no.

**Y lo introduje yo:** el fallo apareció al bajar `HOMING_PWM_SEEK` de 70 a 55 para
suavizar el impacto (v1.53.2). A 55 el brazo no siempre pasa ese punto.

### Corrección

`HOMING_PWM_SEEK` devuelto a **70**, y **sólo la búsqueda**: el toque sigue en 55
porque arranca a 5° del tope real —ya pasado el punto duro— y es el que fija la
medición, así que la suavidad donde importa se conserva.

**Verificado: 8/8 exitosos**, y el tope positivo pasó de 20,56° de dispersión a
**0,35°** (2 conteos), igual de bueno que el negativo.

### Lo que sí quedó del intento fallido

Aunque la hipótesis era errónea, dos cambios de ese intento valen por sí solos y se
conservan: `WAIT_QUIET` ahora vigila **el brazo además del péndulo**, y agotar su
timeout es **falla (código 5)** en vez de arrancar a ciegas. El comentario original
decía que arrancar igual "es riesgo de repetibilidad y no de daño" — era falso: el
riesgo es un cero equivocado aceptado en silencio.

Las esperas del lado del cliente se revirtieron a 0 por defecto: no aportan y cuestan
6 s por homing.

**Pendiente mecánico:** conviene revisar qué hay a ~119° del centro. El firmware ya
lo esquiva con más fuerza, pero es un síntoma físico real.

---

## P4 {#p4}
### m4 LQR cruza el límite en 0,3 s desde péndulo colgando

**Severidad:** media — puede no ser defecto.

**Evidencia.** 3 de 3 repeticiones: acciona el motor el 100% del tiempo, satura hacia
un lado y cruza los 95° en 0,3 s.

**Actualización 2026-07-31 — la "entrega perfecta" era un artefacto.** Se registró un
traspaso con α = 178,4°, α̇ = 0,0 °/s y `E/E*` = 1,000, y el LQR aguantó sólo 0,86 s.
Pero la traza muestra al péndulo recorriendo **33° en 70 ms (≈470 °/s)** en ese mismo
instante.

**Causa:** `wrapPendulumTurns()` reiniciaba el filtro de velocidad (`rl_vf_init =
false`), y el acotado se dispara justo al cruzar la vertical — o sea que la velocidad
reportada caía a 0 exactamente donde las compuertas deciden el traspaso. `verySlow`
se cumplía **siempre** al cruzar arriba, sin importar la velocidad real. El LQR no
recibía un péndulo quieto sino uno pasando a ~470 °/s.

**Corregido:** al acotar se DESPLAZA el estado del filtro por el mismo salto
(`rl_vf_alPrev += turns·360·DEG_TO_RAD`) en vez de reiniciarlo, de modo que la
derivada queda continua.

**Con la compuerta honesta, `tn=175` no dispara nunca** (0/4): el swing-up **no está
entregando** una condición válida. P4 vuelve a no ser evaluable — lo medido antes no
probaba nada sobre el LQR.

**Cómo afrontarlo.** Revisar las ganancias (`lqr.py` usa `Q = diag([1, 10, 1, 5])`,
nunca validadas en banco) y el `catch` de frenado inicial. Ahora se puede iterar de
verdad: hay un swing-up capaz de producir la condición inicial correcta, y
`swing_trans_*` deja registrada la calidad de cada entrega.

### Causas candidatas (2026-07-31, por lectura del firmware — NO medidas en banco)

Cuatro defectos en el camino de entrada al LQR. Se listan por cuánto explican del
síntoma; **ninguno está verificado experimentalmente todavía**.

**H1. El `catch` no mide velocidad, mide desplazamiento acumulado.** (`:2944-2955`)
La rama del catch retorna (`:2954`) **antes** de `lqr_prevAlpha = alpha_raw`
(`:2977`), así que durante los 400 ms de `LQR_CATCH_MS` la referencia queda congelada
en el valor de entrada. `-(pendPosRaw - lqr_prevAlpha)/dt` con `dt` = 2 ms fijo divide
por un tick todo el recorrido desde el traspaso: 30° acumulados dan 15.000 °/s, y
`brake_pwm` satura contra `LQR_CATCH_PWM` (25) casi de inmediato. Peor: la dirección
se fija en los primeros 10 ms desde esa misma lectura, que con una entrega buena
(α̇ ≈ 0) es **ruido de un conteo de encoder**. Neto: 400 ms de empuje constante de
±25 PWM en un sentido esencialmente aleatorio.

**H2. Durante esos 400 ms no corre el LQR.** El `return` corta el tick. Con
ω_n = 14,34 rad/s (medida, P5), una desviación de la vertical crece como
`cosh(ω_n·t)`: **×155 en 400 ms**. Una entrega a 1,6° se convierte en caída completa
antes del primer tick de control. Explica los 0,86 s de aguante sin culpar a las
ganancias.

**H3. Con estas escalas el LQR es un relé.** (`:3000-3011`) `alpha` va en grados y
`velAlpha_ctrl` en grados/s (`rawVelAlpha` deriva `alpha_raw`, en grados; `kf_x[3]`
también, porque `kalmanUpdate` se alimenta de grados). Con `LQR_PWM_MAX = 70`, la
salida satura con **3,2°** de error (`lqr_K2 = 22`), **1,3°** en la banda very-near
(`K2 = 55`) y **7,8 °/s** (`lqr_K4 = 9`). Fuera de esa ventana la salida es ±70
constante. Coherente con lo medido en `m4_rep1.csv` (PWM clavado en −69/−67/−63) y con
que el veredicto del m4 sea "acciona el motor el 100% del tiempo".

**H4. El escalado por velocidad está permanentemente saturado.** (`:2993`)
`vel_alpha_dps = fabsf(velAlpha_ctrl) * RAD_TO_DEG` multiplica deg/s por 57,3: el
umbral de 200 se cruza con 3,5 °/s reales y `vel_scale` topa en 2,0 con 8,7 °/s. En la
práctica `k4_eff` es **siempre el doble** del declarado — no es gain scheduling, es una
constante oculta. Al arreglarlo hay que rehacer cualquier sintonía de `lqr_K4`.

**H5. Las ganancias del firmware no vienen de `src/qube_rl/lqr.py`.** El diseño por
CARE está en unidades SI (rad, rad/s) y `u ∈ [-1,1]`; los valores del `.ino` son de
sintonía manual en otra escala. No es que las ganancias diseñadas estén sin validar:
es que **no son las que corren**.

**H6. El periodo de gracia del centering nunca existió.** (2026-08-04, por lectura del
bloque de centering del modo 4.) El código calculaba
`centering_sec = (millis() - lqr_catchMs)/1000`, pero `lqr_catchMs` **ya se había
puesto a cero** al salir del catch, unas líneas más arriba. `millis() - 0` es el
**uptime de la placa**, siempre >> 2 s, así que `ramp` valía 1 desde el primer tick.

Su propio comentario dice *"solo activo 2+ segundos después del catch; durante los
primeros 2 s el LQR necesita control total del servo"*, **y eso no ocurría nunca**: el
centering entraba a ganancia plena, con hasta ±25 PWM sobre un `LQR_PWM_MAX` de 70,
justo cuando el swing-up entrega con el brazo lejos del centro. Es una fuerza que tira
del brazo al centro exactamente en el instante en que el LQR lo necesita para atrapar.

Mismo patrón que H1 y H4: un camino de código que no hace lo que su comentario dice. Y
como H2 y H6 viven los dos dentro de la ventana del catch, **medir uno sin controlar el
otro no significa nada**.

**Orden sugerido:** H1/H4 primero (son los que hacen que las mediciones signifiquen
algo), después H2/H3, que cambian comportamiento. No mezclar el arreglo del catch con
un cambio de ganancias en la misma tanda.

**Instrumentación (2026-08-04, v1.58.5).** H2 y H6 pasan a ser configurables por HTTP
(`?lc=` en ms, `?cg=` 0/1) **con los defaults iguales al comportamiento anterior**, así
que flashear no cambia nada por sí solo y el A/B se hace sin reflashear. `/state` expone
`lqr_alive_ms`, la supervivencia latcheada por el firmware desde el **fin** del catch
—contar los 400 ms en que el LQR no corre se los regalaría por igual a todas las
condiciones—. Campaña y criterio pre-registrado en `experiments/2026-08-04_p4_catch/`.

---

## P5 {#p5}
### Magnitud de α̇ dudosa

**Severidad:** alta — `E/E*` es criterio de traspaso y métrica de P2.

**Evidencia.** El firmware reporta 506–871 °/s en el traspaso. Contrastado con
`E/E*` implica una frecuencia natural de ~4,5 Hz, bastante más de lo típico para un
péndulo de este tamaño.

**Contexto.** El bug F1 (α̇ ≡ 0) se arregló el 2026-07-28: ahora `alpha_dot` lee
`rl_vf_alVel`, el mismo estimador de los modos 6 y 7. O sea que α̇ **existe**; lo
que está en duda es su escala, y por herencia la de `PEND_INERTIA`/`PEND_MASS`/
`PEND_LENGTH` que entran en `E/E*`.

**Estado:** `EN CURSO` — experimento de oscilación libre en marcha.

---

## P6 {#p6}
### m2 PID: sobrepaso 68–77% → **39–42% real**; y un kick anti-fricción inútil

**Severidad:** baja — converge, sin cortes. No bloquea nada del RL.

**Evidencia original.** Escalón de 40° (+20 → −20). El barrido previo, con escalón de
25°, dio ~25% de sobrepaso.

### Primero: la cifra estaba inflada por la métrica

`validate.py` calculaba `(max|θ| − |sp|)/|sp|`: normalizaba por el **setpoint** en vez
del tamaño del escalón, y tomaba el pico de todo el segmento, transitorio de entrada
incluido. En un escalón que cruza el cero eso da el doble.

Recalculado sobre **las mismas trazas** con la métrica corregida (`step_overshoot`,
normaliza por `sp − θ₀` y busca el pico tras el primer cruce):

| escalón | vieja | **nueva** |
|---|---|---|
| +3 → +20 (Δ 17°) | 13,8–28,3% | 16,3–31,7% |
| +17 → −20 (Δ 37°) | **68,3–76,7%** | **38,8–42,0%** |
| −15 → 0 (Δ 15°) | no se medía | 14,4–21,4% |

El sobrepaso real es ~40% en el peor escalón. Sigue siendo mucho y hay que bajarlo,
pero **la cifra de 68–77% no era el sobrepaso**. Nótese que en los escalones cortos la
métrica nueva da *más* que la vieja: ahí el escalón es menor que `|sp|`.

### Causa del sobrepaso: amortiguamiento derivativo insuficiente

`Td = Kd/Kp = 0,15/3 = 0,05 s`. En la traza (`m2_rep1.csv`): PWM inicial de 101
(`pwmLimit = PWM_MAX = 200` mientras |err| > 20°), el brazo recorre 20° en 69 ms
(~295 °/s) y el freno derivativo disponible es `0,15 × 295 ≈ 44` contra 113 de empuje.
Pico en −34,9, rebote a −8,2 (undershoot 11,8°): ~2 ciclos mal amortiguados. El
escalonamiento de `pwmLimit` recorta el par de accionamiento pero **no frena**.

### Causa del error de régimen (4,8°): el kick anti-fricción no podía funcionar

No es del ajuste, es fricción estática, y el mecanismo que debía cubrirla estaba mal
por los dos extremos a la vez:

- exigía `|err| > 8°`, y la banda donde el brazo queda pegado es **0,8–8°** —
  justo la que quedaba fuera;
- aplicaba `PWM_MIN = 12`, y **12 PWM no mueve el mecanismo**: el homing usa 45
  (`HOMING_PWM_MIN`) para vencer la misma fricción, y la traza muestra al brazo
  inmóvil en −15,2° con el PID pidiendo 14–15 PWM durante más de 1 s.

Un kick por debajo del arranque real es un kick que por construcción no arranca. Con
la banda descubierta, lo único que saca al brazo es el integrador, a `Ki × err ≈`
**2,4 PWM/s** — más lento que la prueba de 3 s, así que la corrida termina con el
error todavía puesto.

### Correcciones (2026-07-31, compilan; **sin medir en banco todavía**)

- Métrica de sobrepaso corregida en `validate.py`, con la vieja conservada aparte
  (`overshoot_pct_max_legacy`) para poder empalmar con las tandas del 30.
- `stiction_err_thresh_deg` 8 → **2**, `stiction_kick_pwm` 12 → **30**, ambos
  configurables por HTTP (`?se=`, `?sk=`) y en `/state`. `PWM_MIN` se eliminó: su
  único uso era éste y el nombre prometía un piso global que nunca fue.
- El feedforward gravitacional se movió **antes** de la zona muerta. Estaba después,
  así que el `pwm = 0` de la zona muerta quedaba pisado por el `ff` sumado a
  continuación. Inocuo sólo porque `servo_ff_pwm = 0` por defecto.

**Pendiente:** barrer `kd` ∈ {0,15 · 0,3 · 0,45 · 0,6} y el par `se`/`sk` con
`experiments/2026-07-31_pid/scripts/sweep_pid.py`. El barrido mide `hunting` (cruces
del setpoint y PWM activo en régimen) a propósito: subir el piso del kick puede
cambiar un error de régimen por un ciclo límite, que es peor. Criterio: sobrepaso
< 20% sin degradar `sse` ni disparar hunting.

---

## P7 {#p7}
### `sample_hz` inflado en modos multi-tramo

**Severidad:** baja (instrumentación, no firmware).

`record()` reinicia `t_s` en cada tramo, así que en m1/m2/m6 el cálculo dividía el
total de muestras por la duración del **último** tramo. Reportaba 40–74 Hz cuando la
tasa real es ~13 Hz en todos los modos.

**Estado:** `RESUELTO` — ver cambios.

---

## P8 {#p8}
### El homing no siempre deja el brazo centrado

**Severidad:** baja — no afecta la calibración.

Al cortar el motor el puente queda en corte, no en freno, y el péndulo con swing
residual back-drivea el brazo (es direct-drive). Una corrida quedó a 19,5° del centro.
El offset se fija en el centro geométrico medido pase lo que pase, así que **el cero
es correcto igual**.

**Estado:** `MITIGADO` — `QubeRealEnv` encadena `m2` tras el homing para centrado fino
(v1.54.0); medido `park_error_deg = 0.0`.

---

## P9 {#p9}
### El estimador de α̇ sobre-lee ~4× a alta velocidad

**Severidad:** media — no bloquea nada hoy, pero invalida cualquier métrica que use
α̇ lejos del cero.

**Estado:** `RESUELTO`. **El "4×" era en parte artefacto de P13** — un cambio de
offset a mitad de corrida es una discontinuidad de 360° que entra en el derivador como
un pico. El sesgo real es **1,52×**.

### Causa (analítica)

```c
rl_vf_alVel = 50.0f * (xal - rl_vf_alPrev) + 0.36787944f * rl_vf_alVel;
```

Al término de diferencia le falta el factor `(1−a)`. Para velocidad constante la
ganancia en régimen es `1/(1−e⁻¹) = 1,582`; a la frecuencia natural del péndulo
(2,28 Hz medida) es **1,520**. Al cuadrado, el término cinético de la energía se
sobre-estima **2,3×**.

### El estimador NO se corrige

El simulador usa **exactamente el mismo filtro** (`qube_rl/utils.py`,
`VelocityFilter`, portado de Quanser) con la misma ganancia — verificado numéricamente:
ambos dan 1,5820 ante una rampa. Para las observaciones del RL lo que importa es que
sim y real concuerden, no que el valor sea físicamente exacto. **Cambiar el firmware
rompería el emparejamiento sim2real.**

### Se corrige sólo donde α̇ es una magnitud física

`ALPHA_DOT_FILTER_GAIN = 1.52` se descuenta en los dos cálculos de energía (criterio de
traspaso y ley de bombeo `pl=1`). Los umbrales de velocidad se dejan en la escala del
estimador: se calibraron contra valores **reportados**, y convertirlos los desplazaría.

### Verificación

**Empírica**, por conservación de energía en oscilación libre
(`α̇(0) = ω_n·√(2(1−cos A))`, con ω_n medida del período): cociente
reportado/predicho = **1,488** en 3 corridas, contra 1,520 calculado. La dispersión
(1,23–1,68) viene de muestrear a ~30 Hz por HTTP y perder el pico exacto.

**Funcional:** el criterio `energy` del traspaso, que **nunca había disparado**, ahora
lo hace en 2 de 3 intentos. `E/E*` en el traspaso da 0,954–0,961, coherente con los
0,961 medidos geométricamente en el ápice — dos caminos independientes que concuerdan.

---

## P10 {#p10}
### Los umbrales de traspaso cortaban el bombeo a mitad de subida

**Severidad:** alta. **Estado:** `RESUELTO`.

**Evidencia.** El bombeo crece de forma **monótona ~9°/ciclo**
(26→35→46→56→65→73→80→90→98→106→111→120 en 12 ciclos) y el brazo se mantiene en ±50°,
lejos de su límite. Los umbrales estaban en `near=120`, `forced=125`, ventana de
pico=120: **todos disparaban justo donde el bombeo todavía subía.**

El modo 7 híbrido ya usaba `hybrid_enter_deg = 165` — el modo 5 estaba muy por debajo.

**Corrección.** `NEAR 120→155`, `FORCED 125→165`, `PEAK_DEG 60→25`.

**Resultado medido.** Pico de |α| de 120–128° a **146,9–149,4°** (5/5, dispersión
2,5°), y **0/5 cortes por límite de servo** — era el LQR, tras el traspaso prematuro,
quien llevaba el brazo al tope.

---

## P11 {#p11}
### El bombeo satura contra `swingupPwmMax`

**Severidad:** alta. **Estado:** `RESUELTO` — pero **no era el cuello de botella**.

**Evidencia.** PWM del bombeo en 48–49 contra un tope de 50: saturado el 70% del
tiempo. Con la salida recortada, `ke_gain` **no puede influir** — otra razón, además
del bug F1, por la que sus barridos históricos no eran atribuibles.

**Pero subir el tope empeora las cosas:**

| `swingupPwmMax` | meseta | E/E* | ciclos | θ máx | ¿cortó? |
|---|---|---|---|---|---|
| **50** | **144,0°** | **0,904** | 50 | 73,0 | no |
| 65 | 141,9° | 0,893 | 10 | 75,1 | sí |
| 80 | 122,5° | 0,768 | 6 | 87,0 | sí |
| 100 | 80,6° | 0,418 | 3 | 93,5 | sí |

Más PWM ⇒ el brazo oscila más ancho ⇒ cruza los ±95° ⇒ `safeStop` mata la corrida
antes de que el bombeo acumule energía. Los ciclos completados caen de 50 a 3.

**Conclusión:** dejar `swingupPwmMax = 50`. El límite real es P12.

---

## P12 {#p12}
### El límite blando desperdicia 40°/lado de recorrido mecánico

**Severidad:** alta — es el **cuello de botella actual** del swing-up.

**Evidencia.** Los topes mecánicos están en **±134,8°** (medidos con más de 30
homings, dispersión del tope negativo 0,70°). El límite blando `SERVO_HARD_LIMIT_DEG`
está en **95°**: sobran ~40° por lado sin usar.

El barrido de P11 muestra que la energía por ciclo crece con la amplitud del brazo,
pero el límite trunca la corrida antes de acumular. `sp=65` alcanzó el mejor pico
individual (152,9°) justo antes de morir.

**Sobrepaso tras el corte — medido.** Primera medición dio 47–57°, pero **estaba
contaminada**: comparaba la posición del corte contra el reposo 2,5 s después, y en
ese lapso el péndulo excitado back-drivea el brazo. Separando la traza temporal:

```
corte en θ=-75,6 → -97 (0,14 s) → -93 (0,4 s) → -38 (0,7 s) → -9 (1,1 s) → -19 (2,8 s)
```

**El sobrepaso real en la dirección de marcha es 27°** (a PWM 50); los 70° de
"excursión máxima" eran el retorno empujado por el péndulo. El puente **sí frena**
(con ENA en alto y ambos IN en 0, el L298N pone los bornes en corto), no queda libre.

**Margen disponible.** Tope mecánico en 134,8°. Con límite 95 + 27 de sobrepaso = 122:
hay ~13° de margen. Subir el límite a ~105 lo consumiría casi entero, y a más PWM el
sobrepaso crece.

**Pero a `sp=50` el brazo sólo llega a 73–79°**, o sea que **el límite no está atando
hoy**. Subirlo no desbloquearía nada por sí solo. Reclasificado: no es el cuello de
botella; el cuello es la ley de bombeo (ver P2).

---

## P13 {#p13}
### El cero del péndulo se redefine en silencio durante el swing-up

**Severidad:** media — invalida cualquier análisis que compare α entre corridas.

`resetPendulumOffsetHere()` se llama en 4 puntos del swing-up (detección de giro,
recovery), así que **"colgando" deja de ser 0°** a mitad de corrida y no vuelve. El
offset nuevo depende de dónde estaba el péndulo cuando saltó la detección.

**Cómo se descubrió.** Un detector de reposo que exigía `|α| < 3°` **nunca pasaba**,
ni con el péndulo perfectamente quieto: agotó los 45 s de timeout en 8 corridas
seguidas. El péndulo estaba en reposo; el cero era el que se había movido.

**Consecuencias.**
- Cualquier umbral absoluto sobre α es frágil entre corridas.
- `alpha_max` sigue siendo comparable **dentro** de una corrida, pero comparar α entre
  corridas exige verificar que el offset no cambió (`pend_offset_deg` en `/state`).
- Los criterios de traspaso usan `pendPos`, que hereda este offset. Si el reset ocurre
  antes del traspaso, los umbrales de 155/165 se evalúan contra otra referencia.

### Corrección

La intención de los 4 sitios de llamada era **acotar** la lectura a [−180,180] tras
acumular vueltas, no re-cerar. Restar vueltas enteras logra lo mismo **preservando el
significado físico** de α (0 = colgando).

- `wrapPendulumTurns()` nueva: desplaza el offset en múltiplos de 360°. Los 4 sitios
  pasan a usarla. `resetPendulumOffsetHere()` queda sólo para el cero manual `zp=1`,
  que es legítimo con el mecanismo colgando en reposo.
- `zeroPendulumHere()` ahora delega en `resetPendulumOffsetHere()`, así `zp=1` también
  re-siembra el filtro de velocidad — antes el salto del offset entraba como un pico.
- **`pend_wraps` en `/state`**: contador monotónico de acotados. Se dejó monotónico a
  propósito: reiniciarlo en `setMode(5)` perdía eventos, porque el fallback del LQR
  acota y **justo después** llama a `setMode(5)`, borrando el wrap recién registrado.

**Verificación (prueba discriminante).** Se fuerza un offset artificial que hace leer
400° y se entra brevemente a m4, donde la protección corta el motor antes del
fallback. Las dos implementaciones predicen resultados distintos:

| implementación | `pend_position_deg` esperado |
|---|---|
| vieja (cero donde esté) | 0° — pierde la referencia |
| **nueva (resta una vuelta)** | **40°** (400−360) |

Medido: **44,04° con `pend_wraps` +1**. Pasa.

**Nota sobre el alcance.** En el lazo de control `pendPos` ya se acotaba
aritméticamente (`fmodf`), así que el acotado por offset sólo hacía falta para
`pendPosRaw`. Pero la telemetría de `/state` **no** aplica ese `fmod`, y el lazo
heredaba igual el offset corrompido — por eso los umbrales de traspaso se evaluaban
contra una referencia falsa.

---

## P14 {#p14}
### Las cuatro compuertas de traspaso comparaban `fabsf(pendPos)` sin acotar

**Severidad:** alta — invalidaba las mediciones de P2 y P4 a la vez.
**Estado:** `RESUELTO` — v1.57.2, 2026-08-03.

**Causa.** Las cuatro condiciones que disparan el traspaso m5→m4 (`nearVertical`,
`atPeakTransition`, `forcedTransition`, `energyReady`) comparaban `fabsf(pendPos)` contra
sus umbrales **sin acotar `pendPos` a [−180, 180]**. Si el péndulo acumula una vuelta,
`|pendPos|` supera cualquier umbral hasta 178 con el péndulo lejos de la vertical.
`wrapPendulumTurns()` (P13) sí acota, pero sólo se llama en las ramas de spin y recovery:
entre medio `pendPos` puede pasarse sin que nadie lo corrija.

**Evidencia** (campaña de bring-up del 03-ago, run 2, m5):

| `trans_alpha` latcheado | ángulo real | dista de vertical | reportó | correspondía |
|---|---|---|---|---|
| −199,16° | 160,84° | 19,2° | near+slow+**forced**+energy | `forced` es falso (160,84 < 165) |
| −223,42° | 136,58° | **43,4°** | near+slow+forced | **ninguna**: 136,58 < 155 |

La segunda traspasó con el péndulo a 43° de la vertical y `E/E*` = 0,863. En ambas,
`swing_trans_vel = 0,00` **exacto**: las dos mitades del criterio —ángulo y velocidad— se
cumplían de forma espuria a la vez.

**Corrección.** Acotado local para la evaluación (`pendPosWrapped`), sin tocar el offset ni
el estado, que los sigue manejando `wrapPendulumTurns()`. `swing_transAlphaDeg` pasa a
latchear el valor acotado, que es el que evaluaron las compuertas y el único comparable
entre corridas.

**Resultado medido**, 3 intentos inmediatamente después del fix:

| | antes | después |
|---|---|---|
| α de entrega | 136–161° | **170,7 / 179,3 / 177,0°** |
| `E/E*` | 0,86–0,97 | **0,9943 / 1,0007 / 1,0016** |
| `vel` | 0,00 exacto | 76,6 / 68,2 / 118,1 °/s |

**Es la misma familia que P1 y P13**: un umbral evaluado contra una referencia que no
significa lo que el umbral supone. Y como P1, estuvo enmascarando el diagnóstico de otro
problema — acá, de P2 y P4 a la vez.

**Consecuencia retroactiva.** Cualquier corrida en la que el péndulo acumulara vuelta podía
traspasar lejos de la vertical, entregándole al LQR una condición insostenible. Las
mediciones previas de P2 y P4 hay que releerlas con esto en mente.

---

## P15 {#p15}
### Con el motor bombeando, el lazo produce 256–330 Hz, no 500

**Estado:** `ABIERTO` · **Detectado:** 2026-08-03, primera sesión de la app de escritorio
(`docs/mine/APP_ESCRITORIO.md`).

#### Lo medido

Adquisición por bloques a 500 Hz nominales, `decim=1`, sondeo 0,2 s:

| condición | tasa efectiva | intervalo máx | huecos | perdidas | `loop_overruns` |
|---|---|---|---|---|---|
| reposo, motor sin energizar | **500,1 Hz** | 9,65 ms | 285 | 0 | 0 |
| reposo (2ª corrida) | **500,1 Hz** | 8,99 ms | 296 | 0 | 0 |
| **m5 swing-up, con GUI** | **330,1 Hz** | 214,6 ms | 217 | 0 | 7 |
| **m5 swing-up, sin GUI** | **256,4 Hz** | 488,6 ms | 131 | 0 | 8 |

#### Por qué no es el enlace

**`dropped = 0` en las cuatro.** Ese contador lo lleva el firmware y cuenta las muestras
que el anillo descartó por estar lleno, es decir, las que el PC no alcanzó a llevarse. En
cero significa que el PC vació el buffer siempre: **las muestras que faltan nunca se
produjeron**. La mediana del intervalo sigue siendo 1,997 ms —la mayoría de los ticks
llegan a tiempo—, así que no es una desaceleración uniforme sino **paradas largas**.

#### El detalle que más conviene mirar

`loop_dt_max_us` marcó **17,3 ms** en la corrida donde las marcas de tiempo muestran un
hueco de **488,6 ms**. La métrica de salud del propio firmware **no ve** estas paradas;
lo que sí las registra es `loop_overruns` (8), que cuenta exactamente los casos en que el
atraso superó cinco períodos y hubo que re-sincronizar. Es decir: **`loop_dt_max_us` por
sí solo no sirve para descartar una parada del lazo**, y varias afirmaciones previas se
apoyaron sólo en él.

#### Lo que NO está establecido

La causa. La adquisición por sí sola no la produce (en reposo da 500,1 Hz con el DAQ
corriendo), así que el factor nuevo es el motor en marcha, pero eso no distingue entre:
el costo del propio lazo de swing-up, la transacción I²C del INA219 bajo ruido de
conmutación, la radio transmitiendo mientras el motor conmuta, o una caída de tensión
—el proyecto ya tuvo brownouts con el escalón de corriente del freno (v1.53.x, y el
1000 µF del riel de 5 V es la mitigación vigente).

**Descartada una candidata: no era el broadcast del WebSocket.** La placa de 30 pines
**no tiene la GUI en SPIFFS** (`GET /` → 404, verificado el 2026-08-03: nunca se le corrió
`uploadfs`), así que no había ningún navegador conectado a `/ws` durante ninguna de las
corridas. El costo de `ws.textAll()` sin clientes es despreciable.

**n=1 por condición con motor.** No repetir esto antes de sacar conclusiones sería el
mismo error que ya costó caro tres veces en este registro.

#### Cómo se afrontó, y el resultado: **no se reprodujo**

Se corrió el experimento propuesto (`experiments/2026-08-03_p15_loop/`, protocolo dentro
de la app para ver la traza mientras medía): **6 condiciones × n=3, 15 s cada una,
intercaladas**, con el criterio escrito antes de medir.

| condición | mediana Hz | dt máx | paradas >20 ms | perdidas | overruns |
|---|---|---|---|---|---|
| `reposo` | 498,7 | 16,7 ms | **0** | 0 | 3–9 |
| **`m1_osc`** (motor conmutando, sin lazo) | **490,4** | 17,4 ms | **0** | 0 | **19–32** |
| `m2_step` | 499,1 | 14,4 ms | 0 | 0 | 2–7 |
| `m5` (swing-up) | 498,7 | 14,2 ms | 0 | 0 | 4–5 |
| `m5_sv0` / `m5_tp1000` | 498,9 / 499,8 | 12,5 / 12,8 ms | 0 | 0 | 0–5 |

**18 de 18 sin una sola parada sobre 20 ms.** Y la réplica del protocolo original —dejar
bombear 6 s y recién ahí medir, para capturar al péndulo ya girando— dio **500,2 Hz con
máximo 8,7 ms**, con `pend_wraps = 5` y traspaso a α=176,84° (`E/E*` 0,9994): la condición
fue tan exigente como la original.

**Lo que sí quedó medido:** `m1_osc` es la peor condición de forma consistente (490,4 Hz y
19–32 overruns contra 498,7 y 3–9 en reposo). El motor conmutando **sí** perturba el lazo,
en la dirección que la hipótesis señalaba, pero ~2 % de las muestras y no el 50 %. Y no es
el que más corriente pico tiene (66 mA contra 278 mA de `m5`): lo que lo distingue es la
**frecuencia de inversión del puente**. Las variantes de comunicaciones (`sv=0`,
`tp=1000`) no cambian nada: esa hipótesis queda sin respaldo.

#### Por qué queda `NO REPRODUCIBLE` y no `RESUELTO`

El fenómeno se midió tres veces con instrumentos distintos, así que no fue un error de
lectura. Pero entre aquellas corridas y éstas cambiaron cosas que ya **no se pueden separar
retroactivamente**: la placa se reinició (reflasheo OTA a v1.58.3), las corridas originales
venían de una sesión larga con muchos swing-ups, homings y **un golpe contra el tope**, y
en una de ellas la app saturaba un núcleo del PC. Lo honesto es decir que algo que el
reinicio limpió lo producía, sin poder nombrarlo.

**Si vuelve, antes de reiniciar:** guardar `/state` completo, correr
`loop_load.py --gui --only reposo,m1_osc,m5 --reps 3` en ese mismo estado —la comparación
contra la tabla de arriba es directa— y recién después reiniciar. Si el reinicio lo cura,
eso **es** el dato.

#### Lo que este experimento NO borra

En la corrida original, `loop_dt_max_us` marcó **17,3 ms** mientras las marcas de tiempo
mostraban un hueco de **488 ms**. La métrica de salud del firmware **no ve** esas paradas;
sí las ve `loop_overruns`. Eso vale independientemente de P15: **leer `loop_dt_max_us` solo
no permite descartar una parada del lazo**, y varias conclusiones previas de este registro
se apoyan únicamente en él.

#### Consecuencia para lo ya escrito

Cualquier afirmación de la forma "el control corre a 500 Hz" durante swing-up queda
acotada: **a 500 Hz nominales, con paradas medidas de hasta medio segundo**. Afecta en
particular al análisis del traspaso a LQR, donde 400 ms de `LQR_CATCH_MS` conviven con
paradas del mismo orden.

---

## P16 {#p16}
### El encoder del péndulo pierde cuentas en el régimen del swing-up

**Estado:** `ABIERTO` · **Detectado:** 2026-08-03/04, al ir a rehacer el cero de α antes de
la etapa 5. Detalle completo en `experiments/2026-08-03_alpha_drift/`.

#### La prueba

El ciclo se cierra sobre una referencia **física**: el péndulo colgando. Se pone el cero con
el péndulo quieto (`zp=1`), se perturba, se espera a que la **cuenta cruda** deje de cambiar
durante ~5 s, y se vuelve a leer. Debería dar 0; lo que sobre es deriva.

| régimen | \|α̇\| máx | deriva del colgado | en cuentas |
|---|---|---|---|
| **lento** (el brazo va y viene con el PID) | 223–492 °/s | **0,00 · 0,35 · 0,70 · 0,70°** | 0 · 2 · 4 · 4 |
| **swing-up** | 1661–1717 °/s | **0,00 · −13,36 · +22,50°** | 0 · −76 · +128 |

**El colgado es repetible a 0,7°.** Eso descarta la rival seria —que el péndulo no se
detenga siempre en el mismo lugar por fricción o tironeo del cable—: las derivas de 13 y
22° tras el swing-up no son mecánicas.

#### ⚠ CORRECCIÓN (2026-08-04): la explicación del filtro RC es FALSA

La primera versión de esta entrada atribuía la deriva a que la señal del encoder
(2,4 kHz a 1700 °/s) supera el corte de su filtro RC (10 kΩ × 10 nF → **1,59 kHz**), y
predecía un umbral de pérdida en **1118 °/s**. La cuenta cerraba y **el experimento la
refutó.**

Barriendo la energía del bombeo con el traspaso **desactivado** (`tr=0`), para que el
régimen no cambie a mitad de corrida:

| \|α̇\| máx | deriva | cuentas |
|---|---|---|
| 182 °/s | 0,00° | 0 |
| 902 °/s | −0,18° | −1 |
| 1479 °/s | −0,18° | −1 |
| 1483 °/s | −0,70° | −4 |
| 1527 °/s | −0,70° | −4 |
| 1601 °/s | −0,18° | −1 |
| 1626 °/s | +0,35° | +2 |

**A 1626 °/s —muy por encima del umbral que la teoría del RC predecía— la deriva es de 1 a
4 cuentas**, el mismo piso que la repetibilidad mecánica. Y con el traspaso habilitado, dos
corridas más a 1658 y 1668 °/s dieron **0,00°**.

Total: **8 corridas controladas hasta 1668 °/s sin deriva**. La velocidad, por sí sola, no
la produce.

#### Qué queda entonces

Las dos derivas grandes (−13,36° y +22,50°) siguen sin explicación, pero hay una
correlación que las separa de todo lo demás: **ocurrieron en corridas donde el brazo
terminó FUERA del límite blando** —se midió θ = 111,8° y 115,7° contra un límite de ±95°—,
es decir donde el brazo se estrelló contra el tope mecánico. En las corridas de hoy el
brazo se recentra entre ciclos y termina en 67–77°: no golpea, y no hay deriva.

**Hipótesis viva: golpe mecánico contra el tope**, no pérdida de pulsos por velocidad.
Confirmarla exige golpear el brazo a propósito, que es mecánicamente abusivo; no se hizo.

**Software descartado igual:** el PCNT no tiene filtro de glitches (`pcnt_filter_enable` no
se llama) y la deriva aparece también sin vueltas contabilizadas.

> La lección que sí queda: **la etapa 2.6 del bring-up validó este encoder girándolo A
> MANO** —una vuelta, 2048 cuentas exactas—, que son decenas de °/s. Ahora está validado
> hasta 1668 °/s, y eso sí se puede afirmar.
>
> Y la otra, más cara: **el primer experimento tenía el traspaso como variable oculta.**
> Comparé corridas con y sin LQR creyendo que comparaba velocidades, construí una
> explicación cuantitativa coherente sobre esa confusión, y la escribí. La cuenta del RC
> era correcta; lo que estaba mal era suponer que describía lo que había medido.

#### Alcance real de la reserva, ya acotado

α **no** se degrada por velocidad hasta 1668 °/s, así que `E/E*`, el ángulo de traspaso y
la entrada del LQR **no** quedan bajo sospecha general, como afirmaba la primera versión de
esta entrada. La reserva se acota a: **las corridas en las que el brazo llega al tope
mecánico**, donde se midió deriva de 13–22° en 2 de 3 casos.

Eso sigue tocando a [P4](#p4) y [P12](#p12) —el límite del brazo trunca 5 de 8 swing-ups—,
porque son justamente las corridas donde el brazo golpea. Pero es una reserva mucho más
angosta que "α no es de fiar en régimen energético".

#### Cómo afrontarlo

1. **Confirmar el golpe como causa**: correlacionar la deriva con θ máximo alcanzado en la
   corrida. Los datos ya guardados alcanzan para un primer cruce, sin banco.
2. **Resolver P12** (que el brazo no llegue al tope) es la mitigación real, y ya estaba en
   la lista por otras razones.
3. **No hace falta tocar el filtro RC.** La cuenta que lo señalaba describía un fenómeno
   que no ocurre.

---

## P17 {#p17}
### El contador del péndulo satura a las 16 vueltas y α deja de significar nada

**Estado:** `ABIERTO` · **Detectado:** 2026-08-04, por accidente: una corrida del swing-up
dejó al péndulo girando y el análisis reportó `|α̇| máx = 199.822 °/s`, físicamente
imposible.

#### Lo medido

En esa corrida el péndulo dio **18 vueltas** y la cuenta cambió en **−32.630**. El PCNT
está configurado con `counter_h_lim = 32767` / `counter_l_lim = -32768`
(`esp32_qube.ino:1120`, `:1135`) y **no hay nada que acumule el desbordamiento**: no se
registra ISR, no se llama a `pcnt_event_enable`, y la lectura es un
`pcnt_get_counter_value` directo. Al llegar al límite el contador se reinicia y la posición
acumulada se pierde en silencio.

**32767 / 2048 = 16 vueltas.** Ése es el techo.

#### Por qué importa

- El brazo no lo alcanza nunca: su recorrido es de ±135°.
- **El péndulo gira libre**, así que 16 vueltas es perfectamente alcanzable — se alcanzó
  hoy sin proponérselo, en 12 s de bombeo con el traspaso desactivado.
- Cuando ocurre, α no se degrada: **se vuelve basura**, y con ella `E/E*`, la velocidad
  estimada y cualquier observación que se le pase a un agente. Un episodio largo de RL o un
  bombeo sostenido entran de lleno en este régimen.
- No hay ninguna señal que lo denuncie salvo un valor absurdo: `pend_wraps` sigue contando
  y la lectura sigue "pareciendo" un ángulo.

#### Cómo afrontarlo

1. **Acumular el desbordamiento**: habilitar los eventos de límite del PCNT y llevar un
   acumulador de 32/64 bits, que es el patrón estándar para encoders con PCNT.
2. **Mientras tanto**, `zp=1` reinicia la referencia y sirve como paliativo entre corridas,
   pero no protege a una corrida larga.
3. **Detectarlo desde el cliente**: una `|α̇|` por encima de lo físicamente posible
   (digamos 3000 °/s) es la firma. Vale la pena que la app lo marque en vez de graficarlo
   como si fuera un dato.

---

## P18 {#p18}
### El bombeo no tenía techo de energía: el péndulo podía embalarse sin límite

**Estado:** `RESUELTO` (2026-08-04, v1.58.4). Detectado a partir de [P17](#p17): si el
contador satura a las 16 vueltas, la pregunta anterior es **por qué el péndulo puede llegar
a dar 16 vueltas.**

#### La causa

La ley resonante (`pl=0`, la que corre) hace `pump_ref = alpha_dot * K`. Cuanto más rápido
va el péndulo, más grande la referencia y más se bombea: **es autorreforzante y no tiene
ningún término que la apague.** La ley de Åström-Furuta (`pl=1`) sí lo tiene —el factor
`(E* − E)`, y su comentario lo dice: *"hace que se apague sola al llegar arriba"*— pero
midió peor y no es la que corre.

**Lo único que detenía el bombeo era el traspaso al LQR.** Sin él (`tr=0`, o simplemente
porque no dispara) no hay techo: 18 vueltas en 12 s.

**El anti-spin existente no puede resolverlo**, y entender por qué importa: frena el
**brazo**, y a un péndulo que ya gira sobre un brazo quieto sólo la fricción le saca
energía. El cooldown expira y el bombeo vuelve a inyectar.

#### La corrección

- **Techo de energía** (`swingupEnergyCeiling`, por defecto 1,15): por encima de eso el
  bombeo no inyecta. Coast, no freno — por lo mismo que arriba.
- **Corte por vueltas** (`SWINGUP_MAX_TURNS = 3`): respaldo que aborta a modo 0.
- **`?ec=` y `swing_ceiling_hits` en `/state`**, para poder forzar el camino de código y
  verlo actuar en vez de confiar en que funciona.

#### Verificado

Con `ec=0.35` forzado: **179 cortes** y el péndulo se queda en ~43°. Con el valor de
producción: traspaso normal a `E/E*` = 0,9550, 0 vueltas.

> El techo actúa ~53 veces en un swing-up normal (de ~2400 ticks): `E/E*` supera 1,15
> transitoriamente durante el bombeo sano y el guardián recorta ese exceso **sin impedir el
> traspaso**. No es una alarma.

---

## P19 {#p19}
### `/rl_state` se congela en silencio al salir de los modos 6/7

**Estado:** `ABIERTO` · **Detectado:** 2026-08-04, durante el primer diagnóstico
real-vs-sim.

`updateRlObservation()` **sólo corre en las ramas de los modos 6 y 7**
(`esp32_qube.ino:3586`, `:3844`, `:3899`). Si el firmware sale de esos modos —por
ejemplo el respaldo de `SERVO_HARD_LIMIT_DEG` a 95°, que hace `setMode(0)`—, el endpoint
`/rl_state` **sigue respondiendo 200 con el último valor calculado, para siempre**.

No falla, no avisa, no cambia un flag: **repite**.

#### Lo medido

Tres episodios de 500 pasos con el brazo arrancando en 91–94°. En el primer paso se
cruzó el límite, el firmware cortó a modo 0, y a partir de ahí `theta` quedó
**exactamente constante** en las 1500 muestras (`min = max = inicio = fin`), igual que
`alpha`. La política corrió los 500 pasos de cada episodio contra una observación muerta
y saturó al 95%.

El resultado (`reach = 0%`, `min_dist = 176°`) parecía una brecha sim2real catastrófica
y **no medía nada**.

#### Por qué es grave

Un agente de RL no tiene forma de distinguir "el estado no cambió" de "el estado dejó de
medirse". Un episodio de entrenamiento sobre hardware que entre en este régimen aprende
de datos inventados, y el `reward` que acumula es igual de falso. **Cualquier campaña
sim2real previa que haya cruzado el límite blando está bajo sospecha**, y no hay forma de
saberlo mirando sus CSV salvo por esta firma.

#### Cómo detectarlo desde el cliente, hoy

Un estado que no cambia **ni un conteo de encoder** entre pasos no es un estado medido:
el péndulo cuelga libre y no puede estar perfectamente inmóvil con el motor accionando.
`qube_real.py` debería tratar N lecturas idénticas consecutivas como error.

#### Cómo afrontarlo

1. **Que `/rl_state` diga en qué modo se calculó** y cuántos ms hace que se actualizó.
   Es el mismo patrón que ya se usó en `swing_trans_ms_ago`: un dato latcheado sin su
   marca de tiempo es una trampa.
2. **Que el cliente falle ruidosamente** ante lecturas repetidas o `mode != 6`, en vez de
   seguir alimentando la política.
3. Ver [P12](#p12): mientras el brazo pueda alcanzar el límite blando durante un
   episodio, este camino se sigue ejecutando.

---

## P20 {#p20}
### El lazo RL por HTTP corre a 14,3 Hz, no a los 50 Hz para los que se entrena

**Estado:** `ABIERTO` · **Detectado:** 2026-08-04, medido directamente.

Un paso del modo 6 son **dos** viajes de ida y vuelta —`rl_cmd` para mandar la acción y
`/rl_state` para leer— y tarda **69,9 ms** medidos sobre 100 pasos. El período que exige
`control_freq = 50` es de 20 ms.

**La política corre 3,5× más lento de lo que fue entrenada.**

#### Lo que provoca

Cada acción se sostiene 3,5 veces más de lo esperado, el brazo se pasa de largo y alcanza
la abrazadera de 80°. Ahí la observación queda **fuera de la distribución de
entrenamiento** —en sim el brazo nunca superó 73°— y la política satura, lo que la clava
más contra el tope. Se realimenta.

Medido con `r7_ft_fr100_s0_best`: en el hierro, acción media 0,936 con 93,6% de pasos
saturados y 91,3% del tiempo por encima de 80°. La **misma política en sim**: acción
media 0,111, 1,5% saturados, 0% por encima de 80°, y sostiene 9,43 s.

#### La consecuencia que más duele

**El modo 6 no es un banco de pruebas válido para políticas de 50 Hz**: mide el enlace,
no la política. Eso incluye muy probablemente el *"el deploy real del modelo de 95% dio
hold ~0"* de junio, que fue uno de los dos pilares que justificaron toda la campaña de
adaptación de fricción. No se puede afirmar sin los datos de aquella corrida, pero el
mecanismo estaba disponible y el script era el mismo.

El plan del 2026-06-26 ya había escrito esta rama —*"si el real no sube como la sim, el
problema es latencia… ningún sweep de fricción lo arregla"*— y el diagnóstico nunca se
corrió.

#### Cómo afrontarlo

1. **Modo 7 (inferencia en la ESP32).** Corre a la frecuencia del lazo, sin HTTP en el
   medio. Es el único despliegue que puede evaluar honestamente una política de 50 Hz.
   Requiere `export_rltools` → `policy_weights.h` → verificar → flashear.
2. **Que `rl_cmd` devuelva el estado en la misma respuesta**: de dos viajes a uno, ~35 ms.
   No llega a 50 Hz, pero deja de ser el factor dominante.
3. ESP-NOW o USB directo, si alguna vez hace falta entrenar sobre el hardware.

> **Corolario para el diseño:** entrenar a 50 Hz y desplegar por un enlace de 14 Hz es una
> divergencia silenciosa entre entrenamiento y despliegue, de la misma familia que
> `MOTOR_DIR`. `control_freq` debería verificarse contra la tasa realmente alcanzable
> **antes** de correr una campaña, no después.

---

## P21 {#p21}
### La inferencia en chip (m7) rompe el lazo de 500 Hz

**Estado:** `ABIERTO` · **Detectado:** 2026-08-04, en la primera campaña que midió m7
contra un criterio (`experiments/2026-08-04_m7_chip/`).

#### Lo medido

`loop_dt_max_us` dio **17–23 ms en los diez intentos**, contra los 2000 µs nominales:
paradas de **diez períodos**. Los `overruns` salieron bimodales — {22, 31, 32, 36} contra
{262, 271, 284, 286, 287} — así que se midió el tiempo real pasado en cada rama del
híbrido:

```
corr(segundos en rama política, overruns) = +0,996   (n = 10)
```

Prácticamente lineal: **~10,6 overruns por cada segundo de inferencia**. Los intentos
dominados por el LQR se quedan en 22–32, que es la línea base por conmutación del motor ya
documentada en [P15](#p15) (19–32). **La rama del LQR es barata; la de la política no.**

A 50 Hz de tick, eso significa que **~21% de las inferencias atrasan el lazo más de
10 ms**.

#### Por qué es del orden de 100× de más

La red es 36→64→64→1: unas **6.464 multiplicaciones-acumulaciones**. En un ESP32 a
240 MHz con FPU de un ciclo eso son decenas de microsegundos, no diez milisegundos.
No es el costo natural de la red — hay algo patológico en cómo se ejecuta.

Candidatos, sin verificar: acceso a los pesos `constexpr` en flash sin caché, la función
de activación, o el armado de la observación (`HistoryWrapper` de 4 pasos) en vez de la
inferencia misma.

#### Lo que bloquea

**El sim2real sigue sin medirse.** Van dos caminos de despliegue y los dos fallan por
frecuencia antes de llegar a la pregunta: el modo 6 por el enlace ([P20](#p20)) y el modo
7 por la inferencia. Una política de 50 Hz cuyo lazo se atasca 10 ms en una de cada cinco
decisiones no está corriendo a 50 Hz.

**No se puede concluir que la política no transfiera.** La misma política da 5/5 al ápice
y hold 9,14 s en la sim con el `Dp` medido.

#### Cómo afrontarlo

1. **Medir el tiempo de una inferencia** con un contador alrededor de la llamada. Es el
   dato que decide si el problema es la red, los pesos en flash, o el armado de la
   observación. Sin eso, optimizar es adivinar.
2. Recién entonces: optimizar la inferencia, bajar la frecuencia **y re-entrenar a esa
   frecuencia**, o achicar la red.
3. **No re-exportar ni re-entrenar antes.** Cambiar la política no arregla un problema de
   tiempo de ejecución.

---

## P22 {#p22}
### La referencia angular del péndulo deriva, y nadie la re-establece

**Estado:** `MITIGADO` · **Detectado:** 2026-08-04, midiendo m5 a 500 Hz
(`experiments/2026-08-04_m5_swingup/`).

#### Lo medido

Con el péndulo **en reposo verificado** —la lectura no cambia en 1,2 s— y colgando, que
es donde debe leer 0°:

| rep | α inicial | resultado del swing-up |
|---|---|---|
| 1 | **82,62°** | pico 176,1°, traspasa en 1,3 s |
| 2 | **97,38°** | pico 180,0°, traspasa en 1,3 s |
| 3 | **−264,02°** | **pico 96,0°, bombea 18,1 s sin llegar** |
| 4 | **91,06°** | pico 175,1°, traspasa en 1,6 s |

Como el reposo está verificado, eso no es movimiento: **es la referencia corrida, y
corrida distinto en cada intento**. `pend_wraps` sube en cada intento (4 → 5 → 6 → 6) y
la deriva lo acompaña; el −264° aparece justo después de una vuelta.
`wrapPendulumTurns()` resta vueltas enteras pero el residuo queda.

#### Por qué importa

El firmware usa α para **la energía, las cuatro compuertas de traspaso y el techo de
[P18](#p18)**. Con la referencia corrida, el bombeo trabaja contra un ángulo que no es el
real.

#### La mitigación

`zp=1` (`zeroPendulumHere()`) ya existía y **el protocolo nunca lo usaba**. Llamándolo
tras reposo verificado, antes de cada intento:

| condición (`sp=60`) | picos \|α\| | θ en bombeo | fallos totales |
|---|---|---|---|
| protocolo actual | 107,4–179,6° | 12–68° | 1/4 |
| + reposo tras homing | 96,0–180,0° | 12–67° | 1/4 |
| **+ `zp=1`** | **159,4–179,6°** | **64,1–94,9°** | **0/5** |

**Elimina el modo de fallo catastrófico.** Falta llevarlo al firmware o al protocolo
canónico: hoy vive en el script del experimento.

#### Una hipótesis previa que resultó FALSA, para que no se reponga

La primera lectura fue *"el swing-up no bombea desde cero: remata la energía residual que
el homing deja al golpear los topes"*, apoyada en que los intentos exitosos resuelven en
1,0–1,5 s. **La prueba la refuta:** esperando reposo después del homing, los exitosos
siguen tardando 1,3–1,6 s y el fallo aparece igual (1 de 4 en las dos condiciones). La
energía residual no era la variable.

#### Consecuencia para P12

**La "refutación" de [P12](#p12) del mismo día se midió con la referencia corrida**, o sea
con el bombeo debilitado (θ 12–68°). Con `zp=1` el brazo llega a **94,9°** contra un tope
de 95. P12 vuelve a `ABIERTO` y hay que re-medirlo con el protocolo corregido.

---

## Historial de cambios

| fecha | problema | cambio | verificación |
|---|---|---|---|
| 2026-07-30 | P7 | `pwm_active_frac_inmode` + `time_in_mode_s` | m4 pasó de FAIL a PASS; el modo accionaba el 100% del tiempo vigente |
| 2026-07-30 | P3 | Ventana de homing 250–290 → **262–278** | Rechaza las 3 corridas malas de 250,3–251,7; homing OK con 269,1 |
| 2026-07-30 | P5 | `PEND_INERTIA` 2e-5 → **7,75e-5**, de ω_n medido | Oscilación libre: T=0,46 s ⇒ ω_n=14,34 rad/s vs 28,2 del valor viejo |
| 2026-07-30 | P1 | Compuerta de velocidad en `forcedTransition` (150 °/s) | Los criterios se diversificaron: antes 7/7 `forced`, después aparecen `near+slow` y `peak` |
| 2026-07-30 | P10 | Umbrales `NEAR 155`, `FORCED 165`, `PEAK 25` | Pico de α 120–128° → **146,9–149,4°**; cortes por límite 5/5 → **0/5** |
| 2026-07-30 | P11 | Barrido de `swingupPwmMax` | Se **mantiene en 50**: subirlo reduce la meseta por muerte prematura |
| 2026-07-30 | P2 | Ley de energía (Åström–Furuta) como `?pl=1` | **Peor**: meseta 72,5 vs 142,7 de la resonante. Se deja `pl=0` |
| 2026-07-30 | P3 | `WAIT_QUIET` vigila el brazo; timeout → falla (código 5) | Se conserva: falla ruidosa en vez de cero equivocado en silencio |
| 2026-07-30 | P3 | `HOMING_PWM_SEEK` 55 → **70** (sólo la búsqueda) | **8/8 exitosos**; dispersión del tope + de 20,56° a 0,35° |
| 2026-07-30 | P2 | `swingupPwmMax` 50 → **60** (barrido fino con reposo verificado) | α máx 145,4° → 158,7°; `E/E*` 0,911 → 0,966 |
| 2026-07-31 | P13 | `wrapPendulumTurns()` reemplaza el re-cero en los 4 sitios; `pend_wraps` en `/state` | Prueba discriminante: 44,04° donde lo viejo daba 0°. Deriva del cero tras girar: **98° → 0,18°** |
| 2026-07-31 | P4 | Filtro de velocidad: se DESPLAZA el estado al acotar, ya no se reinicia | El "traspaso perfecto" (vel=0,0) era artefacto: el reinicio caía justo al cruzar la vertical y anulaba la compuerta `verySlow`. Con la compuerta honesta, `tn=175` no dispara (0/4) |
| 2026-07-31 | P12 | `SERVO_HARD_LIMIT_DEG` 95 → 105 y **revertido** | No aportó: α siguió topando en 159–160 y el brazo sólo usó el espacio extra (llegó a 123°, a 12° del tope). Más riesgo sin beneficio |
| 2026-07-31 | P2 | `?tr=` para desactivar el traspaso y poder medir la meseta real | **Reformulado**: el bombeo llega a 179,8° con wrap. No falta energía |
| 2026-07-31 | seguridad | Freno anti-giro de `PWM_MAX` (200) a **120** | Ese escalón de corriente tumbó la placa 2 veces; un freno que provoca reinicio pierde el control entero |
| 2026-07-31 | P9 | `ALPHA_DOT_FILTER_GAIN = 1.52` en los cálculos de energía (el estimador NO se toca: empareja con el sim) | Validado por energía: 1,488 medido vs 1,520 calculado. El criterio `energy` pasa a disparar (2/3) |
| 2026-07-31 | P2 | Re-verificación del barrido con P13 arreglado | Confirmado: sp 50→60 da 145,4° → **157,3°**, `E/E*` 0,912 → **0,961** |
| 2026-07-31 | P6 | Métrica de sobrepaso: normalizar por el escalón, pico tras el primer cruce | Recalculado sobre las trazas del 30: 68,3–76,7% → **38,8–42,0%**. La cifra vieja se conserva como `overshoot_pct_max_legacy` |
| 2026-07-31 | P6 | Kick anti-fricción: umbral 8°→**2°**, piso 12→**30** PWM, ambos por HTTP (`se`/`sk`). `PWM_MIN` eliminado | Compila. **Sin medir en banco**: falta confirmar que baje el error de régimen de 4,8° sin provocar hunting |
| 2026-07-31 | P6 | Feedforward gravitacional movido antes de la zona muerta | Compila. Inocuo hasta ahora porque `servo_ff_pwm = 0`; con `ff` en uso la zona muerta no existía |
| 2026-07-31 | P4 | Causas candidatas H1–H5 documentadas (catch congelado, 400 ms sin control, escalas grado/rad) | **Por lectura de código, sin verificar en banco.** Ningún cambio aplicado todavía |
| 2026-08-03 | P14 | Acotado de `pendPos` en las 4 compuertas de traspaso (v1.57.2) | α de entrega 136–161° → **170,7–179,3°**; `E/E*` 0,86 → **0,994–1,002**; se acaban los `vel = 0,00` exactos |
| 2026-08-03 | P3 | Frenado de aproximación al tope: seek 70 hasta 8° y después 55 (v1.58.0) | 6/6 homings, rango 270,176 en las seis; dispersión de topes de 1–3 cuentas a **0,000°**. `HOMING_PWM_SEEK` sigue en 70: bajarlo es lo que causó P3 |
| 2026-08-03 | P4 | **H1** `lqr_prevAlpha` se actualiza dentro del catch; **H4** se quita el `RAD_TO_DEG` sobrante (v1.58.1) | Supervivencia del LQR **0,3 s → 0,48 / 0,55 / 3,33 s** (n=3 traspasos de 5 ciclos). H1: el freno medía desplazamiento acumulado, no velocidad. H4: `k4_eff` era el doble del declarado — **rehacer la sintonía de `lqr_K4`** |
| 2026-08-03 | P4 | **H2 pasa a ser el cuello** | Las supervivencias de 0,48 y 0,55 s son los 400 ms de `LQR_CATCH_MS` más 80–150 ms de LQR real: el controlador apenas corre. Sin verificar todavía |
| 2026-08-03 | P6 | Primeros datos de banco del kick anti-fricción (`se=2`, `sk=30`), n=6 | `sse` **4,79° → ~2,0°**, pero el sobrepaso **empeoró**: 38,8–42,0% → 46,7–86,6%. El kick compra régimen y paga sobrepaso; barrer `sk` **junto con** `kd` |
| 2026-08-03 | P6 | Etapa 4 completa, medida a 500 Hz con ventana de 14 s (`experiments/2026-08-03_p6_pid/`) | **`kd` 0,15 → 0,45 baja el sobrepaso de 38,9% a 8,2%**, sin hunting y con `sse` +0,20° (dentro de la dispersión). Tendencia monótona en 4 niveles con repeticiones casi idénticas. **Criterio de P6 cumplido por primera vez.** Falta n≥4 y cambiar el default en el `.ino` |
| 2026-08-03 | P6 | El control 4.1 **falla su propio criterio**: con el kick viejo el `sse` da 2,45°, no los 4,8° documentados | La ventana explica la diferencia: 3,5 s daba 4,8°, y hoy el mismo escalón mide 7,7–15,9° con 5 s contra 2,7° con 14 s. **El kick (`se`/`sk`) no mueve la aguja**: 2,45 vs 2,49, con dispersión intra-configuración (1,33–3,56) mayor que la diferencia entre configuraciones |
| 2026-08-03 | P15 | Detectado con la app de escritorio: la tasa de muestreo real cae a 256–330 Hz con el motor bombeando | `dropped=0` en todas las corridas ⇒ no es el enlace, el lazo no produce. `loop_dt_max_us` (17,3 ms) **no ve** un hueco de 488 ms; sí lo ve `loop_overruns` |
| 2026-08-04 | P16 | Prueba de deriva del colgado, lento contra swing-up (`experiments/2026-08-03_alpha_drift/`) | Primera lectura: deriva 0,0–0,7° a ≤492 °/s contra 0–22,5° a ~1700 °/s ⇒ se atribuyó al filtro RC (corte 1,59 kHz contra señal de 2,4 kHz) |
| 2026-08-04 | P16 | **Corrección**: barrido de energía con el traspaso desactivado (`tr=0`) | **La explicación del RC es falsa.** 8 corridas hasta **1668 °/s sin deriva** (1–4 cuentas). El primer experimento tenía el traspaso como **variable oculta**: comparaba con y sin LQR creyendo comparar velocidades. La deriva sólo aparece cuando el brazo termina **fuera del límite blando** (111,8° y 115,7° medidos): hipótesis viva, golpe mecánico |
| 2026-08-04 | P18 | Techo de energía en el bombeo + corte por vueltas (v1.58.4) | La ley resonante era autorreforzante y sólo la detenía el traspaso. Verificado forzando `ec=0.35`: **179 cortes** y el péndulo se queda en 43°. Regresión con el valor de producción: traspaso a `E/E*` 0,9550, 0 vueltas. El anti-spin previo no podía resolverlo: frena el brazo, no el péndulo |
| 2026-08-04 | P17 | Descubierto al reportar `|α̇| = 199.822 °/s` en una corrida de 18 vueltas | **El PCNT satura a las 16 vueltas** (32767/2048) y no hay acumulador de desbordamiento. α no se degrada: se vuelve basura, sin ninguna señal que lo denuncie |
| 2026-08-03 | P15 | Experimento controlado de 6 condiciones × n=3 dentro de la app (`experiments/2026-08-03_p15_loop/`) | **No se reproduce**: 18/18 corridas a 490–500 Hz, cero paradas >20 ms, y la réplica del protocolo original da 500,2 Hz con el péndulo dando 5 vueltas. Queda `NO REPRODUCIBLE`. Sí quedó medido que el motor conmutando cuesta ~2% de las muestras (`m1_osc` 490,4 Hz y 19–32 overruns) y que `sv=0`/`tp=1000` no cambian nada |
| 2026-08-03 | P6 | Escalón +17 → −20 medido sobre la traza a 500 Hz (n=3, ventana de 14 s en la última) | Sobrepaso **36,5 / 37,7 / 38,4 %**, consistente con la base recalculada de 38,8–42,0%. `sse` 2,72° con ventana larga; con 5 s daba 7,7–15,9° — **el `sse` depende de cuánto se espere**, y las comparaciones entre campañas exigen declarar la ventana |
| 2026-08-04 | P4 | **H6 detectada por lectura**: el periodo de gracia del centering nunca existió (`centering_sec` leía un timestamp ya puesto a cero ⇒ uptime de la placa ⇒ rampa llena desde el primer tick) | El comentario del bloque prometía 2 s sin centering + 2 s de rampa. En los hechos, ±25 PWM a ganancia plena sobre `LQR_PWM_MAX`=70 justo cuando el swing-up entrega con el brazo lejos del centro |
| 2026-08-04 | P4 | `?lc=` / `?cg=` + `lqr_alive_ms` (v1.58.5): H2 y H6 configurables **con defaults = comportamiento anterior** | Flashear no cambia nada por sí solo; el A/B sale sin reflashear. Verificado en banco: 4/4 ida y vuelta de parámetros, saturación `9999`→`2000`, los tres campos en `/state` |
| 2026-08-04 | P4 | Barrido 5 condiciones × 4 intercaladas, n=19 con traspaso (`experiments/2026-08-04_p4_catch/`) | **H2 REFUTADA, y en la dirección contraria**: con `cg=0` la supervivencia cae monótona al acortar el catch (0,567 → 0,461 → 0,406 s). El catch también disipa energía; la cuenta del `cosh` medía su costo y no su beneficio. **H6 se sostiene** (+15%/+19% en medianas). **Y `corr(calidad de entrega, supervivencia) ≈ −0,09`: la entrada no explica nada ⇒ el cuello es el controlador (H3/H5).** El outlier de 3,33 s no se reprodujo en 4 intentos |
| 2026-08-04 | sim | **`Dp` medido por spin-down con el brazo sujeto**: 1e-6 → **7,52e-6** (`experiments/2026-08-04_friction_spindown/`) | n=2, λ coincide al 0,4% con amplitudes de 64° y 43° ⇒ amortiguamiento **viscoso**. El barrido de junio (20×–130×) estuvo entre **2,7× y 17,3×** la fricción real, y `Dp_std`=5e-7 hacía que la aleatorización muestreara en [0, 2e-6]: **el valor real quedaba fuera de la distribución entera**. Validación gratis: ω_n con brazo fijo 10,68 analítico vs **10,46 medido** ⇒ la inercia de la sim está bien |
| 2026-08-04 | sim | Hipótesis **descartada**: que `Dr` estuviera igual de mal por el freno del L298N a `PWM=0` | **La sim ya modela ese freno** en el término de back-EMF (`trq = n·km·(V − km·θ̇·n)/Rm` ⇒ 2,1e-4 con V=0, **42× el `Dr` mecánico**). τ del brazo en la sim = 0,47 s, no los 46 s de `Dr` solo. Medir `Dr` es una corrección del 2%: **no reponer esta hipótesis** |
| 2026-08-04 | P19/P20 | Primer `diagnose_real_vs_sim.py` de la historia del proyecto (`experiments/2026-08-04_sim2real/`) | **El cuello del sim2real es el enlace, no la física.** Un paso del modo 6 tarda 69,9 ms (dos viajes) ⇒ **14,3 Hz contra los 50 de entrenamiento**. La misma política: en sim acción media 0,111 y hold 9,43 s; en el hierro acción media 0,936, 93,6% saturada y 91,3% del tiempo contra la abrazadera de 80° |
| 2026-08-04 | P19 | Descubierto que `/rl_state` **repite el último valor** al salir de los modos 6/7 en vez de fallar | Firma: `theta` exactamente constante en 1500 muestras. Un brazo trabado igual daría ruido de encoder, y el péndulo colgando no puede estar inmóvil con el motor al 95%. Convirtió un episodio muerto en un `reach=0%` que parecía brecha sim2real |
| 2026-08-04 | infra | `make_real_env()` no exponía `homing_every`/`homing_on_start`: **por la factory el homing era inalcanzable** | Los episodios arrancaban donde hubiera quedado la corrida anterior — el 2026-08-04, en 91–94°, a 1° del corte duro. Corregido en la factory y `--homing-every` con default 1 en el script. Con homing, `min_dist` pasó de 176° a **68–89°** |
| 2026-08-04 | P6 | Regresión de m2 sobre v1.58.5 (n=3 por nivel), con `kd=0,15` como control | **`kd=0,45` cumple con margen: 1,2% de sobrepaso** (0,0 · 1,2 · 3,0), 0 hunting, 500 Hz sin pérdidas. P6 pasa a `RESUELTO`. **Y se detectó deriva del banco**: contra el 3 de agosto el sobrepaso bajó en los DOS niveles (39,3→34,7 y 8,4→1,2) y el `sse` subió en los dos (≈2,7→3,36 y 3,4→4,01). Firma de más fricción; el control con `kd=0,15` es lo que descarta que sea `kd` o el firmware. **Las comparaciones absolutas de `sse` contra campañas de otro día no son válidas sin re-medir el control** |
