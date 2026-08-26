# `campaña_a2.py` — retirado el 2026-08-12

Estaba suelto en la raíz de `~TESIS`. Se guarda acá porque produjo el veredicto que hay que
retractar y conviene poder verlo, no porque sirva.

**No lo uses.** El reemplazo es `../scripts/run_a2.py` + `../scripts/decay_analysis.py`.

## Por qué no vale

**La métrica no dependía de la planta.** `analizar_decaimiento` (línea 125) contaba cruces por
cero con `a[i-1]*a[i] < 0` sobre `pend_position_deg`. Ese campo es un ángulo **no acotado, que
acumula vueltas, y cuyo cero (`zp`) es volátil y se pierde en cada reinicio**
(`esp32_qube.ino:2238`, `:1409-1413`; en modo 0 `wrapPendulumTurns()` no se llama nunca). Si el
péndulo oscila alrededor de un equilibrio distinto de cero — el caso normal, y el que se dio —
**no hay ningún cambio de signo y `n_ciclos` sale 0 pase lo que pase**, con fricción o sin ella.
Después la tabla de líneas 176-196 traducía ese 0 a "Fricción seca bloqueante".

Está probado en `../scripts/test_decay_analysis.py::test_el_criterio_viejo_falla_donde_el_nuevo_acierta`:
sobre una traza sintética de pivote **sano** con un offset de 341°, este criterio cuenta 0
cruces y el analizador nuevo dice VISCOSO.

Los otros dos defectos:

- **Muestreo.** Polling de `/state` con `time.sleep(0.03)`, que la latencia HTTP dejó en 6,5 Hz
  efectivos contra una planta de 1,70 Hz: menos de 4 muestras por ciclo. El banco tiene un DAQ
  de 500 Hz por bloques (`/daq`) con cliente Python hecho, y no se usó.
- **Umbral inalcanzable.** Clasificaba "pivote sano" con ≥20 ciclos, y 15 s a 1,70 Hz son 25
  ciclos como máximo teórico.

Además no miraba nada de lo que grababa: la columna `theta` de su propio CSV muestra que el
brazo se movió **127,8°** durante la captura, lo que por sí solo invalida la corrida.
