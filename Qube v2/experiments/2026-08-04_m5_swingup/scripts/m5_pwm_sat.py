"""Cuanta autoridad de PWM deja sin usar el bombeo del modo 5.

Por que hace falta. El firmware afirma en `esp32_qube.ino:1076` —y P11 lo repite— que el
bombeo "satura el PWM el 100% del tiempo, con lo que ke_gain no puede influir". Esa frase
es la razon por la que se dejo de tocar la ganancia del bombeo. Nunca se midio: se dedujo.
Si es falsa, hay margen de actuacion sin usar y el barrido de la referencia de bombeo
(`?pr=`) tiene sentido; si es cierta, pedir mas referencia no puede cambiar nada y no vale
la pena gastar banco.

Cuatro cuidados, cada uno por un error ya cometido en este experimento:

1. **La fase de re-cero corre con `mode == 5`.** Desde v1.58.8 el modo 5 arranca esperando
   quietud (`esp32_qube.ino:3741-3761`) con el motor en cero antes de bombear. Contarla
   diluye la fraccion saturada hacia abajo y hace parecer que sobra margen. Se detecta como
   la corrida inicial de muestras con `pwm == 0` y se descarta.

2. **No todo PWM en modo 5 es el bombeo.** El freno de fin de carrera usa
   `SERVO_BRAKE_PWM = 70` y el freno de giro `SWINGUP_SPIN_BRAKE_PWM = 120`, los dos por
   ENCIMA del tope del bombeo. La ley de bombeo hace `constrain(pwm, -sp, +sp)`, asi que
   `|pwm| > sp` identifica sin ambiguedad una muestra que NO es bombeo. Contarlas como
   saturacion es exactamente el error inverso al del punto 1.

3. **`sp` NO es el techo que el bombeo puede alcanzar.** Lo que el DAQ registra es
   `lastPwmCmd`, que se asigna dentro de `setMotorDirect` (`:1425`), o sea DESPUES de la
   atenuacion por posicion que aplica `setMotor` (`:1447-1451`):

       factor = 1 / (1 + (|theta| / SOFT_SAT_K_DEG)^2),  SOFT_SAT_K_DEG = 200

   El bombeo pide `sp` y lo que sale es `int(sp * factor)`. Comparar contra `sp` a secas
   da 0% de saturacion SIEMPRE —el valor exacto solo se alcanzaria con el brazo en
   theta = 0— y hace concluir que sobra autoridad cuando en realidad el lazo esta pegado a
   su techo. El techo se recalcula por muestra con el `theta_deg` del propio CSV, que es el
   mismo `pos` que alimenta `lastServoPos` (`:3355-3356`).

4. **El `sp` sale del JSON de la campana, no de un 60 hardcodeado.** El nombre del archivo
   ya pisó una tanda entera una vez.

Uso:
    uv run python m5_pwm_sat.py
    uv run python m5_pwm_sat.py --json data/m5_sp60.json
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"

SOFT_SAT_K_DEG = 200.0  # esp32_qube.ino:702


def soft_sat_cap(sp: int, theta_deg: float) -> int:
    """Techo que el bombeo puede alcanzar con el brazo en `theta_deg`.

    Replica `setMotor` (`esp32_qube.ino:1447-1451`): el lazo pide `sp` y el puente H
    recibe `int(sp * factor)`. Es contra ESTO que hay que medir saturacion, no contra `sp`.
    """
    k = abs(theta_deg) / SOFT_SAT_K_DEG
    return int(sp / (1.0 + k * k))


def load(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return [
            {"pwm": float(r["pwm"]), "theta": float(r["theta_deg"]), "mode": int(float(r["mode"]))}
            for r in csv.DictReader(fh)
            if r.get("pwm") not in (None, "") and r.get("mode") not in (None, "")
        ]


def pump_samples(rows: list[dict[str, float]], sp: int) -> tuple[list[tuple[float, int]], int, int]:
    """Fase de bombeo: sin el re-cero inicial y sin las muestras de freno.

    Devuelve ([(|pwm|, techo efectivo)], muestras de re-cero descartadas, muestras de freno).
    """
    in5 = [r for r in rows if r["mode"] == 5]
    # (1) el re-cero: la corrida inicial de ceros, antes del primer PWM del bombeo
    zero_phase = 0
    for r in in5:
        if r["pwm"] != 0.0:
            break
        zero_phase += 1
    pumping = in5[zero_phase:]
    # (2) los frenos: |pwm| > sp no puede venir de la ley de bombeo, que acota a sp
    brake = sum(1 for r in pumping if abs(r["pwm"]) > sp)
    return (
        [(abs(r["pwm"]), soft_sat_cap(sp, r["theta"])) for r in pumping if abs(r["pwm"]) <= sp],
        zero_phase,
        brake,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=str(DATA / "m5_sp60.json"),
                    help="resumen de la campana; de ahi sale el sp real de cada rep")
    args = ap.parse_args()

    summary = {int(r["rep"]): int(r["sp"]) for r in json.loads(Path(args.json).read_text(encoding="utf-8"))}
    stem = Path(args.json).stem  # m5_sp60 -> m5_sp60_r{n}.csv

    print(f"{'rep':>4} {'sp':>3} {'n_bombeo':>9} {'re-cero':>8} {'freno':>6} "
          f"{'sat vs sp':>10} {'sat real':>9} {'|pwm| med':>10} {'techo med':>10}")
    naive_fracs, sat_fracs = [], []
    for rep in sorted(summary):
        csv_path = DATA / f"{stem}_r{rep}.csv"
        if not csv_path.exists():
            print(f"{rep:>4}  (sin CSV: {csv_path.name})")
            continue
        sp = summary[rep]
        pump, n_zero, n_brake = pump_samples(load(csv_path), sp)
        if not pump:
            print(f"{rep:>4} {sp:>3}  (sin muestras de bombeo)")
            continue
        pwm = [v for v, _ in pump]
        # La prueba ingenua, la que da 0% siempre. Se imprime al lado para que la
        # diferencia con la real quede a la vista y no haya que creer en la nota.
        naive = sum(1 for v in pwm if v >= sp) / len(pwm)
        sat = sum(1 for v, cap in pump if v >= cap) / len(pump)
        naive_fracs.append(naive)
        sat_fracs.append(sat)
        print(f"{rep:>4} {sp:>3} {len(pwm):>9} {n_zero:>8} {n_brake:>6} "
              f"{naive:>9.1%} {sat:>8.1%} {statistics.mean(pwm):>10.1f} "
              f"{statistics.mean([c for _, c in pump]):>10.1f}")

    if not sat_fracs:
        return
    med = statistics.median(sat_fracs)
    print(f"\nsaturacion contra el techo efectivo: min {min(sat_fracs):.1%}  mediana {med:.1%}  "
          f"max {max(sat_fracs):.1%}   (n={len(sat_fracs)})")
    print(f"la prueba ingenua (contra sp) habria dado: mediana {statistics.median(naive_fracs):.1%}")
    # Criterio fijado ANTES de correr esto, en el plan del dia.
    print(f"\ncriterio: mediana < 60%  ->  {'PASS' if med < 0.60 else 'FAIL'}")
    if med < 0.60:
        print("  Hay autoridad de PWM sin usar: la afirmacion de :1076 y de P11 no se sostiene,")
        print("  y pedir mas referencia de bombeo (?pr=) puede traducirse en mas energia.")
    else:
        print("  El bombeo ya vive contra su techo: la referencia extra no se puede seguir.")
        print("  Subir ?pr= manda el brazo mas lejos del centro, donde la atenuacion por")
        print("  posicion BAJA el techo todavia mas. No gastar banco en ese barrido.")


if __name__ == "__main__":
    main()
