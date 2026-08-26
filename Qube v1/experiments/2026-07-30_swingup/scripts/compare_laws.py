"""P2 — A/B entre la ley de bombeo resonante (historica) y la de energia (Astrom-Furuta).

Se incluye la resonante como CONTROL en la misma tanda: comparar contra numeros de
hace media hora arrastraria cualquier deriva del banco (temperatura, friccion, la
tension de bateria que fue cayendo). El signo de la ley nueva se prueba en ambos
sentidos porque depende de la convencion de cableado, que no se puede deducir aca.
"""
import json, math, statistics, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from sweep_pumpref import Qube, peaks_of, DATA, SAMPLE_DT

CONFIGS = [
    ("resonante",      dict(pl=0, sp=50, pc=0, pr=70)),
    ("energia sp=50",  dict(pl=1, sp=50, pc=0, pn=1, pg=8000)),
    ("energia sp=70",  dict(pl=1, sp=70, pc=0, pn=1, pg=8000)),
]

def homing_retry(q, n=3):
    # P3: el homing falla ~1 de cada 4 tras modos energeticos (calado falso con el
    # pendulo agitado). Reintentar es la mitigacion mientras la causa raiz siga abierta.
    for i in range(n):
        try: return q.homing()
        except RuntimeError as e:
            if i == n-1: raise
            print(f"    homing fallo ({e}); reintento {i+2}/{n}"); time.sleep(3.0)

def run(q, cfg, secs):
    homing_retry(q)
    q.cmd(**cfg)
    q.cmd(m=5)
    rows, t0 = [], time.monotonic()
    while (t := time.monotonic() - t0) < secs:
        try: d = q.state()
        except Exception: time.sleep(SAMPLE_DT); continue
        rows.append({"t_s": round(t,4), "mode": d.get("mode"),
                     "alpha_deg": d.get("pend_position_deg"),
                     "theta_deg": d.get("position_deg"), "pwm": d.get("pwm")})
        if abs(float(d["position_deg"])) > 88.0: break   # aborto del cliente
        if d.get("mode") == 0: break
        time.sleep(SAMPLE_DT)
    q.cmd(m=0)
    inm = [r for r in rows if r["mode"] == 5]
    pk = peaks_of(inm)
    tail = [v for _,v in pk[len(pk)*2//3:]] if len(pk) >= 6 else [v for _,v in pk]
    meseta = statistics.median(tail) if tail else 0.0
    th = [abs(float(r["theta_deg"])) for r in inm]
    return {"picos": len(pk), "meseta": round(meseta,2),
            "pico_max": round(max((v for _,v in pk), default=0.0),2),
            "E_ratio": round((1-math.cos(math.radians(meseta)))/2, 4),
            "theta_max": round(max(th, default=0.0),1),
            "murio": any(r["mode"] == 0 for r in rows)}

def main():
    q = Qube("192.168.100.50")
    out = []
    for name, cfg in CONFIGS:
        for rep in (1,2):
            print(f"\n--- {name}  rep {rep} ---")
            try: r = run(q, cfg, 22.0)
            except Exception as e:
                print(f"    ERROR: {e}"); q.cmd(m=0); continue
            r.update(cfg=name, rep=rep); print("    " + json.dumps(r)); out.append(r)
    q.cmd(m=0, pl=0, sp=50, pc=0, pr=70)
    (DATA/"compare_laws.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print("\n=== resumen ===")
    print(f"{'config':<16}{'meseta':>9}{'E/E*':>8}{'pico max':>10}{'theta max':>11}{'murio':>7}")
    for name,_ in CONFIGS:
        g=[r for r in out if r["cfg"]==name]
        if not g: continue
        print(f"{name:<16}{statistics.mean(r['meseta'] for r in g):>9.1f}"
              f"{statistics.mean(r['E_ratio'] for r in g):>8.3f}"
              f"{max(r['pico_max'] for r in g):>10.1f}"
              f"{max(r['theta_max'] for r in g):>11.1f}"
              f"{sum(r['murio'] for r in g):>7}")
main()
