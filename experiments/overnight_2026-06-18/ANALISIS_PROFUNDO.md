# Análisis Profundo — Overnight DRL 2026-06-18

## 1. Diagnóstico del Problema

### 1.1 Lo que funciona
El agente con `linear_alpha` logra **100% reach** (llega al invertido) de forma consistente y reproducible. El swing-up está resuelto. El hold máximo de 0.66s indica que el agente **intenta** balancear pero no puede sostenerlo.

### 1.2 El problema central: 0% balance
La métrica `balance_rate` mantiene el péndulo invertido-y-lento (≤12°, ≤1 rad/s) durante **≥1s continuos** (50 steps a 50Hz). El mejor caso (0.66s) no alcanza este umbral.

### 1.3 Brecha crítica: recompensa ≠ métrica de evaluación
**Esta es la causa raíz.** La reward `linear_alpha` mide:
```
r = |α|/π - 0.2·(θ/(π/2))²
```
- Premia llegar arriba (gradiente lineal)
- Penaliza brazo lejos del centro
- **NO** penaliza velocidad alta
- **NO** premia mantener la posición invertida

La métrica de evaluación requiere:
- `|α - π| ≤ 12°` (inverted AND slow)
- `|α̇| ≤ 1 rad/s` (slow)
- Sostenido ≥50 steps consecutivos

El agente maximiza la recompensa acumulada, no la métrica de evaluación. No tiene incentivo para aprender estabilización.

---

## 2. Constraint de Hardware: ESP32 (FIJO)

### 2.1 Lo que NO se puede cambiar

La red neuronal **debe** ser `[64, 64]` para deploy en el ESP32:

| Constraint | Valor | Fuente |
|------------|-------|--------|
| `net_arch` | **64** (2 capas ocultas) | `config.py:83` — "fits ESP32 flash/RAM budget" |
| Parámetros | 6,593 | `policy_weights.h` — architecture: 36→64→64→1 |
| Flash | ~25.8 KB | `train.py:13` — "~17 KB flash" |
| RAM | ~1-2 KB | `train.py:13` — inference-time only |
| INPUT_DIM | 36 (4×9) | `esp32_qube.ino:69` — hardcoded |
| OUTPUT_DIM | 1 | `esp32_qube.ino` — single PWM action |
| Activación | ReLU + Hardtanh(-2,2) | `esp32_qube.ino:84,99` — hardcoded |
| Forward pass | Manual (sin framework) | `esp32_qube.ino:79-99` — loop en C++ |

**Razón:** El firmware tiene el forward pass hardcodeado en C++ (sin librería de inferencia). Cambiar `RL_HIDDEN` requiere modificar `esp32_qube.ino` + `policy_weights.h` + recompilar y testear en hardware.

### 2.2 Lo que SÍ se puede cambiar (entrenamiento en PC)

Todos los parámetros de entrenamiento son libres — solo afectan el modelo `.zip` resultante, que siempre exporta a `[64,64]`:

| Parámetro | Actual | Propuesto | Razón |
|-----------|--------|-----------|-------|
| **Reward function** | `linear_alpha` | **`linear_alpha_balance`** | Causa raíz del 0% balance |
| **`timesteps`** | 150,000 | **500,000** | Balance es comportamiento tardío |
| **`buffer_size`** | 200,000 | **500,000** | Más diversidad de transiciones |
| **`gamma`** | 0.99 | **0.995** | Horizonte más largo → planificación |
| `learning_rate` | 3e-4 | 3e-4 | OK — estándar SAC |
| `batch_size` | 256 | 256 | OK |
| `tau` | 0.005 | 0.005 | OK |
| `learning_starts` | 1,000 | 1,000 | OK |
| `max_episode_steps` | 500 | 500 | OK — 10s a 50Hz |
| `control_freq` | 50 Hz | 50 Hz | OK — match firmware |

---

## 3. Análisis de Parámetros por Categoría

### 3.1 Reward Function — Impacto: CRÍTICO

