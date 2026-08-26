# P19 / P20 — que un dato falso sea imposible, no improbable

**Fecha:** 2026-08-06 · **Firmware:** v1.61.0 (`RL_PROTO_VERSION` 3 → 4) · **Motor:** sin mover

## El defecto

`QubeRealEnv.step()` atrapaba el error de red, escribía un warning y **conservaba el
último estado**:

```python
except requests.RequestException:
    logger.warning("rl_step failed, using last known state")
```

Un episodio muerto —enlace caído, el modo cambiado por debajo, el lazo detenido— producía
observaciones que parecían perfectamente válidas, y todos los números de la campaña se
calculaban sobre ellas. **Es un defecto de integridad de datos, no de rendimiento:** una
traza así es indistinguible de una real *después* de grabada. Es la razón por la que las
campañas del modo 6 de junio quedaron bajo sospecha en bloque.

## El arreglo

**Firmware:** cada recálculo de la observación se sella con `seq` (monótono), `age` (ms
desde que se calculó) y `md` (el modo en que corrió). Los tres viajan en `/rl_state`, en
`/rl_step` y ahora también en `/state`, donde los puede mirar la GUI.

**Python:** `_check_freshness()` rechaza una lectura repetida, vieja o de otro modo, y el
`except` que conservaba el estado pasó a **terminar el episodio**. Se prefiere un episodio
que muere ruidosamente a uno que miente en silencio.

`RL_PROTO_VERSION` sube a 4: el contrato de la observación no cambió, pero un firmware v3
ya no sirve para una campaña válida, y el handshake lo dice.

## P19 reproducido en la placa

```
1) homing:  homing_ok=True  centered=False  err=-73.04

2) modo 0 — el lazo RL no tickea:
   seq 0 -> 0        age=999999 ms   md=-1

3) modo 6 (acción 0, el motor no se mueve):
   mode=6  seq 56 -> 103   age=21 ms   md=6   pwm=0
   -> 47 observaciones en ~1 s (el tick interno es 50 Hz)

4) vuelta a modo 0 — la observación se CONGELA:
   seq 104 -> 104    age=2395 ms
   congelada: True
```

El paso 4 **es** P19. Antes de este cambio el cliente habría seguido leyendo los mismos
cuatro números indefinidamente y llamándolos datos. Ahora `age = 2395 ms` supera
`MAX_OBS_AGE_MS = 200` y `StaleObservationError` corta el episodio.

Las 47 observaciones/s del paso 3 son el tick **interno** del firmware, no la tasa del
enlace HTTP. P20 es sobre el round-trip y se mide del otro lado.

## P20

`reset()` cierra el episodio anterior midiendo la frecuencia **alcanzada** y la compara
con `control_freq`. Por debajo del 80 % aborta (`strict_freq=True`, el default) o avisa.

Se entrenó y se evaluó a "50 Hz" sobre un enlace de 26,1 Hz durante campañas enteras sin
que nada lo dijera: la política ve una dinámica que no es la que aprendió.

## Verificación

13 tests nuevos (`tests/test_rl_freshness.py`), sin placa. Cada criterio con sus dos
mitades — el caso que debe fallar y el que debe pasar:

| criterio | caso que debe FALLAR | caso que debe PASAR |
|---|---|---|
| campos de procedencia | firmware v3 sin `seq`/`age`/`md` | respuesta v4 completa |
| modo | `md=0` a mitad de episodio | `md=6` |
| antigüedad | `age = 201 ms` | `age = 200 ms` (límite inclusivo) |
| repetición | 3 veces el mismo `seq` | 2 veces (el cliente puede sondear >50 Hz) |
| enlace caído | `ConnectionError` en `step()` | round-trip sano |
| frecuencia | 26 Hz sobre 50 pedidos | 48 Hz sobre 50 |

La mitad "debe PASAR" no es ceremonia: un criterio de frescura demasiado estricto aborta
episodios sanos, que es la otra forma de romperlo.

## Pendiente

- **Medir P20 de verdad**, o sea la tasa del round-trip HTTP con el nuevo `/rl_step`. La
  cifra vigente (26,1 Hz) es anterior a esta sesión.
- **Una campaña de m6 con el arreglo puesto.** Recién ahora una medición del modo 6 puede
  sostenerse; todas las anteriores quedan acotadas por lo que no se podía descartar.
