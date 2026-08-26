"""Analisis de decaimiento libre del pendulo: separa friccion seca de viscosa.

La pregunta. Desde el 2026-08-05 hay una medicion (n=1) que dice que el pivote desarrollo
friccion seca de 1,26e-3 N.m, 18x el par viscoso, y una campana del 2026-08-12 que dijo lo
contrario sin datos que la sostuvieran. El Grupo A se vuelve a levantar entero, y para eso
hace falta primero un criterio que se pueda defender.

**Por que no sirve contar ciclos.** El script anterior (`campana_a2.py`, ahora en
`deprecated/`) contaba cruces por cero con `a[i-1]*a[i] < 0` sobre `pend_position_deg`. Ese
campo es un angulo NO acotado que acumula vueltas y cuyo cero (`zp`) es volatil y se pierde
en cada reinicio: si el pendulo oscila alrededor de un equilibrio distinto de cero -que es
el caso normal- **nunca hay cambio de signo y el conteo da 0 pase lo que pase**, con
friccion o sin ella. El veredicto no dependia de la planta. Aparte, contar ciclos tampoco
distingue Coulomb de viscoso: lo que los distingue es la FORMA de la envolvente.

    viscoso   A(t) = A0 * exp(-lambda*t)     perdida por semiciclo proporcional a A
    Coulomb   A(t) = A0 - c*t                perdida por semiciclo CONSTANTE

De ahi sale el discriminador de este modulo. Sobre la secuencia de picos A_k de |alpha| se
ajusta de una sola vez el modelo mixto

    dA_k = A_k - A_{k+1} = c_v * A_k + c_c

y el veredicto sale de cuales coeficientes son significativamente distintos de cero, no de
un umbral inventado:

    c_c ~ 0, c_v > 0   ->  VISCOSO     lambda = -(2/T)*ln(1-c_v)
    c_v ~ 0, c_c > 0   ->  SECO        tau_c  = c_c*k/2   (perdida por semiciclo = 2*tau_c/k)
    ambos > 0          ->  MIXTO       + amplitud de cruce A* = c_c/c_v

Hay un cuarto estimador que sale gratis de la misma traza y es de otra familia: el **angulo
de reposo final**, tau_c = k*sin(theta_rest). Es la medicion del 2026-08-05 (4,75 grados ->
1,26e-3 N.m) repetida en cada corrida. Que coincida con `c_c` es la comprobacion cruzada.

**Donde esta la vertical, y por que no es el reposo previo.** Todo lo anterior se mide
respecto del equilibrio, asi que ubicarlo mal invalida el resto. `spindown_now.py:111` usa
el reposo previo a la suelta y lo llama "la posicion colgando real", lo cual vale para el
protocolo excitado por el homing -donde el pendulo arranca colgando- pero **no para la
suelta manual**, donde el operador sostiene el pendulo ARRIBA durante todo el preambulo: ahi
el reposo previo es el angulo de suelta, no la vertical, y centrar con el corre toda la
oscilacion. Aca el equilibrio se estima con la **mediana de los puntos medios entre extremos
consecutivos**, que converge a la vertical tanto con amortiguamiento viscoso como con
Coulomb (en ambos los puntos medios alternan de signo y promedian a cero) y no depende de
`zp` ni del wrap. El reposo previo se usa solo como comprobacion, y si difiere se avisa.

El caso trabado es el unico donde no hay extremos suficientes para ese estimador. Por eso el
protocolo exige que **cada corrida arranque con el pendulo colgando y quieto** antes de
levantarlo: esa pre-lectura es la unica referencia de vertical que le queda a una traza en la
que el pendulo no llega a oscilar.

**Las guardas fallan cerradas.** Una corrida que no cumple no se clasifica: se descarta y se
informa por que. El script anterior confundia "no hay dato" con "0 ciclos = friccion
bloqueante", que es como un submuestreo de 9 Hz termino leyendose como un pivote trabado.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks as _sp_find_peaks

# ── Constantes fisicas ──────────────────────────────────────────────────────────
# Juego auto-consistente: reproduce a la vez la f_n adoptada por la tesis (1,70 Hz,
# Capitulo_05.tex:105-151) y el tau_seco del 2026-08-05 (k*sin(4,75 deg) = 1,258e-3 N.m).
# OJO: el firmware usa PEND_INERTIA = 7,75e-5 (esp32_qube.ino:760), un factor 1,7 mas chico,
# heredado de la f_n de 2,28 Hz que la tesis descarto. Ese es el valor incoherente; aca no
# se usa. Ver `qube_dynamics.py:49-65`.
G = 9.81
MP = 0.024  # masa del pendulo [kg]
LP = 0.129  # largo del pendulo [m], barra uniforme
JP = MP * LP**2 / 3.0  # inercia respecto del pivote = 1,331e-4 kg.m2
K_REST = MP * G * LP / 2.0  # rigidez gravitatoria = 1,519e-2 N.m/rad
OMEGA_N = math.sqrt(K_REST / JP)  # 10,68 rad/s
F_N = OMEGA_N / (2.0 * math.pi)  # 1,700 Hz
T_N = 1.0 / F_N  # 0,588 s

# Referencias contra las que se compara (banco fresco, 2026-08-04, n=2)
REF_LAMBDA = 0.0283
REF_DP = 7.52e-6
# Referencia de friccion seca (2026-08-05, n=1, el resultado a confirmar o refutar)
REF_TAU_C = 1.26e-3

# Cuantizacion del encoder del pendulo: 2048 cuentas por vuelta (esp32_qube.ino:389).
COUNT_DEG = 360.0 / 2048.0  # 0,176 deg

# ── Guardas ─────────────────────────────────────────────────────────────────────
# Las dos primeras son las que importan y estan derivadas de la fisica, no de los datos.
#
# Envolvente: para que el detector de maximos locales funcione hacen falta al menos 3
# muestras por semiciclo, o sea 6 por ciclo. A 1,70 Hz son 10,2 Hz.
MIN_SAMPLES_PER_CYCLE_ENVELOPE = 6.0
#
# Discriminador: la regresion diferencia picos consecutivos, y para el caso viscoso de
# referencia la perdida por semiciclo es dA/A = 1-exp(-lambda*T/2) = 0,83%. Un muestreo de N
# por ciclo subestima cada pico en hasta 1-cos(pi/N); para que ese error quede en torno al
# 10% de la senal buscada hace falta 1-cos(pi/N) < 0,1%, o sea N > 40. A 1,70 Hz son 68 Hz.
# Por debajo de eso se reporta lambda pero NO se corre el discriminador: dA seria ruido.
MIN_SAMPLES_PER_CYCLE_DISCRIM = 40.0

MIN_RATE_ENVELOPE_HZ = MIN_SAMPLES_PER_CYCLE_ENVELOPE * F_N  # 10,2 Hz
MIN_RATE_DISCRIM_HZ = MIN_SAMPLES_PER_CYCLE_DISCRIM * F_N  # 68,0 Hz

# El brazo tiene que estar quieto. Con dos grados de libertad acoplados la energia del
# pendulo se trasvasa al brazo y vuelve, y la envolvente deja de decaer: el 2026-08-05 el
# brazo se movio 13 grados y el ajuste dio lambda = -0,0006 con R2 = 0,02.
#
# El umbral esta graduado, y no en 4 grados a secas, por un caso concreto: la corrida 1 del
# 2026-08-12 tuvo 5,8 grados de excursion y aun asi dio 92 semiciclos limpios con R2 = 0,998.
# Descartarla fue perder dato bueno. Lo que importa no es la excursion en si sino si el
# acoplamiento arruino la envolvente, y de eso ya se encargan el R2 y `centro_estable`; el
# limite duro queda para excursiones donde el trasvase de energia es innegable.
MAX_ARM_SPAN_DEG = 4.0  # por encima: aviso
FATAL_ARM_SPAN_DEG = 10.0  # por encima: no hay envolvente que valga

# Amplitud minima util. **No es el 20 grados de `spindown_now.py:72`**: aquel umbral existia
# para proteger una medicion de `Dp` bajo modelo viscoso puro, y aca la pregunta es
# justamente si el modelo viscoso aplica, con sueltas deliberadas de 15 grados. El piso real
# es la cuantizacion del encoder (0,176 deg/cuenta) y el angulo de reposo esperado si hay
# Coulomb (~5 deg): 8 grados deja margen sobre ambos.
MIN_AMPLITUDE_DEG = 8.0

MIN_PEAKS_FOR_FIT = 6  # menos que esto y no hay regresion que valga
PEAK_FLOOR_FRAC = 0.15  # picos por debajo del 15% del maximo: ruido, no senal
PROMINENCE_DEG = 4.0 * COUNT_DEG  # 0,70 deg: por encima del ruido de cuantizacion
GAP_TOLERANCE = 3.0  # un intervalo 3x la mediana es un hueco de transporte, no una muestra
REST_STD_DEG = 0.5  # desviacion por debajo de la cual se considera que algo esta quieto
PREROLL_S = 2.0  # ventana inicial que el protocolo exige con el pendulo colgando
EQ_MISMATCH_DEG = 2.0  # desacuerdo tolerable entre las dos estimaciones de la vertical

# Los "picos" tienen que estar al periodo del pendulo. Sin esta guarda, una senal de ruido
# produce cientos de maximos locales, el ajuste exponencial devuelve lambda ~ 0 con R2 ~ 0 y
# el veredicto sale VISCOSO: un pivete inexistente clasificado como sano. La f_n de 1,70 Hz
# esta establecida por cinco determinaciones (Capitulo_05.tex:105-151) y la banda de +-40%
# cubre incluso la estimacion de 2,28 Hz que la tesis descarto, asi que no impone el valor:
# solo exige que lo detectado oscile como este pendulo y no como otra cosa.
PERIOD_TOLERANCE = 0.40

# R2 minimo del ajuste de envolvente para admitir un veredicto viscoso. Es el mismo criterio
# de `spindown_now.py:73`, que nacio de dos capturas malas que daban 0,12 y 0,40 y aun asi
# imprimian un Dp.
MIN_R2_ENVELOPE = 0.85

# Desplazamiento tolerable del centro de oscilacion a lo largo de una corrida. Un pendulo
# libre decae alrededor de una vertical FIJA; si el centro se corre, lo que hay es otra cosa
# (encoder perdiendo cuentas, mecanismo moviendose, mano en el banco) y ningun lambda medido
# sobre esa traza significa lo que dice.
MAX_CENTER_DRIFT_DEG = 3.0

# ── Veredictos ──────────────────────────────────────────────────────────────────
DESCARTADA = "DESCARTADA"  # las guardas no dejan concluir. NO es un resultado sobre el pivote.
TRABADO = "TRABADO"  # se solto con amplitud suficiente y no completo un ciclo
SECO = "SECO"
VISCOSO = "VISCOSO"
MIXTO = "MIXTO"
INDETERMINADO = "INDETERMINADO"  # el ajuste corrio pero ningun coeficiente es significativo


@dataclass
class Guard:
    """Una condicion que la captura debe cumplir para que el analisis signifique algo."""

    name: str
    ok: bool
    detail: str
    #: Si es fatal y no se cumple, la corrida se descarta. Si no, solo limita el analisis
    #: (tipicamente: alcanza para lambda pero no para el discriminador).
    fatal: bool = True


@dataclass
class DecayResult:
    verdict: str
    guards: list[Guard] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    # captura
    n: int = 0
    duration_s: float = 0.0
    rate_hz: float = 0.0
    samples_per_cycle: float = 0.0
    arm_span_deg: float = float("nan")

    # referencia y suelta
    equilibrium_deg: float = float("nan")
    equilibrium_method: str = ""
    release_idx: int = 0
    release_t_s: float = float("nan")
    amp0_deg: float = float("nan")
    rest_after_deg: float = float("nan")
    n_releases: int = 1
    center_drift_deg: float = float("nan")
    n_valores_alpha: int = 0

    # picos
    n_peaks: int = 0
    n_peaks_expected_viscous: int = 0
    peaks_t: np.ndarray = field(default_factory=lambda: np.zeros(0))
    peaks_a: np.ndarray = field(default_factory=lambda: np.zeros(0))
    half_period_s: float = float("nan")

    # estimador 1: envolvente exponencial (modelo viscoso)
    lam_exp: float = float("nan")
    r2_exp: float = float("nan")

    # estimador 2: envolvente lineal (modelo Coulomb)
    slope_lin: float = float("nan")
    r2_lin: float = float("nan")

    # estimador 3: balance de energia por semiciclo -> tau_c y Dp en unidades fisicas
    tau_c_fit: float = float("nan")
    dp_fit: float = float("nan")
    se_tau_c: float = float("nan")
    se_dp: float = float("nan")
    t_tau_c: float = float("nan")
    t_dp: float = float("nan")
    lam_from_dp: float = float("nan")
    cross_amp_deg: float = float("nan")  # amplitud donde ambas perdidas se igualan

    # estimador 4: angulo de reposo final (familia independiente). COTA INFERIOR de tau_c.
    tau_c_from_rest: float = float("nan")

    # derivados
    dp: float = float("nan")

    @property
    def discarded(self) -> bool:
        return self.verdict == DESCARTADA

    @property
    def failed_guards(self) -> list[Guard]:
        return [g for g in self.guards if not g.ok]

    def summary(self) -> str:
        parts = [f"{self.verdict:<14}"]
        if not self.discarded:
            parts.append(f"amp0={self.amp0_deg:6.1f} deg  picos={self.n_peaks:3d}")
            if math.isfinite(self.lam_exp):
                parts.append(f"lambda={self.lam_exp:.4f} 1/s (R2={self.r2_exp:.3f})")
            if math.isfinite(self.tau_c_fit):
                parts.append(f"tau_c={self.tau_c_fit:.2e} (t={self.t_tau_c:.1f})")
            if math.isfinite(self.dp_fit):
                parts.append(f"Dp={self.dp_fit:.2e} (t={self.t_dp:.1f})")
            if math.isfinite(self.tau_c_from_rest):
                parts.append(f"tau_c>={self.tau_c_from_rest:.2e}")
        bad = self.failed_guards
        if bad:
            parts.append("| falla: " + ", ".join(g.name for g in bad))
        return "  ".join(parts)


# ── Carga de trazas ─────────────────────────────────────────────────────────────
@dataclass
class Trace:
    """Una captura cruda, ya normalizada a segundos y grados."""

    t: np.ndarray
    alpha_deg: np.ndarray
    theta_deg: np.ndarray | None = None
    source: str = ""
    dropped: int = 0

    def __len__(self) -> int:
        return len(self.t)


def load_trace(path: str | Path) -> Trace:
    """Lee un CSV de decaimiento. Reconoce los tres esquemas que existen en el proyecto.

    Se identifica por el conjunto exacto de columnas y no por heuristicas sobre los valores,
    porque el esquema del 2026-08-04 esta en RADIANES y el resto en grados: adivinar la
    unidad mirando el rango es justo el tipo de atajo que produce un factor 57 silencioso.
    """
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{path.name}: archivo vacio")
    cols = set(rows[0])

    def col(name: str) -> np.ndarray:
        return np.array([float(r[name]) for r in rows], dtype=float)

    if {"t_s", "alpha_deg"} <= cols:
        # Esquema canonico del DAQ (qube_daq/__main__.py, qube_app/recorder.py).
        # `alpha_raw_deg` es el angulo SIN envolver, que es el que queremos: envolver
        # introduce saltos de 360 que el detector de picos leeria como picos.
        alpha = col("alpha_raw_deg") if "alpha_raw_deg" in cols else col("alpha_deg")
        theta = col("theta_deg") if "theta_deg" in cols else None
        return Trace(col("t_s"), alpha, theta, path.name)

    if {"t", "alpha", "theta"} <= cols:
        # 2026-08-04: capturado por polling de /rl_state, en RADIANES.
        return Trace(col("t"), np.degrees(col("alpha")), np.degrees(col("theta")), path.name)

    if {"t", "angulo"} <= cols:
        # 2026-08-12: la campana rota. Polling de /state, grados.
        theta = col("theta") if "theta" in cols else None
        return Trace(col("t"), col("angulo"), theta, path.name)

    raise ValueError(f"{path.name}: esquema no reconocido, columnas = {sorted(cols)}")


# ── Extremos, equilibrio y suelta ───────────────────────────────────────────────
def find_extrema(a: np.ndarray, prominence: float = PROMINENCE_DEG) -> np.ndarray:
    """Indices de los puntos de retorno, alternando maximo y minimo.

    La prominencia descarta los extremos espurios que la cuantizacion del encoder produce a
    montones en las mesetas: a 250 Hz una meseta plana tiene cientos de maximos locales de
    una cuenta de altura, y sin este filtro serian "semiciclos".
    """
    hi, _ = _sp_find_peaks(a, prominence=prominence)
    lo, _ = _sp_find_peaks(-a, prominence=prominence)
    if hi.size == 0 and lo.size == 0:
        return np.zeros(0, dtype=int)
    idx = np.concatenate([hi, lo])
    kind = np.concatenate([np.ones(hi.size, dtype=int), -np.ones(lo.size, dtype=int)])
    order = np.argsort(idx)
    idx, kind = idx[order], kind[order]

    # Forzar la alternancia: de cada racha del mismo tipo se conserva el mas extremo. Sin
    # esto, dos maximos seguidos (que la asimetria de Coulomb produce cerca del final) darian
    # un punto medio sin sentido.
    keep: list[int] = []
    run_start = 0
    for i in range(1, len(idx) + 1):
        if i == len(idx) or kind[i] != kind[run_start]:
            run = idx[run_start:i]
            vals = a[run] if kind[run_start] > 0 else -a[run]
            keep.append(int(run[int(np.argmax(vals))]))
            run_start = i
    return np.array(keep, dtype=int)


def refine_extremum(t: np.ndarray, a: np.ndarray, i: int) -> tuple[float, float]:
    """Vertice de la parabola por los tres puntos alrededor de `i`. Devuelve (t, valor).

    No es cosmetico: con N muestras por ciclo el extremo muestreado subestima al verdadero en
    hasta 1-cos(pi/N), que a 13 Hz -los datos del 2026-08-04- es un 8%. La correccion baja
    ese sesgo un orden de magnitud y es lo que permite comparar capturas tomadas a tasas
    distintas sin que la tasa se cuele como si fuera friccion.
    """
    if i <= 0 or i >= len(a) - 1:
        return float(t[i]), float(a[i])
    y0, y1, y2 = float(a[i - 1]), float(a[i]), float(a[i + 1])
    denom = y0 - 2.0 * y1 + y2
    if denom == 0.0:
        return float(t[i]), float(a[i])
    shift = float(np.clip(0.5 * (y0 - y2) / denom, -0.5, 0.5))
    value = y1 - 0.25 * (y0 - y2) * shift
    time = float(t[i]) + shift * (float(t[i + 1]) - float(t[i - 1])) * 0.5
    return time, value


def estimate_equilibrium(t: np.ndarray, a: np.ndarray) -> tuple[float, str, list[str]]:
    """Ubica la vertical. Devuelve (equilibrio_deg, metodo, avisos).

    Metodo principal: mediana de los puntos medios entre extremos consecutivos. Con
    amortiguamiento viscoso los puntos medios alternan +-A*r^k*(1-r)/2 y con Coulomb
    alternan +-dA/2; en los dos casos promedian a cero alrededor del equilibrio, asi que la
    mediana converge a la vertical sin suponer cual de los dos modelos rige.

    Respaldo: la pre-lectura del protocolo (los primeros `PREROLL_S` segundos con el pendulo
    colgando y quieto). Es la unica referencia disponible cuando el pendulo no llega a
    oscilar, que es justo el caso trabado.
    """
    notes: list[str] = []
    eq_pre = float("nan")
    if len(t) > 10:
        dt = float(np.median(np.diff(t)))
        if dt > 0:
            n0 = max(10, min(int(PREROLL_S / dt), len(a) // 4))
            if float(np.std(a[:n0])) < REST_STD_DEG:
                eq_pre = float(np.median(a[:n0]))

    ext = find_extrema(a)
    eq_mid = float("nan")
    if ext.size >= 3:
        vals = np.array([refine_extremum(t, a, i)[1] for i in ext])
        eq_mid = float(np.median(0.5 * (vals[:-1] + vals[1:])))

    if math.isfinite(eq_mid):
        if math.isfinite(eq_pre) and abs(eq_pre - eq_mid) > EQ_MISMATCH_DEG:
            notes.append(
                f"el reposo previo ({eq_pre:.1f} deg) no coincide con la vertical estimada por "
                f"los extremos ({eq_mid:.1f} deg): la grabacion arranco con el pendulo "
                f"sostenido, no colgando. Se usa la estimacion por extremos."
            )
        return eq_mid, "puntos_medios", notes
    if math.isfinite(eq_pre):
        notes.append(
            "no hay extremos suficientes para ubicar la vertical por puntos medios; se usa la "
            "pre-lectura con el pendulo colgando. El resultado depende de que esa pre-lectura "
            "se haya hecho de verdad."
        )
        return eq_pre, "pre_lectura", notes
    notes.append(
        "no se pudo ubicar la vertical: ni hay oscilacion ni hay pre-lectura en reposo."
    )
    return float("nan"), "ninguno", notes


def peaks_of(t: np.ndarray, c: np.ndarray, floor_frac: float = PEAK_FLOOR_FRAC) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Amplitud de cada semiciclo sobre una senal ya centrada. Devuelve (indices, t, |valor|)."""
    ext = find_extrema(c)
    if ext.size == 0:
        return np.zeros(0, dtype=int), np.zeros(0), np.zeros(0)
    refined = np.array([refine_extremum(t, c, i) for i in ext])
    tp, ap = refined[:, 0], np.abs(refined[:, 1])
    keep = ap > floor_frac * float(np.abs(c).max())
    return ext[keep], tp[keep], ap[keep]