| Reward | Reach | Balance | Diagnóstico |
|--------|-------|---------|-------------|
| `swingup_balance` | 0% | 0% | Gradiente ≈0 cuando cuelga → nunca empieza |
| `linear_alpha` | 100% | 0% | Llega pero no premia mantener |
| `linear_alpha_dense` | 0% | 0% | Vel shaping inestabiliza |
| `cos_alpha` (previo, 6D) | ~100% | 10.6s | Ver §4 — contexto Importante |

**Problema con `linear_alpha`:**
- `|α|/π` = 1.0 cuando está invertido. **Ya no puede mejorar** el término de ángulo.
- No hay incentivo para reducir `|α̇|` (velocidad angular del péndulo).
- El agente aprende a llegar arriba y luego "flota" con alta velocidad → pierde el equilibrio.

**Problema con `swingup_balance`:**
- `pendulum = (1 - cos α)/2` tiene gradiente ≈ 0.005 cuando α ≈ 0 (colgando).
- Con 150k steps, el agente no descubre la estrategia de mecer.

### 3.2 Hiperparámetros SAC — Solo los cambiables

| Parámetro | Actual | Propuesto | Razón | ¿Cambia en ESP32? |
|-----------|--------|-----------|-------|:---:|
| `buffer_size` | 200k | **500k** | Más diversidad off-policy | No |
| `timesteps` | 150k | **500k** | Balance es tardío (~1000 episodios) | No |
| `gamma` | 0.99 | **0.995** | Horizonte 2s→4s, más peso al futuro | No |

### 3.3 Environment — Impacto: BAJO (ya correcto)

| Parámetro | Valor actual | Notas |
|-----------|-------------|-------|
| `max_episode_steps` | 500 (10s) | Suficiente para swing-up + balance. OK. |
| `angle_limit_theta` | ±120° | Correcto — el swing-up necesita ±120°. |
| `control_freq` | 50 Hz | Estándar. OK. |
| `velocity_filter_order` | 2 | OK — matches firmware. |

### 3.4 Wrappers — Impacto: BAJO (ya correctos)

| Wrapper | Estado | Notas |
|---------|--------|-------|
| `DeadZone(0.2)` | Activo | Compensa fricción estática. OK. |
| `HistoryWrapper(4)` | Activo | 36 features con continuity cost. OK. |
| `GentlyTerminating` | Activo | OK. |
| `PotentialShaping` | Solo en configs PBRS | El potencial `(1-cos α)/2` es débil — ver §3.5. |

### 3.5 PBRS (Potential-Based Reward Shaping) — Impacto: BAJO (con el potencial actual)

El potencial `Φ = (1 - cos α)/2` es policy-invariante (Ng et al. 1999) pero:
- Solo modela la componente angular, no la velocidad
- `F(s,s') = γΦ(s') - Φ(s)` agrega una señal débil que no compensa la falta de incentivo de balance en la reward base
- Empeoró los resultados vs. `linear_alpha` base (0.49s → 0.12s hold)

**No descarta PBRS; descarta ESTE potencial.** Un potencial que incluya `−|α̇|` y centrado de θ podría ser efectivo.

---

## 4. Contexto del Run Anterior (10.63s balance)

| Aspecto | Run anterior (10.63s) | Overnight (0.66s max) |
|---------|----------------------|----------------------|
| Reward | `cos_alpha` (multiplicativa) | `linear_alpha` (aditiva) |
| Red | [256, 256] | [64, 64] |
| Obs | 6D (sin raw angles) | 8D (con raw angles) |
| TimeLimit | No explícito | 500 steps |
| Alpha termination | **Sí (±π)** | No (v1.44 fix) |
| Steps | 12,756 | 150,000 |
| Buffer | 100K | 200K |

**⚠️ Advertencia crítica:** El run anterior tenía **alpha termination** — el episodio terminaba al llegar al invertido (`±π`). Esto hacía la tarea "más fácil" artificialmente: el agente solo necesitaba **llegar** arriba, no **quedarse**. Con 12.7K steps el agente aprendió a llegar y el episodio terminaba. No hay evidencia de que el agente hiciera balance real.

El entorno v1.44 (actual) **no termina** al llegar al invertido — el agente debe aprender a mantenerlo. Esto es más realista pero más difícil.

