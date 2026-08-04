# Plan de trabajo — dejar funcionales los 8 modos

**Objetivo:** que cada modo del firmware haga lo que dice hacer, con un criterio medible.
No es un plan de optimización del balanceo: el balanceo es *uno* de los ocho, y hoy se
lleva toda la atención mientras otros tres nunca se verificaron de verdad.

Iniciado 2026-08-04, tras el diagnóstico sim2real que dejó abiertos [P19](REGISTRO_PROBLEMAS.md#p19) y [P20](REGISTRO_PROBLEMAS.md#p20).

## Convenciones

Las mismas de `PLAN_TRABAJO_V2.md`: SoftAP `http://192.168.4.1`, `Invoke-RestMethod` y no
`curl`, nunca `pio device monitor`, y el paro (`?x=1`) en una consola aparte antes de
energizar.

---

## Estado de partida

| modo | qué es | estado real hoy | qué falta para "funcional" |
|---|---|---|---|
| 0 | STOP | ✅ funcional | — |
| 1 | PWM manual | ✅ funcional | — |
| 2 | PID servo | ⚠️ funciona, mal sintonizado | confirmar `kd` y cambiar el default |
| 3 | Homing | ✅ funcional | (P8: no siempre deja el brazo centrado) |
| 4 | LQR | ❌ **sostiene 0,5 s** | rehacer ganancias (P4 → H3/H5) |
| 5 | Swing-up | ⚠️ entrega bien, se trunca | P12: el brazo llega al tope |
| 6 | Deep RL (HTTP) | ❌ **14 Hz, no evalúa nada** | P20: definir para qué sirve |
| 7 | Deep RL (chip) | ❓ **nunca verificado** | criterio propio + medición |

**Lo que hay que asumir de entrada:** el criterio actual de `validate.py` para m6 y m7 es
*"el motor se movió"* (`pwm_std > 5`). Eso no es funcionalidad, es señal de vida. Los
"9,9–10,0 s" que aparecen en la campaña de bring-up para m7 son **la duración de la
ventana de grabación**, no un tiempo de balanceo. Cualquier plan que arranque creyendo
que m7 anda parte de una lectura equivocada.

---

## Etapa 1 — m2 PID: cerrar lo que ya está medido

Lo más barato del plan: la medición ya existe, falta consolidarla.

- [ ] **1.1** Repetir el escalón +17 → −20 con `kd=0,45` hasta **n ≥ 4**, ventana de 14 s
      (la ventana **se declara**: con 5 s el `sse` da 7,7–15,9° y con 14 s da 2,7°).
      **Criterio:** sobrepaso < 20% sin hunting y sin degradar `sse`.
- [ ] **1.2** Si 1.1 confirma, **cambiar el default de `kd` en el `.ino`** de 0,15 a 0,45.
      Hoy el valor bueno sólo existe como parámetro HTTP: quien flashee limpio se lleva el
      malo.
- [ ] **1.3** Re-medir con el default nuevo para que el `CHANGELOG` diga "medido" y no
      "compila".

**Criterio de etapa:** m2 pasa de "funciona mal sintonizado" a "funcional".

---

## Etapa 2 — m7 Deep RL en chip: darle un criterio y medirlo

El modo con menos evidencia de los ocho, y el de mayor leverage: **es el único camino que
puede evaluar una política de 50 Hz**, porque no tiene HTTP en el lazo (P20).

- [ ] **2.1 Definir el criterio.** Hoy no existe. Propuesta: *desde péndulo colgando, con
      swing-up, el modo 7 mantiene |α − 180°| < 15° durante ≥ 3 s en 3 de 5 intentos*.
      Anotarlo **antes** de medir.
- [ ] **2.2 Verificar qué política tiene flasheada.** `policy_weights.h` viene de un
      `export_rltools` de fecha desconocida. Sin saber qué modelo es, el resultado no es
      atribuible. **Criterio:** dejar registrado modelo, fecha y hash.
- [ ] **2.3 Exportar `r7_ft_fr100_s0_best.zip`** (el mejor candidato de junio, y el que
      sostiene 9,43 s en la sim corregida) y correr `verify_export.py`.
      **Criterio:** la salida del header coincide con la del `.zip` sobre las mismas
      observaciones. Es lo que separa "la política falló" de "la exportación falló".
- [ ] **2.4 Flashear y medir contra 2.1**, con n = 5.
- [ ] **2.5 Medir la tasa real del lazo en m7** (`loop_dt_max_us`, `loop_overruns`).
      **Criterio:** que la inferencia on-chip no rompa los 500 Hz del lazo. Si los rompe,
      m7 tiene un problema propio, distinto de P20.

**Criterio de etapa:** m7 tiene un veredicto medido contra un criterio escrito antes, sea
cual sea. Un FAIL documentado también cierra la etapa.

---

## Etapa 3 — m6 Deep RL por HTTP: decidir para qué sirve

**No se puede "arreglar" a 50 Hz**: 69,9 ms por paso son dos viajes de ida y vuelta sobre
WiFi. Pero el modo no es inútil — hay que redefinirlo con honestidad.

- [ ] **3.1 Arreglar [P19](REGISTRO_PROBLEMAS.md#p19) primero**, que es un defecto de
      seguridad de datos y no de rendimiento: que `/rl_state` exponga **en qué modo se
      calculó** y **hace cuántos ms**, y que `qube_real.py` **falle ruidosamente** ante
      lecturas repetidas o `mode != 6`. Sin esto, cualquier medición de m6 puede ser un
      episodio muerto disfrazado.
      **Criterio:** forzar el corte (llevar el brazo más allá de 95° en m6) y verificar que
      el cliente **aborta** en vez de seguir.
- [ ] **3.2 Unificar `rl_cmd` + `/rl_state` en una respuesta.** De dos viajes a uno:
      ~35 ms, ~28 Hz. **Criterio:** medir, no suponer.
- [ ] **3.3 Declarar la frecuencia alcanzable como parte del contrato.** `control_freq`
      tiene que verificarse contra la tasa real **antes** de una campaña. Un chequeo de
      arranque que compare lo pedido con lo medido y avise.
- [ ] **3.4 Redefinir m6** como lo que puede ser: banco de pruebas de políticas de baja
      frecuencia, telemetría y control manual desde el PC — **no** como despliegue de las
      políticas de 50 Hz. Actualizar la tabla de modos y `validate.py`.

**Criterio de etapa:** m6 tiene una definición que se sostiene, y una medición de m6 no
puede volver a producir datos falsos en silencio.

---

## Etapa 4 — m5 Swing-up: P12, el único `ABIERTO` bloqueante

El swing-up **ya entrega bien** desde P14 (α 170,7–179,3°, `E/E*` ≈ 1,00). Lo que falla es
que el brazo llega al límite blando y trunca el intento.

- [ ] **4.1 Cuantificar cuánto trunca hoy**, con el firmware actual y P14/P18 ya
      corregidos. El dato histórico (5 de 8 truncados) es de **antes** de esas
      correcciones. **Criterio:** saber si P12 sigue siendo bloqueante antes de gastar en
      arreglarlo.
- [ ] **4.2 Si sigue**, atacar por reducción de excursión del brazo y no por más recorrido:
      subir `SERVO_HARD_LIMIT_DEG` a 105 **ya se probó el 2026-07-31 y se revirtió sin
      aportar** — el brazo simplemente usó el espacio extra. **No repetir ese
      experimento.**

**Criterio de etapa:** o P12 deja de ser bloqueante, o queda cuantificado con el firmware
actual.

---

## Etapa 5 — m4 LQR: rehacer las ganancias

El más roto de los ocho: sostiene ~0,5 s. La campaña del 2026-08-04 ya descartó las
causas de entrada.

**Lo que ya NO hay que investigar:**
- **H2 está refutada**: acortar el catch **empeora** (0,567 → 0,461 → 0,406 s).
- **La calidad de la entrega no explica nada**: `corr(α de entrega, supervivencia)
  ≈ −0,09` con n = 19. Hubo entregas de 179,1° con `E/E*` = 1,002 que aguantaron 0,582 s.

**Queda H3 y H5**, que son la misma familia: las ganancias.

- [ ] **5.1 H3 — verificar que el LQR no es un relé.** Con `LQR_PWM_MAX = 70` y
      `lqr_K2 = 22`, la salida satura con **3,2°** de error (1,3° en la banda very-near).
      Fuera de esa ventana la salida es ±70 constante. **Criterio:** medir la fracción de
      tiempo saturado durante un intento de balanceo. Si es alta, no se está evaluando un
      LQR.
- [ ] **5.2 H5 — usar las ganancias diseñadas.** `src/qube_rl/lqr.py` resuelve el CARE en
      unidades SI; las del `.ino` son sintonía manual en otra escala. **No es que las
      diseñadas estén sin validar: es que no son las que corren.** Convertirlas a las
      unidades del firmware y compararlas contra las actuales.
- [ ] **5.3 A/B por HTTP** (`lqr1`–`lqr4`, `lqr2n`, `lqr4n`…), con `cg=1` fijo —
      H6 se sostuvo y conviene no volver a medir con el defecto puesto.
      **Criterio:** superar de forma reproducible los ~0,6 s actuales.
- [ ] **5.4 Rehacer la sintonía de `lqr_K4`**: su valor efectivo venía siendo **el doble**
      del declarado hasta que se corrigió H4 el 2026-08-03. Cualquier ajuste anterior a esa
      fecha no es válido.

**Criterio de etapa:** el LQR sostiene ≥ 3 s, o queda demostrado que con las ganancias
diseñadas tampoco, lo que movería la sospecha al modelo.

---

## Etapa 6 — Cerrar el default de `cg` y la limpieza de P4

- [ ] **6.1** Decidir el default de `cg` (periodo de gracia del centering). Se sostuvo en
      medianas (+15% y +19%), pero con n = 4 y dispersión de factor 33. **Criterio:**
      n ≥ 8 antes de cambiar el default, o dejarlo en 0 y documentar por qué.
- [ ] **6.2** Limpiar `lqr_aliveMs` al entrar al modo 5, para que no haya que condicionar
      por "¿hubo traspaso en este intento?". Es un filo que ya hizo tropezar un análisis.

---

## Orden y por qué

1. **Etapa 1 (m2)** primero: está medido, es barato y cierra un modo entero.
2. **Etapa 2 (m7)** después: máximo leverage. Es el único camino de despliegue que no
   choca con P20, y hoy no sabemos si funciona.
3. **Etapa 3 (m6)**, en particular 3.1: es un defecto que **produce datos falsos**. Cuanto
   más se tarde, más mediciones quedan bajo sospecha.
4. **Etapa 4 (m5)** antes que la 5: P12 es el único `ABIERTO` bloqueante, y 4.1 puede
   cerrarlo gratis si las correcciones de agosto ya lo resolvieron.
5. **Etapa 5 (m4)** al final: es la más cara y la que más veces se atacó con hipótesis
   equivocadas. Ahora al menos las candidatas están acotadas a las ganancias.

## Criterios de corte

- **No avanzar de etapa con un criterio en rojo.**
- **Una tanda, un cambio.**
- **El criterio se escribe antes de medir.** Este proyecto ya tiene cuatro casos (P2, P6,
  P11, y ahora P19/P20) donde se construyó sobre una medición que era artefacto de
  instrumentación.
- **Lo no presenciado se redacta con cautela**, aunque los logs lo respalden.
