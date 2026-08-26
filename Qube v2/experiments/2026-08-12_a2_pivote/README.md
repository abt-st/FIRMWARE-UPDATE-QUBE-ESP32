# 2026-08-12 — Grupo A: re-verificación del pivote del péndulo

Se vuelve a levantar el Grupo A completo (A1 inspección, A2 decaimiento libre, A3 origen de la
fricción) porque el cierre anterior no está sostenido por los datos.

---

## 1. Por qué se rehace

`HANDOFF_A2.md` daba el Grupo A por cerrado: A1 ✅, A2-15° ✅ con "≥5 ciclos en 6 s,
amortiguamiento viscoso", A3 innecesario. El único artefacto que dejó esa campaña dice lo
contrario, y la traza no es un decaimiento:

| Evidencia | Valor |
|---|---|
| `resultados_15deg.json` | `n_ciclos: 0`, `"Fricción seca bloqueante"`, `ok: false` |
| `angulo_inicial` de la corrida "de 15°" | **65,39°** |
| `decaimiento_15deg.csv` | 96 muestras; mín. 46,06° / máx. 76,11°; nunca cruza la vertical |
| Muestreo | 6,5 Hz efectivos (mediana 9,1 Hz), con un hueco de 1,24 s |
| **Excursión del brazo durante la captura** | **127,8°** |
| Carpeta `campaña_a2_20260812_205625/` | vacía |

Los 127,8° del brazo por sí solos invalidan la corrida: con el brazo libre los dos grados de
libertad se acoplan y la envolvente deja de decaer. Nadie miró esa columna, y estaba en el CSV.

### Los tres defectos del método anterior

1. **Muestreo.** Polling de `/state` contra una planta de 1,70 Hz: menos de 4 muestras por
   ciclo. El banco tiene un DAQ de 500 Hz por bloques binarios (`/daq`, `/daq/read`) con
   cliente Python hecho (`src/qube_daq/`), y no se usó.
2. **La métrica no dependía de la planta.** `analizar_decaimiento` contaba cruces por cero con
   `a[i-1]*a[i] < 0` sobre `pend_position_deg`, que es un ángulo **no acotado, que acumula
   vueltas y cuyo cero (`zp`) es volátil** (`esp32_qube.ino:2238`, `:1409-1413`; en modo 0
   `wrapPendulumTurns()` no se llama nunca). Si el péndulo oscila alrededor de un equilibrio
   distinto de cero — el caso normal — **no hay ningún cambio de signo y `n_ciclos` sale 0 con
   fricción o sin ella**. Está probado en `test_decay_analysis.py::test_el_criterio_viejo_falla_donde_el_nuevo_acierta`.
   Encima, su umbral de "pivote sano" era ≥20 ciclos, inalcanzable en una ventana de 15 s.
3. **Contar ciclos no distingue Coulomb de viscoso.** Lo que los distingue es la forma de la
   envolvente y la dependencia de λ con la amplitud.

---

## 2. Re-análisis de los datos históricos (`reanalyze_history.py`)

Antes de tocar el banco, el analizador nuevo se pasó por los conjuntos que ya existen. Los dos
del 04-ago tienen verdad conocida y **opuesta** a la del 05-ago: si no reproduce ambos, no sirve.

| Dataset | Veredicto | λ | Dp vs referencia |
|---|---|---|---|
| 04-ago, suelta 64° | INDETERMINADO (13,3 Hz) | **0,0283** (R² 0,978) | **1,00×** |
| 04-ago, suelta 43° | INDETERMINADO (13,6 Hz) | **0,0286** (R² 0,984) | **1,01×** |
| 05-ago, suelta manual | DESCARTADA | — | — |
| 12-ago, campaña rota | DESCARTADA | — | — |

**Reproduce la referencia viscosa a 1 %** en los dos archivos del 04-ago, y sale INDETERMINADO
por corrida a propósito: a 13 Hz alcanza para la envolvente y no para el discriminador. Vale la
pena que quede dicho — la referencia viscosa de todo el proyecto también está submuestreada, y
lo que la sostiene no es el R² de una corrida sino que λ coincidiera entre dos amplitudes.

### 2.1 Hallazgo: el τ_seco = 1,26e-3 del 05-ago no está establecido

`spindown_man_1.csv` es el único registro a 500 Hz que sostiene P24 y §5.12.7 de la tesis. Al
pasarlo por el analizador nuevo aparecen tres cosas:

- **Contiene tres tramos** de caída libre separados por aportes de energía, no una suelta.
- **El centro de oscilación se desplaza 13,7°** a lo largo de la grabación. Un péndulo libre
  decae alrededor de una vertical fija; si el centro se corre, lo que hay es otra cosa.
