"""Construye presentacion_qube.html: un deck HTML autocontenido.

Los Artifacts aplican una CSP que bloquea todo host externo, asi que cada recurso
--ecuaciones, figuras y fuentes-- se incrusta en el propio archivo.

    uv run --with pillow --with fonttools --with brotli build_assets.py

Las ecuaciones se compilan desde equations/eqs.tex y se convierten a SVG con los
glifos trazados. El orden de EQ_IDS debe coincidir con el orden de las ecuaciones
en ese archivo.
"""

from __future__ import annotations

import base64
import io
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EQ_DIR = ROOT / "equations"
FIG_DIR = ROOT.parent / "tesis_usach" / "imagenes"
LM_DIR = Path("C:/texlive/2026/texmf-dist/fonts/opentype/public/lm")

TEMPLATE = ROOT / "deck.src.html"
OUTPUT = ROOT / "presentacion_qube.html"

# El indice en esta lista es la pagina en eqs.tex (1-based).
EQ_IDS = [
    "lazo_cerrado", "motor_electrica", "motor_backemf", "motor_mecanica",
    "motor_torque", "motor_ss", "motor_matrices", "motor_primer_orden",
    "motor_km_taum", "motor_gw", "motor_gpos", "enc_resolucion", "enc_fmax",
    "enc_nyquist", "el_theta", "el_alpha", "pend_ss", "pend_A", "pend_B",
    "pid_continuo", "pid_transferencia", "pid_discreto", "anti_windup", "ema",
    "lqr_costo", "riccati", "lqr_K", "tau_lqr", "energia", "energia_target",
    "swingup_u", "lqr_impl", "k4_boost", "filtro_complementario",
    "newton_euler", "soft_saturation", "fc_rc", "histeresis", "snr", "mdp",
]

FIGURES = [
    "diagrama_bloques", "topologia_potencia", "senal_encoder",
    "fig_pid_tuning", "fig_ke_sweep", "fig_capture_distribution",
    "fig_gantt", "flujo_datos", "system_wiring",
]

# Graficos de MLflow, generados por charts.py como SVG con var(--viz-*).
CHARTS = ["rl_curvas", "rl_hold", "rl_scatter"]

FONTS = {"lm-regular": "lmroman10-regular.otf", "lm-bold": "lmroman10-bold.otf"}

# Marca temporal para los ids de glifo, resuelta en cada insercion.
NS_MARK = "\x00NS\x00"

# Las claves llevan guion (lm-regular), asi que el patron debe aceptarlo.
PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[A-Za-z0-9_-]+)\}\}")

# El .tex se compone a 12pt: dividir las dimensiones en pt por 12 las expresa en
# em, de modo que la ecuacion escala con el font-size del contenedor.
TEX_PT = 12.0

MAX_FIG_WIDTH = 1500


def run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"fallo {cmd[0]}:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")


def build_equations() -> None:
    """Compila eqs.tex y emite un SVG por ecuacion, con los glifos como trazos.

    --currentcolor hace que dvisvgm emita fill='currentColor' en vez de negro,
    para que las ecuaciones sigan el color del tema.
    """
    run(["latex", "-interaction=nonstopmode", "-halt-on-error", "eqs.tex"], EQ_DIR)
    for stale in EQ_DIR.glob("eq_*.svg"):
        stale.unlink()
    run(
        ["dvisvgm", "--page=1-", "--no-fonts", "--exact-bbox", "--currentcolor",
         "--optimize=all", "--output=eq_%2p.svg", "eqs.dvi"],
        EQ_DIR,
    )


def load_equation(page: int, eq_id: str) -> str:
    """Lee un SVG de ecuacion y lo deja listo para incrustar, salvo los ids.

    Los ids quedan marcados con el prefijo NS_MARK, que namespace_equation()
    sustituye por un prefijo unico en cada insercion.
    """
    svg = (EQ_DIR / f"eq_{page:02d}.svg").read_text(encoding="utf-8")

    svg = re.sub(r"<\?xml[^>]*\?>\s*", "", svg)
    svg = re.sub(r"<!--.*?-->\s*", "", svg, flags=re.DOTALL)

    ids = set(re.findall(r"\bid='([^']+)'", svg))
    for old in sorted(ids, key=len, reverse=True):
        svg = svg.replace(f"id='{old}'", f"id='{NS_MARK}{old}'")
        svg = svg.replace(f"href='#{old}'", f"href='#{NS_MARK}{old}'")

    m = re.search(r"width='([\d.]+)pt' height='([\d.]+)pt'", svg)
    if not m:
        sys.exit(f"ecuacion {eq_id}: no se pudo leer width/height")
    w_em, h_em = float(m.group(1)) / TEX_PT, float(m.group(2)) / TEX_PT

    # Las dimensiones absolutas en pt impiden que la ecuacion escale; se sustituyen
    # por un tamano en em y se deja que el viewBox mantenga la proporcion.
    svg = svg.replace(
        m.group(0),
        f"class='eq-svg' role='img' aria-label='ecuacion {eq_id}' "
        f"style='width:{w_em:.3f}em;height:{h_em:.3f}em'",
        1,
    )
    return svg.strip()


