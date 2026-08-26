"""Tests del análisis en vivo y de la grabación, sin hardware.

El caso que da nombre a la mitad de este archivo es el del sobrepaso: la métrica vieja
normalizaba por ``|setpoint|`` y en un escalón que cruza el cero devolvía más del doble
del valor real. Aquí queda fijado con números, para que el día que alguien "simplifique"
la normalización el test lo diga.
"""

from __future__ import annotations

import csv

import numpy as np
import pytest

from qube_analysis.metrics import compute_overshoot, compute_overshoot_step
from qube_app.analysis import (
    StepDetector,
    derive_velocity,
    phase_portrait,
    step_metrics,
    transition_summary,
    upright_stats,
    wrap_deg,
)
from qube_app.recorder import CSV_FIELDS, Recorder
from qube_app.stream import Chunk
from qube_daq.__main__ import CSV_FIELDS as DAQ_CSV_FIELDS


def step_trace(y0: float, sp: float, peak: float, n: int = 500, dt: float = 0.002):
    """Escalón con sobrepaso: sube al pico, vuelve al setpoint y se queda ahí."""
    t = np.arange(n) * dt
    rise, settle = n // 4, n // 2
    return t, np.concatenate(
        [
            np.linspace(y0, peak, rise),
            np.linspace(peak, sp, settle),
            np.full(n - rise - settle, sp),
        ]
    )


# ── Sobrepaso: la métrica correcta contra la vieja ────────────────────────────


def test_overshoot_normalises_by_the_step_not_the_setpoint():
    # El escalón real del banco: de −20° a +17°, con un pico de +24°.
    _, y = step_trace(y0=-20.0, sp=17.0, peak=24.0)

    correcto = compute_overshoot_step(y, setpoint=17.0, y0=-20.0)
    legacy = compute_overshoot(y, setpoint=17.0)

    assert correcto == pytest.approx(7.0 / 37.0 * 100.0, rel=1e-3)  # 18,9 %
    assert legacy == pytest.approx(7.0 / 17.0 * 100.0, rel=1e-3)  # 41,2 %
    assert legacy > 2 * correcto, "en un escalón que cruza el cero la métrica vieja duplica"


def test_overshoot_agrees_with_the_legacy_metric_when_the_step_starts_at_zero():
    # Donde la normalización vieja era correcta, las dos deben coincidir: si no, el
    # cambio de definición rompería el empalme con las campañas anteriores.
    _, y = step_trace(y0=0.0, sp=20.0, peak=28.0)
    assert compute_overshoot_step(y, 20.0, 0.0) == pytest.approx(compute_overshoot(y, 20.0), rel=1e-6)


def test_overshoot_is_zero_when_the_response_never_passes_the_setpoint():
    _, y = step_trace(y0=0.0, sp=20.0, peak=20.0)
    assert compute_overshoot_step(y, 20.0, 0.0) == 0.0


def test_negative_step_looks_at_the_minimum_not_the_maximum():
    # Bajando, el pico que importa es el mínimo. Tomar `max` daría el valor de partida.
    _, y = step_trace(y0=17.0, sp=-20.0, peak=-27.0)
    assert compute_overshoot_step(y, -20.0, 17.0) == pytest.approx(7.0 / 37.0 * 100.0, rel=1e-3)


def test_step_metrics_reports_both_numbers_side_by_side():
    t, y = step_trace(y0=-20.0, sp=17.0, peak=24.0)
    m = step_metrics(t, y, setpoint_deg=17.0)

    assert m is not None
    assert m.overshoot_pct == pytest.approx(18.9, abs=0.2)
    assert m.overshoot_legacy_pct == pytest.approx(41.2, abs=0.2)
    assert m.sse_deg == pytest.approx(0.0, abs=0.2)
    assert m.y0_deg == pytest.approx(-20.0)


def test_step_metrics_declines_a_segment_too_short_to_mean_anything():
    assert step_metrics(np.arange(5) * 0.002, np.zeros(5), 10.0) is None


# ── Detección del escalón ─────────────────────────────────────────────────────


def test_step_detector_ignores_noise_and_fires_on_a_real_change():
    det = StepDetector(min_step_deg=1.0)

    assert det.update(20.0, t_now_s=0.0) is False, "el primer valor sólo siembra la referencia"
    assert det.update(20.2, t_now_s=1.0) is False, "0,2° es ruido de sondeo, no un escalón"
    assert det.update(-20.0, t_now_s=2.0) is True
    assert det.t_step_s == 2.0


def test_step_detector_measures_only_from_the_step_onwards():
    t, y = step_trace(y0=-20.0, sp=17.0, peak=24.0)
    det = StepDetector()
    det.update(-20.0, 0.0)
    det.update(17.0, float(t[0]))

    m = det.measure(t, y)
    assert m is not None
    assert m.samples == len(y)


# ── Velocidad, retrato de fase, upright ───────────────────────────────────────


def test_velocity_is_derived_from_the_unwrapped_signal():
    # Una vuelta completa a 360 °/s: sobre la señal cruda la derivada es constante.
    t = np.arange(1000) * 0.002
    alpha = 360.0 * t
    assert np.allclose(derive_velocity(t, alpha, smooth_n=1), 360.0, atol=1e-6)
    # Y el suavizado no debe introducir sesgo en una rampa: la media móvil es de fase cero.
    assert np.allclose(derive_velocity(t, alpha, smooth_n=9), 360.0, atol=1e-6)


def test_deriving_the_wrapped_signal_would_inject_a_spike():
    # Es la razón por la que el transporte entrega α sin envolver. Este test documenta
    # el modo de falla que se evita, no una función que se use.
    t = np.arange(1000) * 0.002
    alpha = 360.0 * t
    v_mal = derive_velocity(t, wrap_deg(alpha), smooth_n=1)
    assert np.abs(v_mal).max() > 10_000.0