def best_decay_segment(
    idx: np.ndarray, tp: np.ndarray, ap: np.ndarray, growth_tol: float = 0.20
) -> tuple[int, int, int]:
    """Ubica el tramo de decaimiento libre mas largo. Devuelve (indice, fin, n_tramos).

    Una caida libre no puede ganar energia: si un pico supera al minimo de los anteriores por
    mas de `growth_tol`, algo le devolvio energia al pendulo -otra suelta, un golpe, una mano-
    y la grabacion contiene mas de un tramo. Ajustar una sola envolvente sobre eso no mide
    ninguno de los dos.

    **Se elige el tramo mas largo, no el ultimo.** Es la diferencia entre leer bien y leer mal
    `spindown_man_1.csv` del 2026-08-05: esa grabacion trae 10 s de decaimiento limpio y
    despues se vuelve erratica, y quedarse con el ultimo tramo hace pasar el desorden final
    por el resultado del ensayo. El tramo mas largo es el que trae mas informacion.
    """
    if ap.size < 3:
        return 0, len(ap), 1
    run_min = np.minimum.accumulate(ap)
    grow = np.flatnonzero(ap[1:] > (1.0 + growth_tol) * run_min[:-1]) + 1
    if grow.size == 0:
        return 0, ap.size, 1
    # Indices consecutivos son una misma maniobra, no varias.
    starts = [0] + [int(g) for g in grow[np.concatenate([[True], np.diff(grow) > 1])]]
    bounds = starts + [ap.size]
    spans = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)]
    lo, hi = max(spans, key=lambda s: tp[s[1] - 1] - tp[s[0]] if s[1] > s[0] else -1.0)
    return int(idx[lo]), int(hi), len(spans)


