# Resultados — Validación exhaustiva, 2026-07-30

**24 repeticiones (8 modos × 3), 0 errores. 8/8 modos aprobados.**

## Veredictos

| modo | | resultado |
|---|---|---|
| m0 | STOP | **PASS** — motor inerte |
| m1 | PWM manual | **PASS** — error de seguimiento ≤ 1, movió en ambos sentidos |
| m2 | PID servo | **PASS** — error en régimen máx 4.79° (umbral 8) |
| m3 | Homing | **PASS** — recorrido 268.24–269.65° |
| m4 | LQR | **PASS** — acciona el motor 100% del tiempo en modo; **sobrevive 0,3 s** |
| m5 | Swing-up | **PASS** — traspasa a LQR en las 3; criterio `forced` ×2, `peak` ×1 |
| m6 | Deep RL (HTTP) | **PASS** — una acción no nula mueve el motor |
| m7 | Deep RL (chip) | **PASS** — acciona 96–100% del tiempo; sobrevive los 10 s |

**"Aprobado" significa que el modo hace lo que declara, no que controle bien.** m4
aprueba porque acciona el motor; que sólo dure 0,3 s es desempeño, no funcionalidad.

## Hallazgo principal: el homing acepta calibraciones malas

De las 24 corridas de homing, **3 midieron un recorrido ~19° corto y aun así fueron
aceptadas**:

| corrida | recorrido | tope + | tope − |
|---|---|---|---|
| pre-m1 rep3 | **250.31** | −124.81 | 125.51 |
| pre-m2 rep1 | **250.84** | −125.33 | 125.51 |
| pre-m1 rep2 | **251.72** | −126.21 | 125.51 |
| *(las otras 21)* | 268.24–270.18 | −142.7 a −145.4 | 124.81–125.51 |

Pasaron por poco la ventana de 250–290°. **Un cero corrido ~10° se dio por bueno.**

Y el patrón confirma, con mucha más fuerza, lo que se había visto en el barrido de
modos del mismo día:

- **Tope negativo: 124.81–125.51° en las 24 corridas** → dispersión 0.70° (4 conteos).
- **Tope positivo: −124.81 a −145.37°** → dispersión 20.56°.

Toda la variabilidad está en el tope positivo. El negativo se repite casi exacto.

### Mecanismo

`SEEK_NEG` siempre arranca desde el tope opuesto: carrera constante de ~270°, misma
velocidad terminal, misma penetración. `SEEK_POS` arranca desde donde haya quedado el
brazo. Las 3 corridas malas vienen **inmediatamente después de `m1`**, el único modo
que empuja el brazo a PWM fijo contra los topes y lo deja con el péndulo agitado. La
hipótesis es un **calado falso**: el péndulo oscilando frena el brazo lo suficiente
como para que el detector (0,5° en 120 ms) lo lea como tope, 19° antes del real.

Es hipótesis, no conclusión: no se corrió el experimento que la probaría.

### Acciones que sugiere

1. **Apretar la ventana a ~262–278°.** El recorrido real es 268–270; 250 como piso
   deja pasar exactamente este fallo. Es un cambio de una línea.
2. Endurecer `WAIT_QUIET` o exigir dos toques coincidentes en el lado positivo.
3. Que `QubeRealEnv` compare el `range` nuevo contra el histórico y avise ante un
   salto, en vez de confiar sólo en la ventana absoluta.

## Otros resultados

### m2 PID: repetible pero con sobrepaso alto
Error en régimen **4.77–4.79°** (dispersión 0.009° — notablemente repetible).
Sobrepaso **68–77%**, bastante peor que el ~25% del barrido anterior, porque acá el
escalón +20° → −20° es de 40°, no de 25°.

### m4 LQR: muere en 0,3 s
Desde brazo centrado y péndulo colgando, el LQR satura hacia un lado y cruza los 95°
en **0,3 s** en las 3 repeticiones. No es que "no aguante": no llega a intentarlo.

### m5 Swing-up: aparece `peak`, sigue sin capturar
Dos repeticiones traspasaron por `forced` y una por `peak` (α=120.41, `E/E*`=0.754).
Picos de α 121.3–130.1°, con vertical en 180°. `E/E*` de 0.75–0.87: la energía nunca
alcanza. Coincide con `experiments/2026-07-30_swingup/`.

### m7: el único que se sostiene 10 s
Acciona 96–100% del tiempo, σ(PWM) ≈ 97–104, y **no cruzó el límite** en ninguna
repetición. Tampoco balancea, pero es el único modo de vertical que no se autodestruye.

## Defectos de instrumentación encontrados (y corregidos)

Los anoto porque afectan cómo leer los números crudos:

1. **`pwm_active_frac` sobre la ventana completa daba falso negativo.** m4 salía
   "motor prácticamente inactivo" (4%) cuando accionaba el **100%** del tiempo que
   estuvo vigente — el otro 96% de la ventana era post-`safeStop`. Corregido con
   `pwm_active_frac_inmode` + `time_in_mode_s`, que separa *acciona* de *cuánto dura*.
2. **`sample_hz` está inflado en los modos multi-tramo** (m1, m2, m6): `record()`
   reinicia `t_s` en cada tramo, así que el cálculo divide el total de muestras por la
   duración del último tramo. Los valores reales son ~13 Hz, como en los modos de un
   solo tramo. **Los 40–74 Hz de esos modos no son reales.**
3. En `analyze.py`, `alpha traspaso` promedia valores con signo y la etiqueta
   `centro (m3)` en realidad imprime recorridos. Cosmético, pero no leer esas dos.

La tasa real de ~13 Hz viene de la latencia HTTP (~40 ms por `/state`) más la pausa
deliberada de 40 ms, necesaria para no tumbar el AsyncTCP del ESP32.
