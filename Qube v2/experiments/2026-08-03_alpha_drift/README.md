# P16 — Deriva de α: qué era y qué no

> **Aviso.** La primera versión de este documento concluía que el encoder pierde cuentas
> por velocidad, por culpa del filtro RC. **Esa conclusión está refutada** por el barrido
> de la §4. Se conserva el razonamiento completo porque el error es instructivo: la cuenta
> del filtro era correcta y aun así describía un fenómeno que no ocurre.

**Sesión:** 2026-08-03/04 · **Firmware:** v1.58.3 · **Script:** `scripts/alpha_drift.py`

---

## Cómo apareció

Buscando otra cosa. Antes de tocar el LQR había que rehacer el cero de α, y al leerlo se
vio que **el péndulo colgando y quieto marcaba −87,19°**. Un péndulo en reposo apunta hacia
abajo, siempre, sea cual sea la posición del brazo: colgando tiene que leer 0.

## La prueba

El ciclo se cierra sobre una referencia **física**, no sobre ningún cero de software:

1. con el péndulo colgando y quieto, poner el cero (`zp=1`) → α = 0;
2. perturbar;
3. esperar a que vuelva a colgar y se quede quieto — se vigila la **cuenta cruda**, que no
   depende de ninguna convención, hasta que no cambia en ~5 s;
4. leer α. **Debería volver a 0.** Lo que sobre es deriva.

Y la comparación que decide, entre dos regímenes de velocidad:

| régimen | \|α̇\| máx | deriva del colgado | en cuentas |
|---|---|---|---|
| **lento** — el brazo va y viene con el PID | 223–492 °/s | **0,00 · 0,35 · 0,70 · 0,70°** | 0 · 2 · 4 · 4 |
| **swing-up** | 1661–1717 °/s | **0,00 · −13,36 · +22,50°** | 0 · −76 · +128 |

**El colgado es repetible a 0,7° (4 cuentas).** Eso descarta la explicación mecánica —que
el péndulo simplemente no se detenga siempre en el mismo lugar por fricción del rodamiento
o tironeo del cable—, que era la rival seria. Las derivas de 13 y 22° tras el swing-up no
son mecánicas.

## Por qué: la señal se sale del filtro

| magnitud | valor |
|---|---|
| Encoder del péndulo | 2048 cuentas/vuelta en cuadratura X4 → **512 pulsos/vuelta por canal** |
| Velocidad en swing-up | 1661–1717 °/s = 4,6–4,8 vueltas/s |
| **Frecuencia por canal** | **2360–2444 Hz** |
| Filtro RC del acondicionamiento | 10 kΩ × 10 nF, τ = 100 µs |
| **Frecuencia de corte** | **1,59 kHz** (`docs/hardware/signal_conditioning.md`) |

**La señal del encoder está por encima de la frecuencia de corte de su propio filtro.**

El umbral que predice esa cuenta es `1590 Hz / 512 = 3,11 vueltas/s = **1118 °/s**`, y cae
justo entre las dos condiciones medidas: sin pérdida a ≤492 °/s, con pérdida a ≥1661 °/s.

El filtro se dimensionó para atenuar el ruido de conmutación del PWM, que corre a
**20 kHz**. Lo que no se verificó al elegirlo es la **frecuencia máxima de la señal útil**.
A mano —como se validó el encoder en la etapa 2.6 del bring-up, una vuelta completa, 2048
cuentas exactas— se está en unas decenas de °/s: dos órdenes de magnitud por debajo del
problema. **Una validación lenta no dice nada del régimen rápido.**

### Software descartado

- **El PCNT no filtra**: `pcnt_filter_enable` no se llama en ningún lado, así que el
  filtro de glitches del contador por hardware está apagado.
- **No es desbordamiento del contador**: los límites están en ±32767 y las cuentas
  observadas andan por ±1500.
- La deriva aparece con y sin vuelta contabilizada (ciclo 1: 0 vueltas, −76 cuentas), así
  que tampoco es el acotado de vueltas.

## Lo que esto contamina

α se mide con esta misma cadena, y **se degrada justo en las corridas energéticas**, que
son las únicas que importan para el swing-up y el traspaso. Quedan bajo sospecha:

- **`E/E*` y el ángulo de traspaso** — se calculan con α en el instante de mayor velocidad.
- **La entrada del LQR (P4)**: "el LQR no sostiene" y "el LQR recibe un ángulo equivocado"
  son indistinguibles con este dato. Una deriva de 13–22° en la vertical es enorme para un
  controlador que trabaja con `|α| < 25°`.
- **P2** (¿alcanza la energía?) y las observaciones del RL, por lo mismo.

No dice que esas conclusiones estén mal. Dice que **la medición sobre la que se apoyan no
es de fiar en ese régimen**, que es distinto y peor.

## 4. El barrido que refuta la explicación

Se barrió la energía del bombeo (`sp`) **con el traspaso desactivado** (`tr=0`), para que
el régimen no cambie a mitad de corrida:

| \|α̇\| máx | deriva | cuentas |
|---|---|---|
| 182 °/s | 0,00° | 0 |
| 902 °/s | −0,18° | −1 |
| 1479 °/s | −0,18° | −1 |
| 1483 °/s | −0,70° | −4 |
| 1527 °/s | −0,70° | −4 |
| 1601 °/s | −0,18° | −1 |
| 1626 °/s | +0,35° | +2 |

Y dos corridas más **con** traspaso, a 1658 y 1668 °/s: **0,00°** las dos.

**Ocho corridas hasta 1668 °/s sin deriva**, muy por encima del umbral de 1118 °/s que
predecía la teoría del filtro. La velocidad, sola, no la produce.

### El error: una variable oculta

El primer experimento comparó corridas **con** traspaso (las que derivaron) contra
corridas **sin** traspaso (las lentas), creyendo que comparaba velocidades. El traspaso al
LQR estaba correlacionado con la velocidad y quedó fuera del análisis. Sobre esa confusión
construí una explicación cuantitativa que cerraba —el corte del RC a 1,59 kHz contra una
señal de 2,4 kHz— y la escribí como si estuviera establecida.

La cuenta del filtro sigue siendo correcta. Lo que estaba mal era suponer que describía lo
que había medido.

### Qué queda vivo

Las dos derivas grandes (−13,36° y +22,50°) siguen sin explicación, pero hay una
correlación clara: **ocurrieron en corridas donde el brazo terminó fuera del límite
blando** —θ = 111,8° y 115,7° medidos contra un límite de ±95°—, o sea donde se estrelló
contra el tope. En las corridas de hoy el brazo se recentra entre ciclos, termina en
67–77°, no golpea, y no hay deriva.

**Hipótesis viva: golpe mecánico.** Confirmarla exige golpear el brazo a propósito, lo que
es abusivo con el mecanismo; no se hizo. La mitigación real es resolver P12 —que el brazo
no llegue al tope—, que ya estaba en la lista.

## 5. Un defecto encontrado de rebote: P17

Una corrida dejó al péndulo dando **18 vueltas** y el análisis reportó `|α̇| máx =
199.822 °/s`. El PCNT está configurado con límites de ±32767 y **sin acumulador de
desbordamiento**: a las **16 vueltas** (32767/2048) el contador se reinicia y α se vuelve
basura, sin ninguna señal que lo denuncie. Ver [P17](../../docs/REGISTRO_PROBLEMAS.md#p17).

## Datos

`data/alpha_drift.json` (swing-up), `data/alpha_drift_suave.json` (perturbación lenta) y
`data/alpha_drift_sp.json` (barrido de energía).
