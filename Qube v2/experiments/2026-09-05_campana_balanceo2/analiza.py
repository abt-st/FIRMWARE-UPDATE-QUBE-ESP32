"""Diagnostico por traza: donde muere cada intento y cuanto recorrido usa el brazo.

El resumen que deja `campana.py` responde «sirvio o no». Esto responde «por que», que es
lo que elige la condicion siguiente. Dos cosas que el resumen no separa:

  · **En que modo muere el intento.** Una falla `3` (brazo al tope) contada sobre el
    total no distingue el brazo derivando mientras BOMBEA (m5) del brazo derivando
    mientras BALANCEA (m4). Son dos arreglos distintos —`pc`/`pr` contra `lpm`/`lqr4`—
    y en la base de esta sesion el reparto fue 15 y 8, o sea que la mayoria ni siquiera
    llegaba al balanceo.
  · **El centro de oscilacion del brazo durante el bombeo.** Es el numero que dice si
    `pc` tiene algo que corregir: si el centro esta en 0 el recorrido se reparte y no
    hay nada que ganar; si esta corrido, el brazo toca un limite mientras del otro lado
    le sobran decenas de grados.

    python analiza.py [traza.jsonl ...]      # sin argumentos: todas las de data/
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

DATOS = Path(__file__).parent / "data"

FALLAS = {
    0: "ninguna",
    1: "el pendulo se cayo",
    2: "el pendulo dio una vuelta",
    3: "el brazo llego al tope",
    4: "nunca llego a la vertical",
    5: "el recentrado no pudo volver",
    6: "no se aquieto para el re-cero",
}


def cargar(ruta: Path) -> tuple[dict, list[dict]]:
    meta: dict = {}
    muestras: list[dict] = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        if not linea.strip():
            continue
        d = json.loads(linea)
        if d.get("_meta"):
            meta = d
        else:
            muestras.append(d)
    return meta, muestras


def informe(ruta: Path) -> None:
    meta, ms = cargar(ruta)
    if not ms:
        print(f"{ruta.name}: traza vacia")
        return
    print(f"\n{'=' * 78}\n{ruta.name}  ·  {meta.get('config', '?')}  ·  {ms[-1]['t']:.0f} s, {len(ms)} muestras")

    # ── Donde muere cada intento ──────────────────────────────────────────────
    # El modo de la muestra ANTERIOR al incremento del contador: cuando el contador
    # sube el firmware ya cambio de modo, asi que leerlo en la misma muestra atribuye
    # todas las fallas al modo 5.
    por_modo: dict[tuple[int, int], int] = {}
    prev = ms[0]["swing_retry_count"]
    for i, m in enumerate(ms[1:], 1):
        if m["swing_retry_count"] > prev:
            clave = (ms[i - 1]["mode"], m["swing_fail_reason"])
            por_modo[clave] = por_modo.get(clave, 0) + 1
            prev = m["swing_retry_count"]
    if por_modo:
        print("\ndonde muere el intento:")
        for (modo, razon), n in sorted(por_modo.items(), key=lambda kv: -kv[1]):
            print(f"  modo {modo}  {FALLAS.get(razon, razon):30s} x{n}")

    # ── Recorrido del brazo mientras bombea ───────────────────────────────────
    b = [
        m["position_deg"] for m in ms if m["mode"] == 5 and not m["swing_recenter_phase"] and not m["swing_zero_phase"]
    ]
    if b:
        s = sorted(b)
        print("\nbrazo durante el bombeo:")
        print(f"  centro (media) {statistics.mean(b):+6.1f} deg   ·   mediana {statistics.median(b):+6.1f} deg")
        print(
            f"  recorrido p5..p95 {s[int(0.05 * len(s))]:+6.1f} .. {s[int(0.95 * len(s))]:+6.1f}"
            f"   ·   extremos {s[0]:+.1f} .. {s[-1]:+.1f}   (limite duro ±95)"
        )
        print(f"  tiempo del lado negativo: {sum(1 for x in b if x < 0) / len(b) * 100:.0f} %")

    # ── Reparto del tiempo ────────────────────────────────────────────────────
    total = len(ms)
    quieto = sum(1 for m in ms if m["mode"] == 5 and m["swing_zero_phase"])
    recentra = sum(1 for m in ms if m["swing_recenter_phase"])
    m4 = sum(1 for m in ms if m["mode"] == 4)
    bombeo = len(b)
    print("\nreparto del tiempo:")
    for etiqueta, n in [
        ("esperando quietud", quieto),
        ("bombeando", bombeo),
        ("balanceando (m4)", m4),
        ("recentrando", recentra),
    ]:
        print(f"  {etiqueta:20s} {n / total * 100:4.0f} %")

    # ── Traspasos ─────────────────────────────────────────────────────────────
    traspasos = [m for i, m in enumerate(ms) if m["mode"] == 4 and (i == 0 or ms[i - 1]["mode"] != 4)]
    if traspasos:
        alphas = [abs(m.get("swing_trans_alpha") or 0) for m in traspasos]
        energias = [m.get("swing_trans_energy") or 0 for m in traspasos]
        print(f"\ntraspasos: {len(traspasos)}")
        print(
            f"  |alpha| en el traspaso: mediana {statistics.median(alphas):.1f} deg  (rango {min(alphas):.1f}..{max(alphas):.1f})"
        )
        print(
            f"  E/E* en el traspaso:    mediana {statistics.median(energias):.2f}   (rango {min(energias):.2f}..{max(energias):.2f})"
        )


def main() -> int:
    rutas = [Path(a) for a in sys.argv[1:]] or sorted(DATOS.glob("*.jsonl"))
    if not rutas:
        print("no hay trazas en data/")
        return 1
    for r in rutas:
        informe(r)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
