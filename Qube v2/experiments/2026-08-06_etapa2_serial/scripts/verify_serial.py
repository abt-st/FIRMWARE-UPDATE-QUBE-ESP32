"""Verifica en placa las colisiones de prefijo que arregló la Etapa 2.

NO energiza el motor y NO entra a ningún modo que mueva: los seis comandos que se
verifican son de offset y configuración. Se puede correr con el banco en cualquier
estado, incluso con P24 sin resolver, porque no mide dinámica.

Uso:
    uv run python experiments/2026-08-06_etapa2_serial/scripts/verify_serial.py --selftest
    uv run python experiments/2026-08-06_etapa2_serial/scripts/verify_serial.py
    uv run python experiments/2026-08-06_etapa2_serial/scripts/verify_serial.py --port COM7

Abrir el puerto serie reinicia la placa. Acá eso no molesta —la campaña arranca de cero
a propósito— pero hay que rehacer el homing si el banco se iba a usar para otra cosa.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field

try:
    import serial
    import serial.tools.list_ports
except ImportError:  # pragma: no cover - depende del entorno
    print("Falta pyserial: uv add pyserial")
    sys.exit(2)

BAUD = 115200
SETTLE_S = 0.7


@dataclass
class Check:
    """Una fila de la tabla del README."""

    cmd: str
    changed: dict[str, float | int] = field(default_factory=dict)
    unchanged: list[str] = field(default_factory=list)
    echo: str | None = None
    note: str = ""


# El criterio, tal cual está escrito en el README y antes de tocar la placa.
# `unchanged` es la mitad que el firmware viejo reprueba: sin ella, el viejo pasaría.
CHECKS: list[Check] = [
    Check("o10", {"offset_deg": 10.0}, note="referencia del servo, ya funcionaba"),
    Check("op25", {"pend_offset_deg": 25.0}, ["offset_deg"], note="el viejo ponía offset_deg en 0"),
    Check("zp", {}, ["offset_deg"], echo="[PEND]", note="el viejo cerraba el SERVO"),
    Check("ed-1", {"encoder_dir": -1}, note="dirección del servo, ya funcionaba"),
    Check("edp1", {"pend_dir": 1}, ["encoder_dir"], note="el viejo ponía encoder_dir en 1"),
    Check("cpr1024", {"counts_per_rev": 1024.0}, note="CPR del servo, ya funcionaba"),
    Check("cprp2048", {"pend_counts_per_rev": 2048.0}, ["counts_per_rev"], note="el viejo lo ignoraba en silencio"),
    Check("lqr230", {}, [], echo="[LQR] K2=30", note="el viejo caía en default"),
    Check("ke0.9", {"ke_gain": 0.9, "ke_override": 0.9}, [], note="P23: no existía por serie"),
    Check("ke-1", {"ke_override": -1.0}, [], note="suelta el override"),
    Check("vv", {}, [], echo="[ERR] comando desconocido", note="el viejo imprimía la ayuda"),
    # Hallado por esta misma campaña, 2026-08-06. `qq` NO es un comando desconocido:
    # `q` tiene `case` —es la escala de par del m7— y `toFloat("q")` daba 0.0, así que
    # un typo apagaba el par del modo 7 sin imprimir nada. Medido: 1.0 -> 0.0.
    Check("q1", {"rl_pwm_scale": 1.0}, [], echo="[RL] scale=1", note="valor válido, se acepta"),
    Check("qq", {}, ["rl_pwm_scale"], echo="[ERR] q necesita", note="typo: se rechaza y NO toca el par"),
    # El resto de la clase `qq`. Cada uno: el typo se rechaza Y no mueve lo que tocaba.
    # `s` y `kp` son los peores — `s` en modo 2 MUEVE el brazo, `kp` es la ganancia
    # del PID, y los dos se iban a 0 en silencio.
    Check("s15", {"setpoint_deg": 15.0}, [], note="setpoint válido"),
    Check("sx", {}, ["setpoint_deg"], echo="[ERR] s necesita", note="typo: no manda el brazo a 0"),
    Check("kp3.5", {}, [], echo="[PID] kp=3.500", note="ganancia PID válida"),
    Check("kpx", {}, [], echo="[ERR] kp necesita", note="typo: no pone Kp en 0"),
    Check("kz1", {}, [], echo="[ERR] use kp/ki/kd", note="subcomando inválido, antes callaba"),
    Check("L6 25", {}, [], echo="[LQR] g6=25.000", note="lqr_K2 por serie"),
    Check("L6 x", {}, [], echo="[ERR] formato", note="typo: no pone lqr_K2 en 0"),
    Check("L99 5", {}, [], echo="[ERR] L99 no existe", note="antes decía éxito sin escribir nada"),
    Check("gf2", {}, [], echo="[GS] gf=2.000", note="gain scheduling válido"),
    Check("gfx", {}, [], echo="[ERR] gf necesita", note="typo rechazado"),
    Check("edx", {}, ["encoder_dir"], echo="[ERR] ed necesita", note="typo: no invierte el servo"),
    Check("m9", {}, ["mode"], note="modo fuera de rango, no cambia nada"),
    Check("mx", {}, ["mode"], echo="[ERR] m necesita", note="typo: no cae a modo 0"),
    Check("lqr2x", {}, [], echo="[ERR] use lqr1..lqr4", note="typo: no pone K2 en 0"),
]

TOL = 0.05


def find_port() -> str | None:
    for p in serial.tools.list_ports.comports():
        desc = p.description.lower()
        if any(k in desc for k in ("cp210", "ch340", "silicon labs", "usb serial")):
            return p.device
    return None


def send(ser: serial.Serial, cmd: str) -> str:
    ser.reset_input_buffer()
    ser.write((cmd + "\r\n").encode())
    time.sleep(SETTLE_S)
    raw = ser.read(ser.in_waiting or 8192).decode(errors="replace")
    return "\n".join(ln.strip() for ln in raw.splitlines() if ln.strip() and not ln.startswith("POS:"))


def _last_complete_json(buf: str) -> dict:
    """Último objeto JSON *balanceado* del búfer.

    Un `re.findall(r'\\{.*\\}')` sobre una lectura parcial devuelve basura o nada, y la
    telemetría serie a 10 Hz se intercala con la respuesta de `?`: el JSON llega partido.
    Acá se cuentan llaves y sólo se acepta un objeto cerrado.
    """
    best: dict = {}
    depth = 0
    start = -1
    for i, c in enumerate(buf):
        if c == "{":
            if depth == 0:
                start = i
            depth += 1
        elif c == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    cand = json.loads(buf[start : i + 1])
                except json.JSONDecodeError:
                    continue
                if isinstance(cand, dict) and "mode" in cand:
                    best = cand
    return best


def read_state(ser: serial.Serial, timeout: float = 4.0) -> dict:
    """`?` imprime getStateJson por serie. Se acumula hasta tener un objeto completo."""
    ser.reset_input_buffer()
    ser.write(b"?\r\n")
    deadline = time.time() + timeout
    buf = ""
    while time.time() < deadline:
        chunk = ser.read(ser.in_waiting or 1)
        if chunk:
            buf += chunk.decode(errors="replace")
            got = _last_complete_json(buf)
            if got:
                return got
        else:
            time.sleep(0.05)
    return _last_complete_json(buf)


def evaluate(check: Check, before: dict, after: dict, echo: str) -> tuple[bool, list[str]]:
    """Bloque de veredicto. Puro a propósito: se ejercita sin placa en --selftest."""
    fallos: list[str] = []

    for campo, esperado in check.changed.items():
        if campo not in after:
            fallos.append(f"`{campo}` no está en /state — ¿firmware viejo?")
        elif abs(float(after[campo]) - float(esperado)) > TOL:
            fallos.append(f"`{campo}` = {after[campo]}, se esperaba {esperado}")

    for campo in check.unchanged:
        if campo not in before or campo not in after:
            fallos.append(f"`{campo}` no está en /state — no se puede verificar que no cambió")
        elif abs(float(after[campo]) - float(before[campo])) > TOL:
            fallos.append(f"`{campo}` cambió de {before[campo]} a {after[campo]} y no debía — es el defecto viejo")

    if check.echo and check.echo not in echo:
        fallos.append(f"la placa no respondió `{check.echo}` (dijo: {echo[:80]!r})")

    # `zp` no declara un valor de llegada, pero tiene que haber movido algo.
    if check.cmd == "zp" and before.get("pend_offset_deg") == after.get("pend_offset_deg"):
        fallos.append("`zp` no movió `pend_offset_deg`: no re-estableció el cero del péndulo")

    return (not fallos), fallos


def selftest() -> int:
    """El veredicto, contra un estado construido para FALLAR.

    Sin esto el script es un criterio que no puede reprobar — el defecto que este
    proyecto cometió tres veces en dos días.
    """
    problemas: list[str] = []

    # 1. El defecto viejo de `op`: escribe lo suyo PERO pisa el offset del servo.
    viejo_before = {"offset_deg": 10.0, "pend_offset_deg": 25.0}
    viejo_after = {"offset_deg": 0.0, "pend_offset_deg": 25.0}
    ok, _ = evaluate(CHECKS[1], viejo_before, viejo_after, "")
    if ok:
        problemas.append("el veredicto APROBÓ el firmware viejo en `op25` (pisó offset_deg y no lo vio)")

    # 2. Firmware nuevo: lo suyo cambia, lo ajeno no.
    nuevo_before = {"offset_deg": 10.0, "pend_offset_deg": 0.0}
    nuevo_after = {"offset_deg": 10.0, "pend_offset_deg": 25.0}
    ok, fallos = evaluate(CHECKS[1], nuevo_before, nuevo_after, "")
    if not ok:
        problemas.append(f"el veredicto REPROBÓ el firmware correcto en `op25`: {fallos}")

    # 3. Un campo ausente no puede pasar por aprobado (firmware viejo sin `pend_dir`).
    ok, _ = evaluate(CHECKS[4], {"encoder_dir": -1}, {"encoder_dir": -1}, "")
    if ok:
        problemas.append("el veredicto APROBÓ un /state sin `pend_dir`")

    # 4. Un eco ausente tampoco.
    ok, _ = evaluate(CHECKS[10], {}, {}, "ayuda de comandos QUBE")
    if ok:
        problemas.append("el veredicto APROBÓ un comando inválido que imprimió la ayuda")

    if problemas:
        print("SELFTEST FALLÓ — el criterio no distingue lo que dice distinguir:")
        for p in problemas:
            print(f"  - {p}")
        return 1
    print("selftest OK: el veredicto reprueba el firmware viejo y aprueba el nuevo (4 casos)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Verificación en placa de la Etapa 2")
    ap.add_argument("--port", default=None, help="puerto serie (por defecto: autodetectar)")
    ap.add_argument("--selftest", action="store_true", help="ejercita el veredicto sin placa y sale")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if selftest() != 0:
        print("\nNo se toca la placa con un criterio que no se sostiene.")
        return 1

    port = args.port or find_port()
    if port is None:
        print("No se encontró un ESP32. Conectá la placa por USB o pasá --port COMx.")
        return 2

    print(f"\nAbriendo {port} (esto REINICIA la placa)...")
    ser = serial.Serial(port, BAUD, timeout=2)
    time.sleep(2.0)  # el ESP32 tarda en arrancar tras el reset por DTR

    try:
        estado = read_state(ser)
        if not estado:
            print("La placa no contestó a `?`. Sin lectura no se reporta nada.")
            return 2
        if "ke_override" not in estado:
            print("FALLA: /state no publica `ke_override` — la placa NO tiene el firmware v1.59.0.")
            print("       Flashear primero: uv run python src/firmware/flash.py")
            return 1

        print(f"placa viva — mode={estado.get('mode')} v_bus={estado.get('v_bus')} ina_ok={estado.get('ina_ok')}")
        if estado.get("mode") != 0:
            print("FALLA: la placa no está en modo 0. Mandá `x` antes de correr esto.")
            return 1

        print("\n" + "=" * 72)
        resultados: list[tuple[Check, bool, list[str]]] = []
        for check in CHECKS:
            before = read_state(ser)
            echo = send(ser, check.cmd)
            after = read_state(ser)
            if not after:
                print(f"  {check.cmd:<10} SIN LECTURA — se aborta")
                return 2
            ok, fallos = evaluate(check, before, after, echo)
            resultados.append((check, ok, fallos))
            marca = "PASS" if ok else "FAIL"
            print(f"  {check.cmd:<10} {marca}   {check.note}")
            for f in fallos:
                # ASCII a proposito: la consola de Windows es cp1252 y un guion de caja
                # tiraba el script justo cuando habia algo que reportar.
                print(f"             -> {f}")

        print("=" * 72)
        pasaron = sum(1 for _, ok, _ in resultados if ok)
        print(f"\n{pasaron}/{len(resultados)} PASS")
        if pasaron == len(resultados):
            print("Etapa 2 VERIFICADA en placa.")
            return 0
        print("Etapa 2 NO verificada: todas comparten el mismo mecanismo, una en rojo las deja a todas.")
        return 1
    finally:
        # ── Restaurar el banco, y no a mano ──────────────────────────────────────
        # La campaña deja `encoder_dir = -1`, `counts_per_rev = 1024`, `lqr_K2 = 30` y
        # dos offsets movidos. Irse así corrompe en silencio toda medición posterior:
        # exactamente la clase de daño que esta Etapa vino a eliminar. `reboot` devuelve
        # TODO a los defaults compilados, porque `Preferences` sólo guarda credenciales
        # WiFi — restaurar campo por campo sería otra lista que puede quedar incompleta.
        send(ser, "x")
        print("\nrestaurando defaults compilados (reboot)...")
        ser.write(b"reboot\r\n")
        time.sleep(3.5)
        estado = read_state(ser)
        ser.close()
        if estado:
            print(
                f"placa restaurada — mode={estado.get('mode')} "
                f"encoder_dir={estado.get('encoder_dir')} cpr={estado.get('counts_per_rev')} "
                f"offset={estado.get('offset_deg')} ke_override={estado.get('ke_override')}"
            )
        else:
            print("AVISO: no se pudo confirmar el estado tras el reboot. Verificar a mano.")


if __name__ == "__main__":
    sys.exit(main())