- **El tramo limpio más largo (t = 6,5 a 16,2 s) da λ = 0,0265, R² = 0,997, Dp = 0,94× la
  referencia sana.** El desplome que se leyó como agarrotamiento ocurre después de t ≈ 17 s,
  donde el movimiento se vuelve errático (−32 → −56 → −52 → −26 → −17 en menos de un segundo),
  que no es la firma de ninguna fricción.

Y el número en sí es reconstruible:

| | |
|---|---|
| meseta final de la traza | −12,30° |
| mediana de la traza completa | −16,52° |
| centro de oscilación real (puntos medios) | **−36,91°** |
| reposo medido contra la **mediana** | +4,22° → τ_c = **1,12e-3 N·m** |
| reposo medido contra el **centro real** | +24,61° → τ_c = 6,32e-3 N·m |

El registro reporta 4,75° y 1,26e-3: la primera línea lo reproduce salvo por el recorte exacto
de la ventana. O sea que la cifra descansa en tomar **la mediana de la traza como vertical**
(`spindown_now.py:88`, con un docstring que defiende esa elección). Para una traza que oscila
simétrica alrededor de la vertical la mediana *es* la vertical; para ésta no, porque la
grabación pasa la mayor parte del tiempo en la cola casi detenida y la mediana queda 20° del
centro de oscilación.

> **Lo que esto establece y lo que no.** Establece que el valor τ_seco = 1,26e-3 N·m no está
> sostenido por el archivo que lo respalda. **No** establece que el pivote estuviera sano el
> 05-ago: esa grabación tiene un desorden real después de t ≈ 17 s cuyo origen no se sabe.
> Tampoco es "la otra lectura es la correcta" — es que el número no está determinado.
> `Capitulo_05.tex:679-703` y `:218-231` citan esta cifra, y `REGISTRO_PROBLEMAS.md:1599`
> (P24) descansa en ella. **Hay que decidir qué hacer con eso, y no es una decisión de código.**

Nota aparte, de la misma revisión: el ángulo de reposo da una **cota inferior** de τ_c, no una
igualdad. El péndulo se detiene en el primer punto de retorno que cae dentro de la banda de
adherencia, y ese punto puede quedar en cualquier lugar de la banda. La tesis lo reporta como
igualdad. Con varias repeticiones el máximo de la tanda converge al borde de la banda desde
abajo, y por eso la campaña las agrega (`compare_across_amplitudes`).

---

## 3. El criterio nuevo (`decay_analysis.py`)

**Referencia.** Todo se mide contra el **centro de oscilación estimado por la mediana de los
puntos medios entre extremos consecutivos**, que converge a la vertical tanto con
amortiguamiento viscoso como con Coulomb y no depende de `zp` ni del wrap. El reposo previo a
la suelta se usa sólo como comprobación: en la suelta manual el operador sostiene el péndulo
arriba, así que ahí el reposo previo es el ángulo de suelta y no la vertical.

**Discriminador: balance de energía por semiciclo**, con las amplitudes en radianes y
`E = k(1−cos A)`:

```
dE_k = tau_c * (A_k + A_{k+1})  +  Dp * (pi/2) * omega_d * ((A_k+A_{k+1})/2)^2
```

Ajuste por mínimos cuadrados sin término independiente (a amplitud nula no se disipa nada), que
devuelve τ_c y Dp en unidades físicas con sus errores estándar. El veredicto sale de cuáles
coeficientes son significativos, no de un umbral inventado.

Se llegó a esta forma porque la versión en amplitud (regresar ΔA contra A_k) tiene dos defectos
que aparecieron probándola: pone el ruido de A_k en los dos lados de la ecuación y fabrica
pendiente viscosa donde no la hay — una traza de Coulomb puro salía MIXTA —, y supone pequeñas
oscilaciones, que a 45° o 60° ya no vale.

**Cuatro estimadores** por corrida: envolvente exponencial (λ), envolvente lineal, balance de
energía (τ_c y Dp), y ángulo de reposo final (cota inferior de τ_c, familia independiente).

**Veredictos:** `VISCOSO`, `SECO`, `MIXTO`, `TRABADO`, `INDETERMINADO`, `DESCARTADA`.
`DESCARTADA` no es un resultado sobre el pivote — es la ausencia de uno.

### Guardas (fallan cerradas)

