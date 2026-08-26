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
| 4 | LQR | ❌ **sostiene 0,5 s** | rehacer ganancias (P4 → H3/H5) — **el bloqueante del proyecto** |
| 5 | Swing-up | ✅ entrega repetible dentro de su diseño | nada bloqueante (ver Etapa 4, cerrada) |
| 6 | Deep RL (HTTP) | ❌ **14 Hz, no evalúa nada** | P20: definir para qué sirve |
| 7 | Deep RL (chip) | ❓ **nunca verificado** | criterio propio + medición |

**Lo que hay que asumir de entrada:** el criterio actual de `validate.py` para m6 y m7 es
*"el motor se movió"* (`pwm_std > 5`). Eso no es funcionalidad, es señal de vida. Los
"9,9–10,0 s" que aparecen en la campaña de bring-up para m7 son **la duración de la
ventana de grabación**, no un tiempo de balanceo. Cualquier plan que arranque creyendo
que m7 anda parte de una lectura equivocada.

---

## Etapa 1 — m2 PID ✅ COMPLETADA (2026-08-04)

> **Esta etapa estaba casi hecha cuando se escribió el plan.** Se redactó desde la fila
> de P6 en el registro, que decía "falta confirmar y cambiar el default" y estaba
> desactualizada. Lección para las etapas siguientes: **verificar el estado en el código
> y en los datos, no en la tabla resumen.**

- [x] **1.1** Ya estaba medido con **n = 5** por nivel (`sweep_kd.json` +
      `sweep_kd_confirm.json`): `kd=0,15` → 37,6–39,4%; `kd=0,45` → **7,9–8,8%**, cero
      cruces, `sse` solapado. Criterio cumplido.
- [x] **1.2** El default **ya era 0,45** desde v1.58.0 (`esp32_qube.ino:314`). Verificado
      además que `Preferences` guarda **sólo credenciales WiFi**, así que NVS no pisa las
      ganancias: el valor compilado es el que corre.
- [x] **1.3** Regresión sobre v1.58.5, n=3: **sobrepaso 1,2%** (0,0 · 1,2 · 3,0), 0
      hunting, 500 Hz sin pérdidas.

**m2 es funcional.**

### Hallazgo lateral: el banco derivó durante la sesión

La regresión no reprodujo los números absolutos del 3 de agosto, así que se corrió el
control con `kd=0,15`:

| `kd` | sobrepaso 3-ago | hoy | `sse` 3-ago | hoy |
|---|---|---|---|---|
| 0,15 | 39,3% | 34,7% | 2,58–2,88° | 3,36° |
| 0,45 | 8,4% | 1,2% | 2,65–3,03° | 4,01° |

**Se movió toda la curva**, en los dos niveles y en el mismo sentido: menos sobrepaso,
más error de régimen. Es la firma de **más fricción**, coherente con que el brazo trabajó
mucho ese día (campaña de P4, spin-down, tres corridas sim2real). El efecto de `kd`
sobrevive intacto.

> **Consecuencia para todas las etapas siguientes:** las comparaciones **absolutas**
> contra campañas de otro día no son válidas sin re-medir el control. El control barato
> es correr el punto viejo junto al nuevo, no confiar en la tabla histórica.

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

## Etapa 4 — m5 Swing-up ✅ COMPLETADA (2026-08-04/05)

> Se redactó cuando P12 era "el único `ABIERTO` bloqueante". Ya no lo es: la campaña del
> 2026-08-04 lo cerró como `NO ES DEFECTO`. **El bloqueante pasó a [P4](REGISTRO_PROBLEMAS.md#p4)**,
> o sea a la Etapa 5.

- [x] **4.1 Cuantificado** (`experiments/2026-08-04_m5_swingup/`, v1.58.8, n=10): θ durante
      el bombeo va de 49,2° a 80,1° (mediana 70,0) contra un tope de 95 — **14,9° de margen,
      0/10 lo tocan**. Los diez lo rozan **después** del traspaso (94,0–94,8°), que es P4.
      P12 pasa a `NO ES DEFECTO`, esta vez con la referencia de α correcta y n=10.
- [x] **4.2 No aplica**: P12 no sigue.

El veredicto de m5 contra su criterio, escrito antes de medir: **10/10 traspasan**, `E/E*`
en 0,955–1,001 (PASS), 0/10 tocan el tope en bombeo (PASS), y 5/10 entregan con |α| ≥ 165
(FAIL). El criterio 1 es más estricto que el umbral del propio firmware
(`SWINGUP_TRANS_NEAR` = 155) y las diez entregas caen entre 156,4° y 179,8°: **m5 entrega
dentro de su diseño de forma repetible**.

### Por qué el criterio 1 no se cierra subiendo un parámetro

Medido el 2026-08-05 sobre esas mismas trazas (`m5_pwm_sat.py`): el bombeo tiene el **PWM
en su techo el 92,5% del tiempo** (86,7–94,1%). Eso confirma [P11](REGISTRO_PROBLEMAS.md#p11),
que hasta ahora era una deducción por lectura, y descarta los mandos que parecían
candidatos: `?pr=` agranda un error que ya satura, y `?ke=` además está roto
([P23](REGISTRO_PROBLEMAS.md#p23)). La atenuación por posición tampoco es el cuello (techo
efectivo medio 58,1–59,1 sobre 60, con el brazo trabajando centrado).

**Queda un solo mando: `sp`, el techo mismo.** Su barrido histórico (50 → 70, óptimo en 60)
es **anterior a P22**, o sea que se midió sobre la referencia de α que derivaba — el mismo
motivo por el que no son atribuibles los de `ke` y `bt`. Rehacerlo es la única vía de
parámetro que queda, con la tensión de que el margen al tope bajó de 26,7° a 14,9°.

Si el barrido no alcanza los 165°, la conclusión honesta es que **la energía del bombeo
está limitada por par y no por sintonía**, y las salidas son las tres de
[P2](REGISTRO_PROBLEMAS.md#p2): control por par, menos fricción, o aceptar el umbral de 155
que el firmware ya usa.

**Criterio de etapa: cumplido.** P12 dejó de ser bloqueante y quedó cuantificado con el
firmware actual.

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
