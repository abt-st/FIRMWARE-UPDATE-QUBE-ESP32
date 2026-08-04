"""Análisis en vivo sobre la ventana que se está viendo.

Tres reglas que vienen de errores ya pagados en este proyecto:

1. **El sobrepaso se normaliza por el tamaño del escalón**, no por el setpoint. La cifra
   vieja se conserva junto a la nueva (``overshoot_legacy_pct``) para poder empalmar con
   las tandas anteriores; si se cambiara la definición en silencio, el cambio de métrica
   parecería una mejora que no ocurrió.
2. **α̇ se deriva de α sin envolver.** Derivar la señal envuelta mete un pico de ±360°/dt
   en cada vuelta; por eso el transporte entrega α crudo.
3. **Lo que el firmware latchea, no se reconstruye.** ``E/E*``, el ángulo y la velocidad
   del traspaso salen de ``/state`` (:func:`transition_summary`). Muestrear el modo desde
   el cliente llega tarde y da otro ángulo: ya produjo un "76–128°" que en realidad era
   125–127° consistentes.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qube_analysis.metrics import compute_overshoot, compute_overshoot_step, compute_steady_state_error

#: Bitmask de ``swing_trans_reason`` en el firmware.
TRANSITION_REASONS = {1: "near+slow", 2: "peak", 4: "forced", 8: "energy"}

#: |α| de la vertical invertida, en la convención del proyecto (colgando = 0°).
UPRIGHT_DEG = 180.0


def wrap_deg(alpha_deg: np.ndarray) -> np.ndarray:
    """Envuelve a [-180, 180). Para graficar, no para derivar."""
    return (np.asarray(alpha_deg) + 180.0) % 360.0 - 180.0


def derive_velocity(t_s: np.ndarray, x_deg: np.ndarray, smooth_n: int = 9) -> np.ndarray:
    """Deriva por diferencias centradas y suaviza con una media móvil.

    ``x_deg`` debe venir **sin envolver**. Sin filtro, a 500 Hz una sola cuenta de
    encoder son ~88 °/s de ruido y el retrato de fase se convierte en una nube.

    La media móvil es de fase cero y —a diferencia de una EMA recursiva— se calcula
    vectorizada: la ventana visible puede tener decenas de miles de puntos y esto se
    recalcula en cada cuadro.
    """
    t_s = np.asarray(t_s, dtype=np.float64)
    x_deg = np.asarray(x_deg, dtype=np.float64)
    if len(t_s) < 3:
        return np.zeros_like(x_deg)
    v = np.gradient(x_deg, t_s)
    smooth_n |= 1  # impar: así la media móvil queda centrada y no desplaza la señal
    if smooth_n <= 1 or len(v) <= smooth_n:
        return v

    smoothed = np.convolve(v, np.ones(smooth_n) / smooth_n, mode="same")
    # `same` deja los bordes con menos muestras dentro de la ventana, así que hay que
    # dividir por el peso realmente aplicado. Ese peso vale 1 en todo el centro y sólo
    # baja en los `smooth_n // 2` extremos: construirlo directamente evita una segunda
    # convolución sobre todo el array, que costaba tanto como la primera.
    half = smooth_n // 2
    weight = np.ones(len(v))
    edge = (np.arange(half) + half + 1) / smooth_n
    weight[:half] = edge
    weight[-half:] = edge[::-1]
    return smoothed / weight


# ── Escalón ───────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StepMetrics:
    """Desempeño de un escalón del servo, medido sobre la traza a 500 Hz."""

    setpoint_deg: float
    y0_deg: float
    peak_deg: float
    overshoot_pct: float
    """Normalizado por el salto pedido: (pico − sp) / (sp − y0)."""
    overshoot_legacy_pct: float
    """Normalizado por |sp|, como lo hacía ``validate.py``. Sólo para empalmar."""
    settling_s: float
    sse_deg: float
    duration_s: float
    samples: int


def step_metrics(
    t_s: np.ndarray,
    theta_deg: np.ndarray,
    setpoint_deg: float,
    *,
    tolerance: float = 0.02,
    sse_window_ratio: float = 0.1,
) -> StepMetrics | None:
    """Métricas del segmento dado, que debe empezar en el instante del escalón.

    Devuelve ``None`` si el segmento es demasiado corto para significar algo.
    """
    t_s = np.asarray(t_s, dtype=np.float64)
    theta_deg = np.asarray(theta_deg, dtype=np.float64)
    if len(theta_deg) < 10:
        return None

    y0 = float(theta_deg[0])
    amplitude = setpoint_deg - y0
    peak = float(np.max(theta_deg)) if amplitude >= 0 else float(np.min(theta_deg))
    dt = float(np.median(np.diff(t_s))) if len(t_s) > 1 else 0.002

    # Tiempo hasta la última salida de la banda. Se usa un dt uniforme (la mediana): a
    # 500 Hz lo es salvo por los huecos, que ya se reportan aparte en la salud del enlace.
    band = tolerance * abs(amplitude) if amplitude else tolerance * abs(setpoint_deg)
    outside = np.flatnonzero(np.abs(theta_deg - setpoint_deg) > band)
    settling = float(outside[-1] + 1) * dt if len(outside) else 0.0

    return StepMetrics(
        setpoint_deg=float(setpoint_deg),
        y0_deg=y0,
        peak_deg=peak,
        overshoot_pct=compute_overshoot_step(theta_deg, setpoint_deg, y0),
        overshoot_legacy_pct=compute_overshoot(theta_deg, setpoint_deg) if setpoint_deg else 0.0,
        settling_s=settling,
        sse_deg=compute_steady_state_error(theta_deg, setpoint_deg, sse_window_ratio),
        duration_s=float(t_s[-1] - t_s[0]),
        samples=len(theta_deg),
    )


class StepDetector:
    """Detecta cambios de setpoint en ``/state`` y marca dónde empieza cada escalón.

    El setpoint no viaja en la muestra binaria de 16 B, así que el disparo viene del
    sondeo de ``/state`` a 2 Hz. Eso deja una incertidumbre de hasta medio período en el
    **inicio** del segmento; el pico y el régimen, que es lo que se mide, quedan enteros
    dentro de la traza a 500 Hz.
    """

    def __init__(self, min_step_deg: float = 1.0) -> None:
        self.min_step_deg = min_step_deg
        self.setpoint_deg: float | None = None
        self.t_step_s: float | None = None
        """Marca de tiempo (reloj del DAQ) del último cambio detectado."""

    def update(self, setpoint_deg: float | None, t_now_s: float) -> bool:
        """Informa el setpoint actual. Devuelve True si acaba de cambiar."""
        if setpoint_deg is None:
            return False
        previous = self.setpoint_deg
        if previous is None:
            self.setpoint_deg = float(setpoint_deg)
            return False
        if abs(setpoint_deg - previous) < self.min_step_deg:
            return False
        self.setpoint_deg = float(setpoint_deg)
        self.t_step_s = float(t_now_s)
        return True

    def measure(self, t_s: np.ndarray, theta_deg: np.ndarray) -> StepMetrics | None:
        """Mide sobre la ventana, desde el último escalón detectado hasta el final."""
        if self.t_step_s is None or self.setpoint_deg is None or len(t_s) == 0:
            return None
        start = int(np.searchsorted(t_s, self.t_step_s))
        if start >= len(t_s) - 10:
            return None
        return step_metrics(t_s[start:], theta_deg[start:], self.setpoint_deg)


# ── Vertical invertida ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class UprightStats:
    """Cuánto tiempo se sostuvo el péndulo arriba dentro de la ventana visible."""

    fraction: float
    """Fracción de la ventana con |α| dentro de la tolerancia de la vertical."""
    hold_now_s: float
    """Racha en curso al final de la ventana. Cero si ahora mismo no está arriba."""
    hold_max_s: float
    tolerance_deg: float


def upright_stats(t_s: np.ndarray, alpha_deg: np.ndarray, tolerance_deg: float = 20.0) -> UprightStats:
    """Estadística de sostenimiento sobre α **envuelto** (la distancia a ±180°).

    Las rachas se calculan con la suma acumulada reiniciada en cada caída, sin bucle de
    Python: esto se recalcula sobre la ventana visible varias veces por segundo y a
    500 Hz la ventana son decenas de miles de muestras.
    """
    t_s = np.asarray(t_s, dtype=np.float64)
    if len(t_s) < 2:
        return UprightStats(0.0, 0.0, 0.0, tolerance_deg)
    inside = np.abs(wrap_deg(alpha_deg)) >= UPRIGHT_DEG - tolerance_deg
    dt = np.diff(t_s, prepend=t_s[0])

    # Truco del cumsum con reinicio: en cada muestra caída la racha vale cero, y
    # restar el máximo acumulado hasta la última caída deja la racha en curso.
    elapsed = np.cumsum(dt * inside)
    runs = elapsed - np.maximum.accumulate(np.where(inside, 0.0, elapsed))
    return UprightStats(
        fraction=float(np.count_nonzero(inside)) / len(inside),
        hold_now_s=float(runs[-1]),
        hold_max_s=float(runs.max()),
        tolerance_deg=tolerance_deg,
    )


# ── Retrato de fase y traspaso ────────────────────────────────────────────────


def phase_portrait(
    alpha_deg: np.ndarray,
    alpha_dot_dps: np.ndarray,
    max_points: int = 2000,
) -> tuple[np.ndarray, np.ndarray]:
    """α envuelto contra α̇, con NaN donde la señal da la vuelta.

    Sin el corte, pyqtgraph une el último punto de +180° con el primero de −180° y dibuja
    una recta horizontal que atraviesa el retrato y no corresponde a ninguna trayectoria.

    El diezmado a ``max_points`` es por costo: a 500 Hz una ventana de 20 s son 10.000
    puntos para una figura de unos 400 px de ancho. El diezmado va **antes** del corte,
    para que los saltos se detecten sobre la serie que efectivamente se dibuja. No se usa
    el diezmado automático de pyqtgraph porque éste no es una serie temporal.
    """
    step = max(1, len(alpha_deg) // max_points)
    x = wrap_deg(np.asarray(alpha_deg, dtype=np.float64)[::step])
    y = np.asarray(alpha_dot_dps, dtype=np.float64)[::step].copy()
    if len(x) > 1:
        jumps = np.flatnonzero(np.abs(np.diff(x)) > 180.0)
        x[jumps] = np.nan
        y[jumps] = np.nan
    return x, y


def transition_summary(state: dict) -> dict | None:
    """Traspaso swing-up → LQR **tal como lo latcheó el firmware**.

    Devuelve ``None`` si no hubo traspaso en el intento en curso (``setMode(5)`` limpia
    el latch). Nada de esto se recalcula desde las muestras a propósito.
    """
    reason = state.get("swing_trans_reason")
    if not reason:
        return None
    labels = [name for bit, name in TRANSITION_REASONS.items() if int(reason) & bit]
    return {
        "reason_mask": int(reason),
        "reasons": labels,
        "alpha_deg": state.get("swing_trans_alpha"),
        "vel_dps": state.get("swing_trans_vel"),
        "energy_ratio": state.get("swing_trans_energy"),
        "ms_ago": state.get("swing_trans_ms_ago"),
    }
