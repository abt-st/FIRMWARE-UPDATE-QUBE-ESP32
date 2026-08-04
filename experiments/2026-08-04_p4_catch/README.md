# P4/H2 + H6 — la ventana del catch del LQR

**Criterio escrito ANTES de medir**, como en la campaña de P15. Firmware v1.58.5.

## Qué se mide y por qué

Dos defectos que viven los dos dentro de la ventana del catch del modo 4, y que por
eso no se pueden medir por separado sin controlarlos por separado:

**H2 — durante el catch el LQR no corre.** La rama del catch termina en `return`
(`esp32_qube.ino:3333`), así que durante `LQR_CATCH_MS` = 400 ms el controlador no
ejecuta ni un tick. Con ω_n = 14,34 rad/s (medida, P5) una desviación de la vertical
crece como `cosh(ω_n·t)`: **×155 en 400 ms**. Una entrega a 1,6° se convierte en caída
completa antes del primer tick de control.

**H6 — el periodo de gracia del centering nunca existió.** El bloque de centering
calculaba `centering_sec = (millis() - lqr_catchMs)/1000`, pero `lqr_catchMs` ya se
había puesto a cero al salir del catch, unas líneas más arriba. `millis() - 0` es el
uptime de la placa, siempre >> 2 s, así que `ramp` valía 1 **desde el primer tick**. El
comentario del propio bloque dice *"solo activo 2+ segundos después del catch; durante
los primeros 2 s el LQR necesita control total del servo"* — y eso no ocurría nunca. El
centering entraba a ganancia plena, con hasta ±25 PWM sobre un `LQR_PWM_MAX` de 70,
justo cuando el swing-up entrega con el brazo lejos del centro.

Es el mismo patrón de H1 y H4: un camino de código que no hace lo que su comentario
dice. Se descubrió leyendo el bloque, no midiendo.

## Diseño

`?lc=` (ms del catch) y `?cg=` (0/1, periodo de gracia) son configurables por HTTP
desde v1.58.5, **con defaults iguales al comportamiento anterior**: flashear no cambia
nada por sí solo y el A/B se hace sin reflashear.

| condición | lc | cg | qué aísla |
|---|---|---|---|
| control | 400 | 0 | comportamiento histórico |
| A | 400 | 1 | solo H6 |
| B | 100 | 0 | solo H2, catch corto |
| C | 0 | 0 | solo H2, sin catch |
| D | 0 | 1 | H2 + H6 juntos |

n = 4 por condición, **intercaladas** (rep externo, condición interno): la sesión de
banco deriva y medir en bloques confunde la deriva con el efecto.

La supervivencia se lee de `lqr_alive_ms`, **latcheado por el firmware** desde el fin
del catch hasta la salida del modo 4. No se infiere del muestreo del modo: a 25 Hz de
HTTP "sobrevivió 0,3 s" son 7 muestras. Cuenta desde el *fin* del catch a propósito —
contar los 400 ms en que el LQR no corre se los regalaría por igual a todas las
condiciones.

## Criterios, fijados de antemano

1. **El control tiene que reproducir el histórico.** Referencia del 2026-08-03:
   supervivencias de **0,48 / 0,55 / 3,33 s** (n=3). Si el control cae fuera de ese
   rango, el banco cambió y no hay nada que comparar — rehacer la línea base antes de
   leer ninguna otra condición. (Misma lógica que el paso 4.1 de `PLAN_TRABAJO_V2.md`,
   y el mismo control que en P6 falló su propio criterio y sirvió justamente para eso.)

2. **H2 se confirma** si la supervivencia crece de forma **monótona** al bajar `lc`
   (400 → 100 → 0) con `cg` fijo. Una sola condición mejor que las otras no basta: la
   dispersión intra-condición del 3 de agosto fue de 0,48 a 3,33 s, casi un factor 7.

3. **H6 se confirma** si `cg=1` mejora a `lc` fijo, en las dos filas donde aparece
   (400 y 0).

4. **Sólo cuentan los intentos con traspaso.** Un intento que no traspasó no dice nada
   del LQR. El script los reporta aparte y no los promedia.

5. **La calidad de la entrega es covariable, no ruido.** Cada intento registra
   `swing_trans_*` (α, vel, E/E*). Una condición que parezca mejor con entregas
   sistemáticamente mejores no probó nada sobre el LQR. Con P14 corregido las entregas
   vienen en 170,7–179,3° con E/E* ≈ 1,00, así que deberían ser comparables — pero hay
   que verificarlo, no suponerlo.

## Cómo correrlo

Con el PC asociado al SoftAP `QUBE-ESP32`, y el paro de emergencia
(`Invoke-RestMethod "http://192.168.4.1/cmd?x=1"`) a mano en otra consola:

```powershell
uv run python experiments\2026-08-04_p4_catch\scripts\catch_sweep.py --reps 4
```

