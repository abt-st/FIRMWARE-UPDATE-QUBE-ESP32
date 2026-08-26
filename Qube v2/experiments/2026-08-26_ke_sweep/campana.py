"""Barrido de `ke` del swing-up, con la salud del enlace medida en cada tanda.

Protocolo, y por qué cada pieza:

- **La latencia se mide con `/rl_state`, no con `/state`.** [P28]: cada petición a
  `/state` o `/cmd` le cuesta al lazo de 500 Hz una resincronización (0,97 overruns por
  petición contra 0,00 en `/rl_state` y `/daq`). Medir el enlace con `/state` sería
  degradar justo lo que se quiere observar.
- **`/state` se sondea a tasa FIJA** (`STATE_HZ`) en todas las tandas. No se puede
  eliminar —los latches del traspaso sólo están ahí— pero sí dejar su carga constante,
  para que sea una constante del experimento y no un confundente entre tandas.
- **`rt=0`**: un intento por tanda. Con el reintento activo (def. desde v1.63.0),
  «enganchó al primer intento» y «enganchó al tercero» dan el mismo veredicto y la tasa
  de éxito se infla en silencio.
- **Homing antes de cada tanda.** No es ritual: la compuerta de v1.60.0 lo exige, y el
  cero del brazo es contra lo que se mide toda la escalera de límites del servo.
- Las trazas son del DAQ del chip a 500 Hz, marcadas por el tick que las produjo.

Uso:  python campana.py <etiqueta> <ke> [<ke> ...]
"""

from __future__ import annotations

import json
import statistics
import struct
import sys
import time
from pathlib import Path

import requests

URL = "http://192.168.4.1"
AQUI = Path(__file__).parent
DATA = AQUI / "data"
DATA.mkdir(parents=True, exist_ok=True)  # una tanda perdida por un directorio ausente es una tanda de motor gastada
MAGIC = 0x51414451

#: Tasa fija de sondeo de `/state`. Constante del experimento (ver P28).
STATE_HZ = 4.0
#: Duración máxima de un intento antes de cortar por tiempo.
INTENTO_S = 40.0
#: Parámetros fijos del barrido. `tn=162` está medido como mejor que el default 155.
FIJOS = {"tn": 162, "rt": 0, "sv": 0}

ses = requests.Session()
ses.headers.update({"Connection": "keep-alive"})


