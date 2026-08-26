"""Prueba el criterio contra casos cuyo veredicto se conoce de antemano.

**Por que existe este archivo.** En dos dias se emitieron tres veredictos falsos sobre este
banco, y en los tres el error no estuvo en la fisica sino en traducir el criterio a codigo.
El caso mas caro: `campana_a2.py` contaba cruces por cero sobre una senal que nunca cambia de
signo, asi que devolvia "friccion seca bloqueante" para cualquier entrada -incluido un pivote
sano- y nadie lo noto porque el numero que imprimia era plausible.

De ahi la regla que sigue este archivo: **cada criterio se prueba contra un caso que DEBE
fallar**, no solo contra uno que deba pasar. Un test que solo comprueba el caso feliz no
habria detectado nada de lo anterior.

Las trazas se generan integrando la dinamica real del pendulo -no una senal analitica- con
friccion viscosa, de Coulomb o ambas, muestreadas y cuantizadas como las entrega el encoder.
Asi la prueba cubre tambien el detector de picos y el estimador de la vertical, que es donde
estaban los errores.

    uv run pytest test_decay_analysis.py -v
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import decay_analysis as da

# ── Simulador ───────────────────────────────────────────────────────────────────
SIM_DT = 2.0e-4  # 5 kHz: ~2900 pasos por ciclo, de sobra para Euler simplectico


def simulate_free_decay(
    amp0_deg: float,
    *,
    lam: float = 0.0,
    tau_c: float = 0.0,
    seconds: float = 60.0,
    dt: float = SIM_DT,
) -> tuple[np.ndarray, np.ndarray]:
    """Integra  Jp*th'' = -k*sin(th) - Dp*th' - tau_c*sign(th')  desde el reposo.

    `lam` es la tasa de decaimiento de la envolvente en el caso viscoso puro, o sea
    Dp = 2*Jp*lam: asi el parametro de entrada es directamente lo que el analizador tiene que
    devolver, sin conversiones intermedias donde esconder un error.

    La adherencia se resuelve en los puntos de retorno: si al invertirse la velocidad el par
    gravitatorio no alcanza para vencer al seco, el pendulo se queda ahi. Es el mecanismo que
    produce el angulo de reposo distinto de cero del 2026-08-05.
    """
    dp = 2.0 * da.JP * lam
    n = int(seconds / dt)
    th = math.radians(amp0_deg)
    om = 0.0
    out = np.empty(n)
    stuck = False
    for i in range(n):
        out[i] = th
        if stuck:
            continue
        torque = -da.K_REST * math.sin(th) - dp * om
        if om != 0.0:
            torque -= tau_c * math.copysign(1.0, om)
        om_new = om + (torque / da.JP) * dt
        if om * om_new <= 0.0 and abs(da.K_REST * math.sin(th)) <= tau_c:
            stuck = True
            om = 0.0
            continue
        om = om_new
        th += om * dt
    return np.arange(n) * dt, np.degrees(out)


def make_run(
    amp0_deg: float,
    *,
    lam: float = 0.0,
    tau_c: float = 0.0,
    seconds: float = 60.0,
    rate_hz: float = 250.0,
    offset_deg: float = 0.0,
    preroll_s: float = 3.0,
    lift_s: float = 1.5,
    hold_s: float = 1.5,
    quantize: bool = True,
    seed: int = 0,
) -> da.Trace:
    """Arma una corrida completa tal como la produce el protocolo del banco.

    colgando y quieto -> se levanta a mano -> se sostiene -> se suelta -> decae.

    La pre-lectura colgando no es decorativa: es la unica referencia de vertical que le queda
    a una traza donde el pendulo no llega a oscilar, o sea al caso trabado. El protocolo la
    exige por eso, y este generador la reproduce para que el test lo verifique.
    """
    rng = np.random.default_rng(seed)
    t_sim, th_sim = simulate_free_decay(amp0_deg, lam=lam, tau_c=tau_c, seconds=seconds)

    step = int(round(1.0 / (rate_hz * SIM_DT)))
    decay = th_sim[::step]
    dt = step * SIM_DT

    n_pre = int(preroll_s / dt)
    n_lift = int(lift_s / dt)
    n_hold = int(hold_s / dt)
    pre = np.zeros(n_pre)
    # Rampa suave (coseno alzado): sin discontinuidad de velocidad en los extremos, que es
    # como se levanta un pendulo a mano.
    ramp = amp0_deg * 0.5 * (1.0 - np.cos(np.linspace(0.0, math.pi, n_lift)))
    hold = np.full(n_hold, amp0_deg)

    a = np.concatenate([pre, ramp, hold, decay]) + offset_deg
    if quantize:
        a = np.round(a / da.COUNT_DEG) * da.COUNT_DEG
        a = a + rng.normal(0.0, 0.2 * da.COUNT_DEG, a.size)
    t = np.arange(a.size) * dt
    theta = np.zeros(a.size)  # brazo sujeto: excursion nula
    return da.Trace(t, a, theta, source="sintetica")


# ── Casos que deben PASAR ───────────────────────────────────────────────────────
def test_viscoso_puro_se_clasifica_y_recupera_lambda():
    """Pivote sano de referencia: lambda del 2026-08-04, sin nada de seco."""
    tr = make_run(45.0, lam=da.REF_LAMBDA)
    r = da.analyze(tr, target_amp_deg=45.0)
    assert r.verdict == da.VISCOSO, r.summary()
    assert abs(r.lam_exp - da.REF_LAMBDA) / da.REF_LAMBDA < 0.05, f"lambda = {r.lam_exp}"
    assert r.r2_exp > 0.95


def test_coulomb_puro_se_clasifica_y_recupera_tau_c():
    """Seco moderado: suficientes semiciclos como para que corra el discriminador.

    El caso que destapo el sesgo del discriminador en amplitud: regresando dA contra A_k
    esta misma traza salia MIXTA, porque el ruido compartido entre los dos lados fabricaba
    un termino viscoso. Con el balance de energia sale SECO, que es lo que es.
    """
    tau = 2.5e-4
    tr = make_run(45.0, tau_c=tau)
    r = da.analyze(tr, target_amp_deg=45.0)
    assert r.verdict == da.SECO, r.summary()
    assert abs(r.tau_c_fit - tau) / tau < 0.10, f"tau_c = {r.tau_c_fit}"


def test_coulomb_puro_el_reposo_final_es_cota_inferior_de_tau_c():
    """El cuarto estimador es de otra familia, pero solo acota: no estima.

    El pendulo se detiene en el PRIMER punto de retorno que cae dentro de la banda de
    adherencia |k*sin(theta)| <= tau_c, y ese punto puede quedar en cualquier lugar de la
    banda. O sea que k*sin(theta_reposo) <= tau_c siempre, con igualdad solo si la parada fue
    justo en el borde. **Esto vale tambien para el 1,26e-3 del 2026-08-05**, que la tesis
    reporta como igualdad: es una cota inferior.
    """
    tau = 2.5e-4
    r = da.analyze(make_run(45.0, tau_c=tau))
    assert math.isfinite(r.tau_c_from_rest), r.notes
    assert 0.0 < r.tau_c_from_rest <= tau * 1.05, f"reposo = {r.tau_c_from_rest}"
    # Y un pivote sin friccion seca se queda en la vertical: un reposo distinto de cero es en
    # si mismo evidencia de Coulomb, que es lo que hace util al estimador aunque solo acote.
    sano = da.analyze(make_run(45.0, lam=da.REF_LAMBDA))
    assert not math.isfinite(sano.tau_c_from_rest) or sano.tau_c_from_rest < 0.1 * tau


def test_mixto_reporta_los_dos_terminos_en_unidades_fisicas():
    tau, lam = 2.5e-4, da.REF_LAMBDA
    r = da.analyze(make_run(45.0, lam=lam, tau_c=tau))
    assert r.verdict == da.MIXTO, r.summary()
    assert r.t_tau_c > 2.0 and r.t_dp > 2.0
    assert abs(r.tau_c_fit - tau) / tau < 0.15, f"tau_c = {r.tau_c_fit}"
    assert abs(r.dp_fit - 2.0 * da.JP * lam) / (2.0 * da.JP * lam) < 0.25, f"Dp = {r.dp_fit}"
    assert math.isfinite(r.cross_amp_deg) and r.cross_amp_deg > 0


def test_viscoso_puro_no_inventa_friccion_seca():
    """El otro lado del discriminador: sin Coulomb, tau_c no puede salir significativo."""
    r = da.analyze(make_run(45.0, lam=da.REF_LAMBDA))
    assert r.verdict == da.VISCOSO, r.summary()
    assert not (r.t_tau_c > 2.0), f"tau_c = {r.tau_c_fit} (t = {r.t_tau_c})"


def test_seco_severo_se_detecta_por_conteo_aunque_no_haya_regresion():
    """tau_c del 2026-08-05: detiene el pendulo en pocos semiciclos.

    No alcanzan los picos para la regresion, y el veredicto tiene que salir igual del conteo.
    Es el caso donde el script viejo acertaba por accidente y por el motivo equivocado.
    """
    r = da.analyze(make_run(45.0, tau_c=da.REF_TAU_C))
    assert r.verdict in (da.SECO, da.TRABADO), r.summary()
    assert r.n_peaks < da.MIN_PEAKS_FOR_FIT
    assert 0.0 < r.tau_c_from_rest <= da.REF_TAU_C * 1.05, f"tau_c(reposo) = {r.tau_c_from_rest}"


# ── Casos que DEBEN fallar, o que el criterio viejo erraba ──────────────────────
def test_offset_de_341_grados_no_cambia_el_veredicto():
    """El fallo exacto de la campana del 2026-08-12.

    `pend_position_deg` acumula vueltas y su cero es volatil, asi que la misma planta puede
    leerse en 0 o en 341 grados. El criterio de cruces por cero daba "friccion bloqueante"
    para el segundo caso. Aca el veredicto tiene que ser identico.
    """
    limpia = da.analyze(make_run(45.0, lam=da.REF_LAMBDA, offset_deg=0.0))
    corrida = da.analyze(make_run(45.0, lam=da.REF_LAMBDA, offset_deg=341.0))
    assert corrida.verdict == da.VISCOSO, corrida.summary()
    assert abs(corrida.lam_exp - limpia.lam_exp) / limpia.lam_exp < 0.02
    assert abs(corrida.equilibrium_deg - 341.0) < 1.0


def test_trabado_no_puede_pasar_por_sano():
    """Pivote agarrotado: se suelta y no completa un ciclo. Prohibido clasificarlo VISCOSO."""
    r = da.analyze(make_run(45.0, tau_c=8.0e-3))
    assert r.verdict == da.TRABADO, r.summary()
    assert r.verdict not in (da.VISCOSO, da.MIXTO)


def test_submuestreo_de_9hz_se_descarta_en_vez_de_clasificarse():
    """La campana del 2026-08-12 muestreo a 9,1 Hz y el script emitio un veredicto igual.

    A esa tasa los picos no se pueden ubicar. El resultado correcto no es otro veredicto: es
    ninguno.
    """
    r = da.analyze(make_run(45.0, lam=da.REF_LAMBDA, rate_hz=9.1))
    assert r.verdict == da.DESCARTADA, r.summary()
    assert any(g.name == "tasa_envolvente" for g in r.failed_guards)


def test_tasa_intermedia_reporta_lambda_pero_no_discrimina():
    """13 Hz: la tasa real de los datos del 2026-08-04, que son LA referencia viscosa.

    Alcanza para la envolvente y no para el discriminador. El analizador tiene que decir
    exactamente eso en vez de inventar un veredicto Coulomb/viscoso por corrida.
    """
    r = da.analyze(make_run(45.0, lam=da.REF_LAMBDA, rate_hz=13.3))
    assert r.verdict == da.INDETERMINADO, r.summary()
    assert math.isfinite(r.lam_exp)
    assert abs(r.lam_exp - da.REF_LAMBDA) / da.REF_LAMBDA < 0.15
    assert any("discriminador" in n for n in r.notes)


def test_ventana_corta_avisa_que_no_llega_a_media_vida():
    """15 s contra una vida media de 24 s: la envolvente apenas cae."""
    r = da.analyze(make_run(45.0, lam=da.REF_LAMBDA, seconds=15.0))
    assert any("vida media" in n for n in r.notes), r.notes


def test_amplitud_distinta_de_la_pedida_se_avisa_y_se_agrupa_por_la_medida():
    """Soltar a mano no da en el blanco, y eso cambia la etiqueta, no la validez.

    La corrida "de 15 grados" del 2026-08-12 partio de 65 y nadie lo noto; la del 2026-08-12
    por la tarde pedia 15 y solto desde 23,3, con 81 semiciclos limpios. Lo correcto no es
    descartarla -seria tirar dato bueno- sino avisar y agruparla por la amplitud MEDIDA.
    """
    r = da.analyze(make_run(65.0, lam=da.REF_LAMBDA), target_amp_deg=15.0)
    assert r.verdict == da.VISCOSO, r.summary()
    assert any(g.name == "amplitud_objetivo" and not g.ok for g in r.guards)
    assert abs(r.amp0_deg - 65.0) < 3.0

    # y la agregacion lo pone en la casilla de 65, no en la de 15
    agg = da.compare_across_amplitudes([(15.0, r)])
    assert list(agg["por_amplitud"]) == [70.0], agg["por_amplitud"]


def test_angulo_congelado_se_nombra_por_lo_que_es():
    """Cinco corridas del 2026-08-12 salieron con el angulo del pendulo constante.

    El motivo que se imprimia era `amplitud_minima`, que no sugiere ir a mirar el banco. Un
    encoder incremental en reposo da un valor exactamente constante -es un contador, no tiene
    temblor- asi que la traza plana no distingue "no se solto" de "el canal no lee"; las dos
    invalidan la corrida y las dos piden mirar el banco, no el analisis.
    """
    t = np.arange(0, 70.0, 1 / 250.0)
    tr = da.Trace(t, np.full(t.size, -996.50), np.zeros(t.size))
    r = da.analyze(tr, target_amp_deg=35.0)
    assert r.verdict == da.DESCARTADA, r.summary()
    assert any(g.name == "angulo_cambia" for g in r.failed_guards), [g.name for g in r.failed_guards]


def test_brazo_algo_movido_no_descarta_si_la_envolvente_aguanta():
    """5,8 grados de excursion descartaban una corrida con 92 semiciclos y R2 = 0,998.

    El limite duro queda para excursiones donde el trasvase de energia es innegable; entre
    medio es un aviso, y quien decide es el R2 junto con `centro_estable`.
    """
    tr = make_run(35.0, lam=da.REF_LAMBDA)
    tr.theta_deg = np.linspace(0.0, 5.8, len(tr))
    r = da.analyze(tr)
    assert r.verdict == da.VISCOSO, r.summary()
    assert any(g.name == "brazo_quieto" and not g.ok and not g.fatal for g in r.guards)

    tr2 = make_run(35.0, lam=da.REF_LAMBDA)
    tr2.theta_deg = np.linspace(0.0, 13.0, len(tr2))
    assert da.analyze(tr2).verdict == da.DESCARTADA


def test_brazo_suelto_se_descarta():
    """El fallo del 2026-08-05: con el brazo libre la envolvente deja de decaer."""
    tr = make_run(45.0, lam=da.REF_LAMBDA)
    tr.theta_deg = np.linspace(0.0, 13.0, len(tr))
    r = da.analyze(tr)
    assert r.verdict == da.DESCARTADA, r.summary()
    assert any(g.name == "brazo_quieto" for g in r.failed_guards)


def test_hueco_de_transporte_se_declara_y_se_excluyen_los_pares_que_lo_cruzan():
    """El CSV del 2026-08-12 tiene un hueco de 1,24 s. Un hueco no se tapa: se declara.

    Pero tampoco descarta la corrida: lo que se descarta es el par de picos que cruza el
    hueco, porque ese par abarca mas de un semiciclo y su perdida de energia contamina la
    regresion. El resto de la traza sigue siendo dato bueno, y lambda tiene que salir igual.
    """
    tr = make_run(45.0, lam=da.REF_LAMBDA)
    tr.t = tr.t.copy()
    tr.t[len(tr) // 2 :] += 1.24
    r = da.analyze(tr)
    assert r.verdict == da.VISCOSO, r.summary()
    assert any(g.name == "huecos" and not g.ok for g in r.guards)
    assert any("semiciclo" in n for n in r.notes), r.notes
    assert abs(r.lam_exp - da.REF_LAMBDA) / da.REF_LAMBDA < 0.05


def test_energia_inyectada_se_detecta_y_se_analiza_el_tramo_mas_largo():
    """Dos sueltas encadenadas: la primera larga y limpia, la segunda corta.

    Es la forma de `spindown_man_1.csv` del 2026-08-05. Quedarse con la ultima -que era lo
    que hacia la primera version de este modulo- hace pasar el tramo corto por el resultado
    del ensayo.
    """
    largo = make_run(45.0, lam=da.REF_LAMBDA, seconds=40.0, preroll_s=3.0)
    corto = make_run(20.0, lam=da.REF_LAMBDA, seconds=6.0, preroll_s=0.0, lift_s=0.5, hold_s=0.5)
    tr = da.Trace(
        np.concatenate([largo.t, corto.t + largo.t[-1] + 0.004]),
        np.concatenate([largo.alpha_deg, corto.alpha_deg]),
        np.zeros(len(largo) + len(corto)),
    )
    r = da.analyze(tr)
    assert r.n_releases >= 2, r.notes
    assert r.verdict == da.VISCOSO, r.summary()
    assert r.amp0_deg > 35.0, f"se quedo con el tramo corto: amp0 = {r.amp0_deg}"


def test_centro_que_se_desplaza_se_descarta():
    """Un pendulo libre decae alrededor de una vertical FIJA.

    Si el centro se corre -encoder perdiendo cuentas, mecanismo moviendose- la envolvente
    puede verse perfecta y el lambda que sale no significa nada. Sin esta guarda el
    analizador emitia un veredicto igual.
    """
    tr = make_run(45.0, lam=da.REF_LAMBDA)
    tr.alpha_deg = tr.alpha_deg + np.linspace(0.0, 15.0, len(tr))
    r = da.analyze(tr)
    assert r.verdict == da.DESCARTADA, r.summary()
    assert any(g.name == "centro_estable" for g in r.failed_guards)


def test_sin_oscilacion_ni_prelectura_no_se_ubica_la_vertical():
    """Senal plana con ruido: no hay nada que medir, y el analizador tiene que decirlo."""
    rng = np.random.default_rng(1)
    t = np.arange(0, 60.0, 1 / 250.0)
    a = 341.0 + rng.normal(0.0, 3.0, t.size)  # ruido grande: ni quieto ni oscilando
    r = da.analyze(da.Trace(t, a, np.zeros(t.size)))
    assert r.verdict == da.DESCARTADA, r.summary()


# ── El criterio viejo, para dejar constancia de que estaba roto ─────────────────
def test_el_criterio_viejo_falla_donde_el_nuevo_acierta():
    """Reproduce `analizar_decaimiento` de `campana_a2.py` sobre un pivote SANO con offset.

    Documenta el modo de falla en vez de solo afirmarlo: la misma traza que el analizador
    nuevo clasifica VISCOSO, el conteo de cruces por cero la reporta con 0 ciclos, que su
    tabla traducia a "friccion seca bloqueante".
    """
    tr = make_run(45.0, lam=da.REF_LAMBDA, offset_deg=341.0)
    a = tr.alpha_deg
    cruces = int(np.count_nonzero(a[:-1] * a[1:] < 0))
    assert cruces == 0, "la senal nunca cambia de signo: el criterio viejo no puede contar"
    assert da.analyze(tr).verdict == da.VISCOSO


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
