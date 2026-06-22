# Métodos alternativos para resolver el balance con DRL (QUBE)

> **Contexto:** estado de los ensayos RL al 2026-06-22 y catálogo de métodos
> alternativos para que la política DRL cumpla la tarea de **swing-up + balance
> sostenido** (péndulo invertido ≤12° y lento ≤1 rad/s durante ≥1 s continuo).
>
> Branch: `DRL_IMP` · Métrica de éxito: `balance_rate` (histórico: **0 %**).

---

## 1. Estado actual de los ensayos (R4 relanzado)

El run de confirmación R4 había muerto en silencio el 19-jun (la sesión que lo
lanzó se cerró). Relanzado el 2026-06-22 con `nohup`, desacoplado de la terminal.

- **Config:** `linear_alpha` + `near_upright_prob=0.4`, **500k × 3 seeds** (config
  ganadora primero), luego `0.6` si sobra presupuesto. Plan del HANDOFF.
- **Presupuesto:** 10 h. Primer seed ~2 h.
- **Log:** `experiments/2026-06-19_r4_curriculum/run_r4_2026-06-22.log`
- **MLflow:** experimento `qube_r4_curriculum`
- **Mejor resultado histórico (a confirmar por R4):** R3-curriculum config 03 →
  `upright 30.4 %`, `hold_max 0.92 s` (1 seed, 300k) — a **0.08 s** del umbral de 1 s.

> Riesgo: si la máquina entra en suspensión, el entrenamiento se pausa.

---

## 2. Diagnóstico — por qué está atascado

El problema **no es una mala loss**, es un **conflicto estructural de un único
objetivo escalar**: una recompensa densa tiene que servir a dos regímenes
físicamente opuestos.

| Régimen | Lo que necesita | Lo que lo rompe |
|---|---|---|
| **Swing-up** | bombear energía → α̇ **alto** al pasar por arriba | cualquier penalización de velocidad → "colgar quieto" se vuelve óptimo local → **0 % reach** |
| **Balance** | disipar energía → α̇ **bajo**, control de precisión | el gradiente de `linear_alpha` (`\|α\|/π`) premia *estar arriba* pero es **plano en velocidad** → no enseña a frenar |

Evidencia en los datos:

- `linear_alpha` → **100 % reach, 0 % balance** (sube fiable, no se queda).
- `linear_alpha_balance` (penalización de velocidad global) → **0 % reach** (mata el swing-up).
- `linear_alpha_stabilise` (damping gateado en `|α|>π/2` + bono gaussiano) → **0 % reach**:
  el damping todavía castiga el **paso a alta velocidad por el ápice**.

**Conclusión:** "compound loss" en RL no es la loss del optimizador (la de SAC es
fija) — el equivalente real es **reward compuesta + currículo + regularización de
política**. La clave es añadir señal de balance **sin** distorsionar el óptimo del
swing-up.

---

## 3. Métodos alternativos (rankeados por valor/riesgo y encaje con el código)

### ⭐ A. PBRS — *potential-based reward shaping* (la "compound reward" correcta)

Ya existe el wrapper (`src/qube_rl/wrappers/potential_shaping.py`) pero **nunca se
usó en los experimentos** (todos `potential=None`).

PBRS añade `F = γ·Φ(s′) − Φ(s)`. Ng, Harada & Russell (1999) probaron que esta
forma **deja la política óptima invariante** (policy invariance) → matemáticamente
**no puede matar el swing-up**, a diferencia de las penalizaciones ad-hoc.

- **Acción concreta:** añadir un potencial **energético** a `POTENTIALS` (hoy solo
  hay `_phi_upright = (1−cos α)/2`):

  ```
  Φ(s) = w₁·(1 − cos α)/2 − w₂·(E(s) − E_top)²
  ```

  con `E` = energía mecánica total. Da un gradiente físicamente significativo
  hacia "arriba *y* con la energía justa" (base del swing-up clásico por
  *energy-shaping* de Åström–Furuta).
- **Crítico:** el `gamma` del wrapper debe **igualar** el `gamma=0.995` del agente.
  Hoy el default del wrapper es `0.99` → bug latente si se activa sin pasar el gamma.

### ⭐ B. Currículo inverso *recocido* (annealing) — potenciar la palanca ganadora

