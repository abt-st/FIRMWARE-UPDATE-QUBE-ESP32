# P4: cinco hipótesis descartadas, y el defecto estaba en el fierro

**Fecha:** 2026-08-05 · **Firmware:** v1.58.8 → **v1.58.10** · **Repo:** `Qube v2`, rama `DRL_IMP`
**Corridas de banco:** ~90 en cuatro campañas · **Nada commiteado**

Jornada dedicada a averiguar por qué el LQR no sostiene el péndulo. Se eliminaron cinco de
seis hipótesis con medición y criterio pre-registrado. Al cierre, un ensayo de decaimiento
libre mostró que **el pivote del péndulo desarrolló fricción seca 13,4 veces mayor que el
par viscoso**, lo que da una explicación única a la jornada entera y deja el banco fuera de
servicio como instrumento de control.

---

## 1. Estado al terminar

| | |
|---|---|
| Placa | modo 0, `v_bus` 15,0 V, `ina_ok` true, defaults compilados restaurados |
| Firmware | **v1.58.10** — `?lpm=` nuevo, tres espejos del LQR en `/state`, tres comentarios corregidos |
| **Banco** | **NO SIRVE COMO INSTRUMENTO.** Ver P24 |
| Tesis | §5.11 nueva, 128 páginas, compila limpio |
| Git | **sin commitear**: firmware, 3 documentos, 7 scripts, ~90 CSV |

**Lo primero al retomar: inspección mecánica del pivote.** Todo lo demás está bloqueado.

---

## 2. El hallazgo de cierre: P24

Suelta manual con el brazo sujeto a mano y motor apagado. Desde ~19° el péndulo baja al
reposo **sin cruzarlo ni una vez**, con mesetas de hasta **4,25 s sin cambiar un conteo**.

Encoder descartado: barrido manual de 30 s dio 2240° recorridos, 9712 valores, meseta máxima
0,12 s y ninguna sobre 0,5 s. La lectura sigue el movimiento; se traba el péndulo.

| | |
|---|---|
| par seco retenido (quieto a 4,75°) | **1,26e-3 N·m** |
| par viscoso máx. a 50° y 2,28 Hz | 9,4e-5 N·m |
| razón | **13,4×** |

Coulomb de esa magnitud come **19° por ciclo**: desde 19° se detiene en menos de un ciclo
(~0,4 s). Es exactamente lo observado — el modelo predice la medición.

**El 2026-08-04 el mismo péndulo dio decaimiento viscoso limpio** (sueltas de 64° y 43°
coincidiendo al 0,4%, lo que exige muchos ciclos). La planta cambió entre ambas fechas.

**Reserva: n=1**, al final de ~90 corridas, sin medición equivalente con banco fresco. No se
sabe si apareció hoy, si es reversible, ni el origen.

---

## 3. Por qué esto reordena la jornada

Da explicación única a tres cosas que se venían tratando por separado:

1. El bombeo necesitando el triple de tiempo.
2. El swing-up muriendo tras ~12 corridas (el "ciclo de trabajo").
3. **Por qué cinco hipótesis sobre el controlador cayeron una tras otra.** El diseño por
   CARE supone amortiguamiento viscoso; con 1,26e-3 N·m de fricción seca no modelada en la
   articulación a estabilizar, no describe esta planta.

Se buscó el defecto en el lazo todo el día y estaba en el fierro.

---

## 4. Lo que sí quedó medido de P4

| hipótesis | veredicto |
|---|---|
| H1 — dirección del catch fijada por ruido | **sin margen** (su mecanismo vive en la ventana de H2) |
| H2 — el LQR no corre durante el catch | **descartada**: quitarla entera mueve el residuo de −2,3 a −2,6 ms |
| H7 — signo de K3 invertido (nueva) | **no confirmada**: +3,6 ms contra ±11,4 de dispersión |
| H3 — la salida satura | **confirmada como hecho** (93%), **descartada como causa** |
| H5 — las ganancias no son las diseñadas | **sin medir**, único candidato en pie |

**La variable dominante es la entrega**, no el controlador. Sobre 29 traspasos con errores
de 0,9° a 23,2°:

    t_pérdida = −4,17·ε + 90,2 [ms]    r = −0,865   R² = 0,749

- Cruce por cero en **α ≈ 158°**: por debajo, el traspaso no sirve. `SWINGUP_TRANS_NEAR` = 155
  queda del lado inservible. Barrido de `?tn=`: **162 mejora de forma reproducible** (0 → 14 ms
  con 5/5 traspasos); 168 y 175 entregan mejor pero disparan 2/5.
- **Ordenada ~90 ms**: con traspaso perfecto el péndulo se pierde igual. Mejor resultado de
  las 90 corridas: 114 ms.

