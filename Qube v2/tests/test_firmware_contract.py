"""Barrera contra el defecto que este proyecto ya pagó cuatro veces.

El patrón tiene nombre propio en el registro: **superficie de control publicada que
ningún lazo lee**. ``?bt=`` vivió desde v1.20 hasta la auditoría del 2026-07-28 siendo
API documentada que el firmware aceptaba y nunca consultaba; ``ke_gain`` no actuaba en el
swing-up por el bug F1; ``?ke=`` sigue abierto como P23; y ``LQR_PWM_MAX`` no era el
límite operativo del modo 4 porque un ``70`` literal lo re-acotaba en cinco ramas. Los
cuatro se encontraron a mano, leyendo código, después de que una campaña midiera ruido.

Estos tests no dependen de Qt a propósito: la única barrera automática que existía
—los tres tests que parsean el ``.ino`` en ``test_app_ui.py``— vive detrás de un
``importorskip("PySide6")`` y CI no instala ese extra, así que nunca se ejecutaba.

**Lo que estos tests SÍ atrapan:** un parámetro HTTP cuya variable no se lee en ninguna
parte fuera de las funciones de superficie, y un comando anunciado en la ayuda serial que
el despachador no atiende.

**Lo que NO atrapan, y hay que saberlo:** el caso ``?ke=`` (P23), donde la variable *sí*
se lee pero el propio lazo la pisa en el primer tick, y el caso ``/rl_cmd?scale=``, donde
la variable se lee en el modo 7 pero no en el 6. Los dos exigen seguir el flujo de datos
y no se detectan mirando presencia de identificadores. Para ésos, la defensa es medir el
mando antes de barrerlo.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIRMWARE_INO = REPO / "src" / "firmware" / "esp32_qube" / "esp32_qube.ino"
REGISTRO_MD = REPO / "docs" / "REGISTRO_PROBLEMAS.md"
HTTP_API_MD = REPO / "docs" / "http_api.md"

# Funciones que exponen o reportan estado. Una aparición del identificador acá NO cuenta
# como "el firmware usa esto": son justamente los lugares donde `bt` se veía vivo.
SURFACE_FUNCTIONS = (
    "handleCmd",
    "handleRlCmd",
    "handleRlState",
    "handleRlStep",
    "handleState",
    "handleDaq",
    "handleDaqRead",
    "getStateJson",
    "printHelp",
    "processSerialCommand",
)

# Los paréntesis externos NO son decorativos: sin ellos la alternancia se extiende sobre
# lo que se concatene después, `const ` sola clasifica cualquier línea como declaración, y
# el test aprueba mandos vivos como si fueran inertes. Pasó al escribirlo.
C_TYPES = (
    r"(?:(?:volatile|static|const|unsigned|signed)\s+|(?:float|double|int|long|bool|char|String|size_t|uint\d+_t)\b)"
)


def _strip_comments(src: str) -> str:
    """Quita comentarios conservando las cadenas. Sin esto, un identificador nombrado en
    un comentario cuenta como uso y el test aprueba lo que debía rechazar."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == '"' or c == "'":
            quote = c
            out.append(c)
            i += 1
            while i < n:
                out.append(src[i])
                if src[i] == "\\":
                    i += 1
                    if i < n:
                        out.append(src[i])
                        i += 1
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            i += 2
            while i + 1 < n and not (src[i] == "*" and src[i + 1] == "/"):
                out.append("\n" if src[i] == "\n" else " ")
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _match_block(code: str, open_at: int) -> int:
    """Devuelve el índice justo después de la llave que cierra la que abre en `open_at`."""
    depth, i, n = 0, open_at, len(code)
    while i < n:
        c = code[i]
        if c in "\"'":
            quote = c
            i += 1
            while i < n:
                if code[i] == "\\":
                    i += 2
                    continue
                if code[i] == quote:
                    break
                i += 1
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise AssertionError("llave sin cerrar al recorrer el firmware")


