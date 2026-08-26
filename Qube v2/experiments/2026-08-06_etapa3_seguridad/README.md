# Etapa 3 — la capa de seguridad, verificada en banco

**Fecha:** 2026-08-06 · **Firmware:** v1.60.0 · **Motor:** energizado (15,0 V), homing incluido

## Qué cambia

Tres defectos transversales de la máquina de modos, ninguno con número de problema propio:

1. **`homing_ok` no compuertaba nada.** Se escribía y se publicaba desde v1.53 y **ningún
   camino de código lo consultaba**. Se podía entrar a m2/m4/m5/m6/m7 sin haber hecho
   homing nunca, con `positionOffsetDeg = 0` — o sea con toda la escalera de límites del
   servo (70/80/85/90/95°) medida contra un cero arbitrario.
2. **La seguridad era por rama, no por sistema.** Brownout sólo en m4 y m5, duplicado
   literal, con `12.5`/`13.5` escritos a mano en cuatro sitios. m1, m2, m6 y **m7 no lo
   tenían** — y m7 es el que más corriente puede pedir. El INA219 se leía, se publicaba y
   **no se comparaba contra nada**: no existía límite de corriente en ninguna parte.
3. **m6 y m7 no tenían límite de ángulo del péndulo**, mientras m4 tenía dos. Importa por
   [P17]: el contador satura a las 16 vueltas y α deja de ser un ángulo; una política
   alimentada con basura sigue entregando acciones plausibles y nada lo denuncia.

## Criterio de aceptación — escrito ANTES de medir

| # | prueba | criterio |
|---|---|---|
| 1 | Sin homing, entrar a m2/m4/m5/m6/m7 | los cinco **rechazados**, `mode_reject=2`, `pwm=0` en todo momento |
| 2 | Sin homing, entrar a m0/m1 | **permitidos** (m1 lo mira el operador; m0 debe funcionar siempre) |
| 3 | Homing con recorrido válido | `homing_ok=true` **aunque no logre centrar** |
| 4 | Tras homing, entrar a m2 | **aceptado**, `mode_reject=0` |
| 5 | `/state` publica la capa | `homing_required`, `ina_required`, `mode_reject`, `brownout_cut_v`, `brownout_derate_v`, `current_limit_ma`, `safety_action`, `safety_cuts`, `safety_derates` |

**Nota sobre la prueba 1:** es intrínsecamente segura — si la compuerta funciona, el motor
no se mueve. Verificar un rechazo no puede romper nada.

## Resultados

**5/5.** La prueba 1 dio los cinco rechazos con `mode_reject=2` y `pwm=0`; m0 y m1 pasaron.

```
  modo  aceptado  reject  pwm   veredicto
  m2    False     2       0     RECHAZADO OK
  m4    False     2       0     RECHAZADO OK
  m5    False     2       0     RECHAZADO OK
  m6    False     2       0     RECHAZADO OK
  m7    False     2       0     RECHAZADO OK
  m1    True      0       0     PERMITIDO OK
  m0    True      0       0     PERMITIDO OK
```

`/state` pasa de 90 a **100 campos**.

## Lo que salió mal, y por qué importa

### Una hipótesis mía, medida y refutada

La primera versión metió la capa entera —brownout, derate y límite de corriente— dentro de
`setMotorDirect()`, que es el único punto que escribe el puente H. Parecía el lugar
correcto: cubre el lazo y el homing sin que haya que acordarse en cada rama.

El homing empezó a fallar con `code=4` (timeout al centrar). **Hipótesis inmediata: mi
cambio.** El homing usa `setMotorDirect()` justamente para saltarse toda modulación, y
cerca del centro su techo baja a 45 PWM; un derate de hasta 0,3 lo dejaría sin autoridad.
Encajaba perfecto.

Se midió antes de creerla: `derates=0`, `cuts=0`, **tensión mínima 14,84 V** — a más de un
volt del umbral de derate. *La capa de seguridad nunca intervino.* La hipótesis era falsa.

> Para poder medirlo hubo que agregar `safety_derates`, porque un derate era **invisible**:
> `safety_action` se limpia en el tick siguiente y `safety_cuts` sólo cuenta cortes. Un
> guardián sin contador no se puede acusar ni absolver.

El rediseño se mantuvo igual (corte duro en `setMotorDirect`, modulación en `setMotor`)
porque **es correcto con independencia de la causa**: el homing conduce contra los topes a
propósito, así que un límite de corriente ahí es lo contrario de lo que hace falta.

### El defecto real: el centrado entra en ciclo límite

Muestreando la posición durante `GOTO_CENTER`:

```
   t      raw_pos    error    pwm
  14.5    -116.54     34.37    -70
  14.7     -34.80    -47.37     70     <- cruzó el centro
  14.9      46.58   -128.76     70
  15.2    -105.47     23.29    -45
  15.4    -189.67    107.49    -70
  16.2      48.52   -130.69     70
```

El brazo **oscila de tope a tope** —de −210 a +48 raw, el recorrido entero— a PWM ±70, sin
asentarse nunca. Dentro de `HOMING_CENTER_SLOW_DEG` (30°) el techo baja a `HOMING_PWM_MIN`
(45), que está documentado como *"piso para vencer fricción estática"*: **usar el piso de
arranque como techo de aproximación**, con una ventana de ±5° y esta inercia, es un
bang-bang. Es P8 —"el brazo no siempre queda centrado"— manifestándose como fallo total.

**No se re-sintonizó a ciegas.** Se instrumentó (`homing_center_err`) y queda para una
sesión propia con datos.

### El arreglo: separar la calibración del estacionamiento

El cuadro de coordenadas queda determinado **en cuanto los dos topes están medidos y el
recorrido valida**. El cero es el centro geométrico *medido*, no donde quede el brazo — lo
decía el propio comentario del firmware. Parquear en el centro es una **comodidad**.

Las dos cosas estaban atadas a la misma bandera, así que un estacionamiento fallido tiraba
abajo una calibración perfectamente válida. Con la compuerta de esta etapa, eso dejaba el
banco **inutilizable** por un defecto que P8 ya tenía catalogado como no bloqueante.

Ahora `homing_ok` se fija al validar el recorrido y `homing_centered` reporta aparte.

**Medido tras el cambio:**

```
homing_ok       = True
homing_centered = False   err = -39.38 deg
rango = 270.352   centro = -75.586   fail = 0
position_deg (cero aplicado) = -61.348

m2 tras homing: mode=2 reject=0        -> ACEPTADO
m2 activo 1,5 s: pos = 1.23  pwm = 2
```

El brazo quedó 39° descentrado, **y m2 lo llevó a 1,23° en 1,5 s**. Que es exactamente la
mitigación que P8 ya documentaba (`QubeRealEnv` encadena `m2` tras el homing): el modo que
la compuerta estaba bloqueando es el que hace bien el trabajo que el homing no logra.

## Pendiente

1. **`bcut`, `bder`, `ilim`, `hr`, `sf` por HTTP** — son parámetros HTTP y esta sesión
   corrió por serie; el PC no volvió a asociarse al SoftAP tras los reinicios.
2. **Sintonía del centrado del homing (P8)** — con `homing_center_err` ya instrumentado.
   El bang-bang está medido; falta la sesión de ajuste.
3. **El límite de corriente nunca se ejercitó.** Default 2000 mA contra un máximo observado
   de 278 mA: no se puede provocar sin calar el motor a propósito. Queda declarado como
   guardián de sobrecorriente **sostenida** (3 lecturas a ~10 Hz), no como fusible rápido.
4. **La compuerta `sf` (INA219 caído) no se probó**: exige desconectar el sensor.