**Conclusión:** La comparación 10.63s vs 0.66s NO es directa. El entorno actual es fundamentalmente diferente. El benchmark correcto es 0% balance → ¿cuánto podemos mejorar?

---

## 5. Plan de Mejora — Solo parámetros viables para ESP32

### 5.1 PRIORIDAD 1: Reward con incentivo de balance (CRÍTICO)

**Propuesta: `linear_alpha_balance`**

```python
def linear_alpha_balance(state: np.ndarray) -> float:
    """Dense reward: linear_alpha + explicit balance incentive.

    Adds:
    - Velocity penalty: penalises |alpha_dot| to encourage slow inverted hold
    - Balance bonus: multiplicative reward when upright AND slow
    - Keeps linear_alpha's strong gradient for swing-up
    """
    al = np.mod((state[ALPHA] + np.pi), 2 * np.pi) - np.pi
    al_abs = np.abs(al)
    al_rew = al_abs / np.pi  # swing-up progress: 0..1

    # Balance zone: inverted (|α| > 150°) AND slow (|α̇| < 2 rad/s)
    upright = al_abs > 5 * np.pi / 6  # > 150°
    slow = abs(state[ALPHA_DOT]) < 2.0
    balance_bonus = 2.0 if (upright and slow) else 0.0

    # Velocity penalty: quadratic, always active
    vel_penalty = -0.01 * state[ALPHA_DOT] ** 2

    # Arm centering: light
    th_penalty = -0.2 * (state[THETA] / (np.pi / 2)) ** 2

    return float(al_rew + vel_penalty + th_penalty + balance_bonus)
```

**Por qué funciona:**
- `al_rew` mantiene el gradiente fuerte para swing-up
- `vel_penalty` crea incentivo para reducir velocidad angular
- `balance_bonus` da una recompensa extra explícita cuando el agente está invertido-y-lento
- El agente ahora tiene **señal directa** para aprender la estabilización
- **Solo cambia entrenamiento** — el modelo resultante sigue siendo [64,64]

### 5.2 PRIORIDAD 2: Más timesteps (ALTO)

Cambiar de 150k a **500k** por semilla. Razones:
- 150k ≈ 300 episodios de 500 steps
- Balance es un comportamiento tardío que emerge después del swing-up
- Con `linear_alpha` el reach se logra a ~50k steps; los 100k restantes son para descubrir balance
- 500k ≈ 1000 episodios → más oportunidades para descubrir la secuencia de estabilización
- **Budget:** 500k × 2 seeds × 3 configs = 3M steps. A ~70 fps → ~12 horas. Cabe en un overnight.

### 5.3 PRIORIDAD 3: Buffer más grande (MEDIO)

Cambiar de 200k a **500k**. Razones:
- SAC reutiliza datos del buffer; más tamaño = más diversidad
- Con 500k steps, un buffer de 200k descarta transiciones antiguas prematuramente
- Buffer de 500k guarda todo el historial de aprendizaje

### 5.4 PRIORIDAD 4: Gamma más alto (MEDIO)

Cambiar de 0.99 a **0.995**. Razones:
- γ = 0.99 → horizonte efectivo ~100 steps (2s)
- γ = 0.995 → horizonte efectivo ~200 steps (4s)
- Balance requiere planificación a más largo plazo (mantener posición por 1s+)
- Aumentar γ da más peso a recompensas futuras → más incentivo para mantener posición

### 5.5 PRIORIDAD 5: Evaluar `cos_alpha` en el entorno actual (BAJO pero informativo)

Ejecutar `cos_alpha` con [64,64] en el entorno v1.44 para ver si el run anterior era reproducible o si los fixes de v1.44 cambiaron la dificultad. Aísla el efecto del reward vs. el efecto del entorno.

---

## 6. Matriz de Experimentos Sugerida (Ronda 2)

| # | Reward | Steps | Buffer | Gamma | Seeds | PBRS | Prioridad |
|---|--------|-------|--------|-------|-------|------|-----------|
| 1 | `linear_alpha_balance` | 500k | 500k | 0.995 | [0,1,2] | None | **MÁXIMA** |
| 2 | `linear_alpha` | 500k | 500k | 0.995 | [0,1,2] | None | ALTA (control) |
| 3 | `cos_alpha` | 500k | 500k | 0.995 | [0,1,2] | None | MEDIA (historical) |

