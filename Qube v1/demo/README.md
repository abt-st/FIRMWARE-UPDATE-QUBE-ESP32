# Demostración de avance

Secuencia guiada sobre el hardware real, pensada para mostrar el estado del proyecto
en una reunión. Cada bloque explica qué va a hacer, lo hace, y muestra lo medido.

## Antes de empezar

1. **Conectar el PC a la red WiFi `QUBE-ESP32`** (clave `qube1234`). El firmware
   opera como SoftAP puro, así que la placa **no** está en la red del laboratorio:
   mientras dure la demo el WiFi del PC no tiene salida a internet (si lo necesita,
   dejar el cable Ethernet conectado en paralelo).
2. **Encender la ESP32** y verificar que responde:
   ```bash
   curl http://192.168.4.1/state
   ```
3. **Despejar el recorrido del brazo.** El homing lo mueve unos 270° contra ambos
   topes mecánicos.
4. **Péndulo colgando libre**, sin nada que lo enganche.

```Shell
cd demo
python demo_avance.py
```

Pide ENTER entre bloques, para poder ir explicando. `Ctrl-C` corta en cualquier
momento y **siempre** deja el motor detenido.

## Los siete bloques

| # | qué muestra                                                 | dura         |
| - | ------------------------------------------------------------ | ------------ |
| 1 | El problema: el encoder pierde el cero al reiniciar          | instantáneo |
| 2 | Homing automático, 3 corridas seguidas                      | ~40 s        |
| 3 | Control de posición del brazo (PID), escalón y vuelta      | ~25 s        |
| 4 | Swing-up: el bombeo creciendo ciclo a ciclo                  | ~30 s        |
| 5 | El entorno de entrenamiento recalibrándose solo             | ~15 s        |
| 6 | Metodología: tres mediciones contaminadas que se detectaron | ~10 s        |
| 7 | Estado y trabajo pendiente                                   | instantáneo |

Los tiempos de la tabla suman ~2 minutos de ejecución corrida, pero varían bastante:
los bloques 3, 4 y 5 arrancan con un homing, y los bloques 4 y 5 esperan además a que
el péndulo se aquiete (hasta 30 s si viene con energía residual). Con las pausas para
explicar, contar 5–7 minutos.

## Opciones

```bash
python demo_avance.py --solo 2,4,5   # sólo algunos bloques
python demo_avance.py --sin-pausa    # corrido, sin ENTER
```

## Qué esperar en cada bloque

**Bloque 2 — homing.** Las tres corridas deberían dar un recorrido de ~270° y una
dispersión del centro por debajo de 0,4°. El valor típico es **0,176°, que es
exactamente un conteo de encoder**: no se puede medir mejor con este sensor.

**Bloque 3 — PID.** Converge a 25° con sobrepaso del 30–70% y vuelve a 0. El
sobrepaso alto es ajuste pendiente, no un problema de la planta.

**Bloque 5 — entorno de entrenamiento.** Es la parte de software: `QubeRealEnv` pide
un reset con recalibración y el episodio arranca centrado, con `zero_epoch` marcando
el marco de referencia. Necesita el venv del proyecto; si no lo encuentra lo dice y
sigue sin romper nada.

Viene inmediatamente después del swing-up, así que el bloque espera el reposo del
mecanismo y pasa `homing_settle_time=3.0` en vez del default `0.0`. Sin eso el homing
lee una perturbación como si fuera un tope y el firmware aborta con código 5 — y a
diferencia de los otros bloques, el entorno **no reintenta**: levanta excepción.

**Bloque 4 — swing-up.** Lo elocuente es la línea de crecimiento:

```
21 → 42 → 44 → 59 → 74 → 92 → 109 → 121 → 134 → 155 → 157
```

Llega a **150–160°** según la corrida (vertical = 180°). **No va a equilibrar** — eso
es lo que está en curso, y el bloque lo dice explícitamente.

Si avisa *"péndulo detenido antes de fijar su cero: NO"*, el péndulo arrancó con
energía residual y el cero quedó corrido: los ángulos de ese bloque no sirven. Esperar
a que se aquiete y repetir con `--solo 4`.

Que informe *"el brazo cruzó su límite de 95°"* es el final **esperado**, no una
excepción: ocurrió en las 7 corridas registradas el 2026-07-31. El corte automático
actúa a los 95° y el brazo arrastra unos grados más. Es la protección funcionando.

La línea *"entrega al LQR"* puede salir de las dos formas. Con la compuerta de
velocidad ya corregida (P4), un barrido de 4 corridas en `tn=175` no disparó ninguna
entrega; la demo corre con `tn=155`, que cae justo dentro de la meseta medida
(142–154°), así que puede disparar o no. Ambos resultados son honestos y el bloque los
informa por igual.

## Tolerancia a fallos

Cada bloque está **aislado**: si uno falla, los demás siguen corriendo y el script
dice cómo reintentar sólo ese. En una presentación es peor quedarse sin el resto que
perder un bloque.

El homing **reintenta hasta 3 veces** por su cuenta. El fallo por recorrido fuera de
tolerancia es esporádico (roce mecánico) y casi siempre pasa al segundo intento; si
insiste las tres, hay algo físico que revisar.

Al salir —por fin normal, por `Ctrl-C` o por error— el corte del motor se reintenta
**15 veces** antes de dar una alarma. Una caída transitoria de HTTP no debe traducirse
en un susto innecesario, pero tampoco se declara detenido sin confirmarlo.

**Qué NO respalda a la demo.** El watchdog de comandos del firmware sólo vigila los
modos 1 (PWM manual) y 6 (RL por HTTP): los modos que usa esta demo —2, 3 y 5— son
autónomos y siguen corriendo sin órdenes externas por diseño. Si el HTTP se cae a mitad
de un bombeo, el único respaldo es el límite duro del brazo (`SERVO_HARD_LIMIT_DEG`,
95°), que dispara `setMode(0)`. Por eso conviene tener a mano el corte de alimentación.

## Si algo sale mal

| síntoma                                      | qué hacer                                                                                                               |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `No responde la placa`                      | Verificar encendido y que el PC siga asociado a `QUBE-ESP32`. La IP ya no cambia: siempre `192.168.4.1`                  |
| `El INA219 no responde`                     | No sigue a propósito: sin protección de corriente no se energiza el motor                                              |
| `homing FAIL code=1`                        | Recorrido fuera de tolerancia. Revisar que nada obstruya el brazo y reintentar                                           |
| `homing FAIL code=5`                        | El mecanismo no se aquietó. Esperar a que el péndulo pare y reintentar                                                 |
| Se queda unos segundos sin responder          | Normal y tolerado: el lazo de la ESP32 llega a bloquearse ~95 ms cuando el WiFi le roba tiempo. El script reintenta solo |
| El brazo queda contra un tope                 | Correr`--solo 2`: el homing lo recupera solo                                                                           |
| `El bloque 5 falló: Homing FALLO (code=5)` | El mecanismo no se aquietó. Esperar y correr`--solo 5`                                                                |

**Parada de emergencia:**

```bash
curl "http://192.168.4.1/cmd?m=0"
```

## Honestidad de lo que se muestra

La demo está construida sobre resultados **reproducibles**. Lo que aún no funciona —la
captura del péndulo en la vertical— se declara en los bloques 4 y 6 en vez de
esquivarse.

El bloque 5 no es relleno: buena parte del trabajo fue descubrir que mediciones
propias estaban contaminadas, y las tres que menciona son reales y están documentadas
con su evidencia en `docs/REGISTRO_PROBLEMAS.md`.