def _function_spans(code: str) -> dict[str, tuple[int, int]]:
    spans: dict[str, tuple[int, int]] = {}
    for name in SURFACE_FUNCTIONS:
        m = re.search(rf"^[A-Za-z_][\w:<>*&\s]*?\b{re.escape(name)}\s*\([^;{{]*\)\s*\{{", code, re.M)
        if m is None:
            continue
        spans[name] = (m.start(), _match_block(code, code.index("{", m.end() - 1)))
    return spans


@pytest.fixture(scope="module")
def code() -> str:
    return _strip_comments(FIRMWARE_INO.read_text(encoding="utf-8", errors="replace"))


@pytest.fixture(scope="module")
def surface(code: str) -> list[tuple[int, int]]:
    spans = _function_spans(code)
    missing = set(SURFACE_FUNCTIONS) - set(spans)
    # Si una función de superficie se renombra, el test dejaría de excluirla y empezaría a
    # contar sus apariciones como uso real: aprobaría en silencio. Mejor que falle.
    assert not missing, f"no se encontraron estas funciones en el firmware: {sorted(missing)}"
    return sorted(spans.values())


def _in_surface(pos: int, surface: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in surface)


def _param_blocks(code: str) -> dict[str, str]:
    """Cada ``hasParam("x")`` con el cuerpo que se ejecuta si el parámetro viene."""
    blocks: dict[str, str] = {}
    for m in re.finditer(r'hasParam\("([^"]+)"\)', code):
        name = m.group(1)
        brace = code.find("{", m.end())
        newline = code.find("\n", m.end())
        if brace != -1 and (newline == -1 or brace < newline):
            body = code[brace : _match_block(code, brace)]
        else:
            body = code[m.end() : newline if newline != -1 else len(code)]
        blocks.setdefault(name, "")
        blocks[name] += "\n" + body
    return blocks


def _assigned_globals(body: str) -> set[str]:
    """Identificadores a los que el bloque asigna, sin contar los declarados ahí mismo."""
    found: set[str] = set()
    for line in body.splitlines():
        for m in re.finditer(r"\b([A-Za-z_]\w*)\s*=(?!=)", line):
            before = line[: m.start(1)]
            if re.search(C_TYPES + r"\s*$", before):
                continue  # declaración local: su vida empieza y termina en el bloque
            found.add(m.group(1))
    return found


def _is_read_somewhere(ident: str, code: str, surface: list[tuple[int, int]]) -> bool:
    for m in re.finditer(rf"\b{re.escape(ident)}\b", code):
        if _in_surface(m.start(), surface):
            continue
        after = code[m.end() : m.end() + 40]
        if re.match(r"\s*=(?!=)", after):
            continue  # es el destino de una asignación, no una lectura
        line_start = code.rfind("\n", 0, m.start()) + 1
        if re.search(C_TYPES + r"[\w\s*&]*$", code[line_start : m.start()]):
            continue  # es la declaración
        return True
    return False


# Parámetros que no guardan estado: disparan una acción y se acaban ahí.
ACTION_ONLY = {"x", "r", "z", "zp", "rj", "start", "stop", "a", "wifi_reconnect"}


def test_every_http_param_reaches_a_control_path(code: str, surface: list[tuple[int, int]]):
    """Un parámetro que sólo se guarda y se vuelve a publicar es `bt` otra vez.

    Si este test falla, la pregunta no es cómo hacerlo pasar: es si el mando debería
    existir. Las dos salidas legítimas son cablearlo a un lazo o sacarlo de la API.
    """
    inertes: list[str] = []
    for name, body in _param_blocks(code).items():
        if name in ACTION_ONLY:
            continue
        targets = _assigned_globals(body)
        if not targets:
            continue  # el bloque llama a una función; no hay estado que verificar
        if not any(_is_read_somewhere(t, code, surface) for t in targets):
            inertes.append(f"?{name}= escribe {sorted(targets)} y nadie lo lee")
    assert not inertes, "mandos inertes en el firmware:\n  " + "\n  ".join(inertes)


