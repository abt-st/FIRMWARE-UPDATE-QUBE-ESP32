# Plan de trabajo — QUBE v2

Protocolo de banco por etapas, para ejecutar paso a paso. Nace con la migración a la
placa **DOIT ESP32 DevKit V1 de 30 pines** (`CHANGELOG.md` v1.57.1) y sigue con la cola
de pendientes que deja `REGISTRO_PROBLEMAS.md`.

**Estado de partida (2026-08-03):** el QUBE está armado y operativo con la placa de 38
pines, tal como quedó el 31 de julio. La placa nueva reemplaza a la vieja; el resto del
montaje (perfboard, L298N, INA219, 2× LM2596, 2× CD40106BE) no se toca.

## Convenciones

- **Dirección:** SoftAP puro, `http://192.168.4.1`. El PC debe estar asociado a la red
  `QUBE-ESP32`.
- **En PowerShell usar `Invoke-RestMethod`, no `curl`** — en PowerShell 5.1 `curl` es
  alias de `Invoke-WebRequest` y devuelve un objeto, no el JSON. Los ejemplos de
  `docs/http_api.md` están en sintaxis bash.
  ```powershell
  Invoke-RestMethod "http://192.168.4.1/state"
  Invoke-RestMethod "http://192.168.4.1/cmd?m=3"
  ```
- **Nunca abrir `pio device monitor`**: reinicia la placa. Toda observación va por HTTP.
- **Paro de emergencia:** `Invoke-RestMethod "http://192.168.4.1/cmd?x=1"`. Tenerlo a
  mano en una consola aparte antes de energizar el motor.
- Marcar cada paso con `[x]` a medida que se completa, y anotar el valor medido al lado
  del criterio. Los resultados que cambien un diagnóstico van a `REGISTRO_PROBLEMAS.md`.

---

## Etapa 1 — Recableado a la placa de 30 pines

Objetivo: que la placa nueva quede cableada y arranque, **sin energizar el motor**.

- [ ] **1.1 Fotografiar el cableado actual** antes de desconectar nada, con la placa
      vieja todavía puesta. Es el único registro de cómo estaba si algo no cierra.
- [ ] **1.2 Cortar toda la alimentación** — los 15 V de la fuente y el USB. Verificar con
      multímetro que VS del L298N está a 0 V antes de tocar cables.
- [ ] **1.3 Desconectar la placa de 38 pines.** Etiquetar los 9 hilos de señal + VIN/3V3/GND
      a medida que salen.
