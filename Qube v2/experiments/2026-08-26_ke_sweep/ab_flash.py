"""A/B de las constantes del péndulo, re-flasheando en la misma sesión.

Por qué re-flashear en vez de comparar contra las tandas de la mañana: el banco deriva
dentro de la sesión y se recupera con el reposo (P12). Entre el firmware viejo y el nuevo
hubo una hora de descanso, así que «4/6 ahora contra 0/12 antes» mezcla el cambio con la
recuperación y no atribuye nada. Alternando bloques A/B/A/B en la misma sesión, la deriva
afecta a los dos brazos por igual y además queda medible como tendencia entre bloques.

Cada bloque verifica `pend_wn2` en `/state` antes de medir: 205.69 = escala vieja,
113.04 = escala nueva. Sin esa verificación, un flasheo que no entró se leería como un
resultado del tratamiento.

    python ab_flash.py <bloques>     # cada bloque = 3 tandas, alternando viejo/nuevo
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import requests

URL = "http://192.168.4.1"
AQUI = Path(__file__).parent
# Junto al experimento y no en /tmp: el /tmp de Git Bash no es el que ve Python en
# Windows (alli resuelve a C:/tmp), asi que el binario no aparecia.
BIN = {"viejo": AQUI / "fw" / "fw_viejo.bin", "nuevo": AQUI / "fw" / "fw_nuevo.bin"}
WN2 = {"viejo": 205.69, "nuevo": 113.04}


def estado(timeout_total: float = 90.0) -> dict | None:
    t0 = time.time()
    while time.time() - t0 < timeout_total:
        try:
            return requests.get(URL + "/state", timeout=4).json()
        except requests.RequestException:
            time.sleep(3)
    return None


def flashear(cual: str) -> bool:
    """Sube el binario y verifica por `pend_wn2` que efectivamente quedó corriendo."""
    st = estado()
    if st is None:
        print("  sin enlace antes de flashear", flush=True)
        return False
    if abs(float(st.get("pend_wn2", -1)) - WN2[cual]) < 0.5:
        print(f"  ya corre el {cual} (pend_wn2={st['pend_wn2']}), no se re-flashea", flush=True)
        return True

    requests.get(URL + "/cmd?x=1", timeout=5)
    time.sleep(0.5)
    data = BIN[cual].read_bytes()
    print(f"  flasheando {cual} ({len(data)} bytes)...", flush=True)
    try:
        r = requests.post(
            URL + "/update",
            files={"firmware": ("firmware.bin", data, "application/octet-stream")},
            timeout=240,
        )
        print(f"    HTTP {r.status_code} {r.text[:40]}", flush=True)
    except requests.RequestException as exc:
        print(f"    corte durante el POST ({type(exc).__name__}) — puede ser el reinicio", flush=True)

    time.sleep(12)
    st = estado()
    if st is None:
        print("  la placa no volvio", flush=True)
        return False
    wn2 = st.get("pend_wn2")
    ok = wn2 is not None and abs(float(wn2) - WN2[cual]) < 0.5
    print(f"  verificacion: pend_wn2={wn2} (esperado {WN2[cual]}) -> {'OK' if ok else 'NO COINCIDE'}", flush=True)
    return ok


def main() -> int:
    n_bloques = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    orden = ["viejo", "nuevo"]
    for b in range(n_bloques):
        cual = orden[b % 2]
        print(f"\n########## bloque {b + 1}/{n_bloques} — firmware {cual.upper()} ##########", flush=True)
        if not flashear(cual):
            print("  se aborta: el flasheo no quedo verificado", flush=True)
            return 1
        etiqueta = f"AB_{b + 1:02d}_{cual}"
        subprocess.run(
            [sys.executable, str(AQUI / "campana.py"), etiqueta,
             "--set", "ec=1.15", "--set", "cg=0", "--", "-1", "-1", "-1"],
            cwd=AQUI, check=False,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