def find_release(
    t: np.ndarray, c: np.ndarray, speed_thr_deg_s: float = 5.0, window_s: float = 0.05
) -> int:
    """Indice de la suelta sobre la senal YA centrada en el equilibrio.

    Arranca en la excursion maxima -que es el angulo al que se sostuvo el pendulo, o el
    primer pico si la grabacion empezo con el ya oscilando- y avanza mientras la velocidad
    siga por debajo del umbral. En una suelta manual eso recorre toda la meseta de sujecion;
    en una traza que ya venia oscilando avanza una muestra, porque en un punto de retorno la
    velocidad tambien es nula. Los dos casos quedan bien sin ramas distintas.

    La velocidad se mide sobre una ventana de `window_s`, no entre muestras consecutivas: a
    250 Hz un solo salto de cuantizacion del encoder (0,176 deg) equivale a 44 deg/s, muy por
    encima del umbral, y la meseta de sujecion se leeria como movimiento desde la primera
    muestra.
    """
    if len(t) < 5:
        return 0
    i_hold = int(np.argmax(np.abs(c)))
    dt = float(np.median(np.diff(t)))
    if dt <= 0:
        return i_hold
    w = max(1, int(round(window_s / dt)))
    if len(c) <= w:
        return i_hold
    speed = np.abs(c[w:] - c[:-w]) / (w * dt)
    i = i_hold
    while i < len(speed) and speed[i] < speed_thr_deg_s:
        i += 1
    return int(min(i, len(t) - 1))


