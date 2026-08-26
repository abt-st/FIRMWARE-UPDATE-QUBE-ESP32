"""Cada criterio, ejercitado contra un caso construido para FALLAR.

Este proyecto lleva **tres veredictos falsos en dos días** y todos se detectaron leyendo
la salida cruda, no la marca PASS/FAIL. La contramedida que el propio registro propone es
exactamente esto: *ejercitar el bloque de veredicto con un caso sintético construido para
que falle, no sólo con uno de efecto nulo*.

Por eso cada criterio tiene sus dos mitades. Un criterio que sólo se prueba contra datos
buenos no está probado: está confirmado.
"""

from __future__ import annotations

import numpy as np
import pytest

from qube_analysis.criteria import (
    check_balance_hold,
    check_energy_ratio,
    check_loop_health,
    check_m2_step,
    check_m3_repeatability,
    check_m5_delivery,
    check_m6_link,
    check_observations_live,
    hold_time_s,
    overshoot_pct,
    saturated_fraction,
    soft_sat_cap,
    summarize,
)

# ── m2 ──────────────────────────────────────────────────────────────────────────


def test_overshoot_normalises_by_the_step_not_the_setpoint():
    """El caso exacto de P6: normalizar por el setpoint infló 39 % a 68-77 %."""
    # Escalón +20 → -20 (tamaño 40) con un pico de -28: sobrepaso real = 8/40 = 20 %.
    theta = np.array([20.0, 0.0, -28.0, -20.0])
    assert overshoot_pct(theta, setpoint_deg=-20.0, start_deg=20.0) == pytest.approx(20.0)
    # Normalizando por |setpoint| = 20 habría dado 40 %: el doble.


def test_m2_rejects_an_overshooting_step():
    theta = np.array([20.0, 0.0, -40.0, -20.0])  # 50 % de sobrepaso
    assert not check_m2_step(theta, -20.0, 20.0).passed


def test_m2_accepts_a_clean_step():
    theta = np.array([20.0, 0.0, -20.5, -20.0])  # 1,25 %
    assert check_m2_step(theta, -20.0, 20.0).passed


# ── m3 ──────────────────────────────────────────────────────────────────────────


def test_m3_rejects_a_correct_mean_with_bad_spread():
    """Recorrido correcto en promedio y disperso no es calibración, es suerte."""
    v = check_m3_repeatability([265.0, 274.3, 269.6])  # media ~269,6 pero rango 9,3°
    assert not v.passed
    assert v.metrics["spread_deg"] > 1.0


def test_m3_rejects_a_repeatable_but_wrong_range():
    assert not check_m3_repeatability([250.0, 250.2, 250.1]).passed


def test_m3_accepts_the_measured_campaign():
    assert check_m3_repeatability([269.5, 269.7, 269.85, 269.6]).passed


def test_m3_refuses_to_judge_a_single_run():
    assert not check_m3_repeatability([269.65]).passed


# ── m4 / m7 ─────────────────────────────────────────────────────────────────────


def test_hold_time_measures_the_longest_run_not_the_total():
    t = np.arange(0, 1.0, 0.1)
    # dentro, fuera, dentro más largo
    alpha = np.array([180, 180, 90, 180, 180, 180, 90, 90, 90, 90], dtype=float)
    assert hold_time_s(t, alpha, tolerance_deg=15.0) == pytest.approx(0.3, abs=0.05)


def test_balance_hold_rejects_the_measured_p4_campaign():
    """~90 corridas, mejor absoluto 114 ms: no llega a 3 s ni de lejos."""
    assert not check_balance_hold([0.114, 0.058, 0.0, 0.096, 0.0]).passed


def test_balance_hold_accepts_a_passing_campaign():
    assert check_balance_hold([3.2, 0.5, 4.1, 3.0, 0.2]).passed


def test_balance_hold_threshold_scales_with_n():
    """El defecto exacto de `c1 >= 4`: escrito para n=5, aprobaba 4 de 20."""
    holds = [3.5] * 4 + [0.0] * 16  # 4 de 20 = 20 %
    v = check_balance_hold(holds, min_runs=3, n_runs=5)
    assert not v.passed, "un criterio de n=5 no puede juzgar 20 corridas"


# ── m5 ──────────────────────────────────────────────────────────────────────────


def test_soft_sat_cap_falls_with_theta():
    """El techo real baja con |theta|; compararlo contra la constante da 0 % siempre."""
    assert soft_sat_cap(60, np.array([0.0]))[0] == 60
    assert soft_sat_cap(60, np.array([200.0]))[0] == 30


def test_saturation_against_the_constant_would_report_zero():
    """El sesgo que apareció dos veces, reproducido."""
    theta = np.full(100, 80.0)
    cap = soft_sat_cap(60, theta)  # ~52
    pwm = cap.copy()  # el firmware registra el valor YA atenuado
    assert saturated_fraction(pwm, theta, 60) == pytest.approx(1.0)
    # Contra la constante 60, ninguna muestra la alcanza:
    assert float(np.count_nonzero(np.abs(pwm) >= 60)) / len(pwm) == 0.0


def test_m5_delivery_rejects_the_measured_campaign():
    """5/10 sobre 165° = 50 %, contra un criterio del 80 %."""
    entregas = [179.8, 156.4, 170.1, 158.0, 166.2, 157.1, 172.4, 159.9, 160.3, 168.8]
    v = check_m5_delivery(entregas)
    assert not v.passed
    assert v.metrics["fraction"] == pytest.approx(0.5)


def test_m5_delivery_accepts_a_good_campaign():
    assert check_m5_delivery([170.0] * 9 + [150.0]).passed


def test_energy_ratio_rejects_one_outlier():
    """10/10 menos uno sigue siendo FAIL: la banda es para todos."""
    assert not check_energy_ratio([0.96, 0.99, 1.00, 0.88]).passed


def test_energy_ratio_accepts_the_measured_campaign():
    assert check_energy_ratio([0.955, 0.981, 1.001, 0.964]).passed


# ── m6 ──────────────────────────────────────────────────────────────────────────


def test_m6_link_rejects_the_measured_rate():
    """26,1 Hz sobre 50 pedidos = 52 %."""
    assert not check_m6_link(26.1).passed


def test_m6_link_accepts_a_healthy_rate():
    assert check_m6_link(47.0).passed


def test_observations_live_rejects_a_frozen_stream():
    """El episodio muerto de P19: la secuencia deja de avanzar."""
    assert not check_observations_live([1, 2, 3, 4, 4, 4, 4]).passed


def test_observations_live_tolerates_a_single_repeat():
    assert check_observations_live([1, 2, 2, 3, 4]).passed


# ── Salud del lazo ──────────────────────────────────────────────────────────────


def test_loop_health_rejects_the_p15_signature():
    assert not check_loop_health(overruns=28, rate_hz=490.3).passed


def test_loop_health_accepts_a_clean_capture():
    assert check_loop_health(overruns=1, rate_hz=500.1).passed


# ── Resumen ─────────────────────────────────────────────────────────────────────


def test_summary_is_red_if_any_criterion_is_red():
    ok = check_m6_link(47.0)
    bad = check_m6_link(26.1)
    passed, texto = summarize([ok, bad])
    assert not passed
    assert "1/2" in texto