# ── El criterio, ejercitado contra un caso construido para FALLAR ──────────────
#
# Este proyecto lleva tres criterios bien escritos y mal implementados en dos días, los
# tres imprimiendo un veredicto falso, y este archivo estuvo a punto de ser el cuarto: la
# primera versión daba por inertes a `ff`, `he`, `hx` y `sk`, que se leen los cuatro. Un
# bloque de veredicto sólo probado contra un caso que debe aprobar no está probado.

_FIRMWARE_FALSO = """
float mando_vivo = 1.0f;
float mando_muerto = 2.0f;
void handleCmd(AsyncWebServerRequest *request) {
  if (request->hasParam("vivo")) {
    mando_vivo = request->getParam("vivo")->value().toFloat();
  }
  if (request->hasParam("muerto")) {
    mando_muerto = request->getParam("muerto")->value().toFloat();
  }
}
String getStateJson() {
  // Acá `mando_muerto` se ve vivo, y es justo lo que pasaba con `bt`.
  json += "\\"muerto\\":" + String(mando_muerto, 1) + ",";
  return json;
}
void loop() {
  const float u = mando_vivo * 2.0f;
  setMotor((int)u);
}
"""


def _veredicto(fuente: str) -> list[str]:
    code = _strip_comments(fuente)
    spans = sorted(_function_spans(code).values())
    inertes = []
    for name, body in _param_blocks(code).items():
        targets = _assigned_globals(body)
        if targets and not any(_is_read_somewhere(t, code, spans) for t in targets):
            inertes.append(name)
    return inertes


def test_the_verdict_block_catches_an_inert_param():
    """Sin esto, un test que nunca puede fallar pasa por barrera."""
    assert _veredicto(_FIRMWARE_FALSO) == ["muerto"], (
        "el criterio no distingue un mando inerte de uno vivo: publicarlo en `getStateJson` "
        "no puede alcanzar para darlo por usado"
    )


def _advertised_commands(code: str) -> set[str]:
    """Tokens que `printHelp()` promete. Se leen de las propias cadenas que imprime."""
    spans = _function_spans(code)
    body = code[slice(*spans["printHelp"])]
    tokens: set[str] = set()
    for line in re.findall(r'"([^"]*)"', body):
        if line.startswith("==="):
            continue
        # `s<deg>`, `kp<val>`, `wifi_ssid<TuRed>`, `g1(on)`, `z`, `x(stop)`.
        # El `(?<![=\w])` descarta los `8=catch_ms` de la tabla de índices de `L<n>`:
        # son la descripción de un argumento, no comandos.
        for tok in re.findall(r"(?<![=\w])([a-z_]+[0-9]*)(?=<|\(|,|\s|$)", line):
            tokens.add(tok)
    return tokens


def _dispatched_commands(code: str) -> tuple[set[str], set[str]]:
    """(iniciales atendidas por el switch, tokens completos comparados explícitamente)."""
    spans = _function_spans(code)
    body = code[slice(*spans["processSerialCommand"])]
    initials = set(re.findall(r"case\s+'(.)'\s*:", body))
    whole = set(re.findall(r'cmd\s*==\s*"([^"]+)"', body))
    whole |= set(re.findall(r'cmd\.startsWith\("([^"]+)"\)', body))
    return initials, whole


# Palabras de la ayuda que describen el texto, no comandos.
HELP_PROSE = {
    "modos",
    "servo",
    "pendulo",
    "lqr",
    "hibrido",
    "gainsched",
    "motor",
    "info",
    "wifi",
    "sistema",
    "deg",
    "val",
    "pwm",
    "stop",
    "reset",
    "on",
    "off",
    "fino",
    "grueso",
    "estado",
    "ip",
    "ina",
    "scan",
    "esta",
    "ayuda",
    "reinicia",
    "el",
    "esp",
    "entrar",
    "salir",
    "clamp",
    "escala",
    "par",
    "modo",
    "damping",
    "signo",
    "velocidad",
    "swing",
    "up",
    "catch",
    "ms",
    "gain",
    "angle",
    "near",
    "vnear",
    "por",
    "http",
    "device",
    "homing",
    "pid",
    "tured",
    "tuclave",
}