# ── Ajustes ─────────────────────────────────────────────────────────────────────
def _r2(y: np.ndarray, pred: np.ndarray) -> float:
    ss_tot = float(((y - y.mean()) ** 2).sum())
    if ss_tot <= 0:
        return float("nan")
    return 1.0 - float(((y - pred) ** 2).sum()) / ss_tot


def fit_exponential_envelope(tp: np.ndarray, ap: np.ndarray) -> tuple[float, float]:
    """log(A) vs t. Devuelve (lambda, R2). Modelo viscoso."""
    if tp.size < 3 or np.any(ap <= 0):
        return float("nan"), float("nan")
    y = np.log(ap)
    m, b = np.polyfit(tp, y, 1)
    return -float(m), _r2(y, m * tp + b)


def fit_linear_envelope(tp: np.ndarray, ap: np.ndarray) -> tuple[float, float]:
    """A vs t. Devuelve (pendiente [deg/s], R2). Modelo Coulomb."""
    if tp.size < 3:
        return float("nan"), float("nan")
    m, b = np.polyfit(tp, ap, 1)
    return -float(m), _r2(ap, m * tp + b)


def consecutive_pairs(tp: np.ndarray, half_period_s: float, tol: float = 0.35) -> np.ndarray:
    """Mascara de los pares (k, k+1) que de verdad son semiciclos consecutivos.

    Un hueco de transporte puede tragarse un punto de retorno entero, y entonces dos picos
    "consecutivos" estan separados por dos semiciclos: la perdida de energia de ese par es el
    doble y contamina la regresion. En vez de descartar la corrida se descarta el par. El
    ajuste de envolvente no necesita esto -una regresion de log(A) contra t no se entera de
    un pico faltante- pero el discriminador si, porque su unidad es el semiciclo.
    """
    if tp.size < 2 or not math.isfinite(half_period_s) or half_period_s <= 0:
        return np.zeros(max(tp.size - 1, 0), dtype=bool)
    dt = np.diff(tp)
    return np.abs(dt - half_period_s) <= tol * half_period_s


