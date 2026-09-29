"""Por qué el brazo se va al tope mientras el péndulo se sostiene, a 500 Hz.

El sondeo de `/state` de `campana.py` corre a ~6 Hz efectivos: un balanceo de 1,3 s deja
ocho muestras, y con ocho muestras no se puede decir si alpha se sienta en un valor distinto
de cero ni a qué ritmo deriva el brazo. Esta captura usa `/daq`, que muestrea **a la tasa
del lazo** en el buffer del ESP32 y entrega bloques binarios: 500 Hz de resolución con dos
peticiones por segundo en vez de seis, o sea también menos atrasos del lazo inyectados
(medido: cada petición HTTP cuesta exactamente un overrun).

La hipótesis que viene a probar, y qué la distinguiría:

  **Si el cero de alpha está corrido** respecto del equilibrio real, el LQR sostiene el
  péndulo INCLINADO un ángulo fijo delta. Un péndulo inclinado necesita aceleración
  horizontal continua para quedarse así, y eso es exactamente una deriva monótona del
  brazo hasta el tope. La firma es: alpha se sienta en un delta ≠ 0 repetible **con el mismo
  signo entre episodios**, y el signo de la deriva del brazo lo acompaña.

  **Si en cambio el lazo es marginalmente estable**, alpha oscila alrededor de cero con
  amplitud creciente y la deriva del brazo no tiene signo preferido.

Los dos casos se arreglan distinto —un trim de `op` contra re-sintonizar las ganancias—
así que distinguirlos es lo que decide la condición siguiente.

    python diagnostico_m4.py [segundos]      # def. 150
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from qube_daq.client import Acquisition, DaqClient

URL = "http://192.168.4.1"
DATOS = Path(__file__).parent / "data"
CATCH_MS = 400  # `lqr_catch_ms` del firmware: durante el catch el LQR no corre


def cmd(q: str) -> bool:
    try:
        return requests.get(f"{URL}/cmd?{q}", timeout=4).status_code == 200
    except requests.RequestException:
        return False


def estado() -> dict | None:
    try:
        return requests.get(URL + "/state", timeout=4).json()
    except (requests.RequestException, ValueError):
        return None


def alpha_deg(al_deg: np.ndarray) -> np.ndarray:
    """Distancia con signo a la vertical de arriba. 0 = vertical, ± = a cada lado."""
    a = (al_deg - 180.0) % 360.0
    a = np.where(a > 180.0, a - 360.0, a)
    return -a


def episodios_m4(acq: Acquisition) -> list[dict]:
    """Cada estadía en modo 4, con lo que hicieron alpha y el brazo dentro."""
    m4 = acq.mode == 4
    if not m4.any():
        return []
    bordes = np.diff(m4.astype(np.int8))
    inicios = list(np.flatnonzero(bordes == 1) + 1)
    finales = list(np.flatnonzero(bordes == -1) + 1)
    if m4[0]:
        inicios.insert(0, 0)
    if m4[-1]:
        finales.append(len(m4))

    al = alpha_deg(acq.al_deg)
    eps: list[dict] = []
    for i, j in zip(inicios, finales, strict=True):
        dur = float(acq.t_s[j - 1] - acq.t_s[i]) * 1000.0
        if dur < 300.0:
            continue
        # El catch no es balanceo: durante esos 400 ms el LQR no corre.
        t0 = acq.t_s[i] + CATCH_MS / 1000.0
        est = (acq.t_s[i:j] >= t0) & (np.abs(al[i:j]) < 40.0)
        if est.sum() < 50:  # menos de 0,1 s arriba: no dice nada
            continue
        a_est = al[i:j][est]
        th_est = acq.th_deg[i:j][est]
        t_est = acq.t_s[i:j][est]
        pwm_est = acq.pwm[i:j][est]
        span = float(t_est[-1] - t_est[0])
        eps.append(
            {
                "t_ini": float(acq.t_s[i]),
                "dur_ms": dur,
                "n": int(est.sum()),
                "alpha_mediana": float(np.median(a_est)),
                "alpha_desv": float(np.std(a_est)),
                "brazo_ini": float(th_est[0]),
                "brazo_fin": float(th_est[-1]),
                "deriva_deg_s": float((th_est[-1] - th_est[0]) / span) if span > 0 else 0.0,
                "pwm_saturado_pct": float(100.0 * np.mean(np.abs(pwm_est) >= 69)),
                "pwm_medio": float(np.mean(pwm_est)),
            }
        )
    return eps


def main() -> int:
    segundos = float(sys.argv[1]) if len(sys.argv) > 1 else 150.0

    st = estado()
    if st is None:
        print(f"la placa no responde en {URL}")
        return 1
    if not st["ina_ok"]:
        print("INA219 caido: no se energiza el motor")
        return 1
    if not st["homing_ok"]:
        print("sin homing: pedir `m3` antes de correr esto")
        return 1
    print(f"placa: v_bus={st['v_bus']:.2f} V  lqr_catch_ms={st['lqr_catch_ms']}  lqr_pwm_max={st['lqr_pwm_max']}")

    # Defaults de fabrica, que es la condicion sobre la que se hizo todo el diagnostico.
    for q in (
        "lc=400",
        "lpm=70",
        "cg=0",
        "tn=155",
        "sp=60",
        "ke=-1",
        "lqr1=2.0",
        "lqr4=9.0",
        "pc=0.0",
        "pr=70.0",
        "rtn=-1",
        "rj=1",
    ):
        cmd(q)
        time.sleep(0.05)

    cmd("m=5")
    time.sleep(1.0)
    if (estado() or {}).get("mode") != 5:
        print("el modo 5 no entro")
        return 1

    print(f"capturando {segundos:.0f} s a 500 Hz...")
    with DaqClient(ip=URL.replace("http://", "")) as daq:
        acq = daq.record(seconds=segundos, decim=1, poll_interval=0.5)
    cmd("m=0")

    if acq.n == 0:
        print("la captura salio vacia")
        return 1
    print(f"{acq.n} muestras · {acq.duration_s:.1f} s · {acq.rate_hz:.0f} Hz efectivos · perdidas={acq.dropped}")
    if acq.dropped:
        print("⚠ hubo muestras perdidas: la continuidad de la serie no esta garantizada")

    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    np.savez_compressed(
        DATOS / f"daq_m4_{sello}.npz",
        t_s=acq.t_s,
        th_deg=acq.th_deg,
        al_deg=acq.al_deg,
        pwm=acq.pwm,
        mode=acq.mode,
    )

    eps = episodios_m4(acq)
    if not eps:
        print("ningun episodio de modo 4 utilizable en la captura")
        return 1

    print(f"\n{len(eps)} episodios de modo 4 con el pendulo arriba:\n")
    print(
        f"{'dur_ms':>7s} {'alpha_med':>10s} {'alpha_sd':>9s} {'brazo_ini':>10s} {'deriva':>9s} {'pwm_sat':>8s} {'pwm_med':>8s}"
    )
    for e in eps:
        print(
            f"{e['dur_ms']:7.0f} {e['alpha_mediana']:+10.2f} {e['alpha_desv']:9.2f} "
            f"{e['brazo_ini']:+10.1f} {e['deriva_deg_s']:+9.1f} {e['pwm_saturado_pct']:7.0f}% {e['pwm_medio']:+8.1f}"
        )

    alphas = [e["alpha_mediana"] for e in eps]
    derivas = [e["deriva_deg_s"] for e in eps]
    mismo_signo_a = sum(1 for a in alphas if a > 0)
    mismo_signo_d = sum(1 for d in derivas if d > 0)
    print(f"\nalpha mediano entre episodios: {statistics.median(alphas):+.2f} deg")
    print(
        f"  positivos {mismo_signo_a}/{len(alphas)}   ·   dispersion entre episodios {statistics.pstdev(alphas):.2f} deg"
    )
    print(f"deriva del brazo: {statistics.median(derivas):+.1f} deg/s   ·   positivas {mismo_signo_d}/{len(derivas)}")
    print(f"PWM saturado: {statistics.median(e['pwm_saturado_pct'] for e in eps):.0f} % del tiempo (mediana)")

    # El veredicto se dice explicito, con la condicion que lo decide a la vista.
    sesgado = abs(statistics.median(alphas)) > 2.0 and max(mismo_signo_a, len(alphas) - mismo_signo_a) >= 0.8 * len(
        alphas
    )
    print()
    if sesgado:
        print(f"SESGO DE CERO: alpha se sienta en {statistics.median(alphas):+.2f} deg con el mismo signo en")
        print(
            f"  {max(mismo_signo_a, len(alphas) - mismo_signo_a)}/{len(alphas)} episodios. El LQR sostiene el pendulo INCLINADO, y eso"
        )
        print("  exige aceleracion continua del brazo. Se corrige con un trim de `op`.")
    else:
        print(f"SIN SESGO CLARO: alpha mediano {statistics.median(alphas):+.2f} deg,")
        print(f"  {mismo_signo_a}/{len(alphas)} positivos. La deriva no se explica por un cero corrido;")
        print("  hay que mirar la sintonia y la saturacion.")

    (DATOS / f"daq_m4_{sello}_episodios.json").write_text(json.dumps(eps, indent=2), encoding="utf-8")
    print(f"\ncaptura: daq_m4_{sello}.npz  ·  episodios: daq_m4_{sello}_episodios.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
