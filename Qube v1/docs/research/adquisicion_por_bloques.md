# Adquisición por bloques: el ESP32 muestrea, el PC interpreta

Diseño e implementación del modo de adquisición de datos: la ESP32 muestrea a la tasa
del lazo en un buffer circular y el computador se lleva **bloques**, reconstruye la
serie temporal y hace todo el análisis.

- **Fecha:** 2026-07-31 · **Firmware:** v1.57.0 · **Protocolo DAQ:** v1
- **Código:** `src/firmware/esp32_qube/esp32_qube.ino` (bloque DAQ), `src/qube_daq/`
- **Estado:** implementado y probado en tests; **sin correr en banco todavía**.

---

## 1. Lo que se decidió, y lo que no

La idea de partida era dejar la ESP32 **solo como adquisición de datos**, con el PC
recibiendo, interpretando y analizando. Esa idea se adopta en su parte de adquisición
y análisis, y **no** en la de mover el lazo de control al computador. La razón no es de
gusto arquitectónico: es una cifra medida.

| | frames de red por segundo | ¿alcanza? |
| --- | --- | --- |
| Telemetría actual (WebSocket 10 Hz) | 10 | sí |
| **Adquisición por bloques a 500 Hz** | **~4** | **sí, con margen** |
| Lazo cerrado desde el PC a 50 Hz | 50 | no |
| Lazo cerrado desde el PC a 500 Hz | 500 | no, por 16× |
| **Techo medido del enlace** | **31** | — |

La clave está en la primera y la tercera fila: **adquirir está limitado por caudal;
controlar está limitado por latencia.** Un bloque que tarda 30 ms en llegar no degrada
nada, porque cada muestra viaja con la marca de tiempo del tick que la produjo — la
serie se reconstruye exacta. Un lazo de control, en cambio, no puede esperar: el
período es de 2 ms y el round-trip medido es de 32 ms con colas de 63 ms
(CHANGELOG v1.50.0).

Dicho de otro modo: mover el lazo al PC multiplica por 16 la exigencia sobre el
recurso escaso —la radio— a cambio de liberar microsegundos en un núcleo que ni
siquiera transmite. La adquisición por bloques hace lo contrario: **baja** el tráfico
por muestra útil de 1 frame cada 100 ms a 512 muestras por frame.

## 2. Sobre la carga de la placa

La hipótesis razonable de que "la ESP32 va lenta porque carga con el WiFi *y* con todo
el lazo" merece una precisión que cambia la conclusión. El `loop()` de Arduino corre en
el **core 1** y la pila WiFi en el **core 0**: la ley de control no compite con la
radio. Lo que sí comparte núcleo con el control es la **telemetría**, que se ejecuta
dentro del mismo `loop()` (`esp32_qube.ino`, `serviceFailsafeAndTelemetry()`), y ahí
hay tres costos reales, todos de comunicaciones y ninguno de control:

1. una línea de ~120 caracteres por `Serial.print` cada 100 ms — a 115200 baudios son
   ~10 ms de UART contra un período de 2 ms, y casi nadie la lee, porque abrir el
   monitor serial reinicia la placa;
2. el `String` concatenado de `getStateJson()`, con más de 40 campos;
3. la transacción I²C al INA219.

Por eso este release agrega `/cmd?sv=0`, que apaga la línea serial sin tocar nada más.
Y por eso el sentido de la interferencia sigue siendo el documentado en
`demo/README.md`: *"el lazo llega a bloquearse ~95 ms cuando el WiFi le roba tiempo"*.
**La red le roba al lazo, no al revés.** La medición que lo confirma o lo refuta está
en `experiments/2026-07-31_softap/scripts/measure_loop_load.py`.

## 3. Formato del bloque

Todo little-endian. Cabecera de 16 B + N muestras de 16 B.

| Cabecera | bytes | contenido |
| --- | --- | --- |
| `magic` | 4 | `0x51414451` (`QDAQ`) |
| `pv` | 1 | versión de protocolo (1) |
| `sample_bytes` | 1 | 16 |
| `n` | 2 | muestras en este bloque |
| `dropped` | 4 | perdidas **acumuladas** desde el último `start` |
| `t_now` | 4 | `micros()` al servir el bloque |

| Muestra | bytes | contenido |
| --- | --- | --- |
| `t_us` | 4 | `micros()` del tick que la produjo |
| `th_deg` | 4 | posición del brazo, con offset aplicado |
| `al_deg` | 4 | péndulo **crudo, sin envolver** |
| `pwm` | 2 | comando aplicado al motor en ese tick |
| `mode` | 1 | modo activo |
| `flags` | 1 | bit0 = `ina_ok` |