def fit_discriminator(peaks_deg: np.ndarray, omega_d: float, mask: np.ndarray | None = None) -> dict:
    """Balance de energia por semiciclo. Devuelve tau_c y Dp en unidades fisicas.

    Este es el estimador que decide. Se plantea sobre la energia y no sobre la amplitud por
    dos razones concretas, las dos descubiertas probando el criterio contra casos sinteticos:

    1. **La version en amplitud tiene un sesgo estadistico.** Regresar dA_k = A_k - A_{k+1}
       contra A_k pone el ruido de A_k en los dos lados de la ecuacion, y esa correlacion
       espuria fabrica una pendiente viscosa donde no la hay: una traza de Coulomb puro salia
       MIXTA. Aca los regresores son SIMETRICOS en el par (A_k, A_{k+1}), y el ruido de una
       diferencia es ortogonal al de una suma, asi que el sesgo desaparece.
    2. **La version en amplitud supone pequenas oscilaciones.** A 45 o 60 grados el periodo
       se alarga y la rigidez efectiva cae, asi que la perdida de Coulomb por semiciclo
       -constante en energia- deja de ser constante en amplitud. Con E = k*(1-cos A) la
       nolinealidad entra exacta y no hay que acotar el rango de amplitudes.

    El modelo, por semiciclo, con las amplitudes en radianes:

        dE_k = tau_c * (A_k + A_{k+1})  +  Dp * (pi/2) * omega_d * ((A_k+A_{k+1})/2)^2

    El primer termino es el trabajo del par seco a lo largo del recorrido; el segundo es
    ``Dp*integral(omega^2 dt)`` evaluada sobre medio ciclo casi sinusoidal. Se ajusta por
    minimos cuadrados SIN termino independiente: la fisica dice que a amplitud nula no se
    disipa nada, y esa restriccion es informacion real, no una comodidad.
    """
    out = {"tau_c": float("nan"), "dp": float("nan"), "se_tau_c": float("nan"),
           "se_dp": float("nan"), "t_tau_c": float("nan"), "t_dp": float("nan"), "n": 0}
    if peaks_deg.size < 4 or omega_d <= 0:
        return out
    a = np.radians(peaks_deg)
    energy = K_REST * (1.0 - np.cos(a))
    d_e = energy[:-1] - energy[1:]
    path = a[:-1] + a[1:]  # recorrido angular del semiciclo
    if mask is not None:
        keep = np.asarray(mask, bool)
        d_e, path = d_e[keep], path[keep]
    mean_a = 0.5 * path
    x = np.column_stack([path, (math.pi / 2.0) * omega_d * mean_a**2])
    n, p = x.shape
    if n <= p:
        return out
    if n <= p:
        return out
    try:
        beta, *_ = np.linalg.lstsq(x, d_e, rcond=None)
        xtx_inv = np.linalg.inv(x.T @ x)
    except np.linalg.LinAlgError:
        return out
    resid = d_e - x @ beta
    s2 = float((resid**2).sum()) / (n - p)
    se = np.sqrt(np.maximum(s2 * np.diag(xtx_inv), 0.0))
    out.update(
        tau_c=float(beta[0]), dp=float(beta[1]),
        se_tau_c=float(se[0]), se_dp=float(se[1]),
        t_tau_c=float(beta[0] / se[0]) if se[0] > 0 else float("nan"),
        t_dp=float(beta[1] / se[1]) if se[1] > 0 else float("nan"),
        n=n,
    )
    return out


def crossover_amplitude_deg(tau_c: float, dp: float, omega_d: float) -> float:
    """Amplitud a la que las dos perdidas por semiciclo se igualan.

    tau_c*2A = Dp*(pi/2)*omega_d*A^2  ->  A* = 4*tau_c/(pi*Dp*omega_d).
    Por debajo manda el seco, por encima el viscoso. Es el numero que dice si la friccion
    seca importa en el regimen en que el LQR trabaja (pocos grados) aunque no se note en una
    suelta grande.
    """
    if not (math.isfinite(tau_c) and math.isfinite(dp)) or tau_c <= 0 or dp <= 0 or omega_d <= 0:
        return float("nan")
    return math.degrees(4.0 * tau_c / (math.pi * dp * omega_d))


def tau_c_from_rest_angle(theta_rest_deg: float) -> float:
    """El pendulo se queda donde el par gravitatorio ya no vence al seco: tau_c = k*sin(theta).

    **Es una cota inferior, no siempre una estimacion.** El pendulo se detiene en el primer
    punto de retorno que cae dentro de la banda de adherencia |k*sin(theta)| <= tau_c, y ese
    punto puede quedar bien adentro de la banda si la parada fue violenta. Cuando la traza
    trae muchos semiciclos antes de parar, el ultimo punto de retorno cae pegado al borde de
    la banda y entonces si es una buena estimacion. Con pocos semiciclos, subestima.
    """
    if not math.isfinite(theta_rest_deg):
        return float("nan")
    return K_REST * abs(math.sin(math.radians(theta_rest_deg)))


