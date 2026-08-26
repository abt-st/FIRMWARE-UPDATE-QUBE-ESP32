"""N sueltas seguidas del péndulo con el brazo RETENIDO, en una sola traza.

Por qué así y no con una suelta por corrida:

- **El brazo retenido (`m2 s=0`) es la única medición limpia.** Con el brazo libre el
  sistema es de dos grados de libertad y la frecuencia que se mide no es la del péndulo:
  la caída libre de esta sesión con brazo libre da ~2,5 Hz en amplitudes chicas, que es
  un modo del conjunto, no `f_n`.
- **Sólo sirve el PRIMER medio ciclo de cada suelta.** [P24]: el pivote tiene fricción
  seca dominante y el péndulo cae de 48° a 6° en 0,8 s. Con fricción de Coulomb el
  medio período *crece* al bajar la amplitud —la adherencia retiene el péndulo cerca del
  punto de retorno— así que los medios ciclos tardíos están contaminados y sesgan `f_n`
  hacia abajo. Medido en esta sesión: 1,49 / 1,29 / 0,92 Hz en medios ciclos sucesivos
  de la MISMA suelta, que para un péndulo limpio deberían ser el mismo número.
- Por eso hacen falta **muchas sueltas desde amplitud alta**, no muchos ciclos de una.

Uso:  python caida_multiple.py <salida.csv> [n_sueltas]
"""

from __future__ import annotations

import json
import struct
import sys
import time
from pathlib import Path

import requests

URL = "http://192.168.4.1"
MAGIC = 0x51414451
DATA = Path(__file__).parent / "data"
DATA.mkdir(parents=True, exist_ok=True)

ses = requests.Session()
ses.headers.update({"Connection": "keep-alive"})


def js(path: str, timeout: float = 6.0) -> dict:
    r = ses.get(URL + path, timeout=timeout)
    r.raise_for_status()
    return r.json()


def drenar(acc: list) -> int:
    try:
        buf = ses.get(URL + "/daq/read", timeout=5).content
    except requests.RequestException:
        return 0
    if len(buf) < 16:
        return 0
    magic, _pv, _sb, n, _dr, _tn = struct.unpack_from("<IBBHII", buf, 0)
    if magic != MAGIC:
        return 0
    for i in range(n):
        acc.append(struct.unpack_from("<IffhBB", buf, 16 + 16 * i)[:5])
    return n


def esperar_quieto(timeout_s: float = 12.0, banda_deg: float = 0.6, quieto_s: float = 1.5) -> bool:
    """Espera a que el pendulo deje de moverse. Devuelve False si no lo logra.

    La fase de re-cero del modo 5 (P22, `sz=1`) exige quietud y aborta si no la
    consigue; arrancar un `m5` con el pendulo todavia oscilando deja el cero de alpha
    donde caiga y toda la traza siguiente se mide contra una referencia que no es la
    vertical.
    """
    t0 = time.time()
    ventana: list[float] = []
    while time.time() - t0 < timeout_s:
        try:
            a = js("/state", timeout=4)["pend_position_deg"]
        except (requests.RequestException, KeyError):
            continue
        ventana.append(a)
        ventana = ventana[-int(quieto_s / 0.15) :]
        if len(ventana) >= 8 and (max(ventana) - min(ventana)) < banda_deg:
            return True
        time.sleep(0.15)
    return False


def homing() -> bool:
    js("/cmd?m=3")
    t0 = time.time()
    while time.time() - t0 < 50:
        time.sleep(0.4)
        try:
            st = js("/state")
        except requests.RequestException:
            continue
        if st["homing_phase"] == "DONE":
            print(f"  homing DONE range={st['homing_range']:.2f} sign={st['homing_pwm_sign']}", flush=True)
            return True
        if st["homing_phase"] == "FAIL":
            print(f"  homing FAIL range={st.get('homing_range')}", flush=True)
            return False
    return False


