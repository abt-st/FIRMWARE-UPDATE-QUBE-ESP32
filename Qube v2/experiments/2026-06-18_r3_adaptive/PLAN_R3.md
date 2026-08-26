# Plan R3 — Penalización Adaptativa para Swing-Up + Balance

## Contexto

| Ronda | Reward | reach | balance | Lección |
|-------|--------|:-----:|:-------:|---------|
| R1 | `linear_alpha` | 100% | 0% | Swing-up resuelto; falta incentivo de balance |
| R2 | `linear_alpha_balance` | **0%** | 0% | Penalización global de velocidad **mata** el swing-up |
| **R3** | `linear_alpha_adaptive` | ?% | ?% | Penalización solo en mitad superior |

## 1. Análisis de causa raíz (R2)

El error de R2 fue aplicar `-0.01·α̇²` **en todo el espacio de estados**:

```
Durante swing-up: α̇ ≈ 5-10 rad/s → penalización = -0.25 a -1.0 por paso
Reward promedio: -1.41 (negativo → política colapsa)
```

El agente necesita α̇ alto para bombear energía (swing-up). Penalizar eso globalmente impide descubrir la estrategia de mecer.

## 2. Solución: Penalización Adaptativa

### 2.1 Diseño

```python
def linear_alpha_adaptive(state):
    """linear_alpha + adaptive velocity penalty (upper-half only).
    
    Phase logic:
    - Lower half (|α| < π/2):  vel_penalty = 0 (free to pump energy)
    - Upper half (|α| > π/2):  vel_penalty = -0.05·α̇² (stabilise)
    - Inverted + slow (>150°, |α̇|<2):  balance_bonus = +2.0
    """
```

### 2.2 Mapa de recompensas por zona

```
                    α = π (invertido)
                         │
           ┌─────────────┼─────────────┐
           │  BALANCE    │   BALANCE   │  vel_penalty = -0.05·α̇²
           │  bonus=2.0  │   bonus=2.0 │  balance si |α̇|<2
           │  si |α̇|<2  │             │
           ├─────────────┼─────────────┤  α = 5π/6 (150°)
           │  UPPER      │   UPPER     │  vel_penalty = -0.05·α̇²
           │  (acercam.) │  (acercam.) │  sin balance bonus
           ├─────────────┼─────────────┤  α = π/2 (90°)
           │  LOWER      │   LOWER     │  vel_penalty = 0
           │  (swing-up) │  (swing-up) │  libre de bombear
           └─────────────┼─────────────┘
                         │
                    α = 0 (colgando)
```

### 2.3 Parámetros y sensibilidad

| Parámetro | Valor | Rango seguro | Si es muy alto... | Si es muy bajo... |
|-----------|-------|-------------|-------------------|-------------------|
| `vel_penalty_max` | -0.05 | -0.01 a -0.1 | Agente no puede acercarse al invertido | No estabiliza |
| `balance_bonus` | 2.0 | 1.0 a 5.0 | Reward hacking (flotar arriba) | No incentivo de balance |
| `upright_threshold` | 150° (5π/6) | 120° a 170° | Zona de bonus muy pequeña | Bonus se activa muy fácil |
| `slow_threshold` | 2 rad/s | 1.0 a 3.0 | Bonus se activa con velocidad alta | Bonus casi inalcanzable |

### 2.4 Por qué estos valores

- **vel_penalty = -0.05**: En la mitad superior, α̇ típico durante acercamiento ≈ 2-3 rad/s → penalización ≈ -0.2 a -0.45 por paso. Comparable a `al_rew` ≈ 0.5-0.8. No domina, pero sí frena.
- **balance_bonus = 2.0**: Alto enough para competir con `al_rew` (max 1.0) y dar señal clara de "quédate aquí".
- **upright = 150°**: Coincide con la métrica de evaluación (12° del invertido = 168°). 150° es más generoso para dar margen de aprendizaje.
- **slow = 2 rad/s**: Más generoso que la métrica de evaluación (1 rad/s). El agente aprende a reducir velocidad gradualmente.

## 3. Matriz de Experimentos R3

| # | Nombre | Reward | Steps | Seeds | PBRS | Notas |
|---|--------|--------|-------|-------|------|-------|
| 1 | `adaptive_base` | `linear_alpha_adaptive` | 200k | [0,1,2] | No | **Primario** — penalización adaptativa |
| 2 | `adaptive_500k` | `linear_alpha_adaptive` | 500k | [0,1,2] | No | Más tiempo — balance es tardío |
| 3 | `linear_control` | `linear_alpha` | 200k | [0,1,2] | No | Control — ya probado en R2 |
| 4 | `adaptive_pbrs` | `linear_alpha_adaptive` | 200k | [0,1,2] | upright | PBRS con potencial mejorado |

