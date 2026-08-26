# Migración a ESP32 de 30 pines: bring-up completo y tres bugs de control

**Fecha:** 2026-08-03 · **Firmware:** v1.57.1 → **v1.58.1** · **Repo:** `Qube v2`
(la carpeta `Qube v1` es el respaldo congelado del estado previo a la migración)

Sesión de banco completa: se reemplazó la placa ESP32 por una DevKit V1 de 30 pines, se
recableó, se validó contra la campaña del 30 de julio y —una vez que el hierro estuvo
sano— se encontraron y corrigieron tres defectos de la lógica de control que llevaban
meses enmascarando los diagnósticos de P2 y P4.

---

## 1. Estado al terminar

| | |
|---|---|
| Placa | DOIT ESP32 DevKit V1, **30 pines** — única placa del proyecto |
| Pines | **Sin renumerar.** Los 9 GPIO en uso existen en los 30 pines |
| Firmware | v1.58.1, compila y corre |
| Encoders | 1 cuenta de error en 1535 (servo), 0 en 2048 (péndulo) |
| INA219 | detecta en 0x40, mide 15,03 V del riel del motor |
| Homing | 6/6, rango 270,176 en las seis, dispersión de topes **0,000°** |
| Swing-up → LQR | entrega a **173–179°** con `E/E*` ≈ **1,00**; supervivencia hasta **3,33 s** |

**Documentos que se tocaron:** `docs/PLAN_TRABAJO_V2.md` (protocolo por etapas, con los
resultados medidos), `docs/REGISTRO_PROBLEMAS.md` (P14 nuevo, P4 actualizado),
`docs/hardware/pinout.md` + `pinout_esp32_30.png` (nuevo), `CHANGELOG.md` (v1.57.1 → 1.58.1).

---

## 2. Lo que se aprendió del recableado

**Tres fallas, dos de ellas inducidas por el orden del header.** La placa de 30 pines baja
`D27` antes que `D26`, y `D21` está tres posiciones antes que `D22` con `RX0`/`TX0` en el
medio. Una cinta recta permuta IN1/IN2, y es fácil correrse en el I2C.

| falla | síntoma | cómo se encontró |
|---|---|---|
| **SDA/SCL permutados** | `ina_ok=false`, scan I2C vacío | Permutar los pines **en firmware**, reflashear y escanear: apareció en 0x40 al instante |
| **IN1/IN2 permutados** | El lazo cerrado se fugaba al tope | Observación física de Antonio, contrastada contra `MOTOR_DIR = -1` |
| Encoders / J4 | — | Estaban bien: 1 cuenta de error en 1535 |

**El multímetro no podía encontrar la del I2C.** Medir 3,3 V en ambas líneas es compatible
con el cruce, con un cable cortado y con todo bien a la vez: los pull-ups internos de la
ESP32 de un lado y los del breakout del INA219 del otro dejan las dos líneas en alto pase lo
que pase. Un nivel alto no prueba continuidad ni orden.

**La de IN1/IN2 sobrevivió a mi propia verificación**, y vale la pena entender por qué: el
**modo 1 manual no aplica `MOTOR_DIR`** (sólo lo aplican PID `:3134`, LQR `:3261` y swing-up
`:3516/3534/3547`). Con IN1/IN2 permutados el pulso manual se ve perfectamente normal. El
homing tampoco lo detecta: aprende el sentido solo en `homing_pwmSign` (`:807`), a
propósito, para no depender de esta convención — dio 5/5 estando mal cableado.

> **Criterio correcto y suficiente:** con `MOTOR_DIR = -1`, un **PWM crudo positivo debe
> BAJAR `position_deg`**. Es una desigualdad, no una impresión visual.

---

## 3. Los tres bugs de control

### P14 (v1.57.2) — el que desbloqueó todo lo demás

Las cuatro compuertas de traspaso comparaban `fabsf(pendPos)` contra sus umbrales **sin
acotar a [−180, 180]**. Con el péndulo pasado de vuelta, `|pendPos|` supera cualquier
umbral hasta 178 estando lejos de la vertical. Medido: un traspaso con `pendPos = −223,42`
(ángulo real **136,6°**, a 43° de la vertical, `E/E*` = 0,86) que no debió ocurrir. Y en las
mismas repeticiones, `swing_trans_vel = 0,00` exacto: las dos mitades del criterio se
cumplían espuriamente a la vez.

**Efecto del fix:** entregas de 136–161° → **170,7 / 179,3 / 177,0°**, `E/E*` de 0,86 →
**0,994–1,002**. Una de ellas a **0,7° de la vertical**.

### P4/H1 y H4 (v1.58.1)

- **H1:** la rama del catch termina en `return`, así que se saltaba la actualización de
  `lqr_prevAlpha`. Durante los 400 ms de `LQR_CATCH_MS` la referencia quedaba congelada y
  el "freno proporcional a la velocidad" dividía el desplazamiento **acumulado** por un tick
  de 2 ms. La dirección se fijaba en los primeros 10 ms desde esa misma lectura, que con una
  entrega buena es ruido de una cuenta de encoder.
