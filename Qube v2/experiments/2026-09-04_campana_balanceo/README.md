# Campaña de balanceo: que el swing-up entregue un péndulo que se quede arriba

**Pregunta:** ¿alguna configuración cercana a los valores del firmware consigue que el
modo 4 sostenga el péndulo, en vez de perderlo en menos de dos segundos?

No es un barrido a ciegas. Las condiciones salen de hipótesis que ya están escritas en el
firmware y en `docs/REGISTRO_PROBLEMAS.md` ([P4]/H2, H3, H6 y la corrección H4), y ninguna
se aleja más de lo que esos comentarios ya proponen. **La respuesta corta es que no**: lo
que movió el banco fue corregir [P26], no ninguna perilla. Está todo en
[Resultados](#resultados--2026-09-04).

## Qué se mide

**Cuánto aguanta el modo 4 después de un traspaso desde el modo 5.** La definición de
éxito es la del propio firmware, no una inventada para esta campaña: sobrevivir
`LQR_SUCCESS_MS` = 3000 ms re-arma el presupuesto de reintentos
(`esp32_qube.ino:4587`). Por debajo de eso el firmware mismo considera que el intento
no prosperó.

`lqr_alive_ms` cuenta desde el **fin del catch**, no desde la entrada al modo, y deja
de actualizarse al salir del modo 4 conservando su valor final. Ese número miente de dos
formas, las dos encontradas a mitad de campaña y las dos con su caso en `autoprueba()`:

1. **No se pone en cero al entrar al modo 4.** Un episodio corto muestreado a 8 Hz se
   lleva la supervivencia del episodio anterior. Se acota contra el reloj de pared de la
   propia traza, que es un límite superior honesto y no depende de creerle al firmware.
2. **Un episodio que termina en `swing_fail_reason = 4` no es un balanceo.** Es
   `LQR_ARRIVE_TIMEOUT_MS`: el firmware se rinde a los 1500 ms porque el péndulo nunca
   llegó a 25° de la vertical. Quedan fuera de la estadística de supervivencia y se
   cuentan aparte, en `traspasos_sin_llegar`.

## Línea base y banda de ruido

⚠ **El banco deriva dentro de una misma sesión**, y una tanda de 5 minutos tiene mucha
dispersión por sí sola. Por eso `C0_base` se corre **al menos dos veces** por sesión y el
veredicto compara contra la envolvente `[mín, máx]` de esas bases, no contra una sola. Con
una sola base el script se niega a juzgar y devuelve `SIN BANDA`.

Las tandas de agosto (`../2026-08-30_reintento_ilimitado/`) están para dar contexto, **no**
para comparar contra ellas: son de otra sesión y de otro firmware.

## Condiciones

`BASE_CMD` —los defaults compilados— se manda **entero** antes de cada condición, así que
`cmd` lista sólo lo que cambia. Sin eso una condición hereda en silencio los parámetros de
la anterior, porque la placa no se reinicia entre tandas.

| | Cambio | Por qué |
|---|---|---|
| `C0_base` | defaults de fábrica | línea base de la sesión |
| `C1_pc1` | `pc` 0 → 1,0 | recentrado del bombeo: el centro de oscilación del brazo se sentó en −9,9° y toca −95 mientras del otro lado sobra recorrido |
| `C2_pc1_pr60` | `pr` 70 → 60 | deja 35° de margen al límite en vez de 25, a costa de energía por ciclo |
| `C3_lc0` | `lc` 400 → 0 | durante el catch el LQR **no corre**. Con ω_n = 14,34 rad/s una desviación crece ×155 en 400 ms ([P4]/H2) |
| `C4_lc200`, `C9_lc600`, `C10_lc800` | `lc` a ambos lados de 400 | barrido de la duración del catch |
| `C5_lpm110` | `lpm` 70 → 110 | con el techo en 70 sobre `PWM_MAX` = 200 la salida está saturada el 93 % del tiempo y las cuatro ganancias no pueden influir ([P4]/H3) |
| `C6_tn162` | `tn` 155 → 162 | el cruce por cero de la utilidad del traspaso cae en α ≈ 158 |
| `C7_k4_18` | `lqr4` 9 → 18 | al corregir H4 el K4 efectivo se redujo a la mitad y la sintonía previa nunca se rehízo |
| `C8_pc2` | `pc` → 2,0 | recentrado más fuerte |
| `C11_k1_4`, `C12_k1_4_lpm110` | `lqr1` 2 → 4 | la única ganancia que mira la **posición del brazo**, que es la falla dominante |
| `X_cg1` | `cg` 0 → 1 | [P4]/H6, fuera de la escalera: con los signos de v1.67.0 contradecía la evidencia |

## Veredicto

Cinco niveles, decididos en `veredicto()`:

- **LOGRADO** — al menos un intento aguantó ≥ 3 s.
- **MEJORA** — p50 **y** máximo por encima del techo de la banda de las bases.
- **NO SIRVE** — p50 o máximo por debajo del piso de la banda.
- **DENTRO DEL RUIDO** — cae dentro de la banda. No es un aval: es falta de resolución.
- **INVÁLIDA** — cero traspasos, o menos de dos bases (`SIN BANDA`).

`autoprueba()` corre el criterio contra siete trazas sintéticas antes de tocar la placa:
cinco que **deben** fallar y dos que deben pasar. Entre las que deben fallar están los
números reales de `C1_pc1`, que el criterio anterior aprobaba como mejora y caen dentro
del ruido. Sin eso, un criterio que aprueba pase lo que pase se ve igual que uno correcto.

## Lo que esta campaña no puede verificar

`/state` **no publica** `tn`, `sp`, `ke` ni `lqr4`. El script comprueba `lqr_catch_ms`,
`lqr_pwm_max`, `lqr_centering_grace` y `swing_retry_max` contra lo pedido, y deja los
otros cuatro declarados como no verificables en la cabecera de cada traza. Un 200 de
HTTP no es un parámetro aplicado.

## Cómo correrlo

```
python campana.py --lista            # condiciones + autoprueba del criterio
python campana.py C0_base 5          # una condición, 5 minutos
python analiza.py                    # dónde muere cada intento, por traza
```

Hace homing si hace falta (con reintento: un `homing_fail=1` aislado es un tope falso
por fricción, no un banco enfermo), registra `/state` a 8 Hz en `data/` y deja el banco
en modo 0 al terminar. Cada tanda deja su `*_resumen.json` junto a la traza. Las tandas
con el firmware anterior a la corrección de [P26] están en `data/pre_p26/` y **no son
comparables** con las de v1.68.0.

## Resultados — 2026-09-04

La campaña corrió 22 tandas de 5 minutos más una captura de 150 s a 500 Hz. Tres balanceos cruzaron los 3 s, todos con K4 subido, todos verificados por tres vías.
El resto del resultado no salió de mover parámetros.

### Lo que sí cambió el banco: P26

Las seis tandas con firmware v1.67.0 dijeron lo mismo tres veces: **23 de 28 intentos
mueren en el tope del brazo y ninguno con el péndulo caído**. Eso es exactamente lo que
predice [P26], confirmado en banco desde el 2026-08-21 y pendiente de corregir a
propósito. `homing_pwm_sign` volvió a medir −1 en las tres corridas de homing del día.

Se corrigió en v1.68.0 con el banco delante. El registro documentaba cuatro expresiones;
son **seis**: las dos comparaciones `stop_dir == pwm_dir` del modo 4 construyen
`stop_dir` en espacio de posición y lo comparan contra el signo de `pwm`, que ya salió de
multiplicar por `MOTOR_DIR`. Con el signo cruzado el limitador estrangulaba el PWM que
iba **al centro**.

| | v1.67.0 (n=2 bases) | v1.68.0 (n=2 bases) |
|---|---|---|
| Traspasos a m4 en 300 s | 8 y 14 | **17, 18, 25 y 26** (n=4 bases) |
| Supervivencia p50 | 380 y 452 ms | 187 y 360 ms |
| Mejor balanceo | 799 y 1174 ms | **1327 y 1455 ms** |
| Intentos ≥ 3 s | 0 | 0 |

El arreglo **duplicó los traspasos y subió el mejor balanceo unos 300 ms**. No subió la
mediana: con el doble de traspasos entran muchos marginales que antes no ocurrían, y la
mediana baja aunque la cola mejore. Decir que «duplicó la mediana» sería falso.

### Dos defectos de la métrica, encontrados a mitad de camino

Los dos inflaban el resultado y los dos están ahora en `autoprueba()` con un caso que
debe fallar. Salieron de una sola pregunta: por qué las dos líneas base daban un máximo
de **1502 ms exacto**.

1. **`lqr_alive_ms` no se pone en cero al entrar al modo 4.** Conserva el valor del
   episodio anterior hasta que termina el catch. Tres episodios de una sola muestra
   figuraban con 498, 1238 y 1501 ms heredados. Se acota contra el reloj de pared de la
   propia traza.
2. **Un episodio que termina en `swing_fail_reason = 4` no es un balanceo.** Es
   `LQR_ARRIVE_TIMEOUT_MS`: el firmware se rinde a los 1500 ms porque el péndulo nunca
   llegó a 25° de la vertical. Los cinco episodios de ese motivo daban 1501–1502 ms y
   arrastraban el máximo de la tanda entera.

### La banda de ruido, que es el otro resultado

Dos corridas de `C0_base` con parámetros **idénticos**, separadas por 20 minutos:

| | corrida 1 | corrida 2 |
|---|---|---|
| v1.67.0 | 8 traspasos, p50 380 ms | 14 traspasos, p50 452 ms |
| v1.68.0 | 18 traspasos, p50 360 ms | 17 traspasos, p50 187 ms |

Una tanda de 5 minutos rinde 17–18 traspasos y esa dispersión se traga casi cualquier
efecto. **Un criterio que compare contra una sola base declara «mejora» a la mitad de las
repeticiones de la propia base** — que es el error que este banco ya cometió tres veces.
Por eso el veredicto compara contra la envolvente `[mín, máx]` de las bases y tiene un
nivel `DENTRO DEL RUIDO` que no es un aval sino la falta de resolución.

### Veredictos

| condición | traspasos | p50 | máx | veredicto |
|---|---|---|---|---|
| `C1_pc1` (v1.67.0) | 19 | 540 ms | 1217 ms | mejora — **no reproducida**: `pc` no movió el centro del brazo en C3 ni C5 |
| `C3_lc0` (v1.67.0) | 13 | 183 ms | 269 ms | **no sirve** — 9 caídas del péndulo contra 1 |
| `C9_lc600` (v1.67.0) | 11 | 446 ms | 674 ms | no sirve |
| `C5_lpm110` (v1.68.0) | 16 | 556 ms | 1269 ms | **mixto**: mediana por encima de la banda y cero episodios que no llegaran a la vertical, pero el mejor balanceo por debajo. La regla, fijada antes de ver el dato, lo llama no sirve |
| `C11_k1_4` (v1.68.0) | 1 | — | — | **anómala, no utilizable**: 1 traspaso en 258 s contra 16–18 de las bases |
| `C12_k1_4_lpm110` (v1.68.0) | 23 | 441 ms | 1251 ms | **no sirve** — doblar K1 con techo de sobra tampoco frena la deriva |

`C3_lc0` refuta [P4]/H2 en su forma extrema: el catch **sí** hace trabajo útil. Sin él el
LQR recibe el péndulo con demasiada velocidad y lo pierde.

### Segunda mitad: el instrumento, y qué pasa dentro del modo 4

**El sondeo cuesta un atraso del lazo por petición, exacto.** Medido con el motor quieto,
cuatro ventanas de 45 s: sin muestrear, 1 overrun; muestreando a 8 Hz, **257 overruns
contra 256 peticiones**. La telemetría serial no influye (254 contra 257). El peor período
pasa de ~19 ms a ~22 ms sobre un nominal de 2000 µs.

Con balanceos de 1,3 s eso no era despreciable, así que se midió: una tanda idéntica a
**2 Hz** baja los atrasos de 1698 a 565 y da un mejor balanceo de **1329 ms contra una
banda de [1297, 1484]** a 8 Hz. **El instrumento no es lo que limita.** La sospecha era
razonable y quedó descartada midiendo, no argumentando.

**Lo que sí limita, sin ambigüedad: el recorrido del brazo.** De los 17 balanceos que
pasaron 1000 ms, **14 terminan con el brazo en el tope y sólo 3 con el péndulo caído**. Y
el histograma de 110 episodios se corta en 1484 ms sin ningún caso por encima de 1500;
los timeouts de llegada quedan limpiamente aparte, todos en 1501–1502 ms.

**Captura a 500 Hz por `/daq`** (`diagnostico_m4.py`, 75 100 muestras, 0 perdidas), porque
a 6 Hz un balanceo deja ocho muestras y con ocho no se decide nada:

| | |
|---|---|
| Deriva del brazo durante el balanceo | **−128 °/s** (mediana de 4 episodios) |
| α dentro del episodio | mediana +7,1°, **desviación de 11 a 24°** |
| PWM contra el techo **efectivo** por muestra | **28,6 %** del tiempo (21,5 % con el péndulo arriba) |
| PWM mediano | 42 sobre un techo de 70 |

A 128 °/s y con ±95° de recorrido, el brazo va del centro al tope en ~1,5 s: exactamente
lo que duran los balanceos. La deriva **no** se explica por un cero de α corrido — α no se
sienta en un valor fijo, oscila con desviación de 11 a 24° —, así que un trim de `op` no
es la respuesta.

**Y el 28,6 % re-abre [P4]/H5.** El registro tenía H3 medida en **43,6–100 %, mediana
70,4 %**, y de ahí la frase «el LQR es un relé a cualquier autoridad». Esa medición se hizo
con los seis signos de [P26] invertidos, cuando el *centering* sumaba hasta ±25 PWM en el
sentido equivocado y empujaba el total contra el techo. Con los signos corregidos el lazo
**ya no está pegado al techo**, lo que explica por qué `lpm` sigue sin hacer nada (C5 y C12
lo confirman de nuevo) y deja a las ganancias —H5— como la hipótesis viva, ahora medible en
un régimen que no es de relé.

> ⚠ La cuenta hay que hacerla contra el techo **efectivo por muestra**,
> `⌊lpm / (1 + (|θ|/200)²)⌋`, no contra `lpm`: la prueba ingenua contra el 70 literal da
> 14,2 % sobre los mismos datos. El registro ya advertía de esta trampa.

### El único balanceo que pasó los 3 segundos

`C13_k4_18` —`lqr4` 9 → 18, sola, todo lo demás en los defaults— produjo **un balanceo de
3408 ms**, el primero de la campaña y el primero registrado en este banco (el máximo de
agosto eran 1,76 s). Está verificado por tres vías independientes, porque la métrica ya
había mentido dos veces:

1. `lqr_alive_ms` sube de forma **monótona** a lo largo de 20 muestras seguidas, de 60 a
   3408 ms. No es un valor congelado heredado del episodio anterior.
2. **Reloj de pared:** el modo 4 duró de t = 62,10 s a t = 66,02 s, o sea 3910 ms. Menos
   los 400 ms del catch, 3510 ms. Concuerda.
3. **El propio firmware lo declaró:** `swing_retry_count` cayó de 4 a **0** en t = 65,50 s
   con `alive = 3083 ms`, que es exactamente lo que hace
   `if (lqr_aliveMs > LQR_SUCCESS_MS && swing_retryCount > 0) swing_retryCount = 0;`.
   Nadie mandó ese comando desde el PC.

**Pero no es reproducible, y hay que decirlo.** Tres tandas de la misma condición:

| tanda | traspasos | p50 | máx | brazo al tope | ≥ 3 s |
|---|---|---|---|---|---|
| 1 | 17 | 532 ms | 1395 ms | **4** | 0 |
| 2 | 20 | 554 ms | **3408 ms** | 9 | **1** |
| 3 | 19 | 414 ms | 1504 ms | 14 | 0 |

**Un éxito en 56 traspasos.** Y las fallas por tope —4, 9, 14— se mueven tanto entre
repeticiones que la caída a 4 de la primera tanda, que en el momento pareció el hallazgo
de la campaña, es ruido. Es el mismo error que la banda de bases estaba puesta para evitar,
cometido otra vez sobre un dato nuevo.

Lo que queda en pie de `C13`: es la única condición que **cruzó el umbral alguna vez**, y
el balanceo está documentado y verificado. No es una configuración que estabilice el
péndulo. `C14` (K4 18 + K2 30) deshizo lo poco que se veía: fallas por tope de vuelta en 11.

### Subir K4: tres balanceos por encima de 3 s, y por qué todavía no alcanza

El gain scheduling del LQR tiene tres tramos: `|α| < 5°` usa (K2 55, K4 20); `|α| < 25°`
usa (30, 15); el resto usa la base (22, 9). Medido a 500 Hz, **α oscila dentro del
episodio con desviación de 11 a 24° alrededor de una mediana de +7**, o sea que el
balanceo transcurre casi entero en la banda `near`.

Eso reinterpreta las dos condiciones de K4:

- **`C13_k4_18`** mueve `lqr4`, la K4 de la banda **base**, que sólo actúa con `|α| > 25°`
  — cuando el péndulo ya se está cayendo. Ayuda a recuperar, no a balancear.
- **`C15_k4n_25`** mueve `lqr4n`, la de la banda `near`: **el régimen de balanceo real.**

Agrupando todas las tandas de cada condición, que es la única lectura honesta cuando los
veredictos por tanda saltan tanto:

| condición | traspasos | ≥ 3 s | mejor balanceo | Fisher 1 cola |
|---|---|---|---|---|
| `C0_base` (5 tandas) | 100 | **0** | 1484 ms | — |
| `C13_k4_18` (3 tandas) | 56 | 1 | 3408 ms | p = 0,36 |
| `C15_k4n_25` (4 tandas) | 54 | **2** | **4663 ms** | p = 0,12 |
| todas con K4 subido | 123 | 3 | 4663 ms | **p = 0,17** |

**Sugerente, no establecido.** Con tres eventos, la prueba exacta no puede bajar de 0,05
por más que el efecto sea real; hace falta acumular traspasos. Lo que sí es difícil de
explicar por azar: en **100 traspasos** de línea base ningún episodio pasó de 1484 ms, y
con K4 subido hay tres por encima de 3000.

Los tres balanceos largos están verificados uno por uno igual que el primero: reloj de
pared concordante y **el contador de reintentos cayendo solo a cero** (3→0 con
`alive = 3094 ms`, 10→0 con `alive = 3037 ms`), que es el firmware declarando el éxito por
su cuenta. En la serie del episodio de 3798 ms se ve además la contaminación documentada:
las dos primeras muestras traen el 478 heredado del episodio anterior antes de reiniciarse
en 107 y subir limpio hasta 3798. La cota por reloj de pared la neutraliza.

**Y las tandas siguen saltando.** `C15` en cuatro repeticiones dio 4, 17, 26 y 7
traspasos; la de 26 tuvo los dos éxitos y la de 7 salió NO SIRVE. `C14` (K4 18 + K2 30)
deshizo el efecto. Nada de esto es una configuración que estabilice el péndulo a pedido.

### Una cuarta trampa del criterio: tandas sin potencia

`C15` en su primera tanda dio **4 traspasos** contra una banda base de 14 a 26, y el
criterio la declaró NO SIRVE. La línea base de control corrida inmediatamente después dio
14 traspasos y 28 reintentos: **el banco estaba sano y lo que falló fue el veredicto**. Una
tanda cuya supervivencia se calcula sobre cuatro episodios no es comparable con una de
veinte.

Ahora hay una compuerta: por debajo de la mitad del mínimo de traspasos de las bases, el
veredicto es `SIN POTENCIA` y la condición hay que repetirla antes de atribuirle nada. Con
ella, `C11_k1_4` (1 traspaso) y esa primera tanda de `C15` quedan fuera del cuadro en vez
de contar como evidencia en contra.

### Qué queda por hacer

- **Re-caracterizar las ganancias del LQR.** v1.68.0 dice explícitamente que ninguna
  sintonía anterior de m4/m5/m7 es transferible. `C11_k1_4` (K1 2 → 4, la única ganancia
  que mira la posición del brazo) quedó sin medir.
- **Repetir `C5_lpm110`.** Es lo único que subió la mediana por encima de la banda.
- **Cerrar `X_cg1`.** Con los signos corregidos, la hipótesis [P4]/H6 es una pregunta
  distinta a la de agosto.
- **Publicar `tn`, `sp`, `ke` y `lqr4` en `/state`.** Hoy no son verificables: el script
  los declara como tales en la cabecera de cada traza en vez de darlos por buenos.
- **El 62 % del tiempo se va esperando que el péndulo se aquiete** para el re-cero de
  [P22]. Es lo que limita la potencia estadística de una tanda de 5 minutos.

Durante la campaña la placa **se reinició sola** una vez entre tandas (perdió
`homing_ok` y `homing_pwm_sign`, `ms_since_cmd` de 10 min). Sin fusible ni bulk en el
banco, conviene anotarlo.

[P4]: ../../docs/REGISTRO_PROBLEMAS.md#p4
[P22]: ../../docs/REGISTRO_PROBLEMAS.md#p22
[P26]: ../../docs/REGISTRO_PROBLEMAS.md#p26