### 3.1 Comparaciones clave

- **1 vs 3** → efecto de la penalización adaptativa (misma base, misma cantidad de steps)
- **1 vs 2** → efecto de más steps (¿500k rompe el 0% de balance?)
- **1 vs 4** → efecto de PBRS sobre la reward adaptativa

### 3.2 Presupuesto

| Config | Steps | Seeds | Tiempo/seed | Total |
|--------|-------|-------|-------------|-------|
| 1 | 200k | 3 | ~40 min | ~2h |
| 2 | 500k | 3 | ~100 min | ~5h |
| 3 | 200k | 3 | ~40 min | ~2h |
| 4 | 200k | 3 | ~40 min | ~2h |
| **Total** | | | | **~11h** |

Con budget de 7h: configs 1-3 completas, config 4 parcial.

## 4. Currículo como respaldo (si R3 no rompe 0%)

Si la penalización adaptativa sola no logra balance, implementar **currículo de 2 stages**:

### Stage 1: Swing-up (ya resuelto)
- Reward: `linear_alpha`
- Steps: 100k
- Resultado esperado: 100% reach (ya demostrado)

### Stage 2: Fine-tune con balance
- Reward: `linear_alpha_adaptive`
- Steps: 100k
- Inicializar desde modelo del Stage 1
- El agente ya sabe llegar → ahora aprende a quedarse

**Ventaja:** Separa el problema. El Stage 1 ya está resuelto.
**Riesgo:** Catastrophic forgetting — el agente puede "olvidar" el swing-up durante el fine-tune.
**Mitigación:** Usar learning rate bajo (1e-4) en Stage 2 para preservar conocimiento.

## 5. Métricas de éxito

| Métrica | R1 | R2 | Target R3 | Target Final |
|---------|:--:|:--:|:---------:|:------------:|
| reach_rate | 100% | 0-100% | **≥90%** | 100% |
| balance_rate | 0% | 0% | **≥10%** | ≥80% |
| upright_fraction | 3.5% | 0-13% | **≥20%** | ≥50% |
| max_hold_s | 0.66s | 0-0.74s | **≥1.5s** | ≥5.0s |
| ep_rew_mean | 318 | -1.4 to 342 | **≥350** | ≥500 |

## 6. Implementación

### 6.1 Archivos a modificar

| Archivo | Cambio | Líneas estimadas |
|---------|--------|:---:|
| `src/qube_rl/rewards.py` | Agregar `linear_alpha_adaptive` + registrar en REWARDS | ~30 |
| `experiments/2026-06-18_r3_adaptive/run_r3.py` | Script de entrenamiento R3 | ~200 (copiar de R2) |

### 6.2 Tests

- Verificar que `linear_alpha_adaptive` retorna valores en rango esperado
- Verificar que la penalización es 0 en mitad inferior
- Verificar que la penalización es negativa en mitad superior
- Smoke test del script R3

### 6.3 Orden de ejecución

1. Implementar `linear_alpha_adaptive` en rewards.py
2. Registrar en REWARDS dict
3. Crear carpeta `experiments/2026-06-18_r3_adaptive/`
4. Crear `run_r3.py` con matriz de experimentos
5. Smoke test (--smoke)
6. Lanzar entrenamiento real (background, ~7h)
7. Dejar corriendo sin supervisión

## 7. Riesgos

| Riesgo | Probabilidad | Mitigación |
|--------|:---:|-----------|
| Adaptive penalty sigue matando swing-up | Baja | vel_penalty=0 abajo preserva bombeo |
| Balance bonus crea reward hacking (spinning) | Media | evaluate_balance detecta spinning (vel_tol) |
| 200k steps no alcanza balance | Media | Config 2 prueba 500k |
| Umbral π/2 es muy abrupto | Baja | Se puede suavizar con sigmoide en R4 |
| Currículo (Stage 2) olvida swing-up | Media | LR bajo + buffer compartido |

## 8. Criterio de decisión para R4

| Resultado R3 | Acción R4 |
|-------------|-----------|
| balance ≥ 10% | Deploy a hardware real (modo 7) |
| balance > 0% pero < 10% | Más steps (500k-1M) o currículo |
| balance = 0% pero reach ≥ 90% | Currículo obligatorio + tuning de parámetros |
| balance = 0% y reach < 90% | Revisar adaptive penalty (¿vel_penalty_max muy alto?) |
