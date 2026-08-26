# Registro de problemas — QUBE Servo

Bitácora viva de defectos conocidos, su estado, y **cómo afrontarlos si siguen
abiertos**. Iniciada 2026-07-30 tras la campaña de validación exhaustiva.

Estados: `ABIERTO` · `EN CURSO` · `RESUELTO` · `MITIGADO` · `NO ES DEFECTO`

| id | problema | severidad | estado |
|---|---|---|---|
| [P1](#p1) | `forcedTransition` anula los otros 3 criterios de swing-up | alta | `RESUELTO` |
| [P2](#p2) | ~~El swing-up no alcanza la energía~~ → **sobra energía; el problema es la captura** | alta | `REFORMULADO` |
| [P3](#p3) | Homing se cala en un punto duro y acepta el cero corrido | alta | `RESUELTO` |
| [P4](#p4) | El LQR no sostiene ni con una entrega perfecta (α=178,4°, α̇=0, E/E*=1,000) | **alta** | `ABIERTO` — bloqueante |
| [P5](#p5) | Magnitud de α̇ dudosa → `E/E*` no confiable | alta | `RESUELTO` |
| [P6](#p6) | ~~m2 PID: sobrepaso 68–77%~~ → **39–42%**; la cifra estaba inflada por la métrica | baja | `EN CURSO` |
| [P7](#p7) | `sample_hz` inflado en modos multi-tramo (instrumentación) | baja | `RESUELTO` |
| [P8](#p8) | Homing: el brazo no siempre queda centrado | baja | `MITIGADO` |
| [P9](#p9) | El estimador de α̇ tiene ganancia 1,52, no 1 | media | `RESUELTO` |
| [P10](#p10) | Umbrales de traspaso cortaban el bombeo a mitad de subida | alta | `RESUELTO` |
| [P11](#p11) | El bombeo satura contra `swingupPwmMax`, anulando `ke_gain` | alta | `RESUELTO` (no era el cuello) |
| [P13](#p13) | `resetPendulumOffsetHere()` redefine el cero del péndulo en silencio | media | `RESUELTO` |
| [P12](#p12) | El límite del brazo trunca 5 de 8 swing-ups antes de llegar arriba | alta | `ABIERTO` — bloqueante |

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

**Orden sugerido:** H1/H4 primero (son los que hacen que las mediciones signifiquen
algo), después H2/H3, que cambian comportamiento. No mezclar el arreglo del catch con
un cambio de ganancias en la misma tanda.

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
