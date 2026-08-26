# ESP32 en SoftAP puro + aplicación de escritorio

Evaluación de dejar la ESP32 operando **solo como punto de acceso** (sin cliente del
router) y de trasladar la transmisión de datos desde el navegador a una **aplicación
nativa en el PC**.

- **Fecha:** 2026-07-31
- **Firmware de referencia:** `src/firmware/esp32_qube/esp32_qube.ino` (v1.53.0 al escribirlo)
- **Estado:** **migración ejecutada en v1.56.0.** El SoftAP puro es el rol por defecto
  del firmware; el rol anterior se reconstruye con `pio run -e esp32dev_apsta`. La
  medición que valida o revierte la decisión está pendiente y vive en
  `experiments/2026-07-31_softap/` (§9). Este documento se mantiene como el análisis
  que fundamenta el cambio; **no** se reescribe con resultados que aún no existen.

## Convención de evidencia

Cada afirmación cuantitativa lleva una etiqueta que declara **de dónde sale**, porque la
mitad de las decisiones de este proyecto se tomaron sobre mediciones propias y la otra
mitad sobre expectativas que todavía no se han verificado en banco. Confundirlas sería
el mismo error que ya se documentó en `REGISTRO_PROBLEMAS.md`.

| Etiqueta | Significado                                                                 |
| -------- | --------------------------------------------------------------------------- |
| **[M]**  | **Medido** en este banco, con registro en `CHANGELOG.md` o en `experiments/` |
| **[D]**  | **Derivado**: se deduce del código propio o de una medición propia          |
| **[E]**  | **Esperado**: referencia externa o razonamiento, **sin medir aquí**         |

---

## 1. Resumen y recomendación

Hoy la ESP32 levanta **simultáneamente** un SoftAP (`QUBE-ESP32`, `192.168.4.1`) y una
conexión al router del laboratorio con IP fija `192.168.100.50`
(`esp32_qube.ino:2555`, `:2569`, `:2047`). Toda la operación real —la demo, la GUI, los
scripts de RL— se hace por la segunda vía. Esa coexistencia AP+STA sobre una **radio
única** fue la causa medida de los picos de latencia de ~100 ms que degradaban el lazo
PC-en-el-lazo, y sólo se domó subiendo el intervalo de beacon del AP de 100 a 300 ms
**[M]**.

La propuesta que se evalúa aquí es eliminar el problema en su raíz en lugar de
mitigarlo: **apagar el STA** (`ENABLE_STA = false`, `esp32_qube.ino:981`), dejar la
ESP32 como único punto de acceso y conectar el PC directamente a ella, con una
**aplicación de escritorio en Python** que reemplace al navegador como interfaz de
control y adquisición.

**Recomendación.** Vale la pena, pero **condicionada a medirla**. El cambio de firmware
es de una línea, es reversible, y ataca un cuello de botella cuya causa ya está
identificada con evidencia propia; además entrega dos beneficios que no dependen de la
latencia y que hoy son problemas reales de operación: el banco deja de depender de la
red de la universidad y la dirección deja de ser variable. Ahora bien, **ninguna cifra
de latencia en SoftAP puro está medida en este banco**, y hay un modo de falla nuevo que
la literatura documenta con claridad —el buffering que el SoftAP aplica a una estación
que se duerme, siendo ahora el PC esa estación— capaz de anular la mejora si no se
configura el adaptador del portátil. Por eso la sección 9 propone un A/B corto y honesto,
con el criterio de decisión escrito **antes** de correrlo.

Lo que **no** hace esta propuesta: no resuelve por sí sola el modo 6. Si tras medir el
enlace sigue por encima del período de 20 ms, la conclusión vigente del README no cambia
y el camino sigue siendo ESP-NOW o el puente USB (sección 10).

---

## 2. Punto de partida: qué hace hoy el firmware y qué se midió

### 2.1 Configuración de radio actual

