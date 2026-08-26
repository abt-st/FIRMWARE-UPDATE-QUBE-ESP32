# Gemelo Digital del QUBE Servo para Entrenar DRL — Viabilidad y Plan de Trabajo

**Fecha:** 2026-06-18
**Objetivo:** Evaluar la viabilidad de construir un *gemelo digital* (digital twin) del péndulo rotatorio invertido QUBE Servo (ESP32) para entrenar políticas de control por Aprendizaje por Refuerzo Profundo (DRL), y —de ser viable— presentar un plan de trabajo accionable.
**Estado del repositorio analizado:** rama `DRL_IMP`, paquete `src/qube_rl`.

> **Documento relacionado:** `viabilidad_aprendizaje_refuerzo.md` (viabilidad general de RL) y `MODELO_FISICO_SISTEMA_QUBE.md` (ecuaciones de movimiento). Este documento se centra específicamente en el **gemelo digital como herramienta de entrenamiento sim-to-real** y aporta un plan calibrado al estado *real* del código.

---

## 1. Veredicto

### ✅ Viable — y, de hecho, ya está iniciado.

El gemelo digital no es una propuesta a futuro: existe una **primera versión funcional** en `src/qube_rl`. La pregunta de investigación ya no es *"¿se puede construir?"* sino *"¿qué le falta para ser un gemelo digital de fidelidad suficiente para que la política transferida funcione en el hardware real?"*.

| Componente del gemelo digital | Estado actual en el repo | Archivo |
|---|---|---|
| Dinámica no lineal del Furuta (Euler-Lagrange) | ✅ Implementada (portada de `Armandpl/furuta`) | `src/qube_rl/envs/qube_dynamics.py` |
| Entorno Gymnasium de simulación | ✅ Implementado (integración Euler semi-implícita @ 500 Hz, control @ 50 Hz) | `src/qube_rl/envs/qube_sim.py` |
| Entorno Gymnasium del hardware real (HTTP/ESP32) | ✅ Implementado | `src/qube_rl/envs/qube_real.py` |
| Domain randomization | ✅ Implementada (Gaussiana por parámetro, sin *drift*) | `qube_dynamics.py::randomize()` |
| Modelado de no-idealidades (cuantización encoder, filtro de velocidad, zona muerta) | ✅ Parcial | `qube_sim.py`, `wrappers/deadzone.py`, `utils.VelocityFilter` |
| Algoritmo DRL (SAC + gSDE) | ✅ Configurado | `config.py::SACConfig`, `train.py` |
| Exportación a ESP32 (RLtools) + destilación | ✅ Implementada | `export_rltools.py`, `distill.py` |
| Tracking de experimentos (MLflow) | ✅ Implementado | `mlflow_tracking.py` |
| **Calibración de parámetros con datos reales (system ID)** | ❌ **Pendiente** — los parámetros son estimaciones nominales | — |
| **Validación cuantitativa sim-vs-real del gemelo** | ❌ **Pendiente** | — |
| **Cierre del lazo sim-to-real medido (tasa de éxito en hardware)** | ❌ **Pendiente** | — |

**Conclusión:** la infraestructura está construida. El trabajo de tesis con mayor valor científico es **convertir el simulador en un gemelo digital *validado***: identificar los parámetros físicos con datos reales, cuantificar la brecha sim-to-real y cerrarla. Eso es exactamente lo que distingue un "simulador" de un "gemelo digital".

---

## 2. ¿Qué es un "gemelo digital" en este contexto?

Un gemelo digital es un modelo de simulación de un sistema físico concreto que (a) está **calibrado con datos del sistema real**, (b) se **valida cuantitativamente** contra su comportamiento medido, y opcionalmente (c) se **actualiza** con datos nuevos. Para RL, su función es ser la *fuente de muestras barata y segura* que reemplaza la interacción —costosa y peligrosa para el hardware— con el sistema físico.

Un simulador genérico con parámetros "de catálogo" **no** es un gemelo digital: solo lo es cuando se demuestra que reproduce el sistema real dentro de una tolerancia. La literatura de digital twins formaliza esto como un problema de **identificación de sistemas (gray-box) + validación** (Phillips et al., 2024; ver §6).

La brecha entre el gemelo y la realidad ("reality gap") se cierra con dos familias de técnicas complementarias, ambas ya soportadas por el código:

1. **Identificación de sistema** → ajustar los parámetros del modelo a los datos reales (reduce el sesgo del modelo).
2. **Domain randomization** → entrenar sobre una *distribución* de modelos para que la política sea robusta a la incertidumbre residual (Tobin et al., 2017; Peng et al., 2018).

---