El currículo funciona pero es **estático**: `near_upright_prob` fijo y spread fijo
(`_NEAR_UPRIGHT_SPREAD`). El método de Florensa (CoRL'17, ya citado en el código)
**mueve la distribución de inicio hacia afuera** a medida que el agente aprende.

- **Acción concreta:** empezar con `near_upright_prob ≈ 0.9` y spread *tight*
  (±10°), y **decaer ambos** durante el entrenamiento (vía callback). Da
  experiencia densa de balance al principio y luego enseña el "puente" desde más
  lejos. Barato y montado sobre lo único que ya dio 30.4 %.

### B-bis. Reward consciente de *duración* (ataca la métrica directamente)

El criterio de éxito es **hold continuo ≥ 1 s**, pero ninguna reward premia la
*continuidad*. Un bono que crece con pasos consecutivos dentro de la zona de éxito
(un "streak bonus", reseteado al salir) empuja justo hacia los 0.08 s que faltan.
Riesgo de reward-hacking → acotarlo a la zona exacta del eval (±12°, α̇ ≤ 1).

### C. Regularización de suavidad de acción (CAPS, Mysore et al. 2021)

Cerca del ápice SAC inyecta ruido (max-entropy) que mete *chatter* y tumba el
péndulo. Penalizar `‖aₜ − aₜ₋₁‖` (temporal) + `‖a(s) − a(s+ruido)‖` (espacial).
Ayuda al balance **y** al futuro sim2real. Ya existe `use_continuity_cost` en
`HistoryWrapper` — verificar si está activo y, en su caso, subirlo.

### C-bis. Bajar / recocer la entropía objetivo de SAC

La entropía objetivo por defecto (`-dim(A) = -1`) mantiene exploración que
desestabiliza el balance fino. Recocer `target_entropy` hacia ~0 en la fase final;
evaluar determinista (ya se hace).

### 🛟 D. Híbrido RL → LQR (fallback) — solución *garantizada* para la tesis

RL hace swing-up, el firmware conmuta a **LQR modo 4** al llegar arriba. Es el
enfoque estándar del Furuta en la literatura y **cumple la tarea designada con
seguridad**. Para defensa de tesis es un resultado legítimo y fuerte. Variante
"más ML": **dos políticas + switch** (opciones jerárquicas), ambas aprendidas.

---

## 4. Recomendación

Cuando R4 termine y se vea si el multi-seed confirma ~0.9 s:

- **R5 = A + B juntos** (PBRS energético con γ casado + currículo recocido). Es la
  combinación principista de mayor valor esperado, reutiliza el código existente y,
  por diseño, **no puede romper el swing-up** — directamente lo que ha frenado cada
  ronda.
- Mantener **D (híbrido LQR)** como red de seguridad garantizada para la tesis.

### 4.1 R5 — implementado y en cola (2026-06-22)

Ya está cableado y validado (smoke test OK); se lanza en cuanto R4 libere la máquina
(ver §"correr en paralelo": RAM libre ~1.1 GB no da para dos runs).

- **Código nuevo:**
  - `rewards.py` → `linear_alpha_apex_stabilise`: damping **gateado a ~30° del
    ápice** (no π/2) — corrige la causa de que `linear_alpha_stabilise` matara el
    swing-up. Verificado: el paso rápido por la horizontal **no** se penaliza.
  - `wrappers/potential_shaping.py` → potencial `"energy"` (KE+PE con las
    constantes de `QubeDynamics`, `E_top=c₄`), policy-invariante (recomendación A / EBERL).
  - `envs/factory.py` → pasa `potential_gamma`, `potential_scale`,
    `potential_energy_weight` al wrapper (γ casado a 0.995).
  - `experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py` → callback
    `CurriculumAnneal` (near_upright_prob 0.6→0.2 sobre el 70% del entrenamiento) +
    flag `--no-mlflow` para smoke tests sin tocar el `mlflow.db` en uso.
- **Matriz R5:** `01_apex_anneal` (apuesta principal), `02_pbrs_energy_anneal`
  (recomendación A aislada), `03_apex_static` (ablación: sin annealing).
- **Lanzar:** `.venv/Scripts/python.exe experiments/2026-06-22_r5_pbrs_curriculum/run_r5.py --budget-hours 10 --timesteps 500000 --seeds 0 1 2`

---

## 5. Casos de éxito sim2real (investigación profunda)

> Búsqueda 2026-06-22. Ordenados por **similitud con este proyecto** (Furuta /
> péndulo rotatorio + RL + hardware embebido). Al final, la receta consolidada y
> el contraste con lo que ya hace QUBE.

### 5.1 EBERL — Energy-Based Exploration RL · **mismo hardware (Quanser QUBE2 Furuta), real** ⭐⭐⭐
*Energy-Based Exploration for Reinforcement Learning of Underactuated Mechanical Systems* (2024-25).

El caso **más parecido al tuyo**: validado experimentalmente en el **swing-up y la
estabilización de un Quanser QUBE2 Furuta real** (además de Cartpole y Pendubot en sim).

- **Diagnóstico que comparte contigo:** los sistemas subactuados **empiezan cada
  episodio desde el equilibrio** (colgando) → la exploración está severamente
  limitada y son caóticos → la exploración estándar de RL no basta. *Es
  exactamente tu cuello de botella.*
- **Solución:** modelan la energía del sistema con una **Deep Lagrangian Network
  (DeLaN)** (que respeta la mecánica lagrangiana y conserva energía/pasividad) y la
  acoplan a un **controlador basado en energía** para forzar exploración
  *dirigida al objetivo*, encima de la exploración propia del RL.
- **Lección para QUBE:** valida directo la recomendación **A (potencial
  energético)** y ofrece una segunda vía contra el "arranque desde abajo limita la
  exploración" (la otra vía es tu **currículo inverso, B**). Combinar shaping
  energético + currículo es coherente con la evidencia.

### 5.2 Furuta DIY casero · SAC + gSDE, **~1 min de balance** ⭐⭐⭐
*Real-life Reinforcement Learning – Furuta Pendulum* (energy-in-joles, 2024).

- **Algoritmo:** **SAC** (elegido sobre PPO por eficiencia de muestras, *off-policy*).
- **Clave del éxito:** **gSDE** (Generalized State-Dependent Exploration) —
  *"crítico para aplicaciones robóticas reales, permite políticas más suaves
  aplicables a sistemas físicos"*.
- **Latencia:** forzaron **frecuencia de control fija** (`_enforce_control_frequency()`)
  porque el tiempo de cómputo por paso varía mucho; el baud rate limita el rate
  (50+ Hz a 31250 baud vs 23 Hz a 9600).
- **Resultado:** **~1 minuto de balance sostenido tras 200k timesteps** (entrenando
  *directo en hardware*, sin sim).
- **Lección para QUBE:** **tu config ya coincide con la receta ganadora** →
  `SACConfig` ya tiene `use_sde=True`, `use_sde_at_warmup=True`, `sde_sample_freq=64`
  y `control_freq=50`. Mantén gSDE activo también en *deployment*. La latencia
  WiFi/HTTP del ESP32 (`QubeRealEnv` sobre `192.168.4.1`) es tu equivalente del
  cuello de baud rate → fija el rate y modélala (§5.6).

### 5.3 Sim2Real de péndulo rotatorio doble · *model-based* ⭐⭐
*Sim-to-Real RL for a Rotary Double-Inverted Pendulum Based on a Mathematical Model* (MDPI, 2025).

- **Tesis central:** la **domain randomization por sí sola no cierra el reality gap**
  en sistemas no lineales de alto DOF. Hay que **reforzar la consistencia física
  del modelo mediante estimación de parámetros a partir de datos experimentales**
  → mejora *tanto* la transferibilidad de la política *como* la estabilidad del control.
- **Lección para QUBE:** valida tu pista de **identificación de sistema**
  (`src/qube_analysis/sysid.py` + `experiments/PROTOCOLO_IDENTIFICACION.md`): es el
  lever sim2real #1, por delante de la DR. Identifica fricción (Coulomb + viscosa),
  ganancia del motor e inercias del QUBE real *antes* de randomizar.

### 5.4 Optimización + transferencia de Furuta a real ⭐⭐
*Optimizing RL Control Model in Furuta Pendulum and Transferring It to Real-World* (2023).

- **Hallazgo:** entrenar con un **dominio de estados más amplio** mejora el
  sim2real; logran swing-up consistente **para distintas masas de péndulo** en el
  Furuta físico.
- **Lección:** randomizar parámetros físicos (masa, fricción, ganancia) durante el
  entrenamiento da robustez transferible.

### 5.5 Domain randomization + *fine-tuning* en hardware ⭐⭐
Consenso de varios trabajos (incl. revisiones de DR y triple péndulo invertido):

- Con DR, añadir **20-50 episodios reales** mejora notablemente la política;
  **50-200 episodios** la llevan a nivel de una entrenada 100 % en real.
- **Identificación de fricción del motor + DR** desplegadas con éxito en prototipos
  reales (incl. triple péndulo) para mantener balance.
- **Fine-tuning real con LR más bajo** que en sim.
- **Lección:** ya tienes `src/qube_rl/finetune.py` — el plan correcto es
  sim (con DR) → exportar → 20-200 episodios de *fine-tune* en el ESP32 con LR bajo.

### 5.6 Receta consolidada sim2real (orden recomendado para QUBE)

| # | Palanca | Estado en QUBE | Acción |
|---|---|---|---|
| 1 | **Identificación de sistema** (fricción Coulomb+viscosa, ganancia motor, inercias) desde datos reales | 🟡 en curso (`sysid.py`, protocolo) | Completar y *cablear* los parámetros (y los `*_std` del DR) al `QubeDynamics` del sim |
| 2 | **Domain randomization** alrededor de los params (Rm, km, masas, longitudes, fricciones) | 🟢 **activo** (`QubeDynamics.randomize()` por `reset()`) | Re-centrar `*_std` con los datos de identificación (#1); añadir ruido de encoder/cuantización |
| 3 | **Modelado de latencia/retardo** acción+observación (WiFi/HTTP ESP32) | 🔴 ausente | Inyectar delay de 1-2 pasos en sim; fijar rate de control |
| 4 | **gSDE / suavidad de acción** | 🟢 activo (`use_sde=True`) | Mantener en deployment; opcional CAPS (§3-C) |
| 5 | **Historia de observación** (infiere velocidad/latencia) | 🟢 activo (`HistoryWrapper`, obs 36-D) | OK |
| 6 | **Shaping/exploración energética** (EBERL, Åström) | 🔴 ausente | Recomendación **A** (potencial energético PBRS) |
| 7 | **Fine-tuning en hardware** (LR bajo, 20-200 ep) | 🟡 existe `finetune.py` | Ejecutar tras resolver balance en sim |

### 5.7 Secuenciación (importante)

El balance **aún no está resuelto en simulación**. Las palancas sim2real (#1-#5, #7)
aplican **después** de cerrar el balance en sim — **excepto** la #6
(exploración/shaping energético), que ataca el problema de sim *ahora* y es además
lo que hizo funcionar el QUBE2 real en EBERL. Por eso el plan **R5 = A + B** sigue
siendo el siguiente paso, y la batería sim2real (§5.6) es la fase que le sigue de cara
al hardware de la tesis.

---

## Referencias

- A. Y. Ng, D. Harada, S. Russell. *Policy Invariance Under Reward Transformations*. ICML 1999. (PBRS)
- C. Florensa et al. *Reverse Curriculum Generation for Reinforcement Learning*. CoRL 2017. (currículo inverso)
- S. Mysore et al. *Regularizing Action Policies for Smooth Control with Reinforcement Learning* (CAPS). ICRA 2021.
- K. J. Åström, K. Furuta. *Swinging up a pendulum by energy control*. Automatica 2000. (energy-shaping)
- T. Haarnoja et al. *Soft Actor-Critic*. ICML 2018. (entropía / SAC)

### Sim2real (sección 5)

- *Energy-Based Exploration for Reinforcement Learning of Underactuated Mechanical Systems* (EBERL), 2024-25 — validado en Quanser QUBE2 Furuta real. [ResearchGate](https://www.researchgate.net/publication/392423949_Energy-Based_Exploration_for_Reinforcement_Learning_of_Underactuated_Mechanical_Systems)
- *Real-life Reinforcement Learning – Furuta Pendulum* (energy-in-joles, 2024) — SAC + gSDE, ~1 min de balance. [Blog](https://energy-in-joles.github.io/project/2024-08-31-furuta/) · [GitHub](https://github.com/energy-in-joles/Inverted-Pendulum-Robot)
- *Sim-to-Real RL for a Rotary Double-Inverted Pendulum Based on a Mathematical Model*. MDPI Mathematics 13(12):1996, 2025. [MDPI](https://www.mdpi.com/2227-7390/13/12/1996)
- *Optimizing RL Control Model in Furuta Pendulum and Transferring It to Real-World*, 2023. [ResearchGate](https://www.researchgate.net/publication/373540444_Optimizing_Reinforcement_Learning_Control_Model_In_Furuta_Pendulum_And_Transferring_It_to_Real-World_JULY_2023)
- *Modeling, Simulation, and Control of a Rotary Inverted Pendulum: A RL-Based Approach*. MDPI Eng 5(4):95, 2024. [MDPI](https://www.mdpi.com/2673-3951/5/4/95)
- *Enhancement of Energy-Based Swing-Up Controller via Entropy Search* (Bayesian opt del swing-up energético), 2019. [arXiv:1904.01214](https://arxiv.org/abs/1904.01214)
- Quanser / MathWorks — *RL Toolbox para QUBE-Servo 2* (SAC/PPO/TD3, retos sim2real: latencia, cómputo embebido). [Quanser](https://www.quanser.com/blog/artificial-intelligence/using-the-reinforcement-learning-toolbox-to-balance-an-inverted-pendulum/) · [MathWorks](https://www.mathworks.com/help/reinforcement-learning/ug/train-agents-to-control-quanser-qube-pendulum.html)
- *Efficient Sim-to-Real Transfer in RL Through Domain Randomization and Domain Adaptation*, 2023. [ResearchGate](https://www.researchgate.net/publication/376254940_Efficient_Sim-to-Real_Transfer_in_Reinforcement_Learning_Through_Domain_Randomization_and_Domain_Adaptation)

---

*Documento generado el 2026-06-22. Ver también:
`docs/research/DRL_IMPLEMENTATION_PLAN.md`,
`docs/research/METODOS_ESTABILIZACION_PENDULOS_INVERTIDOS.md`,
`experiments/2026-06-18_r3_curriculum/FINAL_REPORT.md`.*