| Aspecto              | Estado actual                                        | Referencia                  |
| -------------------- | ---------------------------------------------------- | --------------------------- |
| Modo WiFi            | `WIFI_AP_STA` (AP + cliente simultáneos)             | `esp32_qube.ino:2555`       |
| SSID/clave del AP    | `QUBE-ESP32` / `qube1234`, WPA2-PSK                   | `:979-980`                  |
| IP del AP            | `192.168.4.1` (fija por diseño del SoftAP)           | `:2700`                     |
| Clientes máximos     | 4                                                     | `:2569`                     |
| Canal del AP         | **Forzado al canal del router** por escaneo en `setup()` | `:2561-2568`            |
| Intervalo de beacon  | 300 ms (default 100 ms)                               | `:2575-2581`                |
| Power save           | `WIFI_PS_NONE` explícito, re-afirmado en cada `GOT_IP` | `:2586-2591`              |
| IP del STA           | Estática `192.168.100.50`                             | `:2047-2053`                |
| Reconexión STA       | Guardián no bloqueante en `loop()`                    | `:2815-2821`                |
| Servidor             | `ESPAsyncWebServer` + WebSocket en `/ws`              | `:990`, `:2595-2607`        |
| Lazo de control      | 500 Hz (`CONTROL_PERIOD_US = 2000`)                   | `:626`                      |
| Telemetría WS        | 100 ms por defecto; **500 ms en modo 6**              | `:635`, `:639`, `:2485-2501` |

Dos detalles de esa tabla no son cosméticos, y conviene subrayarlos porque **son la
prueba de que la radio ya está saturada**:

1. El canal del SoftAP **no se elige**: se copia del router mediante un escaneo
   bloqueante en `setup()`. Si se forzara otro canal, el STA no lograría autenticar
   (Reason 2, AUTH_EXPIRE), porque la radio es una sola y no puede estar en dos canales
   a la vez **[D]**. Es decir, hoy el AP es rehén de la red del laboratorio.
2. La telemetría por WebSocket se **decima a 500 ms durante el modo 6**
   (`:2495-2499`), con un comentario que lo dice sin eufemismos: un broadcast cada
   100 ms le roba tiempo de aire al tráfico latencia-crítico **[D]**.

### 2.2 Latencia medida del enlace (CHANGELOG v1.50.0, 2026-07-08)

Banco de latencia HTTP con `a=0`, sin mover el motor, sobre STA @ `192.168.100.50` con
AP+STA activos **[M]**:

| Configuración                              | media     | máx        | picos >100 ms | throughput |
| ------------------------------------------ | --------- | ---------- | ------------- | ---------- |
| Viejo (pv2), 2-RTT `/rl_cmd` + `/rl_state`  | 69 ms     | 173 ms     | —             | 14,6 Hz    |
| Viejo (pv2), lectura simple `/rl_state`     | 41 ms     | 155 ms     | 2,1 %         | 24 Hz      |
| **Nuevo, `/rl_step` + beacon 300 ms**       | **32 ms** | **63 ms**  | —             | **31 Hz**  |
| Nuevo, soak `/rl_state` (×3)                | 33–40 ms  | 71–111 ms  | 0–0,3 %       | 25–30 Hz   |

El dato más valioso de esa campaña no es la mejora sino **cómo se aisló la causa**: se
verificó en tres flasheos OTA iterativos (`setSleep(false)` → `+WIFI_PS_NONE` → `+beacon
300 ms`) y **los dos primeros no quitaron los picos; el beacon sí**. Eso descarta el
modem-sleep como causa y deja a la **coexistencia AP+STA** como responsable **[M]**.

De ahí se sigue el argumento central de este documento: si la coexistencia es la causa y
el beacon es sólo un paliativo, **eliminar el rol STA es atacar la causa** **[D]**.

### 2.3 Lo que la latencia sí y no compromete

El período del modo 6 es de 20 ms (50 Hz) y el round-trip mide 32 ms de media **[M]**:
el lazo PC-en-el-lazo **no cierra a su frecuencia nominal**, y ésa es la razón por la
que existe el modo 7 on-device como ruta alternativa. Los modos autónomos —PID, homing,
LQR, swing-up y el propio modo 7— se cierran dentro de la ESP32 a 500 Hz y **no dependen
del enlace** **[D]**. Conviene tenerlo presente para no sobrevender el cambio: SoftAP
puro puede mejorar el modo 6 y la calidad de la telemetría, pero no altera el desempeño
de control de los modos que hoy funcionan.

### 2.4 Instrumentación que ya existe y que sirve de juez

No hace falta construir un banco de medición nuevo. El firmware ya expone tres campos
pensados exactamente para esto (`docs/http_api.md:74-81`):

- `loop_dt_max_us` — peor período real del lazo de control desde el último reset.
- `loop_overruns` — veces que el atraso superó cinco períodos y hubo que resincronizar.
- `loop_dt_nom_us` — el nominal, 2000 µs.

Se resetean con `GET /cmd?rj=1`, y la propia documentación advierte que hay que llamarlo
**al arrancar** cada captura porque el peor caso del arranque —el escaneo WiFi
bloqueante— domina si no se reinicia el contador. Ese detalle es, por sí solo, un
argumento menor a favor de SoftAP puro: **sin STA no hay escaneo que bloquee el
`setup()`** **[D]**.

