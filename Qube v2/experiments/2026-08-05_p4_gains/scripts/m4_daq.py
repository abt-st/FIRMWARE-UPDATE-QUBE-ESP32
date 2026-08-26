"""m4 — el LQR medido a 500 Hz: saturacion de la salida y excursion del brazo.

Por que hace falta. Todas las campanas de m4 hasta hoy muestrearon por HTTP a ~14 Hz, que
son 5 a 20 muestras por intento. Con eso se decidio que el LQR "sostiene 0,5 s" sin poder
ver que pasa en el medio. Las trazas del m5 (que traen el modo 4 completo a 500 Hz) dieron
dos cosas:

  - la salida esta en su techo el 70,4% del tiempo (H3 CONFIRMADA), y
  - el pendulo sale de +-20 grados de la vertical en 0 a 86 ms desde el traspaso, o sea
    DENTRO de la ventana del catch, donde el LQR no ejecuta ni un tick.

Por eso la metrica primaria de esta campana es `t_loss` —ms desde el traspaso hasta perder
el pendulo— y no `lqr_alive_ms`, que cuenta desde el FIN del catch y por lo tanto no mide
la misma cosa con `lc=0` que con `lc=400`.

Dos cuidados que este proyecto ya pago caro:

1. **El techo de la salida NO es LQR_PWM_MAX.** El DAQ registra `lastPwmCmd`, asignado en
   `setMotorDirect` (`esp32_qube.ino:1425`), o sea DESPUES de la atenuacion por posicion de
   `setMotor` (`:1447-1451`, factor `1/(1+(|theta|/200)^2)`). Comparar contra 70 a secas da
   0% de saturacion en cualquier corrida. El techo se recalcula por muestra con el theta de
   la propia traza. (Mismo error que se encontro en el bombeo, ver `m5_pwm_sat.py`.)

2. **La saturacion se mide descartando la ventana del catch.** Ahi el tope es
   LQR_CATCH_PWM=25 y no 70, asi que contarla como "no saturado" seria el mismo error que
   contar la fase de re-cero del bombeo. `t_loss`, en cambio, se mide desde el traspaso
   INCLUYENDO el catch: perder el pendulo durante el catch sigue siendo perderlo.

Contrato del firmware: un solo consumidor de /daq/read. No correr con la GUI abierta.

Uso:
    uv run python m4_daq.py --reps 5
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from qube_app.link import QubeLink
from qube_app.recorder import Recorder
from qube_app.stream import DaqStream

DATA = Path(__file__).resolve().parent.parent / "data"

SERVO_LIMIT_DEG = 95.0
LQR_PWM_MAX = 70  # esp32_qube.ino:489
SOFT_SAT_K_DEG = 200.0  # esp32_qube.ino:702
PEND_UP_TOL_DEG = 20.0  # |180 - alpha| por encima de esto = el pendulo se perdio
# Error de entrega por debajo del cual el LQR arranca con el pendulo DENTRO de la banda.
# Equivale al criterio 1 del m5 (|alpha| >= 165). Medido el 2026-08-05 sobre las 10 trazas
# del m5: concordancia 10/10 entre cumplir ese criterio y tener t_loss > 0.
HANDOFF_GOOD_ERR_DEG = 15.0
# Umbrales de la proteccion por tension del firmware (`:3722`, `:4031`).
BROWNOUT_CUT_V = 12.5  # por debajo: pwm = 0 y el tick retorna
BROWNOUT_DERATE_V = 13.5  # por debajo: el PWM se escala por tension
REASON_BITS = {0x01: "near+slow", 0x02: "peak", 0x04: "forced", 0x08: "energy"}

# Condiciones. Cada una difiere del control en UNA sola cosa.
#   nocatch: quita la ventana del catch entera (H1 + H2 juntas; no pretende separarlas)
#   h7:      solo el signo del amortiguamiento del brazo
CONDITIONS: dict[str, dict[str, float]] = {
    "control": {"lc": 400, "lqr3": 1.5},
    "nocatch": {"lc": 0, "lqr3": 1.5},
    "h7": {"lc": 400, "lqr3": -1.5},
}
CATCH_SAMPLES_PER_MS = 0.5  # 500 Hz


def decode_reason(mask: int) -> str:
    return "+".join(n for b, n in REASON_BITS.items() if mask & b) or "-"


def soft_sat_cap(theta_deg: np.ndarray, pwm_max: int = LQR_PWM_MAX) -> np.ndarray:
    """Techo que la salida del LQR puede alcanzar con el brazo en `theta_deg`.

    `pwm_max` es parametro porque desde v1.58.9 el techo del LQR es configurable (`?lpm=`).
    Medir un barrido de `lpm` contra un 70 fijo daria saturaciones falsas — el mismo error
    que da 0% al comparar contra el tope sin la atenuacion por posicion.
    """
    k = np.abs(theta_deg) / SOFT_SAT_K_DEG
    return (pwm_max / (1.0 + k * k)).astype(int)


def wait_for_rest(link: QubeLink, timeout: float = 25.0, tol: float = 0.5) -> bool:
    link.send({"m": 0})
    end = time.perf_counter() + timeout
    prev, stable = None, 0
    while time.perf_counter() < end:
        a = float(link.state().get("pend_position_deg", 0.0))
        if prev is not None and abs(a - prev) < tol:
            stable += 1
            if stable >= 8:
                return True
        else:
            stable = 0
        prev = a
        time.sleep(0.15)
    return False


def homing(link: QubeLink, timeout: float = 30.0) -> dict:
    link.send({"m": 3})
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        d = link.state()
        if d.get("homing_phase") == "DONE":
            return d
        if d.get("homing_phase") == "FAIL":
            raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
        time.sleep(0.2)
    raise RuntimeError("homing timeout")


def attempt(link: QubeLink, cond: str, rep: int, max_s: float) -> dict | None:
    if not wait_for_rest(link):
        print("    (aviso: el pendulo no se aquieto; se mide igual y queda anotado)")
    homing(link)
    # El re-cero del pendulo lo hace el propio firmware al entrar al modo 5 (v1.58.8, P22):
    # el cliente no tiene que acordarse de nada.
    link.send({"cg": 1, **CONDITIONS[cond]})
    time.sleep(0.1)

    stream = DaqStream(link.ip, decim=1, poll_interval=0.2)
    rec = Recorder(DATA / f"m4_{cond}_r{rep}.csv")
    rec.open()
    parts: list[tuple[np.ndarray, ...]] = []

    def pump(seconds: float) -> None:
        end = time.perf_counter() + seconds
        while time.perf_counter() < end:
            time.sleep(0.05)
            for c in stream.drain():
                rec.write(c)
                parts.append((c.t_s, c.th_deg, c.al_deg, c.pwm, c.mode))

    link.reset_loop_metrics()
    stream.start()
    try:
        pump(0.5)
        link.send({"m": 5})  # el swing-up entrega al modo 4 solo
        pump(max_s)
    finally:
        link.send({"m": 0})
        stream.stop()
        for c in stream.drain():
            rec.write(c)
            parts.append((c.t_s, c.th_deg, c.al_deg, c.pwm, c.mode))
        rec.close()

    if not parts:
        print("    ERROR: no llego ninguna muestra")
        return None
    th = np.concatenate([p[1] for p in parts])
    al = np.concatenate([p[2] for p in parts])
    pwm = np.concatenate([p[3] for p in parts])
    mode = np.concatenate([p[4] for p in parts])

    st = link.state()
    mask = int(st.get("swing_trans_reason") or 0)
    trans = (
        {
            "reason": decode_reason(mask),
            "alpha_deg": float(st["swing_trans_alpha"]),
            "vel_dps": float(st["swing_trans_vel"]),
            "energy_ratio": float(st["swing_trans_energy"]),
        }
        if mask
        else None
    )

    row: dict = {
        "cond": cond,
        "rep": rep,
        **CONDITIONS[cond],
        # Latcheado por el firmware desde el FIN del catch: con lc=0 y con lc=400 NO mide
        # la misma cosa. Se registra para comparar con las campanas viejas, no para decidir.
        "alive_ms": int(st.get("lqr_alive_ms") or 0),
        "transition": trans,
        "loop_overruns": st.get("loop_overruns"),
    }
    row.update(analyse(th, al, pwm, mode, int(CONDITIONS[cond]["lc"])))
    return row


def analyse(
    th: np.ndarray,
    al: np.ndarray,
    pwm: np.ndarray,
    mode: np.ndarray,
    lc_ms: int,
    pwm_max: int = LQR_PWM_MAX,
) -> dict:
    """Metricas del modo 4 a partir de una traza de 500 Hz.

    Funcion pura y separada de la adquisicion a proposito: `selftest.py` la corre sobre las
    trazas del m5 de 2026-08-04, cuyas cifras ya se conocen, y verifica que las reproduce.
    Un error de metrica descubierto con el motor girando cuesta una sesion de banco.
    """
    in4 = mode == 4
    if not in4.any():
        return {"handed_off": False}

    th4, al4, pwm4 = th[in4], al[in4], np.abs(pwm[in4])
    # Acotar UNA vez sobre el array entero, no muestra a muestra (leccion de P14).
    err4 = np.abs(180.0 - np.abs((al4 + 180.0) % 360.0 - 180.0))

    # METRICA PRIMARIA. Desde el traspaso (incluyendo el catch: perder el pendulo durante
    # el catch sigue siendo perderlo) hasta salir de +-PEND_UP_TOL_DEG de la vertical.
    lost = np.flatnonzero(err4 > PEND_UP_TOL_DEG)
    t_loss_ms = float(lost[0]) / CATCH_SAMPLES_PER_MS if lost.size else None

    # La saturacion, en cambio, SI descarta el catch: ahi el tope es 25, no 70.
    th_p, pwm_p = th4[int(lc_ms * CATCH_SAMPLES_PER_MS):], pwm4[int(lc_ms * CATCH_SAMPLES_PER_MS):]
    sat = float((pwm_p >= soft_sat_cap(th_p, pwm_max)).mean()) if th_p.size else None

    return {
        "handed_off": True,
        "t_in_m4_s": round(float(in4.sum()) / 500.0, 3),
        # metrica primaria: ms desde el traspaso hasta perder el pendulo
        "t_loss_ms": round(t_loss_ms, 1) if t_loss_ms is not None else None,
        "alpha_err_at_handoff_deg": round(float(err4[0]), 1),
        # H3: contra el techo EFECTIVO, no contra LQR_PWM_MAX, y sin el catch
        "n_post_catch": int(th_p.size),
        "sat_frac": round(sat, 3) if sat is not None else None,
        # La prueba ingenua, al lado, para que la diferencia sea auditable
        "sat_frac_naive": round(float((pwm_p >= pwm_max).mean()), 3) if th_p.size else None,
        "pwm_mean": round(float(pwm_p.mean()), 1) if th_p.size else None,
        "theta_max_m4_deg": round(float(np.abs(th4).max()), 1),
        "theta_final_deg": round(float(th4[-1]), 1),
        "limit_hit_in_m4": bool(np.abs(th4).max() > SERVO_LIMIT_DEG),
        "alpha_final_err_deg": round(float(err4[-1]), 1),
    }


def _med(grp: list[dict], key: str) -> float | None:
    vals = [r[key] for r in grp if r.get(key) is not None]
    return statistics.median(vals) if vals else None


def veredicto(rows: list[dict]) -> None:
    ok = [r for r in rows if r["handed_off"] and r.get("t_loss_ms") is not None]
    print(f"\n=== resultado (n={len(rows)} intentos, {len(ok)} con traspaso y perdida medida) ===")
    sin = [r for r in rows if not r["handed_off"]]
    if sin:
        print(f"  {len(sin)} sin traspaso, reportados aparte y NO promediados: "
              f"{[(r['cond'], r['rep']) for r in sin]}")
    if not ok:
        print("  ningun intento utilizable: no hay nada que decir del LQR")
        return

    grupos = {c: [r for r in ok if r["cond"] == c] for c in CONDITIONS}
    for name, grp in grupos.items():
        if not grp:
            continue
        print(f"\n  {name}  (n={len(grp)})")
        print(f"    t_loss ms         {sorted(r['t_loss_ms'] for r in grp)}")
        print(f"    saturacion        {sorted(r['sat_frac'] for r in grp if r['sat_frac'] is not None)}"
              f"   (ingenua: {sorted(r['sat_frac_naive'] for r in grp if r['sat_frac_naive'] is not None)})")
        print(f"    theta max         {sorted(r['theta_max_m4_deg'] for r in grp)}")
        print(f"    alive_ms (viejo)  {sorted(r['alive_ms'] for r in grp)}")
        print(f"    err alpha entrega {sorted(r['alpha_err_at_handoff_deg'] for r in grp)}")

    ctrl = grupos.get("control", [])
    if not ctrl:
        print("\n  sin control utilizable: no se evalua ningun criterio")
        return

    # Criterio 1 — el control tiene que reproducir la referencia de 500 Hz
    tl_c = _med(ctrl, "t_loss_ms")
    print(f"\n  1. control reproduce la referencia (t_loss 0-86 ms): "
          f"{tl_c:.0f} ms  {'OK' if tl_c is not None and tl_c <= 130 else 'FUERA DE RANGO'}")
    if tl_c is not None and tl_c > 130:
        print("     El banco cambio. Rehacer la linea base antes de leer nada mas.")

    # Criterio 2 — H3, re-verificacion
    sat_c = _med(ctrl, "sat_frac")
    if sat_c is not None:
        print(f"  2. H3 (saturacion del control > 50%): {sat_c:.1%}  "
              f"{'reproduce' if sat_c > 0.50 else 'NO reproduce'}")

    # Criterio 3 — la ventana del catch, por factor 3 en la mediana de t_loss.
    # SOLO sobre las entregas buenas: con una entrega mala el pendulo ya esta fuera de la
    # banda en el traspaso (t_loss = 0) y no hay nada que el catch pueda haber arruinado.
    # Medido el 2026-08-05: concordancia 10/10 entre "|alpha| >= 165" y "t_loss > 0".
    nc = grupos.get("nocatch", [])
    good_c = [r for r in ctrl if r["alpha_err_at_handoff_deg"] <= HANDOFF_GOOD_ERR_DEG]
    good_n = [r for r in nc if r["alpha_err_at_handoff_deg"] <= HANDOFF_GOOD_ERR_DEG]
    print(f"\n  3. ventana del catch — entregas buenas (err <= {HANDOFF_GOOD_ERR_DEG:.0f} deg): "
          f"control {len(good_c)}/{len(ctrl)}, nocatch {len(good_n)}/{len(nc)}")
    if len(good_c) < 3 or len(good_n) < 3:
        print("     NO SE EVALUA: hacen falta >= 3 entregas buenas por condicion.")
        print("     Repetir con mas reps; un veredicto sobre n=2 no es un veredicto.")
    else:
        g_c, g_n = _med(good_c, "t_loss_ms"), _med(good_n, "t_loss_ms")
        f = g_n / g_c if g_c else float("inf")
        print(f"     t_loss {g_c:.0f} -> {g_n:.0f} ms (x{f:.2f}, hace falta x3)")
        if f >= 3.0:
            print("     CULPABLE: quitar el catch retiene el pendulo mucho mas tiempo.")
            print("     Falta separar H1 (direccion aleatoria) de H2 (el LQR no corre).")
        else:
            print("     DESCARTADA: la sospecha pasa entera a la saturacion (H3) y a las")
            print("     ganancias. Es un resultado, no un fracaso de la tanda.")

    # Criterio 6 — la entrega es covariable, no ruido. Va ANTES de los criterios que
    # comparan condiciones, porque decide si esas comparaciones significan algo.
    covariable(ok)

    # Criterio 4 — H7: baja la excursion del brazo sin empeorar t_loss.
    # Se evalua sobre el RESIDUO de t_loss tras descontar el error de entrega. Comparar
    # medianas crudas seria violar el criterio 6: una condicion a la que le tocaron mejores
    # entregas se ve mejor sin haber probado nada. (La primera version de este bloque
    # comparaba medianas crudas y dio un "CONFIRMADA" falso el 2026-08-05. Mismo fallo que
    # el `c1 >= 4` del m5: criterio bien escrito, mal implementado.)
    h7 = grupos.get("h7", [])
    if h7 and len(ok) >= 6:
        res = residuos(ok)
        r_c, r_h = res.get("control"), res.get("h7")
        th_c, th_h = _med(ctrl, "theta_max_m4_deg"), _med(h7, "theta_max_m4_deg")
        spread = max(abs(x) for g in res.values() for x in g["all"])
        okk = r_h is not None and r_c is not None and (r_h["med"] - r_c["med"]) > spread
        print("\n  4. H7 (lqr3 negativo), sobre el residuo de t_loss:")
        print(f"     residuo control {r_c['med']:+.1f} ms  vs  h7 {r_h['med']:+.1f} ms   "
              f"(dispersion intra-condicion +-{spread:.1f})")
        print(f"     theta max {th_c:.1f} -> {th_h:.1f} deg  (las dos contra el tope de 95)")
        print(f"     {'CONFIRMADA' if okk else 'NO CONFIRMADA'}")


def residuos(ok: list[dict]) -> dict:
    """t_loss con el efecto de la entrega descontado, por condicion."""
    e = np.array([r["alpha_err_at_handoff_deg"] for r in ok])
    t = np.array([r["t_loss_ms"] for r in ok])
    m, b = np.polyfit(e, t, 1)
    out: dict = {}
    for c in CONDITIONS:
        idx = [i for i, r in enumerate(ok) if r["cond"] == c]
        if not idx:
            continue
        res = t[idx] - (m * e[idx] + b)
        out[c] = {"med": float(statistics.median(res)), "all": [float(x) for x in res]}
    return out


def covariable(ok: list[dict]) -> None:
    """Criterio 6: cuanto de t_loss explica la entrega, antes de atribuir nada a la condicion."""
    e = np.array([r["alpha_err_at_handoff_deg"] for r in ok])
    t = np.array([r["t_loss_ms"] for r in ok])
    if e.size < 4 or e.std() < 1e-6:
        return
    r = float(np.corrcoef(e, t)[0, 1])
    m, b = np.polyfit(e, t, 1)
    print(f"\n  6. covariable — t_loss vs error de entrega (n={e.size}): r = {r:+.3f}, "
          f"R2 = {r**2:.3f}")
    print(f"     ajuste t_loss = {m:.2f}*err + {b:.1f}; cruza cero en err = {-b / m:.1f} deg "
          f"(alpha = {180 + b / m:.1f})")
    for c in CONDITIONS:
        errs = [r2["alpha_err_at_handoff_deg"] for r2 in ok if r2["cond"] == c]
        if errs:
            print(f"     err de entrega {c:<8} mediana {statistics.median(errs):>5.1f}  {sorted(errs)}")
    if r**2 > 0.5:
        print("     >> La entrega explica la mayor parte de la varianza. Cualquier diferencia")
        print("        entre condiciones hay que leerla sobre el residuo, no sobre la mediana.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default="192.168.4.1")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--max-s", type=float, default=20.0)
    args = ap.parse_args()

    link = QubeLink(args.ip)
    d = link.state()
    print(f"Placa: mode={d.get('mode')} ina_ok={d.get('ina_ok')} v_bus={d.get('v_bus')}")
    if not d.get("ina_ok"):
        raise SystemExit("INA219 caido: sin proteccion por calado no se energiza el motor.")
    if d.get("lqr_alive_ms") is None:
        raise SystemExit("Firmware sin `lqr_alive_ms`: hay que flashear >= v1.58.5.")
    # Con `ina_ok` verdadero, la proteccion por tension esta ACTIVA en los dos modos que usa
    # esta campana (`:3722` para el LQR, `:4031` para el swing-up) y por debajo de 12.5 V
    # hace `pwm = 0; setMotor(0); return`. O sea que con la fuente del motor apagada la
    # tanda entera corre con el motor mudo y produce 15 filas de nulos que parecen una
    # campana fallida. Paso el 2026-08-05: v_bus = 4.01 V, la ESP32 viva por USB y nada mas.
    v_bus = float(d.get("v_bus") or 0.0)
    if v_bus < BROWNOUT_CUT_V:
        raise SystemExit(
            f"v_bus = {v_bus:.2f} V, por debajo del corte por brownout ({BROWNOUT_CUT_V} V): "
            "el firmware anula todo comando de motor. Encender la fuente del motor."
        )
    if v_bus < BROWNOUT_DERATE_V:
        raise SystemExit(
            f"v_bus = {v_bus:.2f} V, en la banda de reduccion (< {BROWNOUT_DERATE_V} V): el "
            "firmware escala el PWM por tension y la saturacion medida no seria atribuible."
        )

    DATA.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    try:
        # Intercaladas: rep externo, condicion interno. El banco deriva dentro de una
        # sesion (Etapa 1, las dos curvas de kd se movieron enteras en un dia) y medir
        # en bloques confunde la deriva con el efecto.
        for rep in range(1, args.reps + 1):
            for cond in CONDITIONS:
                print(f"\n--- rep {rep}/{args.reps}  cond={cond} ---")
                try:
                    r = attempt(link, cond, rep, args.max_s)
                except Exception as exc:
                    print(f"  ERROR: {exc}")
                    link.send({"m": 0})
                    continue
                if r is None:
                    continue
                if not r["handed_off"]:
                    print("  SIN TRASPASO (no cuenta para el LQR)")
                else:
                    tl = r["t_loss_ms"]
                    sat = r["sat_frac"]
                    print(f"  t_loss={'nunca' if tl is None else f'{tl:.0f} ms'}"
                          f"  sat={'-' if sat is None else f'{sat:.1%}'}"
                          f"  theta_max={r['theta_max_m4_deg']:.1f}"
                          f"  entrega err={r['alpha_err_at_handoff_deg']:.1f} deg"
                          f"  (alive={r['alive_ms']} ms)")
                rows.append(r)
    finally:
        link.send({"m": 0})
        # Dejar el firmware como estaba: lqr3 vuelve a su default compilado.
        link.send({"lqr3": CONDITIONS["control"]["lqr3"]})

    (DATA / "sweep.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    if rows:
        veredicto(rows)


if __name__ == "__main__":
    main()
