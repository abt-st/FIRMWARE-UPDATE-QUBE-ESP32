"""Criterios de aceptación por modo, como código versionado.

Hasta ahora los criterios vivían en prosa (`docs/PLAN_MODOS_FUNCIONALES.md`) y en scripts
sueltos de `experiments/`, que `ruff` excluye y CI no toca. Eso tuvo un costo medible:
**tres veredictos falsos en dos días** —un `c1 >= 4` que no escalaba con `n`, una
comparación de medianas que omitía descontar la covariable que el propio protocolo
mandaba descontar, y una comprobación de tendencia que toleraba un aumento de 5 puntos—
más el sobrepaso "68-77 %" que era 39 % mal normalizado, más los "9,9-10,0 s" del modo 7
que eran la duración de la ventana de grabación.

Un criterio que vive en un script de campaña se reescribe en cada campaña. Uno que vive
acá se ejercita en CI **contra un caso construido para fallar** (`tests/test_criteria.py`),
que es la contramedida que el propio registro propone.

Todas las funciones devuelven un :class:`Verdict`: el veredicto **y los números que lo
sostienen**, para que un PASS se pueda auditar sin volver a la traza.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import pairwise

import numpy as np

# Vertical invertida, en la convención de alpha del DAQ (crudo, sin envolver).
UPRIGHT_DEG = 180.0
# Atenuación por posición de `setMotor()` en el firmware: el techo real del PWM baja con
# |theta|. Medir saturación contra la constante da 0,0 % en cualquier corrida, porque el DAQ
# registra `lastPwmCmd`, o sea el valor POSTERIOR a la atenuación. Este sesgo apareció dos
# veces (bombeo y LQR) antes de quedar entendido — ver `soft_sat_cap`.
SOFT_SAT_K_DEG = 200.0


@dataclass
class Verdict:
    """Un veredicto y su evidencia.

    ``passed`` nunca se reporta solo: ``metrics`` lleva los números con los que se decidió
    y ``detail`` la frase que explica por qué.
    """

    name: str
    passed: bool
    detail: str
    metrics: dict[str, float] = field(default_factory=dict)

    def __str__(self) -> str:  # pragma: no cover - formato
        return f"[{'PASS' if self.passed else 'FAIL'}] {self.name}: {self.detail}"


def wrap_deg(a: np.ndarray | float) -> np.ndarray:
    """Envuelve a (-180, 180]."""
    return (np.asarray(a, dtype=np.float64) + 180.0) % 360.0 - 180.0


def soft_sat_cap(pwm_ceiling: float, theta_deg: np.ndarray) -> np.ndarray:
    """Techo EFECTIVO del PWM, muestra a muestra.

    ``factor = 1 / (1 + (|theta| / SOFT_SAT_K_DEG)²)``, igual que `setMotor()`. Comparar el
    PWM registrado contra la constante en vez de contra esto es el sesgo que hizo creer
    que el bombeo saturaba el 0,0 % del tiempo cuando satura el 92,5 %.
    """
    k = np.abs(np.asarray(theta_deg, dtype=np.float64)) / SOFT_SAT_K_DEG
    return np.floor(pwm_ceiling / (1.0 + k * k))


# ── m2 — PID de posición del servo ──────────────────────────────────────────────


def overshoot_pct(theta_deg: np.ndarray, setpoint_deg: float, start_deg: float) -> float:
    """Sobrepaso normalizado por el TAMAÑO DEL ESCALÓN, no por el setpoint.

    Normalizar por el setpoint dio "68-77 %" sobre trazas cuyo sobrepaso real era 39-42 %
    (P6). Con un escalón de +20 → -20 el setpoint es -20 pero el escalón mide 40.
    """
    step = setpoint_deg - start_deg
    if abs(step) < 1e-9:
        return 0.0
    theta = np.asarray(theta_deg, dtype=np.float64)
    peak = np.max(theta) if step > 0 else np.min(theta)
    return float(max(0.0, (peak - setpoint_deg) / step) * 100.0)


def check_m2_step(
    theta_deg: np.ndarray,
    setpoint_deg: float,
    start_deg: float,
    max_overshoot_pct: float = 20.0,
) -> Verdict:
    """m2 es funcional si el escalón no sobrepasa más de ``max_overshoot_pct``."""
    ov = overshoot_pct(theta_deg, setpoint_deg, start_deg)
    return Verdict(
        name="m2 sobrepaso",
        passed=ov <= max_overshoot_pct,
        detail=f"sobrepaso {ov:.1f} % contra un máximo de {max_overshoot_pct:.0f} %",
        metrics={"overshoot_pct": ov, "step_deg": abs(setpoint_deg - start_deg)},
    )


# ── m3 — Homing ─────────────────────────────────────────────────────────────────


def check_m3_repeatability(
    ranges_deg: list[float],
    expected_deg: float = 269.65,
    tol_deg: float = 3.0,
    max_spread_deg: float = 1.0,
) -> Verdict:
    """El homing es funcional si el recorrido medido es el esperado **y repetible**.

    Se piden las dos cosas: un recorrido correcto en promedio con dispersión grande no es
    una calibración, es suerte. La dispersión del 2026-08-04 fue de 0,35° sobre 8 corridas.
    """
    if len(ranges_deg) < 2:
        return Verdict("m3 repetibilidad", False, f"hacen falta ≥2 corridas, hay {len(ranges_deg)}", {})
    arr = np.asarray(ranges_deg, dtype=np.float64)
    spread = float(arr.max() - arr.min())
    mean = float(arr.mean())
    dentro = abs(mean - expected_deg) <= tol_deg
    repetible = spread <= max_spread_deg
    return Verdict(
        name="m3 repetibilidad",
        passed=bool(dentro and repetible),
        detail=(
            f"recorrido medio {mean:.2f}° (esperado {expected_deg}±{tol_deg}), "
            f"dispersión {spread:.2f}° (máx {max_spread_deg})"
        ),
        metrics={"mean_deg": mean, "spread_deg": spread, "n": float(len(arr))},
    )


# ── m4 / m7 — sostenimiento invertido ───────────────────────────────────────────


def hold_time_s(t_s: np.ndarray, alpha_deg: np.ndarray, tolerance_deg: float = 15.0) -> float:
    """Racha continua más larga con |alpha| dentro de ``tolerance_deg`` de la vertical.

    Vectorizado con el truco del cumsum reiniciado (mismo que ``qube_app.analysis``): a
    500 Hz una corrida son decenas de miles de muestras.
    """
    t = np.asarray(t_s, dtype=np.float64)
    if t.size < 2:
        return 0.0
    inside = np.abs(wrap_deg(alpha_deg)) >= UPRIGHT_DEG - tolerance_deg
    dt = np.diff(t, prepend=t[0])
    elapsed = np.cumsum(dt * inside)
    runs = elapsed - np.maximum.accumulate(np.where(inside, 0.0, elapsed))
    return float(runs.max())


def check_balance_hold(
    holds_s: list[float],
    min_hold_s: float = 3.0,
    min_runs: int = 3,
    n_runs: int = 5,
) -> Verdict:
    """m4/m7 balancean si sostienen ``min_hold_s`` en ``min_runs`` de ``n_runs``.

    ⚠ El umbral se compara contra el número de corridas REALIZADAS, no contra una
    constante: un ``exitos >= 4`` escrito para n=5 sigue aprobando con n=20 y ya imprimió
    un veredicto falso en este proyecto.
    """
    if len(holds_s) != n_runs:
        return Verdict(
            "balanceo sostenido",
            False,
            f"se esperaban {n_runs} corridas y hay {len(holds_s)}: el criterio no aplica",
            {"n": float(len(holds_s))},
        )
    exitos = int(sum(1 for h in holds_s if h >= min_hold_s))
    return Verdict(
        name="balanceo sostenido",
        passed=exitos >= min_runs,
        detail=(
            f"{exitos}/{n_runs} corridas sostienen ≥{min_hold_s} s (hace falta {min_runs}); mejor {max(holds_s):.3f} s"
        ),
        metrics={"exitos": float(exitos), "n": float(n_runs), "best_s": float(max(holds_s))},
    )


# ── m5 — Swing-up ───────────────────────────────────────────────────────────────


def saturated_fraction(pwm: np.ndarray, theta_deg: np.ndarray, pwm_ceiling: float) -> float:
    """Fracción de muestras contra el techo EFECTIVO (no contra la constante)."""
    p = np.abs(np.asarray(pwm, dtype=np.float64))
    cap = soft_sat_cap(pwm_ceiling, theta_deg)
    usable = cap > 0
    if not np.any(usable):
        return 0.0
    return float(np.count_nonzero(p[usable] >= cap[usable]) / np.count_nonzero(usable))


def check_m5_delivery(
    handoff_alpha_deg: list[float],
    min_alpha_deg: float = 165.0,
    min_fraction: float = 0.8,
) -> Verdict:
    """m5 entrega bien si ``min_fraction`` de los traspasos llegan sobre ``min_alpha_deg``.

    Se usa una FRACCIÓN, no un conteo: el criterio original (`c1 >= 4`) estaba escrito
    para n=5 y habría aprobado 4 de 20.
    """
    if not handoff_alpha_deg:
        return Verdict("m5 entrega", False, "sin traspasos que evaluar", {})
    arr = np.abs(np.asarray(handoff_alpha_deg, dtype=np.float64))
    ok = int(np.count_nonzero(arr >= min_alpha_deg))
    frac = ok / len(arr)
    return Verdict(
        name="m5 entrega",
        passed=frac >= min_fraction,
        detail=(
            f"{ok}/{len(arr)} entregas con |alpha| ≥ {min_alpha_deg}° = {frac:.0%} "
            f"(hace falta {min_fraction:.0%}); mediana {np.median(arr):.1f}°"
        ),
        metrics={"ok": float(ok), "n": float(len(arr)), "fraction": frac},
    )


def check_energy_ratio(ratios: list[float], lo: float = 0.95, hi: float = 1.05) -> Verdict:
    """``E/E*`` de cada traspaso dentro de la banda."""
    if not ratios:
        return Verdict("m5 E/E*", False, "sin traspasos que evaluar", {})
    arr = np.asarray(ratios, dtype=np.float64)
    dentro = int(np.count_nonzero((arr >= lo) & (arr <= hi)))
    return Verdict(
        name="m5 E/E*",
        passed=dentro == len(arr),
        detail=f"{dentro}/{len(arr)} en [{lo}, {hi}]; rango medido {arr.min():.3f}-{arr.max():.3f}",
        metrics={"dentro": float(dentro), "n": float(len(arr))},
    )


# ── m6 — Deep RL por HTTP ───────────────────────────────────────────────────────


def check_m6_link(measured_hz: float, requested_hz: float = 50.0, min_ratio: float = 0.8) -> Verdict:
    """m6 sólo puede evaluar una política si el enlace entrega la frecuencia pedida.

    Es el criterio que m6 **no tenía**: el vigente era ``pwm_std > 5``, que el propio plan
    califica de *señal de vida, no funcionalidad*. Un motor que se mueve no dice nada
    sobre si la política se está evaluando.
    """
    ratio = measured_hz / requested_hz if requested_hz > 0 else 0.0
    return Verdict(
        name="m6 frecuencia del enlace",
        passed=ratio >= min_ratio,
        detail=(
            f"{measured_hz:.1f} Hz alcanzados sobre {requested_hz:.0f} pedidos = {ratio:.0%} "
            f"(hace falta {min_ratio:.0%})"
        ),
        metrics={"measured_hz": measured_hz, "ratio": ratio},
    )


def check_observations_live(seqs: list[int], max_repeats: int = 3) -> Verdict:
    """Ninguna observación se repitió más de ``max_repeats`` veces seguidas (P19).

    Sin esto, una campaña de m6 puede ser un episodio muerto de punta a punta.
    """
    if len(seqs) < 2:
        return Verdict("m6 observaciones vivas", False, f"hacen falta ≥2 muestras, hay {len(seqs)}", {})
    peor, actual = 1, 1
    # pairwise: pares consecutivos, sin construir la lista desplazada.
    for prev, cur in pairwise(seqs):
        actual = actual + 1 if cur == prev else 1
        peor = max(peor, actual)
    return Verdict(
        name="m6 observaciones vivas",
        passed=peor < max_repeats,
        detail=f"la racha más larga de observaciones idénticas fue {peor} (límite {max_repeats})",
        metrics={"max_repeat_run": float(peor), "n": float(len(seqs))},
    )


# ── Salud del lazo, transversal ─────────────────────────────────────────────────


def check_loop_health(overruns: int, rate_hz: float, nominal_hz: float = 500.0, max_overruns: int = 5) -> Verdict:
    """El lazo corrió a su tasa nominal y sin atrasos.

    ⚠ ``loop_dt_max_us`` **no alcanza**: en la corrida original de P15 marcó 17,3 ms
    mientras las marcas de tiempo mostraban un hueco de 488 ms. La métrica de salud del
    firmware no ve esas paradas; ``loop_overruns`` sí.
    """
    tasa_ok = rate_hz >= 0.97 * nominal_hz
    overruns_ok = overruns <= max_overruns
    return Verdict(
        name="salud del lazo",
        passed=bool(tasa_ok and overruns_ok),
        detail=f"{rate_hz:.1f} Hz sobre {nominal_hz:.0f} nominales, {overruns} overruns (máx {max_overruns})",
        metrics={"rate_hz": rate_hz, "overruns": float(overruns)},
    )


def summarize(verdicts: list[Verdict]) -> tuple[bool, str]:
    """Veredicto de conjunto. Una sola en rojo lo tiñe todo."""
    todos = all(v.passed for v in verdicts)
    lineas = [str(v) for v in verdicts]
    n_ok = sum(1 for v in verdicts if v.passed)
    lineas.append(f"{n_ok}/{len(verdicts)} criterios en verde")
    return todos, "\n".join(lineas)
