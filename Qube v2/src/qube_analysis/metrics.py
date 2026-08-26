"""Métricas de desempeño para sistemas de control."""

from __future__ import annotations

import numpy as np


def compute_overshoot(
    response: np.ndarray,
    setpoint: float = 1.0,
) -> float:
    """Compute the percentage overshoot of a step response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.

    Returns:
        Overshoot percentage (0 if none).
    """
    if len(response) == 0:
        return 0.0
    peak = np.max(response)
    if peak <= setpoint:
        return 0.0
    return float(((peak - setpoint) / setpoint) * 100.0)


def compute_overshoot_step(
    response: np.ndarray,
    setpoint: float,
    y0: float | None = None,
) -> float:
    """Sobrepaso porcentual normalizado por el TAMAÑO DEL ESCALÓN.

    :func:`compute_overshoot` divide por ``|setpoint|``, que sólo coincide con el
    sobrepaso real cuando el escalón parte de cero. En un escalón que cruza el cero
    (+17° -> -20°, los que se usan en este banco) esa normalización llega a **duplicar**
    la cifra: sobre las mismas trazas del 2026-07-30 daba 68-77 % contra un 39-42 % real.

    Se conserva la función vieja intacta para poder empalmar con las campañas
    anteriores; ésta es la que hay que usar de aquí en adelante.

    Args:
        response: valores de salida del segmento de escalón.
        setpoint: referencia a la que se le pidió llegar.
        y0: valor de partida. Si es ``None`` se toma la primera muestra.

    Returns:
        Sobrepaso en porcentaje del salto pedido; 0 si no lo hubo.
    """
    if len(response) == 0:
        return 0.0
    start = float(response[0]) if y0 is None else float(y0)
    amplitude = setpoint - start
    if amplitude == 0:
        return 0.0
    # El pico que importa es el que se pasa EN EL SENTIDO del escalón.
    peak = float(np.max(response)) if amplitude > 0 else float(np.min(response))
    excess = (peak - setpoint) / amplitude
    return float(max(0.0, excess) * 100.0)


def compute_settling_time(
    response: np.ndarray,
    setpoint: float = 1.0,
    tolerance: float = 0.02,
    dt: float = 0.1,
) -> float:
    """Compute the 2% settling time of a step response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.
        tolerance: Fraction of setpoint for settling band (default 0.02).
        dt: Time step between samples in seconds.

    Returns:
        Settling time in seconds. Returns len(response) * dt if never settles.
    """
    band = tolerance * abs(setpoint)
    t_settle = len(response) * dt
    for i in range(len(response) - 1, -1, -1):
        if abs(response[i] - setpoint) > band:
            t_settle = (i + 1) * dt
            break
    return float(t_settle)


def compute_steady_state_error(
    response: np.ndarray,
    setpoint: float = 1.0,
    window_ratio: float = 0.1,
) -> float:
    """Compute the steady-state error from the last portion of the response.

    Args:
        response: Array of output values.
        setpoint: Target reference value.
        window_ratio: Fraction of the response to use for steady-state (default 0.1).

    Returns:
        Steady-state error as absolute value.
    """
    if len(response) == 0:
        return 0.0
    n_samples = max(1, int(len(response) * window_ratio))
    final_segment = response[-n_samples:]
    return float(abs(np.mean(final_segment) - setpoint))