| Guarda | Umbral | De dónde sale |
|---|---|---|
| `tasa_envolvente` | ≥ 10,2 Hz (6 muestras/ciclo) | 3 muestras por semiciclo para ubicar un pico |
| `tasa_discriminador` | ≥ 68 Hz (40 muestras/ciclo) | el error de muestreo del pico debe quedar bajo el 10 % de la pérdida por semiciclo (0,83 %) |
| `periodo_plausible` | semiperiodo dentro de ±40 % de 294 ms | ruido puro produce cientos de "semiciclos" y salía VISCOSO |
| `centro_estable` | deriva ≤ 3° | un péndulo libre decae alrededor de una vertical fija |
| `brazo_quieto` | excursión ≤ 4° | 13° el 05-ago dieron R² = 0,02; 128° el 12-ago |
| `amplitud_objetivo` | ±25 % de lo pedido | la corrida "de 15°" del 12-ago partió de 65° |
| `amplitud_minima` | ≥ 8° | cuantización (0,176°/cuenta) y reposo esperado (~5°) |
| `dropped` | = 0 | que el firmware descarte muestras es fallo de protocolo |
| `huecos` | aviso, no fatal | se excluyen los pares de picos que cruzan el hueco |

### Probar el criterio contra casos que DEBEN fallar

`test_decay_analysis.py` — 18 casos, con trazas generadas integrando la dinámica real (no una
señal analítica), muestreadas y cuantizadas como las entrega el encoder. Es lo que no existía:

| Caso | Se exige |
|---|---|
| `viscous_pure` | VISCOSO, λ ±5 %, y **τ_c no significativo** |
| `coulomb_pure` | SECO, τ_c ±10 % |
| `mixed` | los dos términos, en unidades físicas |
| `coulomb_severe` | SECO/TRABADO por conteo, sin regresión |
| **offset de 341° + vueltas** | **VISCOSO, idéntico a la traza limpia** |
| **trabado** | **TRABADO; prohibido pasar por sano** |
| **submuestreo a 9 Hz** | **DESCARTADA, no otro veredicto** |
| 13 Hz (la tasa del 04-ago) | INDETERMINADO: λ sí, discriminador no |
| ventana de 15 s | avisa que no llega a media vida |
| amplitud ≠ la pedida | DESCARTADA |
| brazo suelto / hueco / centro que deriva / energía inyectada | cada uno su guarda |
| **el criterio viejo** | se documenta que da 0 cruces sobre un pivote sano |

```
uv run pytest test_decay_analysis.py -v   # 18 passed
uv run python reanalyze_history.py
```

---

## 4. A1 — inspección visual

Sólo visual, sin desmontar (decisión de Antonio). Consecuencia asumida: **A1 no discrimina nada
por sí solo** — no lo hizo la primera vez —, así que todo el peso del Grupo A recae en A2.

Registrar ítem por ítem, con foto, en vez de un "sin daños visibles" global:

| Ítem | OK / sospechoso / no evaluable sin desmontar | Nota |
|---|---|---|
| disco del encoder: roce, suciedad, excentricidad | | |
| eje y bujes: contaminación, marcas, restos de lubricante | | |
| alineación pivote–encoder | | |
| tornillería y juego | | |
| cableado del péndulo tirando del pivote | | |

*(pendiente de ejecutar)*

---

## 5. A2 — campaña de decaimiento libre

**8 corridas de 60 s a 250 Hz** (`run_a2.py`). 60 s cubre 2,4 vidas medias si el pivote está
como el 04-ago, y sobra si se traba en menos de un ciclo.

Orden **intercalado**, porque el banco se degrada dentro de una misma sesión y una tanda
monotónica confundiría deriva con amplitud:

| # | Amplitud | Rol |
|---|---|---|
| 1 | 35° | línea base A |
| 2 | 15° | |
| 3 | 60° | |
| 4 | 35° | |
| 5 | 15° | |
| 6 | 60° | |
| 7 | 35° | |
| 8 | 35° | línea base B — réplica de la 1 |

λ(1) vs λ(8) mide la deriva de la sesión; las cuatro corridas a 35° dan la repetibilidad
intra-sesión, que es la escala contra la cual se juzga si λ depende o no de la amplitud. 60° y
35° son comparables con las sueltas de 64° y 43° del 04-ago.

### Protocolo por corrida

1. El péndulo arranca **colgando y quieto** unos segundos antes de que lo levantes. Esa
   pre-lectura es la única referencia de vertical que le queda a una traza donde el péndulo no
   llega a oscilar — o sea al caso trabado, que es justo el que hay que poder medir.
2. **Brazo sujeto a mano, firme.**
3. Motor en modo 0, sin par. Hay una mano en el mecanismo.
4. Levantar y **soltar limpio**, sin impulso, y no tocar nada hasta que termine.

