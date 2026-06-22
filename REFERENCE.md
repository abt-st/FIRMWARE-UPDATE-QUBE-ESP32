# REFERENCE.md — Guía de fundamentos y análisis del proyecto QUBE-RL

> **Para quién es esto.** Acabas de llegar al repositorio y no tienes base previa en
> Machine Learning (ML), Reinforcement Learning (RL) ni optimización. Este documento te
> da, de cero y de forma autocontenida, todo lo necesario para entender **qué problema
> resuelve este repo, cómo lo ataca con RL, cómo mejorarlo y qué cosas están mal hechas**.
>
> El nivel es **riguroso/formal**: hay ecuaciones, pero cada una va acompañada de su
> intuición. Los términos técnicos se dan en español con el término en inglés entre
> paréntesis, porque la literatura y el código del repo están en inglés.
>
> **Cómo leerlo.** Si nunca viste ML/RL, lee en orden I → II → III. Si solo quieres
> entender el proyecto, salta a la **Parte IV**. Si vas a corregir/mejorar la tesis, lo
> más valioso para ti son las **Partes V y VI**.

---

## Tabla de contenidos

- [Parte 0 — Mapa rápido y glosario mínimo](#parte-0--mapa-rápido-y-glosario-mínimo)
- [Parte I — Fundamentos de ML y optimización](#parte-i--fundamentos-de-ml-y-optimización)
  - [1. ¿Qué es el aprendizaje automático?](#1-qué-es-el-aprendizaje-automático)
  - [2. Optimización: pérdida, gradiente, optimizadores](#2-optimización-pérdida-gradiente-optimizadores)
  - [3. Redes neuronales](#3-redes-neuronales)
- [Parte II — Reinforcement Learning (formal)](#parte-ii--reinforcement-learning-formal)
  - [4. El MDP: el lenguaje del RL](#4-el-mdp-el-lenguaje-del-rl)
  - [5. Políticas, valor y ecuaciones de Bellman](#5-políticas-valor-y-ecuaciones-de-bellman)
  - [6. Ejes de diseño: on/off-policy, model-free, exploración](#6-ejes-de-diseño-onoff-policy-model-free-exploración)
  - [7. Familias de algoritmos y sus pérdidas](#7-familias-de-algoritmos-y-sus-pérdidas)
- [Parte III — Deep RL y SAC](#parte-iii--deep-rl-y-sac-el-algoritmo-de-este-repo)
  - [8. Deep RL y por qué es inestable](#8-deep-rl-y-por-qué-es-inestable)
  - [9. SAC en detalle](#9-sac-soft-actor-critic-en-detalle)
  - [10. Métricas y diagnóstico de entrenamiento](#10-métricas-y-diagnóstico-de-entrenamiento)
- [Parte IV — El problema de este repositorio](#parte-iv--el-problema-de-este-repositorio)
  - [11. El sistema físico (péndulo de Furuta)](#11-el-sistema-físico-péndulo-de-furuta)
  - [12. Las dos tareas: swing-up y balance](#12-las-dos-tareas-swing-up-y-balance)
  - [13. Formulación como MDP (mapeo al código)](#13-formulación-como-mdp-mapeo-exacto-al-código)
  - [14. Objetivos y estado actual de los resultados](#14-objetivos-del-proyecto-y-estado-actual)
  - [15. Las alternativas clásicas (baseline a superar)](#15-las-alternativas-clásicas-energía--lqr)
- [Parte V — Cómo mejorar los resultados y trabajo futuro](#parte-v--cómo-mejorar-los-resultados-y-trabajo-futuro)
- [Parte VI — Errores y problemas detectados](#parte-vi--errores-y-problemas-detectados-franco-por-severidad)
- [Parte VII — Glosario y referencias](#parte-vii--glosario-y-referencias)

---

## Parte 0 — Mapa rápido y glosario mínimo

**El proyecto en una frase.** Construir una versión barata (~45 USD) y abierta del péndulo
invertido rotatorio Quanser QUBE (un **péndulo de Furuta**) usando un ESP32, y enseñar a un
**agente de RL** a hacer el *swing-up* (levantar el péndulo desde colgando hasta invertido) y
mantenerlo en equilibrio, comparándolo con controladores clásicos (PID, LQR, control por energía).

**8 palabras que necesitas ya:**

| Término (EN) | Español | Qué es aquí |
|---|---|---|
| Agent / policy | Agente / política | La "regla" $\pi$ que mira el estado y decide el voltaje del motor |
| Environment | Entorno | El péndulo (simulado o real) que responde a la acción |
| State / observation | Estado / observación | Lo que el agente "ve": ángulos y velocidades |
| Action | Acción | El voltaje aplicado al motor, normalizado a $[-1,1]$ |
| Reward | Recompensa | Número por paso que dice "qué tan bien lo hiciste" |
| Episode | Episodio | Un intento, desde el reset hasta que termina |
| Return | Retorno | Suma (descontada) de recompensas de un episodio |
| Training | Entrenamiento | Ajustar los pesos de la red para maximizar el retorno |

**Componentes del repo (orientación):**

- `src/qube_rl/` — todo el RL en Python (entorno simulado, recompensas, entrenamiento SAC).
- `src/firmware/esp32_qube/` — el firmware C/Arduino del ESP32 (7 modos de control).
- `docs/` — documentación de hardware (`bom.md`, `pinout.md`, `http_api.md`) y `docs/handoffs/`
  (bitácoras de las sesiones de entrenamiento, con los resultados numéricos).
- `models/` — modelos entrenados (`.zip`) y `policy_weights.h` (pesos exportados a C++).
- `CHANGELOG.md` — la historia iteración a iteración del proyecto.

---

# Parte I — Fundamentos de ML y optimización

## 1. ¿Qué es el aprendizaje automático?

**Machine Learning (ML)** es construir programas que *ajustan sus propios parámetros* a partir
de datos en lugar de seguir reglas escritas a mano. Formalmente, buscamos una función
$f_\theta$ (parametrizada por un vector de números $\theta$, los *pesos*) que minimice una
medida de error sobre los datos. Hay tres paradigmas:

1. **Aprendizaje supervisado (supervised).** Tienes pares entrada→etiqueta correcta
   $(x_i, y_i)$ y aprendes $f_\theta(x)\approx y$. Ejemplo: clasificar fotos de gatos.
2. **Aprendizaje no supervisado (unsupervised).** Solo tienes $x_i$ y buscas estructura
   (agrupar, comprimir). Ejemplo: clustering.
3. **Aprendizaje por refuerzo (reinforcement learning, RL).** No hay "respuesta correcta"
   etiquetada. Un **agente** toma **acciones** en un **entorno**, recibe una **recompensa**
   escalar, y debe descubrir *por ensayo y error* qué secuencia de acciones maximiza la
   recompensa acumulada a largo plazo.

**¿Por qué el péndulo es RL y no supervisado?** Porque nadie conoce de antemano la "acción
correcta" en cada instante: la secuencia óptima de voltajes para hacer el swing-up depende de la
física, del estado actual y de las consecuencias futuras (subactuación: hay que *acumular
energía* meciendo, no se puede empujar directo). No tenemos un dataset de
`(estado → voltaje correcto)`. Lo único que podemos definir es *qué resultado queremos*
(péndulo arriba y quieto) mediante una recompensa, y dejar que el agente lo descubra. Eso es
exactamente RL. (En el repo *sí* hay un intento supervisado parcial: la **destilación**
`distill.py`, que copia un controlador existente — ver Parte VI.)

## 2. Optimización: pérdida, gradiente, optimizadores

Todo el ML (incluido el RL profundo) se reduce a **minimizar una función de pérdida (loss)**
ajustando $\theta$.

### Función de pérdida (loss)
Mide "qué tan mal" lo está haciendo el modelo. Ejemplo canónico, el **error cuadrático medio**
(MSE) para regresión:

$$
\mathcal{L}(\theta) = \frac{1}{N}\sum_{i=1}^{N}\big(f_\theta(x_i) - y_i\big)^2 .
$$

El objetivo es encontrar $\theta^\star = \arg\min_\theta \mathcal{L}(\theta)$.
**Importante para RL:** en RL la "pérdida" no es un error contra etiquetas humanas, sino una
construcción interna (p. ej. el error de la ecuación de Bellman). Pero el mecanismo de
minimización es el mismo.

### Descenso de gradiente (gradient descent)
El **gradiente** $\nabla_\theta \mathcal{L}$ es el vector de derivadas parciales: apunta en la
dirección de *máximo aumento* de la pérdida. Para minimizar, damos pasos en la dirección
**opuesta**:

$$
\theta \leftarrow \theta - \eta\, \nabla_\theta \mathcal{L}(\theta),
$$

donde $\eta>0$ es la **tasa de aprendizaje (learning rate)**. Intuición: bajar una colina a
ciegas, palpando la pendiente local y dando un paso cuesta abajo.

- **Learning rate muy grande:** rebotas y diverges (la pérdida explota).
- **Learning rate muy chico:** convergencia lentísima.
- En este repo, $\eta = 3\times10^{-4}$ — un valor estándar y conservador
  (`src/qube_rl/config.py:63`).

### SGD y mini-batches
Calcular el gradiente con *todos* los datos cada paso es caro. El **descenso de gradiente
estocástico (SGD)** estima el gradiente con un **mini-batch** (un subconjunto aleatorio, aquí de
256 muestras, `config.py:64`). Es ruidoso pero mucho más rápido, y el ruido incluso ayuda a
escapar de mínimos locales malos.

### Optimizadores
Variantes que adaptan el tamaño/dirección del paso para converger mejor:

| Optimizador | Idea | Nota |
|---|---|---|
| **SGD** | Paso fijo en dirección del gradiente | Base; requiere tunear $\eta$ |
| **Momentum** | Acumula una "velocidad" para atravesar valles | Acelera y suaviza |
| **RMSProp** | Escala cada coordenada por la magnitud reciente de su gradiente | Bueno con gradientes desbalanceados |
| **Adam** | Momentum + RMSProp combinados | **El estándar de facto en deep RL**; es el que usa SAC por dentro |

Stable-Baselines3 (la librería de RL del repo) usa **Adam** por defecto para entrenar las redes
de SAC. No necesitas elegirlo: viene incorporado.

## 3. Redes neuronales

Una **red neuronal** es simplemente una función $f_\theta$ flexible, construida apilando capas
de transformaciones lineales seguidas de no linealidades. La variante que usa este repo es el
**perceptrón multicapa (MLP, multilayer perceptron)**:

$$
h_1 = \sigma(W_1 x + b_1), \quad
h_2 = \sigma(W_2 h_1 + b_2), \quad
y = W_3 h_2 + b_3 .
$$

- $x$ es la entrada (la observación), $W_k, b_k$ son los **pesos** y **sesgos** (los $\theta$),
  $h_k$ son las **capas ocultas (hidden layers)**.
- $\sigma$ es la **función de activación** no lineal. Sin ella, apilar capas colapsaría a una
  sola transformación lineal. Las comunes:
  - **ReLU** $\sigma(z)=\max(0,z)$ — barata y la más usada (la usa el firmware on-device).
  - **tanh** — acota la salida a $[-1,1]$; útil para acciones acotadas (SAC la usa en su salida).

**Capacidad y sobreajuste (overfitting).** Más neuronas = más capacidad de representar funciones
complejas, pero también más riesgo de "memorizar" ruido y más memoria/cómputo. En este proyecto
la capacidad está **limitada por el hardware**: la red debe caber en la memoria flash del ESP32.
Por eso la arquitectura es `[64, 64]` (dos capas ocultas de 64 neuronas), elegida explícitamente
porque "cabe en el presupuesto de flash/RAM del ESP32" (`config.py:74`). Una red `[64,64]` para
esta tarea ocupa ~17–26 KB; una `[128,128]` ~67 KB y **no cabe** (ver Parte VI).

**Forward / backpropagation.** *Forward pass*: metes $x$ y calculas $y$. *Backpropagation*:
aplicas la regla de la cadena para obtener $\nabla_\theta \mathcal{L}$ eficientemente, capa por
capa, de la salida hacia la entrada. Con ese gradiente, el optimizador actualiza $\theta$. PyTorch
(bajo SB3) hace esto automáticamente.

---

# Parte II — Reinforcement Learning (formal)

## 4. El MDP: el lenguaje del RL

El RL formaliza el problema como un **Proceso de Decisión de Markov (MDP, Markov Decision
Process)**, una tupla:

$$
\mathcal{M} = (\mathcal{S}, \mathcal{A}, P, R, \gamma).
$$

- $\mathcal{S}$ — **espacio de estados**. Aquí: ángulos y velocidades del péndulo.
- $\mathcal{A}$ — **espacio de acciones**. Aquí: voltaje normalizado $a\in[-1,1]$ (acción
  **continua**, no discreta).
- $P(s'\mid s,a)$ — **dinámica de transición**: probabilidad de pasar a $s'$ tras hacer $a$ en
  $s$. Aquí la da la física del péndulo (en sim, las ecuaciones de movimiento).
- $R(s,a,s')$ — **función de recompensa**: el escalar que premia/castiga.
- $\gamma \in [0,1)$ — **factor de descuento**: cuánto valen las recompensas futuras frente a
  las inmediatas. Aquí $\gamma = 0.99$ (`config.py:67`).

**Propiedad de Markov:** el futuro depende solo del estado *actual*, no de toda la historia. Esto
es una *suposición*, y aquí es delicada: con solo el ángulo y la velocidad **instantáneos**, el
estado es Markoviano para la física ideal, pero retardos, filtrado y ruido lo violan
parcialmente — de ahí el *history wrapper* que apila 4 frames (ver Parte VI).

**Retorno (return).** Lo que el agente realmente quiere maximizar no es la recompensa de un paso,
sino la suma descontada a futuro desde el instante $t$:

$$
G_t = \sum_{k=0}^{\infty} \gamma^{k}\, r_{t+k+1}.
$$

El descuento $\gamma$ hace la suma finita y prioriza lo cercano. Con $\gamma=0.99$, el "horizonte
efectivo" es del orden de $1/(1-\gamma)=100$ pasos $\approx$ 2 s a 50 Hz.

## 5. Políticas, valor y ecuaciones de Bellman

**Política (policy)** $\pi(a\mid s)$: la estrategia del agente, una distribución de probabilidad
sobre acciones dado el estado. El objetivo del RL es encontrar la política óptima $\pi^\star$ que
maximiza el retorno esperado $J(\pi)=\mathbb{E}_\pi[G_0]$.

**Funciones de valor.** Cuantifican "qué tan bueno" es un estado (o un par estado-acción) bajo una
política $\pi$:

$$
V^\pi(s) = \mathbb{E}_\pi[\,G_t \mid s_t = s\,], \qquad
Q^\pi(s,a) = \mathbb{E}_\pi[\,G_t \mid s_t = s,\, a_t = a\,].
$$

$V^\pi(s)$ es el retorno esperado empezando en $s$; $Q^\pi(s,a)$ es lo mismo pero forzando la
primera acción $a$. La **ventaja (advantage)** $A^\pi(s,a) = Q^\pi(s,a) - V^\pi(s)$ mide cuánto
mejor (o peor) que el promedio es tomar la acción $a$.

**Ecuaciones de Bellman.** Expresan el valor de forma *recursiva* (valor de hoy = recompensa
inmediata + valor descontado de mañana). Para una política dada:

$$
Q^\pi(s,a) = \mathbb{E}_{s'\sim P}\Big[\, R(s,a,s') + \gamma\, \mathbb{E}_{a'\sim\pi}\big[Q^\pi(s',a')\big] \Big].
$$

Y la **ecuación de optimalidad de Bellman**, que caracteriza a $Q^\star$ (el valor de la mejor
política posible):

$$
Q^\star(s,a) = \mathbb{E}_{s'}\Big[\, R(s,a,s') + \gamma \max_{a'} Q^\star(s',a') \Big].
$$

Casi todos los algoritmos de RL son, en el fondo, **maneras de resolver aproximadamente estas
ecuaciones** cuando $\mathcal{S}$ es enorme o continuo y no podemos tabular los valores. Ahí entran
las redes neuronales (Parte III): aproximan $Q$ y/o $\pi$.

## 6. Ejes de diseño: on/off-policy, model-free, exploración

- **On-policy vs off-policy.** *On-policy* (p. ej. PPO) aprende solo de datos generados por la
  política actual; debe tirar los datos viejos. *Off-policy* (p. ej. SAC, DQN) puede reutilizar
  datos antiguos guardados en un **replay buffer**, lo que es mucho más **eficiente en muestras
  (sample-efficient)** — crucial cuando cada muestra real cuesta (hardware). **SAC es off-policy.**
- **Model-free vs model-based.** *Model-free* aprende directo de la experiencia sin construir un
  modelo de $P$. *Model-based* aprende/usa un modelo de la dinámica para planificar. **SAC es
  model-free.** (Curiosamente, el repo *sí* tiene un modelo físico analítico — pero lo usa como
  **simulador para generar datos**, no como modelo dentro del algoritmo.)
- **Exploración vs explotación (exploration/exploitation).** El dilema central: explotar lo que
  ya sabes que da recompensa, vs explorar acciones nuevas por si son mejores. Sin exploración, el
  agente se queda atascado en óptimos locales. SAC resuelve esto de forma elegante con
  **máxima entropía** (Parte III): premia explícitamente actuar de forma variada.

## 7. Familias de algoritmos y sus pérdidas

Tres grandes familias, con la **pérdida** que minimizan:

**(a) Basados en valor (value-based)** — p. ej. **Q-learning / DQN**. Aprenden $Q_\theta(s,a)$ y
actúan tomando $\arg\max_a Q$. Minimizan el **error de Bellman** (TD error):

$$
\mathcal{L}(\theta) = \mathbb{E}\Big[\big(\underbrace{r + \gamma \max_{a'} Q_{\bar\theta}(s',a')}_{\text{objetivo (target)}} - Q_\theta(s,a)\big)^2\Big].
$$

Funcionan con acciones **discretas** (el $\max$ es sobre una lista). No sirven directo para el
voltaje continuo de aquí.

**(b) Gradiente de política (policy gradient)** — p. ej. REINFORCE, PPO. Parametrizan la política
$\pi_\theta$ directamente y suben por el gradiente del retorno. El **teorema del gradiente de
política** da:

$$
\nabla_\theta J(\pi_\theta) = \mathbb{E}_{\pi_\theta}\big[\, \nabla_\theta \log \pi_\theta(a\mid s)\; A^\pi(s,a) \big].
$$

Intuición: aumenta la probabilidad de las acciones con ventaja positiva, redúcela para las de
ventaja negativa. Manejan acciones continuas, pero suelen ser on-policy (menos eficientes en
muestras).

**(c) Actor-critic** — combinan lo mejor de ambas: un **actor** $\pi_\theta$ (la política) y un
**crítico** $Q_\phi$ o $V_\phi$ (estima el valor para guiar al actor). El crítico reduce la
varianza del gradiente del actor. **SAC pertenece a esta familia** y es la base de este repo.

---

# Parte III — Deep RL y SAC (el algoritmo de este repo)

## 8. Deep RL y por qué es inestable

**Deep RL** = RL donde $\pi$ y/o $Q$ son **redes neuronales profundas**. Esto permite tratar
estados continuos de alta dimensión (como las 8 cifras de la observación del péndulo), pero
introduce inestabilidad. La causa famosa es la **"tríada mortal" (deadly triad)** de Sutton &
Barto: cuando combinas (1) **aproximación de funciones** (redes), (2) **bootstrapping** (estimar
el target con tu propia estimación, como en Bellman) y (3) **entrenamiento off-policy**, el
aprendizaje puede divergir. Las técnicas estándar para domarlo, todas presentes en SAC:

- **Replay buffer**: guarda transiciones $(s,a,r,s')$ y entrena con mini-batches aleatorios,
  rompiendo la correlación temporal. Aquí: 1.000.000 de transiciones (`config.py:65`).
- **Redes objetivo (target networks)**: una copia "lenta" $\bar\phi$ del crítico para calcular el
  target, que se actualiza suavemente con $\bar\phi \leftarrow \tau\phi + (1-\tau)\bar\phi$,
  $\tau=0.005$ (`config.py:66`). Estabiliza el "blanco móvil".
- **Doble crítico (clipped double-Q)**: dos críticos y se usa el **mínimo** de ambos para el
  target, contrarrestando el sesgo de sobreestimación de $Q$.

## 9. SAC (Soft Actor-Critic) en detalle

**SAC** (Haarnoja et al., 2018) es un algoritmo actor-critic, off-policy, model-free, para
acciones continuas, basado en el marco de **máxima entropía (maximum entropy RL)**. Es el
algoritmo que entrena todas las políticas de este repo.

### El objetivo de máxima entropía
SAC no maximiza solo la recompensa, sino la recompensa **más** la **entropía** $\mathcal{H}$ de la
política (cuán "aleatoria"/exploratoria es):

$$
J(\pi) = \sum_{t} \mathbb{E}_{(s_t,a_t)\sim\pi}\Big[\, r(s_t,a_t) + \alpha\, \mathcal{H}\big(\pi(\cdot\mid s_t)\big) \Big],
\qquad \mathcal{H}(\pi(\cdot\mid s)) = \mathbb{E}_{a\sim\pi}[-\log \pi(a\mid s)].
$$

El **coeficiente de temperatura** $\alpha>0$ regula el balance recompensa↔exploración. Ventajas
de este término de entropía:

1. **Exploración automática y sostenida**: el agente prefiere políticas que mantengan opciones
   abiertas, evitando colapsar prematuramente a un óptimo local (importante en swing-up, donde el
   episodio arranca siempre desde el mismo equilibrio y explorar es difícil).
2. **Robustez y estabilidad** entre semillas, una propiedad por la que SAC es conocido frente a
   otros métodos off-policy.

SB3 además **ajusta $\alpha$ automáticamente** (entropy tuning) para alcanzar una entropía objetivo,
de modo que no hay que tunearlo a mano.

### Los componentes y sus pérdidas
- **Crítico (soft Q-functions)** $Q_{\phi_1}, Q_{\phi_2}$. Minimizan el error de Bellman *suave*
  (incluye el término de entropía en el target):

$$
\mathcal{L}_Q(\phi_i) = \mathbb{E}\Big[\big(Q_{\phi_i}(s,a) - y\big)^2\Big], \quad
y = r + \gamma\Big(\min_{j=1,2} Q_{\bar\phi_j}(s',a') - \alpha \log \pi_\theta(a'\mid s')\Big),\; a'\sim\pi_\theta(\cdot\mid s').
$$

- **Actor (política)** $\pi_\theta$. Es una **Gaussiana "aplastada" con tanh** (tanh-squashed
  Gaussian): la red emite media y desviación, se muestrea con el **truco de reparametrización**
  (reparameterization trick) y se pasa por $\tanh$ para acotar la acción a $[-1,1]$. Minimiza:

$$
\mathcal{L}_\pi(\theta) = \mathbb{E}_{s,\,a\sim\pi_\theta}\Big[\, \alpha \log \pi_\theta(a\mid s) - \min_{j} Q_{\phi_j}(s,a) \Big].
$$

Intuición: el actor busca acciones de alto valor $Q$ **pero** manteniéndose lo más estocástico
posible (el término $\alpha\log\pi$).

- **Temperatura** $\alpha$. Se ajusta minimizando
  $\mathcal{L}(\alpha)=\mathbb{E}[-\alpha(\log\pi_\theta(a\mid s)+\bar{\mathcal{H}})]$, con
  $\bar{\mathcal{H}}$ la entropía objetivo.

### gSDE: exploración pensada para hardware
Por defecto SAC explora inyectando ruido **independiente en cada paso**, lo que produce acciones
"temblorosas" — malo para un motor real (desgaste, vibración, dinámica no modelada). Este repo
activa **gSDE (generalized State-Dependent Exploration)** con `use_sde=True`
(`config.py:68`): el ruido es **función del estado** y se mantiene coherente durante varios pasos
(`sde_sample_freq=64`), generando trayectorias de exploración **suaves**. Es una decisión correcta
y deliberada para facilitar el sim-to-real.

### Resumen de hiperparámetros (fuente: `src/qube_rl/config.py`)
| Hiperparámetro | Valor | Significado |
|---|---|---|
| `learning_rate` | $3\times10^{-4}$ | Paso del optimizador Adam |
| `batch_size` | 256 | Muestras por actualización |
| `buffer_size` | 1.000.000 | Tamaño del replay buffer |
| `tau` ($\tau$) | 0.005 | Velocidad de actualización del target |
| `gamma` ($\gamma$) | 0.99 | Factor de descuento (~2 s de horizonte) |
| `use_sde` | True | Exploración gSDE (suave) |
| `learning_starts` | 1000 | Pasos aleatorios antes de empezar a entrenar |
| `net_arch` | 64 → `[64,64]` | Capas ocultas de actor y crítico |

## 10. Métricas y diagnóstico de entrenamiento

Cuando entrenas, mirar las curvas correctas te dice si va bien. El tracking es con **MLflow**
(`--mlflow`, UI en `mlflow ui --backend-store-uri sqlite:///mlflow.db`). Métricas clave:

| Métrica | Qué es | Qué buscar |
|---|---|---|
| **ep_rew_mean** (episode return) | Retorno medio por episodio | Que **suba** y se estabilice alto |
| **ep_len_mean** (episode length) | Duración media del episodio | Aquí, episodios más largos ⇒ no se cae/no sale de límites (señal de éxito) |
| **entropy / $\alpha$** | Aleatoriedad de la política | Baja gradualmente al converger; si se desploma muy pronto, exploración insuficiente |
| **actor_loss / critic_loss** | Pérdidas de las redes | El critic_loss debe estabilizarse; si explota, hay divergencia |
| **fps** | Velocidad de simulación | Solo rendimiento de cómputo |

`auto_train.py` usa un criterio heurístico: `ep_len_mean > 100` pasos (2 s) ⇒ "balanceando";
`> 50` ⇒ "explorando"; `< 50` ⇒ "no aprende" (`src/qube_rl/auto_train.py`). **Cuidado:** esta es
una métrica *proxy* débil; ver Parte VI sobre por qué medir el éxito así es engañoso.

**Señal de alarma — plateau / óptimo local:** si `ep_rew_mean` se estanca temprano y deja de
subir, el agente convergió a una solución subóptima (exactamente lo que reportan los handoffs de
SAC en este proyecto). Las salidas: reward shaping, currículo, más exploración, otro algoritmo.

---

# Parte IV — El problema de este repositorio

## 11. El sistema físico (péndulo de Furuta)

El **péndulo de Furuta** (o péndulo invertido rotatorio) tiene dos eslabones:

- Un **brazo rotatorio horizontal** accionado por el motor, con ángulo **$\theta$ (theta)**.
- Un **péndulo** montado en el extremo del brazo, que gira libre en un plano vertical, con ángulo
  **$\alpha$ (alpha)**. Convención del repo: $\alpha=0$ **colgando** (abajo), $\alpha=\pm\pi$
  **invertido** (arriba) — ver `src/qube_rl/rewards.py:1-7`.

**Dos equilibrios:** colgando ($\alpha=0$) es **estable** (si lo sueltas, vuelve ahí); invertido
($\alpha=\pi$) es **inestable** (cualquier perturbación lo tira). Mantenerlo invertido requiere
control activo y continuo.

**Subactuación (underactuation).** Hay **2 grados de libertad** ($\theta,\alpha$) pero **1 solo
actuador** (el motor mueve el brazo, no el péndulo directamente). No puedes "empujar" el péndulo
hacia arriba; solo puedes mover el brazo y dejar que la dinámica acoplada transfiera energía al
péndulo. Esto es lo que hace al problema un *benchmark* clásico y no trivial de control.

**El hardware** (resumen; detalles en `docs/bom.md`, `docs/pinout.md`):
ESP32-WROOM-32 (microcontrolador, 240 MHz, WiFi) + driver de motor **BTS7960** (puente H) +
sensor de corriente/voltaje **INA219** + encoders incrementales en cuadratura para medir $\theta$
y $\alpha$. Coste total ~45 USD frente a ~2.500–3.500 USD del Quanser QUBE original. El lazo de
control del firmware corre a **500 Hz**.

## 12. Las dos tareas: swing-up y balance

El problema completo se divide en dos sub-tareas que requieren estrategias opuestas:

1. **Swing-up (levantamiento).** Llevar el péndulo desde colgando ($\alpha=0$) hasta cerca de
   invertido ($\alpha\approx\pi$). Como no se puede empujar directo (subactuación), hay que
   **bombear energía**: mecer el brazo a la frecuencia adecuada para que el péndulo gane amplitud
   progresivamente, como cuando uno se columpia. Es un problema de **inyección de energía**.
2. **Balance (equilibrio).** Una vez arriba, **estabilizar** el equilibrio inestable, haciendo
   micro-correcciones para que no se caiga. Es un problema de **regulación** local.

Lo difícil para RL: una sola política $\pi$ debe aprender *ambos* comportamientos y, sobre todo,
la **transición** entre ellos (llegar arriba con poca velocidad y en una posición de brazo desde
la que se pueda atrapar). Como veremos, ahí es donde el proyecto se atasca (0 % de balance
sostenido).

## 13. Formulación como MDP (mapeo exacto al código)

Así se traduce la teoría de la Parte II al código real (`src/qube_rl/envs/qube_sim.py`):

**Espacio de observación $\mathcal{S}$ — 8 dimensiones** (`qube_sim.py:30`, `:85-92`):

$$
o = [\,\theta,\; \alpha,\; \cos\theta,\; \sin\theta,\; \cos\alpha,\; \sin\alpha,\; \dot\theta,\; \dot\alpha\,].
$$

Incluir $\cos$ y $\sin$ de los ángulos (en vez de solo el ángulo) evita la discontinuidad en
$\pm\pi$ y le da a la red una representación "suave" del ángulo — una buena práctica estándar.

**Espacio de acción $\mathcal{A}$ — 1 dimensión continua** (`qube_sim.py:93`):
$a\in[-1,1]$, que se mapea al voltaje del motor $[-12, +12]\,\mathrm{V}$.

**Dinámica $P$** (`src/qube_rl/envs/qube_dynamics.py`): ecuaciones de movimiento analíticas del
péndulo de Furuta, $M(q)\,\ddot q + C(q,\dot q) = \tau$, resueltas para $\ddot q$, con un modelo de
motor DC. Se integran por **Euler semi-implícito** a 500 Hz, mientras el control decide a 50 Hz
(`qube_sim.py:159-174`).

**Domain randomization (clave para sim-to-real).** En cada `reset()`, 8 parámetros físicos (masa,
longitud, fricción del brazo y del péndulo, resistencia y constante del motor) se **perturban con
ruido gaussiano** alrededor de su valor nominal (`qube_dynamics.py:60-100`). Así la política no se
sobreajusta a un modelo físico exacto y es más robusta al pasar al hardware real
(técnica de Tobin et al., 2017).

**Terminación** (`qube_sim.py:111-113`): el episodio termina si el estado **sale de los límites**
(`state_space`) o se vuelve no finito. Límites por defecto (`config.py:31-36`):
$\theta\in\pm90°$, $\alpha\in\pm180°$, $\dot\theta\le 50$, $\dot\alpha\le 400$ rad/s.
**No hay límite de tiempo** (`truncated` siempre `False`) — un detalle con consecuencias (Parte VI).

**Recompensa $R$.** Hay 9 variantes en `src/qube_rl/rewards.py`. Dos representativas:

- **`linear_alpha`** (`rewards.py:57-71`) — recompensa densa para swing-up:

$$
r = \underbrace{\frac{|\alpha|}{\pi}}_{\text{verticalidad (0 abajo, 1 arriba)}} \;\; \underbrace{-\,0.2\left(\frac{\theta}{\pi/2}\right)^2}_{\text{penaliza brazo descentrado}}.
$$

Usa $|\alpha|/\pi$ **lineal** en vez de $(1-\cos\alpha)/2$ porque la versión coseno tiene gradiente
casi nulo cuando el péndulo cuelga — el agente no "siente" hacia dónde ir. El gradiente lineal da
señal clara desde el principio (acelera el descubrimiento del bombeo de energía).

- **`swingup_balance`** (`rewards.py:95-122`, la recompensa por defecto) — *adaptativa por fase*:

$$
r = p - w_\theta(p)\left(\frac{\theta}{\pi/2}\right)^2 - w_v(p)\,(\dot\theta^2+\dot\alpha^2),
\quad p=\frac{1-\cos\alpha}{2},
$$

con pesos que **crecen con $p$** ($w_\theta = 0.1+0.4p$, $w_v=0.0005+0.002p$): cuando el péndulo
está abajo (fase swing-up) las penalizaciones son ligeras y el brazo puede moverse libre; cuando
está arriba (fase balance) se vuelven fuertes para exigir brazo centrado y movimientos suaves. Es
una forma ingeniosa de codificar las dos tareas en una sola recompensa.

## 14. Objetivos del proyecto y estado actual

**Objetivo general (de la tesis, `tesis_usach/`):** diseñar e implementar una plataforma de
control de péndulo invertido tipo Quanser, modernizando su hardware y software para mejorar el
desempeño, facilitar el uso experimental y hacerla compatible con Python/MATLAB.

**El sub-objetivo de RL:** entrenar (en simulación, con sim-to-real) una política que haga
swing-up y balance, y desplegarla en el ESP32, comparándola con los controladores clásicos.

**Estado actual de los resultados** (fuente: `docs/handoffs/`, `CHANGELOG.md`):

| Enfoque | Métrica reportada | Resultado |
|---|---|---|
| Swing-up clásico (PD sinusoidal / energía) | % que alcanza invertido | **~36–38 %** (mejor de todos) |
| LQR (balance) | tiempo invertido | **~55 s**, pero en **ciclo límite**, no equilibrio estático |
| SAC, `linear_alpha`, 500k pasos (sim) | $\alpha$ máximo alcanzado | **~169°** (casi invertido) |
| SAC config ESP32 (`[64,64]`, raw-8) | % "reach" (>150°) | **~8 %** |
| **Cualquier enfoque** | **% balance sostenido** | **0 %** |
| Claim previo `[128,128]` ~40 % | — | **refutado**: era *spinning* (giro), no swing-up |

**Conclusión honesta del estado:** el swing-up funciona parcialmente (mejor con control clásico
que con RL), pero **nadie ha logrado el balance sostenido** — ni RL ni clásico de forma robusta.
El problema sin resolver es la **transición swing-up → balance** y la estabilización del equilibrio
inestable con la autoridad de control disponible.

## 15. Las alternativas clásicas (energía + LQR)

Sirven de **baseline** (línea base a superar) y de posible *teacher* para el RL:

- **Control por energía (energy shaping) para swing-up.** Se define la energía mecánica del
  péndulo $E = \tfrac12 I\dot\alpha^2 + mgl(1-\cos\alpha)$ y se mece el brazo para llevar $E$ a la
  energía del equilibrio invertido. El firmware lo implementa en el "Mode 5" (energy pumping).
- **LQR (Linear Quadratic Regulator) para balance.** Se **linealiza** la dinámica alrededor del
  invertido y se calcula la ganancia óptima $K$ que minimiza un costo cuadrático
  $\int (x^\top Q x + u^\top R u)\,dt$, dando una ley lineal $u=-Kx$. Es óptimo *localmente* (cerca
  del invertido), por eso necesita que el swing-up lo "entregue" ya casi arriba y lento. El firmware
  lo implementa en "Mode 4", con un filtro de Kalman para estimar el estado.

La estrategia clásica madura es **energía (swing-up) + LQR (balance)** con conmutación. Que el RL
de extremo a extremo aún no iguale esto es esperable: es un problema genuinamente difícil, y el
control clásico aquí está bien afinado.

---

# Parte V — Cómo mejorar los resultados y trabajo futuro

Ordenado de **mayor impacto / menor esfuerzo** a **mayor alcance**.

### A. Arreglos de rigor y medición (hazlos primero — baratos y desbloquean todo)

1. **Define una métrica de éxito correcta.** Hoy el "éxito" se mide como *pico* de $\alpha>120°$
   (`distill.py`), que mide *alcanzar*, no *balancear*, y se deja engañar por el *spinning*. Define:
   > **éxito de balance** = mantener $|\alpha-\pi|<\epsilon$ (p. ej. $\epsilon=12°$) **y**
   > $|\dot\alpha|<$ umbral durante $\ge N$ segundos continuos.
   Reporta además el % de episodios que logran swing-up *y* la fracción de tiempo en equilibrio.
   Sin esta métrica, no puedes saber si una mejora es real.

2. **Múltiples semillas (seeds) con media ± desviación.** Las comparaciones actuales entre
   recompensas/arquitecturas usan **una sola corrida** cada una. SAC tiene alta varianza entre
   semillas; con $n=1$ no se puede concluir nada. Corre $\ge 5$ semillas por configuración y reporta
   media ± std. Fija `--seed` (ya soportado, `config.py:77`).

3. **Añade `TimeLimit` y maneja truncation vs termination.** El entorno nunca trunca por tiempo
   (`qube_sim.py:113`). Envuelve con `gymnasium.wrappers.TimeLimit` y asegúrate de que SB3 distinga
   *terminación* (se cayó) de *truncación* (se acabó el tiempo) en el bootstrap del target — si no,
   penalizas como "fracaso" un episodio de balance que simplemente llegó al límite de tiempo.

### B. Cambios de formulación (medio esfuerzo, alto impacto en el balance)

4. **No termines el episodio en el objetivo.** Hoy $\alpha$ está acotado a $\pm\pi$, así que en
   cuanto el péndulo pasa el invertido, el episodio **termina** (`qube_sim.py:111`). Eso es
   contraproducente: castiga llegar a la meta. Usa $\alpha$ **no acotado** (envuelto con
   $\cos/\sin$) y termina solo por velocidad excesiva o salida del brazo; así el agente puede
   *atravesar* y *quedarse* en el invertido.

5. **Revisa el límite del brazo $\theta=\pm90°$.** Los propios handoffs muestran que el swing-up
   sube de ~8–10 % (a $\pm90°$) a ~38 % permitiendo $\pm120°$. El entorno de entrenamiento prohíbe
   la maniobra que el análisis dice necesaria. Sube el límite de $\theta$ a $\pm120°$/$\pm150°$ en
   sim (y verifica que el hardware lo tolere mecánicamente).

6. **Reward shaping basado en potencial (PBRS, Ng et al. 1999).** Para que cambiar la recompensa
   **no cambie la política óptima**, usa shaping de la forma
   $F(s,s')=\gamma\,\Phi(s')-\Phi(s)$ con un potencial $\Phi$ (p. ej. basado en energía o en
   $-|\alpha-\pi|$). Es la forma teóricamente correcta de "guiar" sin distorsionar el objetivo, y
   reduce el riesgo de *reward hacking* (como el spinning) que ya apareció.

### C. Algoritmo y exploración (medio esfuerzo)

7. **Warm-start / destilación desde un *teacher fuerte*.** Hoy la destilación parte de modelos RL
   débiles. En cambio, usa el controlador **energía + LQR** (que sí hace swing-up al 36–38 %) como
   teacher: genera demostraciones, pre-llena el buffer (behavioral cloning) y luego afina con RL.
   Arrancar desde un experto evita el costoso descubrimiento desde cero.

8. **Currículo (curriculum) / reset desde estados variados.** El swing-up es difícil de explorar
   porque cada episodio arranca igual (colgando). Inicializa algunos episodios cerca del invertido
   para que el agente aprenda *primero* a balancear, y luego amplía hacia abajo. (La literatura de
   Furuta + RL — p. ej. EBERL en el Quanser QUBE2 — usa exploración basada en energía justamente
   por esto.)

9. **Compara con PPO y TD3.** SAC se atasca en óptimos locales aquí. PPO (on-policy, más estable a
   veces) y TD3 (off-policy determinista) son baselines útiles; el repo ya tiene la infraestructura
   para añadirlos.

### D. Sim-to-real (cierra la brecha sim↔hardware)

10. **Modela retardos y ruido en la sim.** El sistema real tiene latencia WiFi (10–100 ms),
    filtrado de velocidad y ruido de encoder. La sim añade cuantización y filtro (bien) pero
    conviene **randomizar también el retardo de acción** y añadir ruido de observación, para que la
    política no dependa de respuestas instantáneas que el hardware no da.

### E. Trabajo futuro (mayor alcance, para capítulos de tesis)

- **RL residual:** aprender una corrección $\pi_\theta$ *sobre* el LQR ($u = u_{LQR}+\pi_\theta$),
  combinando la garantía local del clásico con la flexibilidad del RL.
- **Control basado en modelo / MPC aprendido** aprovechando el modelo físico ya existente.
- **Arreglo de hardware del brownout:** condensador de 470–1000 µF en el riel de 5 V (los handoffs
  reportan ~20 % de caídas de swing-up por caída de tensión).
- **Evaluación en hardware reproducible:** protocolo fijo (N episodios, condiciones iniciales
  controladas, métricas A.1) para comparar RL vs clásico de forma justa y citable.

---

# Parte VI — Errores y problemas detectados (franco, por severidad)

> Cada ítem: **qué pasa**, **evidencia** (`archivo:línea`), **impacto** y **corrección**.
> El tono es directo a propósito: estos son los puntos que más debilitan las conclusiones de la
> tesis y conviene atacarlos antes de sacar más resultados.

> **Estado (v1.44.0):** ✅ **Resueltos en código:** M1, M2, M3, C1, C2, C3, D1, D2, D5.
> 🟡 **Documentados como issues conocidos (requieren prueba en hardware o reentrenamiento):**
> D3 y D4, más las fallas profundas de firmware (ver al final de la parte). Los ítems resueltos
> **cambian el planteamiento** pero para verse en *resultados* hay que **reentrenar**. Detalle de
> los cambios en `CHANGELOG.md` [1.44.0] y en la Parte V.

## 🔴 Severidad alta — metodológicos (invalidan comparaciones)

**M1. Comparaciones con una sola semilla ($n=1$).**
Las tablas de los handoffs comparan recompensas y arquitecturas con **una corrida cada una**.
SAC es notoriamente sensible a la semilla; con $n=1$ las diferencias observadas (p. ej. "raw-8
mejor que hist-4", "8 % vs 4 %") pueden ser **puro ruido**.
*Impacto:* ninguna conclusión comparativa es defendible estadísticamente.
*Corrección:* $\ge5$ semillas, reportar media ± std (ver Parte V.A.2).
✅ **Resuelto (v1.44.0):** `auto_train.py` corre cada config sobre `--seeds` y reporta media ± std
(`evaluate_over_seeds`); selecciona el mejor reward por `balance_rate`.

**M2. Métrica de éxito engañosa (conflación *reach* ↔ *balance*).**
El "éxito" se mide como pico $\alpha>120°$ (`src/qube_rl/distill.py`, función de verificación).
Eso mide *alcanzar* el invertido una vez, no *mantenerlo*. Resultado: se reportan "% reach"
relativamente altos mientras el **balance sostenido es 0 %** — la métrica esconde el fracaso real.
*Evidencia adicional:* el claim de ~40 % con `[128,128]` fue **refutado** al descubrir que era
*spinning* (giro continuo que acumula $\alpha$ sin balancear) — un caso de libro de **reward
hacking** habilitado por una métrica/recompensa mal especificadas.
*Corrección:* métrica de balance basada en tiempo + tolerancia angular + velocidad (Parte V.A.1).
✅ **Resuelto (v1.44.0):** nuevo `qube_rl/metrics.py::evaluate_balance` (reach, `balance_rate` =
mantener invertido-y-lento ≥1 s, fracción de tiempo arriba, hold máximo). Reemplaza el proxy en
`distill.py` e integrado en `auto_train.py`.

**M3. Sin `TimeLimit` ni manejo de truncación.**
`qube_sim.py:113` devuelve siempre `truncated=False`; no hay límite de tiempo de episodio.
*Impacto:* (a) un episodio de balance "perfecto" no termina nunca; (b) sin distinguir truncación
de terminación, el bootstrapping del crítico de SAC trata mal el fin de episodio, sesgando los
valores aprendidos.
*Corrección:* `TimeLimit` + propagación correcta de la bandera de truncación al algoritmo
(Parte V.A.3).
✅ **Resuelto (v1.44.0):** nueva factory `envs/factory.py` envuelve `gymnasium.wrappers.TimeLimit`
(`max_episode_steps=500`) dentro de `Monitor`, así la truncación se registra y se propaga a SAC.

## 🟠 Severidad media-alta — conceptuales/teóricos

**C1. El objetivo está en el borde de terminación.**
$\alpha$ se acota a $\pm\pi$ y el episodio termina al salir de `state_space` (`qube_sim.py:111`).
Pero $\pm\pi$ **es** el objetivo (invertido). Cualquier sobrepaso mínimo del invertido **termina el
episodio**, es decir, el entorno castiga llegar a la meta y hace el balance estructuralmente
frágil.
*Corrección:* $\alpha$ no acotado representado por $\cos/\sin$; terminar solo por velocidad/brazo
(Parte V.B.4).
✅ **Resuelto (v1.44.0):** `QubeSimEnv._is_terminal` y `QubeRealEnv.step` ya **no** terminan por
$\alpha$ (sim terminaba en `state_space.contains`, real a ~171°); solo θ/sobrevelocidad/no-finito +
`TimeLimit`. La observación sigue 8-D (raw $\alpha$ envuelto a $[-\pi,\pi]$).

**C2. Las recompensas no son potential-based; riesgo de reward hacking.**
Las 9 recompensas de `rewards.py` son funciones ad-hoc del estado; cambiar entre ellas **cambia la
política óptima**, así que no son intercambiables como "shaping" ni comparables limpiamente. Además,
recompensar $|\alpha|/\pi$ sin estructura puede premiar el *spinning* (ya ocurrió).
*Corrección:* PBRS (Ng et al. 1999), Parte V.B.6.
✅ **Resuelto (v1.44.0):** nuevo wrapper policy-invariante `wrappers/potential_shaping.py`
(`PotentialShaping`, $F=\gamma\Phi(s')-\Phi(s)$); opt-in con `--potential upright`. Las 9 recompensas
ad-hoc siguen disponibles, pero ahora existe la alternativa correcta.

**C3. El entrenamiento prohíbe la maniobra que el análisis dice necesaria.**
El límite $\theta=\pm90°$ (`config.py:32`) termina el episodio si el brazo pasa de 90°, pero los
handoffs muestran que el swing-up necesita $\pm120°$ o más.
*Impacto:* se entrena en un régimen donde la tarea es casi imposible y luego se concluye que "RL no
funciona".
*Corrección:* subir el límite de $\theta$ en sim (Parte V.B.5).
✅ **Resuelto (v1.44.0):** `EnvConfig.angle_limit_theta = 2π/3` (±120°); `qube_real` ajustado para
igualar el box de observación.

## 🟡 Severidad media — código / documentación

**D1. Docstring incorrecto en la inicialización del estado.**
`src/qube_rl/envs/qube_sim.py:135` documenta `_init_state` como
*"Initialise state near the unstable equilibrium (pendulum inverted)"*, pero el código inicializa
$\alpha\approx0$ con ruido $0.01$ — es decir, **colgando** (el equilibrio **estable**), lo opuesto a
lo que dice. Contradice además el docstring del módulo. Confunde a cualquiera que lea el código para
entender desde dónde empieza el swing-up.
*Corrección:* corregir el docstring a "near the stable (hanging) equilibrium".
✅ **Resuelto (v1.44.0):** docstring de `_init_state` corregido.

**D2. Comentario invertido en `exp_alpha_reward`.**
`src/qube_rl/rewards.py:37`: el comentario dice `# 0 at vertical, 1 at hanging`, pero
$|\alpha|/\pi$ vale **0 colgando** y **1 invertido** — está al revés. Síntoma de un problema más
amplio: el término "vertical" se usa de forma ambigua en todo el repo (a veces = invertido, a veces
= colgando).
*Corrección:* corregir el comentario y unificar terminología (usar "hanging"/"inverted",
evitar "vertical").
✅ **Resuelto (v1.44.0):** comentario en `exp_alpha_reward` corregido a "0 colgando, 1 invertido".

**D3. Desajuste entre la mejor config y la que se despliega.**
Los hallazgos dicen que la mejor config para ESP32 es **raw-8 `[64,64]`** y que el *history wrapper*
(36 entradas) **empeora**; también que `[128,128]` "no cabe" en flash y su 40 % fue refutado. Sin
embargo, el firmware on-device usa una red de **36 entradas (hist-4)** y `models/policy_weights.h`
codifica una `[128,128]` (36→128→128→1).
*Impacto:* se corre el riesgo de **flashear precisamente la variante peor/descartada**.
*Corrección:* regenerar y verificar que el header exportado corresponde al mejor modelo (raw-8,
`[64,64]`); documentar inequívocamente qué `.zip` produjo qué `.h`.
🟡 **Mitigado/documentado (v1.44.0):** `export_rltools.py` ahora **avisa** si el `INPUT_DIM` del
modelo no coincide con el dim esperado por el firmware (`FIRMWARE_INPUT_DIM=36`). El **rewire del
firmware** (pasar la inferencia on-device de 36-hist a 8-raw) sigue **pendiente** porque requiere
re-flasheo y prueba en hardware — issue conocido, no resuelto en código aún.

**D4. Posible inconsistencia en la longitud del péndulo.**
La sim usa `Lp = 0.129 m` (`qube_dynamics.py:51`), mientras el firmware usa
`PEND_LENGTH = 0.065 m` para la energía y para $\sqrt{g/l}\approx12.3$ del filtro de Kalman.
Como $0.129/2 \approx 0.065$, es **probable** que sean cantidades distintas (longitud total vs
distancia al centro de masa de una barra uniforme) y no un error — **pero hay que verificarlo
explícitamente**. Si se usaran como la misma magnitud, la política entrenada vería una dinámica
distinta a la que asumen los controladores del firmware.
*Corrección:* documentar claramente $L_p$ (longitud) vs $l$ (CoM) y confirmar la consistencia
sim↔firmware.

**D5. Destilación incompleta (parámetros muertos).**
`src/qube_rl/distill.py` define `temperature=2.0` y un factor de mezcla `alpha=0.5` para destilación
de conocimiento, pero **no están conectados** a ninguna pérdida: el pipeline real es behavioral
cloning + RL, no *knowledge distillation* con soft targets. Esto puede dar una falsa impresión de
que se aplicó KD.
*Corrección:* o implementar la pérdida de KD (con esos hiperparámetros) o eliminar los parámetros y
renombrar el módulo para reflejar que es BC+RL.
✅ **Resuelto (v1.44.0):** parámetros `temperature`/`alpha` muertos eliminados de `distill.py`;
docstring aclara que es **behavioral cloning + RL** (KD real con soft-targets queda como futuro).

## 🟡 Issues conocidos de firmware (documentados, requieren hardware para arreglar)
La auditoría del firmware (`src/firmware/esp32_qube/esp32_qube.ino`) encontró, además
del Modo 3 ya removido (solo quedaban comentarios huérfanos, ya limpiados) y de un **bug real ya
corregido** (el parser serial aceptaba solo `m<=5`, bloqueando seleccionar los modos RL 6/7 por
serial → ahora `m<=7`), varias **fallas de control profundas** que **no se tocan** sin poder probar
en el péndulo físico (modificarlas a ciegas podría empeorar el comportamiento real):

- **Ciclo límite del LQR:** el balance se sostiene oscilando alrededor de ±180° en vez de quedar
  estático; el término de amortiguamiento solo actúa con $|\alpha|<25°$, lejos de donde aparece el
  ringing. Requiere re-tuning con HW.
- **Latencia de brownout (~100 ms):** el voltaje del bus se lee al ritmo de telemetría (~100 ms)
  pero el lazo corre a 2 ms; el corte por bajo voltaje puede llegar tarde. Idealmente leer el INA219
  al ritmo del lazo o usar interrupción de brownout.
- **Discontinuidad ±180° en la derivada:** el cálculo de velocidad del péndulo mezcla ángulo
  envuelto y sin envolver al cruzar ±180°.
- **Mismatch de despliegue RL (36-hist vs 8-raw):** la inferencia on-device fija 36 entradas
  (4×9, history), pero los hallazgos indican que la mejor config ESP32 es raw-8 `[64,64]` (ver D3).
- **Arreglo de hardware del brownout:** condensador de 470–1000 µF en el riel de 5 V (los handoffs
  reportan ~20 % de caídas de swing-up por caída de tensión).

## Nota sobre lo que **sí** está bien hecho
Para equilibrio (y porque es justo): el repo hace varias cosas correctamente y por encima del nivel
típico de una tesis — domain randomization bien implementada (muestreo siempre relativo al nominal,
sin deriva, `qube_dynamics.py:60-100`); gSDE para exploración suave apta para hardware; representación
angular con $\cos/\sin$; cuantización de encoder y filtro de velocidad que **imitan el firmware** en
la sim (buen detalle de sim-to-real); configuración centralizada (`config.py`) que elimina los
"números mágicos" duplicados; y una corrección documentada del *off-by-one* en el orden
acción→observación→recompensa (`qube_sim.py:103-110`). El proyecto está bien por encima del promedio;
los puntos de arriba son los que lo separan de conclusiones sólidas.

---

# Parte VII — Glosario y referencias

## Glosario ES ↔ EN (rápido)

| Inglés | Español | |
|---|---|---|
| Reinforcement Learning (RL) | Aprendizaje por refuerzo | |
| Agent / Policy | Agente / Política $\pi$ | la regla de decisión |
| Environment | Entorno | el péndulo |
| State / Observation | Estado / Observación | lo que ve el agente |
| Action | Acción | el voltaje |
| Reward / Return | Recompensa / Retorno | escalar por paso / suma descontada |
| Episode | Episodio | un intento |
| Discount factor $\gamma$ | Factor de descuento | peso del futuro |
| Value function $V$, $Q$ | Función de valor | retorno esperado |
| Policy gradient | Gradiente de política | método de optimización del actor |
| Actor-Critic | Actor-crítico | política + estimador de valor |
| Off-policy | Fuera de política | reutiliza datos viejos |
| Replay buffer | Búfer de repetición | memoria de transiciones |
| Loss | Pérdida | función a minimizar |
| Gradient descent | Descenso de gradiente | algoritmo de minimización |
| Optimizer (Adam) | Optimizador | actualiza los pesos |
| Learning rate | Tasa de aprendizaje | tamaño del paso |
| Overfitting | Sobreajuste | memorizar ruido |
| Domain randomization | Aleatorización de dominio | robustez sim-to-real |
| Reward shaping | Modelado de recompensa | guiar el aprendizaje |
| Underactuation | Subactuación | menos actuadores que GDL |
| Swing-up / Balance | Levantamiento / Equilibrio | las dos tareas |

## Referencias (verificadas)

**Libros y RL general**
- R. S. Sutton & A. G. Barto, *Reinforcement Learning: An Introduction*, 2ª ed., MIT Press, 2018.
  Texto base; capítulos sobre MDP, Bellman, gradiente de política y la "tríada mortal".
  http://incompleteideas.net/book/the-book-2nd.html
- OpenAI, *Spinning Up in Deep RL* (referencia pedagógica, con SAC explicado).
  https://spinningup.openai.com/

**SAC (el algoritmo del repo)**
- T. Haarnoja, A. Zhou, P. Abbeel, S. Levine, *Soft Actor-Critic: Off-Policy Maximum Entropy Deep
  Reinforcement Learning with a Stochastic Actor*, ICML 2018. arXiv:1801.01290.
  https://arxiv.org/abs/1801.01290
- T. Haarnoja et al., *Soft Actor-Critic Algorithms and Applications*, 2018 (ajuste automático de
  la temperatura $\alpha$). arXiv:1812.05905. https://arxiv.org/abs/1812.05905
- Documentación de Stable-Baselines3 (implementación de SAC usada aquí):
  https://stable-baselines3.readthedocs.io/en/master/modules/sac.html

**Reward shaping**
- A. Y. Ng, D. Harada, S. Russell, *Policy Invariance Under Reward Transformations: Theory and
  Application to Reward Shaping*, ICML 1999 (potential-based reward shaping, PBRS).
  https://people.eecs.berkeley.edu/~russell/papers/icml99-shaping.pdf

**Péndulo de Furuta + RL / sim-to-real**
- *Modeling, Simulation, and Control of a Rotary Inverted Pendulum: A Reinforcement Learning-Based
  Control Approach*, MDPI Eng, 2024. https://www.mdpi.com/2673-3951/5/4/95
- *Energy-based Exploration for Reinforcement Learning* (EBERL; validado en swing-up + balance del
  Quanser QUBE2 / Furuta). Ver arXiv y referencias del área de exploración basada en energía.
- *Optimizing Reinforcement Learning Control Model in Furuta Pendulum and Transferring It to the
  Real World* (2023) — ejemplo de sim-to-real en Furuta.

**Sim-to-real / domain randomization**
- J. Tobin et al., *Domain Randomization for Transferring Deep Neural Networks from Simulation to
  the Real World*, IROS 2017. arXiv:1703.06907. https://arxiv.org/abs/1703.06907

**Documentación interna del repositorio**
- `README.md` — visión general y los 7 modos de control.
- `CHANGELOG.md` — historia iteración a iteración (v1.0 → v1.42).
- `docs/handoffs/` — bitácoras de entrenamiento con los resultados numéricos citados aquí.
- `docs/bom.md`, `docs/pinout.md`, `docs/http_api.md`, `docs/signal_conditioning.md` — hardware.
- `src/qube_rl/` — código de RL (`config.py`, `envs/qube_sim.py`, `envs/qube_dynamics.py`,
  `rewards.py`, `train.py`, `distill.py`, `finetune.py`).
- `tesis_usach/` — documento de tesis (objetivos, estado del arte, resultados).

---

*Documento de referencia generado para introducir el proyecto QUBE-RL a alguien sin base previa en
ML/RL. Las afirmaciones empíricas se anclan a `docs/handoffs/` y al código; las teóricas a las
referencias citadas. Última revisión basada en el estado del repo en la rama `DRL_IMP`.*