def main() -> int:
    salida = sys.argv[1]
    n_sueltas = int(sys.argv[2]) if len(sys.argv) > 2 else 8

    if not homing():
        if not homing():
            print("homing falló dos veces"); return 1

    # `ec` alto y `sp` generoso: acá interesa LLEGAR a amplitud alta rápido, no que el
    # swing-up capture. `tr=0` deja al bombeo bombeando sin entregar al LQR.
    js("/cmd?tr=0&ec=2.5&sp=80&rt=0&sv=0")
    js("/cmd?rj=1")
    js("/daq?stop=1")
    js("/daq?decim=1&start=1")

    acc: list = []
    sueltas: list = []
    for k in range(n_sueltas):
        # Objetivo escalonado: amplitudes altas primero (menos contaminadas por la
        # friccion seca) y variadas, para poder ver la dependencia con la amplitud.
        # Amplitudes MODERADAS. Por encima de ~100 deg el pendulo tiene energia para
        # pasar por arriba y girar, y una vuelta no tiene medio ciclo que medir: la
        # tanda anterior perdio 4 de 6 sueltas por eso.
        objetivo = [90.0, 75.0, 60.0, 85.0, 70.0, 95.0, 65.0, 80.0][k % 8]

        # Esperar al pendulo REALMENTE quieto antes del `m5`. Sin esto el re-cero de
        # P22 corre contra un pendulo en movimiento y el cero de alpha queda donde
        # sea: en la tanda anterior las sueltas se asentaron en +158, -310, +29 y -49
        # deg, que es la deriva de P22, no el pendulo.
        if not esperar_quieto():
            print(f"  suelta {k + 1}/{n_sueltas}: el pendulo no se aquieto", flush=True)
            continue
        js("/cmd?m=5")
        t0 = time.time()
        soltado = None
        while time.time() - t0 < 22:
            drenar(acc)
            try:
                st = js("/state", timeout=4)
            except requests.RequestException:
                continue
            if st.get("swing_zero_phase", 0):
                continue
            a = abs(((st["pend_position_deg"] + 180) % 360) - 180)
            if st.get("swing_zero_ok") == 0 and st["mode"] == 0:
                break  # el re-cero fallo: el firmware aborto y no se arranca a ciegas
            if a >= objetivo and st["mode"] == 5:
                js("/cmd?m=2&s=0")  # brazo retenido: aisla el pivote del pendulo
                soltado = (round(time.time() - t0, 2), round(a, 1), round(st["position_deg"], 1))
                break
            if st["mode"] == 0:
                break
        if soltado is None:
            print(f"  suelta {k + 1}/{n_sueltas}: no llego a {objetivo:.0f} deg", flush=True)
            js("/cmd?m=0")
            time.sleep(0.5)
            continue
        print(f"  suelta {k + 1}/{n_sueltas}: |alpha|={soltado[1]} deg  brazo={soltado[2]} deg", flush=True)
        sueltas.append(soltado)
        # Dejar decaer con el brazo retenido. 6 s: con friccion seca el pendulo ya esta
        # quieto mucho antes, y esperar mas solo suma muestras de reposo.
        t_dec = time.time()
        while time.time() - t_dec < 6.0:
            drenar(acc)
            time.sleep(0.05)
        js("/cmd?m=0")
        time.sleep(1.0)

    js("/cmd?m=0")
    js("/daq?stop=1")
    for _ in range(10):
        if drenar(acc) == 0:
            break

    final = js("/state")
    acc.sort()
    if not acc:
        print("sin muestras"); return 1
    tref = acc[0][0]
    with (DATA / salida).open("w", encoding="utf-8") as f:
        f.write("t_s,th_deg,al_deg,pwm,mode\n")
        for t_us, th, al, pwm, md in acc:
            f.write(f"{(t_us - tref) / 1e6:.4f},{th:.3f},{al:.3f},{pwm},{md}\n")
    meta = {
        "sueltas": sueltas,
        "muestras": len(acc),
        "loop_dt_max_us": final.get("loop_dt_max_us"),
        "loop_overruns": final.get("loop_overruns"),
        "pend_wraps": final.get("pend_wraps"),
        "v_bus": final.get("v_bus"),
    }
    (DATA / (salida.replace(".csv", "_meta.json"))).write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"muestras={len(acc)}  sueltas={len(sueltas)} -> {salida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
