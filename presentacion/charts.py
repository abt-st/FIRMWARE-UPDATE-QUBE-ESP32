"""Genera los graficos de MLflow como SVG inline para la presentacion.

Solo se comparan corridas con la MISMA funcion de recompensa (linear_alpha):
ep_rew_mean no es comparable entre recompensas distintas. Se descartan las
corridas de humo (<10k pasos), que solo verifican que el pipeline arranca.

Paleta validada con scripts/validate_palette.js de la skill dataviz:
  azul + naranja, ambos modos, peor ΔE adyacente ~97 (protan).
Los colores se emiten como var(--viz-*) para que el deck los cambie por tema;
ejes y texto usan currentColor.

    uv run --with numpy python charts.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "mlflow.db"
OUT = ROOT / "charts"

SMOKE_STEPS = 10_000       # corridas por debajo de esto solo prueban el pipeline
HOLD_THRESHOLD = 1.0       # balance_rate cuenta episodios que sostienen >= 1 s
EPISODE_S = 10.0           # 500 pasos a 50 Hz

# El panel del deck es mas alto que ancho en proporcion 16:9; un viewBox muy
# apaisado se veria encajonado con franjas vacias arriba y abajo.
W, H = 1000, 680
# Titulo en 20, subtitulo en 42, leyenda en 66: cada uno en su renglon.
PLOT_TOP = 96
PAD = {"r": 26, "b": 72, "l": 82}


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------- datos


def load() -> tuple[list[dict], dict[str, list[tuple[int, float]]]]:
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    runs = {
        r["uid"]: dict(r)
        for r in c.execute(
            """select r.run_uuid uid, r.name run, e.name exp,
                 max(case when p.key='reward' then p.value end) reward,
                 max(case when p.key='near_upright_prob' then p.value end) nup,
                 max(case when p.key='timesteps' then p.value end) ts,
                 max(case when p.key='seed' then p.value end) seed,
                 max(case when p.key='potential' then p.value end) pot
               from runs r join experiments e using(experiment_id)
               left join params p using(run_uuid) group by r.run_uuid"""
        )
    }
    for r in c.execute(
        "select run_uuid, key, value from latest_metrics where key like 'final/%'"
    ):
        if r["run_uuid"] in runs:
            runs[r["run_uuid"]][r["key"].split("/")[1]] = r["value"]

    keep = [
        v for v in runs.values()
        if v["reward"] == "linear_alpha"
        and "max_hold_s" in v
        and int(v["ts"] or 0) >= SMOKE_STEPS
    ]
    for v in keep:
        # near_upright_prob>0 es el reinicio curricular cerca de la vertical.
        v["curriculum"] = float(v["nup"] or 0) > 0
        v["steps"] = int(v["ts"])
        # Sin el sufijo pbrs, dos corridas distintas del mismo seed y presupuesto
        # comparten etiqueta: solo se diferencian por el reward shaping.
        base = "curriculum" if v["curriculum"] else "control"
        shaping = "+pbrs" if (v["pot"] and v["pot"] != "None") else ""
        v["label"] = f"{base}{shaping} · s{v['seed']} · {v['steps'] // 1000}k"

    curves: dict[str, list[tuple[int, float]]] = {}
    for v in keep:
        pts = list(
            c.execute(
                "select step, value from metrics where run_uuid=? and key='rollout/ep_rew_mean' order by step",
                (v["uid"],),
            )
        )
        if pts:
            curves[v["uid"]] = [(p[0], p[1]) for p in pts]
    c.close()
    keep.sort(key=lambda v: -v["max_hold_s"])
    return keep, curves


# ---------------------------------------------------------------- helpers svg


def frame(title: str, sub: str, aria: str, body: str, legend: str) -> str:
    return f"""<svg class="viz" viewBox="0 0 {W} {H}" role="img" aria-label="{esc(aria)}"
     xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
  <title>{esc(title)}</title><desc>{esc(aria)}</desc>
  <text class="viz-title" x="0" y="20">{esc(title)}</text>
  <text class="viz-sub" x="0" y="42">{esc(sub)}</text>
  {legend}
  {body}
