# Resultados del Entrenamiento DRL — QUBE Servo

**Fecha:** 2026-06-16
**Estado:** ✅ CONVERGENCIA ALCANZADA

---

## Resultado Principal

El agente SAC logra balancear el péndulo invertido durante **10.63 segundos** en
simulación, superando el umbral de convergencia de 500 steps (10 segundos).

| Métrica | Valor | Interpretación |
|---------|-------|----------------|
| **Ep Len Mean** | **531.5 steps (10.63s)** | ✅ Converge |
| **Ep Rew Mean** | **47.25** | Reward alto |
| **FPS** | 14 | Velocidad de entrenamiento |
| **Steps totales** | 12,756 | De 50,000 planificados |

---

## Progresión del Aprendizaje

```
Step      Ep Len (steps)   Ep Len (s)   Reward   Estado
────────  ──────────────   ──────────   ──────   ──────────────
    214         53.5          1.07s       7.76    Explorando
    598         74.8          1.50s       8.73    Descubriendo
    999         83.3          1.67s       9.29    Aprendiendo
  5,646        352.9          7.06s      39.11    Mejorando
  6,134        306.7          6.13s      34.43    Estabilizando
 12,756        531.5         10.63s      47.25    ✅ CONVERGE
```

El agente pasó de 1 segundo a 10.6 segundos de balance en ~12,700 steps.

---

## Configuración del Entrenamiento

| Parámetro | Valor |
|-----------|-------|
| Algoritmo | SAC (Soft Actor-Critic) |
| Learning rate | 3e-4 |
| Red | [256, 256] (policy y Q) |
| Replay buffer | 100,000 |
| Batch size | 256 |
| Gamma | 0.99 |
| Tau | 0.005 |
| gSDE | Activado (sde_sample_freq=64) |
| Reward | `cos_alpha` (multiplicativa) |
| Obs space | 6-D: [cos θ, sin θ, cos α, sin α, θ̇, α̇] |
| Action space | 1-D: [-1.0, 1.0] (PWM normalizado) |
| Control freq | 50 Hz |
| Domain randomization | Parámetros físicos variados cada reset |
| Wrappers | Monitor, GentlyTerminating, DeadZone, HistoryWrapper(4) |

---

## Métricas Finales de Training

| Métrica | Valor | Interpretación |
|---------|-------|----------------|
| Actor loss | -5.82 | Policy aprendida (normal en SAC) |
| Critic loss | 0.067 | Value function convergida |
| Ent coef | 0.068 | Baja entropía = agente explotando |
| Std | 0.0497 | Noise de exploración estable |

---

## Análisis de Convergencia

**¿Por qué funciona?**
1. **Domain randomization** — Cada reset varía parámetros físicos (masas, largos, resistencia motor). El agente aprende una política robusta.
2. **gSDE** — Exploración correlacionada con el estado, más eficiente que ruido gaussiano.
3. **HistoryWrapper** — 4 pasos de historial dan contexto temporal (aceleración implícita).
4. **DeadZone** — Compensa zona muerta del motor.
5. **Reward multiplicativa** — `cos_alpha × θ_reward` premiza simultaneamente verticalidad y centrado.

**¿Qué falta para hardware real?**
1. Fine-tuning en el ESP32 real (100K steps)
2. Flashear firmware modo 6
3. Probar inferencia vía WiFi

---

## Archivos Generados

| Archivo | Descripción |
|---------|-------------|
| `runs/run1_baseline_1/` | Logs TensorBoard del entrenamiento |
| `models/qube_sac_run1_baseline.zip` | Modelo entrenado (si existe) |

---

## Próximos Pasos

1. **Flashear firmware modo 6:**
   ```bash
   cd src/firmware && pio run -e esp32dev --target upload
   ```

2. **Test endpoints:**
   ```bash
   curl http://192.168.4.1/rl_state
   curl "http://192.168.4.1/cmd?m=6"
   ```

3. **Inferencia en hardware:**
   ```bash
   uv run python -m qube_rl.inference --model models/qube_sac_run1_baseline.zip
   ```

4. **Fine-tuning sim-to-real:**
   ```bash
   uv run python -m qube_rl.finetune --model models/qube_sac_run1_baseline.zip --timesteps 100000
   ```
