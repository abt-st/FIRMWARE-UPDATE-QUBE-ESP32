# 2026-07-30 — Barrido funcional de los 8 modos

## Objetivo

Verificar que cada modo `m0..m7` del firmware entra y hace lo que declara, después
de dos cambios que tocaron el despacho de modos:

- **v1.53.x** — `m3` dejó de ser un hueco y pasó a ser el homing por topes.
- **v1.54.0** — `QubeRealEnv` puede disparar el homing solo.

Lo que hace posible esta campaña es justamente el homing. Hasta ahora, un modo que
derivara el brazo al tope dejaba el banco trabado: `|servo| > 95°` dispara
`safeStop()` en **todos** los modos y ninguno lo revertía, así que había que mover el
brazo a mano. Ahora `m3` está exento de ese chequeo y la campaña se recupera sola
entre modos.

## Configuración

| | |
|---|---|
| Firmware | v1.53.2 (`HOMING_PWM_SEEK=55`, ventana de recorrido 250–290°) |
| Placa | ESP32 @ 192.168.100.50, `ina_ok=true`, `v_bus` ≈ 14.8 V |
| Driver | L298N |
| Encoder brazo | 2048 CPR → 0.176 °/conteo |
| Muestreo | `/state` a 20 Hz |
| Permanencia | 8 s por modo (18 s en `m3`, que dura ~10 s) |
| Homing | uno antes de cada modo, para que `position_deg` sea comparable entre modos |

## Qué NO es esto

**No es una medida de desempeño de control.** Los modos de vertical (`m4`, `m5`,
`m7`) se probaron con el péndulo colgando, que no es su punto de operación. Acá sólo
se comprueba que responden, mueven el motor y terminan de forma limpia.

`m6` se corrió **sin política entrenada en el lazo** (sólo acción 0.0): lo único
atribuible es el round-trip del protocolo, no el comportamiento del agente.

## Resultados

Los 8 modos entraron correctamente (`entered_mode: true` en todos).

| modo | | PWM máx | \|θ\| máx | \|α\| máx | desenlace |
|---|---|---|---|---|---|
| m0 | STOP | 0 | 4.9° | 0.0° | motor en 0 todo el tramo |
| m1 | PWM manual | 59 | 129.4° | 18.8° | cruzó el límite blando → `safeStop` |
| m2 | PID servo | 62 | 31.2° | 9.3° | **converge**, sin cortes |
| m3 | Homing | 55 | 135.1° | 29.2° | termina solo en `m0`, exento del límite por diseño |
| m4 | LQR | 69 | 122.7° | 20.6° | deriva monótona al tope → `safeStop` |
| m5 | Swing-up | 65 | 121.5° | **117.4°** | traspaso a `m4`, luego `safeStop` |
| m6 | Deep RL (HTTP) | 0 | 6.7° | 2.6° | protocolo OK (sin política) |
| m7 | Deep RL (chip) | 186 | 70.4° | 40.3° | inferencia activa, sin cortes en 8 s |

### `m2` es el único que hace control limpio

Setpoint 25° → θ máx 31.2° (sobrepaso ~25%), luego setpoint 0 → θ mín −8.0°.
Converge sin tocar el límite. Consistente con lo ya sabido: ajuste suelto, con
sobrepaso, pero estable.

### `m1`: el `safeStop` funciona

A PWM 60 el brazo cruza los 95° en poco más de un segundo y el firmware corta. Llegó
a 129.4° por inercia después del corte — el puente queda en corte, no en freno.
Es el comportamiento diseñado, no una falla.

### `m5`: hay traspaso automático, pero no captura

```
t=0.00   m5   swing-up bombeando
t=4.28   |α| = 117.4°   (máximo)
t=4.64   m5 → m4        traspaso automático con α = 105.1°
t=6.05   m4 → m0        θ = 97.0° > 95° → safeStop
```

El bombeo llegó a 117° y el firmware entregó el control al LQR solo. **Pero vertical
son 180° en esta convención**, así que el péndulo nunca llegó arriba: el traspaso se
disparó 75° antes. El LQR aguantó ~1.4 s y el brazo derivó al límite.