def test_serial_help_matches_the_dispatcher(code: str):
    """La ayuda es una promesa, y seis de sus cuarenta comandos no la cumplían.

    Este test nació en rojo (``xfail(strict=True)``) y lo arregló la Etapa 2.2/2.3:
    ``lqr1`` a ``lqr4`` no tenían ``case 'l'`` —las cuatro ganancias del LQR, el modo que
    el proyecto lleva ~90 corridas intentando arreglar, no se podían tocar por serie— y
    ``op``, ``zp``, ``edp``, ``cprp`` colisionaban con ``o``, ``z``, ``ed``, ``cpr``.
    El ``strict=True`` es lo que forzó a quitar la marca en vez de dejarla puesta sobre
    un defecto ya resuelto.

    Despachar por `cmd.charAt(0)` y pasar el resto como argumento es legítimo y funciona
    para la mayoría: `m5`, `kp1.2`, `g1` entran por su letra y leen lo que sigue. El
    defecto aparece sólo cuando **un comando anunciado es prefijo de otro**: ahí las dos
    formas entran por el mismo `case` y la más larga se interpreta como la corta con un
    argumento basura. `op30` entra por `case 'o'`, que hace `substring(1).toFloat()` sobre
    `"p30"` → **0**, o sea que pone el offset del servo en cero en vez de mover el del
    péndulo. `zp` entra por `case 'z'` y cerra el servo en vez del péndulo.

    Se comprueban las dos formas de romper la promesa, y sólo ésas:
      1. un comando anunciado cuya inicial no tiene `case`;
      2. una colisión de prefijo sin comparación de token completo que la resuelva.
    """
    initials, whole = _dispatched_commands(code)
    advertised = {t for t in _advertised_commands(code) if t not in HELP_PROSE}
    faltan: list[str] = []

    for tok in sorted(advertised):
        # `startsWith("lqr")` atiende a `lqr1`..`lqr4`: un prefijo despachado cubre sus
        # variantes. Comparar sólo el token exacto daría por rota una familia entera.
        if any(tok == w or tok.startswith(w) for w in whole):
            continue
        if tok[0] not in initials:
            faltan.append(f"`{tok}` está anunciado y no existe `case '{tok[0]}'`")
            continue
        prefijos = [otro for otro in advertised if otro != tok and tok.startswith(otro)]
        if prefijos:
            faltan.append(
                f"`{tok}` colisiona con `{'`, `'.join(sorted(prefijos))}` en `case '{tok[0]}'` "
                f"y nadie compara el token completo"
            )

    assert not faltan, "la ayuda serial promete lo que el despachador no atiende:\n  " + "\n  ".join(faltan)


def test_serial_arguments_are_validated_before_use(code: str):
    """Ningún comando serial convierte su argumento sin validarlo primero.

    Hallado en banco el 2026-08-06, no por un test: ``String::toFloat()`` devuelve
    ``0.0`` ante cualquier basura, sin distinguir *"pidió 0"* de *"se equivocó"*. Medido
    en placa, ``qq`` —un typo de ``q<0..1>``, la escala de par del modo 7— puso
    ``rl_pwm_scale`` de 1,0 a **0,0 sin imprimir nada**: la política entrega torque nulo
    y el modo se ve muerto sin ninguna señal que lo explique. Lo mismo valía para ``s``
    (que en modo 2 mueve el brazo), ``o`` (el cero del servo) y ``L6`` (``lqr_K2``).

    El test de mandos inertes no puede ver esto: ``q`` sí tiene ``case`` y
    ``rl_pwm_scale`` sí se lee. Son defectos distintos con la misma consecuencia —una
    entrada mal formada escribiendo un valor consecuente en silencio— así que hace falta
    una barrera propia.

    La regla: dentro de ``processSerialCommand`` no se llama a ``.toFloat()`` ni a
    ``.toInt()``; se pasa por ``parseSerialNumber()``, que rechaza y lo dice.
    """
    spans = _function_spans(code)
    body = code[slice(*spans["processSerialCommand"])]

    crudas = []
    for m in re.finditer(r"\.to(Float|Int)\(\)", body):
        linea = body[body.rfind("\n", 0, m.start()) + 1 : body.find("\n", m.end())].strip()
        crudas.append(linea)

    assert not crudas, (
        "conversiones sin validar en el despachador serial — un argumento mal formado "
        "escribe un 0 en silencio:\n  " + "\n  ".join(crudas)
    )
    # Y que la validación exista de verdad, no que se haya renombrado el problema.
    assert "parseSerialNumber" in code, "no existe `parseSerialNumber()` en el firmware"


