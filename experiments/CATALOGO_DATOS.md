# Catálogo de Datos Experimentales — QUBE Servo

**Fecha de catalogación:** 2026-06-18
**Alcance:** Inventario de todos los datos CSV capturados del hardware, con procedencia de driver, esquema de columnas, tasa de muestreo y utilidad para identificación de sistema (Fase 1 del plan de gemelo digital).
**Total:** ≈ 412 archivos CSV, ≈ 12 MB en 12 sesiones experimentales.

> ⚠️ **Desactualizado (nota agregada 2026-07-28):** este catálogo cubre solo las sesiones hasta `2026-06-18_r2_balance` / `2026-06-18_r3_adaptive` / `2026-06-18_r3_curriculum`. `experiments/` ya tiene sesiones posteriores sin catalogar: `2026-06-19_r4_curriculum`, `2026-06-22_r4_finetune_s1`, `2026-06-22_r4_real`, `2026-06-22_r5_pbrs_curriculum`, `2026-06-22_r6_real_aligned`, `2026-06-23_r7_curriculum_sweep` (esta última sola pesa 58 MB). Falta una pasada de re-catalogación que inspeccione esas sesiones nuevas; no se hizo en esta tarea de higiene porque requiere revisar cada CSV, trabajo aparte de la limpieza estructural.

> Generado en la **Fase 0** del `docs/research/ai_research/plan_gemelo_digital_drl.md`. Su propósito es que la identificación de parámetros (Fase 1) sepa **qué datos existen, bajo qué hardware se tomaron, y para qué sirven**.

---

## ⚠️ Hallazgo crítico: la data está partida por el cambio de actuador

El driver del motor se **migró de L298N a BTS7960 el 2026-06-08** (commit `78b4e7e` "Migrate motor driver to BTS7960"). Esto divide el dataset en dos regímenes **no intercambiables para el modelo del actuador**:

| Régimen | Fechas de captura | Driver | Válido para… |
|---|---|---|---|
| **Legacy** | ≤ 2026-06-04 | **L298N** (BJT, caída ~2 V) | Parámetros **mecánicos** (péndulo/brazo): masa, longitud, fricción, inercia. **NO** para el mapeo PWM→torque actual. |
| **Actual** | ≥ 2026-06-08 | **BTS7960** (MOSFET, caída ~0.5 V) | Todo, incluido el modelo del actuador (`km`, `Rm` efectiva, zona muerta, `stall_torque`). |

**Regla para Fase 1:** los parámetros del actuador del gemelo (`qube_dynamics.py`) deben identificarse **exclusivamente con datos ≥ 2026-06-08**. Los parámetros puramente mecánicos pueden usar ambos regímenes (la mecánica del péndulo no cambió con el driver).

---

## Inventario por sesión

### Régimen LEGACY (driver L298N)

| Sesión | CSV | Tamaño | Esquema (columnas) | Tiempo | Tasa log | Señales clave | Utilidad Fase 1 |
|---|---|---|---|---|---|---|---|
| `2026-05-07_pid_tuning` | 4 | 583 KB | `t_s,position_deg,setpoint_deg,error_deg,pwm,current_ma,voltage_v,power_mw` | s (uptime, ~1225→1604) | ~8 Hz | servo + pwm + **corriente** | Mecánica del brazo (`Mr,Lr,Dr`); motor solo bajo L298N |
| `2026-05-13_encoder_test` | 1 | 117 KB | igual que arriba | s (relativo 0→117) | ~16.5 Hz | servo + pwm + corriente | Validación de encoder/velocidad |
| `2026-05-29_servo_test` | 1 | 9.8 KB | `t,servo_pos,servo_sp,servo_err,pend_pos,pend_sp,pwm,i_ma,v_bus` | **s (epoch Unix!)** | ~4 Hz | servo **+ péndulo** + pwm | Corto; baja tasa |
| `2026-06-01_cpr_measurement` | 0 | — | (sin CSV; ver README) | — | — | — | Confirma CPR encoder = 2048×4 |
| `2026-06-01_swing` | 79 | 690 KB | `time_s;mode;position_deg;setpoint_deg;pend_position_deg;pwm;voltage_v;current_mA;power_mW` | s (`;` delim) | ~10 Hz | servo + **péndulo** + pwm + corriente | **Péndulo: `Mp,Lp,Dp`** vía decaimiento libre |
| `2026-06-03_swing` | 78 | 2.0 MB | `t_ms,mode,pwm,servo_count,servo_deg,pend_count,pend_raw_deg,pend_deg,ina_ok,v_bus,i_ma,p_mw` | ms | ~7 Hz | **counts crudos** + ángulos + pwm + corriente | **Mejor set mecánico L298N** (raw counts evitan errores de conversión) |
| `2026-06-04_pid_tuning` | 13 | 186 KB | 2 esquemas (PID péndulo / PID servo con `gain_mode`) | ms | ~7 Hz | servo o péndulo + pwm + corriente | Respuesta a escalón cerrada (validación) |

