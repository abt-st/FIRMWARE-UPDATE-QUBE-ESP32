"""Lee el signo de realimentacion del LQR en vez de deducirlo. Motor a cero.

Que resuelve. H7 dice que `velTheta_ctrl` es -theta_dot mientras `theta` entra sin invertir,
o sea que K3 anti-amortigua el brazo. Es lectura de codigo (`:3553-3554` contra `:3546`), y
razonar asi ya fallo tres veces en este proyecto. Se intento confirmarlo por regresion sobre
las trazas del 2026-08-05 y NO se pudo: con la salida saturada el 98% del tiempo quedan 207
muestras utiles, sesgadas a los cruces por cero, y el ajuste da R2 = 0.28 con el signo de
alpha invertido. Desde v1.58.10 el firmware publica lo que la ley consume de verdad.

Como se lee. Mueve el brazo A MANO en un sentido y mira las dos columnas:

    theta subiendo  +  lqr_vel_theta POSITIVA  ->  velTheta_ctrl = +theta_dot  (H7 FALSA)
    theta subiendo  +  lqr_vel_theta NEGATIVA  ->  velTheta_ctrl = -theta_dot  (H7 CIERTA)

Lo mismo con el pendulo para `lqr_vel_alpha` contra `lqr_alpha_err`.

POR QUE ES SEGURO. Las nueve ganancias van a cero, asi que `u = 0`. El centering se
desactiva con el periodo de gracia (`cg=1`) durante los primeros 2 s de cada entrada al
modo 4, y el script re-entra al modo cada 2 s para renovarlo. Ademas `lpm=20`, el minimo:
aunque el bloque de limite de servo fuerce centrado mas alla de +-70 grados, el tope es 20
en vez de 70.

**Manten el brazo dentro de +-60 grados** y el paro (`?x=1`) a mano igual.

Uso:
    uv run python sign_probe.py            # 60 s de lectura
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m4_daq import BROWNOUT_CUT_V

from qube_app.link import QubeLink

ZERO_GAINS = {
    "lqr1": 0, "lqr2": 0, "lqr3": 0, "lqr4": 0,
    "lqr2n": 0, "lqr4n": 0, "lqr2vn": 0, "lqr4vn": 0,
    "lqrdamp": 0,
}
DEFAULT_GAINS = {
    "lqr1": 2.0, "lqr2": 22, "lqr3": 1.5, "lqr4": 9,
    "lqr2n": 30, "lqr4n": 15, "lqr2vn": 55, "lqr4vn": 20,
    "lqrdamp": 0,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--seconds", type=float, default=60.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    if d.get("lqr_vel_theta") is None:
        raise SystemExit("Firmware sin `lqr_vel_theta`: hay que flashear >= v1.58.10.")
    v = float(d.get("v_bus") or 0.0)
    print(f"Placa: mode={d.get('mode')} v_bus={v:.2f} lqr_vel_theta={d.get('lqr_vel_theta')}")
    if v < BROWNOUT_CUT_V:
        print("AVISO: v_bus bajo. El motor no se movera igual — y aca eso no molesta,")
        print("porque este test NO necesita motor: solo lee lo que calcula la ley.")

    print("\nGanancias a CERO y lpm=20. El motor no deberia moverse.")
    link.send({**ZERO_GAINS, "lpm": 20, "cg": 1, "lc": 0})
    time.sleep(0.2)

    print("MOVE EL BRAZO A MANO, despacio, dentro de +-60 grados.\n")
    print(f"{'t':>5} {'theta':>8} {'vel_theta':>10} {'alpha_err':>10} {'vel_alpha':>10} {'pwm':>5}")
    t0 = time.perf_counter()
    last_mode = 0.0
    try:
        while time.perf_counter() - t0 < args.seconds:
            # Re-entrar al modo 4 cada 2 s renueva el periodo de gracia del centering.
            if time.perf_counter() - last_mode > 1.8:
                link.send({"m": 4})
                last_mode = time.perf_counter()
            s = link.state()
            print(f"{time.perf_counter() - t0:>5.1f} {float(s.get('position_deg', 0)):>8.2f} "
                  f"{float(s.get('lqr_vel_theta', 0)):>10.2f} "
                  f"{float(s.get('lqr_alpha_err', 0)):>10.2f} "
                  f"{float(s.get('lqr_vel_alpha', 0)):>10.2f} "
                  f"{s.get('pwm'):>5}")
            time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        link.send({"m": 0})
        link.send({**DEFAULT_GAINS, "lpm": 70, "cg": 0, "lc": 400})
        print("\nmodo 0 y ganancias restauradas a los defaults compilados.")

    print("\nLectura:")
    print("  theta CRECIENDO con vel_theta NEGATIVA  -> velTheta_ctrl = -theta_dot, H7 CIERTA")
    print("  theta CRECIENDO con vel_theta POSITIVA  -> H7 FALSA, K3 ya amortigua bien")


if __name__ == "__main__":
    main()
