"""Mide Dp del pendulo AHORA y lo compara con el valor de banco fresco.

La pregunta. El 2026-08-05 el swing-up se degrado hasta dejar de entregar, con una firma de
mas friccion, y se recupero solo parcialmente con 40 min de reposo. Las ganancias del LQR se
disenan por CARE sobre un modelo cuyo `Dp` se midio UNA vez (2026-08-04, n=2, banco fresco)
y cuyo `Dr` nunca se midio. Si `Dp` cambia por un factor apreciable dentro de una sesion,
P4 y la degradacion del banco son el mismo problema: no habria un juego de ganancias fijas
que sirva.

El metodo. El pendulo es NO ACTUADO, asi que su decaimiento libre mide friccion pura, sin
acoplamiento electrico. La excitacion sale del propio homing: golpea el brazo contra los dos
topes y deja el pendulo oscilando —el efecto lateral que se descubrio en P22—, asi que no
hace falta ninguna mano. Despues se graba la caida libre a 500 Hz.

**EL BRAZO TIENE QUE ESTAR SUJETO, y el modo 0 NO lo sujeta.** Primer intento del
2026-08-05: con `m=0` el brazo se movio 13 grados durante la captura y el ajuste dio
lambda = -0,0006 con R2 = 0,02 — o sea, ninguna exponencial. La razon es que el sistema
tiene dos grados de libertad acoplados: si el brazo puede reaccionar, la energia del pendulo
se trasvasa al brazo y vuelve, y la envolvente deja de decaer. La referencia del 2026-08-04
se tomo explicitamente "con el brazo sujeto" a mano.
Aca la condicion de borde se impone por control: **modo 2 (PID de posicion) con consigna 0**.
El motor actua sobre el BRAZO, no sobre el pendulo, asi que el pendulo sigue siendo libre y
la medicion sigue siendo de friccion pura.

    A(t) = A0 * exp(-lambda * t)      Dp = 2 * Jp * lambda

**Que NO mide esto: `Dr`.** El brazo cuelga del motor, y con el L298N en modo 0 las dos
entradas quedan en bajo, o sea el motor en cortocircuito: frenado electrico. Un
decaimiento del brazo mediria `Dr` mas la disipacion por back-EMF, que son cosas distintas.
Para separarlas hay que abrir el circuito del motor. Se deja anotado como pendiente.

Referencia (2026-08-04, banco fresco, n=2, sueltas de 64 y 43 grados que coincidieron al
0,4%): lambda = 0,0283 1/s, Dp = 7,52e-6.

Uso:
    uv run python spindown_now.py
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from m4_daq import BROWNOUT_CUT_V, homing, wait_for_rest

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

# Jp del pendulo respecto del pivote, tal como lo usa `qube_dynamics.py`:
# Mp*Lp^2/3 con Mp=0,024 y Lp=0,129. Es el mismo con que se derivo Dp = 2*Jp*lambda el
# 2026-08-04. OJO: el firmware usa PEND_INERTIA = 7,75e-5, un factor 1,7 mas chico,
# ajustado para reproducir la frecuencia natural medida. Las dos cifras no coinciden y esa
# discrepancia es un problema aparte; aca se usa la del modelo para poder comparar peras
# con peras contra la referencia.
JP = 0.024 * 0.129**2 / 3.0

REF_LAMBDA = 0.0283
REF_DP = 7.52e-6

# Guardas para que la medicion se niegue a dar un numero que no puede sostener. Las tres
# salieron de fallos concretos del 2026-08-05, en este orden:
MIN_AMPLITUDE_DEG = 20.0  # por debajo manda la friccion seca; el homing solo dio 3,7-4,4
MIN_R2 = 0.85  # las capturas malas dieron 0,12 y 0,40, y aun asi imprimian un Dp
SETTLE_SKIP_S = 5.0  # el PID del brazo tarda ~5 s en asentarse tras el homing
MAX_ARM_SPAN_DEG = 4.0  # con el brazo suelto el acoplamiento de 2 GDL arruina la envolvente


def envelope_lambda(t: np.ndarray, a: np.ndarray) -> tuple[float, float, int]:
    """Ajusta A(t) = A0*exp(-lambda*t) sobre los picos de |alpha|. Devuelve (lambda, R2, n).

    **Se quita la media primero.** Fuera del modo 5 el firmware no re-establece el cero del
    pendulo (P22 se corrige solo al entrar a m5), asi que la senal puede venir con un offset
    grande: medido el 2026-08-05, el pendulo colgaba en reposo pero `alpha` iba de -29,2 a
    -22,5, o sea 26 grados de corrimiento sobre 3,4 de oscilacion real. Ajustar sobre
    `|alpha|` sin centrar hace que los picos esten dominados por el offset constante y la
    exponencial no vea el decaimiento: daba lambda negativa con R2 = 0,03.
    """
    a = a - np.median(a)
    absa = np.abs(a)
    # La referencia del 2026-08-04 se tomo con sueltas de 64 y 43 grados, y comparo esas
    # dos amplitudes para DEMOSTRAR que el amortiguamiento es viscoso. Por debajo de unos
    # 20 grados manda la friccion seca y el modelo A(t)=A0*exp(-lambda*t) no aplica: no es
    # que el ajuste salga impreciso, es que ajusta la curva equivocada.
    if absa.max() < MIN_AMPLITUDE_DEG:
        return float("nan"), float("nan"), -1
    # picos locales del valor absoluto = amplitud de cada semiciclo
    pk = np.flatnonzero((absa[1:-1] > absa[:-2]) & (absa[1:-1] >= absa[2:])) + 1
    # quedarse con los que valen: por encima del ruido de un conteo de encoder
    # Umbral relativo a la amplitud inicial, no absoluto: la excitacion que deja el homing
    # puede ser de pocos grados, y un umbral fijo de 3 deg se quedaria sin picos.
    pk = pk[absa[pk] > 0.15 * absa.max()]
    if pk.size < 6:
        return float("nan"), float("nan"), int(pk.size)
    tp, ap = t[pk], absa[pk]
    m, b = np.polyfit(tp, np.log(ap), 1)
    pred = m * tp + b
    r2 = 1.0 - ((np.log(ap) - pred) ** 2).sum() / ((np.log(ap) - np.log(ap).mean()) ** 2).sum()
    return -float(m), float(r2), int(pk.size)


def find_release(t: np.ndarray, a: np.ndarray) -> int:
    """Indice de la suelta: primera muestra que se aparta del reposo inicial.

    En modo manual la grabacion arranca ANTES de que se suelte el pendulo, para que la
    persona pueda leer el aviso sin apuro. El reposo previo sirve ademas de cero: es la
    posicion colgando real, que es mejor referencia que la mediana de toda la traza (el
    firmware no re-establece el cero fuera del modo 5, ver P22).
    """
    n0 = min(int(2.0 / (t[1] - t[0])), len(a) // 4)
    rest = float(np.median(a[:n0]))
    dev = np.abs(a - rest)
    thr = max(5.0, 4.0 * float(np.std(a[:n0])))
    idx = np.flatnonzero(dev > thr)
    return int(idx[0]) if idx.size else 0


def capture_manual(link: QubeLink, seconds: float, tag: str) -> tuple[np.ndarray, np.ndarray]:
    """Suelta a mano, con el brazo sujeto a mano y el MOTOR APAGADO.

    Es el protocolo del 2026-08-04, el unico que dio un resultado reproducible. El motor va
    en cero a proposito: hay una mano en el mecanismo.
    """
    link.send({"m": 0})
    time.sleep(0.2)
    return _record(link, seconds, tag)


def capture(link: QubeLink, seconds: float, tag: str) -> tuple[np.ndarray, np.ndarray]:
    wait_for_rest(link)
    print("  homing (deja el pendulo oscilando)...")
    homing(link)
    # Brazo sujeto por el PID en el centro. Sin esto la medicion no vale: ver el
    # encabezado. El pendulo sigue sin actuar.
    link.send({"m": 2, "s": 0})
    return _record(link, seconds, tag)


def _record(link: QubeLink, seconds: float, tag: str) -> tuple[np.ndarray, np.ndarray]:

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"spindown_{tag}.csv")
    rec.open()
    parts = []
    stream.start()
    try:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for c in stream.drain():
                rec.write(c)
                parts.append((c.t_s, c.al_deg, c.th_deg, c.pwm))
    finally:
        stream.stop()
        for c in stream.drain():
            rec.write(c)
            parts.append((c.t_s, c.al_deg, c.th_deg, c.pwm))
        rec.close()

    t = np.concatenate([p[0] for p in parts])
    al = np.concatenate([p[1] for p in parts])
    th = np.concatenate([p[2] for p in parts])
    pwm = np.concatenate([p[3] for p in parts])
    # El PID actua sobre el brazo, asi que aca SI hay pwm; lo que importa es que el brazo
    # no se mueva. Si se mueve mas de unos pocos grados, el acoplamiento de dos grados de
    # libertad arruina el ajuste igual que con `m=0`.
    span = float(th.max() - th.min())
    print(f"  brazo: theta en [{th.min():.1f}, {th.max():.1f}] deg  (excursion {span:.1f})"
          f"  |pwm| max {np.abs(pwm).max():.0f}")
    if span > 4.0:
        print(f"  AVISO: el brazo se movio {span:.1f} deg. El PID no lo esta sujetando y el")
        print("  ajuste no va a valer — es el mismo fallo que con m=0.")
    # alpha acotado a [-180,180]; colgando = 0 tras el re-cero del firmware
    return t - t[0], (al + 180.0) % 360.0 - 180.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--seconds", type=float, default=25.0)
    ap.add_argument("--manual", action="store_true",
                    help="suelta a mano con el brazo sujeto a mano y el motor APAGADO "
                         "(protocolo del 2026-08-04). Sin homing.")
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    v = float(d.get("v_bus") or 0.0)
    print(f"Placa: mode={d.get('mode')} v_bus={v:.2f}")
    if v < BROWNOUT_CUT_V:
        raise SystemExit(f"v_bus = {v:.2f} V: el homing no va a mover el brazo.")

    DATA.mkdir(parents=True, exist_ok=True)
    lams = []
    try:
        for i in range(1, args.reps + 1):
            print(f"\n--- captura {i}/{args.reps} ---")
            if args.manual:
                print("  grabando — SOLTAR EL PENDULO CUANDO QUIERAS")
                t, a = capture_manual(link, args.seconds, f"man_{i}")
                k = find_release(t, a)
                rest = float(np.median(a[: max(k // 2, 10)]))
                print(f"  suelta detectada en t = {t[k]:.1f} s   reposo previo = {rest:.1f} deg")
                t, a = t[k:] - t[k], a[k:] - rest
            else:
                t, a = capture(link, args.seconds, f"deg_{i}")
                # Descartar el asentamiento del PID del brazo tras el homing.
                keep = t >= SETTLE_SKIP_S
                t, a = t[keep] - SETTLE_SKIP_S, a[keep]
            amp = float(np.abs(a - np.median(a)).max())
            lam, r2, n = envelope_lambda(t, a)
            print(f"  amplitud real (centrada) {amp:.1f} deg")
            if n == -1:
                print(f"  DESCARTADA: {amp:.1f} deg < {MIN_AMPLITUDE_DEG:.0f} requeridos. Por debajo")
                print("  de eso manda la friccion seca y el modelo viscoso no aplica.")
                continue
            if not np.isfinite(lam) or n < 6:
                print(f"  DESCARTADA: picos insuficientes ({n}).")
                continue
            if r2 < MIN_R2:
                print(f"  DESCARTADA: R2 = {r2:.2f} < {MIN_R2}. La envolvente no es una "
                      "exponencial; no se reporta lambda.")
                continue
            dp = 2.0 * JP * lam
            lams.append(lam)
            print(f"  picos usados {n}   lambda = {lam:.4f} 1/s   R2 = {r2:.3f}   "
                  f"->  Dp = {dp:.3e}")
    finally:
        link.send({"m": 0})

    if not lams:
        print("\n" + "=" * 62)
        print("  SIN MEDICION. No se reporta ningun Dp.")
        print("=" * 62)
        print("\n  La excitacion que deja el homing es de unos 4 grados, y la referencia del")
        print("  2026-08-04 se tomo con sueltas de 64 y 43. Hace falta una suelta grande:")
        print("    1. Sujetar el brazo a mano, firme, en el centro.")
        print("    2. Levantar el pendulo unos 45-60 grados y soltarlo sin impulso.")
        print("    3. Correr este script; graba y ajusta solo.")
        print("  Es el mismo protocolo del 2026-08-04, que es el unico que dio un numero")
        print("  reproducible (dos sueltas coincidiendo al 0,4%).")
        return
    lam = float(np.median(lams))
    dp = 2.0 * JP * lam
    print(f"\n{'=' * 62}")
    print(f"  AHORA (banco cansado, n={len(lams)}):  lambda = {lam:.4f}   Dp = {dp:.3e}")
    print(f"  REFERENCIA (2026-08-04, fresco):     lambda = {REF_LAMBDA:.4f}   Dp = {REF_DP:.3e}")
    print(f"  factor = {dp / REF_DP:.2f}x")
    print(f"{'=' * 62}")
    if dp / REF_DP > 1.5:
        print("\n  La friccion del pendulo SUBIO de forma apreciable. Sostiene la hipotesis")
        print("  de que P4 y la degradacion del banco son el mismo problema: el modelo con")
        print("  que se disenan las ganancias usa un Dp que la planta no tiene hoy.")
    elif dp / REF_DP < 0.67:
        print("\n  La friccion BAJO. No es lo esperado; revisar la captura antes de creerlo.")
    else:
        print("\n  Dp NO cambio de forma apreciable. La hipotesis NO se sostiene: la")
        print("  degradacion del swing-up viene de otro lado (el brazo, que no se mide aca).")


if __name__ == "__main__":
    main()
