# Verificación en banco de la Etapa 2 — el despachador serial por token

**Fecha:** 2026-08-06 · **Firmware:** v1.59.0 · **Motor:** SIN ENERGIZAR

Los cambios de la Etapa 2 compilan y pasan la suite, pero **nada de eso prueba que en la
placa `op30` mueva el cero del péndulo**. Los tests de `test_firmware_contract.py` leen el
`.ino` y verifican que el despachador *tiene* la forma correcta; que la forma correcta
produzca el efecto correcto sólo lo dice el banco.

## Por qué esta campaña es segura

**No energiza el motor y no entra a ningún modo que mueva.** Los seis comandos que la
Etapa 2 arregló son todos de offset y configuración: cambian variables, no PWM. La
verificación entera es *escribir una variable y leer `/state`*. Es la campaña más barata
del proyecto y la única que puede correrse con el banco en el estado que esté — incluso
con P24 sin resolver, porque no mide dinámica.

> Abrir el puerto serie **reinicia la placa**. Acá eso no molesta: la campaña arranca de
> cero a propósito. Lo que sí implica es que hay que rehacer el homing después, si se iba
> a usar el banco para otra cosa.

## Criterio de aceptación — escrito ANTES de medir

La forma de cada prueba es la misma, y es lo que distingue este arreglo de un cambio
cosmético: **se manda el comando largo y se verifica que movió lo suyo Y que NO movió lo
del comando corto con el que colisionaba.** La segunda mitad es la que falla en el
firmware viejo.

| # | comando | tiene que cambiar | tiene que quedar igual | qué hacía el firmware viejo |
|---|---|---|---|---|
| 1 | `o10` | `offset_deg` → 10 | — | (correcto ya) |
| 2 | `op25` | `pend_offset_deg` → 25 | **`offset_deg` sigue en 10** | ponía `offset_deg` en **0** |
| 3 | `zp` | `pend_offset_deg` cambia | **`offset_deg` sigue en 10** | cerraba el **servo** |
| 4 | `ed-1` | `encoder_dir` → −1 | — | (correcto ya) |
| 5 | `edp1` | `pend_dir` → 1 | **`encoder_dir` sigue en −1** | ponía `encoder_dir` en **1** |
| 6 | `cpr1024` | `counts_per_rev` → 1024 | — | (correcto ya) |
| 7 | `cprp2048` | `pend_counts_per_rev` → 2048 | **`counts_per_rev` sigue en 1024** | ignorado **en silencio** |
| 8 | `lqr230` | eco `[LQR] K2=30.000` | — | caía en `default` → imprimía la ayuda |
| 9 | `ke0.9` | `ke_gain` y `ke_override` → 0,9 | — | no existía por serie |
| 10 | `ke-1` | `ke_override` → −1 | — | no existía |
| 11 | `qq` (inválido) | eco `[ERR] comando desconocido` | — | imprimía la ayuda, indistinguible de un éxito |

**Criterio de etapa:** las once pasan. Una sola en rojo deja la Etapa 2 sin verificar,
porque todas comparten el mismo mecanismo.

### La prueba que de verdad importa

La 2, la 3, la 5 y la 7 son las únicas que el firmware viejo reprueba, y las cuatro
reprueban en la columna *"tiene que quedar igual"*. Si el script sólo mirara que
`pend_offset_deg` llegó a 25, **el firmware viejo también pasaría** — porque el viejo no
escribía nada ahí, y `pend_offset_deg` habría quedado en su valor previo, que podría ser
25 por casualidad si alguien lo dejó así. Por eso el script fija primero un valor conocido
en la variable que NO debe moverse.

Este proyecto lleva tres criterios bien escritos y mal implementados en dos días. El
bloque de veredicto de `verify_serial.py` se ejercita contra un estado sintético
construido para FALLAR antes de tocar la placa (`--selftest`), y el script se niega a
reportar si la placa no contestó a alguna lectura.

## P23: la prueba que no se puede hacer sin motor

Que `?ke=` sobreviva a `setMode(5)` **no se verifica acá**. Entrar al modo 5 arranca el
bombeo, y eso necesita motor y banco válido. La prueba 9/10 sólo confirma que el mando
escribe y se publica; que el lazo ya no lo pise es lectura de código más una corrida de
m5 pendiente.

## Resultados

### Mitad HTTP — 2026-08-06, **14/14 PASS**

Placa en SoftAP, flasheada por OTA (`flash.py --upload-only`, 1003 KB, reboot limpio).
Motor sin energizar en el sentido de que **`pwm = 0` en todas las lecturas**, aunque la
fuente estaba presente (`v_bus` 15,02 V, `ina_ok` true). Modo 0 de principio a fin.