</svg>"""


def legend(items: list[tuple[str, str]], x: int = 0, y: int = 68) -> str:
    out, cx = [], x
    for label, var in items:
        out.append(
            f'<rect x="{cx}" y="{y - 9}" width="10" height="10" rx="2" fill="var({var})"/>'
            f'<text class="viz-legend" x="{cx + 16}" y="{y}">{esc(label)}</text>'
        )
        cx += 26 + int(len(label) * 6.7)
    return "".join(out)


def axes(x0, y0, x1, y1, xticks, yticks, xlab, ylab) -> str:
    p = [f'<g class="viz-grid">']
    for yv, ypx in yticks:
        p.append(f'<line x1="{x0}" y1="{ypx:.1f}" x2="{x1}" y2="{ypx:.1f}"/>')
    p.append("</g>")
    p.append(f'<g class="viz-axis"><line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}"/>'
             f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}"/></g>')
    for yv, ypx in yticks:
        p.append(f'<text class="viz-tick" x="{x0 - 10}" y="{ypx + 4:.1f}" text-anchor="end">{yv}</text>')
    for xv, xpx in xticks:
        p.append(f'<text class="viz-tick" x="{xpx:.1f}" y="{y1 + 20}" text-anchor="middle">{xv}</text>')
    p.append(f'<text class="viz-axlab" x="{(x0 + x1) / 2:.0f}" y="{y1 + 46}" text-anchor="middle">{esc(xlab)}</text>')
    p.append(f'<text class="viz-axlab" transform="translate({x0 - 56},{(y0 + y1) / 2:.0f}) rotate(-90)" '
             f'text-anchor="middle">{esc(ylab)}</text>')
    return "".join(p)


# ---------------------------------------------------------------- graficos


def chart_curves(runs, curves) -> str:
    x0, x1 = PAD["l"], W - PAD["r"] - 34
    y0, y1 = PLOT_TOP, H - PAD["b"]
    xmax = max(s for uid in curves for s, _ in curves[uid])
    ymin, ymax = -80.0, 520.0

    sx = lambda s: x0 + (s / xmax) * (x1 - x0)
    sy = lambda v: y1 - ((v - ymin) / (ymax - ymin)) * (y1 - y0)

    yt = [(str(v), sy(v)) for v in (0, 100, 200, 300, 400, 500)]
    xt = [(f"{v // 1000}k", sx(v)) for v in (0, 100_000, 200_000, 300_000, 400_000, 500_000) if v <= xmax]

    body = [axes(x0, y0, x1, y1, xt, yt, "Pasos de entrenamiento", "Recompensa media por episodio")]

    by_uid = {v["uid"]: v for v in runs}
    # Las de control primero, para que las de curriculum queden encima.
    for uid in sorted(curves, key=lambda u: by_uid[u]["curriculum"]):
        v = by_uid[uid]
        pts = curves[uid]
        step = max(1, len(pts) // 120)
        d = " ".join(
            f"{'M' if i == 0 else 'L'}{sx(s):.1f},{sy(val):.1f}"
            for i, (s, val) in enumerate(pts[::step])
        )
        var = "--viz-1" if v["curriculum"] else "--viz-2"
        win = v["balance_rate"] > 0
        body.append(
            f'<path d="{d}" fill="none" stroke="var({var})" stroke-width="2" '
            f'stroke-linejoin="round" stroke-opacity="{1 if win else 0.42}">'
            f'<title>{esc(v["label"])} — hold {v["max_hold_s"]:.2f} s</title></path>'
        )

    # Etiquetas directas solo sobre las dos corridas que equilibran. Terminan a la
    # misma recompensa (480 y 474), asi que se apilan en vez de superponerse.
    winners = sorted((v for v in runs if v["balance_rate"] > 0 and v["uid"] in curves),
                     key=lambda v: -v["ep_rew_mean"])
    for v, dy in zip(winners, (-16, 26)):
        s, val = curves[v["uid"]][-1]
        body.append(
            f'<circle cx="{sx(s):.1f}" cy="{sy(val):.1f}" r="4.5" fill="var(--viz-1)" '
            f'stroke="var(--viz-surface)" stroke-width="2"/>'
            f'<text class="viz-label" x="{sx(s) - 14:.1f}" y="{sy(val) + dy:.1f}" text-anchor="end">'
            f'semilla {v["seed"]} · equilibra {v["max_hold_s"]:.1f} s</text>'
        )

    lg = legend([("Con curriculum (500k y 300k pasos)", "--viz-1"),
                 ("Sin curriculum (150k–300k pasos)", "--viz-2")])
    return frame(
        "La recompensa sube en todas las corridas",
        f"{len(curves)} corridas con reward = linear_alpha · las opacas nunca llegan a equilibrar",
        "Curvas de recompensa media por episodio. Todas las corridas aprenden a levantar el péndulo "
        "y la recompensa converge, pero solo dos de trece llegan a sostenerlo.",
        "".join(body), lg,
    )


def chart_hold(runs) -> str:
    x0, x1 = 250, W - PAD["r"] - 44
    y0, y1 = PLOT_TOP + 8, H - PAD["b"] + 20
    n = len(runs)
    band = (y1 - y0) / n
    bh = min(20.0, band - 6)
    xmax = 5.0
    sx = lambda v: x0 + (v / xmax) * (x1 - x0)

    body = [f'<g class="viz-grid">']
    for v in (0, 1, 2, 3, 4, 5):
        body.append(f'<line x1="{sx(v):.1f}" y1="{y0}" x2="{sx(v):.1f}" y2="{y1:.1f}"/>')
    body.append("</g>")
    for v in (0, 1, 2, 3, 4, 5):
        body.append(f'<text class="viz-tick" x="{sx(v):.1f}" y="{y1 + 22:.1f}" text-anchor="middle">{v}</text>')
    body.append(f'<text class="viz-axlab" x="{(x0 + x1) / 2:.0f}" y="{y1 + 46:.0f}" text-anchor="middle">'
                "Hold máximo continuo (s) · el episodio dura 10 s</text>")

    for i, v in enumerate(runs):
        cy = y0 + i * band + band / 2
        var = "--viz-1" if v["curriculum"] else "--viz-2"
        w = max(1.5, sx(v["max_hold_s"]) - x0)
        op = 1 if v["balance_rate"] > 0 else 0.5
        body.append(
            f'<rect x="{x0}" y="{cy - bh / 2:.1f}" width="{w:.1f}" height="{bh:.1f}" rx="4" '
            f'fill="var({var})" fill-opacity="{op}">'
            f'<title>{esc(v["label"])} — hold {v["max_hold_s"]:.2f} s, '
            f'balance_rate {v["balance_rate"]:.2f}</title></rect>'
        )
        body.append(f'<text class="viz-tick" x="{x0 - 12}" y="{cy + 4:.1f}" text-anchor="end">{esc(v["label"])}</text>')
        body.append(f'<text class="viz-val" x="{x0 + w + 8:.1f}" y="{cy + 4:.1f}">{v["max_hold_s"]:.2f}</text>')

    tx = sx(HOLD_THRESHOLD)
    body.append(f'<line class="viz-rule" x1="{tx:.1f}" y1="{y0 - 12}" x2="{tx:.1f}" y2="{y1:.1f}"/>')
    body.append(f'<text class="viz-rule-lab" x="{tx + 8:.1f}" y="{y0 - 16}">umbral de equilibrio: 1 s</text>')

    lg = legend([("Con curriculum", "--viz-1"), ("Sin curriculum", "--viz-2")])
    return frame(
        "Solo dos de trece corridas superan el umbral",
        "Ninguna configuración sin curriculum pasa de 0,3 s",
        "Hold máximo continuo por corrida. Solo dos corridas, ambas con curriculum y 500 mil pasos, "
        "superan el umbral de un segundo. La mejor alcanza 4,43 segundos de los 10 posibles.",
        "".join(body), lg,
    )


def chart_scatter(runs) -> str:
    x0, x1 = PAD["l"] + 10, W - PAD["r"] - 30
    y0, y1 = PLOT_TOP, H - PAD["b"]
    sx = lambda v: x0 + ((v - 260) / (500 - 260)) * (x1 - x0)
    sy = lambda v: y1 - (v / 5.0) * (y1 - y0)

    yt = [(f"{v}", sy(v)) for v in (0, 1, 2, 3, 4, 5)]
    xt = [(f"{v}", sx(v)) for v in (300, 350, 400, 450, 500)]
    body = [axes(x0, y0, x1, y1, xt, yt, "Recompensa media final por episodio",
                 "Hold máximo continuo (s)")]

    ty = sy(HOLD_THRESHOLD)
    body.append(f'<line class="viz-rule" x1="{x0}" y1="{ty:.1f}" x2="{x1}" y2="{ty:.1f}"/>')
    body.append(f'<text class="viz-rule-lab" x="{x1}" y="{ty - 8:.1f}" text-anchor="end">umbral de equilibrio</text>')

    for v in runs:
        if v["ep_rew_mean"] < 260:
            continue
        cx, cy = sx(v["ep_rew_mean"]), sy(v["max_hold_s"])
        var = "--viz-1" if v["curriculum"] else "--viz-2"
        body.append(
            f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" fill="var({var})" '
            f'fill-opacity="{0.95 if v["balance_rate"] > 0 else 0.55}" '
            f'stroke="var(--viz-surface)" stroke-width="2">'
            f'<title>{esc(v["label"])} — recompensa {v["ep_rew_mean"]:.0f}, hold {v["max_hold_s"]:.2f} s</title>'
            f"</circle>"
        )

    # Las tres semillas del mismo experimento: misma recompensa, destino distinto.
    seeds = sorted(
        (v for v in runs if v["curriculum"] and v["steps"] == 500_000),
        key=lambda v: -v["max_hold_s"],
    )
    for v, dy in zip(seeds, (-14, -14, 22)):
        cx, cy = sx(v["ep_rew_mean"]), sy(v["max_hold_s"])
        body.append(
            f'<text class="viz-label" x="{cx - 12:.1f}" y="{cy + dy:.1f}" text-anchor="end">'
            f'semilla {v["seed"]}</text>'
        )

    lg = legend([("Con curriculum", "--viz-1"), ("Sin curriculum", "--viz-2")])
    return frame(
        "La recompensa no predice el equilibrio",
        "Tres semillas idénticas, recompensa casi igual, resultados opuestos",
        "Dispersión de recompensa final contra hold máximo. Las tres semillas del mismo experimento "
        "convergen a recompensas casi idénticas (471 a 480) pero sostienen el péndulo 0,33, 3,44 y 4,43 segundos.",
        "".join(body), lg,
    )


def main() -> None:
    OUT.mkdir(exist_ok=True)
    runs, curves = load()
    print(f"corridas comparables (linear_alpha, >={SMOKE_STEPS} pasos): {len(runs)}")
    print(f"  con curriculum: {sum(v['curriculum'] for v in runs)}")
    print(f"  que equilibran: {sum(v['balance_rate'] > 0 for v in runs)}")

    for name, svg in [
        ("rl_curvas", chart_curves(runs, curves)),
        ("rl_hold", chart_hold(runs)),
        ("rl_scatter", chart_scatter(runs)),
    ]:
        (OUT / f"{name}.svg").write_text(svg, encoding="utf-8")
        print(f"  -> charts/{name}.svg ({len(svg) / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