# ── Analisis completo de una corrida ────────────────────────────────────────────
def analyze(
    trace: Trace,
    *,
    target_amp_deg: float | None = None,
    amp_tolerance: float = 0.25,
    nominal_rate_hz: float | None = None,
    significance_t: float = 2.0,
) -> DecayResult:
    """Analiza una corrida y devuelve un veredicto, o la descarta explicando por que.

    `target_amp_deg` es la amplitud que la campana pidio: si la suelta real se aparta mas de
    `amp_tolerance`, la corrida no mide lo que decia medir y se descarta. Es la guarda que
    habria atrapado la corrida "de 15 grados" del 2026-08-12, que en realidad partio de 65.
    """
    res = DecayResult(verdict=DESCARTADA)
    t = np.asarray(trace.t, float)
    a = np.asarray(trace.alpha_deg, float)
    res.n = len(t)
    if res.n < 20:
        res.guards.append(Guard("muestras", False, f"solo {res.n} muestras"))
        return res

    t = t - t[0]
    res.duration_s = float(t[-1])
    res.rate_hz = (res.n - 1) / res.duration_s if res.duration_s > 0 else 0.0
    res.samples_per_cycle = res.rate_hz / F_N

    # ── guardas de captura ──────────────────────────────────────────────────────
    res.guards.append(
        Guard(
            "tasa_envolvente",
            res.rate_hz >= MIN_RATE_ENVELOPE_HZ,
            f"{res.rate_hz:.1f} Hz = {res.samples_per_cycle:.1f} muestras/ciclo (minimo "
            f"{MIN_RATE_ENVELOPE_HZ:.1f} Hz). Por debajo, los picos no se pueden ubicar.",
        )
    )
    res.guards.append(
        Guard(
            "tasa_discriminador",
            res.rate_hz >= MIN_RATE_DISCRIM_HZ,
            f"{res.rate_hz:.1f} Hz (minimo {MIN_RATE_DISCRIM_HZ:.1f} Hz). Por debajo, la "
            f"perdida por semiciclo queda enterrada en el error de muestreo de cada pico.",
            fatal=False,
        )
    )

    dt = np.diff(t)
    med_dt = float(np.median(dt)) if dt.size else 0.0
    n_gaps = int(np.count_nonzero(dt > GAP_TOLERANCE * med_dt)) if med_dt > 0 else 0
    max_gap = float(dt.max()) if dt.size else 0.0
    # Un hueco no descarta la corrida: descarta los pares de picos que lo cruzan (ver
    # `consecutive_pairs`). Lo que si es fatal es que el hueco se trague tantos puntos de
    # retorno que no quede envolvente, y eso se detecta despues por el numero de picos. El
    # umbral de aviso es el semiperiodo: un hueco mas largo puede esconder un pico entero.
    res.guards.append(
        Guard(
            "huecos",
            n_gaps == 0,
            f"{n_gaps} intervalos > {GAP_TOLERANCE:.0f}x la mediana (mayor = "
            f"{max_gap * 1000:.0f} ms, semiperiodo = {T_N / 2 * 1000:.0f} ms)"
            if dt.size else "sin datos",
            fatal=False,
        )
    )
    if trace.dropped:
        # Esto si es fatal: que el firmware descarte muestras significa que el PC no dreno el
        # buffer a tiempo, o sea un fallo de protocolo, no una propiedad del dato.
        res.guards.append(Guard("dropped", False, f"el firmware descarto {trace.dropped} muestras"))
    if nominal_rate_hz:
        ok = abs(res.rate_hz - nominal_rate_hz) <= 0.10 * nominal_rate_hz
        res.guards.append(
            Guard("tasa_nominal", ok, f"{res.rate_hz:.1f} Hz vs {nominal_rate_hz:.1f} Hz nominales")
        )

    if trace.theta_deg is not None and len(trace.theta_deg) == res.n:
        th = np.asarray(trace.theta_deg, float)
        res.arm_span_deg = float(th.max() - th.min())
        res.guards.append(
            Guard(
                "brazo_quieto",
                res.arm_span_deg <= MAX_ARM_SPAN_DEG,
                f"excursion {res.arm_span_deg:.1f} deg (aviso sobre {MAX_ARM_SPAN_DEG:.0f}, "
                f"fatal sobre {FATAL_ARM_SPAN_DEG:.0f}). Con el brazo suelto el acoplamiento de "
                f"2 GDL arruina la envolvente; comprobar el R2 y `centro_estable`.",
                fatal=res.arm_span_deg > FATAL_ARM_SPAN_DEG,
            )
        )

    # El angulo del pendulo tiene que cambiar. Un encoder incremental en reposo da un valor
    # exactamente constante -es un contador, no tiene temblor-, asi que una traza plana no
    # distingue "no se solto el pendulo" de "el canal dejo de leer". Las dos cosas invalidan la
    # corrida, pero conviene nombrarlo: el 2026-08-12 cinco corridas seguidas salieron planas y
    # el motivo que se imprimia era `amplitud_minima`, que no sugiere ir a mirar el banco.
    n_valores = int(np.unique(a).size)
    res.n_valores_alpha = n_valores
    if n_valores <= 2:
        res.guards.append(
            Guard(
                "angulo_cambia",
                False,
                f"el angulo del pendulo tomo {n_valores} valor(es) distinto(s) en toda la "
                f"captura ({res.n} muestras). O el pendulo no se movio, o el canal del encoder "
                f"no esta leyendo. Comprobar moviendo el pendulo a mano y mirando /state.",
            )
        )

    # ── vertical y suelta ───────────────────────────────────────────────────────
    eq, method, eq_notes = estimate_equilibrium(t, a)
    res.equilibrium_deg, res.equilibrium_method = eq, method
    res.notes.extend(eq_notes)
    res.guards.append(
        Guard("vertical", math.isfinite(eq), f"metodo = {method}, equilibrio = {eq:.2f} deg")
    )
    if not math.isfinite(eq):
        return res

    c = a - eq

    # Si la grabacion contiene mas de un tramo de caida libre, se analiza el mas largo.
    idx_all, tp_all, ap_all = peaks_of(t, c)
    i0, hi, n_releases = best_decay_segment(idx_all, tp_all, ap_all)
    i1 = int(idx_all[hi]) if hi < idx_all.size else len(t)
    res.n_releases = n_releases
    if n_releases > 1:
        res.notes.append(
            f"la grabacion contiene {n_releases} tramos de caida libre separados por aportes "
            f"de energia (otra suelta, un golpe, una mano). Se analiza el mas largo, "
            f"t = {float(t[i0]):.1f} a {float(t[min(i1, len(t) - 1)]):.1f} s."
        )
    t_seg, c_seg = t[i0:i1], c[i0:i1]
    if len(t_seg) < 20:
        res.guards.append(Guard("tramo_util", False, f"el tramo mas largo tiene {len(t_seg)} muestras"))
        return res

    k = i0 + find_release(t_seg, c_seg)
    res.release_idx = k
    res.release_t_s = float(t[k])

    t_r = t[k:i1] - t[k]
    c_r = c[k:i1]

    # El centro de oscilacion tiene que quedarse quieto. Si se desplaza, lo que hay no es un
    # pendulo decayendo alrededor de una vertical fija -puede ser el encoder perdiendo cuentas,
    # o el mecanismo corriendose- y ningun lambda medido sobre eso significa lo que dice.
    if idx_all.size >= 6:
        vals = np.array([refine_extremum(t, c, i) for i in idx_all])[:, 1]
        mids = 0.5 * (vals[:-1] + vals[1:])
        third = max(len(mids) // 3, 2)
        drift = abs(float(np.median(mids[:third])) - float(np.median(mids[-third:])))
        res.center_drift_deg = drift
        res.guards.append(
            Guard(
                "centro_estable",
                drift <= MAX_CENTER_DRIFT_DEG,
                f"el centro de oscilacion se desplaza {drift:.1f} deg entre el principio y el "
                f"final (maximo {MAX_CENTER_DRIFT_DEG:.0f}).",
            )
        )
    res.amp0_deg = float(np.abs(c_r).max()) if c_r.size else float("nan")

    res.guards.append(
        Guard(
            "amplitud_minima",
            res.amp0_deg >= MIN_AMPLITUDE_DEG,
            f"{res.amp0_deg:.1f} deg (minimo {MIN_AMPLITUDE_DEG:.0f})",
        )
    )
    if target_amp_deg:
        # Aviso, no descarte. Que la suelta se fuera de lo pedido cambia la ETIQUETA de la
        # corrida, no su validez: la fisica no depende de a cuanto se apuntaba. Se agrupa por
        # la amplitud MEDIDA (ver `compare_across_amplitudes`) y listo. Descartarla, como se
        # hacia antes, tiraba dato bueno: la corrida 2 del 2026-08-12 pedia 15 grados, solto
        # desde 23,3 y dio 81 semiciclos con R2 = 0,995.
        ok = abs(res.amp0_deg - target_amp_deg) <= amp_tolerance * target_amp_deg
        res.guards.append(
            Guard(
                "amplitud_objetivo",
                ok,
                f"partio de {res.amp0_deg:.1f} deg y se pidio {target_amp_deg:.0f} "
                f"(+-{amp_tolerance * 100:.0f}%). Se agrupa por la amplitud medida.",
                fatal=False,
            )
        )

    # Reposo final: ultimo 10% de la traza, si el pendulo llego a quedarse quieto.
    tail = c_r[int(0.9 * c_r.size) :] if c_r.size >= 10 else np.zeros(0)
    if tail.size >= 5 and float(tail.std()) < REST_STD_DEG:
        res.rest_after_deg = float(np.median(tail))
        res.tau_c_from_rest = tau_c_from_rest_angle(res.rest_after_deg)
    else:
        res.notes.append("el pendulo todavia se movia al final: no hay angulo de reposo que medir")

    if any(not g.ok and g.fatal for g in res.guards):
        return res  # DESCARTADA. No se emite ningun veredicto sobre el pivote.

    # ── picos ───────────────────────────────────────────────────────────────────
    _, tp, ap = peaks_of(t_r, c_r)
    res.peaks_t, res.peaks_a = tp, ap
    res.n_peaks = int(ap.size)
    res.half_period_s = float(np.median(np.diff(tp))) if tp.size >= 2 else float("nan")

    # Cuantos semiciclos deberia haber si el pivote estuviera como el 2026-08-04. Es la
    # escala contra la cual "3 picos" significa algo.
    res.n_peaks_expected_viscous = int(res.duration_s / (T_N / 2.0)) if res.duration_s > 0 else 0

    if res.n_peaks < 2:
        res.verdict = TRABADO
        res.notes.append(
            f"se solto desde {res.amp0_deg:.1f} deg y no completo un ciclo. Bajo el modelo "
            f"viscoso de referencia (lambda={REF_LAMBDA}) se esperaban ~"
            f"{res.n_peaks_expected_viscous} semiciclos en esta ventana."
        )
        return res
    # Lo detectado tiene que oscilar como este pendulo. Sin esta comprobacion, una senal de
    # ruido produce cientos de "semiciclos", el ajuste devuelve lambda ~ 0 con R2 ~ 0 y el
    # veredicto sale VISCOSO: nada clasificado como pivote sano.
    if math.isfinite(res.half_period_s):
        expected = T_N / 2.0
        ok = abs(res.half_period_s - expected) <= PERIOD_TOLERANCE * expected
        res.guards.append(
            Guard(
                "periodo_plausible",
                ok,
                f"semiperiodo observado {res.half_period_s * 1000:.0f} ms vs "
                f"{expected * 1000:.0f} ms esperados (+-{PERIOD_TOLERANCE * 100:.0f}%). "
                f"Lo que oscila a esa frecuencia no es este pendulo.",
            )
        )
        if not ok:
            res.verdict = DESCARTADA
            return res

    if res.n_peaks < MIN_PEAKS_FOR_FIT:
        res.verdict = SECO
        res.lam_exp, res.r2_exp = fit_exponential_envelope(tp, ap)
        res.notes.append(
            f"solo {res.n_peaks} semiciclos contra ~{res.n_peaks_expected_viscous} esperados "
            f"bajo el modelo viscoso. Son muy pocos para la regresion, pero el conteo ya es "
            f"concluyente: ningun amortiguamiento viscoso con lambda del orden de "
            f"{REF_LAMBDA} detiene el pendulo tan rapido."
        )
        return res

    # ── estimadores ─────────────────────────────────────────────────────────────
    res.lam_exp, res.r2_exp = fit_exponential_envelope(tp, ap)
    res.slope_lin, res.r2_lin = fit_linear_envelope(tp, ap)
    res.dp = 2.0 * JP * res.lam_exp if math.isfinite(res.lam_exp) else float("nan")

    # Una ventana mas corta que la vida media mide la parte de arriba de la envolvente, donde
    # el modelo exponencial y el lineal casi no se distinguen. No invalida la corrida, pero
    # tiene que quedar dicho: es el defecto de los 15 s de la campana del 2026-08-12.
    if math.isfinite(res.lam_exp) and res.lam_exp > 0:
        half_life = math.log(2.0) / res.lam_exp
        if res.duration_s < half_life:
            res.notes.append(
                f"la ventana observada ({res.duration_s:.0f} s) no llega a la vida media "
                f"({half_life:.0f} s): la envolvente apenas cae y los dos modelos son casi "
                f"indistinguibles en ese tramo."
            )

    if res.rate_hz < MIN_RATE_DISCRIM_HZ:
        res.verdict = INDETERMINADO
        res.notes.append(
            f"a {res.rate_hz:.1f} Hz se puede reportar lambda pero no correr el discriminador. "
            f"El veredicto Coulomb/viscoso tiene que salir de comparar lambda entre amplitudes "
            f"distintas (ver `compare_across_amplitudes`)."
        )
        return res

    omega_d = math.pi / res.half_period_s if math.isfinite(res.half_period_s) else OMEGA_N
    pairs = consecutive_pairs(tp, res.half_period_s)
    n_dropped_pairs = int(np.count_nonzero(~pairs))
    if n_dropped_pairs:
        res.notes.append(
            f"{n_dropped_pairs} de {pairs.size} pares de picos no estan separados por un "
            f"semiciclo (huecos de transporte o picos perdidos): se excluyen del discriminador."
        )
    d = fit_discriminator(ap, omega_d, mask=pairs)
    res.tau_c_fit, res.dp_fit = d["tau_c"], d["dp"]
    res.se_tau_c, res.se_dp = d["se_tau_c"], d["se_dp"]
    res.t_tau_c, res.t_dp = d["t_tau_c"], d["t_dp"]
    res.lam_from_dp = res.dp_fit / (2.0 * JP) if math.isfinite(res.dp_fit) else float("nan")
    res.cross_amp_deg = crossover_amplitude_deg(res.tau_c_fit, res.dp_fit, omega_d)

    # Un coeficiente cuenta solo si es positivo Y significativo. Un Dp negativo significativo
    # no es "viscosidad negativa": es senal de que el modelo no describe la traza.
    coulomb = math.isfinite(res.t_tau_c) and res.t_tau_c > significance_t
    viscous = math.isfinite(res.t_dp) and res.t_dp > significance_t

    # Y ademas la envolvente tiene que parecerse a una exponencial antes de llamarla viscosa.
    envelope_ok = (
        math.isfinite(res.lam_exp)
        and res.lam_exp > 0
        and math.isfinite(res.r2_exp)
        and res.r2_exp >= MIN_R2_ENVELOPE
    )
    if viscous and not envelope_ok:
        res.notes.append(
            f"el termino viscoso sale significativo pero la envolvente no es exponencial "
            f"(lambda = {res.lam_exp:.4f}, R2 = {res.r2_exp:.2f}): no se declara VISCOSO."
        )
        viscous = False

    if viscous and coulomb:
        res.verdict = MIXTO
        res.notes.append(
            f"las dos perdidas se igualan en A* = {res.cross_amp_deg:.1f} deg: por debajo manda "
            f"el seco, por encima el viscoso."
        )
    elif coulomb:
        res.verdict = SECO
    elif viscous:
        res.verdict = VISCOSO
    else:
        res.verdict = INDETERMINADO
        res.notes.append(
            "ningun termino resulta significativo: la corrida no distingue entre los dos "
            "modelos. No es evidencia de pivote sano."
        )
    return res


# ── Analisis entre corridas ─────────────────────────────────────────────────────
def compare_across_amplitudes(runs: list[tuple[float, DecayResult]], bin_deg: float = 10.0) -> dict:
    """La prueba del 2026-08-04, ahora con mas de dos amplitudes.

    Si el amortiguamiento es viscoso, lambda NO depende de la amplitud de la suelta. Si hay
    Coulomb, la lambda aparente CRECE al bajar la amplitud, porque una perdida constante por
    ciclo pesa relativamente mas cuando la amplitud es chica.

    `runs` es [(amplitud_objetivo, resultado)]. Las descartadas se ignoran y se cuentan.

    **Se agrupa por la amplitud MEDIDA, no por la pedida**, redondeada a `bin_deg`. Soltar a
    mano no da en el blanco: el 2026-08-12 las sueltas pedidas de 15 y 35 grados salieron de
    23,3 y 43,2. Agrupar por la etiqueta meteria en la misma casilla corridas que no comparten
    amplitud, que es justo la variable del experimento.
    """
    usable = [
        (round(r.amp0_deg / bin_deg) * bin_deg, r)
        for _, r in runs
        if not r.discarded and math.isfinite(r.lam_exp) and math.isfinite(r.amp0_deg)
    ]
    out: dict = {
        "n_total": len(runs),
        "n_descartadas": sum(1 for _, r in runs if r.discarded),
        "n_trabadas": sum(1 for _, r in runs if r.verdict == TRABADO),
        "n_usables": len(usable),
        "por_amplitud": {},
        "veredicto": INDETERMINADO,
        "notas": [],
    }
    # Cada angulo de reposo acota tau_c por abajo, y la cota mas alta de la tanda es la mejor:
    # el pendulo se detiene en un punto cualquiera de la banda de adherencia, asi que con
    # varias repeticiones el maximo converge al borde de la banda desde abajo. Es el uso que
    # justifica repetir, y lo que le faltaba al n=1 del 2026-08-05.
    rests = [r.tau_c_from_rest for _, r in runs if not r.discarded and math.isfinite(r.tau_c_from_rest)]
    out["tau_c_cota_inferior"] = max(rests) if rests else float("nan")
    out["n_reposos"] = len(rests)

    if not usable:
        out["notas"].append("ninguna corrida usable: no hay veredicto de campana.")
        return out

    by_amp: dict[float, list[float]] = {}
    for amp, r in usable:
        by_amp.setdefault(amp, []).append(r.lam_exp)
    for amp, lams in sorted(by_amp.items()):
        arr = np.array(lams)
        out["por_amplitud"][amp] = {
            "n": len(lams),
            "lambda_mediana": float(np.median(arr)),
            "lambda_std": float(arr.std(ddof=1)) if len(lams) > 1 else float("nan"),
            "dp": float(2.0 * JP * np.median(arr)),
        }

    amps = sorted(by_amp)
    if len(amps) < 2:
        out["notas"].append("una sola amplitud: la prueba de independencia no se puede correr.")
        return out

    lam_lo = float(np.median(by_amp[amps[0]]))
    lam_hi = float(np.median(by_amp[amps[-1]]))
    ratio = lam_lo / lam_hi if lam_hi > 0 else float("nan")
    out["lambda_baja"] = lam_lo
    out["lambda_alta"] = lam_hi
    out["razon"] = ratio

    # Dispersion intra-amplitud como escala de lo que es "igual". Sin esto el umbral seria
    # inventado, que es exactamente el error que se busca no repetir.
    spreads = [
        v["lambda_std"] / v["lambda_mediana"]
        for v in out["por_amplitud"].values()
        if math.isfinite(v["lambda_std"]) and v["lambda_mediana"] > 0
    ]
    rel_spread = float(np.median(spreads)) if spreads else float("nan")
    out["dispersion_relativa"] = rel_spread

    if not (math.isfinite(rel_spread) and rel_spread > 0):
        out["notas"].append(
            f"sin replicas por amplitud no hay dispersion contra la cual comparar; la razon "
            f"{ratio:.2f} no se puede juzgar."
        )
    elif ratio > 1.0 + 3.0 * rel_spread:
        out["veredicto"] = SECO
        out["notas"].append(
            f"lambda a {amps[0]:.0f} deg es {ratio:.2f}x la de {amps[-1]:.0f} deg, muy por "
            f"encima de la dispersion intra-amplitud ({rel_spread * 100:.1f}%). Perdida "
            f"constante por ciclo = Coulomb."
        )
    elif abs(ratio - 1.0) <= 3.0 * rel_spread:
        out["veredicto"] = VISCOSO
        out["notas"].append(
            f"lambda no depende de la amplitud dentro de la dispersion medida "
            f"({rel_spread * 100:.1f}%): razon {ratio:.2f}. Es el criterio del 2026-08-04."
        )
    else:
        out["notas"].append(f"razon {ratio:.2f}: no concluye en ninguna direccion.")
    return out