```
placa v1.59.0 — mode=0 v_bus=15.02 ina_ok=True pwm=0
campos de /state: 86        (eran 82 antes del flasheo)

  ?ke=0.9              PASS   P23: fija override y lo publica
  ?ke=0.35             PASS   P23: se puede barrer
  ?ke=-1               PASS   P23: suelta el override
  ?edp=-1              PASS   pend_dir observable, servo intacto
  ?edp=1               PASS   vuelve
  ?cprp=1024           PASS   cpr del péndulo
  ?cprp=2048           PASS   vuelve al default
  ?o=10                PASS   offset servo
  ?op=25               PASS   offset péndulo, servo intacto
  ?o=0&?op=0           PASS   restaura
  ?lpm=100             PASS   techo del LQR (v1.58.9)
  ?lpm=70              PASS   restaura el default
  /rl_cmd?scale=0.5    PASS   lo lee m7, y ahora m6
  /rl_cmd?scale=1      PASS   restaura
```

Placa al terminar: `mode=0 pwm=0 ke_override=-1.0 v_bus=15.02`. Estado completo en
`data/state_antes_flash.json` y `data/state_despues.json`.

### Un FAIL que era del script, no de la placa

La primera corrida dio `?scale=0.5` **FAIL**. No es un defecto del firmware: `scale` vive
en `/rl_cmd`, no en `/cmd`, y el script lo estaba mandando al endpoint equivocado. Queda
anotado porque es exactamente el falso negativo que este proyecto ya pagó varias veces —
un criterio que reprueba por su propia causa y se lee como un defecto de la planta. Se
detectó leyendo el mensaje de fallo, no la marca PASS/FAIL.

(El script también se caía al imprimir ese fallo, por un carácter de caja contra una
consola cp1252. Un reporte de error que se rompe justo cuando hay algo que reportar.)

### Qué prueba y qué NO prueba esta mitad

**Prueba** que el mando `?ke=` escribe, se sostiene entre lecturas, se puede barrer y se
publica en `/state` — o sea que la **cañería** de P23 está sana. Y que agregar campos a
`getStateJson` no rompió la ruta HTTP de configuración.

**NO prueba la afirmación central de P23**, que es que *la rama adaptativa del bombeo ya
no pisa el override*. Ese pisoteo ocurría dentro del lazo del modo 5, y para verlo hay que
entrar al modo 5 y bombear. Con `homing_ok = false` y P24 sin resolver, esa corrida no se
hizo. **Lo que hoy sostiene esa mitad es lectura de código, no banco.**

**NO prueba nada del despachador serial**, que es el grueso de la Etapa 2: `op`, `zp`,
`edp`, `cprp` y `lqr1..4` son `hasParam` separados en `handleCmd`, así que por HTTP
siempre funcionaron. El defecto vivía en `processSerialCommand` y comprobarlo **exige un
cable USB**, que no había durante esta sesión.

### Mitad serie — 2026-08-06, **13/13 PASS · ETAPA 2 VERIFICADA**

Placa por USB en COM5, flasheada por cable. Modo 0, `v_bus` 15,04 V, motor sin mover.

```
  o10        PASS   referencia del servo, ya funcionaba
  op25       PASS   el viejo ponía offset_deg en 0
  zp         PASS   el viejo cerraba el SERVO
  ed-1       PASS   dirección del servo, ya funcionaba
  edp1       PASS   el viejo ponía encoder_dir en 1
  cpr1024    PASS   CPR del servo, ya funcionaba
  cprp2048   PASS   el viejo lo ignoraba en silencio
  lqr230     PASS   el viejo caía en default
  ke0.9      PASS   P23: no existía por serie
  ke-1       PASS   suelta el override
  vv         PASS   el viejo imprimía la ayuda
  q1         PASS   valor válido, se acepta
  qq         PASS   typo: se rechaza y NO toca el par

placa restaurada — mode=0 encoder_dir=1 cpr=2048.0 offset=0.0 ke_override=-1.0
```

Las cuatro que el firmware viejo reprobaba —`op25`, `zp`, `edp1`, `cprp2048`— pasan las
dos mitades del criterio: movieron lo suyo y **no** movieron lo del comando corto.

## Lo que encontró la campaña: `qq` apagaba el par del modo 7 en silencio

La primera corrida dio FAIL en la prueba de "comando desconocido", y el defecto no era
del firmware ni del criterio: **era la elección del token**. `qq` no es desconocido —
`q` tiene `case`, es la escala de par del modo 7 (`q<0..1>`). Y `String::toFloat("q")`
devuelve **0.0**, sin forma de distinguir *"el usuario pidió 0"* de *"el usuario se
equivocó"*.

