# Registro de problemas — QUBE Servo

Bitácora viva de defectos conocidos, su estado, y **cómo afrontarlos si siguen
abiertos**. Iniciada 2026-07-30 tras la campaña de validación exhaustiva.

Estados: `ABIERTO` · `EN CURSO` · `RESUELTO` · `MITIGADO` · `NO ES DEFECTO` ·
`ACOTADO` · `REFORMULADO` · `NO REPRODUCIBLE` · `DEPENDE DEL ESTADO`

> **Invariante de este archivo:** la fila de la tabla y la línea `**Estado:**` de la
> sección tienen que decir lo mismo. El 2026-08-06 se encontraron **seis** desacuerdos
> (P5, P6, P15, P16, P17, P22) más dos secciones sin línea de estado (P4, P12): en todos,
> el cuerpo de la sección ya había llegado a la conclusión de la tabla y la línea del
> encabezado nunca se actualizó. Un lector que entrara por el ancla —que es como se entra
> desde el código y desde la tesis— leía el estado viejo. Es el mismo defecto que
> `?bt=` y `?ke=`, aplicado a la documentación: una superficie publicada que dejó de
> corresponderse con lo que hay detrás. **Al cerrar o mover un problema, tocar los dos
> lugares.**

| id | problema | severidad | estado |
|---|---|---|---|
| [P1](#p1) | `forcedTransition` anula los otros 3 criterios de swing-up | alta | `RESUELTO` |
| [P2](#p2) | ~~El swing-up no alcanza la energía~~ → **sobra energía; el problema es la captura** | alta | `REFORMULADO` |
| [P3](#p3) | Homing se cala en un punto duro y acepta el cero corrido | alta | `RESUELTO` |
| [P4](#p4) | El LQR pierde el péndulo en **~90 ms incluso con entrega perfecta**, y **es un relé a cualquier autoridad**: saturado el 98% del tiempo con el techo al doble | **alta** | `EN CURSO` — 55 corridas el 2026-08-05. **H1, H2, H7 y H3-como-causa descartadas** con medición. `tn=162` mejora la entrega; `lpm` no hace nada. **Queda H5, las ganancias**: el CARE pide otra escala entera (K2 148,7 contra 22). **Es el bloqueante del proyecto** |
| [P5](#p5) | Magnitud de α̇ dudosa → `E/E*` no confiable | alta | `RESUELTO` |
| [P6](#p6) | ~~m2 PID: sobrepaso 68–77%~~ → **39–42%**; la cifra estaba inflada por la métrica | baja | `RESUELTO` (2026-08-04) — `kd=0,45` es el default desde v1.58.0 y se re-verificó en v1.58.5: **1,2%** de sobrepaso, 0 hunting |
| [P7](#p7) | `sample_hz` inflado en modos multi-tramo (instrumentación) | baja | `RESUELTO` |
| [P8](#p8) | Homing: el brazo no siempre queda centrado | baja | `MITIGADO` |
| [P9](#p9) | El estimador de α̇ tiene ganancia 1,52, no 1 | media | `RESUELTO` |
| [P10](#p10) | Umbrales de traspaso cortaban el bombeo a mitad de subida | alta | `RESUELTO` |
| [P11](#p11) | El bombeo satura contra `swingupPwmMax`, anulando `ke_gain` | alta | `RESUELTO` (no era el cuello) |
| [P13](#p13) | `resetPendulumOffsetHere()` redefine el cero del péndulo en silencio | media | `RESUELTO` |
| [P12](#p12) | El límite del brazo trunca swing-ups **cuando el banco lleva corridas encima** | alta | `DEPENDE DEL ESTADO` (2026-08-05) — con el banco fresco **no es defecto** (n=10: θ 49,2–80,1°, 0/10 tocan el tope). Tras ~60 corridas en un día: θ mediana **94,7°**, 3/5 tocan y el swing-up baja a 2/5 traspasos. La conclusión del 2026-08-04 vale, pero **sólo para banco fresco** |
| [P22](#p22) | **La referencia angular del péndulo deriva y nadie la re-establece**: colgando y quieto leía 82/97/91 y una vez −264°, debiendo leer 0 | **alta** | `RESUELTO` (2026-08-04, v1.58.8) — el modo 5 exige quietud y re-establece el cero antes de bombear; 0/5 fallos y 5/5 con `E/E*` en rango |
| [P14](#p14) | Las cuatro compuertas de traspaso comparaban un ángulo **sin acotar** | **alta** | `RESUELTO` (2026-08-03, v1.57.2) |
| [P15](#p15) | Con el motor bombeando, el lazo produce **256–330 Hz**, no 500, con paradas de hasta 0,49 s | **alta** | `NO REPRODUCIBLE` (2026-08-03) — 18/18 corridas limpias tras reiniciar |
| [P16](#p16) | ~~El encoder pierde cuentas por velocidad (filtro RC)~~ → **explicación refutada**; la deriva de α sólo aparece cuando el brazo golpea el tope | media | `ACOTADO` (2026-08-04) — sin deriva en 8 corridas hasta 1668 °/s |
| [P17](#p17) | **El contador del péndulo satura a las 16 vueltas** y α se vuelve basura, sin ninguna señal que lo denuncie | **alta** | `MITIGADO` (v1.58.4) — el bombeo ya no puede embalarse; falta el acumulador de desbordamiento |
| [P18](#p18) | **El bombeo no tenía techo de energía**: sin traspaso, el péndulo se embala sin límite | **alta** | `RESUELTO` (2026-08-04, v1.58.4) |
| [P19](#p19) | **`/rl_state` se congela en silencio** al salir de los modos 6/7: repite el último valor en vez de fallar | **alta** | `RESUELTO` (2026-08-06, v1.61.0) — `seq`/`age`/`md` sellan cada observación y el cliente aborta el episodio en vez de reusar el último estado. Reproducido y detectado en placa |
| [P20](#p20) | **El lazo RL por HTTP corre a 26,1 Hz**, no a los 50 Hz para los que se entrena. El modo 6 no puede evaluar una política | **alta** | `MITIGADO` (2026-08-06) — la frecuencia alcanzada se mide por episodio y se compara con la pedida; por debajo del 80 % aborta. **No acelera el enlace**: lo hace imposible de ignorar. Falta re-medir la tasa real con `/rl_step` |
| [P21](#p21) | **La inferencia en chip (m7) rompe el lazo de 500 Hz**: ~21% de los ticks atrasan >10 ms, unas 100× más lento de lo esperable | **alta** | `ABIERTO` |
| [P24](#p24) | **El pivote del péndulo desarrolló fricción seca dominante: soltado desde 19° baja al reposo sin oscilar, y se queda quieto a 4,75° durante 4,25 s** | **alta** | `ABIERTO` (2026-08-05) — par seco **13,4×** el viscoso; predice detención en <1 ciclo, que es lo observado. Encoder descartado por barrido manual. **Es mecánico**, y probablemente la causa de fondo de [P4](#p4) y de la degradación por uso |
| [P25](#p25) | **Un intento de balanceo fallido terminaba el trabajo**: el m5→m4 que no engancha deriva el brazo al tope y `safeStop()` lo manda a modo 0, con el banco quieto hasta que el operador vuelve a pedir m5 a mano | media | `EN CURSO` (2026-08-21) — corregido en v1.63.0: el intento fallido se detecta antes del tope, el brazo vuelve al centro y se re-bombea, hasta 3 veces. **Compila; no se ha corrido en el hierro**, así que no pasa a `RESUELTO` |
| [P26](#p26) | **Los cuatro términos de «empujar al centro» del firmware no multiplican por `MOTOR_DIR`**, y el resto de cada lazo sí: con `MOTOR_DIR = −1` empujan **hacia el tope**, no hacia el centro | **alta** | `ABIERTO` (2026-08-21) — **CONFIRMADO en banco el mismo día**: `homing_pwm_sign = −1`. La corrección está pendiente a propósito (cambia m4/m5/m7 a la vez y es candidato a causa de fondo de [P4](#p4)) |
| [P27](#p27) | **La `f_n` del péndulo depende de si el brazo está suelto** (2,13 Hz libre contra 1,41 Hz retenido, cociente 0,665): un número de `f_n` sin la condición de contorno no significa nada, y por ahí se cuela la contradicción 1,70 / 2,28 Hz | media | `ABIERTO` (2026-08-21) — brazo libre **2,134 Hz** (32 medios ciclos) contra **1,700 Hz** con brazo fijo: cociente 1,255. **De paso queda refutada** la idea de que el swing-up bombea fuera de resonancia: sigue la frecuencia propia dentro del 0–3 % entre 40° y 145° |
| [P28](#p28) | **Cada petición a `/state` o `/cmd` le cuesta al lazo de 500 Hz una resincronización** (>10 ms de control perdido): 0,97 overruns por petición contra 0,00 en `/rl_state` y `/daq` | **alta** | `ABIERTO` (2026-08-21) — medido y acotado, **causa sin identificar**. Descartadas con medición: el tamaño de la respuesta y la construcción del `String`. Toca a [P20](#p20) y **contamina toda campaña que sondee `/state` mientras mide** |
| [P23](#p23) | **`?ke=` es API publicada que el propio lazo pisa**: la rama adaptativa lo sobrescribe con `KE_GAIN_BASE` en el primer tick con \|α\| > 5°. Tercero después de `bt` y F1 | media | `RESUELTO` (2026-08-06) — `ke_gain_override` separa el mando manual de la rama adaptativa, sobrevive a `setMode(5)`, y `ke_gain`/`ke_override` se publican en `/state`. Sigue siendo cierto que **no** es lo que limita la energía del bombeo: eso es [P11](#p11) |

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

**Estado:** `REFORMULADO` (2026-07-31, reserva levantada el 2026-08-05). El título de
arriba quedó **invertido**: el bombeo *sí* alcanza la energía. Lectura vigente con la
referencia de α sana (n=10): **10/10 traspasan** y `E/E*` cae en 0,955–1,001, o sea que
alcanza y alcanza justo. Lo que no se cumple es entregar por encima de 165° — 5/10 —, y
eso está limitado por par y no por sintonía: el bombeo tiene el PWM en su techo el 92,5%
del tiempo (ver [P11](#p11)). Las salidas siguen siendo tres: control por par, menos
fricción (ver [P24](#p24)), o aceptar el umbral de 155 que el firmware ya usa.

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

> **Reserva levantada (2026-08-05).** La campaña n=10 de
> `experiments/2026-08-04_m5_swingup/` la resuelve sin necesidad de repetir el `tr=0`:
> con el traspaso **armado** y la referencia de α sana, **10 de 10 traspasan** con `E/E*`
> en 0,955–1,001 y picos de 156,4° a 179,8°. La energía llega a la vertical **dentro de
> la ventana de captura**, que era justo lo que las 4 corridas de `tn=175` no mostraban.
>
> Lo que sí queda en pie de este bloque es el techo: medido el 2026-08-05, el bombeo
> tiene el PWM saturado el **92,5%** del tiempo (ver [P11](#p11)), así que no hay margen
> de sintonía para pedirle más. "Sobra energía" es demasiado generoso — la lectura exacta
> es que **alcanza, y justo**: 5 de 10 entregas quedan por debajo de 165°.

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

**Severidad:** **alta** — el "puede no ser defecto" de la primera redacción quedó
descartado: ~90 corridas medidas y el mejor resultado absoluto es **114 ms**. Es el
bloqueante del proyecto.

**Estado:** `EN CURSO` (2026-08-05). H1, H2, H7 y H3-como-causa **descartadas** con
medición y criterio pre-registrado. `tn=162` mejora la entrega de forma reproducible;
`lpm` no cambia nada. **Queda H5, las ganancias** — el CARE pide otra escala entera
(K2 148,7 contra los 22 que corren). Ver también [P24](#p24): con fricción seca 13,4×
el par viscoso en la articulación a estabilizar, el diseño por CARE no describe esta
planta, y eso da una explicación única a por qué cinco hipótesis sobre el controlador
cayeron una tras otra.

> **H5 no está sin datos: está sin datos *útiles*.** `k2_sweep.py` sí corrió sus 12
> puntos (K2 = 8 · 22 · 60 · 148, n=3), y quedaron guardados en
> `experiments/2026-08-05_p4_gains/data/k2_sweep.json`. Pero **10 de 12 no traspasaron**
> (`handed_off: false`): el swing-up dejó de entregar a mitad del barrido, que es la
> firma de [P24](#p24). El barrido no midió K2, midió la degradación del banco.
>
> De los dos puntos que sí entregaron, uno es el **mejor resultado de las ~90 corridas
> de la jornada**: K2 = 60, `t_loss` = **114 ms**, con error de entrega de 2,6°. El otro
> (K2 = 8) duró 58 ms. El default que corre es K2 = 22. Es **n=1 por nivel** y no
> sostiene ninguna conclusión — pero apunta en la dirección de H5 y hasta ahora no
> estaba anotado en ninguna parte. Repetir el barrido con banco válido es la prueba
> pendiente, no escribir el script.

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

> **Cuantificado (2026-08-05).** `compute_lqr_gain()` con su `Q = diag([1, 10, 1, 5])`,
> `R = 1`, convertido a las unidades del firmware (grados, grados/s, salida en cuentas de
> PWM con `u·PWM_MAX`, `PWM_MAX = 200` — la escala de salida es una suposición razonable,
> no un dato):
>
> | | diseñada | firmware | razón |
> |---|---|---|---|
> | K1 (θ) | −3,49 | 2,0 | −0,57× |
> | K2 (α) | 148,74 | 22,0 (55 very-near) | 0,15× |
> | K3 (θ̇) | −4,07 | 1,5 | −0,37× |
> | K4 (α̇) | 12,17 | 9,0 | 0,74× |
>
> **El diseño pide K1 y K3 negativas**, que es H7 visto desde el otro lado. Y pide 6,8× más
> ganancia de α — pero con la salida saturada el 69% del tiempo eso sólo satura más, así
> que **K2 no se toca** hasta resolver la saturación.

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

**H7 (2026-08-05, POR LECTURA — no medida). El amortiguamiento del brazo entraría con el
signo cambiado.** La ley (`:3592`) es `u = -(K1·θ + K2·α + K3·velTheta + K4·velAlpha)`, o
sea la forma `u = −K·x` del CARE. Pero las dos velocidades se calculan **negadas**
(`:3553-3554`, `rawVelTheta = -(theta - prev)/dt`).

- Para α **se cancela**: `alpha` ya viene invertida respecto de `alpha_raw` (`:3546`), así
  que `−α̇_raw = +α̇` y el término de K4 es consistente con el de K2.
- Para θ **no hay nada que lo cancele**: `theta` entra sin invertir y `velTheta_ctrl` es
  −θ̇. Con `K3 = +1,5` el firmware estaría **anti-amortiguando** el brazo.

Encaja con las 15/15 divergencias de abajo, y se llega a la misma conclusión por un segundo
camino independiente: las ganancias diseñadas del CARE piden **K1 y K3 negativas** (ver H5).
Sigue siendo lectura de código — H1, H2, H4 y H6 se dedujeron igual y H2 resultó refutada.
`lqr3` es configurable por HTTP y sin acotar, así que se mide sin reflashear.

**Orden sugerido:** H1/H4 primero (son los que hacen que las mediciones signifiquen
algo), después H2/H3, que cambian comportamiento. No mezclar el arreglo del catch con
un cambio de ganancias en la misma tanda.

### H3 medido a 500 Hz, y el péndulo se pierde en menos de 90 ms (2026-08-05)

Sin banco nuevo: **las 10 trazas del m5 de `experiments/2026-08-04_m5_swingup/` contienen el
modo 4 completo a 500 Hz**, porque el DAQ siguió grabando después del traspaso. Es mucho
mejor dato que todas las campañas de m4 anteriores, que muestrearon por HTTP a ~14 Hz.

**H3 — CONFIRMADA.** Saturación de la salida en modo 4, contra el techo efectivo por muestra
(`int(LQR_PWM_MAX/(1+(|θ|/200)²))`, la misma corrección que hizo falta en [P11](#p11)),
descartando los 400 ms del catch (200 muestras, donde el tope es 25 y no 70):

| | mín | mediana | máx |
|---|---|---|---|
| fracción del modo 4 con la salida en su techo | 43,6% | **70,4%** | 100% |

n = 8 corridas con modo 4 más largo que el catch. Coincide con el 68,8% que daban las
trazas de 14 Hz, lo que da confianza en las dos. **Con la salida clavada, las cuatro
ganancias no pueden influir: lo que corre es un relé.** La prueba ingenua contra
`LQR_PWM_MAX` da 0,0% en las ocho, por el mismo motivo que en el bombeo.

**El orden de los sucesos, que es lo que faltaba.** Desde la entrada al modo 4 (t=0 en el
traspaso), midiendo cuándo el péndulo sale de ±20° de la vertical y cuándo el brazo pasa de
60°:

| | |
|---|---|
| el péndulo sale de ±20° | **0 – 86 ms** (10/10) |
| el brazo llega a 60° | 0 – 1272 ms, mediana ~600 ms |
| quién se va primero | **el péndulo, en 9 de 10** |
| θ final | ±94,0 – ±94,8 en 8/8, contra un tope de 95 |

**El péndulo se pierde en menos de 90 ms desde el traspaso.** El brazo topando es la
consecuencia —el controlador persiguiendo un péndulo que ya se cayó—, no la causa.

> **Corrección de una lectura anterior del mismo día.** Se había escrito lo contrario ("el
> péndulo no se cae, el brazo se va"), a partir de las 15 corridas de
> `2026-08-04_p4_catch/`. Ese análisis miró el **estado en la última muestra** en vez de la
> secuencia, sobre trazas de 14 Hz con 5 a 20 muestras por intento: no distingue "el péndulo
> aguanta" de "ya se cayó y la última muestra cayó antes". El caso de `lc0_cg1_rep03`, con α
> en 177–181° durante 0,8 s, es real pero es una corrida y no el patrón. Vale la pena
> dejarlo anotado: es el mismo error de forma que P6 y que P11 —conclusión sacada de la
> instrumentación y no del equipo—, y esta vez lo cometió el análisis, no el firmware.

Lo que sí se sostiene de aquella lectura: el brazo **siempre** termina contra el tope
(±94,0–94,8 en 8/8).

### El criterio de entrega del m5 predice exactamente si el LQR arranca con algo utilizable

En **5 de las 10** corridas `t_loss = 0`: el péndulo ya estaba fuera de ±20° en el instante
del traspaso. Y cuáles son esas cinco no es casualidad — son **exactamente** las cinco que
fallan el criterio 1 del m5:

| \|α\| en la entrega | crit. 1 (≥165°) | `t_loss` |
|---|---|---|
| 178,9 · 173,5 · 173,3 · 169,6 · 165,6 | PASS | 74 · 86 · 72 · 38 · 36 ms |
| 158,4 · 158,4 · 158,2 · 155,9 · 155,4 | FAIL | **0** en las cinco |

**Concordancia 10/10.** El umbral de 165° que se fijó *antes* de medir —y que se venía
describiendo como "más estricto que el del propio firmware"— parecía ser **la frontera
exacta en la que el LQR recibe un péndulo dentro de la banda**.

> **⚠ Corregido el mismo día por la campaña n=15.** No es un escalón en 165: la relación es
> **continua**. Con entregas que cubren 3,5–21,8° de error, `t_loss` cae 3,52 ms por grado y
> llega a cero recién en err ≈ 21,8° (α ≈ 158°). Un intento con err = 17,2° todavía dio 14 ms.
> La concordancia perfecta era artefacto de una muestra **partida en dos grupos** (155–158 y
> 165–179) sin nada en el medio: una rampa muestreada sólo en los extremos parece un
> escalón. Lo que sigue en pie está abajo.

Dos consecuencias:

1. **`SWINGUP_TRANS_NEAR = 155` es demasiado permisivo:** entrega en un estado que el LQR no
   puede usar, y la mitad de los intentos se pierden ahí. Subir `?tn=` es candidato barato y
   configurable por HTTP. Aviso: el 2026-07-31 `tn=165/170/175` **no disparaban nunca**,
   pero eso fue **antes de P22** y hoy 5 de 10 entregas ya superan 165 solas.
2. **El r ≈ −0,09 entre calidad de entrega y supervivencia queda bajo sospecha.** Se calculó
   contra la supervivencia *total*, que suma intentos muertos por causas distintas. Contra
   el arranque del LQR la relación no es débil: es perfecta en n=10.

Esto también ata [P4](#p4) con el criterio 1 del m5, que quedó en FAIL (5/10) el 2026-08-04:
no son dos problemas separados, es el mismo umbral visto desde los dos lados.

Consecuencia práctica para H5: **no subir K2 en esta etapa.** El diseño pide 6,8× más
ganancia de α que el firmware, pero con la salida ya saturada eso sólo satura más.

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

**Estado:** `RESUELTO` — el experimento de oscilación libre se corrió y cerró en
[P9](#p9): el estimador tiene ganancia **1,52**, no 1. La escala de α̇ ya no está en
duda; lo que sigue sin identificar es `PEND_MASS`/`PEND_LENGTH` (ver P2).

---

## P6 {#p6}
### m2 PID: sobrepaso 68–77% → **39–42% real**; y un kick anti-fricción inútil

**Severidad:** baja — converge, sin cortes. No bloquea nada del RL.

**Estado:** `RESUELTO` (2026-08-04). `kd=0,45` es el default desde v1.58.0 y se
re-verificó sobre v1.58.5 con n=3: **1,2%** de sobrepaso, 0 hunting, 500 Hz sin
pérdidas. Los "pendiente: barrer kd" y "sin medir en banco" que aparecen más abajo
son del texto original y **ya están cumplidos** — se dejan como registro de cómo se
llegó, no como trabajo por hacer. Lo único que sigue sin barrer es `kp`.

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

#### Caracterizado el 2026-08-06: es un ciclo límite, no un residuo de inercia

La explicación de arriba —swing residual back-driveando el brazo— **no describe lo que
pasa hoy**. Muestreando la posición durante `GOTO_CENTER`, el brazo oscila **de tope a
tope** (−210 a +48 raw, el recorrido entero) a PWM ±70, sin asentarse en 10 s:

```
   t      raw_pos    error    pwm
  14.5    -116.54     34.37    -70
  14.7     -34.80    -47.37     70     <- cruzó el centro
  14.9      46.58   -128.76     70
  15.4    -189.67    107.49    -70
```

Dentro de `HOMING_CENTER_SLOW_DEG` (30°) el techo baja a `HOMING_PWM_MIN` (45), que está
documentado como *"piso para vencer fricción estática"*. **Usar el piso de arranque como
techo de aproximación**, con `HOMING_CENTER_TOL_DEG = 5` y esta inercia, es un bang-bang:
el brazo no puede detenerse dentro de la ventana.

**Consecuencia que hubo que arreglar (v1.60.0):** hasta esta fecha `homing_ok` sólo se
fijaba **al terminar de centrar**, así que un estacionamiento fallido tiraba abajo una
calibración válida (recorrido 270,35°, ambos topes correctos) y devolvía `FAIL code=4`.
Con la compuerta de homing de la Etapa 3 eso dejaba el banco **inutilizable**. Ahora el
cero se fija al validar el recorrido —el cuadro de coordenadas queda determinado ahí— y
`homing_centered` / `homing_center_err` reportan el estacionamiento por separado.

Medido tras el cambio: `homing_ok=true`, `homing_centered=false`, error −39,4°, y **`m2`
llevó el brazo a 1,23° en 1,5 s**. La mitigación funciona; lo que faltaba era no dejar que
el estacionamiento invalidara la calibración.

**Pendiente:** re-sintonizar el centrado con `homing_center_err` ya instrumentado. **No se
tocó a ciegas** — el bang-bang está medido, la sintonía necesita su propia sesión.

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

> **Confirmado por medición (2026-08-05).** Hasta hoy la saturación se había estimado
> comparando `|pwm|` contra `swingupPwmMax`, que es la prueba equivocada: el DAQ registra
> `lastPwmCmd`, o sea el valor **después** de la atenuación por posición de `setMotor`
> (`:1447-1451`, factor `1/(1+(|θ|/200)²)`), así que el tope exacto sólo se alcanzaría con
> el brazo en θ = 0 y la cuenta ingenua da **0,0%** en cualquier corrida. Recalculando el
> techo por muestra con el θ de la traza, sobre las diez corridas de
> `experiments/2026-08-04_m5_swingup/` (v1.58.8, `sp` = 60): **saturado 86,7–94,1%, mediana
> 92,5%**. El script es `m5_pwm_sat.py` y imprime las dos cifras lado a lado.
>
> La atenuación por posición no es el cuello: el techo efectivo medio es 58,1–59,1 sobre
> 60, porque el brazo trabaja centrado (centro de oscilación −6,8 a +16,0°).

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

**Severidad:** alta.

**Estado:** `DEPENDE DEL ESTADO` (2026-08-05). Ya **no** es el cuello de botella del
swing-up, como decía esta línea: con el banco fresco no es defecto (n=10, θ 49,2–80,1°,
0/10 tocan el tope). Tras ~60 corridas en un mismo día sí lo es (θ mediana 94,7°, 3/5
tocan, y el swing-up baja a 2/5 traspasos). O sea que P12 mide el estado del banco más
que el diseño del bombeo — ver [P24](#p24).

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

**Estado:** `RESUELTO` — `wrapPendulumTurns()` resta vueltas enteras en vez de
redefinir el cero. El residuo que ese arreglo dejaba es lo que después se registró como
[P22](#p22), y se cerró en v1.58.8.

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

**Estado:** `NO REPRODUCIBLE` (2026-08-03) · **Detectado:** 2026-08-03, primera sesión de
la app de escritorio (`docs/mine/APP_ESCRITORIO.md`). 18/18 corridas limpias tras
reiniciar; ver *Por qué queda `NO REPRODUCIBLE` y no `RESUELTO`* más abajo.

> **Reabierto parcialmente el 2026-08-06.** La firma volvió a aparecer —una pausa de
> **239,4 ms** con `dropped = 0`— pero **sin motor**, sondeando `/state` a 2 Hz durante
> una captura DAQ. Eso no reproduce P15 (que era con motor), y además debilita la
> atribución al motor que se hace más abajo: aquel experimento se corrió dentro de la
> GUI, que sondea. Hace falta un 2×2 de motor × sondeo antes de afirmar cuál de los dos
> cuesta qué. Ver `CHANGELOG.md`, entrada `app-0.2.0`.

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

**Estado:** `ACOTADO` (2026-08-04) — sin deriva en 8 corridas hasta 1668 °/s. La
explicación por filtro RC quedó **refutada**; la reserva se acota a las corridas en que
el brazo golpea el tope mecánico, donde se midió deriva de 13–22° en 2 de 3 casos. La
hipótesis del golpe **no está confirmada**: confirmarla exige golpear el brazo a
propósito. · **Detectado:** 2026-08-03/04, al ir a rehacer el cero de α antes de
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

**Estado:** `MITIGADO` (v1.58.4) — el techo de energía y el corte por vueltas impiden que
el bombeo se embale hasta las 16 vueltas, que era la única vía conocida de alcanzarlas.
**El defecto de raíz sigue en pie:** falta el acumulador de desbordamiento del PCNT
(punto 1 de *Cómo afrontarlo*), así que una corrida larga de RL todavía puede llegar.
· **Detectado:** 2026-08-04, por accidente: una corrida del swing-up
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

**Estado:** `RESUELTO` (2026-08-06, v1.61.0). El firmware sella cada recálculo de la
observación con `seq` (monótono), `age` (ms) y `md` (modo), y `qube_real.py` rechaza una
lectura repetida, vieja o de otro modo. El `except` que conservaba el último estado ahora
**termina el episodio**: se prefiere uno que muere ruidosamente a uno que miente.
`RL_PROTO_VERSION` sube a 4 para que un firmware viejo no pueda usarse en una campaña.

**Reproducido y detectado en placa** (`experiments/2026-08-06_etapa5_p19/`): en modo 6 la
secuencia avanza 47 veces por segundo; al volver a modo 0 se congela y `age` sube a
2395 ms, muy por encima del límite de 200. Antes de esto el cliente habría seguido leyendo
los mismos cuatro números indefinidamente.

**Lo que NO cambia:** todas las campañas de m6 anteriores siguen acotadas por lo que no se
podía descartar. El arreglo protege lo que venga, no rehabilita lo medido.

· **Detectado:** 2026-08-04, durante el primer diagnóstico
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

**Estado:** `MITIGADO` (2026-08-06, v1.61.0). `reset()` mide la frecuencia **alcanzada**
del episodio anterior y la compara con `control_freq`: por debajo del 80 % aborta
(`strict_freq=True`, el default) o avisa. **Esto no acelera el enlace** —sigue siendo el
cuello— pero lo vuelve imposible de ignorar: se entrenó y se evaluó a "50 Hz" sobre un
enlace de 26,1 Hz durante campañas enteras sin que nada lo dijera.

**Pendiente:** re-medir la tasa real del round-trip con `/rl_step`. La cifra de 26,1 Hz es
anterior a esta sesión.

· **Detectado:** 2026-08-04, medido directamente.

> ### ⚠ Corrección (misma sesión)
>
> La primera medición cronometró **`rl_cmd` + `rl_state`**, que son dos viajes de ida y
> vuelta. **Pero `QubeRealEnv.step()` no usa ese camino**: desde el protocolo v3 usa
> **`/rl_step`**, que fija la acción y devuelve el estado en un solo round-trip.
>
> | camino | latencia | tasa |
> |---|---|---|
> | `rl_cmd` + `rl_state` (lo medido primero) | 75,8 ms | 13,2 Hz |
> | **`/rl_step` (el que corre de verdad)** | **38,3 ms** | **26,1 Hz** |
>
> El defecto se sostiene —26 Hz sigue siendo la mitad de los 50 que la política
> necesita— pero **la cifra estaba mal por un factor 2**. Y el arreglo que se había
> propuesto ("que `rl_cmd` devuelva el estado en la misma respuesta") **ya existía**:
> es `/rl_step`. Se corrige el registro en vez de dejar el número inflado.

Un paso del modo 6 por `/rl_step` tarda **38,3 ms** medidos sobre 60 pasos. El período que
exige `control_freq = 50` es de 20 ms.

**La política corre ~2× más lento de lo que fue entrenada.**

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
2. ~~Que `rl_cmd` devuelva el estado en la misma respuesta~~ — **ya existe**: `/rl_step`,
   protocolo v3. Es lo que ya corre, y aun así da 26 Hz.
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

**Estado:** `RESUELTO` (2026-08-04, v1.58.8) — el `MITIGADO` original describía el
paliativo del cliente (`zp=1` a mano en cada script). La corrección definitiva está en el
firmware: el modo 5 exige quietud sostenida y re-establece el cero antes de bombear, y
agotar el timeout es **falla** en vez de arranque a ciegas. Medido: 0/5 fallos y 5/5 con
`E/E*` en rango. · **Detectado:** 2026-08-04, midiendo m5 a 500 Hz
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

**Elimina el modo de fallo catastrófico.**

#### La corrección definitiva (v1.58.8)

El arreglo del cliente dependía de que cada script se acordara de llamarlo, así que se
llevó al firmware: **el modo 5 tiene ahora una fase de quietud + re-cero antes de
bombear**, con el mismo patrón que `H_WAIT_QUIET` del homing y por la misma razón que
dice su comentario — quietud **sostenida por ventana** y no velocidad instantánea, porque
a 500 Hz la diferencia entre dos muestras del encoder es cero o un conteo entero. Vigila
el brazo además del péndulo, y **agotar el timeout es falla**, no arranque a ciegas.

Medido con el cliente usando el protocolo VIEJO, o sea sin que el script haga nada:

| | fallos totales | `E/E*` en rango | θ en bombeo |
|---|---|---|---|
| antes (fw viejo) | 1/4 | 3/4 | 12–68° |
| `zp=1` desde el cliente | 0/5 | 4/5 | 64–**95°** |
| **fw v1.58.8** | **0/5** | **5/5** | **58–86°** |

Mejor que la versión del cliente en las tres columnas. `?sz=0` desactiva la fase para
poder medir contra el comportamiento anterior; por defecto va **activa**, porque es una
corrección y no instrumentación.

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

## P23 {#p23}
### `?ke=` es API publicada que el propio lazo pisa

**Severidad:** media. **Estado:** `RESUELTO` (2026-08-06; hallado el 2026-08-05 por
lectura del código).

**El arreglo.** `ke_gain_override` (negativo = sin override) separa el mando manual del
valor adaptativo: con override puesto, la rama de calado ya no escribe `ke_gain`. Se
sostiene a través de `setMode(5)` a propósito —el orden de uso es `?ke=` y después
`?m=5`, así que limpiarlo en la entrada al modo sería reponer el defecto— y `?ke=-1`
devuelve el control a `KE_GAIN_BASE`/`KE_GAIN_BOOST`. El default reproduce exactamente
el comportamiento anterior.

Además: **`ke_gain` no se publicaba en `/state`**. Un barrido de `?ke=` no tenía forma de
verificar contra qué valor estaba midiendo, que es la mitad de por qué sus campañas no
son atribuibles. Ahora se publican `ke_gain` y `ke_override`.

**Lo que esto NO cierra:** `ke_gain` sigue sin calibrar y su barrido sigue pendiente. Lo
que cambia es que ahora *se puede* barrer.

**Estado de la verificación (2026-08-06).** En banco se comprobó la **cañería**: `?ke=`
escribe, se sostiene entre lecturas, se puede barrer y se publica en `/state`
(`experiments/2026-08-06_etapa2_serial/`, 14/14 por HTTP, modo 0, `pwm = 0`). **No** se
comprobó la afirmación central —que la rama adaptativa del bombeo ya no lo pise—, porque
eso ocurre dentro del lazo del modo 5 y exige entrar a bombear. Con `homing_ok = false` y
[P24](#p24) sin resolver, esa corrida no se hizo: **esa mitad se apoya hoy en lectura de
código.** Cerrarla es una corrida de m5 detrás de la inspección del pivote.

El tercer mando del swing-up con el mismo defecto, después de `bt` (eliminado en la
auditoría del 2026-07-28) y del bug F1.

**Evidencia.** En la rama de bombeo resonante (`esp32_qube.ino:3992-3999`):

```c
if (currentAbsAngle > swing_maxAngleAchieved + SWINGUP_IMPROVE_DEG) {
  swing_maxAngleAchieved = currentAbsAngle;
  swing_lastImprovementMs = millis();
  ke_gain = KE_GAIN_BASE;            // ← pisa lo que puso ?ke=
} else if ((millis() - swing_lastImprovementMs) > STALL_TIMEOUT_MS) {
  ke_gain = KE_GAIN_BOOST;
}
```

`swing_maxAngleAchieved` se resetea a 0 al entrar al modo 5 (`:1505`), así que el primer
tick con |α| > `SWINGUP_IMPROVE_DEG` (5°) sobrescribe `ke_gain` con `KE_GAIN_BASE` = 0,75.
Durante todo el bombeo vale 0,75 o 1,5 (el boost por calado), **nunca lo que se pidió por
HTTP**. El valor declarado en `:730` es 0,65 y tampoco es el que corre.

El comentario de `:1521-1522` afirma *"Solo reset `ke_gain` si no fue configurado por
HTTP"* y **no hay código que lo implemente**. Mismo patrón que H1, H4 y H6 de [P4](#p4): un
camino de código que no hace lo que su comentario dice.

**Alcance.** Menor de lo que parece, y conviene decirlo: aunque `?ke=` funcionara,
[P11](#p11) está medido —el bombeo satura el 92,5% del tiempo— y `ke_gain` sólo escala
`Kp_pump`, o sea la salida ya recortada. **Es una tercera razón independiente por la que
los barridos históricos de `ke` no son atribuibles, pero no es lo que impide subir la
energía del bombeo.**

**Cómo afrontarlo.** Dos opciones, ninguna urgente:

1. Que `?ke=` marque un flag que desactive la rama adaptativa mientras esté puesto. Barato
   y conserva la API.
2. Exponer `KE_GAIN_BASE`/`KE_GAIN_BOOST` por HTTP y dejar `ke_gain` como variable interna.
   Más honesto —el mando pasaría a llamarse como lo que de verdad controla— pero rompe la
   API existente.

Mientras tanto, el comentario mentiroso de `:1521-1522` se corrige igual: cuesta nada y es
lo que hizo perder tiempo.

---

## P24 {#p24}
### El pivote del péndulo desarrolló fricción seca dominante: ya no oscila

**Severidad: alta.** **Estado:** `ABIERTO` (2026-08-05). **Es mecánico, no de control.**

**Evidencia.** Suelta manual con el brazo sujeto a mano (protocolo del 2026-08-04). Desde
unos 19° el péndulo baja al reposo **sin cruzarlo ni una vez**, con mesetas de hasta
**4,25 s sin cambiar un solo conteo de encoder**:

```
t=18  −19,3     t=22  −7,0     t=26  −4,8
t=20  −11,3     t=24  −6,2     t=28  −4,2     t=30  0,0
```

**El encoder está descartado.** Barrido manual de 30 s (`scripts/encoder_probe.py`): 2240°
recorridos, 9712 valores distintos, paso mediano 0,176°, **meseta más larga 0,12 s y ninguna
por encima de 0,5 s**. La medición sigue el movimiento; lo que se traba es el péndulo.

**Cuantificación.** Quedarse quieto a 4,75° del reposo exige retener el par gravitatorio a
ese ángulo:

| | |
|---|---|
| par seco retenido (a 4,75°) | **1,26e-3 N·m** |
| par viscoso máximo a 50° y 2,28 Hz, con `Dp` = 7,52e-6 | 9,4e-5 N·m |
| **razón** | **13,4×** |

Con fricción de Coulomb de esa magnitud la amplitud cae **19° por ciclo**, así que desde 19°
se detiene en **menos de un ciclo (~0,4 s)**. Es exactamente lo observado: el modelo predice
la medición.

**Por qué importa tanto.** El 2026-08-04 el mismo péndulo dio un decaimiento **viscoso
limpio**, con dos sueltas de 64° y 43° coincidiendo al 0,4% — eso exige muchos ciclos. La
planta cambió entre esa fecha y hoy.

Y reordena la jornada entera:

- Explica la [degradación por ciclo de trabajo](#p12): el bombeo necesitando el triple de
  tiempo es energía que se come la fricción seca.
- Explica por qué el swing-up dejó de entregar tras ~12 corridas.
- **Explica por qué las cinco hipótesis sobre el controlador de [P4](#p4) cayeron una tras
  otra:** todas buscaban el error en el lazo. Con 1,26e-3 N·m de fricción seca **no modelada**
  en la articulación que el LQR debe regular, el diseño por CARE —que asume amortiguamiento
  puramente viscoso— no describe esta planta.

**Reserva.** Es **una** suelta (n=1), al final de una jornada de ~90 corridas. No se sabe si
es reversible con reposo, si viene de desgaste, de algo que se soltó o de suciedad en el
pivote. Tampoco se midió con el banco fresco para confirmar que apareció hoy.

**Cómo afrontarlo.** Inspección mecánica del pivote **antes** de cualquier otra medición de
control: juego, rozamiento, alineación, y si el disco del encoder roza. Después repetir la
suelta con banco fresco y n≥3 desde distintas amplitudes. **Ninguna sintonía tapa esto**, y
mientras siga así el banco no sirve como instrumento para P4.

---

## P25 {#p25}
### Un intento de balanceo fallido terminaba el trabajo: el banco quedaba en modo 0 esperando al operador

**Severidad: media.** **Estado:** `EN CURSO` (2026-08-21) — corregido en v1.63.0, **sin verificar en banco**.
**Es de máquina de estados, no de control.**

**Síntoma.** Se pide `m5`, el swing-up bombea, traspasa a `m4` — y a los pocos cientos de ms
`/state` reporta `mode: 0`. No hay mensaje de falla, no hay reintento: el banco queda quieto
hasta que alguien vuelve a pedir `m5`.

**Causa.** El modo 4 tenía **una sola salida practicable** cuando el catch fallaba, y no era
la que parecía. En el código había dos:

| salida | condición | destino | por qué |
|---|---|---|---|
| fin de carrera duro común | `\|pos\| > SERVO_HARD_LIMIT_DEG` (95°) | `safeStop()` → **modo 0** | la que ocurre siempre |
| fallback del LQR | `\|pendPosRaw\| > LQR_FALLBACK_RAW_DEG` (360°) | modo 5 | casi nunca llega a dispararse |

El fallback a swing-up existía desde antes y **es el comportamiento que se quería**, pero pide
que el péndulo dé **una vuelta entera**. Un LQR que no engancha satura hacia un lado —está
contra su techo la mayor parte del tiempo (P4/H3)— y **deriva el brazo al tope** mucho antes
de eso. Gana la primera fila, y la primera fila es un paro de emergencia.

Es el mismo patrón que [P12](#p12) describe desde el otro lado: el tope del brazo es
consecuencia, no causa. Aquí, además, es lo que **enmascara** el diagnóstico — un catch que
se cayó a los 90 ms y un brazo que se fue al tope con el péndulo arriba terminaban los dos
en `mode: 0`, indistinguibles desde `/state`.

**Qué se cambió.**

1. **Detección del intento fallido antes del tope**, en el modo 4: `|α|` sostenido por encima
   de 60° durante 150 ms (caída), o 1,5 s sin haberse acercado nunca a la vertical (entrega
   mala). La caída exige haber estado **antes** dentro de 25° de la vertical — sin esa
   condición el umbral se cumple en el primer tick, porque el traspaso entrega a hasta
   (180 − `tn`) grados, y el reintento entraría en bucle sin llegar a intentar nada.
2. **Fase de recentrado del modo 5**, previa a la quietud de [P22](#p22): la ley del **modo
   2 sin el integral**, con sus ganancias verificadas (`Kp`=3, `Kd`=0,45; v1.58.5, 1,2 % de
   sobrepaso). No se sintoniza nada nuevo. El término derivativo **no es opcional**: sin él
   esto es el bang-bang de `H_GOTO_CENTER` que [P8](#p8) tiene catalogado, porque el piso de
   fricción y el techo de aproximación son el mismo número. Cierra con `homing_pwmSign` —el
   sentido **medido** en el propio banco, no `MOTOR_DIR`—, usa `setMotorDirect()` y suelta el
   piso de PWM dentro de 25°. Queda **exenta del fin de carrera duro** por la misma razón que
   lo está el homing: es la única rutina que puede sacar al brazo de los 95°, y sólo conduce
   hacia el centro. Sale cuando está **cerca y quieto** (12°, 40 °/s): sólo «cerca» no basta,
   porque con el freno dinámico del puente a PWM=0 (τ ≈ 0,47 s) el brazo que cruza la ventana
   a 150 °/s se sigue de largo. Timeout de 5 s **y** detector de calado a 1,2 s en el tramo
   lejano: sin el segundo, un signo invertido serían 5 s de PWM 90 contra el tope.
3. **Presupuesto de 3 reintentos consecutivos** (`?rtn=`), reiniciado por cualquier modo
   pedido a mano y por un balanceo que sobreviva 3 s. Agotado, `safeStop()` como antes.
4. `swing_fail_reason` en `/state` distingue las cinco formas de terminar un intento, que es
   lo que antes no se podía leer.

`?rt=0` restaura el comportamiento previo exacto.

**Corrido en banco el 2026-08-21** (`experiments/2026-08-21_reintento_swingup/`, seis trazas
del DAQ a 500 Hz). El reintento hace lo que debe: **3 de 3 y luego 2 de 2 recentrados
exitosos**, con el brazo volviendo de +97°/+103° al centro en 0,6–1,1 s. Pero la primera
versión traía tres defectos, los tres visibles en las trazas y los tres corregidos en la
misma sesión:

| # | qué pasaba | evidencia | corrección |
|---|---|---|---|
| 1 | Con el motor suelto en la fase de quietud, **el péndulo se lleva el brazo por reacción** | de −6,2° a +96° en 1,1 s con `pwm` = 0 en todas las muestras | hold del brazo mientras haya un reintento en curso |
| 2 | El hold con banda única **se impedía a sí mismo arrancar** | brazo clavado en 19,5–20,0° durante 20 s dando pulsos de 50 PWM, con el péndulo quieto en ±1° | histéresis 35°/15° |
| 3 | El piso de fricción **re-lanzaba el freno** | `pwm` alternando −45/+45 entre muestras consecutivas — el bang-bang de [P8](#p8) otra vez | el piso sólo se aplica al empuje |

Efecto acumulado sobre el pico del brazo: **134,56° (el tope mecánico) → 124,81° → 110,39°**,
y el timeout de quietud de 20 s desapareció.

**Lo que la campaña NO validó**: en las cuatro tandas `swing_fail_reason` fue siempre 3 (tope)
y la detección de caída del péndulo **nunca llegó a dispararse**, porque el brazo llega al tope
primero — [P26](#p26). Esa rama del código sigue sin ejercitarse en el hierro. También quedan
sin ejercitar el motivo 4 (nunca llegó) y el 5 (recentrado imposible).

Lo que hay que mirar cuando se corrija P26:

- Que el recentrado **vaya al centro**. Cierra con `homing_pwmSign`, que ahora se publica en
  `/state` como `homing_pwm_sign`: si el signo estuviera mal empujaría contra el tope, el
  detector de calado lo abortaría a 1,2 s y el síntoma sería `swing_fail_reason: 5` inmediato,
  sin daño. **Leer ese campo después del `m3` es además el test de [P26](#p26)**, que salió a
  la luz al escribir esta corrección y es bastante más grave que ella.
- Que los 60° / 150 ms no aborten intentos **recuperables**. Con el péndulo en vuelo `α`
  cruza rápido; el criterio se eligió por eso, pero el número no está medido.
- Que 3 reintentos no escondan la deriva del banco: tres intentos con recentrado son ~15 s de
  motor. Con [P24](#p24) abierto y [P12](#p12) `DEPENDE DEL ESTADO`, una tasa de éxito
  «1 de cada 3» **no** es comparable con una campaña vieja de un intento por corrida. Por eso
  `swing_retry_count` se publica: sin él, el reintento inflaría las tasas en silencio.

---

## P26 {#p26}
### Los términos de «empujar al centro» no multiplican por `MOTOR_DIR`: empujan al tope

**Severidad: alta.** **Estado:** `ABIERTO` (2026-08-21) — **hipótesis CONFIRMADA en banco**, corrección
pendiente. Salió a la luz al escribir [P25](#p25), buscando con qué signo debía cerrar el
recentrado.

**El argumento, entero.** `MOTOR_DIR` vale `−1` en el firmware actual. Los lazos de posición
del brazo lo aplican; los términos que empujan al centro, no:

| dónde | expresión | ¿`MOTOR_DIR`? |
|---|---|---|
| modo 2, PID de posición | `pwm = MOTOR_DIR * (Kp·err + …)` | **sí** |
| homing, `H_GOTO_CENTER` | `pwm = KP·err · homing_pwmSign` | **sí** (el medido) |
| modo 4, *centering* del LQR | `centering = −gain·theta;  pwm += centering` | **no** |
| modo 4, «FORZAR centro» a >70° | `center_dir = −sign(theta);  pwm = center_dir·lqrPwmMax` | **no** |
| modo 5, freno de fin de carrera a >90° | `brake_dir = −sign(pos);  setMotor(brake_dir·70)` | **no** |
| modo 7, freno del híbrido | idéntico al anterior | **no** |

Las cuatro últimas equivalen a un proporcional con multiplicador `+1` implícito. Y el modo 2
**funciona medido** (v1.58.5: 1,2 % de sobrepaso, 0 hunting), lo que obliga a que
`homing_pwmSign = MOTOR_DIR = −1`: si valiera `+1`, el PID del modo 2 sería realimentación
positiva y el brazo se iría al tope en cuanto se le diera un setpoint.

Con `homing_pwmSign = −1`, esas cuatro expresiones tienen el signo **invertido**: cada vez
que el firmware cree estar devolviendo el brazo al centro, lo está empujando contra el tope.

**Qué predice.** El freno del modo 5 arranca a `SERVO_BRAKE_DEG` = 90° y el corte duro está a
95°: si el freno empuja hacia afuera, el brazo recorre esos 5° en pocos ms y el modo muere.
Eso es, literalmente, el síntoma que [P12](#p12) tiene registrado —«el límite del brazo trunca
swing-ups»— y la razón por la que **todos** los modos de balanceo terminan derivando el servo
al tope. También encaja con [P4](#p4): el *centering* del LQR es un término de hasta ±25 PWM
sobre un techo de 70 que, con el signo cambiado, **se suma** a la deriva en vez de corregirla.

**No se corrigió en v1.63.0, a propósito.** Invertir cuatro términos de golpe cambia el
comportamiento de los modos 4, 5 y 7 a la vez, es candidato a causa de fondo de P4, y esa es
exactamente la clase de cambio que no se hace sin banco delante. El recentrado de P25 sí cierra
con `homing_pwmSign`, así que la corrección nueva no hereda el defecto.

**Verificado en banco el 2026-08-21.** `m3` (homing) y `homing_pwm_sign` en `/state`:

```
homing_ok=True  range=270.703  centered=True  ->  homing_pwm_sign = -1
```

Repetido en las cinco corridas de homing de la sesión, siempre `−1`. Con eso el argumento
queda cerrado: las cuatro expresiones de la tabla empujan **hacia el tope**.

**Y la campaña del mismo día lo corrobora por una vía independiente**
(`experiments/2026-08-21_reintento_swingup/`): en las cuatro tandas de swing-up,
`swing_fail_reason` fue **siempre 3 — «el brazo llegó al tope»**, y **ni una sola vez** la
detección de caída del péndulo que v1.63.0 agregó al modo 4. El brazo llega al tope antes de
que el péndulo se caiga, que es justo lo que este defecto predice.

**Si se confirma**, la corrección es multiplicar los cuatro términos por `MOTOR_DIR` —mejor,
por `homing_pwmSign`, que sobrevive a un recableado— y **re-caracterizar los modos 4, 5 y 7**:
ninguna sintonía hecha con estos signos es transferible.

---

## P27 {#p27}
### La `f_n` del péndulo depende de si el brazo está suelto — y el bombeo **sí** está en resonancia

**Severidad: media.** **Estado:** `ABIERTO` (2026-08-21). Medido en banco,
`experiments/2026-08-21_reintento_swingup/`.

**Lo primero, porque cierra una hipótesis vieja.** Comparar la frecuencia del bombeo contra un
único número de `f_n` no sirve: el período del péndulo crece con la amplitud y el swing-up
recorre 0–180°. Hecha la comparación banda por banda contra la caída libre **a esa misma
amplitud** (153 medios ciclos de bombeo sobre 4 tandas, 32 de caída libre):

| amplitud pico | bombeo (m5) | libre (m0) | cociente |
|---|---|---|---|
| 20–40° | 1,969 Hz | 2,153 Hz | 0,915 |
| 40–60° | 1,952 | 2,007 | 0,972 |
| 60–80° | 1,768 | 1,796 | 0,984 |
| 80–100° | 1,600 | 1,603 | **0,998** |
| 100–120° | 1,430 | 1,448 | 0,987 |
| 120–145° | 1,286 | 1,321 | 0,973 |

**El bombeo sigue la frecuencia propia del péndulo dentro del 0–3 % entre 40° y 145°.** La ley
resonante hace lo que dice hacer, y «el swing-up no captura porque bombea desintonizado» queda
**refutado con medición**. Encaja con lo que ya decía [P2](#p2): energía sobra, el problema es
la captura.

La única desintonía real está en el arranque —20–40°, cociente 0,915— y ahí es donde actúa
`SWINGUP_KICK_HZ = 2,0 Hz` contra una f natural de ~2,13 Hz. Son −6 %: subirlo a ~2,1 es un
cambio de una constante, pero **no está medido que mejore nada** y con la fricción del pivote
el Q es bajo, así que la desintonía puede ser irrelevante. No tocar sin un A/B.

**El hallazgo que sí es un problema: `f_n` no es una propiedad del péndulo solo.**

| condición del brazo | f_n a ángulo pequeño | origen |
|---|---|---|
| **rígidamente fijo** | 1,700 Hz | analítica √(3g/2L_p) + otras 3 vías del registro |
| **libre** (`m0`, puente en corto) | **2,134 Hz** | medido hoy, 32 medios ciclos, 138°→35° |
| «retenido» por el PID del `m2` | 1,411 Hz | medido hoy, n=3 — **ver más abajo, no es un empotramiento** |

Contra el valor de brazo fijo, la medición con brazo libre da un cociente de **1,255**. El signo
es el correcto para un péndulo de Furuta: soltar la base la deja retroceder, baja la inercia
efectiva que ve el péndulo y el modo dominado por el péndulo **sube**. La magnitud queda
pendiente de contrastar contra el modelo acoplado de `qube_dynamics.py`.

O sea que **un valor de `f_n` sin la condición de contorno declarada no es interpretable**, y por
ahí se cuela la contradicción que arrastraba el proyecto: 1,70 Hz y 2,28 Hz **no se contradicen
necesariamente**, pueden ser condiciones distintas. (Eso no exonera a la medición de 2,28: sus
tres corridas dieron 4,8–7,1 Hz entre sí, así que sigue siendo inservible por dispersión. Lo que
cambia es que su *valor central* ya no es absurdo.) Toca directo a [P5](#p5)/`PEND_INERTIA`:
cualquier inercia despejada de una `f_n` hereda la condición con que se midió.

**Para el swing-up manda la condición de brazo libre**, porque durante el bombeo el brazo se
mueve: ~2,13 Hz a ángulo pequeño, bajando a ~1,2 Hz cerca de la vertical.

**El `m2` no sirve como sustituto del brazo fijo, y conviene decir por qué.** Su 1,411 Hz cae
**por debajo** del valor con brazo rígido (cociente 0,830), así que no puede estar interpolando
entre «libre» y «fijo». Un PID de posición es un **resorte**, no un empotramiento: un péndulo
sobre una base elástica tiene un modo acoplado *inferior* al de base rígida, y eso es lo que se
midió. El brazo, además, se movió entre −30,9° y +26,3° con PWM de hasta 197. Con n=3 medios
ciclos, esa pierna **se descarta** como medición de `f_n` con brazo fijo; queda como recordatorio
de que sujetar por software no es sujetar.

**Reservas.** La pierna de brazo libre sí es sólida: 32 medios ciclos limpios de 138° a 35°, con
el motor verificado en `pwm = 0` en **todas** las muestras. Aun así es **una sola suelta**, al
final de una sesión de ~8 campañas.

**Cómo cerrarlo.** Repetir la suelta con el brazo **mecánicamente** trabado —no por software— y
n≥3, con banco fresco; repetir también la de brazo libre para tener n≥3 de los dos lados. Y
declarar en la tesis la condición de contorno **junto a cada** `f_n`. Hasta entonces, no usar una
`f_n` para despejar `PEND_INERTIA` sin decir con qué brazo se midió.

**Nota sobre [P24](#p24).** Estas 32 medias oscilaciones contradicen «el péndulo ya no oscila»
(n=1, 2026-08-05). La caída de amplitud es de ~5,5° por medio ciclo, aproximadamente constante
—sigue siendo la firma de fricción seca—, pero hoy **no** impide oscilar. Habría que revisar si
P24 fue un estado transitorio del pivote o una medición de otra condición.

---

## P28 {#p28}
### Cada petición a `/state` o `/cmd` cuesta una resincronización del lazo de 500 Hz

**Severidad: alta.** **Estado:** `ABIERTO` (2026-08-21). Medido en banco; **la causa no está
identificada** y dos explicaciones ya cayeron con medición.

**La medición.** `loop_overruns` cuenta las veces que el lazo se atrasó más de 5 períodos
(10 ms) y hubo que re-sincronizar. Placa en modo 0, recién arrancada:

| condición | overruns |
|---|---|
| en reposo, **sin** tráfico HTTP, 20 s | **1** |
| 61 peticiones a `/state` | **+61** → 1,00 por petición |

Y por endpoint, todos por el mismo transporte y en la misma sesión:

| endpoint | qué devuelve | tamaño | overruns/petición |
|---|---|---|---|
| `/state` | `getStateJson()` | 2209 B | **0,97** |
| `/cmd` | `getStateJson()` (¡también!) | 2209 B | **0,97** |
| `/rl_state` | `getRlStateJson()` | 87 B | 0,00 |
| `/daq` | `getDaqStatusJson()` | 139 B | 0,00 |
| `/daq/read` | buffer binario estático | **8208 B** | 0,00 |

**Dos hipótesis descartadas, las dos con medición:**

1. **No es el tamaño de la respuesta.** `/daq/read` devuelve 8208 B —casi cuatro veces
   `/state`— y cuesta 0,00.
2. **No es la construcción del `String`.** Se agregó un `reserve(2816)` en `getStateJson()`
   justamente para eliminar las ~120 reasignaciones incrementales, se flasheó y se volvió a
   medir: **0,97 antes y 0,97 después**. El `reserve` quedó en el código con un comentario que
   lo dice, para que nadie lo reintente por ahí.

Lo que queda en pie es la diferencia de *contenido*: `getRlStateJson()` lee **sólo globales
cacheados** —su propio comentario dice que es para no tocar encoder ni I2C desde el contexto
async— mientras que `getStateJson()` lee el hardware ahí mismo (`readPcnt()` de las dos
unidades, cuatro `digitalRead`). Pero `readPcnt` es un `pcnt_get_counter_value()` y un
`digitalRead` son nanosegundos: **no cierra por sí solo con 10 ms**, así que tampoco se puede
declarar causa. Hace falta medir dentro.

**Por qué importa más de lo que parece.**

- `/cmd` **también** llama a `getStateJson()`. O sea que *dar una orden* —cambiar de modo,
  mover el setpoint— cuesta lo mismo que leer el estado. Eso no se ve leyendo la firma del
  endpoint.
- Refuerza [P20](#p20): si cada ida y vuelta le arranca al lazo una resincronización, el
  problema del modo 6 no es sólo la latencia del enlace.
- **Contamina la instrumentación.** Toda campaña que sondee `/state` mientras mide está
  perturbando el lazo que mide. Las trazas del DAQ siguen siendo válidas —las muestrea y las
  marca temporalmente el propio chip a 500 Hz— pero se tomaron bajo esa carga, y eso hay que
  decirlo. Aplica a la campaña del reintento de este mismo día.
- Explica de paso por qué `flash.py` dejó de pasar: el POST de 1 MB a toda velocidad se
  atasca alrededor de los 128 kB. `src/firmware/flash_lento.py` lo manda en bloques de 1460 B
  con 4 ms de pausa y entra entero (1017 kB en ~17 s), verificado.

**Cómo seguir.** Instrumentar `getStateJson()` por dentro con `micros()` por tramo y publicar
el peor, o bisecar: reemplazar las lecturas de hardware por los globales cacheados —el patrón
que `getRlStateJson()` ya usa— y volver a medir. Es una tarde con el banco y cierra el asunto.

---

## Historial de cambios

| fecha | problema | cambio | verificación |
|---|---|---|---|
| 2026-08-21 | **P28** | **Cada petición a `/state` o `/cmd` le cuesta al lazo de 500 Hz una resincronización** | 1,00 overruns/petición (61 en 61) contra 1 en 20 s de reposo. Por endpoint: `/state` y `/cmd` 0,97; `/rl_state`, `/daq` y `/daq/read` (8208 B) **0,00**. Descartado con medición que sea el tamaño (8 kB cuestan cero) y que sea el `String` (`reserve()` flasheado: 0,97 → 0,97). **Causa sin identificar** |
| 2026-08-21 | infra | `flash.py` dejó de pasar contra la placa: el POST se atasca ~128 kB. Se agrega `src/firmware/flash_lento.py` | Bloques de 1460 B con 4 ms de pausa: 1017 kB en ~17 s, `{"ok":true}` y arranque limpio. Verificado tres veces |
| 2026-08-21 | **P27** | **La `f_n` del péndulo depende de la condición del brazo**, y el bombeo del swing-up **sí** está en resonancia | Caída libre con DAQ a 500 Hz: brazo libre **2,134 Hz** (n=11 <60°, 32 medios ciclos en total) contra **1,700 Hz** analítico con brazo fijo, cociente 1,255. La pierna «retenido por `m2`» (1,411 Hz, n=3) se descarta: cae POR DEBAJO del valor de brazo fijo, o sea que un PID es un resorte y no un empotramiento. Bombeo contra libre a igual amplitud: cociente 0,915–0,998 entre 20° y 145°. Refuta «bombea desintonizado» y reconcilia 1,70 vs 2,28 Hz |
| 2026-08-21 | **P26** | **CONFIRMADO en banco**: `homing_pwm_sign = −1` en las cinco corridas de homing de la sesión | Corroborado por vía independiente: en las 4 tandas de swing-up `swing_fail_reason` fue siempre 3 (tope) y **nunca** la detección de caída del péndulo. El brazo llega al tope antes de que el péndulo se caiga. Corrección pendiente a propósito |
| 2026-08-21 | **P25** | Reintento **corrido en banco**; 3 defectos encontrados y corregidos en la misma sesión (motor suelto ⇒ el péndulo se lleva el brazo · hold con banda única ⇒ ciclo límite en el borde · el piso de fricción re-lanzaba el freno) | 3/3 y 2/2 recentrados exitosos. Pico del brazo 134,56° (tope mecánico) → 124,81° → **110,39°**; el timeout de quietud de 20 s desapareció. Sin ejercitar: los motivos de falla 1, 4 y 5 |
| 2026-08-21 | **P26** | **Hallazgo de signo**: los cuatro términos de «empujar al centro» (centering del LQR, forzado a >70°, freno de fin de carrera de m5 y de m7) no multiplican por `MOTOR_DIR`, y el modo 2 y el homing sí | Deducción **sobre el código, sin banco**: el m2 funciona medido ⇒ `homing_pwmSign = MOTOR_DIR = −1` ⇒ esas cuatro expresiones tienen el signo invertido y empujan hacia el tope. Predice el síntoma de P12. `homing_pwm_sign` se publica en `/state` para poder cerrarlo con un `m3` |
| 2026-08-21 | **P25** | **Reintento automático del swing-up** (v1.63.0): el intento fallido se detecta antes del tope, el brazo vuelve al centro con la ley del m2 sin integral y se re-bombea, hasta 3 veces. `rt`/`rtn` en `/cmd`, `swing_retry_count`/`swing_fail_reason` en `/state` | **Sólo compila.** Ningún intento fallido real pasó todavía por este camino; qué mirar en la primera tanda está en P25 |
| 2026-08-05 | P4 | **H3 CONFIRMADA a 500 Hz** sobre las trazas del m5, que traían el modo 4 completo. Sin banco nuevo | Saturado **43,6–100%, mediana 70,4%** (n=8) contra el techo efectivo por muestra; la prueba ingenua da 0,0%. Coincide con el 68,8% de las trazas de 14 Hz. **El péndulo sale de ±20° en 0–86 ms** desde el traspaso, 9/10 antes que el brazo: el tope del brazo es consecuencia |
| 2026-08-05 | **P24** | **El péndulo dejó de oscilar: fricción seca 13,4× el par viscoso** | Suelta manual con brazo sujeto: baja al reposo sin cruzarlo, mesetas de 4,25 s sin cambiar un conteo. Encoder descartado (barrido manual: 2240°, meseta máx 0,12 s). Par seco retenido 1,26e-3 N·m contra 9,4e-5 de viscoso. Predice detención en <1 ciclo, que es lo observado. **La hipótesis de la fila siguiente queda confirmada por una vía distinta a la buscada**: no es que `Dp` derivó, es que el amortiguamiento dejó de ser viscoso |
| 2026-08-05 | P4 · modelo | **Hipótesis nueva, sin contrastar: P4 y la degradación del banco podrían ser el mismo problema** | Las ganancias se diseñan sobre un modelo con `Dp` medido **una vez** (n=2, banco fresco) y `Dr` **nunca medido** (default 5e-6, con `Dr_std` igual al valor). Si la fricción varía dentro de una sesión como se observó, puede **no existir un juego de ganancias fijas** que sirva. Explicaría por qué cinco hipótesis sobre el controlador cayeron seguidas |
| 2026-08-05 | método | **El spin-down automático falló tres veces, cada una por una razón distinta** | (1) con `m=0` el brazo no queda sujeto y el acoplamiento de 2 GDL destruye la envolvente (λ = −0,0006, R² = 0,02); (2) con `m=2` hace falta descartar ~5 s de asentamiento; (3) el ajuste no quitaba un **offset de −26°** en `alpha` (P22 sólo se corrige al entrar a m5). Corregidos los tres, queda el impedimento real: **el homing excita 3,7–4,4°** y la referencia se tomó con sueltas de 64° y 43°; por debajo de ~20° manda la fricción seca. `spindown_now.py` ahora **se niega a reportar** salvo amplitud ≥20° y R² ≥0,85 |
| 2026-08-05 | pendiente | **El péndulo osciló a 1,71 Hz, no a los 2,28 Hz de la identificación del 2026-07-30** | Observado en las capturas de spin-down, sin investigar. Puede ser efecto del brazo mal sujeto. Importa porque de esa frecuencia sale `PEND_INERTIA`, que alimenta la energía del swing-up y el criterio `E/E*` |
| 2026-08-05 | P12 · método | **La degradación del banco es un ciclo de trabajo, no una deriva de jornada**: ~40 min de reposo compran ~12 corridas | Línea base tras el reposo: 7,5 s de bombeo y 3/3. **Doce corridas después: 15,9 s y 2/3.** El segundo intento del barrido de K2 se abortó igual que el primero (2 traspasos de 12; el control, 0/3). Consecuencia de diseño: tandas de ~12 intentos, no de 20 — y un `tn` más exigente alarga cada bombeo, así que el umbral y el largo de la tanda no son independientes |
| 2026-08-05 | P4 | **Mejor resultado individual de la jornada: `t_loss` = 114 ms con entrega de 2,6°** (n=1) | El ajuste predice 79 ms para ese error, así que la ordenada de 90 ms está **subestimada**, no sobreestimada. Refuerza la reserva sobre extrapolar la ecuación hacia errores pequeños. No dice nada sobre K2: es una sola corrida |
| 2026-08-05 | P4/H7 · método | **El signo de realimentación no se pudo recuperar por regresión; se instrumentó** | Ajustar `pwm ~ θ,α,θ̇,α̇` sobre las muestras no saturadas dio R²=0,55 (n=2809) y R²=0,28 (n=207, subconjunto limpio), con el coeficiente de α **de signo cambiado y factor 50**. Con la salida saturada el 98% del tiempo las muestras útiles son sólo los cruces por cero. **v1.58.10** publica `lqr_vel_theta`, `lqr_vel_alpha` y `lqr_alpha_err`, espejos de lo que la ley consume. `scripts/sign_probe.py` lo lee con las nueve ganancias a cero y el motor quieto (verificado); falta una mano en el brazo |
| 2026-08-05 | P12 · método | **El swing-up se degrada a lo largo de una sesión, y con ~60 corridas encima deja de ser utilizable como instrumento** | Medido sobre las 4 tandas del día, en orden: bombeo mediano **5,5 → 6,8 → 6,2 → 13,6 s**; θ máx en bombeo **69,0 → 79,9 → 82,8 → 94,7°**; traspasos **15/15 → 14/20 → 16/20 → 2/5**. El barrido de K2 se abortó en la rep 1 por esto. **Reabre P12 como dependiente del estado del banco** y obliga a verificar la línea base del m5 **antes de cada tanda**, no sólo al empezar el día |
| 2026-08-05 | P4 | **`LQR_PWM_MAX` no era el límite operativo**: el bloque de límites de servo del modo 4 (`:3647-3695`) re-acotaba a un **70 literal en las cinco ramas** | Los dos valores coincidían, así que nunca se notó — pero subirlo no habría hecho nada. Tercer mando con esta forma, tras `bt` y `?ke=`. **v1.58.9**: `?lpm=` (20–150, default 70 = histórico), todo el bloque contra `lqrPwmMax`, y `lqr_pwm_max` en `/state` |
| 2026-08-05 | P4 | **Barrido de `?lpm=` en banco, n=20** (70/100/130/150, `tn`=162 fijo) | **H3 NO es causal.** Residuo de `t_loss` tras descontar la entrega: −8,3 / −6,5 / +0,7 / −1,1 ms contra dispersión intra-nivel de 13–68. Y **la saturación sube en vez de bajar** (97,4 → 98,6%): a cualquier techo el lazo está pegado el 98% del tiempo, así que el LQR **es un relé a cualquier autoridad**. Nunca se alcanzó el régimen lineal. Sin brownout, θ máx igual que siempre |
| 2026-08-05 | método | **El criterio 1 del barrido de `lpm` falló: las dos tandas de la tarde no son comparables** | El control (`lpm`=70, `tn`=162) dio 64 ms contra los 14 ms del mismo `tn` una hora antes. Causa: **las entregas mejoraron de 17,4° a 3,6° de error mediano** con el mismo umbral — deriva del banco tras 55 corridas, del tipo ya documentado en la Etapa 1. La comparación **dentro** de la tanda intercalada sigue valiendo; la de entre sesiones no. Releer así el `0 → 14 ms` de `tn` |
| 2026-08-05 | método | **Tercer criterio bien escrito y mal implementado en dos días** | El barrido de `lpm` imprimió "la saturación baja: SI" sobre una serie que sube (97 → 99%): la comprobación era `sats[i] >= sats[i+1] - 0.05`, que tolera un aumento de 5 puntos. Tras el `c1 >= 4` del m5 y el criterio 4 de la mañana. **Patrón:** el criterio se redacta en prosa, se traduce a una comparación, y la traducción no se prueba contra un caso que deba fallar |
| 2026-08-05 | P4 | **Barrido de `?tn=` en banco, n=20** (155/162/168/175 intercalados) | **`tn=162` es el único que mejora de forma fiable**: 5/5 traspasos y `t_loss` efectivo mediano **0 → 14 ms**. `tn=155` entrega siempre con err 19,7–23,2°, del lado malo del cruce por cero. 168 y 175 entregan mejor (err 0,9–11,2, los dos mejores del día: 112 y 96 ms) pero disparan 2/5 y alargan el bombeo a 9,5 s con el brazo rozando el tope. **Recomendado: default 155 → 162**, a confirmar en otra sesión |
| 2026-08-05 | P4 | **Ajuste con los 29 traspasos de las dos campañas** (err de 0,9° a 23,2°) | `t_loss = −4,17·err + 90,2`, r = −0,865, **R² = 0,749** (el 0,914 de n=15 estaba inflado por una muestra estrecha). El **cruce por cero es estable**: err 21,6° ⇒ **α ≈ 158°**, contra 158,2 de la primera. Por debajo de eso el traspaso no sirve. **Ordenada 90 ms: con entrega perfecta el péndulo se pierde igual.** El techo pre-registrado (77 ms) se superó — la extrapolación lineal fuera de rango subestimaba |
| 2026-08-05 | P4 | **Campaña de banco n=15, tres condiciones intercaladas** (`experiments/2026-08-05_p4_gains/`) | 15/15 traspasan. **`corr(err de entrega, t_loss)` = −0,956, R² = 0,914**: la entrega explica el 91% de la varianza y las condiciones no aparecen. **H1+H2 descartadas** (quitar los 400 ms del catch mueve el residuo de −2,3 a −2,6 ms); **H7 descartada** (+3,6 ms contra ±11,4 de dispersión); **H3 re-confirmada** (saturado 86–98%) |
| 2026-08-05 | método | **Segundo veredicto mal implementado en dos días.** El script imprimió `H7 CONFIRMADA` | Comparaba medianas crudas sin descontar la entrega, que el criterio 6 —pre-registrado en el mismo documento— mandaba descontar. A `h7` le tocaron 4/5 entregas buenas contra 2/5 del control. Corregido: el criterio 4 se evalúa sobre el residuo. Mismo patrón que el `c1 >= 4` del m5 |
| 2026-08-05 | P4 + m5 | **Corregida la "concordancia 10/10"**: la relación es continua, no un escalón en 165° | Con 15 puntos que cubren 3,5–21,8° de error, `t_loss` cae 3,52 ms por grado y llega a cero en err ≈ 21,8° (α ≈ 158°). La concordancia perfecta de n=10 era artefacto de una muestra **partida en dos grupos** (155–158 y 165–179) sin nada en el medio: una rampa muestreada sólo en los extremos parece un escalón. Se sostiene lo importante — la entrega es la variable dominante y `SWINGUP_TRANS_NEAR = 155` entrega donde `t_loss` ya vale 0 |
| 2026-08-05 | método | **Corregida una lectura propia del mismo día** ("el péndulo no se cae, el brazo se va") | Salía de mirar el estado en la **última muestra** de trazas de 14 Hz con 5–20 muestras, en vez de la secuencia. A 500 Hz el orden es el inverso. Mismo error de forma que P6 y P11, esta vez en el análisis y no en el firmware |
| 2026-08-05 | P4 | **H7** (nueva, por lectura): `velTheta_ctrl` es −θ̇ mientras `theta` entra sin invertir, así que K3 anti-amortigua el brazo | Sin medir. El CARE pide K1 y K3 **negativas**, lo mismo por otro camino. Campaña con criterio pre-registrado en `experiments/2026-08-05_p4_gains/`; `lqr3` se A/B por HTTP sin reflashear |
| 2026-08-05 | P11 | **Medido** lo que hasta ahora era deducción, con el techo efectivo por muestra (`m5_pwm_sat.py`) | El bombeo satura **86,7–94,1%, mediana 92,5%** (n=10, `sp`=60). La prueba ingenua contra `sp` da **0,0%** siempre: el DAQ registra `lastPwmCmd`, o sea después de la atenuación por posición de `setMotor`. Tercer número de este experimento que salía de la instrumentación y no del equipo |
| 2026-08-05 | P2 | **Reserva n=2/n=4 levantada** sin repetir el `tr=0` | Con el traspaso armado y la referencia sana, **10/10 traspasan** con `E/E*` 0,955–1,001. La energía llega dentro de la ventana de captura. Lectura exacta: alcanza, y justo |
| 2026-08-05 | P23 | Registrado; comentario mentiroso de `:1521-1522` corregido | Hallado por lectura. El arreglo del firmware queda pendiente: no es lo que limita la energía |
| 2026-08-05 | doc | El comentario de `?pc=` describía un banco que ya no existe | La deriva del centro de oscilación (−18 a −36°) **no se reproduce** desde v1.58.8: n=10 da −6,8 a +16,0° (mediana 5,4). `pc` no tiene hoy nada que corregir |
| 2026-08-04 | P12 | **Re-medido con el bombeo sano** (v1.58.8, n=10, `experiments/2026-08-04_m5_swingup/`) | **θ en bombeo 49,2–80,1°** (mediana 70,0) contra un tope de 95: **14,9° de margen y 0/10 lo tocan**. Tras el traspaso, 94,0–94,8° en los diez — el tope lo alcanza el LQR, no el bombeo. P12 pasa a `NO ES DEFECTO`, esta vez con la referencia de α correcta y n=10 |
| 2026-08-04 | método | El script de m5 daba `PASS` con 5/10 porque el umbral estaba escrito `>= 4` | El criterio era "4 de 5" = **80%**, y así escrito no escala con n. Corregido a proporción, y el umbral se imprime junto al veredicto para que sea auditable. **El criterio 1 de m5 es FAIL (5/10), no PASS** |
| 2026-08-04 | P22 | Fase de quietud + re-cero del péndulo al entrar al modo 5 (v1.58.8), con el patrón de `H_WAIT_QUIET` | Con el cliente usando el protocolo **viejo**: **0/5 fallos** (antes 1/4), **5/5** con `E/E*` en rango y θ de bombeo 58–86°. Agotar el timeout es falla, no arranque a ciegas. `?sz=0` para el A/B |
| 2026-08-04 | P20 | **Corrección de la cifra**: se había cronometrado `rl_cmd`+`rl_state` | `QubeRealEnv.step()` usa `/rl_step` desde proto v3 — un solo round-trip. **38,3 ms → 26,1 Hz**, no 14,3. El defecto se sostiene (26 < 50) pero el número estaba mal por 2×, y el arreglo propuesto **ya existía** |
| 2026-08-04 | P12 | **Reabierto**: su "refutación" del mismo día se midió con la referencia de α corrida | Con el bombeo sano (`zp=1`) el brazo llega a **94,9°** contra un tope de 95, no a los 68° que se habían medido. Hay que re-medirlo con el protocolo corregido |
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
