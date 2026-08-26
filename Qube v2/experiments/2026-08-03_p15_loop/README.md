# P15 — El lazo con el motor en marcha: **no se reprodujo**

**Fecha:** 2026-08-03 · **Firmware:** v1.58.3 · **Instrumento:** `scripts/loop_load.py`,
corrido **dentro de la app** (`--gui`) para poder mirar la traza mientras medía.

---

## Lo que se buscaba

Horas antes, en la misma sesión, dos corridas con firmware **v1.58.2** mostraron esto:

| corrida | tasa efectiva | dt máx | huecos | perdidas | `loop_overruns` |
|---|---|---|---|---|---|
| A — swing-up, con la GUI abierta | **330,1 Hz** | 214,6 ms | 217 | 0 | 7 |
| B — swing-up, autoprueba sin GUI | **256,4 Hz** | 488,6 ms | 131 | 0 | 8 |

`dropped = 0` en las dos. Ese contador lo lleva el firmware y cuenta lo que el anillo
descartó por estar lleno; en cero significa que el PC vació el buffer siempre y que **las
muestras que faltaban nunca se produjeron**. De ahí la hipótesis: el lazo se para.

## El experimento

Seis condiciones, n=3, intercaladas, 15 s cada una, reposo del péndulo verificado antes de
cada corrida. Criterio escrito **antes** de medir: *si `m1_osc` también colapsa, la causa
está del lado del motor y no en el código del swing-up; si `sv0` o `tp1000` recuperan la
tasa, es un costo de comunicaciones dentro del `loop()`*.

| condición | mediana Hz | dt máx | paradas >20 ms | perdidas | I máx | overruns |
|---|---|---|---|---|---|---|
| `reposo` | 498,7 | 16,7 ms | **0** | 0 | 31 mA | 3–9 |
| **`m1_osc`** (motor conmutando, sin lazo) | **490,4** | **17,4 ms** | **0** | 0 | 66 mA | **19–32** |
| `m2_step` (lazo cerrado, suave) | 499,1 | 14,4 ms | 0 | 0 | 49 mA | 2–7 |
| `m5` (swing-up) | 498,7 | 14,2 ms | 0 | 0 | 278 mA | 4–5 |
| `m5_sv0` (serial apagada) | 498,9 | 12,5 ms | 0 | 0 | 96 mA | 3–5 |
| `m5_tp1000` (telemetría diezmada) | 499,8 | 12,8 ms | 0 | 0 | 87 mA | 0–2 |

**18 corridas de 18 sin una sola parada por encima de 20 ms.** El fenómeno no aparece.

### Réplica del protocolo original

Se sospechó que la diferencia estaba en *cuándo* se mide: en las corridas A y B el
swing-up llevaba ya varios segundos bombeando y la captura cubría al péndulo **girando**,
mientras que en el protocolo de arriba los 15 s son casi todos la rampa. Se replicó el
original —`m=5`, seis segundos de bombeo, y recién ahí la autoprueba:

```
500,2 Hz · mediana 2,019 ms · máx 8,722 ms · 0 perdidas
```

Y la placa confirma que la condición fue al menos tan exigente como la original:
`pend_wraps = 5` (cinco vueltas completas del péndulo) y traspaso disparado con
α = 176,84° y `E/E* = 0,9994`. **Sigue sin reproducirse.**

---

## Lo que sí quedó medido: el motor le cuesta al lazo, pero poco

`m1_osc` es la peor condición de las seis, de forma consistente en las tres repeticiones:
**490,4 Hz contra 498,7 en reposo**, y **19–32 overruns contra 3–9**. Es la dirección que
la hipótesis original señalaba —el motor conmutando perturba el lazo— pero la magnitud es
de ~2 % de las muestras, no del 50 %.

Nótese que es `m1_osc` y no `m5` el que más molesta, aun teniendo menos corriente pico
(66 mA contra 278 mA). Lo que distingue a `m1_osc` no es la corriente sino **la frecuencia
de inversión del puente**: un cambio de sentido cada 200 ms por orden del PC, contra las
inversiones más espaciadas del bombeo resonante.

Y las dos variantes de comunicaciones **no** cambian nada relevante: apagar la línea serial
(`sv0`) o diezmar la telemetría (`tp1000`) dejan la tasa igual, dentro del ruido. La
hipótesis de "un costo de comunicaciones dentro del `loop()`" queda sin respaldo en este
banco.

---

## Veredicto y qué hacer si vuelve

**P15 queda `NO REPRODUCIBLE`, no `RESUELTO`.** El fenómeno se midió tres veces con
instrumentos distintos, así que no fue un error de lectura; pero no sobrevive a un
protocolo controlado. Entre unas mediciones y otras cambiaron cosas que **no se pueden
separar retroactivamente**:

- la placa **se reinició** (reflasheo OTA a v1.58.3 en el medio);
- las corridas A y B venían de una sesión larga con muchos swing-ups, homings y **un golpe
  contra el tope** (un pulso de 500 ms a PWM 60 que movió el brazo 130°);
- en la corrida A la app del PC estaba saturando un núcleo al 88 % —después optimizada a
  14 %—, aunque la corrida B fue sin GUI y también colapsó.

Lo honesto es decir que **algo que el reinicio limpió** producía el fenómeno, sin poder
nombrarlo.

**Si vuelve a aparecer, antes de reiniciar nada:**

1. Leer `/state` completo y guardarlo (uptime, `loop_*`, `ina_ok`, `pend_wraps`).
2. Correr `loop_load.py --gui --only reposo,m1_osc,m5 --reps 3` en ese mismo estado: si en
   ese momento sí colapsa, la comparación contra esta tabla es directa.
3. Sólo después reiniciar, y repetir. Si el reinicio lo cura, eso **es** el dato.

## Un pendiente de instrumentación que este experimento no borra

En la corrida B, `loop_dt_max_us` marcó **17,3 ms** mientras las marcas de tiempo mostraban
un hueco de **488 ms**. La métrica de salud del propio firmware **no ve** esas paradas; sí
las ve `loop_overruns`. Eso sigue siendo cierto y vale independientemente de P15: **leer
`loop_dt_max_us` solo no permite descartar una parada del lazo.**

## Datos

`data/` — 18 trazas a 500 Hz en el esquema canónico + `loop_load.json` con las métricas por
corrida.