Cuatro decisiones que valen la pena explicitar:

- **`t_us` se toma en el tick, no al transmitir.** Es lo que hace que la latencia del
  transporte sea irrelevante para la calidad de la serie.
- **`al_deg` viaja sin envolver.** El salto de ±180° destruye cualquier derivada
  numérica; envolver es decisión del análisis, no del transporte. `Acquisition`
  expone `alpha_wrapped_deg` para graficar.
- **No se transmiten velocidades.** Derivar y filtrar es trabajo del PC — que es
  justamente el punto de una arquitectura de adquisición.
- **`dropped` es acumulado y viaja en cada bloque.** Nunca hay pérdida silenciosa: el
  PC sabe cuántas muestras faltan y entre qué marcas de tiempo.

## 4. Buffer y contratos

`DAQ_CAPACITY = 2048` muestras (32 KB) = **4,1 s a 500 Hz**. `DAQ_MAX_BLOCK = 512`
muestras (8 KB) por respuesta. Costo en RAM: el firmware pasó de 15,2 % a 27,7 % de los
327 KB (32 KB de anillo + 8 KB de staging).

- **Productor/consumidor único (SPSC).** Sólo el lazo mueve `daqHead` y sólo el handler
  HTTP mueve `daqTail`, así que la ruta de 500 Hz no necesita sección crítica. La
  muestra se publica *después* de escribirse: el consumidor nunca ve una a medias.
- **Buffer lleno: se descarta la muestra nueva y se cuenta.** Sobrescribir la vieja
  perdería historia en silencio.
- **`start` vacía el buffer.** Mezclar dos sesiones daría un salto temporal
  indistinguible de un dato real.
- **Un solo consumidor.** `beginResponse_P` no copia: lee del staging mientras
  transmite. Una segunda petición concurrente recibe **503** en vez de arriesgar datos
  pisados; el cliente reintenta.
- **Apagado por defecto.** Con `daqRunning = false` el costo en el lazo es una lectura
  de bool.

## 5. Uso

```bash
uv run python -m qube_daq status
uv run python -m qube_daq record --seconds 10 --hz 500 -o data/captura.csv
uv run python -m qube_daq record --seconds 20 --hz 500 --mode 5   # swing-up, MUEVE EL BRAZO
uv run python -m qube_daq plot data/captura.csv
```

El CSV usa el esquema canónico del proyecto (`t_s`, `theta_deg`, `alpha_deg`,
`alpha_raw_deg`, `pwm`, `mode`), el mismo de `src/firmware/capture.py`, para que el
análisis existente lo lea sin adaptadores.

`record` informa siempre **tasa efectiva medida** (no la nominal pedida), intervalo
mediano y máximo, huecos y muestras perdidas. Una captura que perdió muestras lo dice
en mayúsculas; no hay forma de llevarse un CSV creyendo que está completo.

## 6. Qué está verificado y qué no

**Verificado sin hardware** (19 tests, `tests/test_daq_protocol.py` y
`tests/test_daq_client.py`): decodificación campo por campo, rechazo de bloque
truncado, rechazo por desajuste de versión de protocolo, bloque vacío como caso
legítimo, desbordamiento de `micros()` —que ocurre cada **71,6 minutos** y sin corregir
haría que el tiempo vaya hacia atrás— dentro de un bloque y encadenado entre bloques,
concatenación en orden, vaciado de la cola al terminar, y contabilidad de perdidas.

**No verificado:** todo lo que necesita la placa. No se ha medido la tasa efectiva
real, ni cuánto le cuesta al lazo la captura a 500 Hz (`loop_dt_max_us` con DAQ activo
contra el mismo sin DAQ), ni si el buffer alcanza con el `poll_interval` por defecto en
condiciones de radio reales. Nada de esto se ha corrido en banco.

## 7. Pendiente

- Medir en banco lo del punto anterior, y anotarlo en `experiments/2026-07-31_softap/`.
- Incluir corriente y tensión del INA219 en la muestra: hoy no van porque el INA se lee
  a 10 Hz en la ruta de telemetría, y meterlo en el tick de 500 Hz agregaría una
  transacción I²C al lazo. Requiere decidir a qué tasa se muestrea.
- Interfaz gráfica en vivo. El CLI grafica una captura ya grabada; una app de
  escritorio con trazas en tiempo real (PySide6 + pyqtgraph) es el paso siguiente y
  está diseñada en `docs/research/softap_app_escritorio.md` §5.