---

## 5. Defectos de firmware encontrados

| | qué | estado |
|---|---|---|
| **P23** | `?ke=` es API que el propio lazo pisa: la rama adaptativa lo sobrescribe con `KE_GAIN_BASE` en el primer tick con \|α\|>5° | registrado, **sin arreglar** |
| — | **`LQR_PWM_MAX` no era el límite operativo**: un segundo bloque re-acotaba a un 70 literal en sus cinco ramas | **arreglado** (v1.58.9, `?lpm=`) |
| — | Comentario de `?pc=` describía una deriva que ya no ocurre; el "100% saturado" era deducción | corregidos |

Tercer y cuarto caso del patrón "parámetro publicado que ningún lazo lee", tras `bt` y F1.

---

## 6. Lecciones de método (las que más cuestan)

**Tres criterios bien escritos y mal implementados, en dos días.** Un `c1 >= 4` que no escala
con n; una comparación de medianas que omitía descontar la covariable que el propio protocolo
mandaba descontar; y una comprobación de tendencia decreciente que toleraba un aumento de
5 puntos. Los tres imprimieron un veredicto **falso** y los tres se detectaron leyendo la
salida cruda. **Contramedida:** ejercitar el bloque de veredicto con un caso sintético
construido *para que falle*, no sólo con uno de efecto nulo.

**El sesgo del techo efectivo.** La saturación medida contra la constante de PWM da 0,0% en
cualquier corrida, porque el DAQ registra el valor *posterior* a la atenuación por posición.
El techo hay que recalcularlo por muestra. Apareció dos veces (bombeo y LQR).

**El banco tiene ciclo de trabajo.** ~40 min de reposo compran ~12 corridas. Diseñar tandas
de 12, no de 20. `scripts/baseline.py` sale con código 1 si el banco no sirve.

**Tres formas de medir mal un spin-down**, todas cometidas hoy: brazo no sujeto (acoplamiento
de 2 GDL), offset de −26° sin quitar (P22 sólo se corrige en m5), y excitación de 4° cuando
hace falta ≥20° para que el modelo viscoso aplique.

---

## 7. Herramientas nuevas (todas en `experiments/2026-08-05_p4_gains/scripts/`)

| script | qué hace |
|---|---|
| `baseline.py` | 3 intentos; decide si el banco sirve. **Correr antes de cada tanda** |
| `m4_daq.py` | campaña del LQR a 500 Hz; `analyse()` es pura y reutilizable |
| `selftest.py` | valida `analyse()` contra trazas de referencia. Correr antes de energizar |
| `tn_sweep.py` | barrido del umbral de traspaso |
| `lpm_sweep.py` | barrido del techo de PWM del LQR |
| `k2_sweep.py` | barrido de K2. **Escrito y probado en seco, nunca completado** |
| `sign_probe.py` | resuelve H7 leyendo `/state`. **Motor a cero**, necesita mover el brazo a mano |
| `encoder_probe.py` | distingue encoder trabado de mecanismo trabado |
| `spindown_now.py` | decaimiento libre; **se niega a reportar** si amplitud <20° o R² <0,85 |

Y en `2026-08-04_m5_swingup/scripts/`: `m5_pwm_sat.py`, la medición de saturación del bombeo.

---

## 8. Qué hacer al retomar, en orden

1. **Inspeccionar el pivote del péndulo** (P24): juego, rozamiento, alineación, si el disco
   del encoder roza. Bloquea todo lo demás.
2. **Repetir el decaimiento** con banco fresco, n≥3, desde varias amplitudes (≥45°). Comparar
   amplitudes es lo que distingue seco de viscoso — es como se estableció el modelo el 4-ago.
3. `sign_probe.py` — 2 min, sin motor, cierra H7.
4. `baseline.py`, y sólo si pasa: `k2_sweep.py --reps 3`.
5. Decidir el default de `tn` (155 → 162). Medido con n=5 en una sesión; conviene confirmarlo.

**Pendiente sin investigar:** en las capturas el péndulo osciló a **1,71 Hz**, no a los
2,28 Hz de la identificación del 30-jul, de donde sale `PEND_INERTIA` — que alimenta la
energía del swing-up y el criterio `E/E*`. Puede ser el brazo mal sujeto, o no.

---

## 9. Aviso sobre lo que la tesis puede afirmar

Las tres campañas de banco se ejecutaron mediante secuencias automatizadas y **Antonio no
presenció las corridas individuales**. La §5.11 lo dice explícitamente y acota sus
afirmaciones a lo que sostienen las trazas. La ordenada de 90 ms está marcada como
extrapolación apoyada en dos observaciones sueltas (114 y 96 ms).