**Limitación de la medición:** el firmware imprime cuál de los cuatro criterios de
transición se cumplió (`canTransition` / `atPeakTransition` / `forcedTransition` /
`energyReady`) **sólo por serial**, y el monitor serial reinicia la placa. Con la
telemetría HTTP disponible hoy no es posible atribuir el traspaso a un criterio
concreto. Sería un buen candidato a exponer en `/state`.

### `m4` y `m7`

`m4` reprodujo la deriva monótona del brazo al tope ya conocida. `m7` corrió
inferencia de verdad —PWM activo el 95.7% del tramo, hasta 186 de 200— y fue el único
modo de vertical que **no** cruzó el límite en 8 s, aunque tampoco balanceó.

## Hallazgo secundario: la dispersión del homing está toda en un tope

Las 7 corridas de homing de la campaña ocurrieron **sin reinicio de por medio**, así
que comparten marco `raw` y son directamente comparables. Reconstruyendo los topes
desde `homing_range` y `homing_center`:

| homing previo a | recorrido | centro | tope + | tope − |
|---|---|---|---|---|
| m1 | 268.94 | 0.53 | −133.94 | **135.00** |
| m2 | 269.12 | 0.44 | −134.12 | **135.00** |
| m3 | 269.47 | 0.26 | −134.48 | **135.00** |
| m4 | 269.65 | 0.18 | −134.64 | **135.00** |
| m5 | 270.00 | 0.00 | −135.00 | **135.00** |
| m6 | 269.65 | 0.18 | −134.64 | **135.00** |
| m7 | 269.47 | 0.26 | −134.48 | **135.00** |

- Dispersión del **tope −: 0.010°** — por debajo de un conteo de encoder (0.176°).
- Dispersión del **tope +: 1.060°** — unos 6 conteos.

Toda la variabilidad del recorrido está en el tope positivo; el negativo se repite
exacto. Eso es coherente con cómo funciona la rutina: `SEEK_NEG` siempre arranca
desde el tope positivo, o sea con una carrera **constante** de 270° y por lo tanto
misma velocidad terminal y misma penetración elástica. `SEEK_POS`, en cambio, arranca
desde donde haya quedado el brazo tras el modo anterior, con carrera variable.

**Esto es una hipótesis, no una conclusión.** Explica el patrón, pero no se probó:
haría falta una tanda de homings arrancando a propósito desde distancias distintas
del tope positivo, y no se corrió. Tampoco se descarta el estado del péndulo al
arrancar, que varió mucho entre modos (`|α|` máx entre 0° y 117°) y que `WAIT_QUIET`
puede no alcanzar a disipar dentro de su timeout de 4 s.

## Archivos

```
scripts/mode_sweep.py     # campaña completa; --only para un subconjunto
data/m{0..7}_*.csv        # traza cruda por modo (20 Hz)
data/summary.json         # métricas derivadas por modo
```

```bash
python scripts/mode_sweep.py --ip 192.168.100.50
python scripts/mode_sweep.py --ip 192.168.100.50 --only 0,2,3
```

## Conclusiones

1. Los 8 modos entran y despachan. La reasignación de `m3` no rompió nada.
2. `m2` es el único que cierra un lazo de control limpio hoy.
3. `m4`, `m5` y `m7` siguen sin sostener la vertical; `m5` sí bombea bastante más
   fuerte de lo que decía el registro anterior (117° contra ~84°) y sí entrega el
   control al LQR solo.
4. El `safeStop` por límite blando actuó en los 3 modos donde correspondía.
5. **El homing convierte la campaña en algo repetible.** Siete recuperaciones
   automáticas del cero sin una sola intervención manual — que era exactamente el
   punto de implementarlo.

## Pendientes que salieron de acá

- ~~Exponer en `/state` el criterio de transición de `m5`.~~ **Hecho** el mismo día
  (v1.55.0, campos `swing_trans_*`). Reveló que el traspaso lo dispara siempre
  `forcedTransition`, que no tiene compuerta de velocidad ni de energía — ver
  `experiments/2026-07-30_swingup/`.
- Frenado predictivo en el segundo tope del homing (mejora de suavidad; ahora además
  hay motivo para sospechar que la repetibilidad del tope + depende de la carrera).
- Verificar la hipótesis de la carrera variable con homings desde distancias
  controladas.