`zp` no se toca: el análisis usa el centro de oscilación medido en cada corrida.

```
uv run python run_a2.py              # campaña completa
uv run python run_a2.py --analizar   # re-analiza lo grabado, sin banco
```

*(pendiente de ejecutar)*

## 6. Resultados — sesión del 2026-08-12, 22:16 (`data/a2_20260812_221651/`)

**La campaña no concluye: se perdieron 5 de las 8 corridas por una falla del encoder.**

### 6.1 Lo que se pudo medir

| # | pedido | soltó desde | λ [1/s] | R² | Dp vs ref | τ_c del balance | veredicto |
|---|---|---|---|---|---|---|---|
| 1 | 35° | 28,7° | 0,0706 | 0,998 | 2,50× | t = 1,7 (no sig.) | VISCOSO |
| 2 | 15° | 23,3° | 0,0647 | 0,995 | 2,29× | t = 0,8 (no sig.) | VISCOSO |
| 8 | 35° | 43,2° | 0,0409 | 0,997 | 1,45× | t = −0,8 (no sig.) | VISCOSO |

**En ninguna de las tres el término de Coulomb es significativo**, y las tres envolventes son
exponenciales limpias sobre un rango de amplitud de ~9× dentro de cada corrida. Concuerda con
lo que salió al re-analizar el tramo limpio del 05-ago (§2.1).

Pero el amortiguamiento está **1,45–2,50× por encima de la referencia del 04-ago**, y λ se
movió 1,7× dentro de la sesión: 0,0706 → 0,0647 → 0,0409 en orden cronológico. Es **monótona
en el tiempo y no en la amplitud** (λ(23,3°) < λ(28,7°)), así que las dos variables quedaron
confundidas — que es exactamente lo que el orden intercalado con n=2 iba a evitar, y se cayó
al perderse las cinco corridas del medio.

Veredicto de campaña: **INDETERMINADO**, correctamente. n=1 por amplitud, sin dispersión
intra-amplitud contra la cual juzgar la razón de 1,58.

### 6.2 Corridas 3 a 7 — el encoder del péndulo dejó de leer

En las cinco, `alpha` tomó **un solo valor distinto en 17.500 muestras** (−996,50°), mientras
`theta` seguía leyendo y moviéndose 1,8–2,8°. Antonio confirma que en esas cinco levantó y
soltó el péndulo normalmente. O sea que el canal dejó de leer durante ~6 minutos y volvió solo
para la corrida 8.

No es diagnosticable desde `pend_position_deg`: es un contador incremental, y con el péndulo
quieto da un valor exactamente constante, sin temblor — una traza plana no distingue "no se
movió" de "no lee". Lo que sí distingue es mirar los pines crudos, que `/state` publica como
`pend_a` / `pend_b` junto a `pend_count`. Para eso está `scripts/check_encoder.py`.

Encaja con el problema ya conocido del cableado del encoder del péndulo (push-pull de 5 V al
GPIO a través del Schmitt).

> **Antes de repetir la campaña hay que resolver esto.** Una falla intermitente que no avisa
> puede volver a comerse media tanda, y esta vez pasó desapercibida durante seis minutos.

### 6.3 Cambios al analizador que salieron de esta sesión

| Cambio | Por qué |
|---|---|
| `amplitud_objetivo` pasa a aviso | descartaba la corrida 2 —81 semiciclos, R² = 0,995— por soltar desde 23,3° cuando se pedían 15. La amplitud real cambia la etiqueta, no la validez |
| agrupar por amplitud **medida** | soltar a mano no da en el blanco; agrupar por la pedida mete en la misma casilla corridas que no comparten amplitud |
| `brazo_quieto` graduado (aviso >4°, fatal >10°) | descartaba la corrida 1 —92 semiciclos, R² = 0,998— por 5,8° de excursión. Lo que importa es si el acoplamiento arruinó la envolvente, y de eso ya se encargan el R² y `centro_estable` |
| guarda `angulo_cambia` | las cinco corridas planas se reportaban como `amplitud_minima`, que no sugiere ir a mirar el banco |
| no imprimir `n_peaks` en corte temprano | una guarda fatal corta antes de contar picos, y "0 semiciclos" se leía como péndulo trabado |
| aviso si la línea base A y la B no comparten amplitud | si no, el factor de deriva mezcla tiempo con amplitud |

## 7. A3

Condicionado al veredicto de A2. Implica desmontar, lo que cambia la planta e invalida la
comparación con `Dp = 7,52e-6`, así que es una decisión aparte y no está autorizada.