def namespace_equation(svg: str, occurrence: int) -> str:
    """Aisla los ids de glifo de esta insercion concreta.

    dvisvgm numera los glifos por documento (g0-65, g1-12...), asi que los 40 SVG
    reusan los mismos ids. Al concatenarlos en un unico HTML los <use> resolverian
    contra el primer id homonimo del documento -- es decir, contra el glifo de otra
    ecuacion. El prefijo debe ser unico por *insercion*, no por ecuacion: una misma
    ecuacion puede aparecer en dos diapositivas.
    """
    return svg.replace(NS_MARK, f"q{occurrence}-")


def load_figure(name: str) -> str:
    from PIL import Image

    src = FIG_DIR / f"{name}.png"
    img = Image.open(src)
    if img.width > MAX_FIG_WIDTH:
        h = round(img.height * MAX_FIG_WIDTH / img.width)
        img = img.resize((MAX_FIG_WIDTH, h), Image.LANCZOS)
    if img.mode not in ("RGB", "RGBA", "P"):
        img = img.convert("RGB")

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def load_font(filename: str) -> str:
    """Subsetea Latin Modern y la devuelve como data URI woff2.

    Es la misma familia con la que compila la tesis, de modo que los titulos del
    deck y los SVG de las ecuaciones comparten tipografia.
    """
    from fontTools import subset

    opts = subset.Options(
        layout_features=["kern", "liga"],
        desubroutinize=True,
        notdef_outline=True,
        recommended_glyphs=True,
    )
    opts.flavor = "woff2"
    font = subset.load_font(str(LM_DIR / filename), opts)
    subsetter = subset.Subsetter(options=opts)
    subsetter.populate(
        unicodes=[
            *range(0x20, 0x7F),      # ASCII imprimible
            *range(0xA0, 0x100),     # Latin-1: acentos y enye
            0x2013, 0x2014,          # rayas
            0x2018, 0x2019, 0x201C, 0x201D,
            0x2026, 0x00B0, 0x00B7,  # puntos suspensivos, grado, punto medio
            0x2192, 0x2190,          # flechas
            0x03B1, 0x03B8, 0x03C4,  # alpha, theta, tau
        ]
    )
    subsetter.subset(font)

    buf = io.BytesIO()
    font.save(buf)
    font.close()
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:font/woff2;base64,{b64}"


def load_chart(name: str) -> str:
    import re as _re

    svg = (ROOT / "charts" / f"{name}.svg").read_text(encoding="utf-8")
    return _re.sub(r"<\?xml[^>]*\?>\s*", "", svg).strip()


def main() -> None:
    if not TEMPLATE.exists():
        sys.exit(f"falta la plantilla {TEMPLATE}")

    print("generando graficos de mlflow...")
    import charts

    charts.main()

    print("compilando ecuaciones...")
    build_equations()

    tokens: dict[str, str] = {}
    for page, eq_id in enumerate(EQ_IDS, start=1):
        tokens[f"EQ:{eq_id}"] = load_equation(page, eq_id)
    print(f"  {len(EQ_IDS)} ecuaciones")

    for name in FIGURES:
        tokens[f"IMG:{name}"] = load_figure(name)
    print(f"  {len(FIGURES)} figuras")

    for name in CHARTS:
        tokens[f"CHART:{name}"] = load_chart(name)
    print(f"  {len(CHARTS)} graficos")

    for key, filename in FONTS.items():
        tokens[f"FONT:{key}"] = load_font(filename)
    print(f"  {len(FONTS)} fuentes")

    template = TEMPLATE.read_text(encoding="utf-8")
    seen: set[str] = set()
    counter = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal counter
        key = match.group(1)
        if key not in tokens:
            sys.exit(f"placeholder desconocido en la plantilla: {{{{{key}}}}}")
        seen.add(key)
        if key.startswith("EQ:"):
            counter += 1
            return namespace_equation(tokens[key], counter)
        return tokens[key]

    html, n = PLACEHOLDER.subn(replace, template)

    if NS_MARK in html:
        sys.exit("quedaron marcas de namespace sin resolver")
    if PLACEHOLDER.search(html):
        sys.exit("quedaron placeholders sin sustituir")

    unused = sorted(set(tokens) - seen)
    if unused:
        print(f"  aviso: no usados en la plantilla -> {', '.join(unused)}")

    OUTPUT.write_text(html, encoding="utf-8")
    print(f"\n{OUTPUT.name}: {n} inserciones ({counter} ecuaciones), "
          f"{OUTPUT.stat().st_size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
