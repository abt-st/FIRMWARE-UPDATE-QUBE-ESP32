"""P19 / P20: que un dato falso sea imposible, no improbable.

Antes de esto, ``QubeRealEnv.step()`` atrapaba el error de red, escribía un warning y
**conservaba el último estado**. Un episodio muerto —enlace caído, el modo cambiado por
debajo, el lazo de control detenido— producía observaciones que parecían perfectamente
válidas, y todos los números de la campaña se calculaban sobre ellas. Es un defecto de
integridad de datos, no de rendimiento: una traza así es indistinguible de una real
*después* de grabada.

Estos tests corren sin placa: el `env` se construye sin I/O y se le inyectan respuestas.
Cada criterio se ejercita contra un caso que **debe fallar** y contra uno que debe pasar —
sin las dos mitades, un test que nunca puede reprobar pasa por barrera.
"""

from __future__ import annotations

import numpy as np
import pytest
import requests

from qube_rl.envs.qube_real import (
    MAX_OBS_AGE_MS,
    MAX_REPEATED_OBS,
    MIN_FREQ_RATIO,
    QubeRealEnv,
    StaleObservationError,
)


def _fresh(seq: int = 1, age: int = 0, md: int = 6) -> dict:
    """Una respuesta de /rl_step sana."""
    return {"th": 0.0, "al": 3.14, "thd": 0.0, "ald": 0.0, "seq": seq, "age": age, "md": md, "pv": 4}


@pytest.fixture
def env(monkeypatch):
    """Env sin I/O: no se contacta la placa en ningún momento.

    Se anulan las tres salidas de red que usa ``reset()``; lo que se verifica acá es la
    lógica de procedencia y de frecuencia, no el transporte.
    """
    e = QubeRealEnv(
        esp32_ip="0.0.0.0",
        auto_set_mode=False,
        homing_on_start=False,
        reset_settle_time=0.0,
    )
    monkeypatch.setattr(e, "_send_rl_action", lambda *_a, **_k: None)
    monkeypatch.setattr(e, "_send_rl_reset", lambda *_a, **_k: None)
    monkeypatch.setattr(e, "_set_mode", lambda *_a, **_k: None)
    monkeypatch.setattr(e, "_get_rl_state", lambda *_a, **_k: _fresh())
    e._last_obs_seq = None
    e._repeated_obs = 0
    return e


# ── P19: procedencia ────────────────────────────────────────────────────────────


def test_a_fresh_observation_is_accepted(env):
    env._check_freshness(_fresh())  # no debe lanzar


def test_missing_provenance_fields_are_rejected(env):
    """Un firmware anterior al arreglo no puede pasar por bueno en silencio."""
    viejo = {"th": 0.0, "al": 3.14, "thd": 0.0, "ald": 0.0, "pv": 3}
    with pytest.raises(StaleObservationError, match="seq/age/md"):
        env._check_freshness(viejo)


def test_observation_from_another_mode_is_rejected(env):
    """La placa salió del modo 6 a mitad de episodio: lo que siga no mide nada."""
    with pytest.raises(StaleObservationError, match="mode 0"):
        env._check_freshness(_fresh(md=0))


def test_stale_observation_is_rejected(env):
    """A 50 Hz, 200 ms son diez ticks perdidos: es un lazo detenido, no latencia."""
    with pytest.raises(StaleObservationError, match="ms old"):
        env._check_freshness(_fresh(age=MAX_OBS_AGE_MS + 1))


def test_an_observation_at_the_age_limit_still_passes(env):
    """El límite es inclusivo: sin esto el criterio reprobaría lecturas sanas."""
    env._check_freshness(_fresh(age=MAX_OBS_AGE_MS))


def test_a_frozen_sequence_is_rejected(env):
    """El caso que hacía inatribuibles las campañas del modo 6."""
    env._check_freshness(_fresh(seq=7))
    for _ in range(MAX_REPEATED_OBS - 1):
        env._check_freshness(_fresh(seq=7))
    with pytest.raises(StaleObservationError, match="frozen"):
        env._check_freshness(_fresh(seq=7))


def test_one_repeat_is_tolerated(env):
    """El cliente puede sondear más rápido que los 50 Hz del firmware.

    Sin esta tolerancia el criterio abortaría episodios sanos, que es la otra forma de
    romperlo.
    """
    env._check_freshness(_fresh(seq=7))
    env._check_freshness(_fresh(seq=7))
    env._check_freshness(_fresh(seq=8))  # avanzó: se limpia el contador
    assert env._repeated_obs == 0


def test_step_raises_instead_of_reusing_the_last_state(env, monkeypatch):
    """El corazón de P19: caerse el enlace TERMINA el episodio, no lo continúa."""

    def link_down(_action):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(env, "_rl_step", link_down)
    with pytest.raises(StaleObservationError, match="link is down"):
        env.step(np.array([0.0], dtype=np.float32))


def test_step_accepts_a_healthy_round_trip(env, monkeypatch):
    seq = {"n": 0}

    def ok(_action):
        seq["n"] += 1
        return _fresh(seq=seq["n"])

    monkeypatch.setattr(env, "_rl_step", ok)
    obs, _rwd, terminated, truncated, _ = env.step(np.array([0.0], dtype=np.float32))
    assert obs.shape == (8,)
    assert not terminated and not truncated
    assert env._steps_this_episode == 1


# ── P20: la frecuencia alcanzada es parte del contrato ──────────────────────────


def test_the_frequency_check_rejects_a_slow_link(env):
    """Se entrenó a '50 Hz' sobre un enlace de 26,1 Hz sin que nada lo dijera."""
    import time

    env.timing.control_freq = 50
    env._steps_this_episode = 26
    env._episode_start_s = time.time() - 1.0  # 26 pasos en 1 s → 26 Hz
    with pytest.raises(StaleObservationError, match="frecuencia alcanzada"):
        env.reset()


def test_the_frequency_check_passes_a_healthy_link(env):
    import time

    env.timing.control_freq = 50
    env._steps_this_episode = 48
    env._episode_start_s = time.time() - 1.0  # 48 Hz sobre 50 → 96 %
    env.reset()  # no debe lanzar
    assert env._measured_hz == pytest.approx(48, rel=0.1)


def test_strict_freq_false_degrades_to_a_warning(env):
    """Para trabajo exploratorio: avisa, pero no aborta."""
    import time

    env.strict_freq = False
    env.timing.control_freq = 50
    env._steps_this_episode = 10
    env._episode_start_s = time.time() - 1.0
    env.reset()
    assert env._measured_hz is not None
    assert env._measured_hz / 50 < MIN_FREQ_RATIO


def test_the_episode_counters_reset_between_episodes(env):
    env._steps_this_episode = 5
    env._last_obs_seq = 99
    env._repeated_obs = 2
    env.reset()
    assert env._steps_this_episode == 0
    assert env._last_obs_seq is None
    assert env._repeated_obs == 0