- **H4:** sobraba un `RAD_TO_DEG`. `velAlpha_ctrl` ya está en deg/s en el modo 4. El umbral
  de 200 se cruzaba con **3,5 °/s reales** y `k4_eff` era el **doble** del declarado casi
  siempre. El gemelo del modo 7 (`:3828`) ya lo hacía bien: las dos líneas no podían estar
  bien a la vez.

**Efecto:** supervivencia del LQR **0,3 s → 0,48 / 0,55 / 3,33 s**.

### Homing con frenado de aproximación (v1.58.0)

Seek a 70 hasta 8° del tope, después 55. Los 8° son deliberados: el punto duro de P3 está
16° antes del tope, y bajar la potencia antes reintroduce exactamente la falla de v1.53.2.
Dispersión de topes de 1–3 cuentas a **0,000° en 6 corridas**.

---

## 4. Por dónde seguir

**H2 es el cuello ahora, y los datos lo señalan sin ambigüedad.** Las supervivencias de 0,48
y 0,55 s son los 400 ms de `LQR_CATCH_MS` **más 80–150 ms de LQR real**: en esos ciclos el
controlador apenas alcanzó a correr. El ciclo que sobrevivió 3,33 s son 0,4 s de catch más
2,9 s de LQR sosteniendo de verdad. Hay que correr el LQR durante el catch en vez de sólo
frenar, o acortar la ventana.

Después, en orden:

1. **H3** — con `LQR_PWM_MAX = 70` y `lqr_K2 = 22`, la salida satura con 3,2° de error: el
   LQR se comporta como un relé. Va junto con H2, son los dos cambios de comportamiento.
2. **Rehacer la sintonía de `lqr_K4`** — su valor efectivo venía siendo el doble. Se puede
   barrer por HTTP con `lqr4=` sin reflashear.
3. **P6 / etapa 4** — el kick anti-fricción bajó `sse` de 4,79° a ~2,0° pero **empeoró el
   sobrepaso**: 38,8–42,0% → 46,7–86,6% (n=6). Barrer `sk` **junto con** `kd`, no `sk` solo.
4. **P2 / etapa 6** — 2 de 5 ciclos no traspasaron. Ahora que la compuerta es honesta, medir
   cuántos ciclos hay dentro de la ventana de captura.

---

## 5. Trampas de método, para no repetirlas

- **`validate.py` escribe en el `data/` de su propia carpeta.** Correrlo en su sitio habría
  sobrescrito los 24 CSV y el `verdicts.json` del 30 de julio, que es la referencia. Se copió
  el script a carpetas con fecha (`2026-08-03_bringup_v2`, `..._run2`).
- **Una tanda, un cambio.** P14 y el frenado del homing se flashearon y midieron por
  separado a propósito; juntos no habrían sido atribuibles.
- **Reposo verificado antes de medir.** Un escalón de `m2` lanzado con el péndulo todavía
  oscilando dio una traza inservible, y encima se corrió **antes** del homing: sin homing
  `offset_deg = 0` y el límite blando de ±95° queda en un punto arbitrario del recorrido.
- **La referencia física manda.** "Girá media vuelta a ojo" dio 590 cuentas y pareció 60% de
  pérdida de pulsos. No lo era: tope a tope (270° medidos) dio 1535 de 1536.
- **El puerto serie reinicia la placa** y tira al PC del SoftAP; Windows no vuelve solo.
  Reconectar con `netsh wlan connect name="QUBE-ESP32"`.
- **En PowerShell usar `Invoke-RestMethod`, no `curl`** (en 5.1 `curl` es alias de
  `Invoke-WebRequest` y devuelve un objeto). Los ejemplos de `docs/http_api.md` son bash.

---

## 6. Lo que NO está medido

Honestidad sobre los límites de esta sesión:

- **La reducción de la fuerza de impacto del homing no se cuantificó.** El muestreo de
  corriente por HTTP va a ~2,5 Hz y el golpe dura milisegundos. Lo que sí está medido: la
  aproximación ocurre a 55 en vez de 70 y la medición se volvió perfectamente repetible.
  Que el golpe se redujo es una apreciación de Antonio en el banco, no una medición.
- **La supervivencia del LQR tiene n=3** (5 ciclos, 2 sin traspaso). El 3,33 s es un solo
  punto.
- **La correlación "entrega más rápida sobrevive más"** (16 °/s → 0,48 s; 109 °/s → 3,33 s)
  es contraintuitiva y tiene 3 puntos. No construir encima sin repetir.
- **El orden de filas del pinout** que dibuja `pinout_esp32_30.png` es el documentado, no
  verificado contra el serigrafiado de esta placa en particular.