- [ ] **1.4 Montar la de 30 pines y cablear** con la tarjeta
      **`docs/hardware/pinout_esp32_30.png`** a la vista (imprimirla; es el mapa de los 30
      pines en orden físico, con las trampas marcadas en rojo). Tabla equivalente en
      `docs/hardware/pinout.md`. Los tres puntos donde se equivoca uno:
      - IN1/IN2 son contiguos (izq. #6-#7) — cinta directa, sin cruce.
      - Los 4 canales de encoder van en izq. #9–#12 en orden `33, 32, 35, 34`, que es el
        **inverso** del orden de J4 (`34, 35, 32, 33`): la cinta va cruzada.
      - SDA (der. #11) y SCL (der. #14) **no** son contiguos: entre medio están RX0 y TX0.
- [ ] **1.5 Continuidad, todo despoderado.** Multímetro entre cada hilo y su posición del
      header, contra la tabla. **Criterio:** 11 de 11 (9 señales + VIN + 3V3) y GND común.
- [ ] **1.6 Verificar el serigrafiado** de la placa contra el orden de filas documentado:
      hay clones con las filas espejadas.

**Criterio de etapa:** 1.5 completo sin ninguna discrepancia. Si aparece una, no seguir:
corregir y repetir la continuidad entera, no solo el hilo sospechoso.

---

## Etapa 2 — Primer arranque, motor desconectado

> **Corrección (2026-08-03, en banco).** La primera versión de esta etapa decía "el riel de
> 15 V queda apagado". **Es imposible:** los encoders y el CD40106BE se alimentan del riel
> de 5 V de la LM2596 #1, que cuelga de los mismos 15 V. Con la fuente apagada los
> encoders están muertos y sus niveles no significan nada — se leyó `enc_a=0, enc_b=1` en
> **ambos** encoders, patrón sin valor diagnóstico.
>
> El aislamiento correcto no es eléctrico sino mecánico: **desconectar los dos cables del
> motor de OUT1/OUT2 del L298N** y recién ahí encender los 15 V. Así los encoders y el
> INA219 quedan vivos y el motor no puede girar pase lo que pase, que es la garantía que
> se buscaba.

Los **cables del motor van desconectados** de OUT1/OUT2 durante toda esta etapa.

- [ ] **2.1 Desconectar los cables del motor** de OUT1/OUT2 y encender los 15 V. Con eso
      quedan vivos los dos rieles de 5 V (LM2596 #1 lógica/encoders y #2 ESP32) y el
      INA219, y el motor está mecánicamente fuera del circuito. La placa debe arrancar sin
      reinicios. **Si entra en boot loop**, cortar y revisar el riel: el brownout del
      swing-up ya costó crashes y el 1000 µF del rail de 5 V es la mitigación.
- [ ] **2.2 Flashear** desde `Qube v2\src\firmware`:
      ```powershell
      pio run -e esp32dev --target upload
      ```
- [ ] **2.3 Asociarse al SoftAP `QUBE-ESP32`** y leer estado:
      ```powershell
      Invoke-RestMethod "http://192.168.4.1/state"
      ```
      **Criterio:** responde JSON.
- [ ] **2.4 INA219 vivo.** En `/state`, `ina_ok = true` y `v_bus` coherente.
      **Criterio bloqueante:** sin INA219 no hay corte por calado — la protección está
      gateada por `inaOk`. Con `ina_ok = false` **no se energiza el motor**. Si falla,
      revisar SDA/SCL: el error más probable de esta placa es haberse corrido una
      posición hacia RX0/TX0.
- [ ] **2.5 Encoder del servo a mano.** Girar el brazo despacio y leer `count` /
      `position_deg`. **Criterio:** las cuentas cambian de forma monótona y limpia, sin
      saltos.
- [ ] **2.6 Encoder del péndulo a mano.** Igual con `pend_count` / `pend_position_deg`.
      **Criterio:** ídem, y —clave— que **cada encoder responda al suyo**. Si mover el
      brazo mueve las cuentas del péndulo, la cinta de J4 está sin cruzar (paso 1.4).
- [ ] **2.7 Salud del lazo.** `Invoke-RestMethod "http://192.168.4.1/cmd?rj=1"`, esperar
      ~10 s y leer `loop_dt_max_us` / `loop_overruns`.
      **Criterio:** `loop_dt_nom_us` = 2000 y `loop_overruns` = 0 en reposo.

**Criterio de etapa:** 2.4, 2.5 y 2.6 en verde. Recién ahí se energiza el motor.

### Resultados medidos — 2026-08-03

| paso | resultado | veredicto |
|---|---|---|
| 2.2 flasheo | 1.017.536 B, hash verificado | ✅ |
| 2.3 `/state` | responde por SoftAP | ✅ |
| 2.4 INA219 | **SDA y SCL estaban permutados en el cableado.** Corregido en el hierro; detecta en 0x40, `ina_ok=true` | ✅ |
| 2.5 encoder servo | tope a tope: **−1535 cuentas / −269,82°** contra 1536 / 270° esperados — **1 cuenta de error** | ✅ |
| 2.6 encoder péndulo | vuelta completa: **+2048 cuentas / +360,0°**, exacto. Sin diafonía: girar el brazo dejó `pend_count` inmóvil | ✅ |
| 2.7 salud del lazo | `loop_dt_nom_us`=2000, `loop_overruns`=**0** tras `rj=1` (los 91 ms de la primera lectura eran el escaneo WiFi del arranque) | ✅ |

**Los cuatro canales de encoder quedan validados**: cableado correcto (sin la cinta de J4
cruzada) y cadena de acondicionamiento sin pérdida de pulsos. Un error de 1 cuenta en 1535
y de 0 en 2048.

> **Trampa de medición encontrada.** Un primer barrido parcial del brazo dio 590 cuentas y
> pareció 60% de pérdida de pulsos. No lo era: el barrido no había llegado a los topes. La
> referencia física (tope a tope = 270° medidos con más de 30 homings) es lo que vuelve la
> prueba concluyente; girar "más o menos media vuelta" a ojo no mide nada.

> **Nota operativa.** Cada uso del puerto serie reinicia la placa y tira al PC del SoftAP,
> y Windows no vuelve solo. Reconectar con `netsh wlan connect name="QUBE-ESP32"`.

### Cómo se encontró el cruce de SDA/SCL (método reutilizable)

El multímetro **no podía encontrarlo**: medir 3,3 V en ambas líneas es compatible con el
cruce, con un cable cortado y con todo bien a la vez, porque los pull-ups internos de la
ESP32 de un lado y los del breakout del INA219 del otro dejan las dos líneas en alto pase
lo que pase. Un nivel alto no prueba continuidad ni orden.

Lo que sí discrimina, sin desarmar nada: **permutar los pines en firmware, reflashear y
escanear el bus.** Con `sda=22 scl=21` el INA219 apareció en 0x40 al instante; con los
documentados, `I2C scan: sin dispositivos`. Diagnóstico binario en un reflasheo.

El arreglo fue en el cableado, **no** en el firmware, y a propósito: toda la documentación
y las etiquetas de J3 dicen SDA=21 / SCL=22, y dejar el firmware permutado habría creado
la misma clase de divergencia silenciosa que ya costó cara con `MOTOR_DIR`.

---

## Etapa 3 — Energizar el motor y recuperar paridad

Objetivo: demostrar que la placa nueva se comporta igual que la vieja, no solo que
arranca. La referencia es la campaña del 30 de julio
(`experiments/2026-07-30_full_validation/data/verdicts.json`).

- [ ] **3.1 Encender el riel de 15 V.** Con el brazo libre y la mano en el paro.
- [ ] **3.2 Sentido de giro.** `m1` con PWM chico:
      ```powershell
      Invoke-RestMethod "http://192.168.4.1/cmd?m=1&p=40"
      Invoke-RestMethod "http://192.168.4.1/cmd?m=0"
      ```
      **Criterio:** el brazo va en el sentido que espera `MOTOR_DIR`.
      **Si va al revés: invertir los cables del motor, NO el `#define`.** Cambiar el
      signo en firmware manda al tope al PID, al LQR y al swing-up a la vez.
- [ ] **3.3 Homing.** `Invoke-RestMethod "http://192.168.4.1/cmd?m=3"` y leer
      `homing_range`, `homing_ok`, `homing_fail`.
      **Criterio:** `homing_ok = true`, `homing_range` ≈ 270° (ventana 262–278), 3 de 3
      repeticiones. Dispersión del tope esperada ≈ 0,35° tras la corrección de P3.
- [ ] **3.4 Repetir el homing 5 veces** anotando `homing_stop_pos` / `homing_stop_neg`.
      **Criterio:** dispersión comparable a la histórica. Una dispersión de ~20° en el
      lado positivo es el punto duro de P3 volviendo — revisar `HOMING_PWM_SEEK = 70`.
- [ ] **3.5 Validación completa de modos** con el script existente:
      ```powershell
      uv run python experiments/2026-07-30_full_validation/scripts/validate.py
      ```
      **Criterio:** mismos veredictos que `verdicts.json` del 30 de julio. Las diferencias
      que aparezcan son atribuibles al cambio de placa y hay que explicarlas antes de
      seguir a la etapa 4.

**Criterio de etapa:** paridad demostrada contra la campaña del 30. Con esto el bring-up
está cerrado y el QUBE vuelve a estar al nivel funcional que tenía.

### Resultados medidos — 2026-08-03

| paso | resultado | veredicto |
|---|---|---|
| 3.0 `v_bus` | **15,03 V** — el INA219 mide el riel del motor, no otra cosa. Consistencia interna: 2,75 mV / 0,1 Ω = 27,5 mA reportados | ✅ |
| 3.2 sentido de giro | **IN1/IN2 estaban permutados.** Antes: `p=+60` → posición **subía** (20,57→27,42), que con `MOTOR_DIR=-1` deja el lazo en realimentación positiva. Corregido en el hierro; ahora `p=+60` → posición **baja** (20,48→9,40), 96,1 mA | ✅ tras corregir |
| 3.2b escalón PID | desde reposo 34,0° a setpoint 20°: converge a **21,9–22,1°** sin fuga. Error de régimen **≈2°** | ✅ |
| 3.3 homing | `homing_range` **268,59°**, `homing_fail`=0, centro adoptado | ✅ |
| 3.4 dispersión (5×) | rango 270,00–270,53 (media **270,39°**); tope + **0,17°** = 1 cuenta; tope − **0,53°**; **5/5 exitosos** | ✅ |

#### 3.5 — Paridad contra la campaña del 30 de julio (2 corridas completas)

Datos en `experiments/2026-08-03_bringup_v2/` y `..._run2/`. La línea base de julio **no se
tocó**: `validate.py` escribe en el `data/` de su propia carpeta, así que se copió el script
a carpetas con fecha de hoy en vez de correrlo en su sitio.

| modo | 30-jul | run 1 | run 2 |
|---|---|---|---|
| m0 / m1 / m3 / m6 | PASS | PASS | PASS |
| m2 PID | PASS, sse **4,79°** | PASS, sse 2,06° | PASS, sse 2,08° |
| m4 LQR | PASS, sobrevive 0,3 s | 0,3 s | 0,4–0,5 s |
| **m5 swing-up** | **PASS** `{peak, forced}` | **FAIL** | **FAIL** |
| m7 RL chip | PASS, 9,9–10,0 s | 3,1–10,0 s | 9,9–10,0 s |

**El único veredicto que cambia es m5, y no lo causó el recableado.** La base es del **30**;
el **31** se corrigió el filtro de velocidad de P4, que se reiniciaba al acotar vueltas y
hacía que la compuerta `verySlow` se cumpliera siempre al cruzar la vertical. El registro ya
dejó anotado que con la compuerta honesta `tn=175` no dispara (0/4). Además el criterio que
aprobaba en la base era `{peak, forced}`, y `forced` es el que P1 identificó como espurio.
**Con eso el bring-up queda cerrado: la placa de 30 pines reproduce el comportamiento de la
de 38.**

#### Hallazgos nuevos que van a las etapas siguientes

1. **La deriva del homing de la corrida 1 no se reprodujo.** Run 1: 270,5 → 263 → 261 → 260,
   con 5 fallas. Run 2: **0 fallas, 270,35–270,70 en toda la campaña.** No hay aflojamiento
   mecánico. Diferencia entre corridas: en run 1 el péndulo giró hasta **547°** en m5 rep2 y
   las fallas empiezan exactamente ahí. Hipótesis (n=2): la energía residual del péndulo
   girando falsea la detección de calado. **Antes de un homing, exigir reposo del péndulo.**
2. **`swing_trans_vel = 0.0` exacto, dos veces** (run 2, m5 rep 2 y 3), con
   `trans_alpha` de **−199,16°** y **−223,42°** — fuera de [−180, 180]. Esa es justamente la
   firma que P4 dio por corregida el 31 de julio. Revisar en la etapa 5 antes de tocar
   ganancias.
3. **El sobrepaso de m2 empeoró de forma consistente**: 38,8–42,0% en la base recalculada
   contra **46,7–63,6%** (run 1) y **50,6–86,6%** (run 2), con `sse` bajando de 4,79° a
   ~2,0°. El kick `sk=30` compra régimen y paga sobrepaso. n=6: el barrido de la etapa 4
   tiene que mover `sk` **junto con** `kd`, no `sk` solo.

**P3 no volvió.** Su firma es un calado agrupado ~16° antes del tope real con dispersión de
~20° en el lado positivo; se midió 1 cuenta. `HOMING_PWM_SEEK = 70` sigue haciendo su
trabajo.

> **El paso 3.2, tal como estaba escrito, no detecta la falla.** "Verificar que el brazo va
> en el sentido esperado" con `m1` es insuficiente: **el modo 1 no aplica `MOTOR_DIR`**
> (sólo lo aplican PID `:3134`, LQR `:3261` y swing-up `:3516/3534/3547`). Con IN1/IN2
> permutados el pulso manual se ve perfectamente normal y el lazo cerrado se fuga al tope.
> El homing tampoco lo detecta: aprende el sentido solo en `homing_pwmSign` (`:807`), a
> propósito, para no depender de esta convención — por eso dio 5/5 estando mal cableado.
>
> **Criterio correcto y suficiente:** con `MOTOR_DIR = -1`, un **PWM crudo positivo debe
> BAJAR `position_deg`**. Es una desigualdad, no una impresión visual.

> **Error de procedimiento cometido y corregido.** Se intentó un escalón de `m2` **antes**
> del homing. No es válido: sin homing `offset_deg = 0` y el cero de `position_deg` es
> donde arrancó la placa, así que el límite blando de ±95° queda en un punto arbitrario del
> recorrido — la lectura llegó a −104°, imposible en un mecanismo de ±135°. Además se
> lanzó sin verificar reposo, con el péndulo todavía oscilando de una vuelta manual, y en
> accionamiento directo eso arrastra el brazo. **El sentido de giro se determina en lazo
> abierto (3.2), que no depende del cero; cualquier prueba de lazo cerrado va después del
> homing.**

> Anotar el resultado en `CHANGELOG.md` como verificación en banco de v1.57.1: hoy esa
> entrada dice "compila", no "medido".

---

## Etapa 4 — P6: medir el kick anti-fricción (nunca se midió)

`stiction_err_thresh_deg` 8→2 y `stiction_kick_pwm` 12→30 se cambiaron el 31 de julio,
compilan y **nunca se probaron en banco**. Ambos son configurables por HTTP (`se`, `sk`).

- [ ] **4.1 Reproducir el error de régimen** con los valores viejos, como control:
      `?se=8&sk=12`, escalón de +17 → −20.
      **Criterio:** aparece el error de régimen de ~4,8° documentado. Si no aparece, el
      banco cambió y hay que rehacer la línea base antes de comparar nada.
- [ ] **4.2 Medir con los valores nuevos** `?se=2&sk=30`, mismo escalón.
      **Criterio:** el error de régimen baja **sin** disparar hunting.
- [ ] **4.3 Barrer `kd` ∈ {0,15 · 0,3 · 0,45 · 0,6}** con
      `experiments/2026-07-31_pid/scripts/sweep_pid.py`.
      **Criterio de P6:** sobrepaso < 20% sin degradar `sse` ni disparar hunting.
      El barrido mide `hunting` a propósito: subir el piso del kick puede cambiar un error
      de régimen por un ciclo límite, que es peor.

---

## Etapa 5 — P4: arreglar el camino de entrada al LQR

Las causas H1–H5 están documentadas **por lectura de código, sin verificar en banco**.
Dos de ellas ya quedaron confirmadas en el fuente:

- **H1** — `esp32_qube.ino:3204` hace `return` **antes** de `lqr_prevAlpha = alpha_raw`
  (`:3227`). Durante los 400 ms del catch la referencia queda congelada, así que
  `rawVelForCatch = -(pendPosRaw - lqr_prevAlpha)/dt` divide **todo el desplazamiento
  acumulado** por un `dt` de 2 ms: 30° dan 15.000 °/s y el freno satura contra
  `LQR_CATCH_PWM` (25) casi de inmediato. Peor, la dirección se fija en los primeros
  10 ms (`:3197-3199`) desde esa misma lectura, que con una entrega buena es ruido de un
  conteo de encoder.
- **H4** — `:3243` calcula `vel_alpha_dps = fabsf(velAlpha_ctrl) * RAD_TO_DEG`, pero su
  gemela del híbrido del modo 7 (`:3774`) hace `fabsf(velAlpha_ctrl)` sin el factor.
  **Las dos no pueden estar bien.** Si `velAlpha_ctrl` ya está en °/s, el ×57,3 hace que
  el umbral de 200 se cruce con 3,5 °/s reales y `k4_eff` sea siempre el doble del
  declarado: no es gain scheduling, es una constante oculta.

Orden deliberado: **primero H1 y H4, que son los que hacen que las mediciones
signifiquen algo; después H2/H3, que cambian comportamiento.** No mezclar el arreglo del
catch con un cambio de ganancias en la misma tanda.

- [ ] **5.1 Determinar las unidades reales de `velAlpha_ctrl`** siguiendo su origen hasta
      el estimador. Es lo que decide cuál de las dos líneas está mal. Sin esto, arreglar
      H4 es adivinar.
- [ ] **5.2 Arreglar H1**: actualizar `lqr_prevAlpha` también en la rama del catch, para
      que la velocidad sea una derivada por tick y no un acumulado.
- [ ] **5.3 Arreglar H4** según 5.1. **Rehacer cualquier sintonía previa de `lqr_K4`**:
      su valor efectivo venía siendo el doble.
- [ ] **5.4 Medir con la compuerta honesta.** Con `tn=175`, registrar `swing_trans_*` de
      cada entrega. **Criterio:** que el traspaso dispare y que la calidad de la entrega
      quede registrada, que es lo que hoy no se puede afirmar (0/4 con la compuerta
      corregida de P4).
- [ ] **5.5 Recién entonces evaluar el LQR.** Si con una entrega válida sigue sin
      sostener, ahí sí toca revisar ganancias (H3/H5: las del `.ino` son sintonía manual,
      **no** las que diseña `src/qube_rl/lqr.py` por CARE en unidades SI).

---

## Etapa 6 — P2: cerrar la reserva sobre "sobra energía"

La reformulación de P2 descansa en **2 de 3** corridas con `tr=0` que llegaron a 179,8°,
contra **4 corridas con `tn=175` que toparon en 159,1–160,5°**. La diferencia no parece
ser la energía disponible sino cuánto dura la corrida.

- [ ] **6.1 Repetir el `tr=0` con n ≥ 5**, 30 s de bombeo a `sp=60`, protocolo de reposo
      verificado (homing → esperar por estabilidad de α → `zp=1` → bombear).
      **Criterio:** si ≥ 4 de 5 llegan a wrap (`pend_wraps` +1), la reformulación queda
      firme. Si no, "el bombeo alcanza la vertical" vuelve a ser una hipótesis y hay que
      decirlo así en el registro.
- [ ] **6.2 Medir cuántos ciclos hay dentro de la ventana de captura**, que es la
      pregunta real: la afirmación actual está medida con 30 s de bombeo, no dentro del
      tiempo en que efectivamente hay que capturar.

---

## Criterios de corte

- **No avanzar de etapa con un criterio en rojo.** El historial de este proyecto tiene
  tres casos (P2, P6, P11) donde se construyó sobre una medición que después resultó
  artefacto de instrumentación.
- **Una tanda, un cambio.** Especialmente en la etapa 5.
- **Lo no presenciado se redacta con cautela.** Los resultados que no vea Antonio en
  persona van al registro como lo que son, aunque los logs los respalden.
