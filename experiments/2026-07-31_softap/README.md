# 2026-07-31 — SoftAP puro vs AP+STA: latencia del enlace

## Objetivo

Decidir con evidencia si el rol de radio del firmware debe ser **SoftAP puro** o volver
a **AP+STA**. La migración a SoftAP puro ya está hecha en el código (es el rol por
defecto desde v1.56.0), pero la mejora de latencia que la motiva **todavía no está
medida en este banco**: hasta que esta carpeta tenga datos, es una hipótesis razonada.

Fundamento, ventajas/desventajas y análisis completo:
`docs/research/softap_app_escritorio.md`.

## Criterio de decisión — PRE-REGISTRADO

Escrito **antes** de correr la primera medición, y no se toca después. Se adopta SoftAP
puro si, respecto a AP+STA y en la misma sesión:

1. la **media** del round-trip baja al menos un **20 %**, **y**
2. el **p95 no empeora**, **y**
3. la **fracción de muestras > 20 ms no aumenta**.

Se **rechaza** si el p95 o el máximo empeoran, aunque la media mejore: en un lazo de
control la cola pesa más que el promedio. Ése fue exactamente el aprendizaje de la
campaña de julio (CHANGELOG v1.50.0), donde eliminar los picos importó más que bajar
la media.

## Segunda pregunta: ¿quién le roba tiempo a quién?

`measure_loop_load.py` responde una pregunta distinta y previa a la anterior: **si el
lazo de control es el que carga la placa y por eso la transmisión rinde poco**, o si es
al revés y la radio le roba tiempo al lazo.

Las dos hipótesis dan resultados separables sobre `loop_dt_max_us`:

| | dt_max con enlace ocioso | dt_max con enlace martillado |
| --- | --- | --- |
| Si carga el **lazo** | crece con el modo (0 < 4 < 7) | igual que ocioso |
| Si roba la **red** | plano entre modos | se dispara |

```bash
python measure_loop_load.py                 # fases A y B, motor deshabilitado
python measure_loop_load.py --with-control   # + modos 4 y 7: MUEVE EL BRAZO
```

Importa porque decide el rediseño. Si domina la red, mover el lazo al PC **empeora** el
problema: cada muestra pasaría a necesitar un round-trip propio (500 por segundo a
500 Hz, contra las 10 transmisiones/s de hoy y un techo medido de 31 Hz), a cambio de
liberar una fracción mínima de un núcleo que además no es el que transmite —el `loop()`
corre en el core 1 y la pila WiFi en el core 0—. Si domina el lazo, la conclusión se
invierte y hay que aligerarlo.

Sospechas concretas a confirmar o descartar con esta medición, todas del lado de
**comunicaciones** y ninguna de la ley de control:

- la línea de ~120 caracteres por `Serial.print` cada 100 ms (`esp32_qube.ino:2800-2828`),
  que a 115200 baudios son ~10 ms de UART contra un período de 2 ms — y que además
  casi nadie lee, porque abrir el monitor reinicia la placa;
- el `String` concatenado de `getStateJson()` con más de 40 campos;
- la transacción I²C al INA219 dentro del mismo `loop()` que el control.

## Configuración del hardware

| Aspecto | Valor |
| ------- | ----- |
| Firmware | v1.56.0 (L298N), `/rl_step` proto v3 |
| Lazo de control | 500 Hz (`CONTROL_PERIOD_US = 2000`) |
| Modo durante la medición | 0 (motor deshabilitado) salvo que se pase `--mode 6` |
| Adaptador WiFi del PC | **debe estar en "máximo rendimiento"** — ver abajo |

> **Antes de medir: apagar el power-save del adaptador del PC.** En SoftAP puro el PC
> es la *estación*, y un AP retiene las tramas de una estación dormida hasta el DTIM
> siguiente. Si el adaptador está en ahorro de energía, la medición no mide el enlace:
> mide la siesta del portátil. *Administrador de dispositivos → adaptador WiFi →
> Opciones avanzadas → ahorro de energía = máximo rendimiento*, y plan de energía de
> alto rendimiento. Dejarlo anotado en la bitácora de la corrida.

## Procedimiento

Misma sesión, mismo montaje, mismo día. **No** comparar contra la tabla de julio: el
espectro del laboratorio de entonces no es el de hoy.

```bash
cd experiments/2026-07-31_softap/scripts

# A — AP+STA (rol anterior)
cd ../../../src/firmware && pio run -e esp32dev_apsta --target upload && cd -
python measure_link_latency.py run --label apsta --ip 192.168.100.50

# B — SoftAP puro (rol por defecto); asociar el PC a QUBE-ESP32 / qube1234
cd ../../../src/firmware && pio run -e esp32dev --target upload && cd -
python measure_link_latency.py run --label softap

# Repetir alternando A, B, A, B — al menos dos corridas de cada una
python measure_link_latency.py report
```

Alternar importa: una interferencia pasajera en el laboratorio no debe leerse como
efecto del cambio.

## Qué se registra

Cada corrida deja un JSON en `data/` con la serie completa de latencias más el resumen:
media, p50, **p95**, máximo, fracción > 20 ms, throughput, y —leídos del propio
firmware al terminar— `loop_dt_max_us` y `loop_overruns`, que dicen cuánto le robó la
radio al lazo de 500 Hz. `report` imprime la tabla comparativa y recuerda el criterio.

## Resultados

_Pendiente: sin corridas al 2026-07-31._

## Conclusiones

_Pendiente._ Si el resultado es negativo **también se escribe aquí**: un experimento
que descarta una hipótesis con evidencia vale tanto como uno que la confirma, y la
reversión es un solo comando (`pio run -e esp32dev_apsta --target upload`).