### Régimen ACTUAL (driver BTS7960) — prioritario para el gemelo

| Sesión | CSV | Tamaño | Esquema (columnas) | Tiempo | Tasa log | Señales clave | Utilidad Fase 1 |
|---|---|---|---|---|---|---|---|
| `2026-06-08_swing` | 181 | 5.7 MB | rico: `t,servo_deg,pend_deg,pend_raw_deg,pwm,mode,v_bus,i_ma,p_mw` (167) · mínimo: `t,pend,servo,mode,pwm,v` (14) | s (0→90) | ~12 Hz | servo + péndulo + pwm + **corriente** | **Set BTS7960 más grande**; actuador + péndulo |
| `2026-06-10_autoresearch_swing` | 34 | 1.2 MB | rico (32) + sweep `sp,attempt,t,servo_deg,pend_deg,mode,pwm,v_bus` (2) | s (per-intento) | ~12 Hz | servo + péndulo + pwm | Swing-up autoresearch (barrido `ke_gain`) |
| `2026-06-15_sweep_v2` | 1 | 315 KB | `sp,attempt,t,servo_deg,pend_deg,mode,pwm,v_bus` (8391 filas) | s (per-intento) | — | agregado multi-intento | Barrido de parámetros (sin corriente) |
| `2026-06-15_sweep_v3` | 1 | 182 KB | igual (4908 filas) | s (per-intento) | — | agregado multi-intento | Barrido de parámetros |
| `2026-06-15_training` | 19 | 755 KB | `attempt,t,pend_deg,mode,pwm,v_bus` (16) + variante con `sp` (2) | s (per-intento) | — | péndulo + pwm | Datos de entrenamiento/ajuste |

---

## Semántica de columnas (diccionario)

| Columna(s) | Significado | Unidad |
|---|---|---|
| `t`, `t_s`, `time_s` | tiempo (relativo, uptime o epoch — **ver columna "Tiempo"**) | s |
| `t_ms` | tiempo | ms |
| `position_deg`, `servo_deg`, `servo_pos` | ángulo del brazo/servo (θ) | grados |
| `pend_deg`, `pend_position_deg`, `pend_pos`, `pend` | ángulo del péndulo (α) | grados |
| `pend_raw_deg` | ángulo del péndulo sin offset de cero | grados |
| `servo_count`, `pend_count` | conteo crudo del encoder (X4) | counts |
| `setpoint_deg`, `servo_sp`, `pend_sp`, `sp` | consigna | grados |
| `error_deg`, `servo_err` | error = setpoint − medición | grados |
| `pwm` | comando PWM aplicado | −255..255 |
| `mode` | modo de control (0 stop, 1 PWM, 2 PID, 4 LQR, 5 swing, 6 RL) | — |
| `voltage_v`, `v_bus`, `v` | voltaje de bus (INA219) | V |
| `current_ma`, `current_mA`, `i_ma` | corriente (INA219) | mA |
| `power_mw`, `power_mW`, `p_mw` | potencia (INA219) | mW |
| `ina_ok` | flag de lectura válida del INA219 | 0/1 |
| `attempt`, `gain_mode` | índice de intento / modo de ganancia (metadatos de barrido) | — |