def js(path: str, timeout: float = 5.0) -> dict:
    r = ses.get(URL + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def leer(path: str, timeout: float = 5.0) -> bytes:
    r = ses.get(URL + path, timeout=timeout)
    r.raise_for_status()
    return r.content


def parar() -> None:
    """Paro de emergencia, con reintentos y sin lanzar. Última orden que importa."""
    for _ in range(10):
        try:
            ses.get(URL + "/cmd?x=1", timeout=3)
            return
        except requests.RequestException:
            time.sleep(0.3)


# -- Enlace -------------------------------------------------------------------


def medir_enlace(n: int = 20) -> dict:
    """RTT de `/rl_state`: el endpoint barato. Devuelve mediana, p95, máx y fallos."""
    rtts: list[float] = []
    fallos = 0
    for _ in range(n):
        t0 = time.perf_counter()
        try:
            ses.get(URL + "/rl_state", timeout=3)
            rtts.append((time.perf_counter() - t0) * 1000.0)
        except requests.RequestException:
            fallos += 1
        time.sleep(0.02)
    if not rtts:
        return {"n": 0, "fallos": fallos}
    ordenados = sorted(rtts)
    return {
        "n": len(rtts),
        "fallos": fallos,
        "mediana_ms": round(statistics.median(rtts), 2),
        "p95_ms": round(ordenados[int(0.95 * (len(ordenados) - 1))], 2),
        "max_ms": round(max(rtts), 2),
        "min_ms": round(min(rtts), 2),
    }


# -- Homing -------------------------------------------------------------------


def homing(timeout_s: float = 45.0) -> dict:
    """Corre el homing y espera a DONE/FAIL. Devuelve lo que midió."""
    js("/cmd?m=3")
    t0 = time.time()
    fase = "?"
    while time.time() - t0 < timeout_s:
        time.sleep(0.4)
        try:
            st = js("/state")
        except requests.RequestException:
            continue
        fase = st.get("homing_phase", "?")
        if fase in ("DONE", "FAIL"):
            return {
                "fase": fase,
                "ok": st.get("homing_ok"),
                "fail": st.get("homing_fail"),
                "range": st.get("homing_range"),
                "center": st.get("homing_center"),
                "pwm_sign": st.get("homing_pwm_sign"),
                "s": round(time.time() - t0, 1),
            }
    return {"fase": fase, "ok": False, "timeout": True, "s": round(time.time() - t0, 1)}


# -- Una tanda ----------------------------------------------------------------


def drenar(muestras: list) -> tuple[int, int]:
    """Lee un bloque del DAQ. Devuelve (muestras nuevas, dropped acumulado)."""
    buf = leer("/daq/read")
    if len(buf) < 16:
        return 0, -1
    magic, _pv, _sb, n, dropped, _tnow = struct.unpack_from("<IBBHII", buf, 0)
    if magic != MAGIC:
        return 0, -1
    for i in range(n):
        muestras.append(struct.unpack_from("<IffhBB", buf, 16 + 16 * i))
    return n, dropped


def tanda(etiqueta: str, ke: float, indice: int) -> dict:
    reg: dict = {"etiqueta": etiqueta, "ke": ke, "indice": indice, "fijos": dict(FIJOS)}
    reg["t_inicio"] = time.strftime("%H:%M:%S")

    # Un reintento: el homing falla por rango fuera de [262, 278] cuando un toque no
    # llega al tope de verdad, y eso es transitorio. Gastar la tanda entera por eso
    # sería tirar un intento de motor por una causa que se corrige repitiendo.
    reg["homing"] = homing()
    if not reg["homing"].get("ok"):
        reg["homing_reintento"] = homing()
        if not reg["homing_reintento"].get("ok"):
            reg["abortada"] = "homing fallo dos veces"
            return reg
        reg["homing"] = reg["homing_reintento"]

    # Los parámetros se escriben DESPUÉS del homing y antes del `m5`: el override de
    # `ke` sobrevive a `setMode(5)` a propósito, pero conviene no depender de eso.
    fijos = "&".join(f"{k}={v}" for k, v in FIJOS.items())
    js(f"/cmd?{fijos}")
    js(f"/cmd?ke={ke}")
    js("/cmd?rj=1")  # sin esto, el peor caso del arranque domina loop_dt_max_us

    antes = js("/state")
    reg["ke_confirmado"] = {"ke_gain": antes.get("ke_gain"), "ke_override": antes.get("ke_override")}
    MONOTONICOS = ("pend_wraps", "safety_cuts", "safety_derates", "loop_overruns")
    base_mono = {k: antes.get(k) for k in MONOTONICOS}
    reg["monotonicos_antes"] = base_mono
    reg["enlace_antes"] = medir_enlace()

    try:
        js("/daq?stop=1")
    except requests.RequestException:
        pass
    js("/daq?decim=1&start=1")

    muestras: list = []
    eventos: list = []
    rtts_state: list[float] = []
    errores = 0
    dropped = 0
    js("/cmd?m=5")

    t0 = time.time()
    prox_state = 0.0
    prev_clave = None
    modo0_desde = None
    while time.time() - t0 < INTENTO_S:
        try:
            _n, d = drenar(muestras)
            if d >= 0:
                dropped = d
        except requests.RequestException:
            errores += 1

        ahora = time.time() - t0
        if ahora >= prox_state:
            prox_state = ahora + 1.0 / STATE_HZ
            t_rtt = time.perf_counter()
            try:
                st = js("/state", timeout=4)
                rtts_state.append((time.perf_counter() - t_rtt) * 1000.0)
            except requests.RequestException:
                errores += 1
                continue
            clave = (
                st.get("mode"),
                st.get("swing_trans_reason"),
                st.get("swing_recenter_phase"),
                st.get("swing_zero_phase"),
                st.get("swing_fail_reason"),
            )
            if clave != prev_clave:
                eventos.append([round(ahora, 3), list(clave), st.get("position_deg"), st.get("pend_position_deg")])
                prev_clave = clave
            if st.get("mode") == 0 and ahora > 2.0:
                modo0_desde = modo0_desde if modo0_desde is not None else ahora
                if ahora - modo0_desde > 0.6:
                    break
            else:
                modo0_desde = None

    reg["duracion_s"] = round(time.time() - t0, 2)
    try:
        js("/daq?stop=1")
    except requests.RequestException:
        pass
    for _ in range(8):
        try:
            n, d = drenar(muestras)
            if d >= 0:
                dropped = d
            if n == 0:
                break
        except requests.RequestException:
            break

    parar()
    final = js("/state")
    reg["enlace_despues"] = medir_enlace()

    # -- Lo que latcheó el firmware. No se reconstruye desde las trazas. ------
    reg["firmware"] = {
        "swing_trans_reason": final.get("swing_trans_reason"),
        "swing_trans_alpha": final.get("swing_trans_alpha"),
        "swing_trans_vel": final.get("swing_trans_vel"),
        "swing_trans_energy": final.get("swing_trans_energy"),
        "swing_retry_count": final.get("swing_retry_count"),
        "swing_fail_reason": final.get("swing_fail_reason"),
        "swing_zero_ok": final.get("swing_zero_ok"),
        "swing_ceiling_hits": final.get("swing_ceiling_hits"),
        "lqr_alive_ms": final.get("lqr_alive_ms"),
        "ke_gain": final.get("ke_gain"),
        "pend_wraps": final.get("pend_wraps"),
        "loop_dt_max_us": final.get("loop_dt_max_us"),
        "loop_overruns": final.get("loop_overruns"),
        "safety_action": final.get("safety_action"),
        "safety_cuts": final.get("safety_cuts"),
        "safety_derates": final.get("safety_derates"),
        "v_bus": final.get("v_bus"),
        "i_ma": final.get("i_ma"),
        "mode_reject": final.get("mode_reject"),
    }
    # Deltas, no acumulados. Un contador monotonico leido solo al final mide la sesion,
    # no la tanda, y las tandas tardias parecerian peores por el solo hecho de ser tardias.
    reg["delta"] = {
        k: (final.get(k) - base_mono[k]) if isinstance(final.get(k), (int, float)) and isinstance(base_mono[k], (int, float)) else None
        for k in MONOTONICOS
    }
    # `lqr_alive_ms` NO se limpia entre intentos: sobrevive a la caida a proposito. Sin
    # esta compuerta se reporta el latch de la tanda anterior como si fuera nuevo, que es
    # exactamente lo que paso en las tres primeras tandas de esta sesion.
    if not final.get("swing_trans_reason"):
        reg["firmware"]["lqr_alive_ms"] = None
        reg["firmware"]["lqr_alive_ms_nota"] = "sin traspaso en este intento: el latch es de una tanda anterior"
    reg["daq"] = {"muestras": len(muestras), "dropped": dropped, "errores": errores}
    if rtts_state:
        ordenados = sorted(rtts_state)
        reg["enlace_durante"] = {
            "n": len(rtts_state),
            "mediana_ms": round(statistics.median(rtts_state), 2),
            "p95_ms": round(ordenados[int(0.95 * (len(ordenados) - 1))], 2),
            "max_ms": round(max(rtts_state), 2),
        }
    reg["eventos"] = eventos

    # -- Traza -----------------------------------------------------------------
    muestras.sort()
    nombre = f"{etiqueta}_ke{ke:g}_{indice}.csv"
    if muestras:
        tref = muestras[0][0]
        with (DATA / nombre).open("w", encoding="utf-8") as f:
            f.write("t_s,th_deg,al_deg,pwm,mode\n")
            for t_us, th, al, pwm, md, _fl in muestras:
                f.write(f"{(t_us - tref) / 1e6:.4f},{th:.3f},{al:.3f},{pwm},{md}\n")
        reg["csv"] = nombre
        dt = [(muestras[i][0] - muestras[i - 1][0]) for i in range(1, len(muestras))]
        span = (muestras[-1][0] - muestras[0][0]) / 1e6
        reg["daq"]["tasa_hz"] = round((len(muestras) - 1) / span, 1) if span > 0 else 0
        reg["daq"]["huecos"] = sum(1 for d in dt if d > 3000)
        reg["daq"]["dt_max_ms"] = round(max(dt) / 1000.0, 2) if dt else 0
        th_abs = [abs(m[1]) for m in muestras]
        reg["brazo"] = {
            "max_abs_deg": round(max(th_abs), 2),
            "n_sobre_95": sum(1 for v in th_abs if v > 95),
            "n_sobre_110": sum(1 for v in th_abs if v > 110),
        }
        al_abs = [abs(((m[2] + 180) % 360) - 180) for m in muestras]
        reg["pendulo"] = {"max_abs_alpha_deg": round(max(al_abs), 2)}
    return reg


def main() -> int:
    etiqueta = sys.argv[1]
    argv = sys.argv[2:]
    # `--set k=v` sobrescribe un fijo. Queda registrado en cada tanda (`reg["fijos"]`),
    # que es lo que permite saber despues contra que se midio cada traza.
    while argv and argv[0] == "--set":
        clave, _, valor = argv[1].partition("=")
        FIJOS[clave] = float(valor) if "." in valor else int(valor)
        argv = argv[2:]
    if argv and argv[0] == "--":
        argv = argv[1:]
    valores = [float(v) for v in argv]
    print(f"fijos: {FIJOS}", flush=True)
    salida = DATA / f"registro_{etiqueta}.jsonl"
    try:
        for i, ke in enumerate(valores, 1):
            print(f"\n=== tanda {i}/{len(valores)}  ke={ke:g} ===", flush=True)
            reg = tanda(etiqueta, ke, i)
            with salida.open("a", encoding="utf-8") as f:
                f.write(json.dumps(reg, ensure_ascii=False) + "\n")
            fw = reg.get("firmware", {})
            enl = reg.get("enlace_durante", {})
            print(
                f"  traspaso={fw.get('swing_trans_reason')} alpha={fw.get('swing_trans_alpha')} "
                f"E/E*={fw.get('swing_trans_energy')} alive={fw.get('lqr_alive_ms')}ms "
                f"fail={fw.get('swing_fail_reason')} ceil={fw.get('swing_ceiling_hits')} "
                f"dwrap={reg.get('delta', {}).get('pend_wraps')} "
                f"| brazo_max={reg.get('brazo', {}).get('max_abs_deg')} "
                f"| alpha_max={reg.get('pendulo', {}).get('max_abs_alpha_deg')} "
                f"| RTT={enl.get('mediana_ms')}/{enl.get('p95_ms')} ms "
                f"| dovr={reg.get('delta', {}).get('loop_overruns')} dt_max={fw.get('loop_dt_max_us')} "
                f"| v_bus={fw.get('v_bus')} | daq={reg.get('daq', {}).get('muestras')}",
                flush=True,
            )
            time.sleep(2.0)
    finally:
        parar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
