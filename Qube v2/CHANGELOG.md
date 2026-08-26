## [app-0.3.0] — 2026-08-26

### «Aplicar modo» no hacía nada y la app no tenía nada que decir

**Sin cambios de firmware.** Es la capa de interfaz de `src/qube_app/` puesta al día con
tres versiones de firmware que le pasaron por encima: v1.60.0 (compuertas de entrada a
modo), v1.59.0 (P23 cerrado) y v1.63.0 (reintento del swing-up). El transporte y el
análisis no se tocaron.

#### Por qué pasaba

Desde v1.60.0 `setMode()` **rechaza** los modos 2/4/5/6/7 si no se hizo homing (`hr=1`,
por omisión activa) y 1/2/4/5/6/7 con el INA219 caído (`sf=1`). El rechazo es un `return`
temprano: el `GET /cmd?m=4` responde `200`, el modo no cambia y el único aviso sale por
Serial — que en este banco **no se puede abrir sin reiniciar la placa**.

Desde la app eso se veía así: se elegía «4 · LQR», se apretaba «Aplicar modo», la línea de
estado decía `→ /cmd {'m': 4}` y el encabezado seguía mostrando el modo anterior. Sin
error, sin aviso, sin nada. Indistinguible de un enlace caído o de un botón sin conectar,
que es justamente el defecto que app-0.2.0 vino a corregir en el mismo botón.

El firmware publica `mode_reject` en `/state` **desde la misma versión que introdujo la
compuerta**, precisamente para que un cliente pueda explicarlo. Ninguna de las dos
interfaces lo leía.

#### Por qué no lo agarró ninguna prueba

`FakeBoard` aceptaba cualquier `m=` y publicaba `homing_ok` clavado en `false`: la placa
simulada era **más permisiva que la real**, así que la ruta de comandos pasaba en verde
contra un simulador que no podía reproducir el fallo. Un simulador más permisivo que el
firmware no prueba la app, la aprueba.

Ahora `FakeBoard` replica `setMode()` con sus tres razones de rechazo, publica los campos
de v1.60.0/v1.63.0 y honra `hr=` y `sf=`. Arranca con `homed=True` para que `--fake` siga
abriendo con algo que mirar; los tests de la compuerta construyen la placa con
`homed=False`, que es como arranca una ESP32 recién encendida.

#### Cambios aplicados

| # | qué | dónde |
|---|---|---|
| 1 | `mode_reject` se lee y se informa en rojo, por flanco | `main_window._check_mode_reject` |
| 2 | El panel de control conoce las dos compuertas y avisa **antes** de mandar un modo que la placa va a descartar | `panels.ControlPanel.blocked_reason` |
| 3 | Estado del homing siempre visible: fase, recorrido, centro, `homing_pwm_sign` | `ControlPanel.homing_info` |
| 4 | Reintento del swing-up: `swing_retry_count`/`max`, recentrado, re-cero y motivo de la caída | `AnalysisPanel.update_attempt` |
| 5 | La capa de seguridad: `safety_action`, cortes y derates | `HealthPanel` + `poller.health` |
| 6 | `ke` deja de estar marcado como inerte | `panels.GAIN_GROUPS` |

**Sobre (2):** el aviso **no bloquea**. Se ofrece mandar el comando igual, porque la
autoridad sobre la compuerta es el firmware y una lectura de `/state` con un segundo de
antigüedad puede no reflejar un homing recién terminado. Y sin lectura de `/state` no se
advierte nada: no saber no es lo mismo que saber que no. Es el criterio que impide que
esta corrección se convierta en el defecto simétrico —una app que estorba comandos
legítimos— y tiene su test.

**Sobre (4):** `swing_retry_count` no es adorno. Con `rt=1` por omisión, «enganchó al
primer intento» y «enganchó al tercero» se leían igual en pantalla, y el reintento infla
las tasas de éxito en silencio.

**Sobre (6):** `ke` estaba marcado con `inert="P23"` y el tooltip decía que el firmware lo
pisa y que lo escrito «sobrevive milisegundos». **Eso se arregló en v1.59.0**: `ke ≥ 0`
fija un override que la rama adaptativa respeta, `ke < 0` lo suelta, y `/state` publica
`ke_gain` y `ke_override`. La marca se quedó puesta tres versiones de firmware de más,
desalentando un mando que ya funcionaba — el error simétrico del que la marca existe para
evitar. De paso el mínimo del campo baja a −1: con el piso en 0 no había forma de volver a
lo adaptativo desde la app sin un `curl`.

#### Barreras nuevas

`tests/test_app_ui.py` lee las dos compuertas **del `.ino`** y las compara con las listas
de la app, igual que ya hacía con los defaults de las ganancias: si allá se agrega o se
quita un modo y acá no, la app vuelve a ofrecer un botón que la placa descarta. Los
códigos de `mode_reject` se verifican del mismo modo — un código nuevo sin explicación
falla la prueba.

Los dos criterios se probaron contra el caso que **debe** fallar antes de darlos por
buenos: reintroducido el defecto (el rechazo sin informar, y la compuerta ignorando
`homing_ok`), las dos pruebas fallan.

#### Lo que NO se verificó

Todo lo anterior corrió contra la placa simulada. **Nada de esto se probó en banco**: no
hay corrida con motor energizado que confirme que el aviso aparece cuando la ESP32
rechaza de verdad. El camino sí está atado al firmware por los tests que leen el `.ino`,
pero eso verifica el contrato, no la corrida.

#### De paso, en la documentación

`docs/http_api.md` no documentaba `mode_reject`, `ina_required`, `safety_action`,
`safety_cuts`, `safety_derates`, `ke_gain` ni `ke_override` — siete campos que el firmware
publica y la referencia no mencionaba, que es parte de por qué la app se desincronizó.
Quedan en la tabla de `/state`. Y el comentario de `safety_lastAction` en el `.ino`
enumeraba 0–3 mientras la rama de [P17] escribe un 4.

## [1.63.0] — 2026-08-21

### Un intento de balanceo fallido ya no termina el trabajo: vuelve al centro y bombea de nuevo

Se pedía `m5`, el swing-up traspasaba a `m4`, y a los pocos cientos de milisegundos `/state`
reportaba `mode: 0`. Sin mensaje de falla y sin reintento: el banco quieto hasta que alguien
volviera a pedir `m5` a mano.

#### Por qué pasaba

El modo 4 tenía dos salidas cuando el catch fallaba, y la que ocurría no era la que parecía:

| salida | condición | destino |
|---|---|---|
| fin de carrera duro común | `\|pos\| > 95°` | `safeStop()` → **modo 0** |
| fallback del LQR | `\|pendPosRaw\| > 360°` | modo 5 |

El fallback a swing-up **ya existía** y es el comportamiento deseado, pero exige que el
péndulo dé una vuelta entera. Un LQR que no engancha satura hacia un lado —está contra su
techo la mayor parte del tiempo (P4/H3)— y deriva el brazo al tope mucho antes de eso. Gana
la primera fila, y la primera fila es un paro de emergencia.

Efecto de fondo: un catch caído a los 90 ms y un brazo que se fue al tope con el péndulo
arriba terminaban los dos en `mode: 0`, indistinguibles desde `/state`.

#### Cambios aplicados

**1. El intento fallido se detecta antes del tope (modo 4)**

`|α|` sostenido sobre 60° durante 150 ms (caída), o 1,5 s sin haberse acercado nunca a la
vertical (entrega mala). La caída exige haber estado **antes** dentro de 25° de la vertical:
sin esa condición el umbral se cumpliría en el primer tick —el traspaso entrega a hasta
(180 − `tn`) grados— y el reintento entraría en bucle sin llegar a intentar nada.

El caso «nunca llegó» sólo aplica si al modo 4 se llegó **por el traspaso**. Un `m4` pedido a
mano —el LQR de banco, con el péndulo sostenido— no se va solo a bombear.

**2. Fase de recentrado del modo 5, previa a la quietud de P22**

Es la ley del **modo 2 sin el integral**, con sus ganancias verificadas (`Kp`=3, `Kd`=0,45;
v1.58.5, 1,2 % de sobrepaso, 0 hunting): no se sintoniza nada nuevo a ciegas, se reusa el
único lazo de posición del brazo que está medido. El término derivativo **no es opcional** —
sin él esto es el bang-bang de `H_GOTO_CENTER` que P8 tiene catalogado, porque el piso de
fricción y el techo de aproximación son el mismo número.

Cierra con `homing_pwmSign` —el sentido **medido** en el propio banco, no `MOTOR_DIR`—, usa
`setMotorDirect()` y suelta el piso de PWM dentro de 25°. Queda **exenta del fin de carrera
duro** por la misma razón que lo está el homing: es la única rutina que puede sacar al brazo
de los 95°, y sólo conduce hacia el centro.

Sale cuando está **cerca y quieto** (12°, 40 °/s). Sólo «cerca» no basta: con el freno
dinámico del puente a PWM=0 (τ ≈ 0,47 s) el brazo que cruza la ventana a 150 °/s se sigue de
largo, y si alcanza el tope opuesto gasta otro reintento.

Dos guardias, no una: timeout de 5 s para el brazo que avanza pero no llega, y detector de
calado a 1,2 s —sólo en el tramo lejano— para el que no avanza nada. Sin el segundo, un signo
invertido serían 5 s de PWM 90 empujando contra el tope.

**3. Presupuesto de reintentos**

Tres consecutivos (`?rtn=`), reiniciado por cualquier modo pedido a mano y por un balanceo
que sobreviva 3 s. Agotado, `safeStop()` como antes. `?rt=0` restaura el comportamiento
previo exacto.

**4. Corregido de paso: un tick de PWM del LQR aplicado después del cambio de modo**

El fallback por vuelta llamaba a `setMode(5)` y **seguía de largo**; los ~20 renglones
restantes de la rama del modo 4 corrían igual y terminaban en un `setMotor()` con `mode` ya
en 5. Ahora retorna.

#### Hallazgo al margen, y es más grave que la corrección: P26

Buscando con qué signo debía cerrar el recentrado apareció que **`MOTOR_DIR` no está aplicado
en los términos que empujan el brazo al centro**, y sí en los lazos que los rodean:

| dónde | ¿`MOTOR_DIR`? |
|---|---|
| modo 2 (PID de posición) y homing (`H_GOTO_CENTER`) | **sí** |
| *centering* del LQR · «forzar centro» a >70° · freno de m5 a >90° · freno del híbrido m7 | **no** |

El modo 2 funciona medido, lo que obliga a que `homing_pwmSign = MOTOR_DIR = −1`. Con ese
valor, esas cuatro expresiones tienen el signo **invertido**: cada vez que el firmware cree
devolver el brazo al centro, lo empuja contra el tope. Predice exactamente el síntoma de P12 y
explicaría por qué todos los modos de balanceo derivan el servo al tope.