Como referencia cualitativa complementaria, el `README.md` de la demo declara que el
lazo de la ESP32 "llega a bloquearse ~95 ms cuando el WiFi le roba tiempo" **[M]**.

---

## 3. Qué cambia realmente al pasar a SoftAP puro

El cambio parece trivial —una constante booleana— pero **invierte los roles de radio**,
y ahí está lo interesante. Hoy la ESP32 es una *estación* del router; mañana el **PC
pasa a ser estación de la ESP32**. Todo lo que se optimizó del lado del ESP32 sigue
valiendo, pero aparece un actor nuevo cuya política de energía nadie controló hasta
ahora: el adaptador WiFi del portátil.

### 3.1 Lo que desaparece

| Se elimina                                          | Consecuencia                                                                     |
| --------------------------------------------------- | -------------------------------------------------------------------------------- |
| Coexistencia AP+STA en una radio                     | Desaparece la causa raíz medida de los picos de ~100 ms **[D]**                  |
| Escaneo bloqueante de canal en `setup()` (`:2562`)  | Arranque más rápido y determinista; `loop_dt_max_us` limpio desde el inicio **[D]** |
| Guardián de reconexión STA en `loop()` (`:2815`)    | Un condicional menos por iteración del lazo de 500 Hz **[D]**                    |
| Dependencia del canal del router                     | El canal del AP pasa a ser una **decisión propia** (1, 6 u 11 según el espectro) **[D]** |
| Credenciales del laboratorio en NVS                  | Menos estado oculto; se acaba el "funcionaba y ahora no" tras cambiar la red      |
| IP variable                                          | `192.168.4.1` **siempre**, sin DHCP del router ni reservas                        |

### 3.2 Lo que aparece: el power-save del adaptador del PC

Este es el punto que puede arruinar el experimento si no se documenta, y es
contraintuitivo. En la configuración actual, la parte que podía dormirse era la ESP32, y
se le prohibió explícitamente con `esp_wifi_set_ps(WIFI_PS_NONE)` (`:2591`). En SoftAP
puro **la ESP32 deja de ser quien duerme**: quien puede entrar en power-save es el
adaptador del PC, y frente a una estación que se duerme un punto de acceso **no
descarta**, sino que **almacena** las tramas hasta el próximo DTIM.

El síntoma reportado en el foro de Espressif es exactamente ése: con un SoftAP enviando
cada 70 ms, llegaban **tres mensajes juntos y después una pausa de ~200 ms**, y el efecto
empeoraba al conectar un segundo cliente **[E]**. Traducido a este banco: la media
podría mejorar y **la cola empeorar**, que es justo la métrica que importa en un lazo de
control. La mitigación es de configuración del PC, no de firmware:

- Windows: *Administrador de dispositivos → adaptador WiFi → Opciones avanzadas →*
  **modo de ahorro de energía = máximo rendimiento**; y en *Opciones de energía*,
  plan de alto rendimiento con "Configuración del adaptador inalámbrico" en máximo
  rendimiento.
- Verificar el efecto **midiendo**, no confiando en la casilla: el A/B de la sección 9
  debe correrse con esa configuración ya aplicada y declarada.

### 3.3 Otras consecuencias

- **Cuatro clientes como máximo** (`:2569`), que además es el valor por defecto de
  ESP-IDF. Suficiente para PC + teléfono, pero el AP no es una red de laboratorio: cada
  cliente extra compite por el mismo aire y agrava el efecto de ráfagas **[E]**.
- **Sin acceso desde otros equipos de la LAN.** Se pierde la posibilidad de abrir la GUI
  desde cualquier máquina de la sala, y el OTA por WiFi sólo funciona estando asociado
  al AP de la ESP32.
- **El PC pierde salida a internet por WiFi** mientras esté asociado. En un portátil con
  Ethernet esto se resuelve con métricas de ruta (sección 8); en uno sin Ethernet,
  MLflow local sigue funcionando pero OneDrive y la búsqueda web no.
- **El SoftAP desasocia por inactividad** a una estación de la que no recibe datos
  durante un tiempo (300 s por defecto en ESP-IDF) **[E]**. Una app que hace *polling*
  continuo nunca lo alcanza, pero conviene saberlo si se deja el banco en reposo.

---

## 4. Arquitecturas de transporte evaluadas