Medido en placa: `rl_pwm_scale` 1,0 → **0,0**, sin imprimir absolutamente nada. Un typo
deja la política del modo 7 entregando torque nulo, y el modo se ve muerto sin ninguna
señal que lo explique. Con lo que se sabe hoy de m7 —FAIL en los tres puntos de su
criterio— es el tipo de causa que podría haber estado ahí todo el tiempo y nadie habría
podido distinguirla de "la política no sirve".

Afectaba igual a `s` (setpoint, que en modo 2 **mueve el brazo**), `o` (el cero del
servo, el mismo daño que hacía `op`), `p`, `op` y `ke`. Es la misma familia que las
colisiones de prefijo: **una entrada mal formada escribiendo un valor consecuente en
silencio.**

Arreglado con `parseSerialNumber()`, que rechaza lo que no sea un número completo y lo
dice. La prueba `qq` quedó en la campaña como regresión, verificando las dos mitades: que
se rechaza *y* que `rl_pwm_scale` no se movió.

> No lo encontró un test: lo encontró **correr la verificación en el fierro**. El test
> estático de la Etapa 1 no puede ver esto, porque `q` sí tiene `case` y `rl_pwm_scale`
> sí se lee.

## El script restaura el banco

La campaña deja `encoder_dir = -1`, `counts_per_rev = 1024`, `lqr_K2 = 30` y dos offsets
movidos. Irse así corrompe en silencio toda medición posterior. El script termina con
`reboot`, que devuelve **todo** a los defaults compilados —`Preferences` sólo guarda
credenciales WiFi— en vez de restaurar campo por campo, que es otra lista que puede quedar
incompleta. La primera versión no lo hacía.

## Segunda pasada: la clase entera, no una muestra — **27/27**

La primera corrección tocó **seis** comandos. Auditando el resto quedaban **diez** más en
la misma clase, dos de ellos peores que `q`: `L6 <val>` (que es `lqr_K2`, la ganancia
principal del LQR) y `kp/ki/kd`. Un typo ponía cualquiera de esas ganancias en cero, en
silencio.

`L<n>` tenía además un segundo defecto: un índice fuera de 1–12 caía en `default: break` y
**aun así imprimía `[LQR] g%d=%.3f`** — informaba éxito sin haber escrito nada.

La campaña pasó de 13 a 27 pruebas, cada typo con sus dos mitades (se rechaza *y* no mueve
lo que tocaba):

```
  o10 · op25 · zp · ed-1 · edp1 · cpr1024 · cprp2048 · lqr230   PASS
  ke0.9 · ke-1 · vv · q1 · qq                                   PASS
  s15 · sx · kp3.5 · kpx · kz1                                  PASS
  L6 25 · L6 x · L99 5 · gf2 · gfx · edx · m9 · mx · lqr2x      PASS

27/27 PASS — Etapa 2 VERIFICADA en placa
placa restaurada — mode=0 encoder_dir=1 cpr=2048.0 offset=0.0 ke_override=-1.0
```

La barrera estática nueva (`test_serial_arguments_are_validated_before_use`) encontró de
paso tres que la auditoría a mano había dejado: `ed`, `cpr` y `cprp`. **La revisión manual
falló donde el test acertó** — que es el argumento para tener el test.

## `hybrid_catch_*` por HTTP — parcial

Los cuatro parámetros del catch del m7 existían sólo por serial (`L8`–`L11`), o sea
inalcanzables durante una campaña. Ahora son `hcm`/`hcg`/`hcp`/`hca` y se publican.

Verificado por serie: los cuatro se publican en `/state` y `L8`–`L11` los escriben.
**Reserva honesta:** `L8 250` y `L10 40` coinciden con el default compilado, así que esas
dos comprobaciones no podían fallar; las decisivas fueron `L9` (0,2 contra 0,1) y `L11`
(12 contra 15).

**La ruta HTTP de estos cuatro quedó sin ejercitar.** Tras el reinicio por serial el PC no
volvió a asociarse al SoftAP (`netsh wlan connect` devuelve éxito y la interfaz queda
desconectada, con el AP visible). Es una corrida de `verify_http.py` cuando haya WiFi.

## Pendiente

1. **`verify_http.py` con WiFi** — cuatro comprobaciones, las de `hcm`/`hcg`/`hcp`/`hca`.
2. **Una corrida de m5** con banco válido, para cerrar P23 contra el lazo y no contra la
   cañería. Va detrás de la inspección del pivote (P24).