El script hace homing con reposo del péndulo verificado antes de cada intento, y
**aborta si la placa no confirma la condición** que se le pidió — un barrido que en
realidad corrió todo con el mismo valor es el modo de fallo clásico de estas campañas.

## Resultados — 2026-08-04

20 intentos, 5 condiciones × 4, intercaladas. 19 con traspaso (el que faltó fue
`lc=100 rep1`). Datos crudos en `data/`: un CSV por intento más `sweep.json`.

| lc | cg | n | media | mediana | rango | α entrega | E/E* |
|---|---|---|---|---|---|---|---|
| 400 | 0 | 4 | 0,567 s | 0,575 | 0,369–0,750 | 165,2° | 0,981 |
| 400 | 1 | 4 | 0,806 s | 0,661 | 0,567–1,335 | 171,8° | 0,990 |
| 100 | 0 | 3 | 0,461 s | 0,543 | 0,040–0,800 | 170,7° | 0,993 |
| 0 | 0 | 4 | 0,406 s | 0,379 | 0,222–0,645 | 167,7° | 0,986 |
| 0 | 1 | 4 | 0,608 s | 0,451 | 0,318–1,214 | 166,0° | 0,985 |

**Criterio 1 — el control es válido.** 0,369/0,750/0,567/0,582 contiene los 0,48 y 0,55
del 3 de agosto. Los 3,33 s **no reaparecieron** en 4 intentos: era un outlier y no
debería seguir citándose como representativo.

**Criterio 2 — H2 no se sostiene, y falla en la dirección contraria.** Con `cg=0`:
400 → 0,567 s, 100 → 0,461 s, 0 → 0,406 s. Es monótona, pero **al revés de lo
predicho**: quitar el catch empeora. H2 era correcta en su mitad —durante el catch el
LQR efectivamente no corre— y ciega en la otra: el catch también **disipa energía**, y
sin él el LQR recibe un péndulo todavía en movimiento. La cuenta del `cosh(ω_n·t)`
medía el costo del catch y nunca su beneficio.

**Criterio 3 — H6 se sostiene.** `cg=1` mejora en las dos filas, en media y en mediana.
La fila limpia es `lc=0`, donde las entregas son equivalentes (166,0° vs 167,7°;
E/E* 0,985 vs 0,986) y aun así mejora. En `lc=400` la comparación está confundida: a
`cg=1` le tocaron entregas mejores (171,8° vs 165,2°).

### El hallazgo que no estaba en ninguna hipótesis

```
corr(α de entrega, supervivencia) = −0,088
corr(E/E*,        supervivencia) = −0,101     (n = 19)
```

**La calidad de la entrega no predice cuánto sobrevive el LQR.** Hubo entregas de 179,1°
con E/E* = 1,002 que aguantaron 0,582 s, y una de 157,2° que aguantó 1,335 s.

Eso da vuelta la premisa con la que P4 venía trabajando desde julio —*"P4 no es
evaluable hasta que el swing-up entregue bien"*—. Con P14 corregido el swing-up **ya
entrega bien**, y el LQR se cae igual en medio segundo. **El cuello no está en la
entrada, está en el controlador**: apunta a H3 (con estas escalas el LQR es un relé:
satura con 3,2° de error) y H5 (las ganancias del `.ino` son sintonía manual, no las que
diseña `lqr.py` por CARE en unidades SI).

### Lo que estos datos NO permiten afirmar

- n = 4 por condición, y la dispersión global es de **factor 33** (0,040 a 1,335 s). Las
  diferencias entre condiciones son chicas frente a la dispersión interna.
- La mejora de `cg=1` se apoya en buena medida en **un intento largo por grupo** (1,335
  y 1,214 s). En medianas queda en +15% y +19%, no en el +42%/+50% de las medias.
- La correlación nula está medida sobre un rango angosto de entregas (155°–179°, E/E*
  0,95–1,00): dice que *entre entregas buenas* la calidad no discrimina, no que la
  entrega nunca importe.
- La campaña la corrió el script de forma automática. Las trazas están en `data/`; lo
  que no está registrado es qué intentos se presenciaron en el banco.

### Trampa de análisis encontrada (vale para quien reuse `lqr_alive_ms`)

`lqr_alive_ms` **sobrevive a la caída a propósito**, para poder leerse sin carrera. Eso
obliga a todo consumidor a condicionar por "¿hubo traspaso en *este* intento?". Un
primer análisis parcial que tomaba el máximo sobre el CSV entero daba valores imposibles
—1335 ms en un intento con **cero** muestras en modo 4— porque arrastraba el valor del
intento anterior. El script lo hace bien; el análisis a mano se equivocó igual.

**Corrección propuesta, no aplicada:** limpiar `lqr_aliveMs` al entrar al modo 5. No se
tocó para no cambiar el firmware a mitad de campaña.