Se evalúan cinco opciones. Las tres primeras conviven con SoftAP puro sin hardware
nuevo; las dos últimas se resumen para no re-litigar lo ya decidido en el `README.md`.

| # | Transporte                          | Latencia esperada | Cambio de firmware | Riesgo | Veredicto                        |
| - | ----------------------------------- | ----------------- | ------------------ | ------ | -------------------------------- |
| 1 | HTTP/JSON actual (`/rl_step`, `/state`) | 32 ms hoy **[M]** | ninguno            | nulo   | **Base de comparación**          |
| 2 | WebSocket `/ws` + HTTP para comandos | ~10 Hz sostenido **[D]** | ninguno       | bajo   | **Recomendado para la app**      |
| 3 | UDP binario punto a punto            | 5–10 ms **[E]**   | medio              | alto   | Fuera de alcance; ver 4.3        |
| 4 | USB serial directo                   | 2–6 ms **[E]**    | medio              | bajo   | Descartado por requisito de banco |
| 5 | ESP-NOW con dongle                   | 1–6 ms **[E]**    | alto (+ 2ª ESP32)  | medio  | Trabajo futuro, ya decidido      |

### 4.1 HTTP/JSON (lo que hay)

Es la base contra la que se compara y **no requiere tocar nada**. Sus virtudes son
prácticas: `curl` funciona, la MCP funciona, `QubeRealEnv` funciona, y el protocolo está
versionado con `pv` de modo que un desajuste firmware/Python falla ruidosamente en
`reset()` en lugar de entrenar con observaciones de signo equivocado
(`qube_real.py:33-41`). El cliente ya está optimizado hasta donde da: una sola conexión
TCP con keep-alive (`qube_real.py:144-151`) y `http_timeout` de 0,4 s para reintentar
rápido en vez de congelar el lazo (`qube_real.py:86`).

Su costo es la pila: TCP + HTTP + JSON sobre un `AsyncWebServer`, para mover cuatro
flotantes. Es el precio que se paga por la interoperabilidad.

### 4.2 WebSocket para telemetría, HTTP para comandos — **la opción recomendada**

Ya está implementado y desaprovechado. El firmware mantiene `AsyncWebSocket ws("/ws")`
(`:990`) y difunde el JSON completo de estado cada `telemetryPeriodMs` (100 ms por
defecto, ajustable por `/cmd?tp=`, rango 50–5000 ms). Hoy sólo lo consume el
`index.html`; una app de escritorio puede suscribirse con la librería `websockets` de
Python sin **ninguna** modificación de firmware **[D]**.

La ventaja frente al *polling* HTTP es estructural, no marginal: el flujo pasa a ser
**push**, se elimina un round-trip por muestra y desaparecen la cabecera HTTP y el
handshake por lectura. Para adquisición de datos —que es el uso de la app— eso importa
más que la latencia absoluta: lo que se busca es una **serie temporal regular**, y una
difusión periódica desde el dispositivo tiene mucho mejor comportamiento temporal que
una secuencia de peticiones lanzadas desde el PC.

Dos límites honestos: la difusión sigue decimada a 500 ms durante el modo 6 (`:639`), lo
cual está bien justificado en el firmware; y el JSON completo de `/state` es grande —
supera los cuarenta campos—, de modo que subir la tasa por encima de ~20 Hz haría que la
serialización compita con el lazo de control **[E]**. Si la app necesita alta tasa, lo
sensato es un endpoint compacto, no forzar el existente.

### 4.3 UDP binario punto a punto — evaluado y descartado por ahora

Es la opción tentadora: cuatro flotantes en un datagrama de ~20 bytes, sin TCP, sin
JSON. La medición externa de referencia da ~9 ms de mediana para UDP entre dos ESP32,
contra ~6 ms de TCP optimizado **[E]** — es decir, **UDP no ganó** en ese banco, lo que
ya debería moderar el entusiasmo.

Y hay tres trampas concretas, todas documentadas:

1. **UDP se comporta peor en modo AP que en STA.** Un reporte de ESP-IDF mide ~25 % de
   paquetes no transmitidos en modo AP contra 1–2 % en STA **[E]**. Precisamente el modo
   al que se quiere migrar.
2. **Jitter de encolado en lwIP.** El propio issue abierto en ESP-IDF describe latencias
   base de 540 ± 200 µs con **acumulaciones esporádicas de 10–20 ms** liberadas en
   ráfaga, sin causa confirmada por Espressif **[E]**. Un lazo de control no tolera
   colas invisibles.
