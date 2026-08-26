"""Mitad HTTP de la verificación de la Etapa 2.

La otra mitad —las colisiones de prefijo del despachador serial— **no se puede probar
por acá**: `op`, `zp`, `edp` y `cprp` son `hasParam` separados en `handleCmd`, así que
por HTTP siempre funcionaron bien. El defecto vivía en `processSerialCommand`, y
comprobarlo exige un cable USB. Ver `verify_serial.py`.

Lo que sí queda verificado acá:
  - que la placa corre el firmware nuevo (campos de `/state`),
  - **P23**: `?ke=` fija un override que la rama adaptativa respeta y `/state` lo publica,
  - que añadir campos a `getStateJson` no rompió la ruta HTTP de configuración.

NO energiza el motor: sólo escribe offsets y ganancias, y deja la placa en modo 0.

Uso:
    uv run python experiments/2026-08-06_etapa2_serial/scripts/verify_http.py --selftest
    uv run python experiments/2026-08-06_etapa2_serial/scripts/verify_http.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

IP = "192.168.4.1"
TOL = 0.05
SETTLE_S = 0.25

# Campos que sólo existen desde v1.59.0. Sin ellos, lo demás no se mide.
CAMPOS_NUEVOS = ("ke_gain", "ke_override", "pend_dir", "pend_counts_per_rev")


def get_state(ip: str) -> dict:
    return requests.get(f"http://{ip}/state", timeout=5).json()


def cmd(ip: str, endpoint: str = "cmd", **params) -> None:
    requests.get(f"http://{ip}/{endpoint}", params=params, timeout=5)
    time.sleep(SETTLE_S)


def evaluate(nombre: str, after: dict, before: dict, changed: dict, unchanged: list[str]) -> tuple[bool, list[str]]:
    """Bloque de veredicto, puro para poder ejercitarlo sin placa."""
    fallos: list[str] = []
    for campo, esperado in changed.items():
        if campo not in after:
            fallos.append(f"`{campo}` no está en /state")
        elif abs(float(after[campo]) - float(esperado)) > TOL:
            fallos.append(f"`{campo}` = {after[campo]}, se esperaba {esperado}")
    for campo in unchanged:
        if campo not in before or campo not in after:
            fallos.append(f"`{campo}` no está en /state — no se puede verificar que no cambió")
        elif abs(float(after[campo]) - float(before[campo])) > TOL:
            fallos.append(f"`{campo}` cambió de {before[campo]} a {after[campo]} y no debía")
    return (not fallos), fallos


def selftest() -> int:
    """Cuatro casos, dos construidos para FALLAR."""
    problemas: list[str] = []

    ok, _ = evaluate("x", {"ke_gain": 0.75, "ke_override": -1.0}, {}, {"ke_gain": 0.9, "ke_override": 0.9}, [])
    if ok:
        problemas.append("aprobó un ke_gain pisado por la rama adaptativa (0.75 donde se pidió 0.9)")

    ok, fallos = evaluate("x", {"ke_gain": 0.9, "ke_override": 0.9}, {}, {"ke_gain": 0.9, "ke_override": 0.9}, [])
    if not ok:
        problemas.append(f"reprobó el caso correcto: {fallos}")

    ok, _ = evaluate("x", {"offset_deg": 0.0}, {"offset_deg": 10.0}, {}, ["offset_deg"])
    if ok:
        problemas.append("aprobó un campo que cambió cuando no debía")

    ok, _ = evaluate("x", {}, {}, {"ke_override": 0.9}, [])
    if ok:
        problemas.append("aprobó un /state sin el campo pedido (firmware viejo)")

    if problemas:
        print("SELFTEST FALLÓ:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("selftest OK: el veredicto reprueba lo que debe reprobar (4 casos)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=IP)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--save", default=None, help="guardar el /state final en este archivo")
    args = ap.parse_args()

    if args.selftest:
        return selftest()
    if selftest() != 0:
        print("\nNo se toca la placa con un criterio que no se sostiene.")
        return 1

    s0 = get_state(args.ip)
    faltan = [c for c in CAMPOS_NUEVOS if c not in s0]
    if faltan:
        print(f"FALLA: /state no publica {faltan} — la placa NO tiene v1.59.0.")
        return 1
    if s0.get("mode") != 0:
        print(f"FALLA: la placa está en modo {s0.get('mode')}, no en 0. Abortando.")
        return 1

    print(f"placa v1.59.0 — mode={s0['mode']} v_bus={s0['v_bus']:.2f} ina_ok={s0['ina_ok']} pwm={s0['pwm']}")
    print(f"campos de /state: {len(s0)}\n")
    print("=" * 74)

    resultados: list[tuple[str, bool, list[str], str]] = []

    def check(
        nombre: str, params: dict, changed: dict, unchanged: list[str], nota: str, endpoint: str = "cmd"
    ) -> None:
        before = get_state(args.ip)
        cmd(args.ip, endpoint, **params)
        after = get_state(args.ip)
        ok, fallos = evaluate(nombre, after, before, changed, unchanged)
        resultados.append((nombre, ok, fallos, nota))
        print(f"  {nombre:<26} {'PASS' if ok else 'FAIL'}   {nota}")
        for f in fallos:
            # ASCII a proposito: la consola de Windows es cp1252 y un guion de caja
            # tiraba el script justo cuando habia algo que reportar.
            print(f"      -> {f}")

    # ── P23: el override de ke ────────────────────────────────────────────────
    check("?ke=0.9", {"ke": 0.9}, {"ke_gain": 0.9, "ke_override": 0.9}, [], "P23: fija override y lo publica")
    check("?ke=0.35", {"ke": 0.35}, {"ke_gain": 0.35, "ke_override": 0.35}, [], "P23: se puede barrer")
    check("?ke=-1", {"ke": -1}, {"ke_override": -1.0}, [], "P23: suelta el override")

    # ── Campos nuevos de configuración del péndulo ────────────────────────────
    check("?edp=-1", {"edp": -1}, {"pend_dir": -1}, ["encoder_dir"], "pend_dir observable, servo intacto")
    check("?edp=1", {"edp": 1}, {"pend_dir": 1}, ["encoder_dir"], "vuelve")
    check("?cprp=1024", {"cprp": 1024}, {"pend_counts_per_rev": 1024.0}, ["counts_per_rev"], "cpr del péndulo")
    check("?cprp=2048", {"cprp": 2048}, {"pend_counts_per_rev": 2048.0}, ["counts_per_rev"], "vuelve al default")

    # ── Regresión de la ruta HTTP de offsets (la que toqué al agregar campos) ──
    check("?o=10", {"o": 10}, {"offset_deg": 10.0}, ["pend_offset_deg"], "offset servo")
    check("?op=25", {"op": 25}, {"pend_offset_deg": 25.0}, ["offset_deg"], "offset péndulo, servo intacto")
    check("?o=0&?op=0", {"o": 0, "op": 0}, {"offset_deg": 0.0, "pend_offset_deg": 0.0}, [], "restaura")

    # ── 2.3: los cuatro del catch del híbrido, que sólo existían por serial ───
    # `L8`..`L11` eran inalcanzables durante una campaña porque abrir el serial
    # reinicia la placa: toda tanda de m7 corría con los defaults compilados.
    check("?hcm=250", {"hcm": 250}, {"hybrid_catch_ms": 250.0}, [], "catch_ms por HTTP (era L8)")
    check("?hcg=0.2", {"hcg": 0.2}, {"hybrid_catch_gain": 0.2}, [], "catch_gain por HTTP (era L9)")
    check("?hcp=40", {"hcp": 40}, {"hybrid_catch_pwm": 40}, [], "catch_pwm por HTTP (era L10)")
    check("?hca=12", {"hca": 12}, {"hybrid_catch_angle": 12.0}, [], "catch_angle por HTTP (era L11)")

    # ── Regresión de los mandos que ya eran configurables ─────────────────────
    check("?lpm=100", {"lpm": 100}, {"lqr_pwm_max": 100}, [], "techo del LQR (v1.58.9)")
    check("?lpm=70", {"lpm": 70}, {"lqr_pwm_max": 70}, [], "restaura el default")
    # `scale` vive en /rl_cmd, no en /cmd. La primera corrida lo mandó a /cmd y dio FAIL:
    # el defecto era del script, no del firmware. Queda anotado porque es justo el tipo de
    # falso negativo que este proyecto ya pagó — un criterio que reprueba por su propia
    # causa y se lee como un defecto de la placa.
    check("/rl_cmd?scale=0.5", {"scale": 0.5}, {"rl_pwm_scale": 0.5}, [], "lo lee m7, y ahora m6", "rl_cmd")
    check("/rl_cmd?scale=1", {"scale": 1}, {"rl_pwm_scale": 1.0}, [], "restaura", "rl_cmd")

    print("=" * 74)
    pasaron = sum(1 for _, ok, _, _ in resultados if ok)
    print(f"\n{pasaron}/{len(resultados)} PASS")

    final = get_state(args.ip)
    if args.save:
        Path(args.save).write_text(json.dumps(final, indent=2), encoding="utf-8")
        print(f"estado final guardado en {args.save}")
    print(f"placa: mode={final['mode']} pwm={final['pwm']} ke_override={final['ke_override']} v_bus={final['v_bus']:.2f}")

    print("\nNO verificado acá (necesita cable USB): las colisiones de prefijo del")
    print("despachador serial — `op`, `zp`, `edp`, `cprp`, `lqr1..4`. Ver verify_serial.py.")
    print("NO verificado acá (necesita motor y banco válido): que `?ke=` sobreviva a m5.")

    return 0 if pasaron == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