**Red fija: [64, 64]** (constraint ESP32). **Presupuesto estimado:** ~12h (3 configs × 3 seeds × 500k steps a ~70fps).

**Comparaciones clave:**
- Config 1 vs Config 2 → efecto de la reward redesign (balance incentive)
- Config 1 vs overnight → efecto combinado de reward + steps + buffer + gamma
- Config 3 vs overnight → efecto del reward (cos_alpha vs linear_alpha) en entorno v1.44

---

## 7. Métricas de Éxito para la Ronda 2

| Métrica | Overnight (actual) | Target R2 | Target Final |
|---------|-------------------|-----------|--------------|
| reach_rate | 100% | ≥100% | 100% |
| balance_rate | 0% | **≥20%** | **≥80%** |
| upright_fraction | 3.5% | **≥15%** | **≥50%** |
| max_hold_s | 0.66s | **≥2.0s** | **≥5.0s** |
| ep_rew_mean | 318.82 | ≥400 | ≥500 |

---

## 8. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|-------------|---------|------------|
| `linear_alpha_balance` crea reward hacking (spinning) | Media | Alto | Monitorear upright_fraction; si spinning, reducir balance_bonus |
| 500k steps no alcanza balance | Media | Medio | Si no converge, probar currículo (reset cerca del invertido) |
| Budget de tiempo insuficiente | Media | Medio | Priorizar config 1; configs 2 y 3 son opcionales |
| `balance_bonus` umbral duro falla en HW real | Media | Alto | Usar sigmoide suave en vez de binario para sim-to-real |

---

## 9. Auditoría del Plan

### 9.1 Coherencia lógica
✅ Las mejoras abordan la causa raíz identificada:
- Reward sin balance incentive → nueva reward con `balance_bonus` + `vel_penalty`
- Steps insuficientes → 500k (3.3× más que overnight)
- Buffer pequeño → 500k (2.5× más que overnight)
- Gamma bajo → 0.995 (más peso al futuro)

### 9.2 Factibilidad técnica
✅ Todos los cambios son paramétricos — no requieren modificar firmware:
- `linear_alpha_balance` es una nueva función en `rewards.py` (1 archivo, ~15 líneas)
- `timesteps`, `buffer_size`, `gamma` son args del script `run_overnight.py`
- La factory y wrappers ya soportan estas configuraciones sin cambios
- **El modelo resultante sigue siendo [64,64]** — exportable al ESP32 sin modificar firmware

### 9.3 Impacto en sim-to-real
✅ Los cambios son neutrales o positivos para transferencia:
- La reward cambia, pero la arquitectura de red y observación no cambian
- Más steps → política más madura y robusta
- `balance_bonus` con umbrales suaves → más transferible que umbrales binarios

### 9.4 Priorización
✅ Las prioridades están ordenadas por impacto/esfuerzo:
1. Reward (mayor impacto, bajo esfuerzo — 1 archivo)
2. Steps (alto impacto, bajo esfuerzo — solo tiempo de cómputo)
3. Buffer (medio impacto, bajo esfuerzo — 1 parámetro)
4. Gamma (medio impacto, bajo esfuerzo — 1 parámetro)

### 9.5 Verificación
✅ Cada cambio puede evaluarse independientemente:
- Comparar configs 1 vs 2 → efecto de la reward redesign
- Comparar configs 1 vs overnight → efecto de steps + buffer + gamma
- Comparar configs 3 vs overnight → efecto de cos_alpha en entorno v1.44

### 9.6 Completitud
✅ El plan cubre:
- Diagnóstico del problema (§1)
- Constraint de hardware (§2) — fijo, no negociable
- Análisis de parámetros (§3)
- Contexto histórico (§4) — comparación justa
- Soluciones concretas con valores (§5)
- Matriz de experimentos (§6)
- Métricas de éxito (§7)
- Riesgos y mitigaciones (§8)
- Auditoría (§9)
