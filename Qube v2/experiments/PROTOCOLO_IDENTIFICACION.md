# Protocolo de Identificación de Sistema — Gemelo Digital QUBE (Fase 1)

**Fecha:** 2026-06-18
**Objetivo:** Reemplazar los parámetros *de catálogo* de `qube_rl/envs/qube_dynamics.py` por parámetros **medidos** del hardware real (driver **BTS7960**), con su incertidumbre, para convertir el simulador en un gemelo digital validable (Fase 2).
**Herramienta:** `src/qube_analysis/sysid.py` (toolkit reproducible) + `src/qube_analysis/dataset.py` (loader normalizador).

> Este documento es el entregable "script de identificación reproducible" de la **Fase 1** del `docs/research/ai_research/plan_gemelo_digital_drl.md`. Define **qué capturar, cómo, y cómo procesarlo** para cada parámetro.

---

## 0. Por qué hacen falta capturas dedicadas

El `experiments/CATALOGO_DATOS.md` ya estableció que **no existe** una captura limpia de excitación post-2026-06-08 (BTS7960). El barrido de la data existente con `sysid.py` lo confirma: de **439 runs BTS7960**, solo **1 segmento** (`batch20_02.csv`) cumple "motor apagado + oscilación amplia", y en él **el brazo también se mueve** (coast-down acoplado, no péndulo de base fija). Una identificación con intervalo de confianza para una tesis necesita repeticiones controladas.

### Resultado preliminar (de la data oportunista — NO reportable como final)

| Parámetro | Nominal (catálogo) | Preliminar (n=1, acoplado) | Lectura |
|---|---|---|---|
| `Lp` | 12.9 cm | **≈ 13.5 cm** (f=1.66 Hz, R²=0.94) | El largo nominal es **razonable** ✓ |
| `Dp` | 1.0×10⁻⁶ | **≈ 1.3×10⁻⁴** (cota superior) | La fricción nominal es **~100× demasiado baja**; el valor real es mayor, pero está inflado por el acoplamiento con el brazo |

**Conclusión:** confirma `Lp` y revela que `Dp` nominal es implausible, pero con n=1 y brazo libre no es defendible. Capturar lo de abajo.

---

## 1. Pre-requisitos (mediciones directas — las más baratas y fiables)

Antes de cualquier experimento dinámico, medir con instrumentos:

| Parámetro | Cómo | Símbolo en `QubeDynamics` |
|---|---|---|
| Masa del péndulo | Balanza de cocina (±1 g) | `Mp` |
| Masa del brazo | Balanza | `Mr` |
| Largo del péndulo | Regla/calibre (pivote→punta) | `Lp` (valida la identificación dinámica) |
| Largo del brazo | Regla (eje→pivote péndulo) | `Lr` |
| Resistencia del motor | Multímetro entre terminales, rotor bloqueado, promediar varias posiciones | `Rm` |
| CPR del encoder | Ya conocido = 2048×4 | — |

> `Dp` (fricción del péndulo) **escala linealmente con `Mp`**, así que la balanza es un insumo directo del cálculo: `sysid.identify_pendulum(fit, Mp=<medido>)`.

---

## 2. Experimentos dinámicos (excitación en hardware)

La telemetría es **host-polled** vía HTTP (`GET /state` o `GET /rl_state`, este último más liviano → mayor tasa). **No hay logger on-device de alta tasa**, así que el techo práctico por WiFi es **~30 Hz** (suficiente para el péndulo a ~1.7 Hz: ~18 muestras/periodo; marginal para dinámica fina del motor). Si se requiere >100 Hz, hay que añadir un buffer circular en firmware (ver §4).

> **Herramienta de captura:** `src/firmware/capture.py` ejecuta el bucle de polling rápido **localmente** (no por MCP — las llamadas MCP pasan por el agente y no alcanzan decenas de Hz) y escribe directamente el esquema canónico en `experiments/<fecha>_<exp>/`. Mide primero el techo real con `capture.py bench`. Cada experimento abajo tiene su subcomando; todos ejecutan bajo un guard que **siempre manda kill-switch** al salir y clampean el PWM a `--max-pwm`.
>
> ```bash
> python src/firmware/capture.py bench     --ip <IP>            # tasa + latencia reales
> python src/firmware/capture.py freedecay --ip <IP> --reps 8  # Exp. A
> python src/firmware/capture.py pwm-step  --ip <IP>           # Exp. B
> python src/firmware/capture.py deadzone  --ip <IP>           # Exp. C
> ```

### Experimento A — Decaimiento libre del péndulo (→ `Lp`, `Dp`)

**Aísla la mecánica del péndulo.** Es el más importante y el más fácil.

1. **Fijar el brazo** (mordaza/cinta) para que `θ` no se mueva — esto hace válida la relación de base fija `ωn² = 3g/(2·Lp)` que usa `sysid`. *(Sin fijar el brazo, el resultado queda acoplado, como el preliminar de arriba.)*
2. `GET /cmd?m=0` (modo **stop**, motor apagado).
3. Soltar el péndulo desde ~30–45° respecto de la vertical de reposo (ángulo pequeño → modelo lineal válido; evitar grandes amplitudes no lineales).
4. Hostear el log de `GET /rl_state` (o `/state`) a la máxima tasa posible (~30 Hz) durante **≥ 8 s** (capta ~13 periodos para una buena envolvente de decaimiento).
5. Repetir **≥ 8 veces** (da media ± std → el `*_std` real de domain randomization).