def test_firmware_input_dim_is_the_one_python_assumes(code: str):
    """El 36 estaba escrito tres veces sin que ninguna derivara de la otra.

    Cambiar `RL_HISTORY_STEPS` en el `.ino` no rompía nada: el header exportado seguiría
    declarando 36 entradas y la política leería fuera del búfer del firmware.
    """
    consts = {
        name: int(re.search(rf"constexpr\s+int\s+{name}\s*=\s*(\d+)", code).group(1))
        for name in ("RL_HISTORY_STEPS", "RL_OBS_PER_STEP")
    }
    firmware_dim = consts["RL_HISTORY_STEPS"] * consts["RL_OBS_PER_STEP"]

    from qube_rl.export_rltools import FIRMWARE_INPUT_DIM

    assert firmware_dim == FIRMWARE_INPUT_DIM, (
        f"`export_rltools.FIRMWARE_INPUT_DIM` = {FIRMWARE_INPUT_DIM} y el firmware espera "
        f"{consts['RL_HISTORY_STEPS']}x{consts['RL_OBS_PER_STEP']} = {firmware_dim}"
    )


def test_every_http_param_is_documented(code: str):
    """La referencia de la API describe lo que el firmware acepta, y nada más.

    Al escribirse este test faltaban **24 de 70** parámetros —entre ellos ``lpm``, ``tn``,
    ``he``/``hx`` y toda la familia de gain scheduling del LQR—, así que la única forma de
    saber que existían era leer el ``.ino``. Un mando que nadie sabe que existe no se
    barre, y eso es la mitad de por qué varias campañas midieron el default.

    Sin barrera, el doc vuelve a divergir en la siguiente etapa.
    """
    doc = HTTP_API_MD.read_text(encoding="utf-8")
    documentados = set(re.findall(r"`([a-z_0-9]+)`", doc))
    faltan = sorted(p for p in set(re.findall(r'hasParam\("([^"]+)"\)', code)) if p not in documentados)
    assert not faltan, (
        f"parámetros que el firmware acepta y `docs/http_api.md` no documenta: {faltan}\n"
        "Un mando indocumentado no se barre: agregarlo a la tabla o sacarlo del firmware."
    )


def test_registro_table_and_sections_agree():
    """El registro tuvo ocho desacuerdos entre su tabla y sus secciones (2026-08-06).

    Se entra al registro por el ancla —desde el código y desde la tesis—, no por la
    tabla: quien seguía `#p22` leía `MITIGADO` sobre un problema cerrado.
    """
    text = REGISTRO_MD.read_text(encoding="utf-8")
    tabla = dict(re.findall(r"^\| \[P(\d+)\]\(#p\d+\) \|.*?\|.*?\|\s*`?([A-ZÉ ]+?)`?\s*(?:—|\(|\|)", text, re.M))
    partes = re.split(r"^## P(\d+) \{#p\d+\}", text, flags=re.M)[1:]
    secciones = dict(zip(partes[::2], partes[1::2], strict=True))

    assert tabla, "no se pudo leer la tabla de estados del registro"
    problemas: list[str] = []
    for pid, cuerpo in sorted(secciones.items(), key=lambda kv: int(kv[0])):
        m = re.search(r"\*\*Estado:\*\*\s*`([^`]+)`", cuerpo)
        if m is None:
            problemas.append(f"P{pid}: la sección no declara `**Estado:**`")
            continue
        esperado = tabla.get(pid, "").strip()
        if esperado and not m.group(1).startswith(esperado):
            problemas.append(f"P{pid}: tabla dice `{esperado}` y la sección `{m.group(1)}`")
    assert not problemas, "el registro se contradice consigo mismo:\n  " + "\n  ".join(problemas)