**No se corrigió en esta versión, a propósito**: son cuatro términos que cambian los modos 4,
5 y 7 a la vez, y es candidato a causa de fondo de P4. Se registra como
[P26](docs/REGISTRO_PROBLEMAS.md#p26) con el test que lo cierra en un minuto — `m3` y leer
`homing_pwm_sign`, que se publica en `/state` desde esta versión. El recentrado nuevo sí cierra
con `homing_pwmSign`, así que no hereda el defecto.

#### Superficie nueva

| dónde | campo | qué dice |
|---|---|---|
| `/cmd` | `rt` | Habilita el reintento (def. 1). `rt=0` = comportamiento previo |
| `/cmd` | `rtn` | Presupuesto de reintentos consecutivos (def. 3, 0–20) |
| `/state` | `swing_retry_count` | Reintentos consumidos en el intento en curso |
| `/state` | `swing_fail_reason` | 1 caída · 2 vuelta · 3 tope · 4 no llegó · 5 recentrado |
| `/state` | `swing_recenter_phase` | 1 = el brazo está volviendo al centro |
| `/state` | `homing_pwm_sign` | Sentido **medido** motor↔encoder del brazo (`0` = sin homing). Ver P26 |

`swing_retry_count` no es adorno: sin él, «enganchó al tercer intento» y «enganchó al
primero» se leen igual, y el reintento inflaría las tasas de éxito en silencio. Con
[P24](docs/REGISTRO_PROBLEMAS.md#p24) abierto y [P12](docs/REGISTRO_PROBLEMAS.md#p12)
`DEPENDE DEL ESTADO`, tres intentos con recentrado son además ~15 s de motor por corrida.

#### Corrido en banco el mismo día — y tres defectos corregidos ahí mismo

Seis trazas del DAQ a 500 Hz, en `experiments/2026-08-21_reintento_swingup/`. El reintento hace
lo que debe: **3 de 3 y luego 2 de 2 recentrados exitosos**, con el brazo volviendo de +97°/+103°
al centro en 0,6–1,1 s. La primera versión traía tres defectos, los tres visibles en las trazas:

| # | qué pasaba | evidencia | corrección |
|---|---|---|---|
| 1 | Con el motor suelto en la fase de quietud, **el péndulo se lleva el brazo por reacción** | de −6,2° a +96° en 1,1 s con `pwm` = 0 en **todas** las muestras | hold del brazo mientras haya un reintento en curso |
| 2 | El hold con banda única **se impedía a sí mismo arrancar** | brazo clavado en 19,5–20,0° durante 20 s dando pulsos de 50 PWM, con el péndulo quieto en ±1° | histéresis 35°/15° |
| 3 | El piso de fricción **re-lanzaba el freno** | `pwm` alternando −45/+45 entre muestras consecutivas — el bang-bang de P8 otra vez | el piso sólo se aplica al empuje, nunca al freno |

Pico del brazo a lo largo de las tandas: **134,56° (el tope mecánico) → 124,81° → 110,39°**, y el
timeout de quietud de 20 s desapareció.

**P26 quedó CONFIRMADO**: `homing_pwm_sign = −1` en las cinco corridas de homing de la sesión. Y
por vía independiente: en las cuatro tandas `swing_fail_reason` fue **siempre 3 (tope)** y la
detección de caída del péndulo **nunca llegó a dispararse** — el brazo llega al tope antes de que
el péndulo se caiga, que es exactamente lo que P26 predice.

**5. El corte por vueltas acumuladas también pasa por el reintento**

Era el último camino del modo 5 que caía a modo 0 sin gastar reintento. Se vio en banco: una
tanda terminó en `mode 0` con `swing_retry_count` en 0, indistinguible de un paro cualquiera
desde `/state`. Un péndulo embalado es un intento fallido como los demás.

#### Herramienta nueva: `src/firmware/flash_lento.py`

`flash.py` dejó de pasar contra la placa a mitad de la sesión: el POST de 1 MB se atasca
siempre alrededor de los 128 kB y el servidor deja de leer. Reiniciar, parar el DAQ y
reflashear no lo arreglan. El flasheador nuevo manda el cuerpo en bloques de 1460 B con 4 ms
de pausa, para que el lazo de 500 Hz y la tarea de AsyncTCP no se peleen: **1017 kB en ~17 s**,
verificado tres veces. Es la misma raíz que P28.

#### Lo que sigue sin ejercitarse

Los motivos de falla 1 (caída), 4 (nunca llegó) y 5 (recentrado imposible) no se dispararon
todavía en el hierro: mientras P26 esté sin corregir, todo termina por el motivo 3.

#### Advertencia sobre estas mediciones — P28

Se descubrió midiendo el OTA que **cada petición a `/state` o a `/cmd` le cuesta al lazo de
500 Hz una resincronización** (0,97 overruns por petición, contra 0,00 en `/rl_state` y
`/daq`). Las campañas de arriba sondearon `/state` mientras corrían, así que **se tomaron bajo
esa carga**. Las trazas del DAQ siguen siendo válidas —las muestrea y las marca temporalmente
el propio chip— pero conviene saberlo. La causa no está identificada; el tamaño de la
respuesta y la construcción del `String` ya se descartaron con medición. Ver
[P28](docs/REGISTRO_PROBLEMAS.md#p28).

---

## [1.62.0] — 2026-08-20

### Un LED de estado en GPIO13: lo que el monitor serie no puede decir sin reiniciar la placa

El banco no tenía testigo propio desde que se reemplazó el LED original. Un LED colgado del
riel de 5 V habría sido honesto pero redundante: esa información ya está en el LED del
LM2596. Lo que **no** se puede ver sin abrir `/state` es si el firmware arrancó y en qué
estado está el lazo — y consultarlo por USB no es gratis, porque abrir el monitor serie
reinicia la placa (DTR/RTS) y destruye el estado que se quería observar.

#### Elección del pin

`GPIO13` (izq. #3 del header, contiguo al `GND` de izq. #2). No es pin de strapping
(0, 2, 4, 5, 12, 15), no lo usa ninguno de los 9 GPIO de señal, y no es de los que puentea
`test_encoder_pulse_loss` (18/19/22/23). El LED se cablea entre dos posiciones vecinas del
header.

Queda en alta impedancia hasta que `setup()` configura el pin, y eso es deliberado:
**placa alimentada + LED apagado = el firmware no llegó a `setup()`**.

#### Cambios aplicados

**1. Patrones como máscara de bits**

Ciclo de 16 ranuras de 64 ms (1024 ms); el bit *i* dice si el LED está encendido en la
ranura *i*. La ranura sale de un shift sobre `millis()`, no de temporizadores propios.

| Estado | Patrón | Máscara |
|---|---|---|
| Alimentado, en reposo (`mode == 0`) | fijo | `0xFFFF` |
| Un modo con par activo (`mode != 0`) | 1 Hz simétrico | `0x00FF` |
| Homing en curso (`mode == 3`) | ~4 Hz | `0x3333` |
| INA219 caído (`!inaOk`) | doble destello + pausa | `0x0005` |
| Corte de seguridad u `H_FAIL` | ~8 Hz | `0x5555` |

**2. El patrón de INA219 caído tiene código propio a propósito**

Sin INA219 no hay corte por calado ni derate por tensión: el banco corre sin ninguna de las
dos protecciones y hoy eso sólo se ve consultando `ina_ok` en `/state`.

**3. Enganche del corte de seguridad**

`safety_lastAction` se limpia en el tick siguiente, así que un corte por tensión duraría
2 ms en el LED — nada. `serviceStatusLed()` se engancha de `safety_cutCount`, que sólo
crece, y sostiene el patrón de falla `STATUS_LED_FAULT_HOLD_MS` = 5 s.

**4. Tres destellos al entrar a `setup()`**

Antes de tocar SPIFFS, WiFi o I2C. Es lo que distingue un **boot loop** —tren de destellos
repetido, el síntoma del brownout del Cap. 7— de una placa que arrancó una sola vez.

#### Cambios de firmware

```cpp
static const int PIN_STATUS_LED = 13;
static const bool STATUS_LED_ACTIVE_HIGH = true;  // ánodo al GPIO, cátodo a GND

void serviceStatusLed();   // llamada desde loop(), tras el yield()
void statusLedBootFlash(); // llamada desde setup(), antes de SPIFFS/WiFi/I2C
```

#### Notas

- **Costo por vuelta de `loop()`:** una comparación; el `digitalWrite` sólo ocurre en el
  flanco (16 veces por segundo como máximo). No bloquea el lazo de 500 Hz.
- **Cableado:** `GPIO13 → 330 Ω → ánodo (pata larga) → cátodo a GND`. El nivel alto del
  GPIO es **3,3 V, no 5 V**: con Vf ≈ 2,1 V eso da ≈ 3,6 mA (470 Ω → 2,5 mA), muy por
  debajo de los 20 mA por pin. Un verde InGaN de Vf ≈ 3,1 V queda demasiado apagado a
  3,3 V y necesitaría ir a 5 V con transistor.
- **`/state` no se tocó:** el LED no publica ningún campo nuevo.
- **Estado de verificación:** compila (`pio run -e esp32dev`, SUCCESS, RAM 35,8 % / Flash
  78,7 %). **Sin verificar en placa** — ningún patrón fue observado en el banco, y el
  cableado del LED todavía no existe. Lo que hay que comprobar cuando se monte: los tres
  destellos de arranque, el fijo en reposo, el paso a 1 Hz al entrar a un modo con par, y
  el doble destello desconectando el INA219.

---

## [1.59.2] — 2026-08-06

### Los cuatro parámetros del catch del híbrido, por HTTP

`hcm`, `hcg`, `hcp`, `hca` — duración, ganancia, tope de PWM y ángulo del catch del modo 7.
Existían **sólo** por serial (`L8`–`L11`) y, como abrir el serial reinicia la placa, en la
práctica eran inalcanzables durante una campaña: toda tanda de m7 corrió con los defaults
compilados y no había forma de barrerlos. Mismo caso que `lc`/`cg`/`lpm`. Se publican en
`/state` por la misma razón que `lqr_pwm_max` — que una campaña verifique contra qué
valores está midiendo en vez de suponerlos.

`/state` pasa de 82 a **90 campos** en esta sesión.

**Verificado en placa** (COM5): los cuatro se publican y `L8`–`L11` los escriben. Reserva:
`L8 250` y `L10 40` coinciden con el default compilado, así que esas dos comprobaciones no
podían fallar; las decisivas fueron `L9` (0,2 contra 0,1) y `L11` (12 contra 15). La ruta
**HTTP** de estos cuatro quedó sin ejercitar: el PC no volvió a asociarse al SoftAP tras el
reinicio por serial. Es una línea de `verify_http.py` cuando haya WiFi.

---

## [1.59.1] — 2026-08-06

### Un typo apagaba el par del modo 7 en silencio

`String::toFloat()` devuelve `0.0` ante cualquier basura, sin forma de distinguir *"pidió
0"* de *"se equivocó"*. Medido en placa: **`qq`** —un typo de `q<0..1>`, la escala de par
del modo 7— puso `rl_pwm_scale` de 1,0 a **0,0 sin imprimir nada**. La política entrega
torque nulo y el modo se ve muerto sin ninguna señal que lo explique.

Con lo que se sabe hoy de m7 —FAIL en los tres puntos de su criterio— es el tipo de causa
que pudo haber estado ahí sin que nadie pudiera distinguirla de *"la política no sirve"*.
No se afirma que lo fuera: se afirma que **no había cómo descartarlo**.

Afectaba a **diez** comandos, no a uno. Los peores:

| comando | qué hacía un typo |
|---|---|
| `s<deg>` | setpoint a 0 — y en modo 2 el brazo **sale a buscarlo** |
| `L6 <val>` | `lqr_K2` a 0: el modo 4 se queda sin realimentación de α |
| `kp/ki/kd` | ganancia del PID a 0 |
| `o<deg>` | destruye el cero del servo, el mismo daño que hacía `op` |
| `q<0..1>` | par del modo 7 a 0 |

Y `L<n>` tenía un segundo defecto: un índice fuera de 1–12 caía en `default: break` y **aun
así imprimía `[LQR] g%d=%.3f`** — informaba éxito sin haber escrito nada.

`parseSerialNumber()` rechaza lo que no sea un número completo y lo dice. Es la misma
familia que las colisiones de prefijo de v1.59.0: **una entrada mal formada escribiendo un
valor consecuente en silencio.**

> **Lo encontró el banco, no la barrera.** El test de mandos inertes no puede ver esto:
> `q` sí tiene `case` y `rl_pwm_scale` sí se lee. Se agregó una barrera propia
> (`test_serial_arguments_are_validated_before_use`), que de paso encontró tres comandos
> más —`ed`, `cpr`, `cprp`— que la primera pasada había dejado.

---

## [1.59.0] — 2026-08-06

### El despachador serial mentía en seis de sus cuarenta comandos

Despachaba por `cmd.charAt(0)` pasando el resto como argumento. Eso funciona mientras
ningún comando anunciado sea **prefijo** de otro. Cuatro lo eran, y los cuatro estaban en
`printHelp()`:

| anunciado | entraba por | qué hacía en realidad |
|---|---|---|
| `op<deg>` | `case 'o'` | `toFloat("p30")` = 0 → **ponía el cero del servo en 0** |
| `zp` | `case 'z'` | cerraba el **servo**, no el péndulo |
| `edp<1\|-1>` | `case 'e'` | `encoderDir = 1`, no `pendulumDir` |
| `cprp<val>` | `case 'c'` | ignorado **en silencio** |

Y `lqr1`–`lqr4`, anunciados desde siempre, no tenían `case 'l'`: caían en `default`, que
imprimía la ayuda. **Las cuatro ganancias del LQR —el modo que el proyecto lleva ~90
corridas intentando arreglar— no se podían tocar por serie.**

Ahora hay un bloque de token completo antes del switch, de más largo a más corto. `ke` y
`kf` tienen gemelo serial, así que una campaña del swing-up o del LQR puede correr sin
WiFi. Y `default` ya no imprime la ayuda: la imprimía también ante un comando mal tipeado,
con lo que un error se veía igual que un éxito.

### P23 cerrado: `?ke=` era API que el propio lazo pisaba

`setMode(5)` deja `swing_maxAngleAchieved` en 0, y el primer tick con \|α\| > 5° ejecutaba
`ke_gain = KE_GAIN_BASE`. **Todo barrido de `ke` midió `KE_GAIN_BASE` contra sí mismo.**
`ke_gain_override` separa el mando manual de la rama adaptativa y sobrevive a la entrada al
modo, que es donde moría; `?ke=-1` lo suelta.

Y `ke_gain` **no se publicaba en `/state`**: un barrido no tenía cómo verificar contra qué
valor estaba midiendo. Ahora se publican `ke_gain` y `ke_override`.

Esto no calibra `ke_gain` ni cierra su barrido. Lo que cambia es que ahora *se puede*
barrer.

### Además

- **`/rl_cmd?scale=` deja de ser inerte en el modo 6.** Se aceptaba en cualquier modo y se
  publicaba, pero sólo lo leía el 7. Que la misma política vea una transferencia de par
  distinta según por dónde se despliegue es un riesgo de sim2real por sí mismo.
- **`/state` publica `pend_dir` y `pend_counts_per_rev`**, los gemelos que faltaban de
  `encoder_dir` y `counts_per_rev`. Entran en toda lectura de α —y por herencia en `E/E*`,
  en el ángulo de traspaso y en la observación del RL— y hasta hoy sólo se podían conocer
  leyendo el código.
- **Constantes muertas eliminadas:** `SWINGUP_TRANS_NEAR/PEAK/FORCED_DEG` no las leía
  ninguna rama desde que las compuertas pasaron a `swingupCatchDeg`, y arrastraban un
  comentario que mandaba *"exponer `SWINGUP_TRANS_NEAR_DEG`, que sí se usa"*: una
  instrucción falsa sobre código muerto.

**Todos los defaults reproducen el comportamiento anterior**, así que flashear no cambia
nada por sí solo.

### Verificación

**27/27 en placa por serie** (COM5) y **14/14 por HTTP**. Las cuatro pruebas que el
firmware viejo reprobaba pasan las dos mitades del criterio: movieron lo suyo **y no**
movieron lo del comando corto con el que colisionaban.

Sin verificar todavía: que `?ke=` sobreviva a `setMode(5)` en marcha. Eso arranca el bombeo
y necesita motor y banco válido; con `homing_ok = false` y [P24](docs/REGISTRO_PROBLEMAS.md#p24)
sin resolver no se hizo. **Esa mitad se apoya en lectura de código.**

---

## [app-0.2.0] — 2026-08-06

### La app de escritorio: el selector de modos no funcionaba, y otros seis defectos

**Sin cambios de firmware.** Todo es la capa de interfaz de `src/qube_app/`. El núcleo de
transporte y análisis (`stream.py`, `link.py`, `buffers.py`, `analysis.py`, `recorder.py`)
**no se tocó**: está validado en banco desde el 2026-08-03 y ninguno de estos defectos
estaba ahí.

> **Verificado en banco el mismo día** (`APP_ESCRITORIO.md` §6), motor energizado y péndulo
> libre: el selector arreglado aplica el modo pedido (`/state.mode = 6`), homing repite
> **270,527°** contra los 270,53° del 3 de agosto, y el swing-up completó el traspaso
> —`near+slow+energy`, α 156,27°, E/E\* 0,9577— con la cinta de modos y la marca sobre las
> trazas. Lo que quedó sin probar: escribir ganancias (no se pudo restaurar lo que hubiera
> en la placa) y el 2×2 de P15.

#### Y de paso: sondear `/state` durante la captura cuesta 2,4 % de las muestras

La GUI daba 490 Hz donde la autoprueba daba 500, con el motor en modo 0 en las dos. A/B
alternado, n=3, misma sesión:

| condición | tasa | `loop_overruns` | dt máx |
|---|---|---|---|
| DAQ solo | 500,1 · 500,1 · 500,1 Hz | 1 | 8,9–9,9 ms |
| DAQ + `/state` a 2 Hz | 490,3 · 483,3 · 491,1 Hz | 28 | 14,0–**239,4** ms |

Es **la misma firma** que `APP_ESCRITORIO.md` §6 atribuye al motor conmutando («~2 % de las
muestras, 19–32 overruns contra 3–9»), y aquel experimento se corrió dentro de la GUI, que
sondea. No prueba que el motor no cueste nada; prueba que **la atribución al motor no está
establecida**. Hace falta un 2×2 (motor × sondeo). La pausa de 239 ms con `dropped = 0` es
además la firma de [P15](docs/REGISTRO_PROBLEMAS.md#p15), acá sin motor: una pista, no una
conclusión.

#### El defecto que motivó la revisión

**El botón «Aplicar modo» mandaba siempre `m=0`.** `clicked` emite `checked=False`, y como
`isinstance(False, int)` es `True` en Python, ese `False` le ganaba al combo en
`ControlPanel._apply_mode`. Verificado ejecutando el panel:

```
combo currentData -> 4      (LQR seleccionado)
emitido -> {'m': False}     (se enviaba modo 0 = STOP)
```

El selector de modos **no funcionó nunca**: sólo llegaban al firmware los botones con
lambda explícita (`Homing (m3)`, `Set θ (m2)`, `Set PWM (m1)`).

#### El defecto más caro: el panel de ganancias reconfiguraba la placa

Los defaults no coincidían con el `.ino`, y «Enviar» los escribía:

| par | la app enviaba | firmware | efecto |
|---|---|---|---|
| `kd` | 0,15 | **0,45** | un tercio del derivativo |
| `ke` | 0,75 | **0,65** | +15 % de bombeo |
| `sp` | 200 | **60** | el firmware clampeaba a 100: casi el doble |
| `tn` | 175 | **155** | umbral de captura 20° más alto |
| `bt` | 20 | **no existe** | ignorado en silencio (heredado de `index.html:246`) |

Ahora los defaults y los rangos salen del firmware y **un test los verifica parseando el
`.ino`** — que es lo único que impide que vuelvan a divergir. Cada grupo envía **sólo los
campos que cambiaron**: tocar `kp` reescribía `ki` y `kd` con lo que la app creyera.

`/state` no publica las ganancias, así que la app no puede leerlas de vuelta. El panel lo
declara en pantalla en vez de fingir que sabe.

#### Los otros cinco

- **`--hz` y `--poll` se ignoraban.** Se guardaban en dos atributos que nadie leía.
- **El `StepDetector` no se reiniciaba entre capturas.** El reloj del DAQ vuelve a cero, así
  que un escalón viejo se remedía sobre la traza nueva con el setpoint anterior.
- **El paro decía «enviado» aunque hubiera fallado.** `stop_motor` devuelve `bool` tras 15
  intentos y nadie lo miraba. Ahora tiene ranura propia y pegajosa junto al botón: la
  compartida no servía —el propio paro cambia el modo a 0 y el aviso de cambio de modo le
  pisaba el resultado en la misma pasada—. Un test lo fija.
- **`Space` disparaba el paro.** Registrado con contexto de ventana, se robaba la barra
  espaciadora: navegar con el tabulador y confirmar era un paro. Queda sólo `Esc`.
- **Un `/state` parcial tumbaba el ciclo de análisis.** El formateo iba directo a
  `f"{valor:+.2f}"` y el `None` lanzaba dentro de un slot de `QTimer`.

#### I/O fuera del hilo de Qt (que era la regla declarada, e incumplida)

`APP_ESCRITORIO.md` §4 decía «ningún I/O en el hilo de Qt» y había cuatro violaciones.
La peor: cerrar con la placa muda podía congelar la ventana **hasta ~33 s** (15 reintentos
× 2 s de timeout). Arrancar y detener la adquisición pasan al hilo del sondeo, que ya era
el dueño del I/O, y el cierre espera con techo de 4 s.

#### Diagnóstico visible y reconexión

`errors`, `busy_503` y `last_error` se contaban desde el primer día y **no se mostraban en
ningún lado**: cuando `/daq/read` fallaba, la traza se congelaba sin explicación. Ahora
tienen fila propia, en rojo. Si el DAQ enmudece con errores, se reintenta solo — **salvo
grabando**, porque reconectar reinicia el reloj del DAQ en cero y dejaría una costura
invisible en medio del CSV. Ahí la decisión es del operador.

#### `--fake` completo

`FakeBoard` sirve el DAQ y `/state` desde el mismo estado, y `FakeLink` implementa la misma
superficie que `QubeLink`. Antes el modo simulado no levantaba el sondeo: salud del enlace,
escalón, traspaso, potencia y modo quedaban muertos y no había forma de trabajar la
interfaz sin banco. De paso desaparecen las ramas `if self.fake` de la ruta de comandos —
una rama que sólo corre en simulación es una rama que nadie prueba.

#### Interfaz

Barra superior con modo, θ, α, PWM y salud del enlace, alimentada por `/state` **aunque la
adquisición esté detenida** (antes la ventana arrancaba muerta). Panel lateral en pestañas:
el `QScrollArea` con la barra horizontal desactivada no recortaba los controles que no
entraban en 470 px, **los volvía inalcanzables**. Retrato de fase en un divisor, con altura
propia. Eje de tiempo sólo en la última traza. Hoja de estilos completa (`ui/theme.py`):
la anterior era una línea y dejaba botones, combos y spinboxes con el estilo nativo de
Windows sobre fondo oscuro.

La ventana de tiempo ahora **crece desde cero** mientras la captura es más corta que la
ventana: con 20 s pedidos y 9 s capturados, media gráfica quedaba en blanco y parecía
trabada. Sigue cuantizada al mismo cuarto de ventana, así que el eje se regenera con la
misma frecuencia y la optimización del §4.b queda intacta.

#### Cinta de modos y marca del traspaso

`mode` viajaba en cada muestra y no se dibujaba en ningún lado. Se probaron las dos formas:

| | CPU con la ventana llena |
|---|---|
| franjas translúcidas detrás de las cuatro trazas | **52 %** de un núcleo |
| cinta de modos sobre el mismo eje | **31,5 %** |
| sin ninguna de las dos | 31,6 % |

Las franjas de fondo cuestan **18 puntos** —cuatro rectángulos con alfa del tamaño del área
de dibujo, recompuestos en cada repintado— y la cinta cuesta **cero medible**. Después de
lo que costó bajar el pintado en este proyecto, no se le regalan 18 puntos a un sombreado.
La marca del traspaso m5→m4 sí va sobre las cuatro trazas, derivada de `swing_trans_ms_ago`
y por lo tanto con la incertidumbre del sondeo, igual que la potencia.

#### Presets

`settings.py`: juegos de ganancias con nombre y las preferencias de sesión (IP, ventana,
tasa, sondeo, carpeta de grabación) en `~/.qube_app/settings.json`. Cargar un preset
**rellena los campos y no envía nada**: escribir en la placa sigue siendo un acto
explícito. Un archivo corrupto no impide que la app abra.

---

## [sim] Fricción del péndulo medida — 2026-08-04

### `Dp` deja de ser un número inventado: 1e-6 → **7,52e-6** (medido)

**Sin cambios de firmware.** Cambia el simulador, y con él toda campaña de RL futura.

#### Lo medido

Spin-down libre del péndulo **con el brazo sujeto a mano**, n=2
(`experiments/2026-08-04_friction_spindown/`):

| | captura 1 | captura 2 |
|---|---|---|
| amplitud de suelta | 64,2° | 43,3° |
| el brazo se movió | 3,69° | 1,23° |
| λ | 0,0282 1/s | **0,0283 1/s** |
| t½ | 24,5 s | **24,5 s** |

`Dp = 2·Jp·λ = 7,52e-6`, o **7,5×** el nominal anterior.

**El amortiguamiento es viscoso**, que es el modelo que usa `QubeDynamics` (`Dp·α̇`). La
evidencia fuerte no es el R² (0,955 vs 0,926 para exponencial contra lineal: con un
decaimiento de factor 2 las dos curvas se parecen), sino que **λ es idéntico con
amplitudes de suelta de 64° y 43°**. Con fricción seca, un ajuste exponencial daría λ
dependiente de la amplitud.

#### Por qué el barrido de junio no podía funcionar

Probó multiplicadores de **20× a 130×**. La realidad es 7,5×: el valor más bajo del
barrido ya era **2,7 veces** la fricción real, y el más alto **17,3 veces**.

Peor: `Dp_std` era 5e-7, así que la aleatorización de dominio muestreaba `Dp` en
**[0, 2e-6]**. El valor real quedaba **fuera de la distribución entera** — no mal
centrada, sino sin intersección. Eso explica las dos cosas que junio dejó abiertas: por
qué el balance salía plano entre fr20 y fr130 (todos fuertemente sobreamortiguados
respecto del hierro), y por qué un modelo de 95% en sim dio hold ~0 en el rig.

`Dp_std` pasa a 1,5e-6 (20%): la medición repite al 0,4%, así que ese ancho ya no
representa ignorancia sino variabilidad real más robustez sim2real.

#### Lo que hizo que la medición sirviera

**Sujetar el brazo.** Con el brazo libre, todo el rango `Dp` ×1→×130 mueve el t½ de 1,20
a 0,41 s (factor 2,9): la energía se va por el acoplamiento al brazo y `Dp` casi no es
observable. Con el brazo bloqueado el mismo rango va de 174,7 a 1,4 s. **El experimento
de junio no estaba mal medido: estaba en el régimen equivocado.**

Se agregó `--lock-arm` a `measure_friction_spindown.py`. Ojo con la ecuación: un brazo
sujeto impone `thdd = 0` por reacción externa, así que **no** se puede tomar `aldd` de la
matriz de masa acoplada —eso supone el brazo libre de acelerar—. La restringida es
`Jp·aldd = −Dp·ald − c4·sin(al)`. Una primera versión ponía θ/θ̇ en cero pero seguía
usando el modelo acoplado: daba 12,09 rad/s donde la analítica da 10,68 y el hierro
mide 10,46.

#### Validación cruzada que salió gratis

La frecuencia natural con brazo fijo, `sqrt(c4/Jp)`, da **10,68 rad/s** contra los
**10,46 rad/s medidos**: 2%. La inercia que explicaría la medición difiere 4% de la de la
sim. **Los parámetros inerciales de la sim están bien**; lo que estaba mal era solo el
amortiguamiento.

> **Una hipótesis que se investigó y resultó FALSA, para que no se reponga:** que el
> `Dr = 5e-6` del brazo estuviera igual de mal porque el L298N frena el motor con
> `PWM = 0` (IN1=IN2=LOW cortocircuita los bornes) mientras la sim lo dejaría planear.
> **La sim ya modela ese freno**: su modelo de motor es `trq = n·km·(V − km·θ̇·n)/Rm`, que
> con `V=0` deja `trq = −(n²km²/Rm)·θ̇` = 2,1e-4, **42× el `Dr` mecánico**. Medido en la
> propia sim, el brazo desde 200°/s con acción 0 tiene τ = 0,47 s, no los 46 s que daría
> `Dr` solo. Medir `Dr` es una corrección del 2% sobre un término ya modelado.

## [1.58.5] — 2026-08-04

### La ventana del catch del LQR, medible por primera vez (P4/H2 + H6)

**Los defaults reproducen exactamente el comportamiento anterior.** Flashear esta
versión no cambia nada por sí solo: es instrumentación para poder medir dos defectos
que hasta ahora estaban soldados en el firmware, no una corrección de ninguno.

#### H2 — durante el catch el LQR no corre

La rama del catch termina en `return`, así que durante `LQR_CATCH_MS` = 400 ms el
controlador no ejecuta ni un tick. Con ω_n = 14,34 rad/s (medida, P5) una desviación de
la vertical crece como `cosh(ω_n·t)`: **×155 en 400 ms**. Una entrega a 1,6° es una
caída completa antes del primer tick de control.

`?lc=` (0–2000 ms, def. 400) hace configurable esa duración. **`lc=0` desactiva el catch**
y el LQR controla desde el primer tick.

#### H6 — el periodo de gracia del centering nunca existió

Hallazgo nuevo de esta versión, por lectura del bloque de centering del modo 4. El
código calculaba `centering_sec = (millis() - lqr_catchMs)/1000`, pero `lqr_catchMs` ya
se había puesto a cero al salir del catch, unas líneas más arriba. `millis() - 0` es el
**uptime de la placa**, siempre >> 2 s, así que `ramp` valía 1 desde el primer tick.

Su propio comentario dice *"solo activo 2+ segundos después del catch; durante los
primeros 2 s el LQR necesita control total del servo"* — **y eso no ocurría nunca.** El
centering entraba a ganancia plena, con hasta ±25 PWM sobre un `LQR_PWM_MAX` de 70,
justo cuando el swing-up entrega con el brazo lejos del centro.

Es el mismo patrón que H1 y H4: un camino de código que no hace lo que su comentario
dice. `?cg=` elige entre el comportamiento histórico (`0`, el default) y el documentado
(`1`), para medir la diferencia en vez de suponerla.

#### `lqr_alive_ms`: la supervivencia deja de inferirse desde el cliente

`/state` expone ahora `lqr_catch_ms`, `lqr_centering_grace` y `lqr_alive_ms`. El último
es la supervivencia del intento de balanceo, latcheada por el firmware, y **cuenta desde
el fin del catch, no desde la entrada al modo**: contar los 400 ms en que el LQR no corre
se los regalaría por igual a todas las condiciones del A/B. Se mide en el firmware por lo
mismo que `swing_trans_*` — a 25 Hz de HTTP, "sobrevivió 0,3 s" son 7 muestras.

El cronómetro se invalida en `resetLqr()` y se actualiza tick a tick dentro del modo 4:
al caer deja de actualizarse solo y el último valor *es* lo que aguantó. `lqr_aliveMs` no
se limpia al entrar al modo a propósito — tiene que sobrevivir a la caída para poder
leerse después sin carrera.

#### Verificación en banco

| prueba | resultado |
|---|---|
| Flasheo USB | 1.019.600 B, hash verificado |
| Campos nuevos en `/state` | los tres presentes |
| Defaults tras el arranque | `lc=400`, `cg=0` — el comportamiento histórico |
| `?lc=` / `?cg=` ida y vuelta | 4 de 4 confirmadas por `/state` |
| Saturación de `lc` | `9999` → `2000` |

#### Medido el mismo día: H2 refutada, y el cuello no es la entrada

20 intentos (5 condiciones × 4, intercaladas) en `experiments/2026-08-04_p4_catch/`.

| lc | cg | n | media | mediana |
|---|---|---|---|---|
| 400 | 0 | 4 | 0,567 s | 0,575 |
| 400 | 1 | 4 | 0,806 s | 0,661 |
| 100 | 0 | 3 | 0,461 s | 0,543 |
| 0 | 0 | 4 | 0,406 s | 0,379 |
| 0 | 1 | 4 | 0,608 s | 0,451 |

**H2 falla en la dirección contraria a la predicha.** Con `cg=0` la supervivencia baja
monótonamente al acortar el catch (0,567 → 0,461 → 0,406 s): **quitarlo empeora**. H2
era correcta en su mitad —durante el catch el LQR no corre— y ciega en la otra: el catch
también **disipa energía**. La cuenta del `cosh(ω_n·t)` medía su costo y nunca su
beneficio.

**H6 se sostiene**, en media y mediana, en las dos filas. La fila limpia es `lc=0`, con
entregas equivalentes entre `cg=0` y `cg=1`.

**Y el hallazgo que no estaba en ninguna hipótesis:** `corr(α de entrega, supervivencia)
= −0,088` y `corr(E/E*, supervivencia) = −0,101` sobre n=19. **La calidad de la entrega
no predice nada.** Hubo entregas de 179,1° con E/E* = 1,002 que aguantaron 0,582 s, y una
de 157,2° que aguantó 1,335 s. Eso da vuelta la premisa de P4 desde julio: con P14
corregido el swing-up ya entrega bien y el LQR se cae igual. **El cuello es el
controlador (H3/H5), no la entrada.**

El control reprodujo el histórico (contiene los 0,48 y 0,55 del 3 de agosto). Los 3,33 s
**no reaparecieron** en 4 intentos: era un outlier y no debería seguir citándose.

> **Lo que estos datos no permiten afirmar:** n=4 por condición con dispersión global de
> factor 33. La mejora de `cg=1` se apoya en un intento largo por grupo; en medianas es
> +15% y +19%, no el +42%/+50% de las medias.

> El flasheo OTA quedó bloqueado por el firewall de Windows (la red del SoftAP se
> clasifica como pública y la placa no puede abrir la conexión de vuelta);
> `platformio.ini` fija ahora `--host_port=39266` para poder abrir un solo puerto en vez
> de habilitar `python.exe` entero. Se flasheó por USB.

## [1.58.4] — 2026-08-04

### El bombeo no tenía techo de energía: el péndulo podía embalarse sin límite

#### El problema

La ley resonante (`pl=0`, la que corre por defecto) hace `pump_ref = alpha_dot * K`: cuanto
más rápido va el péndulo, más grande la referencia y más se bombea. **Es autorreforzante y
no tiene ningún término que la apague sola** — a diferencia de la ley de Åström-Furuta
(`pl=1`), donde el factor `(E* − E)` se encarga, como dice su propio comentario.

Consecuencia: **lo único que detenía el bombeo era el traspaso al LQR.** Si el traspaso no
dispara —o se desactiva con `tr=0`— no hay techo. Medido el 2026-08-04: **18 vueltas en
12 s**, suficiente para saturar el contador del encoder (P17) y dejar α sin sentido físico.

El anti-spin que ya existía no alcanza, y vale entender por qué: **frena el brazo**, y un
péndulo girando sobre un brazo quieto sólo pierde energía por fricción. El cooldown expira
y el bombeo vuelve a inyectar.

#### Los guardianes

- **Techo de energía** en la rama de bombeo: por encima de `E/E* > swingupEnergyCeiling`
  no se inyecta. Se deja en coast, no se frena: el freno actúa sobre el brazo y no le saca
  energía al péndulo, mientras que dejar de bombear sí la deja caer por fricción y damping.
- **Corte por vueltas** (`SWINGUP_MAX_TURNS = 3`) como respaldo: aborta a modo 0. El bombeo
  sano no completa ninguna vuelta; P2 necesita al menos una para medir la meseta con
  `tr=0`, así que 3 deja margen.
- **`?ec=` configurable y `swing_ceiling_hits` en `/state`.** No es adorno: un guardián que
  nunca se ejecutó no es un guardián, y esperar a la condición patológica no sirve porque
  es rara y además el brazo suele tocar el tope antes (P12).

#### Verificación en banco

| prueba | resultado |
|---|---|
| Techo forzado a `ec=0.35` | **179 cortes**, el péndulo se queda en ~43° en vez de acumular. **El camino de código ejecuta.** |
| Regresión con `ec=1.15` (producción) | Traspaso normal a los 4,8 s: `peak+energy`, **`E/E*` = 0,9550**, 0 vueltas |
| `tr=0`, `sp=45`, 18 s | 0 vueltas (antes: 18) |

> **El techo actúa ~53 veces en un swing-up normal**, sobre unos 2400 ticks. No es un
> fallo: `E/E*` supera transitoriamente 1,15 durante el bombeo sano y el guardián recorta
> ese exceso sin impedir el traspaso. Pero **no es cierto que "nunca actúe en operación
> normal"**, y conviene saberlo antes de leer `swing_ceiling_hits` como una alarma.

## [P15 — no reproducido] — 2026-08-03

### El colapso del lazo con el motor en marcha no sobrevive a un protocolo controlado

**Sin cambios de firmware ni de software.** Es una campaña de medición, con el criterio
escrito antes de medir: `experiments/2026-08-03_p15_loop/`.

Seis condiciones × n=3, 15 s cada una, intercaladas, corridas **dentro de la app** para ver
la traza mientras medía —el firmware admite un solo consumidor de `/daq/read`, así que
script y GUI no pueden leer en paralelo—.

**18 de 18 corridas entre 490 y 500 Hz, cero paradas sobre 20 ms, cero muestras perdidas.**
La réplica del protocolo original (dejar bombear 6 s para capturar al péndulo ya girando)
dio 500,2 Hz con máximo 8,7 ms, `pend_wraps = 5` y traspaso a α=176,84° con `E/E*` 0,9994.

Contra las corridas de la mañana en v1.58.2: 330,1 Hz con 214 ms de hueco, y 256,4 Hz con
488 ms. **P15 pasa a `NO REPRODUCIBLE`, que no es `RESUELTO`**: el fenómeno se midió tres
veces con instrumentos distintos, pero entre unas mediciones y otras la placa se reinició
(reflasheo OTA) y no hay forma de separar retroactivamente qué lo causaba. El registro deja
escrito qué capturar **antes** de reiniciar si vuelve a aparecer.

**Lo que sí quedó medido:** el motor conmutando le cuesta al lazo ~2 % de las muestras
(`m1_osc` 490,4 Hz y 19–32 overruns contra 498,7 y 3–9 en reposo). No es el que más
corriente pico tiene, así que lo que pesa es la **frecuencia de inversión del puente**, no
la corriente. Y apagar la línea serial (`sv=0`) o diezmar la telemetría (`tp=1000`) no
cambia nada: la hipótesis del costo de comunicaciones dentro del `loop()` queda sin
respaldo.

> Vale independientemente de P15: `loop_dt_max_us` marcó 17,3 ms en la corrida con un hueco
> de 488 ms. **Leerlo solo no permite descartar una parada del lazo** — hay que leerlo junto
> a `loop_overruns`.

## [1.58.3] — 2026-08-03

### P6 / etapa 4: `Kd` 0,15 → 0,45. El sobrepaso baja de 39,3 % a 8,4 %

Primer valor de sintonía de este proyecto elegido con un barrido medido sobre la traza a
500 Hz en vez de sobre `/state` a 25 Hz. Datos y protocolo en
`experiments/2026-08-03_p6_pid/`.

#### El barrido
Escalón +17° → −20° (cruza el cero), `kp=3.0`, `ki=0.5`, `se=2`, `sk=30`, repeticiones
intercaladas, reposo del péndulo verificado antes de cada punto.

| `kd` | sobrepaso | `sse` | cruces | pwm activo |
|---|---|---|---|---|
| 0,15 (anterior) | **39,3 %** | 2,70° | 0 | 1,00 |
| 0,30 | 21,6 % | 2,81° | 0 | 1,00 |
| **0,45** | **8,4 %** | 2,66° | 0 | 0,86 |
| 0,60 | 0,0 % | 3,11° | 0 | 0,86 |

Confirmado con **n=5** en 0,15 y 0,45: 37,6–39,4 % contra 7,9–8,8 %. **Las distribuciones
no se solapan**, el error de régimen no se degrada y no hubo hunting en ninguna corrida.
Se elige 0,45 y no 0,60 para dejar margen antes de que el derivativo amplifique ruido.

**Verificado tras el reflasheo OTA:** un escalón sin enviar ninguna ganancia da **9,5 %**.
El default viejo habría dado ~39 %.

#### Dos cosas que el mismo barrido dejó dichas, y no son buenas noticias

**El control del paso 4.1 falla su propio criterio.** Pedía reproducir el error de régimen
de ~4,8° con el kick viejo (`se=8`, `sk=12`) y da **2,45°**. La causa más probable es otra
vez la ventana de medición: los 4,8° salen de segmentos de 3,5 s, y hoy el mismo escalón
mide 7,7–15,9° con 5 s contra 2,7° con 14 s. Un `sse` tomado antes de que asiente no es un
error de régimen. **La línea base de P6 hay que rehacerla entera.**

**El kick anti-fricción no mueve la aguja:** 2,45° con los valores viejos contra 2,49° con
los nuevos, y la dispersión *dentro* de cada configuración (1,33–3,56) es **mayor** que la
diferencia *entre* configuraciones. Con n=2 no se puede resolver ni a favor ni en contra;
lo que sí se ve es `pwm_activo ≈ 1` con **0 cruces**, que es un tope por fricción estática
con el integrador apoyado contra él, no un ciclo límite.

> El tiempo de establecimiento no discrimina en esta campaña: la banda del 2 % son 0,74° y
> el error de régimen es ~2,8°, así que la respuesta nunca entra en la banda y la métrica
> queda saturada en el largo del segmento. Es un límite de la definición, no un dato de la
> planta.

## [1.58.2] — 2026-08-03

### `/daq/read` nunca sirvió un bloque: colisión de rutas con `/daq`

#### El síntoma
El primer intento de adquirir contra la placa devolvió
`magic 0x7670227b != 0x51414451`. Esos cuatro bytes son ASCII: `{"pv`. El endpoint
binario estaba respondiendo el **JSON de estado**, con `Content-Type: application/json`
y 148 bytes.

#### La causa
ESPAsyncWebServer acepta subrutas: `AsyncCallbackWebHandler::canHandle` compara con
`_uri != url && !url.startsWith(_uri + "/")` (`WebHandlerImpl.h:121`). Con

```cpp
server.on("/daq",      HTTP_GET, handleDaq);       // registrado PRIMERO
server.on("/daq/read", HTTP_GET, handleDaqRead);   // inalcanzable
```

`/daq` captura también `/daq/read`, y como los handlers se prueban en orden de registro,
el segundo nunca corría. **La adquisición por bloques no funcionó nunca**, desde que se
implementó en v1.57.0: sus 19 tests son sin hardware y el CLI nunca se había corrido en
banco, así que el defecto sobrevivió a la revisión de código y a la suite entera.

**Corregido:** `/daq/read` se registra antes que `/daq` (GET y OPTIONS), con el porqué
anotado en el fuente para que un reordenamiento cosmético no lo reintroduzca.

#### Verificación en banco — primera adquisición real del DAQ

`python -m qube_app --selftest --seconds 20`, brazo y péndulo en reposo, motor sin
energizar, PC asociado al SoftAP:

| métrica | resultado |
|---|---|
| muestras | **10.469** en 95 bloques, 20,93 s |
| tasa efectiva | **500,1 Hz** (nominal 500,0 · desvío +0,0 %) |
| muestras perdidas | **0** |
| intervalo | mediana **2,000 ms**, máx 8,99 ms |
| huecos (>1,5×) | 296 |
| 503 / errores de red | 0 / 0 |

Los 296 huecos son el lazo estirado por la radio, no muestras que falten: el contador de
perdidas está en cero y la tasa efectiva coincide con la nominal. Es exactamente la
distinción para la que existen los dos contadores separados.

**Costo sobre el lazo:** `loop_dt_max_us` dio 19.212 sin DAQ y 11.157 con DAQ;
`loop_overruns` 1 y 0. Con n=1 por condición y ambos números dominados por eventos de
radio, **lo único afirmable es que no se observó degradación atribuible a la captura**.
No es una medición del costo del DAQ; para eso hace falta repetirlo varias veces.

## [app-0.1.0] — 2026-08-03

### App de escritorio: trazas a 500 Hz, control y análisis en vivo

**Sin cambios de firmware.** Todo es software del PC (`src/qube_app/`), sobre el DAQ por
bloques que ya existía desde v1.57.0.

#### Qué resuelve
La GUI web se alimenta del WebSocket a 10 Hz: un transitorio de 400 ms —el catch del LQR,
la entrega del swing-up— cae en 4 muestras. El DAQ ya muestreaba a 500 Hz pero sólo sabía
grabar a CSV y graficar después. La app mira ese mismo transporte **mientras ocurre**.

#### Contenido
- `stream.py` — consumo incremental de `/daq/read` en un hilo; encadena el desenrollado
  de `micros()` y contabiliza perdidas, huecos y 503. `DaqClient.record()` no servía: se
  bloquea toda la captura y devuelve al final.
- `link.py` / `poller.py` — `/cmd` y `/state` fuera del hilo de Qt, paro de emergencia con
  bandera propia atendida antes que la cola de comandos, y modo **sólo lectura** para no
  ser un segundo escritor cuando corre un entrenamiento RL.
- `analysis.py` — métricas de escalón, α̇ derivada de α **sin envolver**, retrato de fase
  con corte en el envolvimiento, % upright y hold.
- `recorder.py` — CSV canónico + `t_pc_block_s` y `t_now_us` al final. Verificado que
  `qube_daq plot` lo relee sin adaptadores.
- `fake.py` — placa simulada que codifica con la misma función que decodifica el cliente.
- `ui/` — cuatro trazas, retrato de fase, paneles de control y barra de salud.

#### Costo en el PC: 88 % de un núcleo → 14 %
Perfilando en vez de suponiendo. Las optimizaciones del análisis (bucles de Python
vectorizados: `upright_stats` 14,0 → 1,9 ms; `derive_velocity` 3,9 → 1,9 ms; envolver α
sobre la ventana visible y no sobre la historia) **no movieron la aguja**: el costo estaba
en el pintado. Con las gráficas ocultas el proceso caía a 3 %.

Lo que sí lo movió: **avanzar la ventana de tiempo a saltos en vez de deslizarla**
(74 % → 19 %), porque cada cambio de rango regenera las marcas y rótulos de los cuatro
ejes; rango fijo en Y en vez de automático (→ 59 %); y lápiz de ancho 1 en vez de 1,4, que
deja de ser cosmético y Qt lo dibuja por el doble.

Dos cosas que **no** funcionaron, anotadas para que no se reintroduzcan: el diezmado
automático de pyqtgraph salió peor (19,1 contra 16,4 ms/cuadro), y diezmar a mano de
10.000 a 1.000 puntos apenas bajó de 8,2 a 7,4 ms — el costo es **fijo por repintado**, no
por punto. Detalle en `docs/mine/APP_ESCRITORIO.md` §4.b.

#### Distribución
- `scripts/QUBE App.cmd` — doble clic, corre el código actual del repositorio.
- `make exe` → `dist/QubeApp/QubeApp.exe` (~167 MB) con PyInstaller, para llevar el banco
  a una máquina sin Python. **onedir** y no `--onefile` (que se descomprime en `%TEMP%`
  en cada arranque), con consola porque la autoprueba reporta ahí, y con torch/SB3/
  mlflow/matplotlib excluidos: están en el entorno y sin excluirlos el bundle son GB.
- La consola se pone en UTF-8 al arrancar: empaquetada arranca en la página heredada y
  los rótulos del proyecto (°, α, θ, ·) salían como basura.

#### `compute_overshoot_step` en `qube_analysis/metrics.py`
`compute_overshoot` normaliza por `|setpoint|`: en un escalón que cruza el cero **duplica**
la cifra (68–77 % contra 39–42 % reales sobre las trazas del 30-jul). Se agrega la función
correcta **sin tocar la vieja**, y la app muestra las dos —la nueva y la *legacy*— para
poder empalmar con las campañas anteriores.

#### Verificación
37 tests nuevos sin hardware (encadenado de bloques, wrap de `micros()`, hueco entre
bloques, anillos, sólo lectura, sobrepaso correcto vs legacy, esquema del CSV, arranque
de la ventana offscreen). `ruff` y `pyright` limpios en `src/qube_app`.

#### Sesión completa en banco — 2026-08-03
Sentido de giro (criterio de lazo abierto), homing **270,53°**, escalón `m2` +17 → −20
con sobrepaso **36,5 / 37,7 / 38,4 %** (n=3) y `sse` 2,72°, y swing-up con traspaso
`peak` a α=157,15° y `E/E* = 0,9615`. La app midió todo sobre la traza a 500 Hz.

> **Y encontró P15 el primer día.** Con el motor bombeando la tasa efectiva cae a
> **256–330 Hz** con paradas de hasta **488 ms**, y `dropped = 0` en todas las corridas:
> las muestras no se produjeron, no se perdieron en el enlace. Además `loop_dt_max_us`
> marcó 17,3 ms en esa misma corrida — **la métrica de salud del firmware no ve estas
> paradas**; sí las ve `loop_overruns`. Causa sin establecer, n=1 por condición con
> motor. Detalle y plan en `docs/REGISTRO_PROBLEMAS.md` P15.

## [1.58.1] — 2026-08-03

### P4 / H1 y H4: el catch medía desplazamiento acumulado y `k4_eff` era el doble

#### H1 — `lqr_prevAlpha` congelado durante el catch
La rama del catch termina en `return`, así que se saltaba el `lqr_prevAlpha = alpha_raw`
de más abajo. Durante los 400 ms de `LQR_CATCH_MS` la referencia quedaba congelada en el
valor de entrada, y `-(pendPosRaw - lqr_prevAlpha)/dt` dividía el desplazamiento
**acumulado** por un tick de 2 ms: 30° acumulados daban 15.000 °/s y el freno saturaba
contra `LQR_CATCH_PWM` (25) casi de inmediato. Peor: la dirección se fijaba en los primeros
10 ms desde esa misma lectura, que con una entrega buena (vel ≈ 0) es ruido de una cuenta
de encoder — 400 ms de empuje constante de ±25 PWM en un sentido esencialmente aleatorio.

**Corregido:** `lqr_prevAlpha = pendPosRaw` dentro de la rama; la derivada vuelve a ser por
tick.

#### H4 — un `RAD_TO_DEG` de más en el escalado por velocidad
`velAlpha_ctrl` **ya está en deg/s** en el modo 4: sale de `lqr_filteredVelAlpha`, que
deriva `pendPosRaw` (grados), o de `kf_x[3]`, que `kalmanUpdate` alimenta también con
grados. El `* RAD_TO_DEG` hacía que el umbral de 200 se cruzara con **3,5 °/s reales** y que
`vel_scale` topara en 2,0 con **8,7 °/s**: `k4_eff` era el **doble** del declarado casi
siempre. No era gain scheduling, era una constante escondida.

El gemelo del modo 7 (`:3828`) ya lo hacía bien, y su comentario lo dice: *"velAlpha_ctrl is
deg/s"*. Las dos líneas no podían estar bien a la vez; la del modo 4 era la equivocada.

**Corregido:** `vel_alpha_dps = fabsf(velAlpha_ctrl)`, sin conversión.

> **El `k4` efectivo se reduce a la mitad.** Cualquier sintonía previa de `lqr_K4` hay que
> rehacerla. Se puede barrer por HTTP con `lqr4=` sin reflashear.

#### Verificación en banco — 5 ciclos swing-up → LQR

| ciclo | criterio | α entrega | vel (°/s) | `E/E*` | supervivencia |
|---|---|---|---|---|---|
| 1 | near+slow+forced+energy | −175,25° | 16,0 | 0,9983 | 0,48 s |
| 2 | — | — | — | — | sin traspaso |
| 3 | peak+forced | −174,55° | 77,6 | 0,9987 | 0,55 s |
| 4 | — | — | — | — | sin traspaso |
| 5 | forced | 173,85° | 109,3 | 0,9990 | **3,33 s** |

Línea base: **0,3 s**, idéntica el 30-jul y en las dos campañas del 03-ago. El mejor caso
es un orden de magnitud más.

#### Lo que estos datos dicen del siguiente paso (H2)
Las supervivencias de 0,48 y 0,55 s son `LQR_CATCH_MS` (0,4 s) **más 80–150 ms de LQR
real**: en esos ciclos el controlador apenas alcanzó a correr. El ciclo 5 son 0,4 s de catch
más **2,9 s de LQR sosteniendo**. **H2 —los 400 ms sin control— pasa a ser el cuello.**

No sobreinterpretar con n=3: la entrega más lenta (16 °/s) sobrevivió menos que la más
rápida (109 °/s). Puede ser que el freno del catch, ya honesto, sólo haga trabajo útil
cuando hay velocidad que frenar. Son tres puntos.

## [1.58.0] — 2026-08-03

### Homing: frenado de aproximación al tope

#### Motivación
- El homing llegaba al tope a `HOMING_PWM_SEEK` = 70 y golpeaba a plena marcha.

#### Por qué no se baja el seek y ya
- Es exactamente lo que se hizo en v1.53.2 para suavizar el impacto, y **causó P3**: a 55
  el brazo no siempre vence el punto duro que hay a ~119° del centro, se cala ahí y acepta
  un cero corrido de 16°. `HOMING_PWM_SEEK` volvió a 70 por esa razón y se queda en 70.
- Acortar `HOMING_STALL_MS` tampoco sirve: reduce el tiempo de presión **después** del
  golpe, no el golpe. La energía de impacto la fija la velocidad de llegada.

#### Cambios aplicados
- **`HOMING_SEEK_SLOW_DEG = 8.0`**: el seek mantiene 70 y baja a `HOMING_PWM_TOUCH` (55)
  en los últimos 8°. El umbral es deliberadamente **menor que los ~16°** que separan el
  punto duro (119°) del tope (135°): frenar antes sería reintroducir P3.
- Predicción del tope, sin estado persistente en NVS y sin depender del signo del cableado:
  - **Segundo tope:** distancia recorrida desde el primero, ya medido en esa misma corrida.
    Se usa `fabsf(rawPos - homing_stopPosRaw)` para no depender de `homing_pwmSign`, que
    recién se aprende al terminar el toque negativo.
  - **Primer tope:** medición de la corrida anterior (`homing_prevStopPosRaw`), sembrada
    **sólo** si esa corrida pasó la validación de recorrido. Sin memoria válida no frena:
    el comportamiento cae al anterior en vez de frenar a ciegas.

#### Verificación en banco (6 homings consecutivos)
| | antes (v1.57.2) | después |
|---|---|---|
| éxitos | 5/5 y 3/3 | **6/6** |
| rango | 270,35–270,70 | **270,176 en las 6** |
| dispersión tope + | 0,17° (1 cuenta) | **0,000°** |
| dispersión tope − | 0,53° (3 cuentas) | **0,000°** |

La repetibilidad pasa de 1–3 cuentas a **cero**: llegando frenado el brazo se cala siempre
en la misma cuenta. El rango queda 0,2–0,5° más corto, coherente con comprimir menos el
tope.

#### Lo que NO está medido
La reducción de la fuerza de impacto **no se cuantificó**. El muestreo de corriente por
HTTP va a ~2,5 Hz y el transitorio del golpe dura milisegundos, así que los picos de
120–129 mA registrados no son comparables con nada. Lo que sí está medido es que la
aproximación ocurre a 55 en vez de 70 y que la medición se volvió perfectamente repetible.

## [1.57.2] — 2026-08-03

### P14: las cuatro compuertas de traspaso comparaban un ángulo sin acotar

#### Problema identificado
- Las cuatro condiciones que disparan el traspaso m5→m4 comparaban `fabsf(pendPos)`
  contra sus umbrales **sin acotar `pendPos` a [−180, 180]**. Si el péndulo acumula una
  vuelta, `pendPos` se va fuera del rango y `|pendPos|` supera cualquier umbral hasta 178
  con el péndulo **lejos** de la vertical.
- `wrapPendulumTurns()` (P13) sí acota, pero sólo se llama en las ramas de spin y de
  recovery. Entre medio `pendPos` puede pasarse sin que nadie lo corrija.

#### Evidencia medida (2026-08-03, campaña de bring-up run 2, m5)

| `trans_alpha` latcheado | ángulo real | dista de vertical | reportó | correspondía |
|---|---|---|---|---|
| −199,16° | 160,84° | 19,2° | near+slow+**forced**+energy | `forced` es falso (160,84 < 165) |
| −223,42° | 136,58° | **43,4°** | near+slow+forced | **ninguna**: 136,58 < 155 |

La segunda repetición traspasó con el péndulo a 43° de la vertical y `E/E*` = 0,863 — una
entrega que el LQR no puede sostener. En ambas, `swing_trans_vel = 0,00` **exacto**, así
que la compuerta de velocidad también se cumplía trivialmente: las dos mitades del criterio
se satisfacían de forma espuria a la vez.

#### Cambios de firmware
```cpp
// Acotado local para la EVALUACION; el estado y el offset los sigue manejando
// wrapPendulumTurns() (P13). No se toca el cero.
float pendPosWrapped = fmodf(pendPos + 180.0f, 360.0f);
if (pendPosWrapped < 0.0f) pendPosWrapped += 360.0f;
pendPosWrapped -= 180.0f;
```
- `nearVertical`, `atPeakTransition`, `forcedTransition` y `energyReady` pasan a usar
  `fabsf(pendPosWrapped)`.
- `swing_transAlphaDeg` latchea el **acotado** — es el que evaluaron las compuertas y el
  único comparable entre corridas. El crudo sigue en el log de Serial.

#### Notas
- Es la misma familia que P1 (`forced` anulando a las demás) y P13 (el cero corriéndose en
  silencio): un umbral evaluado contra una referencia que no significa lo que el umbral
  supone.
- **Consecuencia para P2 y P4:** cualquier corrida en la que el péndulo acumulara vuelta
  podía traspasar lejos de la vertical, entregándole al LQR una condición insostenible.
  Las mediciones previas de ambos problemas hay que releerlas con esto en mente.
- PATCH y no MAJOR: corrige un bug, no cambia arquitectura ni pines. Sí cambia
  comportamiento del lazo, así que se prueba solo, sin mezclar con otros cambios.

## [1.57.1] — 2026-08-01
### Migración a placa ESP32 DevKit V1 de 30 pines (sin cambio de GPIO)

#### Motivación
- Se reemplaza la placa ESP32 del montaje por una **DOIT ESP32 DevKit V1 de 30 pines**, que
  pasa a ser la única placa del proyecto. Mismo módulo WROOM-32, mismo `board = esp32dev`
  en `platformio.ini`.

#### Hallazgo: no hubo que renumerar ningún pin
- El firmware usa 9 GPIO: **21, 22, 25, 26, 27, 32, 33, 34, 35**. Los 30 pines exponen
  todos.
- Lo único que la placa de 30 pines no expone respecto de la de 38 es **GPIO0 y GPIO6–11**
  (flash SPI), y ninguno estaba en uso.
- Ninguno de los 9 es pin de strapping (0, 2, 4, 5, 12, 15), así que tampoco aparecen
  modos de arranque distintos.
- Por eso esta entrada es **PATCH y no MAJOR**: la tabla de versionado marca MAJOR para
  "cambio de pines", y aquí el mapa de pines es idéntico. Cambió la placa, no la
  asignación.

#### Cambios aplicados

**1. `docs/hardware/pinout.md` — pinout indexado por posición física**
- Nueva columna **Posición** en la tabla de pines: fila (izq./der.) y número contado desde
  el extremo del USB, para cablear contando posiciones.
- Orden completo de ambos headers de la DevKit V1 de 30 pines, con la advertencia de
  verificar el serigrafiado (hay clones con las filas espejadas).
- Sección nueva "Trampas de cableado de esta placa":
  - IN1/IN2 quedan contiguos (izq. #6-#7).
  - Los 4 canales de encoder ocupan izq. #9–#12 en orden `33, 32, 35, 34`, **inverso** al
    del conector J4 de la perfboard (`34, 35, 32, 33`): la cinta va cruzada. Conectarla
    "derecha" intercambia los dos encoders.
  - SDA (der. #11) y SCL (der. #14) no son contiguos: entre medio están RX0 y TX0. Correrse
    una posición aterriza en la UART0 del USB y el síntoma no parece de I2C.
- Nota mecánica: la placa de 30 pines es más corta y angosta; medir el footprint si va
  sobre zócalo.
- La opción B del ENA sigue disponible: GPIO25 está expuesto (izq. #8).

**2. `docs/hardware/bom.md`**
- Se precisa el formato de placa en la BOM: `ESP32-WROOM-32 — placa DevKit V1, 30 pines`.

**3. `docs/hardware/system_wiring_l298n.py`**
- Etiqueta del bloque ESP32: `WROOM-32` → `DevKit V1 - 30 pines`. PNG regenerado.

**4. `docs/hardware/pinout_esp32_30.py` — tarjeta de pinout físico (nueva)**
- Dibuja la placa con sus dos headers en **orden físico**, numerados desde el USB, para
  cablear en el banco contando posiciones. Complementa a `system_wiring_l298n.py`, que es
  un diagrama de redes (qué se conecta con qué) y no dice dónde cae cada pin.
- Marca en rojo las tres trampas: la cinta de encoders cruzada, RX0/TX0 entre SDA y SCL,
  y los pines que la placa no expone.
- `pinout.md` pasa a documentar **los 30 pines**, no solo los 9 en uso: 13 comprometidos,
  3 no cableables (`EN`, `RX0`, `TX0`) y **14 libres** (12 GPIO de propósito general + 2
  input-only), dato que hacía falta para evaluar expansiones como el dongle ESP-NOW.

#### Cambios de firmware
```cpp
// Encabezado de esp32_qube.ino — solo comentario, sin cambio funcional:
// Placa: DOIT ESP32 DevKit V1, 30 pines (modulo WROOM-32). El cambio desde la
//        placa de 38 pines (2026-08-01, v1.57.1) no altero ningun GPIO.
```
- Las constantes `PIN_ENC_A/B`, `PIN_PEND_A/B`, `PIN_ENA/IN1/IN2` y `PIN_I2C_SDA/SCL`
  quedan **intactas**.

#### Notas
- El `perfboard_layout.py` no cambia: la ESP32 no va sobre la perfboard, se conecta por los
  headers J3/J4.
- Orden de verificación en banco tras recablear, con el riel de 15 V **apagado** hasta el
  final: continuidad despoderado → alimentar solo el riel de la ESP32 → flashear →
  observar por HTTP (`http://192.168.4.1/state`, no abrir `pio device monitor`, que
  resetea) → confirmar INA219 → girar brazo y péndulo a mano y ver las cuentas → recién
  ahí energizar los 15 V con `m1` a PWM bajo → `m3` homing.

## [1.57.0] — 2026-07-31
### Adquisición por bloques: el ESP32 muestrea a 500 Hz, el PC interpreta y analiza

La idea era dejar la ESP32 **solo como adquisición de datos**. Se adopta en su parte de
adquisición y análisis, y **no** en la de mover el lazo de control al PC, por una cifra:
adquirir está limitado por **caudal** y controlar por **latencia**. Un bloque que tarda
30 ms en llegar no degrada nada, porque cada muestra viaja con el `micros()` del tick que
la produjo; un lazo de control con período de 2 ms no puede esperar 32 ms (medidos, con
colas de 63 ms). Cerrar el lazo desde el PC a 500 Hz pediría 500 round-trips por segundo
contra un techo medido de 31 Hz.

El resultado es que la adquisición **baja** el tráfico en vez de subirlo: 512 muestras
por frame en vez de una muestra cada 100 ms.

#### Firmware
- Buffer circular SPSC de 2048 muestras (32 KB, 4,1 s a 500 Hz). El productor es el lazo
  (core 1) y el consumidor el handler HTTP (core 0); sólo uno mueve cada índice, así que
  la ruta de 500 Hz no paga una sección crítica. **Apagado por defecto**: cuesta una
  lectura de bool.
- Muestra de 16 B: `t_us`, `th_deg`, `al_deg` **sin envolver**, `pwm`, `mode`, `flags`.
  Sin velocidades: derivar y filtrar es trabajo del PC, que es el punto. El wrap de
  ±180° va afuera porque destruye cualquier derivada numérica.
- `GET /daq?start=1&decim=N` / `?stop=1` / estado en JSON, y `GET /daq/read` con el
  bloque binario. `start` **vacía el buffer**: dos sesiones mezcladas darían un salto
  temporal indistinguible de un dato real.
- Buffer lleno: se descarta la muestra **nueva** y se cuenta; el acumulado viaja en cada
  bloque. Nunca hay pérdida silenciosa.
- Un solo consumidor: `beginResponse_P` no copia, así que una segunda petición
  concurrente recibe 503 en vez de datos pisados.
- **`/cmd?sv=0`**: apaga la línea de telemetría por Serial. Son ~120 caracteres cada
  100 ms, unos 10 ms de UART a 115200 contra un período de lazo de 2 ms — y el
  consumidor habitual no existe, porque abrir el monitor reinicia la placa. Default 1,
  para no romper `qube_serial_tool.py`.
- `/state` suma `daq_running`, `daq_available`, `daq_dropped`, `serial_telemetry`.
- RAM: 15,2 % → 27,7 % de 327 KB (32 KB de anillo + 8 KB de staging).

#### Python — nuevo paquete `src/qube_daq/`
- `protocol.py`: decodificador con validación de `magic`, versión y tamaño. Incluye el
  desenrollado de `micros()`, que **da la vuelta cada 71,6 minutos** y sin corregir haría
  que el tiempo retroceda a mitad de una captura larga.
- `client.py`: `DaqClient.record()` y `Acquisition`, que reporta **tasa efectiva medida**
  (no la nominal pedida), huecos y muestras perdidas. Vacía la cola al detener: lo que
  quedó en el buffer es dato ya medido y descartarlo recortaría el final de cada captura.
- `__main__.py`: `status`, `record` (CSV con el esquema canónico de `capture.py`) y
  `plot`. Con `--mode` pide confirmación y siempre corta el motor al salir.

#### Verificación
19 tests nuevos (149 en total, todos pasan) contra bloques sintéticos: campos, bloque
truncado, desajuste de versión, bloque vacío como caso legítimo, wrap de `micros()`
dentro y entre bloques, concatenación, vaciado de cola y contabilidad de perdidas. El
firmware compila en ambos entornos.

**Sin correr en banco.** No se midió la tasa efectiva real, ni cuánto le cuesta al lazo
capturar a 500 Hz, ni si el buffer alcanza con la radio en condiciones reales.

#### Documentación
- `docs/research/adquisicion_por_bloques.md` — diseño, formato, contratos y la
  discusión de por qué el lazo NO se mueve al PC.
- `docs/http_api.md` — `/daq`, `/daq/read`, `sv` y los campos nuevos de `/state`.
- `experiments/2026-07-31_softap/scripts/measure_loop_load.py` — mide quién le roba
  tiempo a quién (red vs ley de control), con las dos hipótesis separables por diseño.

## [1.56.0] — 2026-07-31
### Rol de radio: SoftAP puro por defecto (el STA queda como entorno de compilación)

El firmware levantaba SoftAP **y** cliente del router a la vez. Esa coexistencia AP+STA
sobre una radio única fue la causa **medida** de los picos de ~100 ms del lazo
PC-en-el-lazo (v1.50.0): se verificó en tres flasheos OTA que ni `setSleep(false)` ni
`WIFI_PS_NONE` los quitaban y que el `beacon_interval` 100→300 ms sí. Es decir, el
beacon era un paliativo sobre una causa que seguía ahí. Se apaga el rol STA.

**Esto no está medido todavía.** La mejora de latencia es la hipótesis que motiva el
cambio, no un resultado: el A/B que la valida —o la revierte— está en
`experiments/2026-07-31_softap/`, con el criterio de decisión **pre-registrado** antes
de la primera corrida. Lo que sí se gana desde ya, y no depende de la latencia, es que
el banco deja de necesitar el router del laboratorio y que la dirección pasa a ser fija.

#### Firmware (`src/firmware/esp32_qube/esp32_qube.ino`)
- `ENABLE_STA` pasa a derivarse del macro `QUBE_ENABLE_STA` (default **0**). El rol
  anterior se reconstruye sin editar el fuente: `pio run -e esp32dev_apsta`.
- `AP_CHANNEL` (6) como constante con nombre. En AP+STA el canal no se elige —se copia
  del router por escaneo, porque la radio es una sola—; en SoftAP puro se usa
  directamente y **se evita el escaneo, que es bloqueante** y domina `loop_dt_max_us`
  al arrancar.
- `beacon_interval` pasa a ser condicional: **300 ms en AP+STA, 100 ms en SoftAP puro**.
  Alargarlo servía para robarle menos aire al STA; sin STA es contraproducente, porque
  el AP retiene las tramas de una estación en power-save hasta el DTIM siguiente y un
  beacon largo alarga esa retención. Con el PC como estación, quien puede dormir ya no
  es el ESP32 (que tiene `WIFI_PS_NONE`) sino el adaptador del portátil.

#### Configuración de red del lado del PC
- `platformio.ini`: nuevo `[env:esp32dev_apsta]`; el OTA por defecto apunta a
  `192.168.4.1` (hay que estar **asociado** a `QUBE-ESP32` para flashear).
- Nuevo `DEFAULT_ESP32_IP` en `src/qube_rl/config.py`, con override por variable de
  entorno `QUBE_IP` — que es lo que permite medir A y B con el mismo script.
- Apuntan al SoftAP: `qube_real.py`, `envs/factory.py`, `inference.py`, `finetune.py`,
  `flash.py`, `capture.py`, `monitor_swingup.py`, `demo/demo_avance.py`,
  `mcp/esp32_qube_server.py`.
- **No se tocó el registro histórico**: los scripts y handoffs de `experiments/` y las
  entradas viejas de este CHANGELOG conservan la IP con la que realmente se corrieron.

#### Documentación
- `docs/research/softap_app_escritorio.md` — evaluación completa: qué cambia al invertir
  los roles de radio, los cinco transportes evaluados, ventajas y desventajas etiquetadas
  como medidas/derivadas/esperadas, riesgos operativos y el protocolo de medición.
- `docs/literature_studies/electricui-latency-benchmark.md` — referencia externa de
  latencia por enlace (WiFi TCP ~6 ms, UDP ~9 ms, ESP-NOW 5,6 ms entre pares ESP32) más
  los reportes de Espressif sobre ráfagas del SoftAP y descartes UDP en modo AP. Es la
  evidencia que sostiene **no** migrar a UDP binario.
- Actualizados `README.md`, `docs/http_api.md`, `demo/README.md`, `mcp/README.md`,
  `src/firmware/data/README.md`; `docs/mine/GUI_WEB_WEBSOCKET.md` queda marcado como
  desactualizado en su sección de IP estática.

#### Reversión
Un comando: `pio run -e esp32dev_apsta --target upload`, y `QUBE_IP=192.168.100.50`
para los scripts. La app de escritorio (el otro tramo de la propuesta) **no** se
implementó: espera al resultado del A/B.

## [1.55.2] — 2026-07-31
### P6: el sobrepaso del PID era 39%, no 77%; y el kick anti-fricción no podía funcionar

Investigación de las causas de los problemas que quedaron abiertos el 30. Lo de este
release es P6 completo (menos el barrido en banco) más las causas candidatas de P4
documentadas. **Nada de esto está medido en banco todavía**: compila y los cálculos
sobre las trazas del 30 se rehicieron, pero el barrido está pendiente.

#### La métrica de sobrepaso estaba mal, y por el doble

`validate.py` normalizaba por `|setpoint|` en vez del tamaño del escalón, y tomaba
`max(|θ|)` de todo el segmento —transitorio de entrada incluido—. En un escalón que
cruza el cero eso duplica la cifra. Recalculado sobre **las mismas trazas**:

| escalón | vieja | **nueva** |
|---|---|---|
| +3 → +20 (Δ 17°) | 13,8–28,3% | 16,3–31,7% |
| +17 → −20 (Δ 37°) | **68,3–76,7%** | **38,8–42,0%** |
| −15 → 0 (Δ 15°) | no se medía | 14,4–21,4% |

`step_overshoot()` normaliza por `sp − θ₀` y busca el pico **tras el primer cruce** del
setpoint. La cifra vieja se conserva como `overshoot_pct_max_legacy` para poder
empalmar con las tandas del 30. En los escalones cortos la nueva da *más* que la
vieja, que es lo correcto: ahí el escalón es menor que `|sp|`.

El sobrepaso real sigue siendo alto (~40%) y la causa es `Td = Kd/Kp = 0,05 s`: 113
PWM de empuje inicial contra ~44 de freno derivativo a 295 °/s.

#### El kick anti-fricción estaba mal por los dos extremos

El error de régimen de 4,8° del m2 no es del ajuste, es fricción estática — y el
mecanismo que debía cubrirla no podía:

- exigía `|err| > 8°`, y la banda donde el brazo queda pegado es **0,8–8°**;
- aplicaba `PWM_MIN = 12`, y **12 PWM no mueve el mecanismo**. El homing usa 45 para
  vencer la misma fricción, y la traza muestra al brazo inmóvil con el PID pidiendo
  14–15 PWM durante más de 1 s.

Un kick por debajo del arranque real es un kick que por construcción no arranca. Con
la banda descubierta, lo único que saca al brazo es el integrador a ~2,4 PWM/s.

- `stiction_err_thresh_deg` 8 → **2**, `stiction_kick_pwm` 12 → **30**, ambos por HTTP
  (`?se=`, `?sk=`) y en `/state`.
- **`PWM_MIN` eliminado**: su único uso era éste, y el nombre prometía un piso global
  que nunca fue.
- El **feedforward gravitacional se movió antes de la zona muerta**. Estaba después, o
  sea que el `pwm = 0` de la zona muerta quedaba pisado por el `ff` sumado a
  continuación. Inocuo sólo porque `servo_ff_pwm = 0` por defecto.

#### P4: cinco causas candidatas, por lectura de código

En `docs/REGISTRO_PROBLEMAS.md`. Las dos que más explican el síntoma: el `catch`
retorna antes de actualizar `lqr_prevAlpha`, así que durante 400 ms divide por un tick
todo el desplazamiento acumulado y satura el freno en una dirección fijada desde ruido
de encoder; y durante esos mismos 400 ms **no corre el LQR**, tiempo en que una
desviación de la vertical crece ×155. Sin cambios aplicados: el orden importa y no
conviene mezclarlos con un cambio de ganancias.

#### Reserva sobre "sobra energía" (P2)

Esa conclusión descansa en 2 corridas de 3 con `tr=0`; las 4 posteriores con `tn=175`
toparon en 159–160°. La diferencia parece ser la duración de la corrida (30 s vs unos
segundos), no la energía. Conviene repetir con n ≥ 5 antes de construir encima.

#### Nuevo

- `experiments/2026-07-31_pid/scripts/sweep_pid.py`: barre `kd`/`kp` y el par
  `se`/`sk` por HTTP. Mide **hunting** (cruces del setpoint y PWM activo en régimen) a
  propósito — subir el piso del kick puede cambiar un error de régimen por un ciclo
  límite, que es peor.

---

## [1.55.1] — 2026-07-30
### Ventana de validación del homing apretada a 262–278°

`experiments/2026-07-30_full_validation/` (24 repeticiones, 8 modos × 3) encontró que
**3 de 24 homings midieron ~250,3–251,7° y fueron ACEPTADOS** por la ventana 250–290:
un cero corrido ~10° se dio por bueno. Las 3 vienen justo después de `m1`, el único
modo que empuja el brazo a PWM fijo contra los topes.

El recorrido real es 268–270°, así que 250 de piso no filtraba nada útil. Ventana
nueva: **262–278**. Verificado tras el cambio: homing OK con 269.121°.

Reconfirmado con 24 muestras: **el tope negativo se repite con 0,70° de dispersión y
el positivo con 20,56°**. `SEEK_NEG` siempre corre con carrera constante desde el tope
opuesto; `SEEK_POS` arranca desde donde quedó el brazo. Hipótesis para el fallo: calado
falso por el péndulo agitado. Sin probar.

---

## [1.55.0] — 2026-07-30
### `/state` expone el criterio de traspaso swing-up → LQR

El criterio ganador se imprimía **sólo por Serial**, y el monitor serial reinicia la
placa: en la práctica el traspaso no era atribuible. Ahora se latchea en el instante
de la transición y sale por `/state`.

- Campos nuevos: `swing_trans_reason` (bitmask: 1=near+slow, 2=peak, 4=forced,
  8=energy), `swing_trans_alpha`, `swing_trans_vel`, `swing_trans_energy`
  (`E/E*`), `swing_trans_ms_ago`.
- **Bitmask, no enum:** los 4 criterios se evalúan antes del cortocircuito y saber
  cuáles coincidieron dice más que saber cuál ganó.
- Se latchea **antes** de `setMode(4)` y `setMode(5)` lo limpia, así que lo que se lee
  siempre corresponde al intento en curso.

#### Lo que reveló, de inmediato
En 4 de 4 intentos el criterio fue **`forced` y sólo `forced`**, con α ≈ 125–127°,
velocidad 506–871 °/s y **`E/E*` de 0.81–0.86**.

`forcedTransition = |pendPos| > 125` es la única de las cuatro condiciones **sin
compuerta de velocidad ni de energía**. Como su umbral (125°) está apenas sobre el de
cercanía (120°), se cruza antes de que las condiciones con compuerta se cumplan: los
criterios que sí verifican velocidad y energía quedan **efectivamente muertos**, y el
LQR recibe un péndulo a 55° de su punto de operación y girando rápido.

#### Corrección de un resultado previo
La primera tanda sugería que el ángulo de traspaso variaba entre 76° y 128°. **Era
artefacto de muestreo** (cliente a 8–13 Hz viendo el cambio de modo hasta 120 ms
tarde). Los 4 criterios exigen `|pendPos| > 120`, así que 76° era imposible por
construcción. Con el valor latcheado el ángulo real es consistente en ~125–127°.

---

## [1.54.2] — 2026-07-30
### Barrido funcional de los 8 modos (`experiments/2026-07-30_mode_sweep/`)

Primera campaña que corre `m0..m7` de corrido sin intervención manual. Lo que la
hace posible es el homing: antes, cualquier modo que derivara el brazo al tope
dejaba el banco trabado hasta moverlo a mano.

- **Los 8 modos entran y despachan.** La reasignación de `m3` no rompió el resto.
- `m2` (PID servo) es el único que cierra un lazo limpio hoy: sobrepaso ~25%, sin
  cortes. `m4`/`m5`/`m7` siguen sin sostener la vertical.
- `m5` bombea bastante más fuerte de lo registrado antes (|α| 117° contra ~84°) y
  **entrega el control al LQR solo**. Pero vertical son 180°: el traspaso se dispara
  75° antes, y el LQR aguanta ~1,4 s antes de que el brazo cruce el límite blando.
- El `safeStop` por límite actuó en los 3 modos donde correspondía.
- **7 recuperaciones automáticas del cero, cero intervenciones manuales.**

#### Hallazgo: la dispersión del homing está toda en un tope
Las 7 corridas comparten marco `raw` (no hubo reinicio). Reconstruyendo los topes:
el **tope negativo se repite con dispersión de 0.010°** —por debajo de un conteo de
encoder— mientras el **positivo dispersa 1.060°**. Coherente con que `SEEK_NEG`
siempre arranca desde el tope opuesto, con carrera constante de 270°, y `SEEK_POS`
desde donde haya quedado el brazo. **Es hipótesis, no conclusión**: explica el patrón
pero no se corrió el experimento que la probaría.

#### Limitación de telemetría encontrada
El criterio que dispara el traspaso `m5`→`m4` (`canTransition` / `atPeakTransition` /
`forcedTransition` / `energyReady`) se imprime **sólo por serial**, y el monitor
serial reinicia la placa. Hoy no es atribuible por HTTP. Candidato a `/state`.

---

## [1.54.1] — 2026-07-30
### GUI: panel de homing

`src/firmware/data/index.html` (requiere `pio run -e esp32dev_ota -t uploadfs`).

- Panel **Homing** en la pestaña Calib: botón de ejecución, abortar (`m=0`), y
  fase / resultado / tope+ / tope− / recorrido / centro en vivo. La telemetría ya
  viajaba: el WebSocket emite `getStateJson()`, el mismo payload que `/state`.
- El resultado se colorea: verde con el cero fijado, ámbar en curso, rojo en fallo
  con el motivo traducido del código (1 recorrido fuera de tolerancia, 2/3 timeout
  de tope, 4 timeout al centrar).
- `Homing` agregado al selector de modos y a `MODE_NAMES`. **No era cosmético:** el
  badge hace `el('mode').value=d.mode`, así que sin la opción `value="3"` el selector
  quedaba en blanco cada vez que el firmware reportaba modo 3.
- Confirmación obligatoria antes de arrancar, y el botón "Aplicar" del selector se
  enruta por la misma función: el modo 3 es el único que mueve el brazo contra los
  topes a propósito, y no debería poder dispararse por un clic distraído.

---

## [1.54.0] — 2026-07-30
### `QubeRealEnv` puede recuperar el cero sin intervención

Cierra el objetivo original: dejar el banco entrenando y que se recupere solo si
pierde la referencia.

#### `src/qube_rl/envs/qube_real.py`
- `run_homing()` público (usable desde un notebook o un script de recuperación),
  más `_start_homing()` / `_wait_homing()` / `_center_arm()`.
- Disparadores: `homing_every=N` (periódico), `homing_on_start`, y
  `homing_on_limit` (por defecto **sí**) que encola un homing cuando un episodio
  termina por límite de servo — la firma de un cero corrido o perdido. `step()` solo
  lo *encola*; correrlo ahí dejaría al brazo moviéndose mientras el llamador todavía
  cree tener el control del lazo.
- `reset(options={"homing": True/False})` fuerza o suprime una corrida puntual sin
  reconfigurar el entorno.
- **Opt-in por defecto** (`homing_every=None`): la rutina mueve el brazo contra
  ambos topes, y eso no puede pasar por sorpresa en un banco desatendido.
- **Centrado fino encadenando `m2`** después del homing. El homing garantiza el
  *cero*, no dónde queda estacionado el brazo (ver la limitación en v1.53.2). Es
  best-effort y no levanta excepción: un brazo descentrado es un mal estado inicial,
  no una referencia corrupta.
- **Un homing fallido levanta excepción.** Seguir contra un cero desconocido
  corrompe en silencio todos los `theta` del dataset; caerse es más barato. En el
  fallo no se incrementa `zero_epoch` y queda pedido el reintento.

#### Trazabilidad del marco de referencia
Cada homing **redefine** `theta = 0`. `reset()` ahora devuelve `info["zero_epoch"]`
en **todos** los resets (no solo los que corrieron homing), y `info["homing"]` con la
geometría medida en los que sí. Sin eso, episodios de antes y después de un homing se
mezclarían como si compartieran marco.

#### Verificado contra el hardware
`reset(options={"homing": True})` completo en **11,4 s**: `range_deg` 269.648 (cuarto
valor idéntico consecutivo), `park_error_deg` 0.0, theta inicial 0.178°. Un reset sin
homing toma 1,2 s. Las rutas de fallo y de timeout se probaron con la telemetría
simulada.

---

## [1.53.2] — 2026-07-30
### Homing más suave contra los topes

Los dos *toques* ya eran suaves (arrancan a 5° del tope, apenas aceleran); lo que
golpeaba fuerte eran las dos *búsquedas*, y `SEEK_NEG` es la peor porque tiene 265°
de carrera para llegar a velocidad terminal.

- `HOMING_PWM_SEEK` de 70 a 55. Velocidad de impacto medida: **80 → 67 °/s**
  (~30% menos energía). No se puede bajar más: a 40 la fricción sola frena el brazo
  y el detector de calado lo lee como tope — ese fue el defecto de v1.53.1.
- `HOMING_STALL_MS` de 200 a 120. No reduce el golpe (ya ocurrió) pero sí los 200 ms
  de empuje sostenido contra el tope después del contacto. Margen de sobra: a PWM 55
  el brazo recorre ~7° en 120 ms, contra un umbral de 0,5°.
- `HOMING_SIDE_TIMEOUT_MS` de 8000 a 12000, porque cruzar los 270° a PWM 55 toma ~5 s.

Confirmación indirecta de que golpea más suave: `homing_range` bajó de 270.18° a
269.65°, **el mismo valor en dos corridas**. Esos 0,5° eran deformación elástica del
tope bajo impacto. La repetibilidad del centro sigue en un conteo (0.176°).

**Presupuesto de tiempo:** el total es ~9–13 s según dónde arranque el brazo, y
`GOTO_CENTER` se lleva la mitad. La búsqueda completa son ~5 s.

**Validación de punta a punta.** Con la ESP32 reiniciada y el cero perdido de verdad
(`offset_deg = 0`, `homing_ok = false`), el homing reconstruyó el centro con una
diferencia de 0,176° —un conteo de encoder— respecto de la calibración anterior, y
midió el mismo recorrido (269.648°) que las dos corridas previas al reinicio. Es el
caso de uso para el que existe el modo: una corrida de entrenamiento desatendida que
sufre un reset puede recuperar su referencia sin intervención.

**Limitación conocida:** el brazo no siempre queda centrado. En una de las corridas
terminó a 19,5° del centro: al cortar el motor el puente queda en corte, no en freno,
y el péndulo con swing residual back-drivea el brazo (es direct-drive). **No afecta la
calibración** — el offset se fija en el centro geométrico medido, no donde quedó
estacionado. Si hace falta centrado fino, lo correcto es encadenar `m2` (PID de
posición) después del homing, que ya es legítimo porque el cero existe.

---

## [1.53.1] — 2026-07-30
### Homing validado en banco: dos defectos corregidos

Primera ejecución real de `m3` sobre el mecanismo. La máquina de estados recorrió la
secuencia completa sin trabarse, pero las dos primeras corridas expusieron defectos
que solo aparecen con el brazo puesto.

- **El toque lento se calaba antes del tope.** Con `HOMING_PWM_TOUCH = 40` el brazo
  se detenía por fricción y el detector lo leía como tope: en la corrida 1 el brazo
  ya había alcanzado `raw = -107.9` durante `SEEK_POS` y el toque terminó en `-97.6`,
  10° corto. Subido a 55 (y `HOMING_PWM_MIN` de 35 a 45).
- **`GOTO_CENTER` se pasaba del centro y reportaba éxito igual.** El lazo P llegaba
  al centro a PWM 70 y declaraba `DONE` en el instante de cruzar la tolerancia;
  `setMotorDirect(0)` deja el puente en corte, no en freno, así que el brazo seguía
  por inercia. En la corrida 2 se pasó 126° y quedó contra el tope opuesto con
  `homing_ok = true` y `position_deg = -125.7`, fuera del límite blando. Ahora el
  éxito exige además que el brazo esté detenido, hay techo de PWM reducido dentro de
  los últimos 30° (`HOMING_CENTER_SLOW_DEG`) y la tolerancia de estacionamiento pasa
  de 2° a 5° — es tolerancia de estacionamiento, no de calibración: el cero se fija
  en el centro geométrico medido pase lo que pase.
- **Ventana de recorrido corregida con medición.** Los 150–230° eran una suposición
  y hacían abortar con `fail=1` un homing correcto. El recorrido real del brazo es
  **270°**; la ventana queda en 250–290.

#### Repetibilidad (4 corridas limpias, 2026-07-30)
`homing_range`: 270.352 / 270.000 / 270.000 / 270.352. En las tres corridas hechas
sin reset intermedio —o sea, comparables en el mismo marco `raw`— `homing_center`
dio 63.809 / 63.633 / 63.633. La dispersión es **un conteo de encoder** (0.176°), el
límite de resolución del sensor. El brazo queda estacionado a menos de 5° del centro.

---

## [1.53.0] — 2026-07-28
### Modo 3 reasignado: homing por topes mecánicos

**Cambio de significado de un ID de modo.** `m3` fue el PID de péndulo hasta v1.34,
quedó como hueco no despachado desde entonces, y ahora es la rutina de homing. Los
logs y datasets con `"mode": 3` anteriores a esta versión corresponden al PID de
péndulo o a un no-op, **no** al homing.

Motivación: el encoder del brazo es incremental y pierde el cero en cada reset. Sin
una forma autónoma de recuperarlo, una corrida de entrenamiento desatendida que
sufra un reset queda entrenando contra una referencia desconocida.

#### Firmware (`esp32_qube.ino`)
- Máquina de estados de homing: espera a que el péndulo se aquiete, busca cada tope,
  retrocede 5° y vuelve a tocarlo lento, valida el recorrido y adopta el punto medio
  como cero (`positionOffsetDeg`). Termina sola en `setMode(0)`.
- **Detección de calado por encoder** (sin movimiento >0,5° durante 200 ms con par
  aplicado), no por temporizador fijo ni por corriente: no depende del INA219, cuya
  caída deja el corte por calado inhabilitado.
- Validación de recorrido (150–230°) antes de fijar el cero. Cubre el caso de encoder
  muerto, que de otro modo mediría un rango ≈0 y calibraría sobre basura.
- Exención del fin de carrera común (`SERVO_HARD_LIMIT_DEG`) para `mode == 3`: el
  homing corre con el cero inválido y necesita alcanzar los topes. Sin la exención se
  auto-mata en el primer tick.
- Usa `setMotorDirect()`: la soft saturation de `setMotor()` escala el PWM según un
  offset que durante el homing todavía no es válido.
- `/state` expone `homing_phase`, `homing_ok`, `homing_fail`, `homing_stop_pos`,
  `homing_stop_neg`, `homing_range`, `homing_center`. El disparo es asíncrono
  (`/cmd?m=3`) y el cliente hace polling: bloquear el callback HTTP dispararía el
  watchdog y congelaría el lazo de 500 Hz.

#### Scripts que mandaban `m=3` (antes inocuo, ahora mueve el brazo)
- `experiments/2026-06-15_training/test_approach_c.py`: enviaba `m=3` creyendo que
  era swing-up; corregido a `m=5`, que es lo que pretendía.
- `experiments/2026-06-04_pid_tuning/test_pid.py`: `--mode pendulum/both` aborta con
  error explícito; el default pasa de `both` a `servo`.

#### Pendiente
- Gancho en `qube_real.py::reset()` para disparar el homing desatendido.
- Validación en banco por etapas antes de soltarlo a rango completo.

---

## [1.52.0] — 2026-07-28
### Reversión de hardware: BTS7960 → L298N (documentación + firmware)

El driver de potencia BTS7960 (migrado el 2026-06-08, commit 78b4e7e) se revierte a
**L298N** por errores de implementación del usuario durante esa migración. Se actualiza
la documentación de hardware vigente (`README.md`, `docs/hardware/pinout.md`,
`docs/hardware/bom.md`, `docs/hardware/signal_conditioning.md`) y los comentarios /
string de boot de `esp32_qube.ino` para reflejar el sistema actual. **La lógica de
control no cambió** — ver detalle abajo.

#### Arquitectura de potencia actual
- **Fuente:** transformador 15V-2A (antes: LiPo 4S / PSU genérica).
- **Motor:** transformador (+) → INA219 (VIN+/VIN−, high-side) → **L298N VS**, igual
  posición de medición que con BTS7960 — solo cambia el driver.
- **Lógica:** **dos** LM2596 en vez de uno.
  - LM2596 #1 (riel "lógica"): L298N VSS + VCC de ambos encoders + pull-ups/filtro RC
    de los 2× CD40106BE.
  - LM2596 #2 (riel dedicado): únicamente ESP32 VIN, aislada del ruido de conmutación
    del L298N y de la corriente variable de los encoders — reduce el riesgo de
    brownout documentado previamente en el rail de 5 V compartido.
- El Vcc de los 2× CD40106BE sigue viniendo del pin 3V3 de la ESP32 (sin cambios) —
  crítico para no repetir la sobretensión de GPIO32/33 de v1.51.1.
- **GPIO25 (PIN_ENA): confirmado sin conexión física** en el L298N actual (jumper ENA
  puesto). El firmware lo deja en HIGH en `setup()` por herencia del wiring BTS7960
  (R_EN/L_EN) — salida sin efecto eléctrico, no un requisito del L298N.

#### Cambios en `esp32_qube.ino`
- Header: arquitectura, topología de potencia y pinout actualizados a L298N.
- String de boot por serial: `"=== QUBE ESP32 + BTS7960 + INA219 ==="` →
  `"=== QUBE ESP32 + L298N + INA219 ==="`.
- Comentarios de `PIN_ENA`/`USE_ENA_PWM` y del `setup()` aclaran que GPIO25 no está
  conectado en el hardware actual.
- `ke_gain` (swing-up): se conserva la atribución histórica ("calibrado en BTS7960,
  25% catch rate, hold 86s") con nota de que **no está re-validado en L298N** — la
  caída de tensión y el par disponible pueden diferir entre drivers.
- **No se tocó la lógica de control** (PID/LQR/swing-up/RL) ni los pines GPIO26/27:
  el esquema de PWM dual en dos pines de dirección ya era electricamente equivalente
  entre BTS7960 (RPWM/LPWM) y L298N (IN1/IN2, opción A, jumper ENA puesto). La
  reversión de hardware fue solo un recableado físico (GPIO26→IN1, GPIO27→IN2).

#### Pendiente
- Re-validar `ke_gain` y el resto de ganancias empíricas del swing-up sobre L298N.

#### Fuera de alcance de este cambio
- Documentos de investigación, validación y memoria de cálculo (`docs/research/`,
  `docs/validation/`, `docs/hardware/memoria_calculo_electronica.tex`,
  `docs/hardware/system_wiring.py`, `docs/hardware/perfboard_layout.py`) siguen
  refiriendo BTS7960 y no se tocaron en esta pasada — son material histórico/análisis,
  no la documentación de hardware operativa.

---

## [1.51.2] — 2026-07-27
### Campaña de validación de los 7 modos por HTTP (banco) + hallazgos de firmware

Prueba en vivo de todos los modos (0–7) manejada por HTTP (`/cmd`, `/rl_step`, `/state`),
en escalera de riesgo con `x=1` entre pasos. **No se modificó `esp32_qube.ino`**; se
registran resultados y limitaciones detectadas para trabajo futuro.

#### Resultados por modo
- **m0 STOP**: OK. Estado base sano (`ina_ok`, bus ~14,8 V).
- **m1 PWM manual**: OK, ambos sentidos. Confirmado: **+PWM → encoder servo negativo**
  (lo compensa `MOTOR_DIR=-1`). Servo muy rápido (~420°/s a p=60).
- **m2 PID posición**: OK, converge y es **estable**. Tuning suelto: overshoot ~10-23° y
  error residual de pocos grados (stiction / desnivel).
- **m5 swing-up**: bombea pero **débil** (llega a ~84°/47 % de vertical, no captura). Con
  `sp=70,ke=0.9` **se desestabiliza**: el servo se va al tope y el motor queda calado.
- **m6 RL-HTTP**: **protocolo `pv=3` y round-trip `/rl_step` OK**; el motor responde a la
  acción con el signo correcto.
- **m7 RL on-device**: la inferencia corre (el pwm varía), bombea ~46°, **no balancea**.
- **m4 LQR**: engancha y **reacciona** (pwm corrige), pero **cae en ~1 s**.

#### Hallazgos (para corregir en futuras versiones)

**1. Lockout de fin de carrera (`esp32_qube.ino:2078`)**
- `if (mode != 0 && fabsf(pos) > SERVO_HARD_LIMIT_DEG) safeStop();` corre cada tick en
  todos los modos. Con **|servo|>95° NINGÚN modo por software recupera** el brazo (el
  modo 1 también se corta antes de aplicar par) → hay que recentrar **a mano**.
- El servo alcanzó 133°: el rango mecánico es **>±95°**; 95° es umbral de software, no
  tope físico. Sugerido: modo/ruta de "recover" con PWM bajo acotado que ignore el límite
  para volver al centro.

**2. Deriva sistemática del servo al tope**
- En m5(reforzado), m7 y m4 el brazo **no se recentra**: deriva monótona a un lado hasta
  el lockout. Es el bloqueador #1 del swing-up/balanceo. Revisar signo/ganancia del
  término de posición del servo (θ) frente a la convención +PWM→encoder negativo.

**3. Bug de telemetría menor**
- `/state.rl_action` reporta `rlAction` (modo 6); en **modo 7 queda obsoleto** y no
  refleja la inferencia on-device (el pwm sí la refleja).

#### Notas
- Encoder del péndulo validado previamente (v1.51.1); toda la campaña usó esa lectura sana.
- Sistema dejado en estado seguro (modo 0, motor detenido) al finalizar.

---

## [1.51.1] — 2026-07-27
### Diagnóstico y validación del encoder del péndulo (fix de cableado + calibración CPR)

El encoder del péndulo leía las coordenadas mal (escala y/o signo). Diagnóstico
eléctrico + validación en vivo por HTTP `/state`. **Fix de hardware (cableado); no se
modificó `esp32_qube.ino`.** Se confirma la parametrización existente.

#### Problema identificado
- Síntoma: `pend_raw_position_deg` con escala/signo incorrectos.
- Medición: **4,1 V y 3,5 V en GPIO32/GPIO33** — fuera del máximo del ESP32 (3,3 V;
  abs. máx 3,6 V). Leer 4,1 V en el pin es imposible si el acondicionamiento fuera
  correcto → prueba de un problema eléctrico, no de CPR ni de firmware.
- **Causa raíz**: la salida acondicionada (Schmitt CD40106, push-pull) hacia el ESP32
  quedó cableada **en línea con la entrada del canal B**. Dos fuentes en contención en el
  mismo nodo → sobretensión en el GPIO y cuadratura rota (el PCNT contaba transiciones
  inventadas → escala/signo mal).
- Nota: los encoders del péndulo son **push-pull 5 V** (no open-drain); el pull-up de
  2,2 kΩ a 3V3 no domina el nivel — por eso es obligatorio el Schmitt a 3,3 V como buffer.

#### Cambios aplicados
**1. Corrección de cableado (hardware, no firmware)**
- Se separó la salida hacia el ESP32 de la entrada del canal B (fin de la contención).
- Reafirmado: pull-up 2,2 kΩ a 3V3 antes del Schmitt; CD40106 alimentado a 3,3 V; su
  salida limpia (≤3,3 V) al GPIO.

#### Validación (en vivo por HTTP `/state`, sin monitor serial — resetea la placa)
- Ambos canales conmutan (`pend_a`, `pend_b` visitan 0 y 1): cuadratura viva.
- Reposo sujeto firme: variación de **2 cuentas (~0,35°)** en 6 s → dithering de 1 LSB,
  sin ruido/conteo fantasma. No hace falta filtro de glitches por ruido.
- Seguimiento coherente entre `pend_count` y `pend_raw_position_deg`; enlace HTTP con
  0 errores sobre cientos de muestras.

#### Calibración CPR
- Método: 3 vueltas físicas contra marca, detección automática de mesetas.
- Resultado: 6169 cuentas / 3 vueltas = **2056 cuentas/rev**, a **+0,4 %** de 2048
  (dentro del error de posicionamiento manual).
- **Confirmado sin cambios**: `pendCountsPerRev = 2048`, `pendulumDir = +1`
  (`esp32_qube.ino:276-277`). El encoder es el estándar del QUBE (512 líneas × 4 = 2048).

#### Notas — robustez PCNT pendiente (no urgente, no era la causa)
- `initPcntUnit` (`esp32_qube.ino:702`) no usa `pcnt_set_filter_value`/`pcnt_filter_enable`
  (filtro de glitches) ni acumulador de overflow int16. La posición absoluta se pierde
  más allá de ~16 vueltas (±32768 cuentas) — relevante solo para giros libres en swing-up.

---

## [1.51.0] — 2026-07-08
### Anexo A: memoria de cálculo de la electrónica + correcciones al diagrama de conexionado

Se documenta paso a paso el dimensionamiento de la electrónica del QUBE (resistencias,
condensadores, sensor de corriente, regulador y tierra en estrella) y se integra como
**Anexo A** de la tesis. En el camino se corrigieron varios errores de trazado del
diagrama de conexionado (`system_wiring.py`) que dejaban líneas ocultas o superpuestas.

#### Memoria de cálculo (nuevo anexo)
- Nuevo `tesis_usach/capitulos/Anexo_A_memoria_calculo.tex` con el desarrollo de:
  árbol de alimentación y topología, fusible 1,5 A, shunt del INA219 (0,1 Ω),
  regulador LM2596 (15→5 V), pull-ups de 2,2 kΩ a 3V3, doble inversión Schmitt
  (CD40106BE) con histéresis, filtro RC anti-alias (τ=100 µs, fc≈1,59 kHz),
  condensadores (bypass 100 nF, filtro 10 nF, bulk 1000/470/10 µF) y tierra en estrella,
  con tabla resumen.
- **Sin dependencias nuevas**: unidades en texto plano con coma decimal (estilo del resto
  de capítulos), sin `siunitx`; referencias cruzadas con `\Cref` y labels `anx-*`;
  `\texorpdfstring` en títulos con símbolos para marcadores limpios del PDF.
- `tesis_usach/main.tex`: bloque `\appendix` tras la bibliografía con
  `\renewcommand{\appendixname}{Anexo}`, nombres cleveref de anexo e `\include` del capítulo.
- Figura `system_wiring.png` copiada a `tesis_usach/imagenes/` para que resuelva por el
  `\graphicspath` de la tesis.
- Se conserva además una versión autónoma en `docs/memoria_calculo_electronica.{tex,pdf}`
  (con `siunitx`) para uso suelto.

#### Correcciones al diagrama de conexionado (`docs/system_wiring.py`)
- **Causa raíz**: los bloques (zorder=3) tapaban las redes (zorder=2) y varias bajadas de
  GND compartían la misma coordenada x, provocando líneas ocultas o superpuestas.
- Línea 3V3 del ESP32 re-ruteada para rodear el bloque MOTOR (ya no queda oculta).
- Línea GND del ESP32 y bajadas de GND (encoder, U1, INA219, LM2596) con coordenadas x
  únicas para evitar solapes; colector de GND de la sección de potencia en x=104.
- Pines IN-/OUT- del LM2596 movidos al borde inferior (antes quedaban tapados por el bloque).
- Identificación de pines del BTS7960/IBT-2 (B+/B-/M+/M-) verificada.

#### Verificación
- `latexmk -pdf main.tex` (con biber): **95 páginas**, 0 referencias sin resolver,
  0 avisos de hyperref, sin overfull graves. El anexo aparece en el índice como
  «A — Memoria de cálculo de la electrónica».


## [1.50.0] — 2026-07-08
### Estabilidad de comunicación WiFi ESP32 ⇄ PC (latencia + cortes)

El enlace HTTP PC-en-el-lazo era **lento (~13 Hz, no 50 Hz)** y **se caía/desconectaba**
en modo AP+STA. Faltaban las palancas clásicas de estabilidad WiFi del ESP32 y el
patrón de tráfico era pesado (2 round-trips por paso). Requiere **reflashear** y
desplegar firmware + `qube_real.py` juntos (contrato `pv`: v2 → **v3**).

#### Causa raíz
- **Modem-sleep activo por defecto** (sin `WiFi.setSleep(false)`): picos de latencia de
  ~100 ms y pérdida de paquetes en tráfico latencia-crítico. Factor #1 de lentitud y cortes.
- **Sin auto-reconexión STA**: `loop()` no verificaba `WiFi.status()`; solo el comando
  manual `wifi_reconnect`. Si el router soltaba al ESP32, no volvía solo.
- **2 round-trips por paso** (`/rl_cmd?a=` + `/rl_state` ≈ 71 ms) para un objetivo de 20 ms.
- **Timeout HTTP de 5 s ×3 reintentos** en el cliente: un paquete perdido congelaba el
  lazo hasta ~15 s.
- **Broadcast WebSocket de `/state`** cada `telemetryPeriodMs` competía por la única radio
  durante los ensayos RL por HTTP.

#### Cambios de firmware (`src/firmware/esp32_qube/esp32_qube.ino`)
- `WiFi.setSleep(false)` + `WiFi.setAutoReconnect(true)` tras `softAP`/`connectSta`, más
  `esp_wifi_set_ps(WIFI_PS_NONE)` explícito (re-afirmado en cada `GOT_IP`): en AP+STA
  `WiFi.setSleep(false)` no siempre desactiva el modem-sleep.
- **`beacon_interval` del AP 100 → 300 ms** (`esp_wifi_set_config` tras `softAP`). En la
  radio única del ESP32 el beacon del AP cada ~100 ms competía con el tráfico STA y era
  la **causa real** de los picos de latencia de ~100 ms (los cambios de power-save no los
  quitaban; el beacon sí). El AP sigue disponible como fallback/GUI.
- `WiFi.onEvent(onWifiEvent)`: loguea STA_DISCONNECTED / STA_GOT_IP.
- **Guardián STA no bloqueante** en `loop()`: si STA no está conectado, reintenta
  `connectStaIfConfigured()` cada `STA_RECONNECT_PERIOD_MS` (5 s) sin frenar el lazo de 500 Hz.
- `broadcastTelemetry()`: se omite el broadcast WS en **modo 6** (RL por HTTP) para no
  robar tiempo de aire; el modo 7 (on-device) lo mantiene.
- **Nuevo `GET /rl_step?a=X`** (proto **v3**): fija la acción **y** devuelve el JSON
  compacto de `/rl_state` en **un** round-trip. `RL_PROTO_VERSION` 2 → 3 (convención de
  observación sin cambios; el bump hace fallar ruidosamente un firmware viejo sin `/rl_step`).
- **Robustez I2C (INA219) para no tumbar la comunicación**: un INA219 marginal que
  sostiene SDA en bajo colgaba `scanI2CBus()`/`initIna219()` en `setup()`. Ahora: (a)
  `i2cBusRecover()` pulsa SCL para soltar el bus antes de `Wire.begin`; (b)
  `Wire.setTimeOut(50)` acota cada transacción; (c) la init I2C se movió a **después de
  `server.begin()`** para que un fallo del sensor no impida arrancar WiFi/servidor; (d)
  el reintento de init respeta `INA_INIT_RETRY_MS` (5 s) en vez de re-escanear el bus en
  cada tick de telemetría. (Detectado al reflashear: en power-on normal arranca bien; el
  cuelgue se disparaba sobre todo con el reset por DTR del monitor serie.)

#### Cambios de Python (`src/qube_rl/envs/qube_real.py`)
- `step()` usa `/rl_step` (una sola llamada) en vez de `_send_rl_action` + `_get_rl_state`.
- `http_timeout` default 5.0 s → **0.4 s** (reintenta rápido en vez de congelar el lazo).
- `requests.Session` con `HTTPAdapter` keep-alive (una conexión TCP reutilizada).
- `EXPECTED_RL_PROTO` 2 → **3** (validado en `reset()`).

#### Resultados medidos (rig real, STA @ 192.168.100.50, AP+STA activos)
Banco de latencia HTTP (a=0, sin mover el motor), antes/después:

| Config                                   | media | máx   | picos >100 ms | throughput |
| ---------------------------------------- | ----- | ----- | ------------- | ---------- |
| Viejo (pv2), 2-RTT `/rl_cmd`+`/rl_state` | 69 ms | 173 ms| —             | 14.6 Hz    |
| Viejo (pv2), lectura simple `/rl_state`  | 41 ms | 155 ms| 2.1 %         | 24 Hz      |
| Nuevo, `/rl_step` + beacon 300 ms        | **32 ms** | **63 ms** | —         | **31 Hz**  |
| Nuevo, soak `/rl_state` (×3)             | 33–40 ms | 71–111 ms | **0–0.3 %** | 25–30 Hz |

Neto: media 2.1× más rápida, cola (máx) 2.7× menor, picos ~eliminados (2.1 % → ~0 %),
**0 fallos** en varios miles de peticiones. Verificado en 3 flasheos OTA iterativos
(setSleep → +WIFI_PS_NONE → +beacon 300 ms); los dos primeros no quitaban los picos, el
beacon sí, lo que confirmó que la causa era la coexistencia AP+STA y no el modem-sleep.

#### Notas
- **Alternativa estructural**: para control RL estable el ~13 Hz se resuelve de fondo con
  el **modo 7 (inferencia on-device a 50 Hz)**; estos fixes hacen fiables además el modo 6
  y el monitoreo por WiFi. Nota: WiFi-en-el-lazo ahora llega a ~25–31 Hz (no 50 Hz), así
  que el modo 7 sigue siendo la vía para 50 Hz reales.
- **Brownout** (crash rate ~20% al golpear el tope mecánico) sigue pendiente por hardware:
  cap 470–1000 µF en el rail 5V. `setSleep(false)` reduce el consumo pulsado que lo agrava.
- Reflashear: `pio run -e esp32dev --target upload` (o OTA `esp32dev_ota`) y desplegar
  `qube_real.py` en la misma tanda.


## [1.49.0] — 2026-07-08
### Comando serial `reboot` + lanzable de escritorio para IP/credenciales WiFi

Resuelve el problema del huevo y la gallina para conectarse a la GUI web: como
`index.html` se sirve **desde** el ESP32 por WiFi, hay que conocer su IP para
abrirla, pero esa IP la asigna el router. Ahora un lanzable de escritorio la
descubre por serial (USB) y también permite reconfigurar el WiFi sin abrir la GUI.

#### Problema identificado
- No había forma de descubrir la IP LAN sin ya estar conectado a la GUI o mirar el
  monitor serial de PlatformIO manualmente.
- El firmware ya exponía `i`, `wifi_info`, `wifi_ssid`/`wifi_pass` por serial, pero
  **no** un reinicio por serial: tras guardar credenciales imprimía "Reiniciar para
  conectar" y había que pulsar RST físicamente. El reboot solo existía por HTTP
  (`/restart`), inservible cuando aún no se conoce la IP.

#### Cambios aplicados

**1. Comando serial `reboot` (`firmware/esp32_qube/esp32_qube.ino`)**
- Nuevo comando de palabra completa `reboot` → `ESP.restart()`, gemelo serial de
  `/restart`. Chequeado **antes** del `switch` por primer carácter porque `r` ya es
  reset de encoders y `reboot` colisionaría.
- `printHelp()`: añadida línea `Sistema: reboot (reinicia el ESP32)`.
- Mensaje de `saveWifiCredentials()`: ahora sugiere enviar `reboot` por serial o
  pulsar RST.

**2. Lanzable de escritorio (`firmware/qube_serial_tool.py`, `QUBE-Serial-Tool.bat`)**
- GUI tkinter (sin dependencias nuevas: `tkinter` stdlib + `pyserial` ya presente).
- Autodetecta el puerto del ESP32 (reutiliza `find_esp32_port` de `serial_cmd.py`).
- **Detectar IP**: envía `i`, parsea la `LAN IP` de `printNetworkInfo()` y abre la
  GUI web en el navegador.
- **Guardar y reiniciar**: envía `wifi_ssid`/`wifi_pass` (valida clave ≥8), luego
  `reboot`; reabre el puerto tras ~9 s y muestra la IP nueva.
- I/O serial en hilo (no congela la ventana), manejo de puerto ocupado y log de
  diagnóstico. Lanzador `.bat` de doble clic (`uv run python`).

#### Cambios de firmware
```cpp
// processSerialCommand(), antes del switch por primer carácter:
if (cmd == "reboot") {
  Serial.println("[REBOOT] Reiniciando...");
  Serial.flush();
  delay(100);
  ESP.restart();   // gemelo serial de /restart; 'r' ya es reset de encoders
}
```

#### Notas
- Requiere **reflashear una vez** para tener `reboot` (`pio run -e esp32dev
  --target upload` o `uv run python src/firmware/flash.py`). Compilación verificada:
  `pio run -e esp32dev` → SUCCESS (Flash 75.9%).
- El lanzable se probó sin placa: instancia la GUI, detecta puerto real y el parser
  separa correctamente `LAN IP` / `AP IP` / `LAN SSID`.
- Descartada la alternativa de hacerlo dentro de la GUI HTML: Web Serial exige
  contexto seguro y falla con el puerto tomado por el firmware, y seguiría
  necesitando la IP para cargar la página.


## [1.48.0] — 2026-06-24
### GUI web rediseñada: sincronizada con el firmware + pestaña de análisis sim2real

Rediseño completo de la única GUI del proyecto (`src/firmware/data/index.html`),
servida desde SPIFFS. Se cerró la brecha entre lo que el firmware expone y lo que
la GUI mostraba, se reorganizó en **pestañas**, y se agregaron herramientas de
análisis pensadas para el problema abierto (mantener el balance ≥1 s). Verificado
con un harness Node+shim de DOM: **24/24 checks funcionales** (handler de
telemetría, watchdog, balance, presets, handshake `pv`, export CSV) + `node
--check` y cruce de IDs/handlers.

> Para verlo en el rig: `pio run -d src/firmware --target uploadfs` (GUI) y, para
> los widgets de acción RL/watchdog, también `pio run -d src/firmware --target
> upload` (campos de telemetría nuevos). Sin reflash, esos widgets quedan en `--`
> sin romper el resto.

#### Sincronización GUI ↔ firmware (`src/firmware/data/index.html`)
- **RL/sim2real:** slider de `rl_pwm_scale` (`/rl_cmd?scale=`), **handshake `pv`**
  contra `EXPECTED_PV=2` (badge verde/amarillo), poll en vivo de `/rl_state`.
- **Calibración** (panel nuevo): offsets `o/op`, dirección `ed/edp`, counts-per-rev
  `cpr/cprp`, con lecturas raw/offset en vivo desde el WebSocket.
- **Ajustes/Kalman** (nuevo): toggle `kf` + telemetría KF, feedforward `ff`, filtro
  de velocidad `va`, período de telemetría `tp`, `gain_mode` en badge.
- **Sistema** (nuevo): `/restart`, subir GUI a SPIFFS por web (`/fs`), `/format`
  con confirmación, config WiFi STA (`wifi_ssid/pass/reconnect`).
- **Swing-up:** añadido `sp` (PWM máx). Resuelta la colisión de id `sp`→`spt`.

#### Pestaña Análisis + herramientas de balance
- **Retrato de fase α vs α̇** (scatter con estela), con α̇ por diferencias finitas
  (EMA), independiente del KF.
- **Métrica de balance en vivo:** % upright, hold actual y hold máximo, con target
  (def 180°) y tolerancia configurables — mide directamente el KPI abierto.
- **Gráfica de acción RL aplicada** (`rl_action`) para diagnosticar el sobrebombeo
  al ajustar `scale`.
- **Presets** (localStorage) de PID/LQR/swing-up/gain-scheduling/RL-scale.
- **CSV extendido** opcional: `rl_action`, `alpha_dot`, `in_upright`, `kf_*`.

#### Telemetría nueva (`firmware/esp32_qube.ino`, `getStateJson()`)
- `rl_action`: acción aplicada al motor en modo 6/7.
- `ms_since_cmd`: edad del último comando → cuenta regresiva del watchdog de
  comandos (auto-STOP a los 10 s en modo 1/6), mostrada como badge.

#### Docs
- `src/firmware/data/README.md`: tablas de endpoints/paneles/telemetría
  actualizadas, nota del handshake `pv` y bloque de auditoría 2026-06-24.


## [1.47.0] — 2026-06-23
### Inferencia on-device (modo 7) operativa: primer swing-up real a invertido

Continuación directa de 1.46.0. Se aplicó la solución a la causa raíz (control a
13 Hz por WiFi): correr la política **en el ESP32 a 50 Hz** (modo 7). Tras
exportar el modelo R6 y corregir tres desajustes más, el rig real hace **swing-up
hasta vertical (1° del invertido), repetido y estable, con el brazo acotado** — el
sim2real transfirió. Lo que queda (mantener el balance ≥1 s) es calidad de modelo,
no integración. Toolchain: PlatformIO (`pio run -d src/firmware -e esp32dev` +
`-e esp32dev_ota --target upload`).

#### Modo 7 — pesos + forward pass (`firmware/esp32_qube.ino`, `qube_rl/export_rltools.py`)
- **Pesos del modelo R6 exportados** a `policy_weights.h` (`python -m
  qube_rl.export_rltools --model .../r6_theta100_s0_step250000.zip`). Arq 36→64→64→1.
- **Activación corregida a `tanh`**: `rl_forward` hacía `Hardtanh(-2,2)` y el modo 7
  multiplicaba `×0.5`; SB3-SAC determinista es `tanh(mu)`. **Verificado
  numéricamente** vs `model.predict`: error 1.7e−07 con tanh, vs 0.27 con el viejo.
- **Layout 4×9=36 confirmado** idéntico al `HistoryWrapper` (oldest-first, `obs_t`
  emparejado con `a_{t-1}`).

#### Modo 7 — correcciones de convención y temporización
- **Replica del env Python corregido on-device**: θ tal cual; **α y α̇ invertidos**
  (encoder péndulo espejado) y α envuelta a [−π,π]; **acción negada hacia el motor**
  (torque espejado), pero el historial guarda la acción de política sin negar.
- **Gate de 50 Hz** con zero-order hold: el loop de control corre a 500 Hz
  (`CONTROL_PERIOD_US=2000`) → sin gate la red de 50 Hz iría 10× rápido.
- **Signo + filtro de velocidad** (la pieza final): el firmware computaba
  `−(x−prev)/dt` → la velocidad llegaba **con signo invertido** vs el `+d/dt` del
  sim (la política amortiguaba cuando debía bombear). Reemplazado por el filtro
  discreto **exacto** del sim `H(s)=50s/(s+50)` @ dt=0.02:
  `v[n]=50·(x[n]−x[n−1])+0.36788·v[n−1]`, verificado contra `utils.VelocityFilter`.

#### Tuning en runtime + harness
- Nuevo `/rl_cmd?scale=X` (0..1): escala de PWM del modo 7 ajustable **sin
  reflashear** (`rl_pwm_scale`, reset a 1.0 en boot) para barrer torque.
- `experiments/2026-06-22_r6_real_aligned/hw_bringup.py`: etapa `mode7`
  (`--scale`, `--reset-encoders`, monitoreo + e-stop).

#### Resultado
- A **scale 0.85**: péndulo a **179° (1° del invertido)** repetidamente, brazo
  acotado (θ ~±48°, sin watchdog, 15 s estables). Swing-up cíclico fiable.
- Barrido 0.8/0.85/0.9: todos llegan a 180° pero **ninguno mantiene** (hold más
  largo ~0.12 s; objetivo ≥1 s). El catch/balance es el problema abierto del
  proyecto (`balance_rate`); el modelo R6 es 50% balance en sim.
- **Pendiente:** modelo de mejor balance (más pasos / currículo inverso) → soltar en
  modo 7 (pipeline ya validado). Opcional: subir el freno θ del firmware de ±90°
  hacia ±100° (límite de sim) para no recortar el catch.


## [1.46.0] — 2026-06-22
### Bring-up sim2real del rig real: 4 bugs de integración corregidos + causa raíz identificada (13 Hz)

Sesión de banco con el modelo R6 (`r6_theta100_s0_step250000.zip`, 50 % balance en
sim, alineado a ±100°). Se convirtió el problema histórico de "nunca balancea / α≈0"
en una cadena de causas totalmente diagnosticada. Herramienta nueva:
`experiments/2026-06-22_r6_real_aligned/hw_bringup.py` (etapas `ping`/`sensors`/
`estop`/`deploy`, con `--dry-run`, `--reset-encoders`, `--action-mult`, watchdog de θ
y e-stop por Ctrl+C).

#### Bugs de integración corregidos (`src/qube_rl/envs/`)
- **Doble conversión de unidades.** `/rl_state` ya entrega **radianes** (firmware
  `handleRlState` aplica `DEG_TO_RAD`), pero `qube_real.py` y `train_real_v4.py`
  hacían `np.radians()` encima (÷57.3) → la política veía un estado casi-nulo
  siempre. **Causa real del `avg_alpha≈0.0001` de r4_real.** Ahora se lee crudo y se
  envuelve α con `wrap_angle`.
- **Signo de acción invertido.** En el rig, +acción mueve θ **negativo**; en sim,
  +acción → +θ. Nuevo `QubeRealEnv(invert_action=True)` (default): niega el comando
  en la frontera de hardware (tras los wrappers, para que el historial de acciones
  que ve la política quede en convención de sim).
- **Signo de α invertido.** Con la acción ya corregida, sim empareja (θ neg ↔ α
  **pos**) pero el HW crudo daba α **neg** (−56° claro bajo un pump real). Nuevo
  `QubeRealEnv(invert_alpha=True)` (default): invierte α y α̇. Con ambos signos, la
  telemetría real del paso 1 (θ−46/α+26) **calza con la trayectoria de sim**
  (θ−35/α+37).
- **Recompensa real invertida** (`train_real_v4.py`): `(cos α+1)/2` premiaba α=0
  (colgando); ahora `|α|/π` igual que la sim (0 colgando, 1 invertido).
- `make_real_env` propaga `invert_action`/`invert_alpha` (defaults `True`).

#### Causa raíz del fallo sim2real (★)
- **Frecuencia de control: el lazo PC-en-el-lazo por WiFi corre a ~13 Hz, no a los
  50 Hz de entrenamiento.** Medido: ~71 ms/paso (`/rl_cmd` ~40 ms + `/rl_state`
  ~34 ms) vs ≤20 ms necesarios. Cada acción se mantiene ~3.5× de más → el brazo se
  pasa antes de que la política corrija → runaway garantizado **sin importar signos
  ni torque**. Esto explica por qué toda prueba de hardware falló históricamente.
- **Solución: inferencia on-device (modo 7).** El firmware ya tiene el scaffolding
  (`policy_weights.h`, `rl_forward()`, buffer 4×9=36, freno ±90°); `export_rltools.py`
  exporta el actor SB3-SAC. Pendiente: conciliar la activación de salida (SAC
  determinista = `tanh(mu)`; el modo 7 hacía `raw_out*0.5`) y verificar el layout.


## [1.45.0] — 2026-06-22
### Zero de servo/péndulo disponible en modo RL (endpoint `/rl_cmd?z=1`)

#### Problema identificado
- En modo RL (modo 6), no existía forma de zeroear el encoder del servo o péndulo
  sin usar `/cmd?z=1` (que también resetea el PID) o `/rl_cmd?r=1` (que pisa el
  offset a 0, destruyendo cualquier zero previo).
- Esto impedía calibrar el origen del encoder antes de ensayos RL, afectando la
  consistencia de las observaciones entre episodios.

#### Cambios aplicados
**1. Nuevo endpoint `/rl_cmd?z=1` — zero servo en modo RL**
- Llama `zeroPositionHere()` (setea `positionOffsetDeg` = posición raw actual).
- Resetea `lqr_prevTheta` a 0 para que la primera derivada no tenga spike.
- NO llama `resetPid()` — preserva estado integral/derivativo del PID.

**2. Nuevo endpoint `/rl_cmd?zp=1` — zero péndulo en modo RL**
- Llama `zeroPendulumHere()` (setea `pendulumOffsetDeg` = posición raw actual).
- Resetea `lqr_prevAlpha` a 0.

#### Cambios de firmware
```cpp
// handleRlCmd — nuevos parámetros:
if (request->hasParam("z")) {
  zeroPositionHere();
  lqr_prevTheta = 0.0f;
  lastCommandMs = millis();
}
if (request->hasParam("zp")) {
  zeroPendulumHere();
  lqr_prevAlpha = 0.0f;
  lastCommandMs = millis();
}
```

#### Notas
- Endpoint seguro durante operación RL: no interfiere con `rlAction` ni modo.
- Uso: `GET /rl_cmd?z=1` antes de iniciar ensayo para calibrar origen.
- Herramienta MCP `qube_zero()` también agregada.


## [1.44.0] — 2026-06-18
### Correcciones de RL (REFERENCE.md Partes V/VI), auditoría de firmware y sync de docs

Implementa los arreglos identificados en `REFERENCE.md`. Los cambios de *defaults*
de entrenamiento mejoran el planteamiento pero **requieren reentrenar** para verse
reflejados en resultados; los modelos `.zip` existentes siguen cargando (layout 8-D
intacto). 84 tests pasan (`tests/test_fixes.py` añadido).

#### RL — correcciones (`src/qube_rl/`)
- **C1 — No terminar el episodio en el objetivo.** La terminación ya no depende de
  `alpha`: el invertido (α=±π) era el objetivo y estaba en el borde de terminación,
  por lo que el episodio terminaba justo al alcanzarlo. Ahora se termina solo por
  límite de servo (θ), sobrevelocidad, estado no finito o `TimeLimit`. Corregido en
  `envs/qube_sim.py` (`_is_terminal`) y `envs/qube_real.py` (antes terminaba a ~171°).
- **M3 — `TimeLimit`.** Nueva factory `envs/factory.py` (fuente única para construir
  entornos) que envuelve `gymnasium.wrappers.TimeLimit` (`max_episode_steps=500`,
  10 s a 50 Hz). Consolida las 5–6 copias divergentes de `make_env`/`make_real_env`.
- **A2 — Layout 8-D preservado.** `observation_from_state` envuelve `alpha` a [-π,π]
  (nuevo `utils.wrap_angle`) para no violar el `observation_space` aunque el péndulo gire.
- **C3 — Límite de brazo θ a ±120°** (`config.py`), según evidencia de los handoffs
  (reach ~8–10 % a ±90° → ~38 % a ±120°). `qube_real` ajustado para igualar el box.
- **C2 — Reward shaping basado en potencial** (policy-invariante, Ng et al. 1999):
  nuevo wrapper `wrappers/potential_shaping.py` (`PotentialShaping`), opt-in vía
  `--potential upright` en `train`/factory.
- **M2 — Métrica de éxito correcta.** Nuevo `metrics.py::evaluate_balance` (reach,
  balance ≥1 s invertido-y-lento, fracción de tiempo arriba, hold máximo). Reemplaza
  el proxy "pico α>120°" en `distill.py`; integrado en `auto_train.py`.
- **M1 — Multi-semilla.** `auto_train.py` corre cada config sobre `--seeds` y reporta
  media ± std (≥5 recomendado); selecciona el mejor reward por `balance_rate`.
- **D5 — Destilación.** Eliminados `temperature`/`alpha` muertos (nunca conectados a
  ninguna pérdida) en `distill.py`; documentado que es BC + RL, no KD con soft-targets.
- **D3 — Guard de exportación.** `export_rltools.py` avisa si `INPUT_DIM` del modelo no
  coincide con el dim esperado por el firmware (36 = 4×9). El rewire firmware 36→8 queda
  documentado como issue conocido (requiere prueba en HW).
- **D1/D2 — Docstrings/comentarios.** Corregido el docstring de `_init_state` (era
  "unstable/inverted", inicializa colgando/estable) y el comentario invertido en
  `exp_alpha_reward`.

#### Firmware (`esp32_qube/esp32_qube.ino`) — limpieza segura
- Eliminado el comentario huérfano `// Umbrales PID Péndulo (modo 3)` (sin código asociado).
- **Bug:** el parser serial aceptaba solo `m<=5`, bloqueando seleccionar los modos RL
  6/7 por consola serial; corregido a `m<=7`.
- Fallas de control profundas (ciclo límite del LQR, latencia de brownout ~100 ms,
  discontinuidad ±180°, mismatch de despliegue RL 36-hist vs 8-raw) **documentadas**
  como issues conocidos en `REFERENCE.md` (no se tocan sin pruebas en hardware).

#### Documentación — sincronización (Modo 3 ya estaba removido del firmware en v1.34)
- Quitado el Modo 3 (PID péndulo) de: `README.md`, `docs/http_api.md`,
  `docs/MODELO_FISICO_SISTEMA_QUBE.md`, `docs/mine/arquitectura.md`, `mcp/README.md`,
  `src/firmware/data/README.md`, `docs/research/*`, `docs/research/DRL_IMPLEMENTATION_PLAN.md`
  y la tesis (`tesis_usach/capitulos/Capitulo_04.tex`). `REFERENCE.md` marca como resueltos
  los ítems corregidos. `backup_l298n/` se deja intacto como registro histórico.

## [1.43.0] — 2026-06-18
### Cleanup GUI Tkinter + auditoría y mejoras de la GUI web embebida

#### GUI Tkinter eliminada
- Removidos `gui/app.py` y el paquete `src/qube_ui/` completo (`app.py`,
  `client.py`, `buffer.py`, `__main__.py`, `__init__.py`) — servía sobre todo
  para pruebas por serial y ya no aporta al proyecto. La **GUI web embebida**
  (servida por el ESP32 desde SPIFFS) la reemplaza por completo.
- Eliminados los tests asociados: `tests/test_buffer.py`, `tests/test_client.py`,
  `tests/test_integration.py`.
- Referencias actualizadas: `pyproject.toml` (quitado `src/qube_ui` de los
  paquetes hatch), `Makefile` (goal `run` eliminado), `README.md`, `AGENTS.md`
  y `experiments/README.md` (ejemplo de export CSV ahora apunta a la GUI web).

#### GUI web embebida — auditoría y mejoras (`src/firmware/data/index.html`)
- **Chart.js local**: se sirve `data/chart.min.js` (v4.5.1) en vez del CDN; antes
  las gráficas no cargaban en modo AP (sin internet). Se consolidó el `index.html`
  divergente de `esp32_qube_l298n/data/` y se eliminó esa carpeta legacy.
- **Fixes**: ID duplicado `btnCSV` (botón muerto en la topbar) removido; export
  CSV de tensión corregido (`v_bus` en vez de `voltage_v`); guarda de
  `ina_ok=false` (hueco en la gráfica de potencia y celdas CSV vacías en vez de 0).
- **Funcionalidad**: panel OTA reintegrado (`POST /update` con barra de progreso);
  modo `m7` (Deep RL on-device) añadido al selector; "Set Servo" ahora fuerza
  `m=2`; estado Deep RL (θ/α) refrescado en vivo desde el WebSocket; favicon vacío.
- Nuevo `src/firmware/data/README.md` documentando la GUI web, endpoints,
  telemetría e historial de auditoría. Pendientes (diferidos): de-inlinar handlers
  para CSP estricta; `m3` (PID péndulo) no se expone porque será removido.

## [1.42.1] — 2026-06-18
### MLflow como tracker único: se elimina TensorBoard; métricas de episodio

- **TensorBoard eliminado** (MLflow lo reemplaza): quitada la dependencia
  `tensorboard` (deps core y extra `rl`), `tensorboard_log`/`--log-dir`/`tb_log_name`
  de train/fast_train/finetune/auto_train, y el lector `EventAccumulator` de
  `auto_train` (ahora las métricas de episodio salen de `model.ep_info_buffer`).
  `runs/` queda ignorado (logs antiguos).
- **Fix del callback MLflow**: ahora registra también `rollout/ep_rew_mean` y
  `ep_len_mean` (recomputadas desde `ep_info_buffer`), no solo las `train/*` losses
  — antes se perdían por el timing de volcado del logger de SB3.
- Verificado: entrenamiento de 30k pasos logueado a MLflow (UI en puerto 5000,
  `sqlite:///mlflow.db`); 96 tests en verde en Python 3.13.

## [1.42.0] — 2026-06-17
### Auditoría estructural: correctitud, reproducibilidad e higiene del pipeline RL

Refactor estructural tras una auditoría del repo. **Los modelos entrenados antes
de esta versión quedan invalidados** por los fixes de correctitud (timing de
reward y drift de domain randomization) — re-entrenar antes de comparar resultados.

#### Bugs de correctitud corregidos
- **Off-by-one en `QubeSimEnv.step()`**: calculaba reward y observación sobre el
  estado *previo* a aplicar la acción, luego integraba. Ahora integra primero y
  reporta reward/obs del estado posterior (semántica MDP correcta).
- **Drift de domain randomization** (`QubeDynamics.randomize`): muestreaba
  alrededor del valor *ya randomizado* en vez del nominal, acumulando deriva en
  cada episodio (y rompiendo la reproducibilidad). Ahora snapshotea los nominales
  en construcción y muestrea siempre desde ellos; además clampa a valores físicos
  positivos (varias `*_std` ≥ media podían dar masa/fricción negativa).
- **Import roto en `distill.py`**: llamaba a `export_header` (inexistente). Ahora
  usa `export_rltools.export_model_to_header`, que además escribe el header
  directo al firmware (los pesos flasheados siempre coinciden con el modelo).
- **Singularidad de M(q)**: piso defensivo en la dinámica y error explícito en LQR.

#### Reproducibilidad
- `--seed` en `train`, `fast_train`, `finetune`, `auto_train`; propagado a
  numpy/torch/`SAC`/`env.reset`. El env usa su `np_random` (no el RNG global).
- `auto_train` deja de hardcodear `2026-06-15_training`; usa la fecha actual / `--out-dir`.

#### Coherencia sim ↔ real ↔ firmware
- Layout de observación unificado en una sola fuente (`utils.observation_from_state`),
  usada por `QubeSimEnv` y `QubeRealEnv` (8-D: `[θ, α, cos θ, sin θ, cos α, sin α, θ̇, α̇]`).
  Test fija el contrato y el input del firmware (9 features × 4 = 36).
- `MAX_VELOCITY` (config) compartido por el clamp de integración y el bound de
  observación (antes obs declaraba ±30 con dinámica a ±50); velocidad filtrada clampada.
- `finetune` por defecto iguala la frecuencia de entrenamiento (50 Hz) y advierte
  si difiere (el `HistoryWrapper` cambia el contexto temporal: 80 ms vs 400 ms).

#### Estructura y calidad
- Nuevo `qube_rl/config.py` (dataclasses) centraliza hiperparámetros SAC, límites,
  deadzone y arquitectura; elimina inconsistencias (buffer 1M vs 50k, batch 256 vs 128).
- `QubeSimEnv._update_state` descompuesto en `_integrate_euler` / `_quantize_angles` /
  `_estimate_velocities`. Constantes de reward documentadas; logging unificado.
- Lint del repo limpiado (ruff: 33 → 0 errores en `src`/`tests`); formato normalizado.
- Suite de tests RL nueva (qube_sim, rewards, wrappers, contrato de observación):
  46 → 85 tests. Workflow de CI (`.github/workflows/ci.yml`: ruff + format + pytest).
- Higiene: `.gitignore` excluye `models/*.zip` y `runs/`; HANDOFF movidos a `docs/handoffs/`.
  Target `make export-policy` para sincronizar el header del firmware.

#### Tracking de experimentos con MLflow (opcional)
- Nuevo `qube_rl/mlflow_tracking.py`: complementa TensorBoard (no lo reemplaza) vía
  un callback de SB3 que reenvía las métricas ya registradas, sin tocar el flujo.
- Cableado en `train`, `fast_train`, `finetune` y `auto_train` con `--mlflow`
  (+ `--mlflow-uri`, `--mlflow-experiment`): loguea params (dataclasses de `config`),
  métricas en streaming y el modelo `.zip` como artifact.
- Degrada con elegancia: si `mlflow` no está instalado o `--mlflow` está apagado,
  los helpers son no-ops. Dependencia opcional: `uv sync --extra tracking`.
- Backend por defecto **`sqlite:///mlflow.db`** (local, cero infra; el file store
  `./mlruns` está en modo mantenimiento y falla en MLflow 3.x). Ver con
  `mlflow ui --backend-store-uri sqlite:///mlflow.db`. Artefactos en `./mlartifacts`.
- 11 tests nuevos (96 en total); `.gitignore` excluye `mlflow.db`/`mlruns`/`mlartifacts`.

#### Pendiente (requiere hardware)
- Split del `esp32_qube_l298n.ino` (~2290 líneas) en módulos: la compilación se
  verifica (25 s) pero la preservación de comportamiento no, sin pruebas en hardware.
- Des-trackear binarios ya versionados: `git rm --cached models/*.zip runs/` (decidir
  destino externo, p. ej. Zenodo/HF, antes de commitear).

---

## [1.41.0] — 2026-06-17
### Entrenamiento 500K steps con linear_alpha: swing-up alcanzado en sim

#### Problema identificado
- El agente SAC previo (COS_ALPHA, 50K steps) no alcanzaba swing-up.
- El timeout de 3600s del harness solo permite ~250K steps por sesión (~75 fps CPU).

#### Cambios aplicados

**1. Entrenamiento 500K steps con `linear_alpha`**
- Se entrenó SAC con reward `linear_alpha`, red [64,64], lr=3e-4.
- Primera sesión: 250K steps (fast_train con chunks de 50K, 5 checkpoints guardados).
- Segunda sesión: continuación desde C5 (250K) por 250K más = 500K total.
- Modelo final: `models/qube_sac_linear_alpha_64_c5_cont.zip`.

**2. Evaluación en sim (10 episodios)**
- 3 de 10 episodios alcanzan max_alpha > 120° (criterio de éxito del handoff).
- Mejor episodio: max_alpha = 169° (casi inversión completa), reward = 11.4.
- ep_len_mean subió de 12 steps (C1) a 482 steps (C5_cont) durante entrenamiento.
- Success rate ~30%, consistencia baja pero swing-up demostrado.

**3. Exportación a C++**
- Pesos exportados a `src/firmware/esp32_qube_l298n/policy_weights.h`.
- Arquitectura: 36 → 64 → 64 → 1, 6,593 parámetros, 25.8 KB flash.
- Compatible con modo 7 (on-device inference en ESP32).

#### Cambios de firmware
```cpp
// policy_weights.h regenerado con pesos de 500K steps (linear_alpha)
// Arquitectura: [36, 64, 64, 1] — RLtools compatible
```

#### Notas
- El reward oscila durante entrenamiento (patrón típico de SAC en swing-up).
- La continuación desde C5 permitió alcanzar 169° de alpha donde C5 solo llegaba a 31°.
- Siguiente paso: fine-tuning en hardware o continuar entrenamiento para mejorar success rate.
- Verificar flash usage: `cd src/firmware && pio run -e esp32dev 2>&1 | grep Flash`.


## [1.40.0] — 2026-06-16
### Rewards densas para swing-up, fixes real env, modo 7 on-device inference

#### Problema identificado
- El agente SAC con `cos_alpha` no aprendía swing-up: gradiente ~0 cuando el péndulo cuelga (25x menor que lineal).
- Real env tenía obs mismatch (6 dims vs 8 de sim) y no convertía grados a radianes.
- `handleCmd` rechazaba `mode=7` (limitaba a 0-6).
- Modelo fine-tuned no funcionaba en hardware real (nada se movía).

#### Cambios aplicados

**1. Nuevas rewards densas (`src/qube_rl/rewards.py`)**
- `linear_alpha`: gradiente lineal `|alpha|/pi` — 25x más fuerte que `cos_alpha` near hanging.
- `linear_alpha_dense`: añade velocity shaping — recompensa al_dot cuando péndulo en mitad inferior (pumping).
- Ambas con penalty ligera de theta (-0.2 at ±90°), clip [-2, 1].
- Verificado: DOWN=0.0, 45°=0.25, UP=1.0.

**2. Fixes en real env (`src/qube_rl/envs/qube_real.py`)**
- Obs space corregido: 8 dims `[θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇]` (match sim).
- Conversión grados→radianes en `step()` y `reset()` (`np.radians(data["th"])`).

**3. Fix firmware (`esp32_qube_l298n.ino`)**
- `handleCmd`: `m <= 6` → `m <= 7` (acepta modo 7).
- Modo 7: forward pass on-device [36→64→64→1], ReLU, Hardtanh(-2,2).
- Historial buffer 4 pasos × 9 features = 36 inputs.
- Safety brake si theta > 90°.

**4. Handoff para entrenamiento overnight**
- Documento `HANDOFF_OVERNIGHT_TRAINING.md` con plan completo.
- Entrenamiento 500K steps con `linear_alpha` + [64,64].
- Monitoreo cada ~20 min vía TensorBoard.

#### Cambios de Python
```python
# rewards.py — nuevas rewards densas
def linear_alpha(state):
    al_rew = np.abs(al) / np.pi  # 25x gradiente near 0
    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2
    return float(al_rew + th_penalty)

# real env — fix grados→radianes
self._state[THETA] = np.radians(data["th"])
self._state[ALPHA] = np.radians(data["al"])
```

#### Notas
- Entrenamiento: `uv run python -m qube_rl.train --timesteps 500000 --reward linear_alpha --net-arch 64`
- Export: `uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip`
- Deploy: `pio run -e esp32dev --target upload` → `GET /cmd?m=7`
- Verificar en sim antes de deploy: max_alpha debe superar 120° en al menos 1/10 episodios.

## [1.39.0] — 2026-06-16
### Entrenamiento RLtools-compatible: reward swingup_balance, red [64,64], exportación C++

#### Problema identificado
- Red [128,128] en `fast_train.py` era demasiado grande para inferencia ESP32 (~51 KB flash vs 17 KB con RLtools).
- No existía reward que adaptara penalidades entre fases de swing-up y balance.
- Sin forma de exportar pesos SB3 al formato C++ de RLtools (`persist_code`).

#### Cambios aplicados

**1. Nueva reward `swingup_balance` (`src/qube_rl/rewards.py`)**
- Penalidades leves durante swing-up (brazo libre), pesadas durante balance (brazo centrado).
- `balance_weight`: 0.1 (down) → 0.5 (inverted). `vel_weight`: 0.0005 → 0.0025.
- Verificado: DOWN=0.0, 45°=0.15, 135°=0.85, UP=1.0.

**2. Red [64,64] por defecto en `train.py`**
- Nuevo flag `--net-arch` (default 64). Guarda como `qube_sac_{net}x2.zip`.
- ~17 KB flash, ~1-2 KB RAM en ESP32 — compatible RLtools.

**3. Refactor de `fast_train.py`**
- Usa `swingup_balance` y [64,64] por defecto. Nuevos flags: `--reward`, `--net-arch`, `--exp-name`.

**4. Nuevo módulo `export_rltools.py`**
- Extrae pesos actor SB3 → genera header C++ `constexpr float[]` (RLtools `persist_code`).
- Uso: `uv run python -m qube_rl.export_rltools --model models/qube_sac_64x2.zip`

#### Notas
- Flujo completo: `train.py` → `export_rltools.py` → firmware ESP32 con RLtools.
- Compatible con modelos existentes: `--net-arch 256` reproduce config anterior.
- Sin cambios al firmware ni interfaz HTTP — solo pipeline de entrenamiento.

## [1.38.0] — 2026-06-16
### Filtro de Kalman (LQG) para estimación de estados del LQR

#### Problema identificado
El LQR (modo 4) estimaba velocidades angulares mediante diferencias finitas + filtro EMA,
que es ruidoso y introduce fase. El docs del proyecto priorizaba LQG (LQR + Kalman) como
mejora #1 por su factibilidad en ESP32 y alto impacto en desempeño.

#### Cambios aplicados

**1. Implementación del Filtro de Kalman discreto (4 estados)**
- Estado: `x = [theta, alpha, dtheta, dalpha]` (posiciones y velocidades)
- Mediciones: `z = [theta, alpha]` (solo posiciones de encoder)
- Modelo: péndulo rotatorio invertido linearizado, discretizado con Euler a 500 Hz
- Predict: propagación con modelo físico (motor + péndulo)
- Update: corrección con mediciones de encoder (posiciones)
- Matrices Q, R, P ajustables en runtime

**2. Integración con LQR (modo 4)**
- Cuando `kf_enabled=true`: LQR usa velocidades estimadas por el KF
- Cuando `kf_enabled=false`: LQR usa EMA (comportamiento original, sin cambios)
- EMA siempre se calcula como fallback (no se pierde información)

**3. HTTP command `kf<0|1>`**
- `GET /cmd?kf=1` activa el filtro de Kalman (resetea estado)
- `GET /cmd?kf=0` vuelve al filtro EMA
- Toggle en tiempo real para comparar desempeño

**4. Telemetría expandida en `/state`**
- `kf_enabled`: estado del filtro
- `kf_theta`, `kf_alpha`: posiciones estimadas por KF
- `kf_dtheta`, `kf_dalpha`: velocidades estimadas por KF (la mejora principal)

#### Arquitectura del KF
```
Modelo discreto (Euler, Ts=2ms):
  Ad = [1  0  Ts   0    ]    Bd = [0, 0, Km*Ts, 0]^T
       [0  1   0  Ts   ]
       [0  0 1-b1*Ts  0     ]
       [0  w2*Ts  0  1-b2*Ts]

H = [1 0 0 0]  (mide posiciones)
    [0 1 0 0]

Predict: x = Ad*x + Bd*u,  P = Ad*P*Ad^T + Q
Update:  K = P*H^T*(H*P*H^T + R)^-1,  x = x + K*(z - H*x)
```

#### Parámetros del modelo
| Parámetro | Valor | Descripción |
|-----------|-------|-------------|
| `KF_MOTOR_GAIN` | 50.0 | PWM -> deg/s^2 |
| `KF_SERVO_FRIC` | 2.0 | Amortiguamiento servo (1/s) |
| `KF_PEND_FREQ` | 12.3 | sqrt(g/l) pendulo [rad/s] |
| `KF_PEND_FRIC` | 0.5 | Amortiguamiento pendulo (1/s) |
| `kf_Q_pos` | 0.1 | Ruido proceso: posicion (deg^2) |
| `kf_Q_vel` | 10.0 | Ruido proceso: velocidad (deg/s^2) |
| `kf_R_pos` | 0.5 | Ruido medicion: encoder (deg^2) |

#### Cambios de firmware
```cpp
// Filtro de Kalman: predict + update en cada ciclo LQR
if (kf_enabled) {
  kalmanPredict((float)lastPwmCmd / (float)PWM_MAX);
  kalmanUpdate(theta, alpha_raw);
}
// LQR usa KF cuando habilitado
float velTheta_ctrl = kf_enabled ? kf_x[2] : lqr_filteredVelTheta;
float velAlpha_ctrl = kf_enabled ? kf_x[3] : lqr_filteredVelAlpha;
```

#### Notas
- RAM: ~200 bytes adicionales (P 4x4 + K 4x2 + x 4)
- CPU: <50 us por ciclo (predict + update) — insignificante a 500 Hz
- No afecta otros modos (PID, swing-up) — solo LQR (modo 4)
- Parámetros del modelo (`KF_MOTOR_GAIN`, etc.) requieren calibración experimental
- Toggle: `curl "http://192.168.4.1/cmd?kf=1"`


## [1.37.0] — 2026-06-11
### Swing-up: PWM acotado + param HTTP ajustable en vivo

#### Problema identificado
El servo golpeaba el tope mecánico izquierdo durante el swing-up porque PWM_MAX=100
era excesivo para resonant pumping. El servo se saturaba en el borde y no podía
oscilar en fase con el péndulo. Además, no había forma de ajustar el PWM sin
recompilar el firmware.

#### Cambios aplicados

**1. `SWINGUP_PWM_MAX` → `swingupPwmMax` (mutable)**
- Antes: `const int SWINGUP_PWM_MAX = 100` (const, inmutable)
- Ahora: `int swingupPwmMax = 50` (configurable vía HTTP en runtime)
- Rango aceptado: 10–100

**2. HTTP param `sp<val>`**
- Nuevo handler en `handleCmd`: `?sp=55` ajusta `swingupPwmMax` en tiempo real
- Permite encontrar el sweet spot sin recompilar
- Formato: `GET /cmd?sp=55`

**3. Todos los paths de modo 5 usan `swingupPwmMax`**
- Kick sinusoidal (péndulo quieto): `constrain(pwm, -swingupPwmMax, swingupPwmMax)`
- Resonant pump (péndulo oscilando): `constrain(pwm, -swingupPwmMax, swingupPwmMax)`
- Damping (próximo a vertical): `constrain(..., -swingupPwmMax, swingupPwmMax)`
- Recovery brake: `constrain(..., -swingupPwmMax, swingupPwmMax)`
- Servo limit brake: `constrain(center_pwm, -swingupPwmMax, swingupPwmMax)`
- Anti-spin brake se mantiene en `PWM_MAX` (frenado máximo para parar spinning)

**4. Servo limit reducido: 80° → 60°**
- Brakes antes de llegar al tope mecánico
- Previene que el servo se acumule en el borde durante pumping

**5. Fix bug pre-existente: `sv` → `pos`**
- Variable `sv` no existía en el scope del modo 5
- Corregida a `pos` (la variable real de posición del servo, línea 1407)

**6. Script `flash.py` — build+upload vía HTTP**
- Usa `POST /update` en vez de espota.py/esptool
- Soluciona el lock de OneDrive sobre `firmware.bin`
- Si `.bin` está bloqueado, convierte `.elf`→`.bin` en `/tmp`
- Args: `--ip`, `--build-only`, `--upload-only`

#### Cambios de firmware
```cpp
// Constante mutable (antes era const)
int swingupPwmMax = 50;  // configurable por HTTP: sp<val>

// Handler HTTP nuevo
if (request->hasParam("sp")) {
  swingupPwmMax = constrain(request->getParam("sp")->value().toInt(), 10, 100);
}

// Todos los constrain del modo 5 ahora usan swingupPwmMax
pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
```

#### Notas
- Default: `swingupPwmMax=50` (punto medio entre 35=insuficiente y 65=excesivo)
- Para ajustar en vivo: `curl "http://IP/cmd?sp=55"`
- Compilación: RAM 15.0%, Flash 73.1%
- Sweep parcial: sp=45 → 80% catch rate

## [1.36.0] — 2026-06-08
### Swing-up funcionando con driver BTS7960

#### Problema identificado
El swing-up con el nuevo driver BTS7960 no funcionaba: el servo se atascaba en los límites mecánicos, la bomba de energía no consideraba la posición del servo, y el frenado de emergencia era inefectivo por la soft saturation.

#### Cambios aplicados

**1. Filtro EMA para velocidad del péndulo en swing-up**
- Antes: `alpha_dot` sin filtrar a 500Hz causaba ruido que impedía el kick alternante
- Ahora: `swing_filteredVelAlpha` con misma constante que LQR (0.60)

**2. `setMotorDirect()` — bypass de soft saturation**
- Función nueva para frenado de emergencia sin la reducción de PWM por soft saturation
- Hard stop a 150° motor-shaft usa `setMotorDirect` para frenado efectivo

**3. Modulación por posición del servo en bomba de energía**
- Amplitud del bombeo se reduce linealmente: 100% en centro, 0% a 200°
- Previene que el servo se acumule en un lado del rango
- Cutoff 200° (actúa solo cerca del hard stop 150°)

**4. Centering suave del servo durante swing-up**
- kp=0.15 proporcional a posición raw del servo
- Guía el servo de vuelta al centro sin frenar la bomba de energía

**5. Parámetros ajustados para BTS7960**
- Soft saturation k: 80° → 120°
- Damping threshold: 120° → 165°
- LQR transition: hemisferio 165°→140°, velocidad 10→50°/s, distancia 1°→20°
- Hard stop: 150° motor-shaft (≈80° output)

**6. Bug Python 3.14 en scripts de sweep**
- `urlopen(url, 5)` interpretaba 5 como data, no timeout → fix: `urlopen(url, timeout=5)`

#### Resultados del entrenamiento (Fase 1-4)
- **ke=0.65 optimo** (25-36% catch rate, hold promedio 82s)
- **bt=1 optimo** (mejor catch rate, servo controlado)
- **LQR hold: 59-88s** (de 90s posibles)
- Transiciones: hemisferio >130°, vel <80°/s, dist <25°
- **Peak detection**: detecta pico de posicion (alpha_dot zero crossing) — sin mejora significativa
- **Forced transition a 165°+**: sin mejora significativa
- **Angle-dependent PWM limit**: PEOR — mata transferencia de energia
- **Ramp-down desde 60°**: PEOR — servo sin autoridad
- **Hard stop final: 120° motor-shaft** con setMotorDirect

#### Problema pendiente: brownout
- Crash rate 20%: motor golpea limite mecanico, voltaje baja
- Angle-dependent limit reduce energia — no es solucion firmware
- **Solucion requerida: capacitor 470-1000uF en rail 5V**

#### Analisis de 173 CSVs
- Catch SOLO ocurre a 150°+ (28% catch rate en 150-180°, 100% en 200°+)
- 85% de intentos no llegan a 150° — bottleneck es energia de bombeo

#### Notas
- Scripts: `test_lqr.py [ke] [attempts] [duration]`, `analyze_all.py`
- Parámetros tuneables vía HTTP: `?ke=`, `?bt=`
- Archivos: `COMPARISON.md` (historico), `SESSION_LOG.md` (detallado)

## [1.35.1] — 2026-06-08
### Fix: selector de modo + reparación SPIFFS + Chart.js CDN

#### Problema 1: Selector de modo se revertía a STOP
El selector de modo en la GUI HTML (`data/index.html`) se revertía inmediatamente a STOP al hacer clic en "Aplicar".

**Causa raíz:** `cmd()` limpiaba `modeUserOverride=false` antes de que el `fetch()` completara. El WebSocket (100ms) enviaba `mode=0` y revertía el selector.

**Fix:** Eliminadas `modeUserOverride=false` y `clearTimeout(modeOverrideTimer)` de `cmd()`. Ahora se gestiona exclusivamente por el `onchange` del `<select>` (8s de gracia).

#### Problema 2: SPIFFS corrupto
Los uploads OTA de SPIFFS (`pio run --target uploadfs`) reportaban SUCCESS pero el contenido no cambiaba. El ESP32 servía archivos viejos o devolvía 500.

**Fix:** Agregado endpoint `GET /format` al firmware que ejecuta `SPIFFS.format()` + `ESP.restart()`. Después se suben los archivos vía `POST /fs`.

#### Problema 3: Chart.js no disponible offline
`chart.min.js` (208KB) no se podía subir a SPIFFS corrupto.

**Fix:** Cambiado `<script src="/chart.min.js">` a CDN de jsDelivr (`cdn.jsdelivr.net/npm/chart.js@4.4.7`). Requiere internet (modo STA).

#### Cambios de firmware
```cpp
// Nuevo endpoint /format
server.on("/format", HTTP_GET, [](AsyncWebServerRequest *request) {
  bool ok = SPIFFS.format();
  request->send(200, "application/json", ok ? "{\"ok\":true}" : "{\"ok\":false}");
  delay(500);
  ESP.restart();
});

#### Notas
- Para reparar SPIFFS en el futuro: `GET /format` → subir archivos vía `POST /fs`
- El parámetro `reboot` temporal en `/cmd` fue removido (ya existe `/restart`)
- OneDrive bloquea archivos `.pio/build` durante sync — usar directorio temporal para builds OTA

## [1.35.0] — 2026-06-08
### Migración de driver de motor: L298N → BTS7960

#### Problema identificado
El L298N (H-Bridge BJT) tiene limitaciones significativas: caída de voltaje de ~2V por los transistores bipolares, corriente máxima de 2A continua (3A pico), y ruido de conmutación PWM de ~100 mV pico que afecta las señales de encoder. Además, se requiere disipador para operación sostenida.

#### Decisión
Migrar a **BTS7960** (Infineon, Dual Half-Bridge MOSFET) — módulo IBT-2. Mejoras sustanciales:

| Parámetro | L298N (antes) | BTS7960 (ahora) |
|-----------|--------------|-----------------|
| Tecnología | BJT | MOSFET |
| RDS(on) total | ~530 mΩ | ~32 mΩ (16 mΩ × 2) |
| Caída de voltaje @ 2A | ~2.0 V | ~0.5 V |
| Corriente máxima | 2A cont. / 3A pico | 10A cont. / 43A pico |
| Disipación @ 2A | ~4 W (requiere disipador) | ~0.1 W (sin disipador) |
| Ruido PWM switching | ~100 mV pico | ~20 mV pico |
| Protecciones | Ninguna integrada | Overcurrent, OTP, UVLO, SCP |
| Costo | $1.50–3 USD | $2–5 USD |

#### Conexiones (GPIOs sin cambio)

| Función | GPIO ESP32 | Conexión L298N (antes) | Conexión BTS7960 (ahora) |
|---------|-----------|----------------------|------------------------|
| PWM adelante | GPIO26 | IN1 | RPWM |
| PWM reversa | GPIO27 | IN2 | LPWM |
| Enable | GPIO25 | ENA (jumper) | R_EN/L_EN (pull-up interno) |
| Motor + | — | OUT1 | M+ |
| Motor − | — | OUT2 | M− |

#### Cambios de documentación
1. **README.md**: Diagrama de arquitectura, topología de potencia, pinout completo, BOM, Cableado de EN, tabla de comparativa de rendimiento, referencias/datasheets actualizados
2. **MODELO_FISICO_SISTEMA_QUBE.md**: Modelo del puente H (§4), topología de MOSFETs, tabla PWM RPWM/LPWM, modelo de pérdidas con RDS(on), ecuación del bloque motor, fuentes de ruido reducidas
3. **Investigación Modernización**: Diagrama de bloques, flujo de datos, asignación de pines, tabla comparativa, BOM
4. **estabilizacion_senales.md**: Tablas de ruido RF/budget, diagramas de tierra (star ground)
5. **integracion_encoder_pendulo.md**: Estado del driver
6. **Validation docs** (5 archivos): Marco científico, resumen ejecutivo, checklist, matriz de referencias
7. **AI research docs** (4 archivos): Modelado LQR, CD40106BE, condicionamiento encoder, RL
8. **src/qube_ui/app.py**: Título de ventana y header
9. **AGENTS.md**: Tabla de arquitectura base
10. **Backup L298N**: Documentación anterior preservada en `backup_l298n/` (gitignored)

#### Archivos no modificados (intencionalmente)
- **Firmware** (`esp32_qube_l298n.ino`): No requiere cambios — el control PWM diferencial IN1/IN2 es idéntico a RPWM/LPWM. Los GPIOs (26, 27) permanecen igual. `MOTOR_DIR` puede necesitar ajuste al instalar el nuevo driver.
- **CHANGELOG entradas anteriores**: Registros históricos preservados con referencias L298N originales
- **Session logs de experimentos**: Datos de sesiones con L298N preservados intactos

#### Notas
- No se requiere recompilar firmware — el esquema de control PWM es compatible (IN1/IN2 = RPWM/LPWM)
- Al instalar el BTS7960, verificar que `MOTOR_DIR` sea correcto (puede requerir invertir cables M+/M−)
- El módulo IBT-2 tiene R_EN y L_EN con pull-up interno — no es necesario conectar el pin EN
- La reducción de ruido de ~5× mejora la relación señal/ruido del encoder (verificado experimentalmente en sesión 2026-06-04: ~20 mV vs ~100 mV)


## [1.34.0] — 2026-06-04
### Eliminación completa del PID Péndulo (modo 3)

#### Problema identificado
El péndulo del QUBE es un brazo articulado pasivo sin motor propio. El modo 3 (PID Péndulo) intentaba controlar algo que no existe físicamente. Se eliminó completamente del firmware, interfaz web, GUI Python y servidor MCP.

#### Cambios de firmware
1. **Variables eliminadas**: `Kp_pend`, `Ki_pend`, `Kd_pend`, `integralTermPend`, `filteredVelPend`, `pendulum_setpoint_deg`
2. **Constantes eliminadas**: `PEND_ANTIWIND_*`, `PEND_STICTION_*`, `PEND_DEADBAND_*`, `PEND_LIMIT_*` (11 constantes)
3. **Función eliminada**: `resetPendulumPid()`
4. **Bloque modo 3 eliminado**: todo el control PID del péndulo en el loop principal
5. **Handlers HTTP eliminados**: `sp` (setpoint péndulo), `kpp`/`kip`/`kdp` (gains péndulo)
6. **Serial**: sub-comando `sp` eliminado, referencias removidas de handlers `zp`, `op`, `edp`, `cprp`, `r`
7. **Telemetría JSON**: removidos `pend_setpoint_deg` y `pend_error_deg` de `/state`
8. **Conservado**: `prevPosPend` (swing-up), `VEL_ALPHA_PEND` (LQR), encoder péndulo, modos 4 y 5

#### Cambios de interfaz web (SPIFFS)
1. **index.html** (ambos data/): opción `PID Péndulo` removida del selector de modos
2. **Panel PID Péndulo eliminado**: entradas Kp/Ki/Kd y botón OK
3. **Fila SP P eliminada**: input setpoint péndulo y botón Set
4. **Script restaurado**: funciones `toggleRec()`, `clearRec()`, `exportCSV()`, chart flush optimization, mode override

#### Cambios de GUI Python
1. **client.py**: métodos `set_pendulum_setpoint()` y `set_pendulum_pid()` eliminados
2. **app.py**: `3: "PID Péndulo"` removido de MODE_NAMES, secciones UI SETPOINT PÉNDULO y PID PÉNDULO eliminadas, métodos `_send_pendulum_setpoint()` y `_send_pendulum_pid()` eliminados
3. **Conservado**: gráfico péndulo, status labels, LQR, Swing-up, calibración (CPR/dir/offset péndulo)

#### Cambios MCP
1. **Herramienta `qube_set_swing_up()` eliminada**
2. **`qube_set_mode()`**: modo 3 removido de descripción y diccionario

#### Archivos modificados
- `src/firmware/esp32_qube_l298n/esp32_qube_l298n.ino`
- `src/firmware/data/index.html`
- `src/firmware/esp32_qube_l298n/data/index.html`
- `src/qube_ui/app.py`
- `src/qube_ui/client.py`
- `mcp/esp32_qube_server.py`


## [1.33.0] — 2026-06-04
### Firmware: alpha continuo, recovery persistente, dead zone + hardware fixes

#### Sesión nocturna — 22+ iteraciones de firmware, 3+ horas

#### Cambios de firmware (críticos)
1. **Alpha continuo para LQR**: `alpha` calculado con aritmética modular usando `pendPosRaw` en vez de `pendPos - copysign(180, pendPos)`. Elimina la discontinuidad en ±180° que rompía el LQR y el fallback.
2. **Recovery persistente en swing-up**: Variable global `swing_recovering` que mantiene el motor apagado cuando el péndulo cruza la vertical (`|pendPosRaw| > 180°`), espera a que caiga al fondo (`|pendPos| < 30°`), y reanuda el pumping.
3. **Dead zone a 160°**: El swing-up no bombea cuando `|pendPosRaw| > 160°`. Permite que el péndulo alcance ±170° sin overshoot a spinning.
4. **Damping progresivo 150°-180°**: Damping lineal de 0.3 a 1.0 del PWM máximo según proximidad a la vertical.
5. **LQR K2_NEAR=30, K4_NEAR=15**: Gains probados que lograron 55+ segundos de estabilización (revertido de experimentos con K2=35, K4=20 que empeoraban el LQR).
6. **Catch mode ±60 PWM**: Frenado al entrar a LQR (era ±20).
7. **Fallback usa `pendPosRaw > 360°`**: En vez de `alpha > 45°` (wrapped) que no se activaba.
8. **Servo protection direction-aware**: Corta PWM que empuja hacia el hard stop del servo (±70° → ±85°).
9. **Anti-spin threshold 360°**: Reducido de 720° para detectar spinning antes.
10. **`balance_threshold = 1.0°`**: Transicionar a LQR solo cuando el péndulo está a <1° de la vertical.

#### Resultados
- Swing-up alcanza ±170° consistentemente ✅
- LQR atrapa el péndulo (mejor resultado: 11.3 segundos) ✅
- Servo protection previene brownout ✅
- Alpha continuo implementado (pendiente de prueba completa) ✅
- **LQR no estabiliza sostenidamente** — oscilaciones demasiado grandes después de la captura ❌

#### Hardware
- **INA219 dañado parcialmente**: Lecturas inconsistentes tras picos de corriente del diodo invertido. `ina_ok: true` pero voltaje inestable.
- **Diodo 1N4007 quemado**: Se quemó por polaridad invertida. **No usar diodo externo con H-bridge** — el L298N tiene diodos flyback internos.
- **3 capacitores dañados** (470µF, 220µF, 100µF): Se dañaron por polaridad invertida. Descartar.
- **LM2596 descalibrado temporalmente**: Se ajustó a 5V con potenciómetro.

#### Archivos
- `experiments/2026-06-03_swing/SESSION_LOG_20260604.md` — log completo de la sesión
- `experiments/2026-06-03_swing/data/` — 5+ CSVs de tests

#### Notas
- RAM: 15.0%, Flash: 72.5%
- Error de caché PlatformIO: `pio run -t clean` antes de recompilar si aparece `FileNotFoundError: .sconsign312.tmp`
- Próximo paso: probar firmware con alpha continuo + recovery en test de 90s

---

# CHANGELOG — QUBE ESP32 (Firmware + Documentación)

Registro de cambios del firmware `esp32_qube_l298n.ino` y documentación del proyecto para la modernización de la plataforma QUBE Servo en el marco de la tesis.

---
## [1.32.0] — 2026-06-04
### GUI HTML: selector de modos, recolección de datos, fix freeze

#### Problema identificado
Selector de modos desincronizado, freeze de la página, y botón Set no movía el motor.

#### Cambios aplicados
1. **Selector de modos**: `selected` movido a STOP (modo 0), WebSocket sincroniza el modo
   al dropdown con flag `modeUserOverride` (8s) para no sobreescribir selección manual.
2. **Panel "Recolección de datos"**: botones Grabar/Exportar CSV/Borrar. Datos solo se
   acumulan cuando el usuario presiona Grabar. Estado visible con conteo de muestras y tiempo.
3. **Fix freeze**: chart updates throttleados a 200ms, `splice(0,n)` batch en vez de `shift()`,
   CSV export usa `Array.push + join` en vez de concatenación de strings.
4. **Botones Set Servo / Set Pén**: ahora envían `m=2&s=VALUE` y `m=3&sp=VALUE` respectivamente,
   activando el modo automáticamente. Setpoints separados en vez de enviarse juntos.
5. **SPIFFS upload**: se usó endpoint `/fs` POST del firmware (SPIFFS OTA no escribe).

#### Archivos modificados
`src/firmware/esp32_qube_l298n/data/index.html` (reescritura completa)

---

## [1.31.1] — 2026-06-04
### Firmware: tuning LQR gains + handoff document

#### Cambios aplicados
1. **K2_NEAR**: 30→35 (subido ligeramente para más autoridad cerca de vertical)
2. **K4_NEAR**: 20→15 (revertido — K4_NEAR=20 empeora el LQR: 3s vs 55s con 15)
3. **Handoff document**: `experiments/2026-06-03_swing/HANDOFF.md` con todos los
   parámetros, bugs corregidos, CSVs, y próximos pasos

#### Hallazgo importante
K4_NEAR=20 es peor que K4_NEAR=15. Con K4=20 el LQR pierde el péndulo en ~3s
vs 55+ s con K4=15. El damping excesivo cerca de la vertical parece desestabilizar
el ciclo límite.

#### Notas
Compilación: ✅ RAM 15.0%, Flash 72.5%
27+ CSVs de tests en `experiments/2026-06-03_swing/data/`

---

## [1.31.0] — 2026-06-04
### Firmware: LQR sostiene péndulo invertido 55+ segundos

#### Resultado
El LQR mantiene el péndulo en modo 4 (control invertido) durante **55+ segundos**
en un ciclo límite estable alrededor de ±180°. El péndulo oscila entre -130° y
+210° (wrapped) pero nunca cae al fondo.

#### Cambios aplicados
1. **LQR gains moderados**: K2_NEAR 60→30, K4_NEAR 25→15 (reduce overshoot)
2. **LQR_NEAR_DEG**: 15→25° (gain scheduling en rango más amplio)
3. **ke_gain**: 0.45→0.5 (más autoridad en swing-up)
4. **LQR_FALLBACK_ALPHA_DEG**: 45→30° (evita soltar el péndulo innecesariamente)
5. **Servo centering**: kp=0.2 en swing-up (reduce oscilación del servo)
6. **Soft saturation**: k=80°, y=2 (protección suave contra hard stop)
7. **Anti-spin con cooldown**: 1s, reset inmediato de offset
8. **Disipación de energía**: threshold 0.95, brake progresivo

#### Parámetros finales del sistema
| Parámetro | Valor |
|---|---|
| ke_gain | 0.5 |
| balance_threshold | 5° |
| vel threshold | 20°/s |
| K1, K2 (base) | 2.0, 22 |
| K2_NEAR, K4_NEAR | 30, 15 |
| LQR_NEAR_DEG | 25° |
| LQR_FALLBACK_ALPHA_DEG | 30° |
| LQR_FALLBACK_TIME_MS | 500ms |
| soft saturation k | 80° |
| centering_kp | 0.2 |

#### Notas
El sistema entra en un ciclo límite — el péndulo no se estabiliza en exactamente
180° pero se mantiene en el hemisferio superior indefinidamente. Para lograr
estabilización completa se requiere reducir la amplitud del ciclo límite, posiblemente
con gains LQR más altos cuando el péndulo está muy cerca de ±180°.

---

## [1.30.1] — 2026-06-03
### Firmware: bug crítico `if`→`else if` en cadenas de modo + disipación swing-up

#### Bug crítico descubierto
Los bloques de modo 2/3/4/5 usaban `if (mode == N)` independientes en vez de
`else if`. Cuando el modo cambiaba (swing-up→LQR), el bloque del modo anterior
seguía ejecutándose y sobreescribía `pwm`.

**Efecto**: En transición swing-up→LQR, el anti-spin brake de modo 5 escribía
`pwm = -100` sobre el LQR, causando que perdiera el péndulo inmediatamente.

**Fix**: Cambiado a cadena `if/else if` (INCOMPLETO — falta eliminar `}` extra
en cierre de modo 3, línea ~1505).

#### Disipación de energía en swing-up
- `energy_ratio >= 0.9`: freno progresivo (brake_gain 0.3→1.0 lineal)
- `energy_ratio >= 0.85`: bombeo reducido al 50%
- `energy_ratio < 0.85`: bombeo normal
- Resultado: péndulo oscila estable ±160° sin spinning

#### Anti-spin con cooldown
- Reset inmediato de offset + freno PWM_MAX + cooldown 1000ms
- Reset de cooldown al entrar a LQR

#### Notas
- Compilación pendiente (error de scope por `}` extra)
- Tests CSV en `experiments/2026-06-03_swing/data/` (19 archivos)
- Log completo en `experiments/2026-06-03_swing/SESSION_LOG.md`

---

## [1.30.0] — 2026-06-03
### Firmware: OTA web + SPIFFS file upload + GUI flasheo

#### Cambios aplicados

**1. Endpoint `/update` (flasheo firmware vía HTTP)**
- `POST /update` acepta multipart con binario `.bin`, escribe con `Update` library, reinicia al completar.
- Detiene modo y motor antes de flashear.

**2. Endpoint `/fs` (upload de archivos a SPIFFS)**
- `POST /fs` acepta multipart con archivo, escribe directamente a SPIFFS (`/filename`).
- Permite actualizar `index.html` desde el navegador sin reflashear toda la partición SPIFFS.

**3. Endpoint `/restart` (reinicio remoto)**
- `GET /restart` responde `{"ok":true}` y reinicia el ESP32.

**4. GUI HTML: panel Firmware OTA**
- Nuevo panel "Firmware OTA" en el sidebar derecho de la GUI web (`index.html`).
- Selector de archivo `.bin`, botón "Flashear", barra de progreso con porcentaje.
- Upload directo a `/update` con `XMLHttpRequest` para feedback en tiempo real.
- CSS: `.ota-bar`, `.ota-fill`, `.ota-status` integrado al tema dark existente.

**5. GUI Python/Tkinter: panel de flasheo**
- Nueva sección "⚡ FIRMWARE" en el panel lateral de `src/qube_ui/app.py`.
- Selector de entorno (`esp32dev`, `esp32dev_debug`, `esp32dev_ota`).
- Selector de puerto serie con detección automática vía `pyserial` + botón ⟳.
- Botón "⚡ Flashear" ejecuta `pio run` + `pio run --target upload` en thread background.
- Botón "✕ Cancelar" aborta el proceso.
- Log de output con scroll, limpieza de ANSI y `\r`.

**6. Fix: auto-scaling de ejes Y en gráficos**
- Péndulo y servo: margen cambiado de `std * 0.5, min 5°` a `ptp * 0.1, min 5°`.
- Péndulo: Y clampeado a ±200° (rango físico real del encoder).
- Fix: datos concentrados cerca de borde ya no se cortan.

#### Notas
- RAM: 15.0% (49092/327680), Flash: 72.5% (949961/1310720).
- Para actualizar solo el HTML sin reflashear firmware: `curl -X POST http://192.168.100.50/fs -F "file=@index.html;filename=index.html"`.
- Upload SPIFFS vía `pio run --target uploadfs` con `ArduinoOTA` puede no reiniciar automáticamente; el endpoint `/fs` es más confiable para updates incrementales.

---


## [1.29.0] — 2026-06-03
### Firmware: anti-spin, LQR catch mode, gain scheduling, MCP docs

#### Cambios aplicados

**1. Anti-spin en swing-up (modo 5)**
- Detección de spinning: delta de posición raw >200° entre samples o acumulación >720°.
- Cuando detecta spinning: frena según dirección de velocidad (60% PWM_MAX).
- Cuando se frena: recalibra offset del encoder.
- Energía calculada con ángulo raw (evita error por wrap en oscilaciones normales).

**2. LQR catch mode**
- Al transicionar de swing-up a LQR, aplica freno máximo por 150ms.
- Objetivo: disipar energía cinética antes de intentar equilibrar.
- Freno basado en dirección de velocidad angular raw.

**3. Gain scheduling LQR**
- Gains base: K1=2.0, K2=22, K3=1.5, K4=9.
- Gains agresivos cerca de vertical (<15°): K2_NEAR=60, K4_NEAR=25.
- Hard stop proporcional (2 PWM/grado de overshoot).

**4. Transición más estricta**
- `balance_threshold`: 12°→5°.
- `SWINGUP_TRANSITION_VEL_DPS`: 500→80°/s.
- `VEL_ALPHA_PEND`: 0.15→0.60 (respuesta más rápida).

**5. MCP server**
- Nueva herramienta `pio_ota_flash(ip)` para flasheo OTA desde MCP.
- Documentación completa en `mcp/README.md`.

**6. Tests y logging**
- Script `experiments/2026-06-03_swing/test_swing.py` con logging CSV.
- 12 tests realizados, análisis en `experiments/2026-06-03_swing/ANALYSIS.md`.

#### Resultados de pruebas
- Swing-up estable hasta ~170° (ke=0.4-0.45) ✅
- LQR atrapa péndulo cerca de vertical, sostiene ~1.3s ✅
- Spinning después de LQR failure ❌ (root cause identificado, fix pendiente)

#### Root cause del spinning (PENDIENTE)
- La energía se calcula con `pendPosRaw` (ángulo crudo acumulado).
- Cuando raw >360°, `cos(raw)` oscila erráticamente → `motion_sign` inestable.
- Fix: usar ángulo wrapped para energía cuando `|pendPosRaw| > 360°`.
- Ver `ANALYSIS.md` para detalles completos.

#### Notas
- RAM: 15.0% (49084/327680), Flash: 72.3% (947569/1310720).
- ArduinoOTA funciona: flash WiFi sin USB desde environment `esp32dev_ota`.

---

## [1.28.1] — 2026-06-03
### Firmware: fix wrap ángulo péndulo + pruebas swing-up

#### Problema identificado
- `pendPos` acumulaba vueltas sin wrap (1554° en pruebas). `normalizeAngle(pendPos - 180)` fallaba para la transición LQR.
- Transición swing-up→LQR demasiado permisiva: `balance_threshold=12°`, `SWINGUP_TRANSITION_VEL_DPS=500°`.
- Hard stop del LQR aplicaba PWM_MAX sin proporcionalidad, causando rebote violento.

#### Cambios aplicados

**1. Wrap modular de `pendPos` (crítico)**
- `pendPosRaw` = ángulo crudo (para cálculo de velocidad, sin discontinuidades).
- `pendPos` = wrap a [-180, 180] con `fmod(pendPos + 180, 360) - 180`.
- Velocidad del péndulo calculada con `pendPosRaw` en modos 3, 4 y 5.

**2. LQR: gains + transición más estricta**
- `balance_threshold`: 12°→8° (solo transiciona más cerca de vertical).
- `SWINGUP_TRANSITION_VEL_DPS`: 500→200°/s (solo transiciona con baja velocidad).
- Gains: K1=2.0, K2=22, K3=1.5, K4=9 (incrementados para más autoridad).
- Hard stop proporcional (2 PWM/grado de overshoot).

**3. Swing-up: bombeo excesivo de energía**
- El péndulo gira indefinidamente en vez de oscilar (motor sobrepotenciado).
- `ke_gain=0.5` es demasiado alto para el hardware actual.
- **Pendiente**: reducir `ke_gain` o implementar swing-up con control de amplitud.

#### Datos de pruebas
- Test 1: LQR atrapó péndulo a ~0.4° de vertical, sostuvo ~1.2s, luego perdió.
- Test 2: Péndulo acumuló 3 vueltas (-1080°), swing-up no logró oscilación.
- Logs guardados en `experiments/2026-06-03_swing/data/`.

---

## [1.28.0] — 2026-06-03
### Firmware: ArduinoOTA + LQR hard stop proporcional + MCP docs

#### Cambios aplicados

**1. ArduinoOTA (flasheo por WiFi)**
- `#include <ArduinoOTA.h>`, `ArduinoOTA.begin()` en setup, `ArduinoOTA.handle()` en loop.
- Hostname: `qube-esp32`. Detiene motor al iniciar OTA.
- Nuevo environment `[env:esp32dev_ota]` en `platformio.ini`.

**2. LQR hard stop proporcional**
- Hard stop a ±120° ahora aplica fuerza proporcional al overshoot (2 PWM/grado).
- Orden corregido: hard stop ANTES del `constrain` final.
- Gains reducidos: K2 25→18, K4 10→8 para captura menos agresiva.
- Fallback time reducido: 2000ms→1000ms para detectar fallos más rápido.

**3. MCP server**
- Nueva herramienta `pio_ota_flash(ip)` para flasheo OTA desde MCP.
- Documentación completa en `mcp/README.md`.

#### Notas
- Primer flash con OTA requiere USB; subsecuentes son por WiFi.
- RAM: 15.0% (49076/327680 bytes), Flash: 72.3% (947181/1310720 bytes).

---

## [1.27.0] — 2026-06-03
### Firmware: calidad de código — correcciones, constantes nombradas, watchdog INA219

#### Problema identificado
Revisión de calidad del firmware reveló:
- **C1**: Cambio de modo duplicado entre HTTP y Serial sin histéresis en transiciones LQR↔swing-up.
- **C2**: `Serial.readStringUntil()` con timeout de 1s bloqueaba el lazo de control a 500 Hz.
- **D1**: Variables muertas (`swingPhase`, `exciteStartMs`, `prevError`, `prevErrorPend`) asignadas pero nunca leídas.
- **D2**: `pwmAttachCompat` ignoraba el bool de retorno sin documentar por qué.
- **D3**: INA219 sin watchdog — si el sensor I2C se desconectaba, los valores quedaban stale.
- **M1**: ~20 magic numbers en los bloques PID/LQR/swing-up sin nombre ni documentación.

#### Cambios aplicados

**1. `setMode()` unificado (C1)**
- Punto único de cambio de modo usado por HTTP (`handleCmd`) y Serial (`case 'm'`).
- Histéresis LQR→swing-up con `lqr_inFallback` flag para evitar rebote rápido.

**2. `processSerialCommand()` con buffer acotado (C2)**
- `readStringUntil('\n')` → lectura caracter por caracter con `Serial.read()` y timeout de 50ms.
- Buffer estático de 64 bytes con protección contra overflow.

**3. Código muerto eliminado (D1)**
- `swingPhase`, `exciteStartMs` y `resetSwingUp()` eliminados (asignados, nunca leídos).
- `prevError` y `prevErrorPend` eliminados (PID usa velocidad filtrada, no error previo).

**4. INA219 watchdog (D3)**
- Verificación I2C cada 1000 ms con `Wire.beginTransmission()` + `endTransmission()`.
- Reintento automático de `initIna219()` cada 5000 ms si el sensor falla.

**5. Constantes nombradas (M1)**
- LQR: `LQR_FALLBACK_TIME_MS`, `LQR_FALLBACK_ALPHA_DEG`, `LQR_REARM_ALPHA_DEG`, `LQR_SERVO_LIMIT_DEG`, `LQR_HARDSTOP_DEG`, `LQR_PROTECT_ALPHA_DEG`.
- PID Servo: `PID_ANTIWIND_ERR_DEG`, `PID_ANTIWIND_VEL_DPS`, `DEADBAND_*_DEG`, `STICTION_*`.
- PID Péndulo: `PEND_ANTIWIND_ERR_DEG`, `PEND_ANTIWIND_VEL_DPS`, `PEND_DEADBAND_DEG`.
- Swing-up: `SWINGUP_TRANSITION_VEL_DPS`, `SWINGUP_KICK_DUTY_FRAC`, `SWINGUP_KICK_PERIOD_MS`, `SWINGUP_QUIET_THRESHOLD_RADPS`, `SWINGUP_PROD_DEADZONE`.
- INA219: `INA_WATCHDOG_PERIOD_MS`, `INA_INIT_RETRY_MS`.

#### Notas
- `USE_ENA_PWM = false` confirmado: PWM en IN1/IN2 (ENA no conectado en hardware).
- RAM: 13.7% (44948/327680 bytes), Flash: 67.7% (887429/1310720 bytes).
- Upload exitoso en COM5 (ESP32-D0WD-V3, rev v3.1).

---

## [1.26.1] — 2026-06-03
### GUI: layout de gráficas — subplots más altos, sin overflow

#### Problema identificado
Los 4 subplots del panel de gráficas se veían comprimidos verticalmente con gaps excesivos entre ellos, causando:
- Subplots de 1.31" de alto (en figura 9×8") demasiado estrechos para series temporales legibles.
- `hspace=0.5` (50% de la altura de subplot como gap) — 27% del alto de figura desperdiciado en gaps vacíos.
- Márgenes superior/inferior (0.96/0.06) demasiado estrechos, riesgo de clipping de títulos de subplot.

#### Cambios aplicados

**1. `App._build_charts` (gridspec)**
- `hspace`: 0.5 → 0.28 (reduce gaps entre subplots, +14% altura por subplot).
- `top`: 0.96 → 0.97 (más espacio para títulos del primer subplot).
- `bottom`: 0.06 → 0.07 (más espacio para xlabel del último subplot).
- `left`: 0.08 → 0.09 (alinea ylabel izquierdo con el borde del panel).
- `right`: 0.97 → 0.95 (libra espacio para los ticks derechos de la subplot `twinx()` de Potencia).

#### Cambios de firmware
```cpp
// Sin cambios — solo ajuste de layout del GUI.
```

#### Notas
- Altura efectiva por subplot: 1.31" → 1.49" (+14%).
- `twinx()` de la subplot de Potencia sigue creando su propio eje Y a la derecha (`V bus`) — el ajuste `right=0.95` previene que se salga del área visible.
- Lint: `ruff check`/`ruff format`/`pyright` pasan en `src/qube_ui/`.

---

## [1.26.0] — 2026-06-03
### GUI: paridad completa con endpoints HTTP del firmware

#### Problema identificado
Auditoría cruzada GUI ↔ firmware reveló opciones del firmware sin exponer en `qube_ui.app`:
- Parámetros HTTP sin widget: `cprp` (CPR péndulo), `edp` (dir encoder péndulo), `op` (offset péndulo), `gs`/`kpf`/`kif`/`kdf`/`kpc`/`kic`/`kdc` (gain scheduling), `wifi_ssid`/`wifi_pass`/`wifi_reconnect` (config STA).
- Campos `/state` no parseados: `gain_scheduling`, `gain_mode`.
- Métodos del cliente sin caller en UI: `set_cpr`, `set_encoder_dir` (código muerto).

#### Cambios aplicados

**1. `QubeState` (cliente)**
- Nuevos campos: `gain_scheduling: bool`, `gain_mode: int`.
- `from_json` los reconoce y los asigna a la dataclass.

**2. `ESP32Client` (cliente)**
- Nuevos métodos: `set_pendulum_cpr`, `set_pendulum_encoder_dir`, `set_pendulum_offset`, `set_gain_scheduling`, `set_servo_pid_fine`, `set_servo_pid_coarse`, `set_wifi_ssid`, `set_wifi_password`, `wifi_reconnect`.
- Validación local de SSID (1-32 chars) y password (>= 8 chars) para evitar round-trips inútiles.

**3. `App._build_control_panel` (GUI)**
- Nueva sección **CALIBRACIÓN (CPR / DIR)**: campos CPR servo/péndulo + radiobuttons `+-1` para dirección encoder servo/péndulo + botón "Aplicar Calibración".
- Nueva sección **GAIN SCHEDULING (PID SERVO)**: checkbox "Activar dual-mode" + sub-bloques para ganancias fino (`kpf`/`kif`/`kdf`) y grueso (`kpc`/`kic`/`kdc`) + botón "Aplicar Gains Fino/Grue.".
- Nueva sección **WIFI STA**: campos SSID (texto) y password (enmascarado) + botones "Aplicar WiFi" y "Reconectar".
- Sección **OFFSET** ampliada con fila independiente para offset del péndulo (`op`) junto a la fila del servo.
- Sección **ESTADO ACTUAL** ampliada con etiquetas de telemetría `GainSch: {on|off} ({fino|grueso})` y `CPR servo: N`.

**4. Handlers de envío**
- Nuevos: `_send_pendulum_offset`, `_send_encoder_dir`, `_send_pendulum_encoder_dir`, `_send_calibration`, `_send_gain_scheduling`, `_send_gain_gains`, `_send_wifi`, `_send_wifi_reconnect`.
- Validación de entrada + `messagebox.showerror` en valores no numéricos o credenciales inválidas.

#### Cambios de firmware
```cpp
// Sin cambios — este commit solo agrega soporte GUI para endpoints existentes.
// Endpoints cubiertos ahora en GUI:
//   /cmd?cprp, edp, op, gs, kpf, kif, kdf, kpc, kic, kdc, wifi_ssid, wifi_pass, wifi_reconnect
```

#### Notas
- Los radiobuttons de dirección de encoder aplican cambios inmediatamente al seleccionar (no requieren "Aplicar"); consistente con el patrón de cambio de modo.
- "Aplicar Calibración" envía CPR y dirección en una sola acción (4 comandos consecutivos al firmware).
- "Aplicar WiFi" no reconecta automáticamente — usuario debe pulsar "Reconectar" para activar STA, evitando desconexiones accidentales.
- Lint: `ruff check`/`ruff format`/`pyright` pasan en `src/qube_ui/`.


---

## [1.25.0] — 2026-06-01
### Swing-up funcional + LQR con fallback automático + 500Hz

#### Problema identificado
- El péndulo no lograba estabilizarse con swing-up (modo 5) + LQR (modo 4).
- **Bug 1:** Signo invertido en la ley de energía del swing-up — el motor peleaba contra el péndulo.
- **Bug 2:** Kick unidireccional — el péndulo se atascaba colgado hacia abajo.
- **Bug 3:** LQR usaba ángulo sin normalizar — la protección siempre mataba el PWM.
- **Bug 4:** Sin fallback — cuando el LQR fallaba, el sistema se quedaba en modo 4 muerto.
- **Bug 5:** Servo desbordaba a ±175°+ durante LQR causando crash mecánico.

#### Cambios aplicados

**1. Ley de energía corregida (modo 5)**
- Antes: `E_err = E - Er` → signo invertido, torque contra el péndulo.
- Ahora: `energy_sign = (Er > E) ? 1.0f : -1.0f` → ley Quanser/Åström-Furuta correcta.

**2. Kick alternante para iniciar oscilación (modo 5)**
- Antes: PWM constante `MOTOR_DIR * PWM_MAX * 0.8` siempre en una dirección.
- Ahora: Alterna dirección cada 250ms (~periodo natural/2) para construir resonancia.
- Threshold ampliado: `abs(alpha_dot) < 0.15f` (era 0.1).

**3. Función `normalizeAngle()` + LQR normalizado (modo 4)**
- Nueva función que normaliza ángulos a [-180, 180].
- `alpha = normalizeAngle(pendPos - 180.0f)` → 0=arriba, ±180=abajo.
- Velocidades calculadas con ángulo crudo (evita errores en wrap-around).

**4. Fallback automático LQR → Swing-up**
- Si `|alpha| > 90°` por >2 segundos → vuelve a modo 5 (swing-up).
- Permite ciclar swing-up → LQR → fallback → swing-up hasta estabilizar.

**5. Protección LQR ampliada y hard stop de servo**
- Protección: `|alpha| > 140°` → PWM=0 (era 150°).
- Hard stop: `|pos| > 120°` → fuerza motor de vuelta al centro.

**6. Filtro de velocidad más rápido**
- `VEL_ALPHA_PEND = 0.30f` (era 0.15) → reduce retardo de 33ms a 17ms.

**7. Frecuencia de control: 200 Hz → 500 Hz**
- `CONTROL_PERIOD_US = 2000` (era 5000) → latencia 2ms vs 5ms.

**8. Balance threshold reducido**
- `balance_threshold = 12°` (era 20°) → transición más cercana a vertical.

**9. Velocidad gate en transición**
- Solo permite transición si `|alpha_dot| < 500°/s` (evita transiciones prematuras).

#### Cambios de firmware
```cpp
// NUEVA: normalización de ángulo
float normalizeAngle(float deg) {
  deg = fmodf(deg, 360.0f);
  if (deg > 180.0f) deg -= 360.0f;
  else if (deg < -180.0f) deg += 360.0f;
  return deg;
}

// Swing-up: energía corregida + kick alternante
const float energy_sign = (Er > E) ? 1.0f : -1.0f;
if (abs(alpha_dot) < 0.15f) {
    if (((millis() / 250) % 2) == 0)
        pwm = MOTOR_DIR * (int)(PWM_MAX * 0.7f);
    else
        pwm = -MOTOR_DIR * (int)(PWM_MAX * 0.7f);
} else {
    float u = ke_gain * energy_sign * motion_sign;
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}

// LQR: ángulo normalizado + fallback + hard stop
const float alpha = normalizeAngle(pendPos - 180.0f);
// ... (fallback si |alpha|>90 por >2s)
// ... (hard stop si |pos|>120)

// Control: 500 Hz
const unsigned long CONTROL_PERIOD_US = 2000;
```

#### Parámetros LQR actuales
- K1=1.5 (posición servo), K2=25 (ángulo péndulo), K3=1.0 (vel servo), K4=10 (vel péndulo)
- VEL_ALPHA_PEND=0.30, balance_threshold=12°, velocity gate=500°/s

#### Notas
- Resultado: LQR atrapa péndulo a 0.2° de la vertical pero no sostiene >0.5s.
- Limitación física identificada: motor L298N demasiado lento. BTS7960 recomendado como upgrade.
- Datos de test en `experiments/2026-06-01_swing/`
- Log completo de tuning en `experiments/2026-06-01_swing/TUNING_LOG.md`


## [1.24.1] — 2026-06-01

### Fix LQR: ángulo péndulo sin normalizar + protección mata motor

#### Problema identificado
- El swing-up (modo 5) funcionaba y el péndulo llegaba a ~0° (vertical), pero el LQR (modo 4) nunca lograba estabilizarlo.
- **100% de los 6 ciclos de swing-up fallaron**: el péndulo llegaba a 160-178° y el LQR apagaba el motor inmediatamente.
- **Causa raíz:** El LQR usaba `pendPos` crudo (que puede ser -521°, 512°, etc. por acumulación del encoder) directamente como `alpha`.
- La protección `abs(alpha) > 150` se activaba siempre porque 161° > 150°, aunque 161° es casi la vertical (180°).
- Segunda causa: la condición de transición swing-up→LQR usaba `fmodf(abs(pendPos), 360) - 180` que no normalizaba correctamente.

#### Cambios aplicados

**1. Función `normalizeAngle()`**
- Normaliza cualquier ángulo a [-180, 180].
- Usada en LQR y en la condición de transición del swing-up.

**2. LQR con ángulo normalizado (modo 4)**
- `alpha = normalizeAngle(pendPos - 180.0)` → 0=arriba, ±180=abajo.
- Velocidades calculadas con ángulo crudo (evita errores en wrap-around ±180°).
- Protección `abs(alpha) > 150` ahora funciona correctamente: solo apaga motor cuando el péndulo está cerca del fondo.

**3. Transición swing-up→LQR simplificada**
- Antes: `fmodf(abs(pendPos), 360) - 180` (incorrecto para ángulos negativos grandes).
- Ahora: `dist_from_up = abs(normalizeAngle(pendPos - 180.0))`.

#### Cambios de firmware
```cpp
// NUEVA: normalización de ángulo
float normalizeAngle(float deg) {
  deg = fmodf(deg, 360.0f);
  if (deg > 180.0f) deg -= 360.0f;
  else if (deg < -180.0f) deg += 360.0f;
  return deg;
}

// LQR: ANTES (sin normalizar, protección siempre activa)
const float alpha = pendPos;  // -521° → abs > 150 → PWM=0

// LQR: DESPUÉS (normalizado, 0=arriba)
const float alpha_raw = pendPos;
const float alpha = normalizeAngle(pendPos - 180.0f);  // 0=arriba
// Velocidades calculadas de alpha_raw (sin wrap-around)
```

#### Notas
- Los gains LQR (K1=1, K2=25, K3=0.5, K4=3) pueden necesitar ajuste fino ahora que el LQR efectivamente controla.
- Si el péndulo oscila alrededor de la vertical sin estabilizar, subir K2 y K4.
- Subir firmware: `pio run --target upload`


## [1.24.0] — 2026-06-01

### PCNT hardware encoder + CPR medido experimentalmente

#### Problema identificado
- El encoder del servo usaba polling en `loop()` (`USE_ENCODER_POLLING`), que perdia transiciones porque el loop tambien maneja WiFi, web server, INA219 y serial.
- Las ISRs por software (`isrEncoderA/B`) usaban `digitalRead()` dentro de la interrupcion (~5us cada llamada), demasiado lento para seguir el ritmo de un encoder incremental a velocidad real.
- El encoder del pendulo no tenia ISRs configuradas, solo polling.
- El CPR de ambos encoders estaba configurado en 2048 por defecto sin verificacion experimental.
- Medir el CPR manualmente era impreciso: el usuario debia rotar el eje y contar vueltas, introduciendo error humano significativo.

#### Cambios aplicados

**1. PCNT (Pulse Counter) hardware para ambos encoders**
- Reemplaza ISRs y polling con el periferico PCNT del ESP32, que decodifica cuadratura X4 en hardware sin intervencion de CPU.
- PCNT_UNIT_0: encoder servo (GPIO34/GPIO35)
- PCNT_UNIT_1: encoder pendulo (GPIO32/GPIO33)
- Cada canal configura: pulse en un pin, control en el otro, con modos REVERSE/KEEP para direccion.
- Eliminadas: `isrEncoderA`, `isrEncoderB`, `isrPendulumA`, `isrPendulumB`, `updateEncoderPolling`, `updatePendulumPolling`, `resetEncoderStateTracker`, `resetPendulumStateTracker`.
- Eliminadas variables: `encoderCount`, `pendulumCount`, `encoderLastState`, `pendulumLastState`, `USE_ENCODER_INTERRUPTS`, `USE_ENCODER_POLLING`.

**2. ISRs para encoder pendulo (agregadas, ahora obsoletas)**
- Se agregaron `isrPendulumA`/`isrPendulumB` antes de migrar a PCNT. Quedan como referencia pero no se usan.

**3. Reset PCNT via HTTP y serial**
- Comando `r` ahora llama `resetPcnt()` en vez de `encoderCount = 0`.
- Comando `zp` (HTTP) solo resetea offset, no el contador PCNT.

**4. CPR verificado experimentalmente**
- Encoder pendulo: CPR = 2048 confirmado (1024 counts = 180.000 exacto).
- Encoder servo: CPR = 2048 verificado via PID (setPosition a 45/-45/0 grados funciona correctamente).
- Ambos encoders son el mismo modelo Premotec 990412016913.

**5. Scripts de medicion de CPR** (`experiments/2026-06-01_cpr_measurement/`)
- `diagnose_encoder.py`: lee estados enc_a/enc_b en tiempo real para diagnosticar hardware.
- `sweep_cpr.py`: barrido no-interactivo con soporte para encoder servo o pendulum.
- `motor_sweep_cpr.py`: mueve el motor con PWM y graba counts.
- `servo_sweep_cpr.py`: barrido servo considerando rango mecanico +/-90 grados.
- `dual_encoder_sweep.py`: compara servo vs pendulum simultaneamente.

#### Cambios de firmware
```cpp
// ANTES: polling en loop (perdia transiciones)
void loop() {
  updateEncoderPolling();    // ~5us por digitalRead x2
  updatePendulumPolling();   // same
  ...
}

// DESPUES: PCNT en hardware (cero perdida)
void loop() {
  ws.cleanupClients();      // PCNT cuenta en background
  ...
}

// Init PCNT (X4 cuadratura)
pcnt_config_t ch0 = {
    .pulse_gpio_num = pinA,
    .ctrl_gpio_num = pinB,
    .lctrl_mode = PCNT_MODE_KEEP,
    .hctrl_mode = PCNT_MODE_REVERSE,
    .pos_mode = PCNT_COUNT_INC,
    .neg_mode = PCNT_COUNT_DEC,
    .counter_h_lim = 32767,
    .counter_l_lim = -32768,
    .unit = PCNT_UNIT_0,
    .channel = PCNT_CHANNEL_0,
};
```

#### Notas
- El PCNT de 16 bits permite ~4 vueltas completas antes de overflow (con CPR=2048). El loop a 200Hz lee el counter periodicamente.
- El ratio de la caja de engranajes es ~10:1 (medido via comparacion dual encoder).
- Los scripts de medicion corrigen el bug de emojis Unicode en Windows (cp1252).

## [1.23.1] — 2026-06-01

### Fix swing-up (modo 5): signo invertido de energía y kick unidireccional

#### Problema identificado
- El péndulo no subía al activar swing-up (modo 5): se quedaba estático colgado hacia abajo.
- El motor generaba mucha fricción porque empujaba en una sola dirección sin alternar.
- **Causa raíz 1:** La ley de bombeo de energía usaba `E - Er` en vez de `Er - E`, invirtiendo el signo del torque. El motor peleaba contra el péndulo en vez de bombearle energía.
- **Causa raíz 2:** El kick inicial (`abs(alpha_dot) < 0.1`) siempre aplicaba `MOTOR_DIR * PWM_MAX * 0.8` (= -80), dirección constante. Esto atascaba el péndulo en vez de iniciar oscilación.

#### Cambios aplicados

**1. Signo correcto de la ley de energía (Quanser/Åström-Furuta)**
- Antes: `u = ke_gain * (E - Er) * sign_val * 80.0` → signo invertido.
- Ahora: `u = ke_gain * sign(Er - E) * sign(α̇ · cos α)` → bombea cuando E < Er, reduce cuando E > Er.
- Eliminada la constrain a [-1, 1] y la multiplicación por 80.0 innecesaria.

**2. Kick alternante para iniciar oscilación**
- Antes: PWM constante en una dirección → péndulo se atasca.
- Ahora: alterna dirección cada 250ms (~periodo natural del péndulo / 2) para construir amplitud por resonancia.
- Se activa cuando `abs(alpha_dot) < 0.15` (threshold ampliado de 0.1 a 0.15).

#### Cambios de firmware
```cpp
// ANTES (buggeado):
const float E_err = E - Er;  // signo invertido
if (abs(alpha_dot) < 0.1f) {
    pwm = MOTOR_DIR * PWM_MAX * 0.8f;  // siempre -80
} else {
    float u = ke_gain * E_err * sign_val * 80.0f;
    u = constrain(u, -1.0f, 1.0f);
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}

// DESPUÉS (corregido):
const float energy_sign = (Er > E) ? 1.0f : -1.0f;
if (abs(alpha_dot) < 0.15f) {
    // Kick alternante cada 250ms
    if (((millis() / 250) % 2) == 0)
        pwm = MOTOR_DIR * (int)(PWM_MAX * 0.7f);
    else
        pwm = -MOTOR_DIR * (int)(PWM_MAX * 0.7f);
} else {
    float u = ke_gain * energy_sign * motion_sign;
    pwm = (int)(MOTOR_DIR * u * PWM_MAX);
}
```

#### Notas
- Parámetro ajustable `ke_gain` (default 0.5) controla la intensidad del bombeo. Subir si el motor no tiene fuerza para construir oscilación.
- `balance_threshold` (default 20°) controla la transición automática a LQR (modo 4).
- Subir firmware: `pio run --target upload`

## [1.23.0] — 2026-06-01

### Gain Scheduling dual-mode para PID servo (Modo 2)

#### Problema identificado
- El PID del modo 2 usaba gains fijos (Kp=3.0, Ki=0.5, Kd=0.15) para cualquier magnitud de error.
- Errores pequeños (<10°) generaban movimientos demasiado agresivos que causaban overshoot y pérdida de posición por backlash mecánico.
- Errores grandes (>10°) no tenían suficiente ganancia para responder rápidamente.
- El escalonamiento de PWM existente limitaba la potencia pero no la dinámica del controlador.

#### Cambios aplicados

**1. Gain Scheduling dual-mode (modo 2)**
- Dos juegos de gains independientes: **modo fino** (|error| ≤ 10°) y **modo grueso** (|error| > 10°).
- Modo fino: Kp=2.0, Ki=0.8, Kd=0.2 — movimientos suaves, más amortiguación, PWM acotado (max 50).
- Modo grueso: Kp=4.0, Ki=0.2, Kd=0.1 — respuesta rápida, PWM libre (max 100).
- Histérisis de ±2° sobre el umbral (10°) para evitar chattering entre modos.
- Dead band adaptiva: 0.5° en modo fino, 1.0° en modo grueso.
- Toggle `useGainScheduling` para activar/desactivar el dual-mode (default: off, usa PID clásico).

**2. Nuevos parámetros HTTP**
- `gs=0|1` — activar/desactivar gain scheduling.
- `kpf`, `kif`, `kdf` — gains del modo fino (Kp, Ki, Kd).
- `kpc`, `kic`, `kdc` — gains del modo grueso (Kp, Ki, Kd).

**3. Nuevos comandos seriales**
- `g0` / `g1` — desactivar/activar gain scheduling.
- `gf<val>`, `gi<val>`, `gd<val>` — ajustar gains del modo fino.
- `GC<val>`, `GI<val>`, `Gd<val>` — ajustar gains del modo grueso.

**4. Telemetría extendida**
- Campo `gain_scheduling` (true/false) en JSON de `/state`.
- Campo `gain_mode` (0=fino, 1=grueso) en JSON de `/state`.

**5. Ayuda actualizada**
- Línea de ayuda serial incluye comandos de gain scheduling.
- Página HTML de `/` incluye endpoints de gain scheduling.

#### Notas
- **Backward compatible**: `useGainScheduling` default es `false`, mantiene el PID clásico existente.
- Activar con `GET /cmd?gs=1` o `g1` por serial.
- Los gains clásicos (Kp/Ki/Kd) siguen funcionando cuando el gain scheduling está desactivado.
- Los parámetros de gain scheduling se resetean al cambiar de esquema (fine ↔ coarse).

---
## [1.22.0] — 2026-06-01

### README completo: diagrama eléctrico actualizado con Schmitt Trigger + filtro RC

#### Problema identificado
- El README no reflejaba el circuito de acondicionamiento de señal real implementado en la protoboard.
- El diagrama eléctrico mostraba solo Schmitt Trigger sin filtro RC, aunque el hardware ya tenía resistencias 10 kΩ y capacitores 10 nF a GND en cada canal.
- Referencia interna a `gui/esp32_client.py` apuntaba a un archivo inexistente (migrado a `src/qube_ui/client.py`).

#### Cambios aplicados

**1. Diagrama eléctrico actualizado**
- Circuito de acondicionamiento: Schmitt Trigger CD40106BE → filtro RC (10 kΩ serie + 10 nF a GND) → GPIO ESP32.
- Diagrama de bloques general incluye Schmitt + RC en cada canal encoder.
- Topología de potencia incluye GND del CD40106BE.

**2. Sección de acondicionamiento de señal reescrita**
- Circuito completo con doble inversión + filtro RC documentado con diagrama ASCII.
- Cálculo de filtro RC: τ = 100 µs, f_c ≈ 1.59 kHz.
- Tabla comparativa de 3 topologías: pull-up solamente, pull-up + Schmitt, pull-up + Schmitt + RC.
- BOM actualizado: resistores 10 kΩ (×4) + capacitores 10 nF (×4).

**3. Modos de operación actualizados**
- Modo m5 (swing-up) incluido en todas las tablas de modos.
- Tabla de parámetros PID actualizada con columna LQR.
- Endpoints HTTP completos con todos los parámetros nuevos (swing-up, WiFi, LQR).

**4. Estructura del proyecto reflejada**
- Rutas actualizadas: `src/firmware/`, `src/qube_ui/`, `src/qube_analysis/`.
- Referencia a `gui/esp32_client.py` corregida a `src/qube_ui/client.py`.
- Sección "Documentación Adicional" con tabla de navegación a docs/.

**5. Roadmap actualizado**
- Ítems completados: swing-up, WiFi STA no-bloqueante, GUI con LQR/swing-up, filtro RC.
- Nuevo ítem: PCB Rev2.0 con acondicionamiento integrado.

#### Notas
- Solo cambios en documentación (README.md). No se modifica firmware ni código Python.
- Todos los enlaces internos verificados contra archivos existentes en el repositorio.

## [1.21.0] — 2026-05-29

### Swing-up (Modo 5), WiFi STA no-bloqueante y credenciales gitignored

#### Problema identificado
- No existía modo de swing-up para levantar el péndulo desde la posición colgante hasta la vertical invertida.
- La conexión WiFi STA bloqueaba el arranque del ESP32 durante 15 segundos si la red no estaba disponible.
- Las credenciales WiFi estaban hardcodeadas o requerían NVS, sin opción de configuración desde GUI.
- El AP solo era accesible en 192.168.4.1,requiriendo desconectarse de la red local.

#### Cambios aplicados

**1. Modo 5: Swing-up por energía (Quanser)**
- Control basado en energía: `E = 0.5*J*α'² + mgl*(1-cos(α))`, `Er = 2*mgl`.
- Dirección de torque: `sign(α' * cos(α))` para agregar energía al péndulo.
- Kick constante cuando el péndulo está quieto (`|α'| < 0.1`) para iniciarlo.
- Transición automática a LQR (modo 4) cuando `|α|` está cerca de 180° (vertical arriba).
- Corregido bug: la transición a LQR solo se activa cerca de la vertical ARRIBA (180°), no abajo (0°).
- Ganancia ajustable vía HTTP: `/cmd?ke=0.5&bt=20` (ke = ganancia energía, bt = umbral transición LQR).

**2. WiFi STA no-bloqueante**
- `connectStaIfConfigured()` ya no usa `while()` con timeout — `WiFi.begin()` conecta en background.
- El AP `QUBE-ESP32` está disponible inmediatamente al arrancar, sin esperar al STA.

**3. Credenciales WiFi gitignored (`credentials.h`)**
- Nuevo archivo `credentials.h` con `DEFAULT_STA_SSID` y `DEFAULT_STA_PASS`.
- Agregado a `.gitignore` — nunca se sube al repositorio.
- `loadWifiCredentials()` usa credenciales de `credentials.h` cuando NVS está vacío.
- El usuario edita `credentials.h` con sus datos reales y compila.

**4. HTTP endpoints para WiFi**
- `/cmd?wifi_ssid=Red&wifi_pass=Clave` — guardar credenciales en NVS.
- `/cmd?wifi_reconnect=1` — reconectar WiFi sin reiniciar.

**5. GUI actualizada (`src/qube_ui/app.py`)**
- Nuevo radio button "Swing-up" en modos de operación.
- Sección "SWING-UP" con parámetros `ke` (gain) y `threshold` (umbral LQR).
- Método `_send_swing_up()` para enviar parámetros.

**6. Cliente actualizado (`src/qube_ui/client.py`)**
- Nuevo método `set_swing_up_params(ke, balance_threshold)`.

**7. MCP server actualizado (`mcp/esp32_qube_server.py`)**
- `qube_set_mode()` actualizado: modos 0-5 documentados.
- Nueva herramienta `qube_set_swing_up(ke, balance_threshold)`.
- Nuevas herramientas `qube_set_wifi(ssid, password)` y `qube_wifi_reconnect()`.

#### Cambios de firmware
```cpp
// Swing-up (modo 5)
float ke_gain = 0.5f;           // Ganancia energía
float balance_threshold = 20.0f; // Umbral transición LQR
int swingPhase = 0;             // 0=excitacion, 1=bombeo
unsigned long exciteStartMs = 0;

// WiFi credentials (gitignored)
#include "credentials.h"
#define DEFAULT_STA_SSID "TuRed"
#define DEFAULT_STA_PASS "TuClave"
```

#### Notas
- Para probar swing-up: conectar péndulo abajo, ejecutar `zp=1` (zero péndulo), luego activar modo 5.
- El péndulo debe estar colgado hacia abajo (0°) antes de activar swing-up.
- RAM: 13.6% (44,684 / 327,680 bytes), Flash: 62.5% (818,545 / 1,310,720 bytes).

## [1.20.0] — 2026-05-29

### Encoder de Péndulo, Modo PID Péndulo y LQR Péndulo Invertido

#### Problema identificado
- El firmware solo soportaba el encoder del servo (GPIO34/35), sin lectura del encoder del péndulo (GPIO32/33).
- No existía modo de control para posicionar el péndulo ni para estabilizarlo en posición vertical (invertido).
- La GUI no mostraba datos del péndulo ni permitía controlar los nuevos modos.

#### Cambios aplicados

**1. Encoder del péndulo (GPIO32/33)**
- Agregadas variables `pendulumCount`, `pendCountsPerRev`, `pendulumDir` para el segundo encoder.
- Implementada decodificación cuadratura X4 por polling (`updatePendulumPolling()`) idéntica al encoder servo.
- Funciones: `getPendulumPositionDeg()`, `zeroPendulumHere()`, `resetPendulumPid()`.

**2. Modo 3: PID Posición Péndulo**
- Control PID del motor basado en el ángulo del péndulo (no del servo).
- Ganancias por defecto: `Kp_pend=15.0`, `Ki_pend=0.5`, `Kd_pend=2.0`.
- Setpoint vía HTTP: `/cmd?m=3&sp=0` (sp = setpoint péndulo).
- Anti-windup y deadband independientes del PID servo.

**3. Modo 4: LQR Péndulo Invertido**
- Control en espacio de estados: `u = -(K1*θ + K2*α + K3*θ' + K4*α')`.
- Estado: `[theta_servo, alpha_pendulo, vel_servo, vel_pendulo]`.
- Ganancias por defecto: `K1=1.0`, `K2=25.0`, `K3=0.5`, `K4=3.0`.
- Protección: si `|α| > 150°` (péndulo caído), PWM = 0 para evitar daño.
- Ganancias ajustables vía HTTP: `/cmd?lqr1=1&lqr2=25&lqr3=0.5&lqr4=3`.

**4. Estado JSON expandido (`/state`)**
- Nuevos campos: `pend_count`, `pend_raw_position_deg`, `pend_position_deg`, `pend_offset_deg`, `pend_setpoint_deg`, `pend_error_deg`.

**5. Nuevos comandos HTTP**
- `sp` — setpoint péndulo (modo 3).
- `zp` — zero encoder péndulo.
- `op` — offset péndulo.
- `edp` — dirección encoder péndulo (+1/-1).
- `cprp` — counts per revolution encoder péndulo.
- `kpp`, `kip`, `kdp` — ganancias PID péndulo.
- `lqr1`, `lqr2`, `lqr3`, `lqr4` — ganancias LQR.

**6. Serial: comandos actualizados**
- `m0..m4` — modos extendidos (antes `m0..m2`).
- `sp<deg>`, `zp`, `op<deg>`, `edp<1|-1>`, `cprp<val>` — péndulo.
- `kpp<val>`, `kip<val>`, `kdp<val>` — PID péndulo.

**7. GUI (`src/qube_ui/app.py`) actualizada**
- 4 subplots: Servo, Péndulo, PWM, Potencia.
- Panel de control: setpoint péndulo, PID péndulo, LQR ganancias.
- Botón "Zero Péndulo" en acciones.
- Estado muestra servo y péndulo simultáneamente.
- Modos de operación: STOP, PWM Manual, PID Servo, PID Péndulo, LQR Invertido.

**8. Cliente (`src/qube_ui/client.py`, `gui/esp32_client.py`) actualizado**
- `QubeState` incluye campos de péndulo.
- Nuevos métodos: `set_pendulum_setpoint()`, `set_pendulum_pid()`, `zero_pendulum()`, `set_lqr_gains()`.

**9. MCP server (`mcp/esp32_qube_server.py`) corregido**
- `DATA_DIR` corregido: apuntaba a `./data/` (no existe) → `./experiments/`.
- Herramientas CSV (`qube_list_experiments`, `qube_read_csv`, `qube_analyze_csv`) ahora buscan recursivamente en `experiments/*/data/`.

#### Cambios de firmware
```cpp
// Encoder péndulo (GPIO32/33)
static const int PIN_PEND_A = 32;
static const int PIN_PEND_B = 33;
volatile long pendulumCount = 0;

// PID Péndulo (modo 3)
float Kp_pend = 15.0f;
float Ki_pend = 0.5f;
float Kd_pend = 2.0f;

// LQR (modo 4)
float lqr_K1 = 1.0f;   // θ servo
float lqr_K2 = 25.0f;  // α péndulo
float lqr_K3 = 0.5f;   // θ' velocidad servo
float lqr_K4 = 3.0f;   // α' velocidad péndulo
```

#### Notas
- RAM: 13.6% (44,672 / 327,680 bytes), Flash: 62.0% (812,193 / 1,310,720 bytes).
- Para modo LQR, el péndulo debe estar cerca de la vertical antes de activar (swing-up manual o desde modo 3).
- Los 36 tests del proyecto pasan correctamente.

## [1.19.0] — 2026-05-28

### Migración de Adafruit_INA219 a INA219_WE + fix de compilación PlatformIO

#### Problema identificado
- `Adafruit_INA219` (v1.2.3) no compila con ESP32 Arduino Core 3.x: `'Serial' was not declared in this scope` en Adafruit BusIO.
- La librería lleva 3 años sin actualización y causa core panic + boot loop en ESP32 Core 3.x ([adafruit/Adafruit_INA219#58](https://github.com/adafruit/Adafruit_INA219/issues/58)).
- Flags `ARDUINO_USB_MODE=1` + `ARDUINO_USB_CDC_ON_BOOT=1` causan que `Serial` no se declare correctamente con PlatformIO + `src_dir`.

#### Cambios aplicados

**1. Librería INA219 reemplazada**
- `adafruit/Adafruit INA219 @ ^1.2.0` → `wollewald/INA219_WE @ ^1.4.1`
- INA219_WE está activamente mantenido (v1.4.1, dic 2025) y compatible con ESP32 Core 2.x y 3.x.

**2. Plataforma fijada a ESP32 Core 2.x**
- `platform = espressif32` (v7.0.1, Core 3.x) → `platform = espressif32@5.4.0` (Core 2.x, framework 3.20006).
- Core 2.x declara `Serial` correctamente sin necesidad de `USB.h`.

**3. Flags USB eliminados**
- Eliminados `-DARDUINO_USB_MODE=1` y `-DARDUINO_USB_CDC_ON_BOOT=1` de `build_flags`.
- Con Core 2.x + sin flags USB, `Serial` = UART0 (GPIO1/3) — funciona para flashing y monitor serial.

**4. API INA219_WE actualizada en firmware**
- `Adafruit_INA219 ina219(addr)` → `INA219_WE ina219(&Wire, addr)`
- `ina219.begin()` → `ina219.init()`
- `ina219.setCalibration_32V_2A()` → eliminado (INA219_WE calibra automáticamente en `init()`)
- `ina219.getPower_mW()` → `ina219.getBusPower()`
- Agregado `ina219.setMeasureMode(INA219_CONTINUOUS)` después de `init()`

**5. Fallback class actualizada**
- Clase stub `Adafruit_INA219` reemplazada por `INA219_WE` con API compatible.

**6. `#include <Arduino.h>` agregado**
- Necesario para que `Serial` se declare en el scope global con PlatformIO + `src_dir`.

**7. platformio.ini corregido**
- Agregado `[platformio] src_dir = esp32_qube_l298n`
- Corregido `check_tool = clang-tidy` → `clangtidy`

#### Cambios de firmware
```cpp
// platformio.ini
platform = espressif32@5.4.0          // antes: espressif32 (sin versión)
lib_deps = wollewald/INA219_WE @ ^1.4.1  // antes: adafruit/Adafruit INA219
build_flags = -DCORE_DEBUG_LEVEL=3    // eliminados ARDUINO_USB_MODE y CDC_ON_BOOT

// esp32_qube_l298n.ino
#include <Arduino.h>                   // agregado al inicio
INA219_WE ina219(&Wire, 0x40);        // antes: Adafruit_INA219 ina219(0x40)
ina219.init();                        // antes: ina219.begin()
ina219.setMeasureMode(INA219_CONTINUOUS); // nuevo
powermW = ina219.getBusPower();       // antes: ina219.getPower_mW()
```

#### Notas
- **UART0** (GPIO1/3) se usa para Serial (USB CDC deshabilitado). Para monitoreo, usar `pio device monitor`.
- RAM: 13.6% (44,584 / 327,680 bytes), Flash: 61.6% (807,609 / 1,310,720 bytes).
- Referencia: [INA219_WE GitHub](https://github.com/wollewald/INA219_WE), [Adafruit_INA219 Issue #58](https://github.com/adafruit/Adafruit_INA219/issues/58)

---

## [1.18.0] — 2026-05-27

### Reescritura y ampliación del README.md

#### Cambios aplicados

**1. Instructivo de Uso completo (nuevo)**
- Guía paso a paso de 11 secciones: prerrequisitos, clonar, LM2596, firmware, WiFi, modos, GUI, HTTP, flujo de trabajo, tests, troubleshooting.
- Incluye diagrama de flujo visual del proceso completo (preparar → ajustar → flashear → verificar → calibrar → monitorear).
- Tabla de troubleshooting con 7 síntomas, causas y soluciones.

**2. Diagramas de arquitectura reescritos**
- Diagrama de conexión general con INA219 en serie (bloques separados: fuente → INA219 → L298N → motor).
- Diagrama detallado de conexión del INA219 (VIN+/VIN− en serie, I2C, alimentación 3.3V).
- Diagrama de flujo de datos con FreeRTOS tasks (control 200 Hz, INA219 100 Hz, telemetry 20 Hz, WiFi event-driven).

**3. Sección Schmitt Trigger CD40106BE documentada**
- Investigación completa: CD40106BE hex inversor Schmitt Trigger, pinout DIP-14, umbrales VT+/VT−, histéresis.
- Circuito de acondicionamiento con doble inversión (INV1+INV2 → GPIO34, INV3+INV4 → GPIO35).
- Protección de entrada: R_series 2.2kΩ + R_pd 10kΩ + C 100nF.
- Alimentación a 3.3V con bypass 100nF (explicación de por qué se necesita).
- Uso de los 6 inversores: 4 para encoders + 2 reservados.
- Nota sobre voltaje de salida: pin 3V3 del ESP32 entrega ~3.5V, seguro para GPIO (máx 3.6V).
- Comparativa: divisor 10kΩ/10kΩ (1.75V, marginal) vs Schmitt trigger (3.5V, limpio).
- Costo total: ~$0.73 USD.
- Estado: implementado en protoboard para encoders servo (GPIO34/35).

**4. Circuito de encoders actualizado**
- Se documentó el circuito actual real: divisor resistivo 10kΩ/10kΩ (3.5V → 1.75V) + Schmitt trigger CD40106BE.
- Se aclaró que 1.75V es marginal para el ESP32 y el Schmitt regenera a 3.5V.

**5. Estructura del README reorganizada**
- 14 secciones numeradas en tabla de contenidos.
- Hardware requerido con tabla de componentes incluyendo CD40106BE.
- Pinout completo con tabla pin por pin, cableado ENA, configuración ESP32.
- Control PID, firmware (FreeRTOS tasks, comandos), calibración, resultados.
- Roadmap actualizado con Schmitt trigger como completado.

#### Notas
- No se modificó el firmware (`esp32_qube_l298n.ino`) en esta entrada.
- Todos los cambios son de documentación.
- Referencia: `docs/research/ai_research/CD40106BE_INVESTIGATION.md`

---

## [1.17.3] — 2026-05-13

### Diagnóstico y autodetección de INA219 por I2C

#### Problema identificado
- En arranque aparecía `INA219: NO DETECTADO` aun con hardware aparentemente conectado.
- Causa probable: dirección I2C distinta a la esperada o problema de bus no visible en logs.

#### Cambios aplicados

**1. Escaneo I2C en arranque y bajo demanda**
- Se agrega `scanI2CBus()` para listar dispositivos detectados en direcciones `0x01..0x7E`.
- Se ejecuta automáticamente en `setup()` y también por comando serial `n`.

**2. Inicialización INA219 con direcciones candidatas**
- Se agrega `initIna219()` que prueba `0x40`, `0x41`, `0x44`, `0x45` y aplica calibración al detectar el sensor.
- Se registra dirección activa en `inaAddr` y se imprime en serial (`INA219: OK @ 0x..`).

**3. Mejoras de diagnóstico por serial**
- `printHelp()` ahora incluye `n(ina scan)` para relanzar detección sin reiniciar.
- El mensaje final de arranque muestra estado y dirección detectada cuando corresponde.

#### Cambios de firmware
```cpp
void scanI2CBus() { ... }                // Escaneo I2C para diagnóstico
bool initIna219() { ... }                // Detección INA219 en varias direcciones
case 'n': { scanI2CBus(); ... }          // Comando serial para reintentar detección
```

#### Notas
- Si el scan no lista ningún dispositivo, el problema es eléctrico (SDA/SCL, GND común, alimentación o pull-ups).
- Si aparece una dirección diferente a las candidatas, se puede extender la lista en `initIna219()`.

---

## [1.17.2] — 2026-05-13

### Confirmación experimental del encoder servo y ajuste de acondicionamiento

#### Problema identificado
- Persistía incertidumbre sobre el tipo de salida del encoder del servo durante pruebas de banco.
- Medición validada por el usuario: en estado abierto el canal alcanza hasta **4.7 V**, y con adaptación resistiva se observa nivel alto de **~2.5 V** en GPIO.

#### Cambios aplicados

**1. Confirmación de comportamiento eléctrico (servo)**
- Se registra el encoder servo como salida compatible con **push-pull a 5 V** en el punto de prueba actual.
- Nivel alto en reposo: ~4.7 V (línea original del encoder).

**2. Adaptación segura a ESP32**
- Topología adoptada para canales A/B del servo: **divisor 10 kΩ / 10 kΩ** hacia GPIO34/GPIO35.
- Nivel alto esperado en ESP32: ~2.5 V (dentro de umbral lógico y seguro para 3.3 V).

#### Notas
- Se mantiene GND común entre fuente, encoder, L298N, INA219 y ESP32.
- Esta entrada documenta validación de hardware y actualización de criterio de cableado; no implica cambios de código en `esp32_qube_l298n.ino`.

---

## [1.17.1] — 2026-05-13

### Reconexión de hardware para recuperar INA219 y diagnóstico de señal de encoder

#### Problema identificado
- Se requirió reconectar el sistema completo para restablecer telemetría del INA219 (bus, corriente y potencia).
- Durante el diagnóstico del encoder, la etapa con divisor resistivo entregó solo **35–40 mV** al GPIO del ESP32 en estado alto.
- Ese nivel queda muy por debajo del umbral lógico de entrada digital, por lo que la ESP32 no detecta flancos y no mide `CNT/POS`.

#### Cambios aplicados

**1. Reconexión integral del cableado de medición (INA219)**
- Se volvió a cablear la ruta de potencia/sensado para recuperar lectura estable del INA219 en telemetría.
- Se validó retorno de variables `v_bus`, `i_ma` y `p_mw` en `GET /state` y salida serial.

**2. Registro del incidente de encoder por nivel lógico insuficiente**
- Se documenta que la topología con divisor resistivo usada en esta prueba no permitió nivel alto válido para ESP32.
- Hallazgo de banco: alto en A/B de 35–40 mV (indetectable), consistente con comportamiento de salida tipo open-drain cuando falta pull-up efectivo.

#### Notas
- Este registro corresponde a reconexión/diagnóstico de hardware; no requiere cambios adicionales de firmware en esta entrada.
- Acción recomendada para encoder: pull-up externo por canal a 3.3 V y evitar divisor a GND cuando la salida sea open-drain.

---

## [1.17.0] — 2026-05-07

### Corrección de Error en Régimen Permanente — Habilitación de Acción Integral

#### Problema identificado
- Tras 4 sesiones experimentales de captura de datos, se identificó que el motor **nunca alcanzaba el ángulo asignado** con error < 10°.
- El setpoint se enviaba correctamente, el motor arrancaba, pero se detenía 10–30° antes por fricción estática.
- Causa raíz: `Ki = 0.0` (integral desactivada) y zona de activación de integral restringida a `|err| < 8°`, que nunca se alcanzaba porque el motor se frenaba antes de entrar en esa zona.

#### Cambios aplicados

**1. Ki: 0.0 → 0.15**
- Habilita la acción integral para acumular corrección cuando el motor se frena por fricción.
- El anti-windup `INTEGRAL_LIMIT = 250` limita la acumulación máxima.

**2. Zona de activación integral: `|err| < 8°` → `|err| < 45°`**
- Permite que el integrador actúe durante el transitorio completo, no solo en zona de estado estable.
- Con el esquema anterior, si el motor se detenía a 20° del setpoint, la integral nunca acumulaba.

**3. Velocidad máxima para activación integral: 25°/s → 60°/s**
- Permite integrar durante el transitorio de aproximación, no solo en estado cuasi-estático.

#### Cambios de firmware
```cpp
// Ganancia integral habilitada
float Ki = 0.15f;  // Antes: 0.0f

// Zona de activación del integrador (lazo de control)
if (abs(err) < 45.0f && abs(filteredVel) < 60.0f) {  // Antes: 8° / 25°/s
  integralTerm += err * dt;
  ...
}
```

#### Ajuste fino recomendado
- Si converge pero oscila alrededor del setpoint: reducir `Ki` a `0.10`
- Si sigue sin alcanzar el setpoint: subir `Ki` a `0.20`
- Comandos HTTP: `/cmd?ki=0.10` o `/cmd?ki=0.20`

---

## [1.16.0] — 2026-05-06

### WiFi AP+STA, CORS, GUI Web y Diagnósticos de Red

#### Cambios aplicados

**1. Modo WiFi AP+STA simultáneo**
- El ESP32 ahora puede crear su propio AP (`QUBE-ESP32` / `qube1234`) **y** conectarse a una red LAN al mismo tiempo.
- Variables configurables: `ENABLE_STA`, `STA_SSID`, `STA_PASS`, `WIFI_CONNECT_TIMEOUT_MS` (15 s).
- Función `connectStaIfConfigured()` con timeout y feedback por Serial.

**2. AP explícitamente visible**
- `WiFi.softAP(AP_SSID, AP_PASS, 6, false, 4)` — canal 6, `hidden=false`, máx 4 clientes.
- Antes el AP podía aparecer como "red oculta" en Windows.

**3. Headers CORS en todas las rutas HTTP**
- `addCorsHeaders()` añade `Access-Control-Allow-Origin: *` a todas las respuestas.
- Handlers OPTIONS registrados para `/state` y `/cmd` (preflight del navegador).
- Permite usar la GUI web desde cualquier origen sin error de CORS.

**4. Diagnóstico de red en runtime**
- Función `printNetworkInfo()`: imprime AP SSID, AP IP, LAN SSID, LAN IP por Serial.
- Comando Serial `'i'` → ejecuta `printNetworkInfo()`.
- `printHelp()` actualizado con mención al comando `i(IP)`.

#### Variables de configuración añadidas
```cpp
const bool ENABLE_STA = true;
const char* STA_SSID = "";  // Rellenar con SSID del router
const char* STA_PASS = "";  // Rellenar con contraseña
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
```

---

## [1.15.0] — 2026-04-29

### Endurecimiento del Lazo de Control y Preparación para Estabilización de Señales

#### Problema identificado
- El motor oscila ±8–15° alrededor del setpoint debido a PWM_MIN=28, que fuerza al motor a moverse incluso para errores muy pequeños (< 1°).
- La autoridad de Kp=0.42 es insuficiente para setpoints grandes o transitorios rápidos.
- El deadband de 0.3° es demasiado pequeño, permitiendo que el ruido del encoder cause chatter.

#### Cambios de firmware aplicados

**1. Reducción de PWM_MIN: 28 → 12**
- Permite resolución de control más fina (motor puede moverse en pasos más pequeños).
- Reduce la banda muerta donde el controlador no puede ajustar PWM sin jump abrupto.
- Nota: El motor debe probarse en modo manual (`m1, p15`) para verificar que funciona a PWM ≥ 12.

**2. Aumento de Ganancia Proporcional: Kp 0.42 → 0.75**
- Mejora la respuesta en transitorios y setpoints lejanos (>30°).
- Compensa la reducción de PWM_MIN_SIZE al permitir mayor autoridad de corrección.
- No se cambia Ki/Kd en esta versión (Ki permanece desactivada).

**3. Ampliación de Deadband: 0.3° → 0.8°**
- Suprime oscilaciones residuales causadas por ruido discreto del encoder (±1 LSB ≈ 0.176°/cnt).
- Mejora estabilidad en estado estable sin sacrificar capacidad transiente.

#### Beneficios esperados
- ✅ Control más suave sin oscilación tipo bang-bang
- ✅ Mejor tracking en transitorios rápidos (>30°)
- ✅ Reducción de chattering en setpoint constante
- ✅ Mejor resolución de control en zona lineal

#### Cambios de firmware mínimos
```cpp
// Línea 121: PWM_MIN
const int PWM_MIN = 12;    // Antes: 28

// Línea 121: Kp  
float Kp = 0.75f;         // Antes: 0.42f

// Línea 641: Deadband
if (abs(err) <= 0.8f) {   // Antes: 0.3f
  pwm = 0;
}
```

#### Comandos de calibración aún activos
- `kp<val>`: sobrescribe Kp en runtime
- `ki<val>`: idem
- `kd<val>`: idem
- `/cmd?kp=0.75`: equivalente HTTP

#### Validación recomendada
1. Compilar y cargar firmware
2. Probar modo manual: `m1` → `p15` → motor debe girar suavemente
3. Probar PID en setpoint 0°: `m2, s0` → debe converger sin oscilar
4. Probar transiente: `s45` → debe alcanzar setpoint en ~2–3 segundos sin overshoot excesivo

---

## [HW-FIX-1] — 2026-04-29

### Diagnóstico de hardware — Encoder sin lectura confiable

#### Causa raíz identificada
- El encoder del servo (Premotec 990412016913) tiene salida **open-drain**: en estado neutro flota alrededor de **2.5 V**, y llega a 5 V solo en el pico de conmutación.
- El level shifter en la ruta A/B medía **~7 MΩ** de impedancia de señal, insuficiente para sostener un nivel lógico limpio.
- Resultado: señal indeterminada que el ESP32 (GPIO34/GPIO35) no puede discriminar como 0 o 1. `CNT` y `POS` no cambian aunque el eje gire.

#### Solución de hardware aplicada
- Se **eliminó el level shifter** del camino de señal A/B.
- Se instalaron **pull-up de 4.7 kΩ a 3.3 V** directamente en las líneas A y B.

```
Encoder A ──┬── 4.7kΩ ── 3.3V
            └── GPIO34 (ESP32)

Encoder B ──┬── 4.7kΩ ── 3.3V
            └── GPIO35 (ESP32)

Encoder GND ─── GND común
```

#### Por qué es seguro sin el level shifter
- Con salida open-drain y pull-up a 3.3 V, la línea oscila entre 0 V (transistor interno conduce) y 3.3 V (pull-up sostiene). Nunca supera 3.3 V en el GPIO.
- El ESP32 GPIO34/GPIO35 no es 5 V tolerante, pero con este esquema nunca ve más de 3.3 V.

#### Cambios de firmware
- **Ninguno requerido.** El firmware ya usaba `INPUT` (sin pull-up interno) en GPIO34/GPIO35, que es correcto para esta topología.

---

## [1.14.0] — 2026-04-28

### Problema detectado
- La posición seguía reportándose incorrecta tras estabilizar el modo de control. En esta etapa, la causa probable pasa a ser **calibración de escala y/o signo del encoder** (no solo captura de pulsos).

### Añadido
- **Calibración en runtime de lectura de encoder** (sin recompilar):
  - `ed<1|-1>`: define dirección de encoder (`encoderDir`).
  - `cpr<val>`: define cuentas por vuelta (`countsPerRev`).
- Equivalentes HTTP:
  - `/cmd?ed=-1`
  - `/cmd?cpr=2048`
- Telemetría JSON extendida:
  - `encoder_dir`
  - `counts_per_rev`

### Objetivo
- Corregir lecturas mal orientadas o mal escaladas de forma inmediata durante la puesta a punto del banco.

---

## [1.13.0] — 2026-04-28

### Problema detectado
- En algunas pruebas, `M:2` permanecía activo pero `POS/CNT` casi no variaban, afectando directamente al PID por falta de retroalimentación confiable.

### Añadido
- **Decodificación de encoder por polling (cuadratura X4)** en `loop()` con tabla de transición (`QUAD_LUT`).
- **Selector de modo de captura**:
  - `USE_ENCODER_INTERRUPTS` (ISR A/B)
  - `USE_ENCODER_POLLING` (sondeo)
- En esta versión se deja **polling activo por defecto** y **interrupciones desactivadas** para robustez en banco.
- **Telemetría de diagnóstico** añadida en JSON:
  - `enc_a`
  - `enc_b`

### Resultado esperado
- Si las señales A/B están presentes en hardware, `CNT/POS` deben actualizarse aunque las ISR no disparen correctamente.
- Si `enc_a/enc_b` quedan fijos, el problema es físico (cableado, nivel lógico o encoder incorrecto), no del PID.

---

## [1.12.0] — 2026-04-28

### Problema detectado
- Durante pruebas de setpoint en PID (`M:2`), el sistema regresaba a `M:0` con `PWM:0` aunque el eje no había llegado al objetivo. Causa: activación del timeout de comandos en banco de pruebas.

### Cambiado
- **Failsafe por timeout configurable**:
  - Nueva bandera `ENABLE_COMMAND_TIMEOUT`.
  - Valor por defecto: `false` para ajuste y calibración en banco.
  - Al ponerla en `true`, se mantiene el comportamiento previo (`safeStop()` cuando expira `COMMAND_TIMEOUT_MS`).

### Nota de uso
- Para operación final con mayor seguridad, reactivar `ENABLE_COMMAND_TIMEOUT = true`.

---

## [1.11.0] — 2026-04-28

### Problema detectado
- Desfase angular sistemático entre setpoint y posición medida (ejemplo reportado: `s-90` alcanzaba alrededor de `45°`). Esto indica referencia cero mecánica desalineada respecto al cero del encoder.

### Añadido
- **Calibración de offset angular en runtime**:
  - Variable `positionOffsetDeg` aplicada a la posición usada por PID y telemetría.
  - Función `zeroPositionHere()` para fijar el cero en la posición mecánica actual.
- **Nuevos comandos serie**:
  - `z` : toma la posición actual como cero (`positionOffsetDeg = rawPos`), pone `setpoint=0` y resetea PID.
  - `o<deg>` : fija manualmente el offset (en grados).
- **Nuevos comandos HTTP**:
  - `/cmd?z=1`
  - `/cmd?o=<deg>`
- **Telemetría extendida**:
  - `raw_position_deg`
  - `offset_deg`

### Resultado esperado
- Corrección directa de desfases constantes (ej. ±45°) sin recablear ni recompilar por cada prueba.

---

## [1.10.0] — 2026-04-28

### Problema detectado
- Aunque el eje alcanzaba `45°`, seguía acumulando demasiada energía al cruzar el setpoint y luego se disparaba de nuevo hacia ángulos grandes. La causa ya no era la dirección del control, sino una combinación de mando excesivo cerca del objetivo e integración activa fuera de la zona útil.

### Cambiado
- **Ganancias**:
  - `Kp`: 0.50 → **0.42**
  - `Ki`: 0.002 → **0.0**
  - `Kd`: se mantiene en **0.06**
- **Integración condicionada**:
  - El término integral solo se acumula si `|err| < 8°` y `|vel| < 25°/s`.
  - Fuera de esa ventana, el integrador se reinicia a `0` para evitar windup durante aproximaciones rápidas.
- **Compensación de fricción más conservadora**:
  - `PWM_MIN` solo se fuerza si `|err| > 8°` y `|vel| < 15°/s`.
- **Límite de PWM dependiente del error**:
  - `|err| < 20°` → `PWM <= 80`
  - `|err| < 10°` → `PWM <= 55`
  - `|err| < 5°` → `PWM <= 35`

### Objetivo
- Reducir la energía con la que el eje cruza el setpoint.
- Evitar que un sobreimpulso pequeño se convierta en una fuga de gran amplitud.

---

## [1.9.0] — 2026-04-28

### Ajuste fino
- A partir de una respuesta ya estable en `45°` (sobreimpulso aproximado de `1.9°` y correcciones finales entre `PWM=0` y `PWM=1`), se realizó un refinamiento para mejorar el asentamiento final y reducir error residual.

### Cambiado
- **Ganancias PID**:
  - `Kp`: 0.55 → **0.50**
  - `Ki`: 0.00 → **0.002**
  - `Kd`: se mantiene en **0.06**
- **Banda muerta de posición**:
  - `|err| <= 0.5°` → **`|err| <= 0.3°`**

### Objetivo
- Reducir ligeramente el sobreimpulso sin perder rapidez.
- Permitir corrección lenta del error estático residual sin reintroducir oscilación apreciable.

---

## [1.8.0] — 2026-04-28

### Problema detectado
- La telemetría mostró inversión prematura del control antes de alcanzar el setpoint (`PWM:+28` alrededor de 32° con `SP=45°`). Esto indicó que la derivada seguía dominando la ley de control aun con el filtro previo, provocando **chattering** y frenado anticipado.

### Cambiado
- **Ganancias PD reajustadas** para dar mayor peso al error de posición y menor peso al término derivativo:
  - `Kp`: 0.35 → **0.55**
  - `Kd`: 0.18 → **0.06**
- **Filtro de velocidad más suave**:
  - `VEL_ALPHA`: 0.25 → **0.12**
  - Esto incrementa el suavizado de la velocidad estimada y reduce inversión espuria de signo por ruido o cuantización del encoder.
- **Compensación de fricción (`PWM_MIN`) menos agresiva**:
  - Antes: se forzaba cuando `|err| > 2°` y `|vel| < 50°/s`
  - Ahora: solo se fuerza cuando `|err| > 6°` y `|vel| < 20°/s`
  - Objetivo: evitar comportamiento tipo bang-bang durante la aproximación al setpoint.

---

## [1.7.0] — 2026-04-28

### Problema detectado
Con `Kd=0.45` a 200 Hz, el ruido de ±1-2 counts del encoder cuadratura generaba velocidades aparentes de ~70°/s. El término derivativo (0.45×70=31 PWM) superaba al proporcional (0.25×45=11 PWM) desde el primer ciclo, enviando el motor en dirección contraria al setpoint.

### Cambiado
- **Filtro paso-bajo en la velocidad** (`filteredVel`): la derivada ya no se calcula directamente de muestra a muestra sino como EMA (*Exponential Moving Average*) con `VEL_ALPHA=0.25`. Esto reduce el impacto del ruido cuántico del encoder sin eliminar la información de velocidad real.
  - Fórmula: `filteredVel = 0.25 × rawVel + 0.75 × filteredVel`
- **`filteredVel` se inicializa a 0** en `resetPid()` para evitar transitorio al arrancar.
- **Ganancias reajustadas** a valores seguros con derivada filtrada:
  - `Kp`: 0.25 → **0.35**
  - `Kd`: 0.45 → **0.18** (Kd efectivo equivalente mayor gracias al filtro)

---

## [1.6.0] — 2026-04-28

### Cambiado
- **Ganancias PID** ajustadas para reducir oscilación creciente (sistema subamortiguado):
  - `Kp`: 0.4 → **0.25** (menos agresividad proporcional)
  - `Kd`: 0.20 → **0.45** (mayor amortiguación al cruzar el setpoint)
- **Lógica de zona muerta (`PWM_MIN`)**: antes se forzaba `PWM_MIN` siempre que `|err| > 0.8°`, lo que inyectaba energía extra mientras el motor ya tenía velocidad alta, amplificando las oscilaciones. Ahora solo se fuerza si se cumplen **ambas** condiciones:
  - `|err| > 2.0°` (lejos del setpoint)
  - `|velocidad| < 50°/s` (motor casi parado)
- Umbral de parada: `|err| ≤ 0.5°` (antes 0.4°).

### Contexto
- Motor llegaba a 45° con buena oscilación inicial pero la corrección de retorno lo llevaba a −90° o más. Causa: `Kd` insuficiente para frenar la velocidad de cruce + `PWM_MIN` añadiendo energía durante las oscilaciones.

---

## [1.5.0] — 2026-04-28

### Cambiado
- **Modo PD puro**: `Ki` establecido en `0.0` para eliminar windup integral como fuente de inestabilidad. El motor alcanzaba el setpoint (45°) pero la energía acumulada por el integrador durante la aproximación causaba un overshoot que crecía en cada ciclo hasta perder el control.
- **Ganancias ajustadas para amortiguación crítica** sobre el Premotec 990412016913:
  - `Kp`: 0.8 → **0.4**
  - `Ki`: 0.01 → **0.0** (desactivado temporalmente)
  - `Kd`: 0.05 → **0.20** (incrementado 4× para frenar oscilaciones)

### Proceso de sintonización recomendado (a partir de esta versión)
1. Estabilizar con PD puro (`Ki=0`): ajustar `Kp` y `Kd` hasta obtener respuesta sobreamortiguada o críticamente amortiguada.
2. Una vez estable, introducir `Ki` de forma incremental desde `0.003` para eliminar error estático residual.
3. Verificar que Ki no reintroduce oscilaciones antes de aumentar.

---

## [1.4.0] — 2026-04-28

### Corregido
- **Retroalimentación positiva (fuga del motor)**: el PID empujaba en la misma dirección que el error creciente, causando que el motor se alejara indefinidamente del setpoint en lugar de converger. Causa raíz: la dirección positiva del motor era opuesta a la dirección positiva del encoder.

### Añadido
- **Constante `MOTOR_DIR`** (`1` / `-1`): invierte la salida del PID hacia `setMotor()` sin modificar la lógica de control ni el encoder. Valor predeterminado: `-1` (invertido para el Premotec 990412016913 con la conexión OUT1/OUT2 actual). Ajustable en una sola línea si se invierte el cableado del motor.

---

## [1.3.0] — 2026-04-28

### Cambiado
- **Control PID: derivada sobre la medición** (`-d(pos)/dt`) en lugar de sobre el error (`d(error)/dt`).
  - Elimina el pico de control (*derivative kick*) al cambiar el setpoint bruscamente.
  - Previene arranque a PWM máximo al activar modo PID con posición alejada del setpoint.
- **Ganancias PID ajustadas** para motor Premotec 990412016913 (18 V nominal, operado a 15 V):
  - `Kp`: 2.0 → **0.8**
  - `Ki`: 0.04 → **0.01**
  - `Kd`: 0.03 → **0.05**
- **`resetPid()`**: ahora inicializa `prevPos` con la posición actual del encoder, evitando transitorio de derivada en el primer ciclo tras un reset o cambio de modo.

### Añadido
- Variable `prevPos` (posición anterior en grados) para cálculo de derivada sobre la medición.

---

## [1.2.0] — 2026-04-27

### Cambiado
- **`COMMAND_TIMEOUT_MS`**: 1500 ms → **10 000 ms** para facilitar pruebas interactivas sin que el failsafe detenga el motor entre comandos.
- **Zona muerta del PID**: umbral de parada refinado a `|err| ≤ 0.4°` y forzado de `PWM_MIN` para `|err| > 0.8°`, evitando oscilación permanente cerca del setpoint.

### Corregido
- **GPIO34 / GPIO35**: cambiados de `INPUT_PULLUP` a `INPUT`.  
  GPIO34 y GPIO35 son pines *input-only* en el ESP32-WROOM-32; no disponen de resistencia pull-up interna. La llamada a `gpio_pullup_en` generaba un error de boot. Se usan resistencias externas de 4.7 kΩ en el lado HV del level shifter.

---

## [1.1.0] — 2026-04-27

### Añadido
- **Wrappers de compatibilidad LEDC** para soportar tanto ESP32 Arduino Core v2 (`ledcSetup` / `ledcAttachPin`) como v3 (`ledcAttachChannel`), seleccionados automáticamente en tiempo de compilación mediante `#if ESP_ARDUINO_VERSION >= ESP_ARDUINO_VERSION_VAL(3,0,0)`.

### Corregido
- **`Adafruit_INA219.h` no encontrado**: inclusión condicional con `#if defined(__has_include)`. Si la biblioteca no está instalada, se usa una clase stub que devuelve valores nulos y activa el flag `inaOk = false`, permitiendo que el firmware compile y opere sin el sensor.

---

## [1.0.0] — 2026-04-27

### Añadido
- Firmware inicial para ESP32 + L298N + INA219 + LM2596 + level shifter 5V↔3.3V.
- **Modo `USE_ENA_PWM = false`**: PWM generado en IN1/IN2 del L298N con jumper ENA habilitado, sin necesidad de cable al GPIO25 (no disponible en el módulo ESP32-WROOM-32 estándar).
- Control en tres modos: `m0` (stop), `m1` (PWM manual), `m2` (PID posición).
- PID discrecional a 200 Hz con anti-windup por saturación del término integral (`INTEGRAL_LIMIT = 250`).
- Telemetría por puerto serie a 10 Hz: posición (°), conteo de encoder, setpoint, PWM, modo.
- Servidor HTTP (Access Point `QUBE-ESP32`) con endpoints `/state` (JSON) y `/cmd` (GET params).
- Lectura de encoder en cuadratura por interrupciones en GPIO34/GPIO35.
- Medición de bus, corriente y potencia por INA219 vía I2C (GPIO21=SDA, GPIO22=SCL).
- Failsafe: detención automática si no se reciben comandos en `COMMAND_TIMEOUT_MS`.

---

## Pinout de referencia (versión actual)

| Señal | GPIO ESP32 | Observación |
|-------|-----------|-------------|
| L298N IN1 | GPIO26 | PWM dirección + |
| L298N IN2 | GPIO27 | PWM dirección − |
| Encoder A | GPIO34 | Vía Schmitt trigger CD40106BE (doble inversión), Vcc=3.3V |
| Encoder B | GPIO35 | Vía Schmitt trigger CD40106BE (doble inversión), Vcc=3.3V |
| INA219 SDA | GPIO21 | I2C |
| INA219 SCL | GPIO22 | I2C |
| ENA L298N | Jumper | Sin cable al ESP32 |

## Motor de referencia

**Premotec 990412016913** — Motor DC con encoder, 18 V nominal, operado a 15 V con L298N.
Dos conectores de 5 pines (encoder motor + encoder péndulo): VCC, A, GND, B, Index.  
Cable trenzado de 2 pines: M+ / M− (terminales del motor, conectados a OUT1/OUT2 del L298N).