## 3. Análisis de brechas (lo que impide que hoy sea un gemelo "de verdad")

1. **Parámetros físicos sin identificar.** `qube_dynamics.py` usa valores por defecto heredados de `Armandpl/furuta` (p. ej. `Lp=0.129 m`, `Mp=0.024 kg`, `Rm=8.4 Ω`, `km=0.042`). No provienen de mediciones del hardware propio. Sin identificación, el "gemelo" simula *otro* péndulo parecido.

2. **Inconsistencia documental de hardware.** `MODELO_FISICO_SISTEMA_QUBE.md` describe un driver **L298N**, pero `qube_dynamics.py` modela un **BTS7960** (y existe `backup_l298n/`, lo que confirma una migración de driver). El modelo del actuador del gemelo debe corresponder al hardware *actual*. Hay que reconciliar la documentación y el modelo del puente H / motor.

3. **Sin validación cuantitativa sim-vs-real.** No hay un experimento que compare trayectorias simuladas contra trayectorias reales (mismo *input* PWM → comparar `θ(t)`, `α(t)`). Sin esto no se puede afirmar fidelidad.

4. **Modelo del actuador simplificado.** La dinámica usa un modelo DC en régimen permanente (`trq = km·(V − km·θ̇)/Rm`, saturado a `stall_torque`). Faltan, y son medibles: **zona muerta / fricción estática** (parcialmente cubierta por `wrappers/deadzone.py`), retardo de comunicación/cómputo, y la relación real PWM→voltaje del BTS7960.

5. **Brecha de latencia.** `qube_real.py` introduce un `sleep(0.01)` por paso y comunica por HTTP/WiFi; el simulador asume el lazo a 50 Hz ideal. La latencia y el jitter del lazo real deben modelarse o acotarse (el `history_wrapper` ayuda a observar dinámica de segundo orden, pero la latencia es un *gap* explícito).

---

## 4. Plan de Trabajo

El plan está dividido en 5 fases. Cada fase produce un entregable verificable y se apoya en módulos que **ya existen**, minimizando código nuevo.

### Fase 0 — Consolidación y reconciliación (≈ 3–5 días)
**Meta:** punto de partida coherente y reproducible.
- [ ] Reconciliar el modelo de hardware: confirmar driver actual (BTS7960) y actualizar `MODELO_FISICO_SISTEMA_QUBE.md` para que coincida con `qube_dynamics.py`. Documentar la relación PWM→voltaje real.
- [ ] Inventariar los datos experimentales ya capturados (`experiments/*/data/*.csv`) y catalogar qué señales contienen (PWM, `θ`, `α`, corriente INA219, tiempo).
- [ ] Fijar la *fuente de verdad* de parámetros: mover los valores nominales a un archivo de configuración versionado (extender `config.py`) con incertidumbre asociada (los `*_std` ya existen).
- **Entregable:** documento de "configuración base del gemelo" + dataset catalogado.

### Fase 1 — Identificación de parámetros (system ID) (≈ 1.5–2 semanas)
**Meta:** reemplazar parámetros de catálogo por parámetros *medidos*. Esto es lo que convierte el simulador en gemelo digital.
- [ ] **Mediciones directas** (las más baratas y fiables): masa y longitud del péndulo y del brazo (balanza + regla), `Rm` (multímetro), CPR del encoder (ya conocido: 2048×4).
- [ ] **Identificación dinámica gray-box:** diseñar experimentos de excitación en el hardware:
  - Decaimiento libre del péndulo colgando → estima `Dp` (fricción) y frecuencia natural → valida `Lp`, `Mp` vía periodo de oscilación.
  - Escalón/chirp de PWM con el brazo libre → estima `km`, `Dr`, dinámica del motor.
- [ ] Ajustar los parámetros del modelo minimizando el error entre trayectoria simulada y real (`scipy.optimize.least_squares` sobre `QubeDynamics`). Es un ajuste de pocos parámetros sobre un modelo ya implementado.
- [ ] Recalibrar los `*_std` de domain randomization a la **incertidumbre real** observada (no inventada).
- **Entregable:** tabla de parámetros identificados con su intervalo de confianza + script de identificación reproducible en `experiments/`.

### Fase 2 — Validación del gemelo (≈ 1 semana)
**Meta:** demostrar fidelidad cuantitativa (criterio de aceptación del gemelo).
- [ ] Protocolo *open-loop*: aplicar la **misma secuencia de PWM** al hardware y al simulador desde el mismo estado inicial; comparar `θ(t)`, `α(t)`.
- [ ] Métricas: RMSE de ángulos, error en frecuencia de oscilación, divergencia temporal (horizonte hasta superar umbral). Definir criterio de aceptación (p. ej. RMSE de `α` < X° en N segundos).
- [ ] Validar también un caso *closed-loop* conocido: ejecutar el LQR existente (`lqr.py`) en sim y en real y comparar.
- **Entregable:** informe de validación con gráficas sim-vs-real y veredicto pasa/no-pasa. (Reusar `qube_analysis/plotter.py`.)

