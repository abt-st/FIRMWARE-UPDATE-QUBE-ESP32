# P6 / etapa 4 — Barrido del PID del modo 2, medido a 500 Hz

**Fecha:** 2026-08-03 · **Firmware:** v1.58.2 · **Placa:** DOIT ESP32 DevKit V1 (30 pines)
**Instrumento:** `scripts/sweep_pid_500hz.py`, sobre la adquisición por bloques del DAQ.

Escalón **+17° → −20°** (cruza el cero a propósito), `kp=3.0`, `ki=0.5`, repeticiones
intercaladas, péndulo en reposo verificado antes de cada punto, homing válido
(`homing_range` 270,53°).

---

## Lo que cambia respecto de la campaña del 2026-07-31

1. **La traza sale del DAQ a 500 Hz**, no de sondear `/state` a 25 Hz.
2. **El segmento dura 14 s, no 3,5 s.** Medido hoy sobre el mismo escalón: con 5 s de
   ventana el `sse` da 7,7–15,9° y con 14 s da 2,72°. Los dos números salen de la misma
   corrida; el corto no es error de régimen, es transitorio sin terminar.

Esa segunda diferencia es la que invalida la comparación directa con las cifras viejas, y
hay que tenerla presente antes de leer nada de abajo como una mejora o un empeoramiento.

---

## 4.1 / 4.2 — El kick anti-fricción: el control **falla su criterio**

| kick | sobrepaso | `sse` | cruces | pwm activo |
|---|---|---|---|---|
| viejo `se=8, sk=12` | 35,6 % | **2,45°** | 0 | 1,00 |
| nuevo `se=2, sk=30` | 37,4 % | **2,49°** | 0 | 1,00 |

El paso 4.1 pedía **reproducir el error de régimen de ~4,8°** con los valores viejos como
control, y declaraba de antemano: *"si no aparece, el banco cambió y hay que rehacer la
línea base antes de comparar nada"*. **No aparece: da 2,45°.**

La explicación más probable no es la planta sino la ventana de medición. Los 4,8° salen de
segmentos de 3,5 s; con esa ventana, hoy, el mismo escalón mide 7,7–15,9°. Un `sse`
tomado antes de que la respuesta asiente no es un error de régimen. Es el mismo tipo de
defecto que ya infló el sobrepaso a "68–77 %".

**El kick no mueve la aguja:** 2,45 contra 2,49. Y la dispersión *dentro* de cada
configuración (1,33 a 3,56) es **mayor** que la diferencia *entre* configuraciones, así
que con n=2 esto no se puede resolver ni a favor ni en contra. Lo que sí se ve en las
cuatro corridas es `pwm_activo = 1,00` con **0 cruces**: el motor empuja de forma continua
sin alcanzar el setpoint. No es ciclo límite —eso tendría cruces—, es un tope por fricción
estática con el integrador apoyado contra él.

---

## 4.3 — Barrido de `kd`: el criterio de P6 se cumple

`se=2`, `sk=30`, n=2 por punto, intercalado.

| `kd` | sobrepaso | `sse` | cruces | pwm activo | corridas |
|---|---|---|---|---|---|
| 0,15 (valor actual del firmware) | **38,9 %** | 2,64° | 0 | 0,87 | 38,5 · 39,3 |
| 0,30 | 21,6 % | 2,81° | 0 | 1,00 | 21,4 · 21,8 |
| **0,45** | **8,2 %** | 2,84° | 0 | 0,87 | 7,9 · 8,4 |
| 0,60 | 0,0 % | 3,11° | 0 | 0,86 | 0,0 · 0,0 |

**`kd = 0,45` cumple el criterio de P6**: sobrepaso 8,2 % (< 20 %), sin hunting, y el
`sse` sube 0,20° respecto de `kd=0,15` — dentro de la dispersión medida en 4.1/4.2.

Lo que hace fuerte a este resultado no es el n por punto sino **la tendencia monótona
sobre cuatro niveles con repeticiones casi idénticas**: 38,5/39,3 · 21,4/21,8 · 7,9/8,4 ·
0,0/0,0. El efecto de `kd` es de un orden de magnitud mayor que el ruido entre corridas,
al revés de lo que pasaba con el kick.

### Confirmación con n=5 (`sweep_kd_confirm.json`)

| `kd` | sobrepaso, las 5 corridas | mediana | rango de `sse` |
|---|---|---|---|
| 0,15 | 38,5 · 39,3 · 37,6 · 39,3 · 39,4 | **39,3 %** | 2,58–2,88° |
| 0,45 | 7,9 · 8,4 · 8,3 · 8,8 · 8,8 | **8,4 %** | 2,65–3,03° |

**Las distribuciones no se solapan**: el peor caso de 0,45 (8,8 %) queda a 29 puntos del
mejor de 0,15 (37,6 %). El `sse` sí se solapa, y en esta tanda la mediana hasta favorece a
0,45 (2,66 contra 2,70): **el amortiguamiento derivativo no se paga con error de régimen**.
Cero hunting en las diez corridas.

`kd = 0,60` anula el sobrepaso, pero paga `sse` (3,11°) y no aporta sobre 0,45 para el
criterio. Se prefiere 0,45 por dejar margen antes de que el derivativo empiece a amplificar
ruido.

### El tiempo de establecimiento no dice nada acá

`settle_s` sale ~14,8 s en **todos** los puntos, es decir el segmento completo. La banda
del 2 % son 0,74° y el error de régimen es ~2,8°: la respuesta **nunca entra en la banda**,
así que la métrica está saturada y no discrimina. No es un hallazgo sobre la planta, es el
límite de la definición cuando hay error de régimen mayor que la banda.

---

## Qué queda abierto

- **El error de régimen de ~2,6–3,1° sigue intacto** y `kd` no lo toca, como corresponde.
  La firma (`pwm_activo` ≈ 1 con 0 cruces) apunta a fricción estática, no a sintonía.
  El kick, tal como está parametrizado, no lo resuelve.
- **Rehacer la línea base de P6**: las cifras de 4,8° y 38,8–42,0 % vienen de ventanas de
  3,5 s y no son comparables con éstas.
- ~~Confirmar `kd=0,45` con n ≥ 4~~ ✅ n=5, distribuciones sin solapamiento.
- ~~Cambiar el valor por defecto del firmware~~ ✅ **v1.58.3**: `Kd = 0.45f` en
  `esp32_qube.ino`, flasheado por OTA. Verificado con un escalón **sin enviar ganancias**:
  9,5 % de sobrepaso, contra el ~39 % que daría el default viejo.
- **`kp` sin barrer.** Con el amortiguamiento ya arreglado, subir `kp` es el candidato
  natural para atacar el error de régimen y acelerar la respuesta; no se probó.

## Datos

`data/` — traza cruda de cada punto a 500 Hz en el esquema canónico (`t_s`, `theta_deg`,
`alpha_deg`, `alpha_raw_deg`, `pwm`, `mode`, `t_pc_block_s`, `t_now_us`), más
`sweep_kd.json` y `sweep_control.json` con las métricas por corrida. Todas las capturas
salieron a 500,0 Hz con **0 muestras perdidas**.