---

## Problemas de calidad detectados (a resolver/normalizar)

1. **Esquemas heterogéneos** — al menos **8 formatos de columnas distintos** entre sesiones. Nombres inconsistentes para la misma señal (`position_deg` vs `servo_deg` vs `servo_pos`; `current_ma` vs `i_ma`).
2. **Unidades de tiempo inconsistentes** — segundos relativos, segundos de *uptime* (arranca en ~1225), **segundos epoch Unix** (`2026-05-29`), y milisegundos (`t_ms`). Un cargador debe normalizar a "segundos desde inicio de episodio".
3. **Delimitador mixto** — `2026-06-01_swing` usa `;`; el resto usa `,`.
4. **Tasa de log baja vs. lazo de control** — el logging va a ~4–16 Hz mientras el control corre a 200 Hz. La frecuencia natural del péndulo (~1.4 Hz) se captura bien, pero **estimar velocidades por diferencias finitas será ruidoso**. Para identificación dinámica fina conviene capturar nuevos datos a mayor tasa (ver "Vacíos").
5. **Archivos vacíos/abortados** — varios CSV con 0, −1, 12 o 26 filas (intentos fallidos). Filtrar por nº mínimo de filas antes de usar.
6. **Ficheros multi-intento concatenados** — los `sweep_data.csv`/`training_data.csv` apilan intentos con `t` que se reinicia por `attempt`; segmentar por `attempt` antes de analizar.

---

## Vacíos de datos para la Fase 1 (lo que falta capturar)

Para una identificación de sistema limpia del gemelo **BTS7960**, los datos actuales son reutilizables pero subóptimos. Experimentos dedicados recomendados (Fase 1):

- [ ] **Decaimiento libre del péndulo** (motor apagado, soltar desde ~horizontal): aísla `Mp, Lp, Dp` y frecuencia natural. Capturar a ≥100 Hz si el firmware lo permite. *Parcialmente presente* en segmentos de coast-down de los swing-ups, pero no como experimento controlado.
- [ ] **Escalón/chirp de PWM con brazo libre** (sin péndulo o péndulo fijo): identifica `km`, `Rm` efectiva y zona muerta del **BTS7960**. **No existe** una captura limpia de este tipo post-06-08.
- [ ] **Barrido de zona muerta**: PWM creciente lento hasta detectar umbral de movimiento (fricción estática del BTS7960).
- [ ] Todas con **timestamp monotónico en ms** y **esquema único** (ver recomendación de normalización).

---

## Recomendaciones de ordenamiento del repositorio

Aplicado en Fase 0:
- ✅ Encabezado y banner del firmware activo corregidos de L298N → BTS7960 (`src/firmware/esp32_qube/esp32_qube.ino`).
- ✅ **Carpeta de firmware renombrada** `esp32_qube_l298n/` → `esp32_qube/` y archivo `esp32_qube_l298n.ino` → `esp32_qube.ino`. Referencias funcionales actualizadas (`platformio.ini`, `Makefile`, `mcp/esp32_qube_server.py`, `distill.py`, `export_rltools.py`) y docs de orientación (`AGENTS.md`, `.github/`, `README.md`). Los logs históricos (CHANGELOG, SESSION_LOGs, HANDOFFs) conservan el nombre antiguo como registro de su fecha.
- ✅ Este catálogo creado.
- ✅ **Cargador normalizador** de CSV creado en `src/qube_analysis` (ver "cargador de datos" abajo).

Pendiente (futuras sesiones):
- ⬜ **Esquema CSV único** para capturas *futuras* del firmware (homogeneizar nombres y `t_ms` monotónico en origen).
- ⬜ Mover los `sweep_data.csv`/`training_data.csv` agregados a un subformato documentado (segmentable por `attempt`).

---

*Catálogo generado: 2026-06-18 · Fase 0 del plan de gemelo digital DRL · Corte de driver: 2026-06-08 (commit 78b4e7e).*