### Fase 3 — Entrenamiento DRL sobre el gemelo (≈ 1.5–2 semanas)
**Meta:** política de swing-up + balance entrenada íntegramente en el gemelo.
- [ ] Entrenar **SAC** (ya configurado, `SACConfig` con `net_arch=64` que cabe en ESP32) con domain randomization activado, usando los parámetros e incertidumbres de las Fases 1–2.
- [ ] Barridos con MLflow (`mlflow_tracking.py`, `auto_train.py`): función de recompensa (`rewards.py` / `rewards_simple.py`), peso del *continuity cost*, escala de randomization.
- [ ] Evaluar robustez **en el propio gemelo** ante perturbaciones y ante parámetros fuera de la distribución de entrenamiento (test de generalización antes de tocar hardware).
- **Entregable:** política entrenada + curvas de aprendizaje y métricas en MLflow.

### Fase 4 — Cierre del lazo sim-to-real (≈ 1.5–2 semanas)
**Meta:** medir y cerrar la brecha en el hardware real.
- [ ] Exportar la política a ESP32 (`export_rltools.py` / `distill.py`) y/o evaluarla vía `qube_real.py` (modo 6) con PWM limitado por seguridad.
- [ ] Medir **tasa de éxito de swing-up**, tiempo de estabilización y rechazo a perturbaciones en hardware (criterios ya definidos en `MODELO_FISICO`, §13).
- [ ] Si hay brecha residual: iterar con (a) más domain randomization, (b) *fine-tuning* corto en hardware (`finetune.py` ya existe), (c) modelar la latencia HTTP/WiFi medida.
- [ ] **Comparativa final** (aporte de tesis): DRL vs. LQR vs. PID/energía sobre la *misma* plataforma, en las mismas métricas.
- **Entregable:** resultados en hardware + tabla comparativa DRL/LQR/clásico + discusión de la brecha sim-to-real.

### Fase 5 — Documentación y reproducibilidad (transversal, ≈ 3–5 días)
- [ ] Redactar la metodología del gemelo digital para el capítulo de tesis (con las referencias de §6).
- [ ] Asegurar reproducibilidad: *seeds* (`config.set_global_seeds`), versiones (`python-313-pin-and-venv-locks`), y artefactos en MLflow.

**Cronograma agregado:** ≈ 7–9 semanas. La ruta crítica es Fase 1 → Fase 2 (sin un gemelo validado, todo lo demás carece de respaldo científico).

---

## 5. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Brecha sim-to-real demasiado grande | La política no transfiere | Domain randomization (ya implementada) + fine-tuning en hardware (`finetune.py`) |
| Parámetros mal identificados (datos ruidosos) | Gemelo sesgado | Filtrado, múltiples repeticiones, validación open-loop independiente (Fase 2) |
| Latencia/jitter del lazo HTTP-WiFi | Inestabilidad en real no vista en sim | Medir latencia real; modelarla en sim o migrar el lazo de inferencia *on-device* (RLtools en ESP32) |
| Daño al hardware durante swing-up | Pérdida de tiempo/equipo | Límites de PWM y de `θ`, terminación temprana (ya en `qube_real.py`) |
| Inconsistencia modelo/hardware (L298N vs BTS7960) | Identificación sobre el modelo equivocado | Resolver en Fase 0 antes de medir |

---

## 6. Referencias confiables (verificadas)

> Verificadas vía arXiv/JMLR/IEEE Xplore/ScienceDirect/MathWorks/GitHub. Se corrigen varias citas erróneas que circulaban en el documento de viabilidad previo (ver notas).

### Sim-to-real y domain randomization
1. Zhao, W., Queralta, J. P., & Westerlund, T. (2020). *Sim-to-Real Transfer in Deep Reinforcement Learning for Robotics: a Survey*. IEEE SSCI 2020, 737–744. https://doi.org/10.1109/SSCI47803.2020.9308468 · arXiv:2009.13303
2. Tobin, J., Fong, R., Ray, A., Schneider, J., Zaremba, W., & Abbeel, P. (2017). *Domain Randomization for Transferring Deep Neural Networks from Simulation to the Real World*. IEEE/RSJ IROS 2017, 23–30. https://doi.org/10.1109/IROS.2017.8202133 · arXiv:1703.06907
3. Peng, X. B., Andrychowicz, M., Zaremba, W., & Abbeel, P. (2018). *Sim-to-Real Transfer of Robotic Control with Dynamics Randomization*. IEEE ICRA 2018, 3803–3810. https://doi.org/10.1109/ICRA.2018.8460528 · arXiv:1710.06537