3. **Enlace de sockets en AP+STA.** En modo APSTA los sockets tienden a atarse a la
   interfaz STA, un problema clásico que desaparece en SoftAP puro pero que hay que
   conocer si alguna vez se vuelve al modo dual **[E]**.

A eso se suma el costo propio: protocolo binario nuevo, versionado nuevo, pérdida sin
retransmisión y una segunda ruta de datos que mantener en paralelo a la HTTP. Se
documenta como camino disponible, no como recomendación.

### 4.4 USB serial y ESP-NOW (ya decididos)

El `README.md:264-278` deja fijada la decisión y este documento no la reabre. En
síntesis: el **USB serial** (~2–6 ms) reintroduce el amarre físico PC↔equipo que la
modernización buscaba eliminar; **ESP-NOW** (~1–6 ms, inalámbrico) exige una segunda
ESP32 como puente porque el WiFi del PC no habla ESP-NOW, y su costo en hardware y
complejidad lo dejó como trabajo futuro. La medición externa ubica ESP-NOW en 5,6 ms de
mediana para 12 bytes **[E]**, algo por encima del "1–3 ms" que se cita habitualmente:
otro dato que conviene tener a la vista antes de invertir en el dongle.

### 4.5 Referencias externas usadas

Analizadas en detalle —con metodología, cifras y limitaciones— en
`docs/literature_studies/electricui-latency-benchmark.md`.

- Comparativa de latencia de enlaces para microcontroladores (Electric UI), con
  metodología de analizador lógico a 100 Msps y tres tamaños de carga:
  <https://electricui.com/blog/latency-comparison>
