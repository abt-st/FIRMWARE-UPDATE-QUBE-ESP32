"""P12 — Cuanto arrastra el brazo despues de cortar el motor, en funcion del PWM.

Necesario para elegir SERVO_HARD_LIMIT_DEG con dato y no con suposicion: el puente
queda en CORTE (no en freno) al cortar, asi que el brazo sigue por inercia. Si el
limite se pone a X, el brazo puede terminar en X + arrastre, y el tope mecanico esta
en 134.8 deg.

Protocolo: desde el centro (homing), pulso de PWM durante un tiempo fijo, corte, y se
compara la posicion en el instante del corte contra el reposo final.

El pulso se dimensiona para NO cruzar el limite blando durante el ensayo — si saltara
el safeStop, el corte lo daria el firmware y no se sabria en que posicion ocurrio.
"""

from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

import requests

DATA = Path(__file__).resolve().parent.parent / "data"
IP = "192.168.100.50"
S = requests.Session()
S.headers.update({"Connection": "keep-alive"})


def cmd(**p):
    return S.get(f"http://{IP}/cmd", params=p, timeout=3).json()


def state():
    for i in range(3):
        try:
            r = S.get(f"http://{IP}/state", timeout=2)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if i == 2:
                raise
            time.sleep(0.15)


def homing(timeout=30.0):
    cmd(m=3)
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        d = state()
        if d.get("homing_phase") == "DONE":
            return d
        if d.get("homing_phase") == "FAIL":
            raise RuntimeError(f"homing FAIL {d.get('homing_fail')}")
        time.sleep(0.2)
    raise RuntimeError("homing timeout")


def one(pwm: int, pulse_s: float) -> dict | None:
    homing()
    cmd(m=1)
    cmd(p=pwm)
    t0 = time.monotonic()
    last = None
    while time.monotonic() - t0 < pulse_s:
        last = state()
        time.sleep(0.03)
    cmd(m=0)
    pos_corte = float(last["position_deg"]) if last else None
    mode_corte = last.get("mode") if last else None
    time.sleep(2.5)                      # dejar asentar
    pos_final = float(state()["position_deg"])
    if mode_corte != 1:
        # El firmware ya habia cortado por su cuenta: el ensayo no mide lo que dice.
        return {"pwm": pwm, "descartado": "safeStop durante el pulso"}
    return {
        "pwm": pwm,
        "pos_corte_deg": round(pos_corte, 2),
        "pos_final_deg": round(pos_final, 2),
        "arrastre_deg": round(abs(pos_final - pos_corte), 2),
    }


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    out = []
    # Pulsos cortos para no acercarse al limite blando durante la medicion.
    for pwm, pulse in [(40, 0.5), (50, 0.5), (60, 0.45), (70, 0.4), (90, 0.35)]:
        for rep in (1, 2):
            print(f"--- PWM {pwm}, pulso {pulse}s, rep {rep} ---")
            try:
                r = one(pwm, pulse)
            except Exception as exc:  # noqa: BLE001
                print(f"    ERROR: {exc}")
                cmd(m=0)
                continue
            r["rep"] = rep
            print(f"    {json.dumps(r)}")
            out.append(r)
    cmd(m=0)
    (DATA / "coast.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print("\n=== arrastre tras el corte ===")
    for pwm in sorted({r["pwm"] for r in out}):
        g = [r["arrastre_deg"] for r in out if r["pwm"] == pwm and "arrastre_deg" in r]
        if g:
            print(f"  PWM {pwm:>3}: {statistics.mean(g):6.2f} deg   (n={len(g)}, rango {min(g):.2f}–{max(g):.2f})")


if __name__ == "__main__":
    main()
