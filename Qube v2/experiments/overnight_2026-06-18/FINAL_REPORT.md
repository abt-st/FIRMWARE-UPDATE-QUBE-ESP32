# INFORME FINAL — Entrenamiento DRL nocturno (QUBE swing-up/balance)

- **Inicio:** 2026-06-18 02:46:43  |  **Fin:** 2026-06-18 07:57:59
- **Tiempo total:** 5:11:16  (presupuesto: 5.0 h)
- **Experimentos completados:** 5/6  (presupuesto agotado antes de terminar todos)

Métrica de éxito = **balance_rate** (fracción de episodios que mantienen el péndulo invertido-y-lento ≥1 s). El histórico del proyecto era **0% de balance**; este es el número a batir.

## Ranking de configuraciones (por balance, luego upright, luego reach)

| # | Experimento | reward | PBRS | balance % | reach % | upright % | hold máx (s) | ep_rew |
|---|---|---|---|---|---|---|---|---|
| 1 | 03_linear_alpha_base | `linear_alpha` | `None` | 0±0 | 100±0 | 3.5 | 0.49 | 318.82 |
| 2 | 02_linear_alpha_pbrs | `linear_alpha` | `upright` | 0±0 | 100±0 | 2.4 | 0.12 | 310.30 |
| 3 | 01_swingup_balance_base | `swingup_balance` | `None` | 0±0 | 0±0 | 0.0 | 0.00 | -1.72 |
| 4 | 04_swingup_balance_pbrs | `swingup_balance` | `upright` | 0±0 | 0±0 | 0.0 | 0.00 | -1.73 |
| 5 | 05_linear_alpha_dense | `linear_alpha_dense` | `None` | 0±0 | 0±0 | 0.0 | 0.00 | 78.62 |

## Conclusiones

- **Mejor configuración:** `03_linear_alpha_base` (reward=`linear_alpha`, PBRS=`None`).
  balance **0.0%** ± 0.0%, reach 100%, upright 3.5%, hold máx 0.49 s.
- ⚠️ **El swing-up funciona pero el balance sigue siendo el cuello de botella.** Siguientes pasos sugeridos: más timesteps, currículo (resetear cerca del invertido), warm-start desde el controlador energía+LQR, o RL residual sobre LQR.

## Cómo inspeccionar

```bash
uv run mlflow ui --backend-store-uri sqlite:///mlflow.db   # experimento: qube_overnight
```

Reportes por experimento: `overnight_2026-06-18/report_*.md`. Modelos: `models/qube_overnight_*.zip`.

---

## Análisis del operador (lectura profunda de los resultados)

### Hallazgo 1 — La recompensa importa MÁS que el algoritmo: `linear_alpha` resuelve el swing-up; `swingup_balance` (el default) **fracasa por completo**
- `linear_alpha` (con o sin PBRS): **100% reach** en ambas semillas, ep_rew ~310–320. Swing-up **consistente y reproducible**.
- `swingup_balance` (reward **por defecto**) y `cos_alpha`-likes: **0% reach**, ep_rew ≈ **−1.72**. El agente no aprende **nada**.
- **Causa raíz (confirma REFERENCE.md):** `swingup_balance` usa `(1−cos α)/2`, cuyo gradiente es **casi nulo cuando el péndulo cuelga** → el agente no recibe señal para empezar a bombear y nunca despega. `linear_alpha` usa `|α|/π` (gradiente constante) → señal clara desde el primer paso. Esto es un resultado **citable para la tesis**.
- **Acción:** cambiar el reward por defecto a `linear_alpha` (o documentar que `swingup_balance` no es entrenable a 150k pasos).

### Hallazgo 2 — Los arreglos v1.44 movieron el "reach" de forma decisiva
Con `linear_alpha` el swing-up pasa a **100% reach** y el agente **se queda merodeando** cerca del invertido (antes el episodio terminaba justo al llegar). El fix **C1** (no terminar en la meta) + **θ±120°** + **TimeLimit** son los que habilitan esto. El cuello de botella se desplazó de "llegar arriba" a "quedarse arriba".

### Hallazgo 3 — El balance sigue en 0%, pero ahora el límite es claro y medible
- Mejor caso: `linear_alpha` base, semilla 1 → **upright 5.8%**, **hold máximo 0.66 s**. Llega arriba y se sostiene fracciones de segundo, pero **nunca ≥1 s**.
- La métrica nueva (`evaluate_balance`) hace este límite **visible y honesto**: reach 100% / balance 0% / hold 0.66s describe exactamente el problema (falta la estabilización final).

### Hallazgo 4 — PBRS (`upright`) **no ayudó** (incluso perjudicó levemente)
- `linear_alpha` base: upright **3.5%**, hold máx **0.49 s**.
- `linear_alpha` + PBRS: upright **2.4%**, hold máx **0.12 s**.
- El potencial `Φ=(1−cos α)/2` es probablemente **demasiado débil / desalineado** (no premia velocidad baja ni brazo centrado en el ápice). No descarta PBRS; descarta **este** potencial. Próximo: potencial basado en energía o que incluya `−|α̇|` y centrado de θ cerca del invertido.

### Hallazgo 5 — `linear_alpha_dense` es inestable
ep_rew 150.98 vs 6.25 entre semillas (alta varianza) y 0% reach. El *shaping* de velocidad de esa variante **desestabiliza** el aprendizaje respecto a `linear_alpha` plano. Descartar.

### Siguientes pasos (priorizados por relación valor/esfuerzo)
1. **Escalar `linear_alpha` a 500k–1M pasos** (los handoffs ya sugerían que 169° llegaba a 500k). 150k basta para reach pero no para que emerja el balance. **Mayor probabilidad de romper el 0%.**
2. **Currículo:** iniciar una fracción de episodios **cerca del invertido** (`α≈π`) para que el agente aprenda a **balancear** directamente, y luego ampliar hacia colgando. La factory ya permite construir el entorno; falta un wrapper/reset opcional con estado inicial mixto.
3. **RL residual sobre LQR** (`u = u_LQR + π_θ`): combina la garantía local del LQR (que el firmware ya tiene) con RL. Alta probabilidad de balance.
4. **Rediseñar el potencial PBRS** (energía / `−|α̇|` + centrado) si se quiere insistir con shaping.
5. **Warm-start/destilación** desde los mejores modelos de swing-up de esta noche
   (`models/qube_overnight_03_linear_alpha_base_s1.zip`) como teacher.

### Veredicto
Noche **productiva y concluyente**: identificó el **mejor reward** (`linear_alpha`, 100% reach reproducible), **descartó** dos variantes (`swingup_balance` default y `linear_alpha_dense`) y **este** PBRS, y **acotó el problema** restante a la estabilización final (hold < 1 s). El balance sostenido sigue abierto; el camino más prometedor es **más pasos + currículo / RL residual** sobre `linear_alpha`.