### Gemelo digital / identificación de sistemas
4. Phillips, D. M., et al. (2024). *Validation Framework of a Digital Twin: A System Identification Approach*. INCOSE International Symposium, 34(1). https://doi.org/10.1002/iis2.13145 *(confirmar lista completa de autores en la página del editor antes de la entrega)*
5. *Evaluating the use of grey-box system identification for digital twins in manufacturing automation* (2024). International Journal of Computer Integrated Manufacturing. https://doi.org/10.1080/0951192X.2024.2386980
6. *A Comprehensive Review of Digital Twin — Part 1: Modeling and Twinning Enabling Technologies* (2022). arXiv:2208.14197

### RL en microcontroladores (despliegue ESP32)
7. Eschmann, J., Albani, D., & Loianno, G. (2024). *RLtools: A Fast, Portable Deep Reinforcement Learning Library for Continuous Control*. JMLR, 25(301), 1–19. https://jmlr.org/papers/volume25/24-0248/24-0248.pdf · arXiv:2306.03530 *(primera demostración de entrenamiento DRL en un microcontrolador; antes llamado BackpropTools)*

### Algoritmos base
8. Schulman, J., Wolski, F., Dhariwal, P., Radford, A., & Klimov, O. (2017). *Proximal Policy Optimization Algorithms*. arXiv:1707.06347
9. Haarnoja, T., Zhou, A., Abbeel, P., & Levine, S. (2018). *Soft Actor-Critic*. ICML 2018, PMLR 80, 1861–1870. arXiv:1801.01290
10. Fujimoto, S., van Hoof, H., & Meger, D. (2018). *Addressing Function Approximation Error in Actor-Critic Methods* (TD3). ICML 2018, PMLR 80. arXiv:1802.09477

### Péndulo Furuta / inverted pendulum — RL y swing-up
11. Åström, K. J., & Furuta, K. (2000). *Swinging up a pendulum by energy control*. Automatica, 36(2), **278–285**. https://doi.org/10.1016/S0005-1098(99)00140-5 *(NB: pp. 278–285; varias fuentes citan erróneamente 287–295)*
12. Hong, M.-R., et al. (2023). *Optimizing Reinforcement Learning Control Model in Furuta Pendulum and Transferring It to Real-World*. IEEE Access, 11, 95195–95200. https://doi.org/10.1109/ACCESS.2023.3310405
13. *Sim-to-Real Reinforcement Learning for a Rotary Double-Inverted Pendulum Based on a Mathematical Model* (2025). Mathematics, 13(12), 1996. https://doi.org/10.3390/math13121996
14. Khan, S., et al. (2025). *A transfer learning based deep neural network adaptive controller for the Furuta pendulum subject to uncertain disturbance signals*. Scientific Reports, 15. https://www.nature.com/articles/s41598-025-10021-1

### Proyecto base (dinámica portada)
15. Du Parc Locmaria, A. (Armandpl). *furuta: Building and Training a Rotary Inverted Pendulum robot* [software]. GitHub. https://github.com/Armandpl/furuta · Reporte técnico W&B (2021): https://wandb.ai/armandpl/furuta/reports/Training-Reproducible-Robots-with-W-B--VmlldzoxMTY5NTM5

### Recursos MathWorks / Quanser (QUBE-Servo + RL)
16. The MathWorks, Inc. *Train Reinforcement Learning Agents to Control Quanser QUBE Pendulum* [doc., RL Toolbox]. https://www.mathworks.com/help/reinforcement-learning/ug/train-agents-to-control-quanser-qube-pendulum.html *(usa TD3/DDPG)*
17. MathWorks (GitHub). *Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2*. https://github.com/mathworks/Reinforcement-Learning-Inverted-Pendulum-with-QUBE-Servo2

> **Correcciones a la bibliografía previa:** (a) **No existe** el blog "Solving Real World RL with a Furuta Pendulum" de Armandpl — usar el repo GitHub + reporte W&B. (b) **No citar** un "blog de Quanser 2026": las entradas de Quanser existen pero sin esa fecha; preferir la documentación oficial de MathWorks (TD3/DDPG, no PPO). (c) RLtools es **2024 (JMLR)**, no 2023.

---

*Documento generado: 2026-06-18 · Plan de gemelo digital para entrenamiento DRL del QUBE Servo ESP32. Construido sobre el paquete `src/qube_rl` existente.*
