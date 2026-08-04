# m5 — swing-up medido a 500 Hz, separando bombeo de LQR

> ## ⚠ CORRECCIÓN (misma sesión, más abajo en §4)
>
> Las secciones 1–3 están medidas **con la referencia angular del péndulo corrida**, un
> defecto que se descubrió después (P22). Con la referencia corregida:
>
> - **El §1 no vale como refutación de P12**: el brazo llega a **94,9°** en bombeo, no a
>   68°. P12 sigue abierto.
> - **El §3 es una hipótesis FALSA**: la energía residual del homing no era la variable.
>
> Se conservan porque el recorrido importa: las dos lecturas equivocadas vinieron de
> medir sobre una referencia rota, que es el patrón dominante de esta sesión.

Dos resultados: **P12 estaba mal atribuido**, y el swing-up depende de una condición
inicial que nadie estaba controlando.

## 1. P12 no es un problema del swing-up

Las campañas previas reportaban `hit_servo_limit` mirando el `theta` máximo del episodio
**completo**, que incluye lo que pasa después del traspaso. Y [P4](../../docs/REGISTRO_PROBLEMAS.md#p4)
tiene documentado que el LQR se fuga al tope. Con eso, **un tope tocado por el LQR se le
cargaba al swing-up**.

El DAQ trae `mode` por muestra, así que la separación es exacta y a 500 Hz:

| | fase de bombeo (m5) | tras el traspaso (m4) |
|---|---|---|
| θ máx, corrida 1 (`sp=60`) | 57,2 · 58,2 · 59,8 · 64,3° | 94,2 · 94,3 · 94,4 · 94,7° |
| θ máx, corrida 2 (`sp=60`) | 12,5 · 54,6 · 65,4 · 68,3° | 94,3 · 94,5 · 94,7° |
| tope superado | **0 de 8** | 0 de 8 |

**Durante el bombeo el brazo nunca pasó de 68,3°, con el límite blando en 95°: quedan
más de 26° de margen sin usar.** El histórico de "5 de 8 swing-ups truncados" es anterior
a P10, P14 y P18.

Consecuencia práctica: **la razón por la que no se subía `swingupPwmMax` ya no aplica.**
El comentario del firmware dice que pedir más referencia "lo llevaría a auto-matarse a
mitad del bombeo"; medido, no llega ni cerca.

## 2. Pero subir el PWM de bombeo no ayuda

| `sp` | picos \|α\| | θ máx en bombeo | traspasos |
|---|---|---|---|
| 60 | 160,1 · 162,1 · 163,1 · 171,2 | 57–64° | 4/4 |
| 60 (repetido) | 107,4 · 163,7 · 173,1 · 179,6 | 12–68° | 3/4 |
| **70** | **93,5 · 148,0 · 160,8 · 179,8** | 12–**94,2°** | 2/4 |

`sp=70` **empeora**: la dispersión se dispara y aparece el único caso en que el brazo sí
se acerca al tope (94,2°). La preocupación histórica era real, pero recién a partir de 70.

## 3. El hallazgo: el swing-up no bombea desde cero

Mirando el tiempo que cada intento pasa en modo 5:

| rep | pico | θ en bombeo | **tiempo en m5** | cortes por techo |
|---|---|---|---|---|
| 1 | 179,6° | 54,6° | **1,3 s** | 25 |
| 2 | **107,4°** | **12,5°** | **17,9 s** | **0** |
| 3 | 163,7° | 65,4° | 1,0 s | 0 |
| 4 | 173,1° | 68,3° | 1,5 s | 39 |

**Los intentos exitosos resuelven el swing-up en 1,0–1,5 segundos.** Eso es demasiado
rápido para partir del péndulo colgando en reposo: arrancan con **energía residual**, la
que deja el homing al golpear el brazo contra los dos topes. El que falló bombeó los
17,9 s completos sin llegar.

O sea: **m5 no bombea desde cero — remata un péndulo que el homing ya puso en
movimiento.** Cuando esa energía no aparece, el bombeo resonante no engancha.

Eso explica la dispersión de `sp=70` sin necesidad de invocar el PWM: la variable
dominante no es la potencia de bombeo sino **la condición inicial, que hoy nadie
controla y que depende de un efecto lateral del homing**.

> **Ojo con el protocolo:** `wait_for_rest()` espera reposo **antes** del homing, no
> después. Entre el homing y el `m=5` no hay ninguna espera, así que la energía residual
> entra sin registrarse. Todas las campañas de swing-up de este proyecto comparten ese
> protocolo.

## Cómo seguir

1. **Medir la condición inicial**, que hoy es una variable oculta: registrar α y α̇ en el
   instante del `m=5`. Sin eso, ningún barrido de `sp` o `ke` es atribuible.
2. **Decidir el protocolo a propósito**, y declararlo: o esperar reposo *después* del
   homing (swing-up honesto desde cero), o aceptar la energía residual como parte del
   arranque (y entonces controlarla, no sufrirla). Hoy es un accidente.
3. Recién con la condición inicial fija tiene sentido volver a `sp`, `ke` o el techo de
   energía.

## Estado del criterio

| criterio | resultado |
|---|---|
| 1. entrega con \|α\| ≥ 165 | 1/4 y 2/4 — **FAIL**, pero ver nota |
| 2. E/E* en [0,95, 1,05] | 4/4 y 3/4 |
| 3. sin tocar el tope en bombeo | **8/8 PASS** |

> **Nota sobre el criterio 1.** El umbral de 165° que fijé es **más estricto que el del
> propio firmware**, cuyo `SWINGUP_TRANS_NEAR` es 155. Las entregas medidas (159–180°,
> `E/E*` 0,968–0,997) están dentro de lo que el firmware considera válido, y traspasan.
> El criterio se conserva como está escrito —no se re-escribe después de ver los datos—
> pero la lectura honesta es que **m5 entrega dentro de su diseño**, y lo que falta es
> fijar la condición inicial, no más energía.

## Errores de este experimento

`m5_daq.py` escribía siempre a `m5.json` y `m5_r*.csv` sin etiquetar por `sp`, así que la
primera corrida de `sp=60` **fue pisada** por la de `sp=70`. Los resúmenes se conservan
(quedaron en consola) pero las trazas crudas de esa tanda se perdieron. Corregido: los
archivos llevan `sp` en el nombre.

---

## 4. Lo que realmente pasaba: la referencia del péndulo deriva

Al agregar la espera de reposo **después** del homing (`--settle`) para probar la
hipótesis del §3, apareció el dato que la refuta y explica todo:

| rep | α inicial | resultado |
|---|---|---|
| 1 | **82,62°** | pico 176,1°, traspasa en 1,3 s |
| 2 | **97,38°** | pico 180,0°, traspasa en 1,3 s |
| 3 | **−264,02°** | **pico 96,0°, bombea 18,1 s sin llegar** |
| 4 | **91,06°** | pico 175,1°, traspasa en 1,6 s |

Un péndulo colgando y en reposo **verificado** —la lectura no cambia en 1,2 s— debe leer
0°. Leía 82–97°, y una vez −264°, fuera del rango físico. **No es movimiento: es la
referencia corrida, y corrida distinto en cada intento.** `pend_wraps` sube en cada
intento (4 → 5 → 6 → 6) y la deriva lo acompaña.

### El arreglo

`zp=1` (`zeroPendulumHere()`) ya existía en el firmware y **el protocolo nunca lo
llamaba**. Con reposo verificado antes, `--zero`:

| condición (`sp=60`) | picos \|α\| | θ en bombeo | fallos totales |
|---|---|---|---|
| protocolo actual | 107,4–179,6° | 12–68° | 1/4 |
| + reposo tras homing | 96,0–180,0° | 12–67° | 1/4 |
| **+ `zp=1`** | **159,4–179,6°** | **64,1–94,9°** | **0/5** |

**Elimina el modo de fallo catastrófico**: 5 de 5 traspasan, contra 1 de cada 4 que antes
bombeaba 18 s sin llegar.

### Las dos lecturas que esto corrige

**§1 — P12 no queda refutado.** Aquella medición (θ ≤ 68° en bombeo) se hizo con la
referencia corrida, o sea con el bombeo debilitado. Con la referencia sana el brazo usa
**64–95°** y uno llegó a 94,9°, a una décima del tope. **P12 vuelve a `ABIERTO`.**

**§3 — la energía residual no era la variable.** Esperando reposo tras el homing, los
intentos exitosos siguen resolviendo en 1,3–1,6 s y el fallo aparece igual (1 de 4 en las
dos condiciones). La hipótesis queda refutada.

### Qué falta para dejar m5 listo

1. **Llevar `zp=1` al protocolo canónico**, o mejor al firmware: que `setMode(5)`
   exija reposo y re-establezca la referencia, en vez de depender de que cada script se
   acuerde. Hoy el arreglo vive sólo en este experimento.
2. **Re-medir P12 con el protocolo corregido.** Con el bombeo sano el brazo llega al
   tope, y ésa es la pregunta original.
3. Recién entonces barrer `sp` o `ke`. Todo barrido anterior a esta corrección se midió
   sobre una referencia que derivaba, así que **no es atribuible**.