- UDP en modo AP con peor desempeño que en STA (ESP-IDF #2985):
  <https://github.com/espressif/esp-idf/issues/2985>
- Ráfagas y pausas de ~200 ms en SoftAP con clientes asociados:
  <https://esp32.com/viewtopic.php?t=36754>
- Jitter de encolado en el envío UDP, abierto y sin respuesta (ESP-IDF #15345):
  <https://github.com/espressif/esp-idf/issues/15345>
- Sockets atados a la interfaz STA en modo APSTA (arduino-esp32 #1946):
  <https://github.com/espressif/arduino-esp32/issues/1946>
- Referencia de `esp_wifi`: `max_connection` por defecto 4, desasociación por
  inactividad: <https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/network/esp_wifi.html>

---

## 5. La aplicación de escritorio

### 5.1 Stack propuesto

**Python + PySide6 + pyqtgraph.** La elección no es de gusto: el repositorio ya es
Python gestionado con `uv`, linteado con `ruff` y probado con `pytest` (`Makefile`), de
modo que una app en Python **hereda el entorno, el CI y las convenciones** en lugar de
abrir una segunda cadena de herramientas. Y `pyqtgraph` está construido sobre Qt con
aceleración por hardware, capaz de sostener cuatro trazas a 50–100 Hz durante minutos,
mientras que Chart.js en el navegador —el motor de la GUI actual— degrada mucho antes al
acumular miles de puntos **[E]**.

### 5.2 Reutilizar antes que reescribir

Buena parte de la app ya está escrita, dispersa en el repositorio:

| Qué se reutiliza                                          | Dónde vive                          |
| --------------------------------------------------------- | ----------------------------------- |
| Cliente HTTP con `Session` keep-alive y timeout corto      | `src/qube_rl/envs/qube_real.py:144-151`, `:86` |
| Secuencias de operación, reintentos y corte seguro al salir | `demo/demo_avance.py`               |
| Esquema completo de campos de telemetría y comandos        | `docs/http_api.md`                  |
| Homing con sus modos de falla y códigos                    | `qube_real.py` (lógica de `homing_*`) |
| Métricas de salud del lazo                                 | `/cmd?rj=1` + campos `loop_*`       |

El manejo de fallos de `demo/demo_avance.py` merece copiarse tal cual, porque ya
incorpora criterio ganado en banco: bloques aislados que no se arrastran entre sí,
homing con hasta tres reintentos, y corte del motor reintentado quince veces antes de
declarar alarma. Una app de escritorio que se quede corta en eso será **peor** que los
scripts que reemplaza.

### 5.3 Qué debe hacer la aplicación

1. **Telemetría en vivo** por WebSocket `/ws`, con gráficos de servo, péndulo, PWM y
   potencia, y reconexión automática silenciosa.
2. **Control de modos** (0 a 7) con confirmación explícita para los que mueven el brazo
   —homing y swing-up—, dado que ambos lo llevan contra los topes.
3. **Ajuste de parámetros**: PID, LQR, gain scheduling, Kalman, período de telemetría.
4. **Grabación** a CSV o Parquet con **doble marca de tiempo**: la del PC y la del
   ESP32. Es la única forma de separar, después, el retardo de transporte del retardo
   real del sistema; con una sola marca esa distinción se pierde para siempre.
5. **Paro de emergencia siempre visible**, con atajo de teclado, cableado a `/cmd?x=1`.
6. **Indicador de salud del enlace**: latencia instantánea, pérdidas, y
   `loop_dt_max_us` / `loop_overruns` leídos del propio dispositivo. Que la app muestre
   la calidad del canal por el que ella misma habla es lo que permite confiar en los
   datos que registra.

### 5.4 Qué **no** debe hacer

**No debe cerrar el lazo de control.** El lazo vive en la ESP32 a 500 Hz y ahí debe
seguir. La app es interfaz y adquisición; la única excepción legítima es el modo 6, que
por definición pone al PC en el lazo y que ya tiene su camino propio en `QubeRealEnv`.
Tampoco debe convertirse en un segundo escritor concurrente: el contrato de concurrencia
documentado en `qube_real.py:6-12` advierte que escribir desde dos clientes a la vez es
*último que escribe gana*. Si la app y un entrenamiento RL corren juntos, **la app debe
quedar en modo lectura**.

---

## 6. Seguridad y modo de fallo

### 6.1 El watchdog no cubre todo, y eso no cambia

El failsafe por pérdida de comandos vigila **solamente** los modos 1 (PWM manual) y 6
(RL por HTTP): 2,5 s de tolerancia para el primero, 10 s para el segundo
(`esp32_qube.ino:659`, `:663`, `:2757-2762`). Los modos 2, 3, 4 y 5 son autónomos por
diseño y **siguen corriendo aunque el enlace muera**; el único respaldo entonces es el
límite duro del brazo, `SERVO_HARD_LIMIT_DEG = 95°` (`:700`), que dispara `setMode(0)`.

Esto es importante para calibrar expectativas: **pasar a SoftAP puro no hace el banco
más peligroso, pero tampoco más seguro**. Lo que cambia es la probabilidad de perder el
enlace, y en principio baja al eliminar la dependencia del router. La app debe declarar
esta limitación en su interfaz, y el corte de alimentación debe seguir a mano.

### 6.2 Superficie expuesta por el AP

- Clave WPA2-PSK **fija y en el código fuente** (`:979-980`). Quien haya leído el
  repositorio puede asociarse. Para un banco de laboratorio es aceptable; conviene
  cambiarla antes de una demostración pública, y no publicarla en la tesis.
- Sobre el mismo AP quedan expuestos **OTA por HTTP** (`/update`), **subida a SPIFFS**
  (`/fs`), **reinicio** (`/restart`) y **formateo** (`/format`), todos sin
  autenticación (`:2608-2675`). En SoftAP puro esa superficie se **reduce** respecto a
  hoy, porque deja de estar alcanzable desde toda la LAN de la universidad y pasa a
  requerir asociación al AP **[D]**. Es, de hecho, una ventaja de seguridad no obvia.
- El AP es **visible** (SSID no oculto, `:2569`). Ocultarlo no aporta seguridad real y
  complica la conexión; no se recomienda cambiarlo.

---

## 7. Ventajas y desventajas

### 7.1 Ventajas

| # | Ventaja                                                                                       | Evidencia |
| - | --------------------------------------------------------------------------------------------- | --------- |
| 1 | Elimina la coexistencia AP+STA, causa raíz identificada de los picos de ~100 ms                | **[D]** sobre medición **[M]** |
| 2 | El canal deja de estar impuesto por el router: se puede elegir el menos congestionado           | **[D]**   |
| 3 | Desaparece el escaneo bloqueante de `setup()`, que hoy contamina `loop_dt_max_us` al arrancar  | **[D]**   |
| 4 | Un condicional menos por iteración del lazo de 500 Hz (guardián STA)                            | **[D]**   |
| 5 | Dirección fija garantizada `192.168.4.1`: se acaba la IP variable y su troubleshooting          | **[D]**   |
| 6 | Banco autónomo: funciona sin router, sin credenciales y sin la red de la universidad            | **[D]**   |
| 7 | Portabilidad real para defensa o feria: se enciende y funciona en cualquier sala                | **[D]**   |
| 8 | Reduce la superficie expuesta: OTA, `/format` y `/fs` dejan de ser alcanzables desde la LAN     | **[D]**   |
| 9 | Menos estado oculto: sin credenciales en NVS, se acaba el "funcionaba y dejó de funcionar"      | **[D]**   |
| 10 | Mejora esperada de latencia y jitter en el lazo del modo 6                                     | **[E]** — **por medir** |
| 11 | Telemetría de mayor tasa y más regular por WebSocket, útil para las trazas de la tesis         | **[E]**   |

### 7.2 Desventajas

| # | Desventaja                                                                                      | Evidencia |
| - | ----------------------------------------------------------------------------------------------- | --------- |
| 1 | El PC pierde internet por WiFi mientras está asociado (mitigable con Ethernet)                   | **[D]**   |
| 2 | Aparece el power-save del adaptador del PC como fuente nueva de ráfagas y pausas de ~200 ms      | **[E]**   |
| 3 | Máximo cuatro clientes, y cada cliente extra degrada el canal                                    | **[D]**/**[E]** |
| 4 | Sin acceso desde otros equipos de la sala: se pierde la GUI "desde cualquier navegador"          | **[D]**   |
| 5 | El OTA por WiFi exige estar asociado al AP de la ESP32                                           | **[D]**   |
| 6 | Los scripts, la demo y la documentación apuntan a `192.168.100.50` y hay que migrarlos            | **[D]**   |
| 7 | El SoftAP desasocia por inactividad prolongada (300 s sin datos, por defecto)                     | **[E]**   |
| 8 | La mejora de latencia **no está medida en este banco**: hoy es una hipótesis razonada             | **[E]**   |
| 9 | Aunque mejore, puede seguir por encima del período de 20 ms del modo 6                            | **[E]**   |
| 10 | La app de escritorio es trabajo nuevo que hay que mantener, frente a una GUI web que ya funciona | —         |

---

## 8. Riesgos operativos y cómo detectarlos

| Síntoma                                                | Causa probable                                                        | Verificación                                                                 |
| ------------------------------------------------------ | --------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Windows marca "Sin internet" y se desconecta sola       | Windows prefiere una red con salida a internet                        | Desmarcar "Conectar automáticamente" en las demás redes; fijar la conexión al AP |
| MLflow, `uv` u OneDrive dejan de sincronizar            | Toda la salida se fue por el AP sin internet                          | Usar Ethernet en paralelo y revisar `route print`: la métrica del Ethernet debe ser menor |
| Muestras que llegan en ráfagas con pausas de ~200 ms    | Power-save del adaptador del PC; el AP buferea hasta el DTIM          | Poner el adaptador en máximo rendimiento y **repetir la medición**            |
| La media mejora pero el máximo empeora                  | El mismo buffering: mueve latencia de la media a la cola              | Mirar p95 y máximo, nunca sólo la media                                      |
| La ESP32 se desasocia sola tras un rato en reposo       | Desasociación por inactividad del SoftAP                              | Mantener el *polling* de la app o reconectar; no es una falla                |
| No mejora nada respecto a AP+STA                        | El cuello no era la coexistencia sino la pila HTTP/JSON               | Comparar contra la fila de 32 ms del CHANGELOG; si empata, ver sección 10    |
| Ya no se puede abrir la GUI desde el teléfono            | Consecuencia esperada del AP puro                                     | Asociar el teléfono al AP (cuenta contra el límite de 4)                     |
| Un flasheo OTA deja la placa inalcanzable                | Se subió firmware con el AP mal configurado                           | Recuperación siempre disponible por USB con `flash.py`                        |

Sobre el punto de Ethernet: es la objeción operativa más probable en el uso diario, y
tiene solución limpia. Windows enruta por la interfaz de **menor métrica**, así que con
el cable conectado el tráfico general sigue saliendo por Ethernet mientras el
`192.168.4.0/24` se resuelve por WiFi. Conviene verificarlo con `route print` antes de
una sesión larga y no descubrirlo a mitad de un entrenamiento.

---

## 9. Protocolo de medición para decidir

La recomendación de la sección 1 queda **condicionada** a este experimento. Está
diseñado para ser corto —menos de una hora de banco— y para no admitir interpretaciones
a posteriori.

### 9.1 Criterio de decisión, escrito antes de medir

Se adopta SoftAP puro si, respecto a la configuración actual y en la misma sesión:

- la **media** del round-trip `/rl_step` baja de forma clara —al menos un 20 %—, **y**
- el **p95 no empeora**, **y**
- la fracción de muestras por encima de 20 ms **no aumenta**.

Se rechaza si el p95 o el máximo empeoran, aunque la media mejore: en un lazo de control
la cola pesa más que el promedio, y ese fue exactamente el aprendizaje de la campaña de
julio, donde eliminar los picos importó más que bajar la media.

### 9.2 Procedimiento

1. **Misma sesión, mismo montaje, mismo día.** Nada de comparar contra la tabla de julio:
   el laboratorio de hoy no tiene el mismo espectro que el de entonces.
2. Adaptador WiFi del PC en **máximo rendimiento**, y dejarlo declarado en el registro.
3. Corrida A — firmware actual (`ENABLE_STA = true`), conectando por `192.168.100.50`.
4. Corrida B — firmware con `ENABLE_STA = false`, conectando por `192.168.4.1`.
5. En cada corrida, con el péndulo **quieto** y **sin mover el motor** (`a=0`, replicando
   las condiciones de la tabla del CHANGELOG):
   - `GET /cmd?rj=1` al inicio, para resetear las métricas del lazo.
   - N ≥ 2000 peticiones `/rl_step?a=0` con `requests.Session` keep-alive, registrando
     cada round-trip individual.
   - Al terminar, `GET /state` y anotar `loop_dt_max_us` y `loop_overruns`.
6. Repetir A y B **al menos dos veces cada una, alternadas** (A, B, A, B), para que una
   interferencia pasajera no se lea como efecto del cambio.

### 9.3 Qué reportar

| Métrica                      | Por qué                                                        |
| ---------------------------- | --------------------------------------------------------------- |
| media, p50, **p95**, máximo  | La cola decide; la media sola engaña                            |
| fracción de muestras >20 ms  | Es literalmente la fracción de pasos que no cierran a 50 Hz      |
| throughput sostenido (Hz)    | Comparable con la columna del CHANGELOG                          |
| `loop_dt_max_us`             | Cuánto le robó la radio al lazo de 500 Hz                        |
| `loop_overruns`              | Cuántas veces hubo que resincronizar el lazo                     |
| fallos y reintentos          | Un enlace rápido que pierde paquetes no sirve                     |

Los resultados van a `experiments/` con fecha, y el resumen a `CHANGELOG.md`. Si la
decisión termina siendo negativa **también hay que escribirla**: un experimento que
descarta una hipótesis con evidencia vale tanto como uno que la confirma, y este
proyecto ya tiene precedente de mediciones contaminadas que costaron caro por no quedar
registradas a tiempo.

---

## 10. Relación con ESP-NOW y trabajo futuro

SoftAP puro **no compite** con la migración a ESP-NOW: la antecede. Es el paso barato
—una constante, reversible, sin hardware nuevo— que además entrega dos beneficios
independientes de la latencia y que hoy son molestias reales: la autonomía del banco y
la dirección fija. Si el experimento de la sección 9 muestra que el enlace sigue por
encima de los 20 ms, la conclusión del `README.md:264-278` se mantiene intacta y el
camino sigue siendo el puente ESP-NOW o el USB directo, con el modo 7 on-device como
ruta ya operativa sin red.

Hay, además, una sinergia que conviene anotar: el plan de ESP-NOW contempla **soltar el
SoftAP** durante el lazo de RL para no reintroducir jitter de coexistencia. Un firmware
que ya sepa arrancar en un solo rol de radio —lo que este cambio introduce— llega a esa
migración con la mitad del trabajo hecho.

Queda pendiente, en cualquier caso, lo que este documento no resuelve y que sería el
siguiente paso natural si la app de escritorio prospera: un **endpoint compacto de
telemetría** —binario o JSON reducido— que permita registrar a 50 Hz o más sin que la
serialización del estado completo compita con el lazo de control. Hoy esa limitación
está reconocida en el propio firmware, que decima la difusión a 500 ms durante el modo
6 precisamente para no robar tiempo de aire.

---

## Referencias internas

- `src/firmware/esp32_qube/esp32_qube.ino` — configuración de radio, endpoints, failsafe
- `CHANGELOG.md`, v1.50.0 (2026-07-08) — campaña de latencia con resultados medidos
- `README.md:264-278` — nota de diseño sobre por qué la telemetría sigue siendo inalámbrica
- `docs/http_api.md` — esquema completo de endpoints, campos y modos
- `docs/mine/GUI_WEB_WEBSOCKET.md` — arquitectura de la GUI web actual (parcialmente desactualizada)
- `src/qube_rl/envs/qube_real.py` — cliente HTTP del lazo RL y contrato de concurrencia
- `demo/demo_avance.py` y `demo/README.md` — operación real y tolerancia a fallos