**Procesado:**
```python
from qube_analysis import load_session, identify_pendulum_from_runs
runs = load_session("experiments/<fecha>_freedecay", driver="BTS7960")
agg, per_run = identify_pendulum_from_runs(runs, Mp=<masa_medida_kg>)
# agg.Lp, agg.Dp; agg.r2 = std de Lp entre runs (spread empírico)
```

### Experimento B — Escalón / chirp de PWM con brazo libre (→ `km`, `Rm` efectiva, `Dr`)

**Identifica el actuador BTS7960** (lo que la data L298N legacy NO sirve para medir).

1. Brazo **libre**, péndulo **fijo o retirado** (para no excitar el modo del péndulo).
2. `GET /cmd?m=1` (PWM manual).
3. **Escalón:** `GET /cmd?p=<valor>` para varios niveles (p.ej. 40, 80, 120, 160). Para cada nivel, dejar que `θ̇` alcance régimen permanente (~1–2 s) y registrar `θ̇_ss`, `i_ma`, `v_bus`.
   - En régimen permanente sin carga: `V ≈ km·θ̇` y `i ≈ (V−km·θ̇)/Rm` → despeja `km` (pendiente de `V` vs `θ̇_ss`) y `Rm`.
4. **Chirp (opcional, mejor):** barrer `p` senoidalmente 0.5→5 Hz desde el host para excitar la dinámica de 1er orden del motor+brazo.
5. Registrar `θ`, `pwm`, `i_ma`, `v_bus` a máxima tasa.

> Pendiente de toolkit: `sysid.estimate_motor_constants` (no implementado aún — requiere esta captura para existir con datos reales; se añadirá cuando exista el dataset).

### Experimento C — Barrido de zona muerta (→ deadzone, fricción estática)

**Umbral de PWM que rompe la fricción estática del BTS7960.**

1. Brazo libre, péndulo fijo/retirado. `GET /cmd?m=1`.
2. **Escalera lenta:** subir `p` de 0 en pasos pequeños (p.ej. +2 cada 0.3 s) hasta detectar movimiento del brazo; repetir en ambos sentidos (±).
3. Registrar `θ`, `pwm`.

**Procesado:**
```python
from qube_analysis import load_run, estimate_deadzone
(run,) = load_run("experiments/<fecha>_deadzone/staircase.csv")
dz = estimate_deadzone(run)            # dz.pwm_threshold, dz.pwm_moving
```
Alimenta `wrappers/deadzone.py` con el umbral medido.

---

## 3. Convenciones de captura (homogeneizar el esquema futuro)

Para que el loader no tenga que adivinar (ver problemas en el catálogo), capturar con:

- **Esquema único de columnas:** `t,theta_deg,alpha_deg,pwm,mode,v_bus,i_ma` (nombres canónicos que `sysid`/`dataset` ya entienden directamente).
- **Tiempo monotónico en segundos** desde inicio del episodio (o `t_ms` monotónico — el loader convierte ms→s).
- **Un archivo por repetición**, nombrado `<exp>_<nn>.csv`, dentro de `experiments/<YYYY-MM-DD>_<exp>/` (la fecha en la ruta hace que `infer_driver` marque BTS7960 automáticamente).
- Delimitador `,` (coma).

---

## 4. Mapa parámetro → experimento (qué falta y qué lo cubre)

| Parámetro `QubeDynamics` | Fuente | Estado |
|---|---|---|
| `Mp`, `Mr`, `Lr` | Medición directa (§1) | ⬜ pendiente (trivial) |
| `Lp` | Exp. A (período) + regla | 🟡 preliminar ≈13.5 cm; falta brazo fijo |
| `Dp` | Exp. A (envolvente) + `Mp` | 🟡 preliminar (inflado); falta brazo fijo |
| `Rm` | Multímetro (§1) + Exp. B | ⬜ pendiente |
| `km` | Exp. B (V vs θ̇_ss) | ⬜ pendiente (no hay data) |
| `Dr` | Exp. B (chirp) | ⬜ pendiente |
| `stall_torque` | Exp. B (saturación) o datasheet | ⬜ pendiente |
| deadzone | Exp. C | ⬜ pendiente |
| `*_std` (domain rand.) | std entre repeticiones de A/B/C | ⬜ se obtiene gratis al repetir |

**Mejora opcional de firmware (si se requiere >100 Hz):** añadir un buffer circular en RAM que muestree el lazo de control (200 Hz) y un endpoint `GET /dump` que lo vuelque al final del experimento. Elimina el techo de ~30 Hz del polling WiFi y mejora la identificación de `Dp` y de la dinámica del motor.

---

*Protocolo Fase 1 · gemelo digital DRL · driver BTS7960 (corte 2026-06-08) · toolkit `qube_analysis.sysid`.*
