# 2026-08-21 — Reintento del swing-up + frecuencia de oscilación

Campaña de banco de una sola sesión. Firmware v1.63.0. Todas las trazas son del
DAQ del chip a 500 Hz (`/daq`), no del muestreo HTTP.

> **Aviso de comparabilidad.** Las trazas son de la MISMA sesión, en el orden en
> que están numeradas, con un homing entre cada una. El banco deriva dentro de una
> sesión (ver P12), así que las tandas 1→5 se comparan entre sí pero **no** contra
> campañas de otro día.
>
> **Y las tandas se tomaron sondeando `/state`**, que según
> [P28](../../docs/REGISTRO_PROBLEMAS.md#p28) le cuesta al lazo de 500 Hz una
> resincronización por petición. Las muestras del DAQ las produce y las marca
> temporalmente el propio chip, así que siguen siendo un registro válido de lo que
> pasó — pero pasó bajo esa carga.

## Qué hay

| archivo | qué es |
|---|---|
| `data/tanda1_sin_hold.csv` | Reintento tal como se escribió primero. |
| `data/tanda2_hold_banda_unica.csv` | Con hold del brazo, banda única de 20°. |
| `data/tanda3_hold_histeresis.csv` | Con hold e histéresis 35°/15°. |
| `data/tanda4_hold_histeresis.csv` | Repetición de la 3 (n=2). |
| `data/tanda5_hold_histeresis.csv` | Tanda de sanidad tras el último cambio (n=3). |
| `data/caida_libre_brazo_libre.csv` | Bombear, cortar a `m0`, dejar decaer. |
| `data/caida_libre_brazo_retenido.csv` | Ídem, pero cortando a `m2` con `s=0`. |
| `captura_reintento.py` | Captura las tandas de reintento. |
| `captura_caida_libre.py` | Bombea y corta a la amplitud pedida. |
| `analisis_frecuencia.py` | Reproduce la tabla de frecuencias de abajo. |

## Resultado 1 — el reintento funciona, y tres defectos que se vieron y corrigieron

| tanda | máx \|brazo\| | muestras >95° | >110° | timeout de quietud |
|---|---|---|---|---|
| 1 (sin hold) | **134,56°** = tope mecánico | 186 | 98 | — |
| 2 (hold banda única) | 124,81° | 102 | 46 | **sí**, 20 s perdidos |
| 3 (hold + histéresis) | 110,39° | 79 | 9 | no |
| 4 (ídem) | 124,28° | 196 | 109 | no |
| 5 (ídem + corte por vueltas) | 105,64° | 110 | **0** | no |

Con la versión final el pico del brazo queda en **105–124°** (n=3): ya no llega al tope
mecánico, pero **sigue pasándose del límite blando de 95°** mientras frena la inercia con la
que el brazo entra al recentrado. Eso es consecuencia de [P26](../../docs/REGISTRO_PROBLEMAS.md#p26),
no del reintento.

Los tres defectos, todos visibles en las trazas:

1. **El péndulo se lleva el brazo con el motor suelto.** La fase de quietud de P22
   corre con `setMotorDirect(0)`. Traza de la tanda 1: el recentrado entrega el
   brazo a −6,2° y **en 1,1 s el brazo llega a +96° con `pwm` en 0 en todas las
   muestras** — sin par del motor, sólo reacción del péndulo oscilando. Gastaba un
   reintento entero sin llegar a bombear. Corregido con un hold del brazo.
2. **El hold con banda única se impide a sí mismo arrancar.** Tanda 2: el brazo se
   clavó en 19,5–20,0° —el borde de la banda de 20°— y estuvo 20 s dando pulsos de
   50 PWM. Cada pulso movía el brazo más que `HOMING_QUIET_DEG` (0,5°) y rearmaba
   la ventana de quietud, **con el péndulo quieto en ±1° todo ese tiempo**.
   Corregido con histéresis 35°/15°.
3. **El piso de PWM re-lanzaba el freno.** El piso de fricción estática se aplicaba
   también al comando que iba en contra: la traza muestra `pwm` alternando −45/+45
   entre muestras consecutivas. Es el bang-bang de P8 reintroducido por el propio
   piso. Corregido: el piso sólo se aplica al empuje, nunca al freno.

En las cuatro tandas `swing_fail_reason` fue **siempre 3 (el brazo llegó al tope)**:
nunca disparó la detección de caída del péndulo. El brazo llega al tope **antes** de
que el péndulo se caiga, que es exactamente lo que predice [P26](../../docs/REGISTRO_PROBLEMAS.md#p26).

## Resultado 2 — el bombeo NO está desintonizado

Comparar el bombeo contra un único número de `f_n` no sirve: el período del péndulo
crece con la amplitud, y el swing-up recorre 0–180°. La comparación correcta es banda
por banda, contra la caída libre **a esa misma amplitud**:

| amplitud pico | bombeo (m5) | libre (m0) | cociente |
|---|---|---|---|
| 20–40° | 1,969 Hz | 2,153 Hz | 0,915 |
| 40–60° | 1,952 | 2,007 | 0,972 |
| 60–80° | 1,768 | 1,796 | 0,984 |
| 80–100° | 1,600 | 1,603 | **0,998** |
| 100–120° | 1,430 | 1,448 | 0,987 |
| 120–145° | 1,286 | 1,321 | 0,973 |

**Entre 40° y 145° el bombeo sigue la frecuencia propia del péndulo dentro del 0–3 %.**
La ley resonante hace lo que dice hacer. La hipótesis «el swing-up no captura porque
bombea fuera de resonancia» queda **refutada con medición**.

La única desintonía real está en el arranque: a 20–40° el cociente es 0,915, y ahí es
donde actúa `SWINGUP_KICK_HZ = 2,0 Hz` contra una f natural de ~2,13 Hz (−6 %).

## Resultado 3 — la `f_n` del péndulo depende de si el brazo está suelto

| condición del brazo | f_n a ángulo pequeño | origen |
|---|---|---|
| **rígidamente fijo** | 1,700 Hz | analítica √(3g/2L_p), L_p = 0,129 m (+ 3 vías del registro) |
| **libre** (`m0`, puente en corto) | **2,134 Hz** | medido acá, 32 medios ciclos de 138° a 35° |
| «retenido» por el PID del `m2` | 1,411 Hz | medido acá, n=3 — **se descarta, ver abajo** |

Contra el valor de brazo fijo, el brazo libre da un cociente de **1,255**. El signo es el
correcto para un péndulo de Furuta: soltar la base la deja retroceder, baja la inercia
efectiva que ve el péndulo y el modo dominado por el péndulo **sube**. La magnitud queda
pendiente de contrastar contra el modelo acoplado de `qube_dynamics.py`.

Un número de `f_n` **no significa nada sin decir en qué condición se midió**, y por ahí se
cuela la contradicción 1,70 / 2,28 Hz del registro: pueden no contradecirse, ser condiciones
distintas. (Eso no exonera la medición de 2,28 Hz: sus tres corridas dieron 4,8–7,1 Hz entre
sí, así que sigue siendo inservible por dispersión. Lo que cambia es que su valor central ya
no es absurdo.)

**Para el swing-up manda la condición de brazo libre**, porque durante el bombeo el brazo se
mueve. O sea ~2,13 Hz a ángulo pequeño, bajando a ~1,2 Hz cerca de la vertical.

**Por qué se descarta la pierna del `m2`.** Su 1,411 Hz cae **por debajo** del valor con brazo
rígido (cociente 0,830), así que no puede estar interpolando entre «libre» y «fijo». Un PID de
posición es un **resorte**, no un empotramiento: un péndulo sobre base elástica tiene un modo
acoplado *inferior* al de base rígida, y eso es lo que se midió. El brazo se movió además entre
−30,9° y +26,3° con PWM de hasta 197, y son n=3 medios ciclos. Queda sólo como recordatorio de
que sujetar por software no es sujetar.

**Reserva de la pierna buena.** 32 medios ciclos limpios con el motor verificado en `pwm = 0`
en todas las muestras — pero es **una sola suelta**, al final de una sesión de ~8 campañas.

**El péndulo oscila.** 32 medios ciclos de decaimiento continuo. [P24](../../docs/REGISTRO_PROBLEMAS.md#p24)
—«el pivote desarrolló fricción seca dominante: ya no oscila», n=1, 2026-08-05— **no se
reproduce hoy**. La caída de amplitud es de ~5,5° por medio ciclo, aproximadamente
constante, que sigue siendo la firma de fricción seca; pero la magnitud ya no impide
oscilar.
