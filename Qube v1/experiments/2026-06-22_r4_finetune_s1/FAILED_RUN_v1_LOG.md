# R4 Fine-tune v1 — FAILED RUN LOG

## Resumen

- **Fecha:** 2026-06-22
- **Script:** `run_finetune.py`
- **Base model:** `experiments/2026-06-19_r4_curriculum/models/r3_01_curriculum04_s1.zip`
- **Status final:** FAILED (MLflow run_uuid: `5c205da290fe4d4d...`)
- **Causa:** El `model.save()` y `evaluate_balance()` estaban dentro del bloque `with mlflow_run()`. El eval crasheó o el context manager falló en `__exit__`, impidiendo que el modelo se guardara a disco.

## Configuración

| Parámetro | Valor |
|-----------|-------|
| reward | `linear_alpha` |
| near_upright_prob | 0.4 |
| LR (fine-tune) | 1e-4 (base era 3e-4) |
| timesteps | 500,000 |
| seed | 1 |
| eval_episodes | 30 |
| net_arch | [64, 64] |
| MLflow experiment | `qube_r4_finetune` |

## Métricas de entrenamiento (500k steps completados)

| Métrica | Valor final (step 500k) |
|---------|------------------------|
| ep_rew_mean | **477.5690** |
| ep_len_mean | **500.0000** |
| actor_loss | -131.8835 |
| critic_loss | 0.4709 |
| ent_coef | 0.1778 |
| ent_coef_loss | 0.5927 |
| learning_rate | 0.0003* |
| n_updates | 998,000 |

*Nota: el LR reportado por el callback parece ser el default (3e-4), no el fine-tune (1e-4). Verificar si el callback lee `model.learning_rate` o el optimizer directly.

## Evolución del reward (checks manuales)

| Step | ep_rew_mean | ep_len_mean | Hora aprox |
|------|-------------|-------------|------------|
| 20k | 458.7 | 489.3 | +10min |
| 33k | 464.7 | 493.5 | +20min |
| 50k | 468.6 | 495.7 | +25min |
| 64k | 471.8 | 500.0 | +35min |
| 87k | 475.3 | 500.0 | +50min |
| 99k | 470.2 | 495.2 | +60min |
| 197k | 476.1 | 500.0 | +3h |
| 206k | 475.2 | 500.0 | +3h10min |
| 301k | 477.1 | 500.0 | +3h30min |
| 333k | 469.8 | 495.3 | +3h45min |
| 363k | 469.6 | 495.3 | +4h |
| **500k** | **477.6** | **500.0** | **+4.5h** |

## Diagnóstico

1. **El entrenamiento SÍ completó** los 500k steps (step=500000 en MLflow)
2. **El modelo NO se guardó** a disco — el archivo `.zip` nunca apareció en `models/`
3. **El eval nunca corrió** — probablemente `evaluate_balance()` o `make_sim_env()` falló
4. **Status FAILED** — el `mlflow_run()` context manager marcó el run como failed
5. **Posible causa raíz:** `model.save()` estaba dentro del `with mlflow_run()` block. Si el `__exit__` del context manager falla, puede que:
   - El save se ejecutó pero fue revertido
   - O el exception propagado antes del save
   - O el save sí corrió pero un race condition con mlflow

## Lección aprendida

**NUNCA** poner `model.save()` dentro de un `with mlflow_run()` block. Guardar el modelo ANTES del context manager o al menos ANTES del eval.

## Fix: v2 (`run_finetune_v2.py`)

- `model.save()` se ejecuta **fuera** del `with mlflow_run()`, inmediatamente después de `model.learn()`
- `evaluate_balance()` está en un `try/except` — si falla, el modelo ya está guardado
- Sin tracking MLflow en la v2 (se puede agregar después si es necesario)

## Modelo base (R4 mejor) — métricas de referencia

| Métrica | R4 base (500k steps) |
|---------|---------------------|
| balance_rate | 51.1% (avg across seeds) |
| reach_rate | 100% |
| upright_fraction | 72.7% |
| max_hold_s | 6.28s |
| ep_rew_mean | ~475 |

El fine-tune v1 alcanzó ep_rew=477.6 (ligeramente mejor que el base), pero sin eval no sabemos si balance/upright mejoraron.