def test_phase_portrait_cuts_the_line_at_the_wrap():
    alpha = np.array([170.0, 179.0, -179.0, -170.0])
    x, y = phase_portrait(alpha, np.ones(4))
    assert np.isnan(x[1]) and np.isnan(y[1]), "el salto ±180° no debe dibujarse como trayectoria"
    assert not np.isnan(x[0]) and not np.isnan(x[3])


def test_upright_stats_measures_the_hold_not_just_the_fraction():
    # 1 s de ventana a 500 Hz: medio segundo arriba, al final.
    t = np.arange(500) * 0.002
    alpha = np.where(t >= 0.5, 178.0, 10.0)
    st = upright_stats(t, alpha, tolerance_deg=20.0)

    assert st.fraction == pytest.approx(0.5, abs=0.01)
    assert st.hold_now_s == pytest.approx(0.5, abs=0.01)
    assert st.hold_max_s == pytest.approx(0.5, abs=0.01)


def test_upright_hold_resets_when_the_pendulum_falls():
    t = np.arange(500) * 0.002
    alpha = np.where(t < 0.4, 179.0, 5.0)  # se cae y no vuelve
    st = upright_stats(t, alpha)

    assert st.hold_max_s == pytest.approx(0.4, abs=0.01)
    assert st.hold_now_s == 0.0


# ── Traspaso latcheado por el firmware ────────────────────────────────────────


def test_transition_summary_decodes_the_reason_bitmask():
    s = transition_summary(
        {
            "swing_trans_reason": 6,  # peak | forced
            "swing_trans_alpha": -174.55,
            "swing_trans_vel": 77.6,
            "swing_trans_energy": 0.9987,
            "swing_trans_ms_ago": 120,
        }
    )
    assert s is not None
    assert s["reasons"] == ["peak", "forced"]
    assert s["energy_ratio"] == pytest.approx(0.9987)


def test_no_transition_is_none_not_an_empty_summary():
    assert transition_summary({"swing_trans_reason": 0}) is None
    assert transition_summary({}) is None


# ── Grabación ─────────────────────────────────────────────────────────────────


def make_chunk(n: int = 4, t_pc_s: float = 1.25) -> Chunk:
    return Chunk(
        t_s=np.arange(n) * 0.002,
        th_deg=np.full(n, 12.5),
        al_deg=np.full(n, 190.0),  # crudo: fuera de [-180, 180)
        pwm=np.full(n, -40),
        mode=np.full(n, 5),
        t_pc_s=t_pc_s,
        t_now_us=987_654,
        dropped_total=0,
    )


def test_csv_keeps_the_canonical_schema_first(tmp_path):
    # Las columnas nuevas van AL FINAL para que `qube_daq plot` y el análisis existente
    # lean el archivo sin adaptadores.
    assert CSV_FIELDS[: len(DAQ_CSV_FIELDS)] == DAQ_CSV_FIELDS

    path = tmp_path / "captura.csv"
    with Recorder(path) as rec:
        rec.write(make_chunk())

    rows = list(csv.reader(path.open(encoding="utf-8")))
    assert tuple(rows[0]) == CSV_FIELDS
    assert len(rows) == 5


def test_csv_carries_both_clocks_and_both_alphas(tmp_path):
    path = tmp_path / "captura.csv"
    with Recorder(path) as rec:
        rec.write(make_chunk(n=2, t_pc_s=3.5))

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert float(rows[0]["alpha_deg"]) == pytest.approx(-170.0), "envuelto para graficar"
    assert float(rows[0]["alpha_raw_deg"]) == pytest.approx(190.0), "crudo para derivar"
    assert float(rows[0]["t_s"]) == 0.0
    assert float(rows[0]["t_pc_block_s"]) == pytest.approx(3.5)
    assert int(rows[0]["t_now_us"]) == 987_654


def test_recorder_refuses_to_write_when_closed(tmp_path):
    rec = Recorder(tmp_path / "x.csv")
    with pytest.raises(RuntimeError):
        rec.write(make_chunk())


# ── Preferencias y presets ────────────────────────────────────────────────────


def test_settings_roundtrip_presets_and_prefs(tmp_path):
    from qube_app.settings import AppSettings

    path = tmp_path / "settings.json"
    settings = AppSettings(path)
    settings.update(window_s=35.0, rate_hz=250)
    settings.save_preset("swing agresivo", {"ke": 0.8, "sp": 90.0})

    reloaded = AppSettings(path)
    assert reloaded.get("window_s") == 35.0
    assert reloaded.get("rate_hz") == 250
    assert reloaded.presets["swing agresivo"] == {"ke": 0.8, "sp": 90.0}

    reloaded.delete_preset("swing agresivo")
    assert AppSettings(path).names() == []


def test_settings_survive_a_corrupt_file(tmp_path):
    """Perder las preferencias no es motivo para que la app no abra."""
    from qube_app.settings import DEFAULTS, AppSettings

    path = tmp_path / "settings.json"
    path.write_text("{esto no es json", encoding="utf-8")

    settings = AppSettings(path)
    assert settings.get("window_s") == DEFAULTS["window_s"]
    assert settings.presets == {}


def test_settings_ignore_unknown_keys(tmp_path):
    """Una clave que ya no existe no debe reaparecer en la interfaz por la puerta de atrás."""
    import json

    from qube_app.settings import AppSettings

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"prefs": {"window_s": 40.0, "obsoleta": 1}}), encoding="utf-8")

    settings = AppSettings(path)
    assert settings.get("window_s") == 40.0
    assert "obsoleta" not in settings.prefs
