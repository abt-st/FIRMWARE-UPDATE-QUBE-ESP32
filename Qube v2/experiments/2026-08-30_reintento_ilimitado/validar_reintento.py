"""Valida que el modo 5 no se rinda solo: reintenta hasta que llegue un comando.

Qué se está midiendo, exactamente: **el modo 5 no puede terminar en modo 0 sin que
este script haya pedido el cambio**. Nada más. No es una campaña de tasa de éxito del
swing-up ni un barrido de parámetros; la pregunta es de máquina de estados.

Cómo falla la validación (esto es lo que hay que poder distinguir, P24):
  · `mode` cae a 0 y el script no mandó nada  -> FALLA, el modo se perdió solo.
  · `swing_retry_count` se estanca en el techo -> FALLA, quedó un presupuesto finito.
  · `swing_retry_max >= 0`                     -> FALLA, el firmware es anterior a v1.66.0
                                                  o alguien dejó un `?rtn=` puesto.
El único final aceptable distinto de «lo paré yo» es `swing_fail_reason = 5`
(recentrado calado), que es la falla mecánica que sigue deteniendo el banco a propósito.

    python validar_reintento.py [minutos]     # def. 5
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

URL = "http://192.168.4.1"
AQUI = Path(__file__).parent
PERIODO_S = 0.2  # 5 Hz: el reintento dura segundos, no hace falta más

FALLAS = {
    0: "ninguna",
    1: "el pendulo se cayo",
    2: "el pendulo dio una vuelta",
    3: "el brazo llego al tope",
    4: "nunca llego a la vertical",
    5: "el recentrado no pudo volver",
    6: "el pendulo no se aquieto para el re-cero",
}


def estado(timeout: float = 4.0) -> dict | None:
    try:
        return requests.get(URL + "/state", timeout=timeout).json()
    except (requests.RequestException, ValueError):
        return None


def cmd(q: str) -> bool:
    try:
        requests.get(f"{URL}/cmd?{q}", timeout=4)
        return True
    except requests.RequestException:
        return False


def pedir_modo(m: int, espera_s: float = 2.0) -> bool:
    """Pide el modo y COMPRUEBA que entró.

    El 2026-08-30 esta validación se comió un minuto de banco mandando `/cmd?m3` en vez
    de `/cmd?m=3`: sin `=` no hay parámetro, el firmware responde 200 y no hace nada. Un
    comando que se da por bueno porque el HTTP no falló no es un comando dado.
    """
    cmd(f"m={m}")
    t0 = time.time()
    while time.time() - t0 < espera_s:
        s = estado()
        # El homing (3) puede terminar solo antes de que lo veamos; `homing_ok` lo delata.
        if s and (s["mode"] == m or (m == 3 and s["homing_ok"])):
            return True
        time.sleep(0.2)
    s = estado()
    print(f"  el modo {m} NO entró (mode={s['mode'] if s else '?'}, mode_reject={s.get('mode_reject') if s else '?'})")
    return False


def veredicto(muestras: list[dict], pedidos: list[float]) -> tuple[bool, list[str]]:
    """Separado de la adquisición para poder probarlo contra trazas que DEBEN fallar.

    Cada regla devuelve su propio renglón: un veredicto de una sola línea no dice cuál
    de las tres condiciones se rompió, y son fallas distintas con arreglos distintos.
    """
    problemas: list[str] = []
    if not muestras:
        return False, ["no se capturó ninguna muestra"]

    techos = {m["swing_retry_max"] for m in muestras}
    if any(t >= 0 for t in techos):
        problemas.append(f"swing_retry_max no es ilimitado en toda la tanda: {sorted(techos)}")

    # Caída a modo 0 no pedida. Ventana de 1,5 s tras cada comando: el cambio de modo
    # no es instantáneo y el muestreo a 5 Hz puede ver el 0 intermedio de un m3->m5.
    for i, m in enumerate(muestras[1:], 1):
        prev = muestras[i - 1]["mode"]
        if prev != 0 and m["mode"] == 0 and not any(abs(m["t"] - tp) < 1.5 for tp in pedidos):
            razon = m.get("swing_fail_reason", 0)
            if razon == 5:
                continue  # falla mecánica: detener es lo correcto
            problemas.append(
                f"t={m['t']:.1f}s: el modo cayó {prev}->0 sin comando (motivo={razon} · {FALLAS.get(razon, '?')})"
            )

    reintentos = max(m["swing_retry_count"] for m in muestras)
    fallas = {m.get("swing_fail_reason", 0) for m in muestras} - {0}
    if reintentos == 0 and not fallas:
        problemas.append(
            "no hubo ni un solo intento fallido: la tanda no prueba nada (el reintento nunca llegó a ejercitarse)"
        )
    return not problemas, problemas


def autoprueba() -> None:
    """El criterio contra un caso que DEBE fallar y otro que DEBE pasar.

    Sin esto la validación no vale: un veredicto que devuelve OK pase lo que pase se ve
    exactamente igual que uno correcto sobre un banco sano.
    """
    malo = [
        {"t": 0.0, "mode": 5, "swing_retry_count": 0, "swing_retry_max": -1, "swing_fail_reason": 0},
        {"t": 8.0, "mode": 5, "swing_retry_count": 3, "swing_retry_max": -1, "swing_fail_reason": 1},
        {"t": 9.0, "mode": 0, "swing_retry_count": 3, "swing_retry_max": -1, "swing_fail_reason": 1},
    ]
    ok, _ = veredicto(malo, pedidos=[0.0])
    assert not ok, "el criterio dio OK sobre una traza que pierde el modo"

    finito = [dict(m, mode=5, swing_retry_max=3) for m in malo[:2]]
    ok, _ = veredicto(finito, pedidos=[0.0])
    assert not ok, "el criterio dio OK con un presupuesto finito"

    bueno = [
        {"t": 0.0, "mode": 5, "swing_retry_count": 0, "swing_retry_max": -1, "swing_fail_reason": 0},
        {"t": 30.0, "mode": 5, "swing_retry_count": 5, "swing_retry_max": -1, "swing_fail_reason": 1},
        {"t": 60.0, "mode": 4, "swing_retry_count": 5, "swing_retry_max": -1, "swing_fail_reason": 1},
    ]
    ok, prob = veredicto(bueno, pedidos=[0.0])
    assert ok, f"el criterio rechazó una traza sana: {prob}"

    quieto = [
        {"t": 0.0, "mode": 5, "swing_retry_count": 0, "swing_retry_max": -1, "swing_fail_reason": 0},
        {"t": 60.0, "mode": 5, "swing_retry_count": 0, "swing_retry_max": -1, "swing_fail_reason": 0},
    ]
    ok, _ = veredicto(quieto, pedidos=[0.0])
    assert not ok, "una tanda sin ningún fallo no puede declararse validada"
    print("autoprueba del criterio: OK (rechaza los 3 casos malos, acepta el sano)")


def main() -> int:
    autoprueba()
    minutos = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0

    st = estado()
    if st is None:
        print("la placa no responde en " + URL)
        return 1
    print(
        f"placa: mode={st['mode']} v_bus={st['v_bus']:.1f} homing_ok={st['homing_ok']} "
        f"retry_max={st['swing_retry_max']}"
    )
    if st["swing_retry_max"] >= 0:
        print("AVISO: el presupuesto NO es ilimitado; se pone en -1 antes de empezar")
        cmd("rtn=-1")

    pedidos: list[float] = []
    t0 = time.time()

    if not st["homing_ok"]:
        print("sin homing: se pide m3 (el brazo va a buscar los dos topes)")
        pedidos.append(time.time() - t0)
        if not pedir_modo(3):
            return 1
        while time.time() - t0 < 90:
            time.sleep(1.0)
            s = estado()
            if s and s["homing_ok"] and s["mode"] != 3:
                break
            if s and s["mode"] != 3 and not s["homing_ok"]:
                print(
                    f"  el homing salió del modo 3 sin lograrlo (fase={s['homing_phase']}, "
                    f"homing_fail={s.get('homing_fail')})"
                )
                break
            if s:
                print(f"  homing: {s['homing_phase']}")
        s = estado()
        if not (s and s["homing_ok"]):
            print("el homing no terminó bien; no se sigue")
            return 1
        print("homing OK")

    print(f"m5 durante {minutos:.1f} min. Ctrl-C para cortar (deja el banco en modo 0).")
    pedidos.append(time.time() - t0)
    if not pedir_modo(5):
        return 1

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    traza = AQUI / "data" / f"reintento_{sello}.jsonl"
    muestras: list[dict] = []
    prev_mode, prev_retry, prev_fail = None, None, None

    try:
        with traza.open("w", encoding="utf-8") as fh:
            while time.time() - t0 < minutos * 60:
                s = estado()
                if s is None:
                    time.sleep(PERIODO_S)
                    continue
                m = {
                    "t": round(time.time() - t0, 3),
                    "mode": s["mode"],
                    "swing_retry_count": s["swing_retry_count"],
                    "swing_retry_max": s["swing_retry_max"],
                    "swing_fail_reason": s.get("swing_fail_reason", 0),
                    "swing_recenter_phase": s.get("swing_recenter_phase", 0),
                    "swing_zero_phase": s.get("swing_zero_phase", 0),
                    "pend_position_deg": s.get("pend_position_deg"),
                    "position_deg": s.get("position_deg"),
                    "lqr_alive_ms": s.get("lqr_alive_ms"),
                }
                fh.write(json.dumps(m) + "\n")
                muestras.append(m)
                if (m["mode"], m["swing_retry_count"], m["swing_fail_reason"]) != (prev_mode, prev_retry, prev_fail):
                    print(
                        f"  t={m['t']:6.1f}s  modo={m['mode']}  reintentos={m['swing_retry_count']}"
                        f"  motivo={m['swing_fail_reason']} ({FALLAS.get(m['swing_fail_reason'], '?')})"
                    )
                    prev_mode, prev_retry, prev_fail = (m["mode"], m["swing_retry_count"], m["swing_fail_reason"])
                time.sleep(PERIODO_S)
    except KeyboardInterrupt:
        print("\ncortado a mano")
    finally:
        cmd("m=0")

    ok, problemas = veredicto(muestras, pedidos)
    print(f"\ntraza: {traza}")
    print(f"muestras: {len(muestras)}  ·  reintentos máx: {max((m['swing_retry_count'] for m in muestras), default=0)}")
    if ok:
        print("VALIDADO: el modo 5 nunca se perdió solo.")
    else:
        print("NO VALIDADO:")
        for p in problemas:
            print("  - " + p)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
