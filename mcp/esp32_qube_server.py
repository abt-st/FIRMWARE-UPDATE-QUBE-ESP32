"""
MCP Server para el proyecto QUBE Servo ESP32.
Proporciona herramientas para:
  - Flash/firmware: compilar, subir, monitor serial
  - Control HTTP: interactuar con el ESP32 en vivo (get state, send cmd, set PID)
  - Análisis: leer y analizar archivos CSV de datos experimentales
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:
    print(
        f"Dependencia faltante: {e}. Instale con: uv add mcp[cli] requests",
        file=sys.stderr,
    )
    sys.exit(1)

# ── Configuración global ──────────────────────────────────────────────────────

FIRMWARE_DIR = Path(__file__).resolve().parent.parent / "firmware"
DATA_DIR = Path(__file__).resolve().parent.parent / "data"
INOTEO_FILE = FIRMWARE_DIR / "esp32_qube_l298n" / "esp32_qube_l298n.ino"
PLATFORMIO_INI = FIRMWARE_DIR / "platformio.ini"

# ── Servidor MCP ──────────────────────────────────────────────────────────────

mcp = FastMCP(
    "qube-esp32",
)

# Estado global del cliente HTTP
_client_state: dict[str, Any] = {
    "ip": "192.168.4.1",
    "timeout": 2.0,
    "connected": False,
}


# ══════════════════════════════════════════════════════════════════════════════
#  HERRAMIENTAS — Firmware / PlatformIO
# ══════════════════════════════════════════════════════════════════════════════


def _run_pio(args: list[str]) -> str:
    """Ejecuta un comando PlatformIO y retorna la salida."""
    cmd = ["pio", *args]
    try:
        result = subprocess.run(
            cmd,
            cwd=str(FIRMWARE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = result.stdout
        if result.stderr:
            output += "\n--- STDERR ---\n" + result.stderr
        return f"[Exit code: {result.returncode}]\n{output}"
    except FileNotFoundError:
        return "Error: 'pio' (PlatformIO) no encontrado. Verifique que está en PATH."
    except subprocess.TimeoutExpired:
        return "Error: El comando PlatformIO excedió 5 minutos de timeout."


@mcp.tool()
def pio_compile(environment: str = "esp32dev") -> str:
    """Compila el firmware del QUBE ESP32 usando PlatformIO.

    Args:
        environment: Entorno de PlatformIO (por defecto 'esp32dev').

    Returns:
        Salida de la compilación con estado de éxito/error.
    """
    return _run_pio(["run", "-e", environment])


@mcp.tool()
def pio_upload(environment: str = "esp32dev") -> str:
    """Compila y sube el firmware al ESP32 conectado.

    Args:
        environment: Entorno de PlatformIO (por defecto 'esp32dev').

    Returns:
        Salida del upload con estado de éxito/error.
    """
    return _run_pio(["run", "-e", environment, "--target", "upload"])


@mcp.tool()
def pio_clean(environment: str = "esp32dev") -> str:
    """Limpia los archivos de build del firmware.

    Args:
        environment: Entorno de PlatformIO (por defecto 'esp32dev').

    Returns:
        Salida de la limpieza.
    """
    return _run_pio(["run", "-e", environment, "--target", "clean"])


@mcp.tool()
def pio_serial_monitor(baud: int = 115200, lines: int = 50) -> str:
    """Lee las últimas líneas del monitor serial del ESP32.

    Abre una conexión serial breve y captura las líneas disponibles.

    Args:
        baud: Velocidad del baud rate (por defecto 115200).
        lines: Número de líneas a capturar.

    Returns:
        Las últimas líneas leídas del serial, o un error si no hay conexión.
    """
    # Primero intentamos encontrar el puerto serial del ESP32
    try:
        result = subprocess.run(
            ["pio", "device", "list"],
            cwd=str(FIRMWARE_DIR),
            capture_output=True,
            text=True,
            timeout=10,
        )
        serial_ports = result.stdout.strip()
    except Exception as e:
        serial_ports = f"No se pudieron listar puertos: {e}"

    return (
        f"Puertos seriales detectados:\n{serial_ports}\n\n"
        "Nota: Para lectura continua del monitor serial, use:\n"
        f"  pio device monitor -b {baud} --echo\n"
        f"  (en la terminal de PlatformIO)\n\n"
        "Opcionalmente puede usar herramientas externas como:\n"
        f"  python -m serial.tools.miniterm {serial_ports.split(chr(10))[0] if serial_ports and chr(10) in serial_ports else 'COM3'} {baud}"
    )


@mcp.tool()
def read_firmware_source() -> str:
    """Lee el código fuente completo del firmware principal (esp32_qube_l298n.ino).

    Returns:
        Contenido del archivo .ino con su ruta absoluta.
    """
    if not INOTEO_FILE.exists():
        return f"Error: No se encontró {INOTEO_FILE}"
    content = INOTEO_FILE.read_text(encoding="utf-8")
    return f"📄 {INOTEO_FILE.name} ({len(content)} caracteres)\n\n{content}"


@mcp.tool()
def get_firmware_info() -> str:
    """Obtiene información del proyecto PlatformIO: entornos, dependencias, config.

    Returns:
        Resumen de la configuración del proyecto firmware.
    """
    info_parts: list[str] = []

    # platformio.ini
    if PLATFORMIO_INI.exists():
        info_parts.append(f"=== platformio.ini ===\n{PLATFORMIO_INI.read_text(encoding='utf-8')}")

    # Estructura del directorio firmware
    info_parts.append("\n=== Estructura del firmware ===")
    for item in sorted(FIRMWARE_DIR.rglob("*")):
        if item.is_file() and not any(d in str(item) for d in [".pio", "__pycache__"]):
            rel = item.relative_to(FIRMWARE_DIR)
            info_parts.append(f"  {rel}")

    return "\n".join(info_parts)


# ══════════════════════════════════════════════════════════════════════════════
#  HERRAMIENTAS — Control HTTP del ESP32 en vivo
# ══════════════════════════════════════════════════════════════════════════════


def _http_get(endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """Realiza una petición HTTP GET al ESP32."""
    url = f"http://{_client_state['ip']}/{endpoint}"
    resp = requests.get(url, params=params, timeout=_client_state["timeout"])
    resp.raise_for_status()
    return (
        resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"response": resp.text}
    )


@mcp.tool()
def qube_connect(ip: str = "192.168.4.1", timeout: float = 2.0) -> str:
    """Configura la conexión al ESP32 y verifica que esté disponible.

    Args:
        ip: Dirección IP del ESP32 (default: 192.168.4.1, modo AP).
        timeout: Timeout HTTP en segundos.

    Returns:
        Estado de la conexión y datos iniciales del dispositivo.
    """
    _client_state["ip"] = ip
    _client_state["timeout"] = timeout

    try:
        data = _http_get("state")
        _client_state["connected"] = True
        return f"✅ Conectado a ESP32 en {ip}\n\nEstado actual:\n{_format_state(data)}"
    except requests.exceptions.ConnectionError:
        _client_state["connected"] = False
        return f"❌ Sin conexión a {ip} — Verifique que el ESP32 está encendido y en modo AP"
    except requests.exceptions.Timeout:
        _client_state["connected"] = False
        return f"❌ Timeout conectando a {ip}"
    except Exception as e:
        _client_state["connected"] = False
        return f"❌ Error: {e}"


@mcp.tool()
def qube_get_state() -> str:
    """Obtiene el estado actual del sistema QUBE (posicion, modo, PWM, potencia).

    Returns:
        Estado actual formateado del ESP32.
    """
    try:
        data = _http_get("state")
        return _format_state(data)
    except Exception as e:
        return f"❌ Error obteniendo estado: {e}"


@mcp.tool()
def qube_send_command(
    m: int | None = None,
    s: float | None = None,
    p: int | None = None,
    x: int | None = None,
    z: int | None = None,
    kp: float | None = None,
    ki: float | None = None,
    kd: float | None = None,
    cpr: float | None = None,
    ed: int | None = None,
) -> str:
    """Envía un comando al ESP32 a través de /cmd.

    Todos los parámetros son opcionales; solo se envían los no-nulos.

    Args:
        m: Modo de operación (0=idle, 1=open-loop, 2=closed-loop, 3=open-loop-voltage).
        s: Setpoint en grados.
        p: Valor PWM directo (-255 a 255).
        x: Kill switch (1=detener motor).
        z: Zero encoder (1=poner origen).
        kp: Ganancia Kp del PID.
        ki: Ganancia Ki del PID.
        kd: Ganancia Kd del PID.
        cpr: Cuentas por revolución del encoder.
        ed: Dirección del encoder (1 o -1).

    Returns:
        Respuesta del ESP32 al comando.
    """
    params: dict[str, Any] = {}
    if m is not None:
        params["m"] = m
    if s is not None:
        params["s"] = round(s, 2)
    if p is not None:
        params["p"] = int(p)
    if x is not None:
        params["x"] = int(x)
    if z is not None:
        params["z"] = int(z)
    if kp is not None:
        params["kp"] = kp
    if ki is not None:
        params["ki"] = ki
    if kd is not None:
        params["kd"] = kd
    if cpr is not None:
        params["cpr"] = round(cpr, 1)
    if ed is not None:
        params["ed"] = int(ed)

    if not params:
        return "⚠️ No se especificó ningún parámetro. Use al menos uno (m, s, p, x, z, kp, ki, kd, cpr, ed)."

    cmd_str = ", ".join(f"{k}={v}" for k, v in params.items())
    try:
        _http_get("cmd", params=params)
        return f"✅ Comando enviado: {cmd_str}"
    except Exception as e:
        return f"❌ Error enviando comando ({cmd_str}): {e}"


@mcp.tool()
def qube_set_pid(kp: float, ki: float, kd: float) -> str:
    """Configura los parámetros PID del controlador QUBE.

    Args:
        kp: Ganancia proporcional.
        ki: Ganancia integral.
        kd: Ganancia derivativa.

    Returns:
        Confirmación del envío.
    """
    try:
        _http_get("cmd", params={"kp": kp, "ki": ki, "kd": kd})
        return f"✅ PID configurado: Kp={kp}, Ki={ki}, Kd={kd}"
    except Exception as e:
        return f"❌ Error configurando PID: {e}"


@mcp.tool()
def qube_stop_motor() -> str:
    """Detiene el motor inmediatamente (kill switch).

    Returns:
        Confirmación de la acción.
    """
    try:
        _http_get("cmd", params={"x": 1})
        return "✅ Motor detenido"
    except Exception as e:
        return f"❌ Error deteniendo motor: {e}"


@mcp.tool()
def qube_set_mode(mode: int) -> str:
    """Cambia el modo de operación del QUBE.

    Args:
        mode: 0=idle, 1=open-loop, 2=closed-loop (PID), 3=open-loop-voltage.

    Returns:
        Confirmación del cambio de modo.
    """
    mode_names = {0: "Idle", 1: "Open-loop", 2: "Closed-loop (PID)", 3: "Open-loop voltage"}
    try:
        _http_get("cmd", params={"m": mode})
        return f"✅ Modo cambiado a: {mode_names.get(mode, f'Modo {mode}')}"
    except Exception as e:
        return f"❌ Error cambiando modo: {e}"


# ══════════════════════════════════════════════════════════════════════════════
#  HERRAMIENTAS — Análisis de datos CSV
# ══════════════════════════════════════════════════════════════════════════════


@mcp.tool()
def qube_list_experiments() -> str:
    """Lista todos los archivos CSV de datos experimentales disponibles.

    Returns:
        Lista de archivos CSV con su fecha y tamaño.
    """
    if not DATA_DIR.exists():
        return f"Directorio de datos no encontrado: {DATA_DIR}"

    csv_files = sorted(DATA_DIR.glob("*.csv"), key=lambda f: f.stat().st_mtime, reverse=True)
    if not csv_files:
        return f"No hay archivos CSV en {DATA_DIR}"

    lines = [f"📁 {DATA_DIR}\n"]
    for f in csv_files:
        size_kb = f.stat().st_size / 1024
        mtime = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"  📊 {f.name} ({size_kb:.1f} KB) — {mtime}")
    return "\n".join(lines)


@mcp.tool()
def qube_read_csv(filename: str, max_rows: int = 100) -> str:
    """Lee un archivo CSV de experimento QUBE y muestra su contenido.

    Args:
        filename: Nombre del archivo CSV (solo nombre, sin ruta completa).
        max_rows: Máximo de filas a mostrar (default: 100).

    Returns:
        Contenido del CSV con header y primeras filas, o resumen si es muy grande.
    """
    csv_path = DATA_DIR / filename
    if not csv_path.exists():
        # Buscar parcialmente
        matches = list(DATA_DIR.glob(f"*{filename}*"))
        if matches:
            csv_path = matches[0]
        else:
            return f"❌ No se encontró '{filename}' en {DATA_DIR}"

    content = csv_path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    total_rows = len(lines) - 1  # Excluir header

    if total_rows <= max_rows:
        return f"📄 {csv_path.name} ({total_rows} filas)\n\n{content}"
    else:
        header = lines[0]
        preview = "\n".join(lines[1 : max_rows + 1])
        return f"📄 {csv_path.name} ({total_rows} filas, mostrando primeras {max_rows})\n\n{header}\n{preview}\n..."


@mcp.tool()
def qube_analyze_csv(filename: str) -> str:
    """Analiza un archivo CSV de experimento QUBE y extrae métricas clave.

    Calcula: overshoot, tiempo de establecimiento, error estacionario,
    rango de PWM, corriente máxima, etc.

    Args:
        filename: Nombre del archivo CSV (solo nombre, sin ruta completa).

    Returns:
        Resumen analítico con métricas clave del experimento.
    """
    csv_path = DATA_DIR / filename
    if not csv_path.exists():
        matches = list(DATA_DIR.glob(f"*{filename}*"))
        if matches:
            csv_path = matches[0]
        else:
            return f"❌ No se encontró '{filename}' en {DATA_DIR}"

    content = csv_path.read_text(encoding="utf-8")
    lines = content.strip().split("\n")
    if len(lines) < 2:
        return "❌ CSV vacío o sin datos"

    header = lines[0].split(",")
    data_rows: list[list[float]] = []
    for line in lines[1:]:
        try:
            vals = [float(x.strip()) for x in line.split(",")]
            data_rows.append(vals)
        except ValueError:
            continue

    if not data_rows:
        return "❌ No se pudieron parsear los datos"

    # Mapear columnas por nombre conocido
    col_map = {h.strip().lower(): i for i, h in enumerate(header)}

    report: list[str] = [f"📊 Análisis de {csv_path.name}", f"   Filas de datos: {len(data_rows)}", ""]

    # Posición (position_deg o similar)
    pos_key = next(
        (k for k in col_map if "position" in k and "deg" in k),
        next((k for k in col_map if "pos" in k), None),
    )
    if pos_key is not None and pos_key in col_map:
        positions = [row[col_map[pos_key]] for row in data_rows if col_map[pos_key] < len(row)]
        if positions:
            report.append("📍 Posición (grados):")
            report.append(f"   Mín: {min(positions):.2f}°")
            report.append(f"   Máx: {max(positions):.2f}°")
            report.append(f"   Media: {sum(positions) / len(positions):.2f}°")
            report.append(f"   Final: {positions[-1]:.2f}°")

    # Error
    error_key = next(
        (k for k in col_map if "error" in k),
        None,
    )
    if error_key is not None and error_key in col_map:
        errors = [row[col_map[error_key]] for row in data_rows if col_map[error_key] < len(row)]
        if errors:
            abs_errors = [abs(e) for e in errors]
            report.append(f"\n🎯 Error:")
            report.append(f"   |Error| final: {abs_errors[-1]:.2f}°")
            report.append(f"   |Error| max: {max(abs_errors):.2f}°")
            report.append(f"   |Error| medio: {sum(abs_errors) / len(abs_errors):.2f}°")

    # PWM
    pwm_key = next((k for k in col_map if "pwm" in k), None)
    if pwm_key is not None and pwm_key in col_map:
        pwms = [row[col_map[pwm_key]] for row in data_rows if col_map[pwm_key] < len(row)]
        if pwms:
            report.append(f"\n⚡ PWM:")
            report.append(f"   Rango: [{min(pwms):.0f}, {max(pwms):.0f}]")
            report.append(f"   |PWM| final: {abs(pwms[-1]):.0f}")

    # Potencia / corriente
    i_key = next((k for k in col_map if "i_ma" in k or "current" in k), None)
    v_key = next((k for k in col_map if "v_bus" in k or "voltage" in k), None)

    if i_key is not None and i_key in col_map:
        currents = [row[col_map[i_key]] for row in data_rows if col_map[i_key] < len(row)]
        if currents:
            report.append(f"\n🔋 Corriente:")
            report.append(f"   Máx: {max(currents):.1f} mA")
            report.append(f"   Media: {sum(currents) / len(currents):.1f} mA")
            report.append(f"   Final: {currents[-1]:.1f} mA")

    if v_key is not None and v_key in col_map:
        voltages = [row[col_map[v_key]] for row in data_rows if col_map[v_key] < len(row)]
        if voltages:
            report.append(f"\n🔌 Voltaje:")
            report.append(f"   Rango: [{min(voltages):.2f}, {max(voltages):.2f}] V")

    # Columnas disponibles
    report.append(f"\n📋 Columnas disponibles: {', '.join(header)}")

    return "\n".join(report)


# ══════════════════════════════════════════════════════════════════════════════
#  UTILIDADES
# ══════════════════════════════════════════════════════════════════════════════


def _format_state(data: dict[str, Any]) -> str:
    """Formatea el estado del ESP32 de forma legible."""
    mode_names = {0: "Idle", 1: "Open-loop", 2: "Closed-loop (PID)", 3: "Open-loop voltage"}
    mode = int(data.get("mode", 0))
    return (
        f"🔄 Modo: {mode_names.get(mode, f'Modo {mode}')} ({mode})\n"
        f"📐 Posición: {data.get('position_deg', 0):.2f}° "
        f"(raw: {data.get('raw_position_deg', 0):.2f}°)\n"
        f"🎯 Setpoint: {data.get('setpoint_deg', 0):.2f}°\n"
        f"📉 Error: {data.get('error_deg', 0):.2f}°\n"
        f"⚙️ PWM: {data.get('pwm', 0)}\n"
        f"🔢 Encoder: {data.get('count', 0)} counts\n"
        f"🔌 INA219: {'OK' if data.get('ina_ok') else 'N/A'}"
        + (
            f"\n   V={data.get('v_bus', 0):.2f}V  I={data.get('i_ma', 0):.1f}mA  P={data.get('p_mw', 0):.1f}mW"
            if data.get("ina_ok")
            else ""
        )
    )


# ══════════════════════════════════════════════════════════════════════════════
#  RECURSOS
# ══════════════════════════════════════════════════════════════════════════════


@mcp.resource("qube://project/structure")
def project_structure() -> str:
    """Retorna la estructura general del proyecto QUBE ESP32."""
    lines: list[str] = ["# Estructura del Proyecto QUBE ESP32\n"]
    root = Path(__file__).resolve().parent.parent
    for item in sorted(root.iterdir()):
        if item.is_dir() and not item.name.startswith(".") and item.name not in ("__pycache__", "node_modules"):
            files = list(item.glob("*"))
            lines.append(f"📁 {item.name}/")
            for f in sorted(files)[:10]:
                if f.is_file():
                    lines.append(f"   📄 {f.name}")
            if len(files) > 10:
                lines.append(f"   ... y {len(files) - 10} más")
        elif item.is_file():
            lines.append(f"📄 {item.name}")
    return "\n".join(lines)


@mcp.resource("qube://firmware/changelog")
def firmware_changelog() -> str:
    """Retorna el CHANGELOG del firmware."""
    changelog = Path(__file__).resolve().parent.parent / "CHANGELOG.md"
    if changelog.exists():
        return changelog.read_text(encoding="utf-8")
    return "CHANGELOG.md no encontrado."


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    mcp.run(transport="stdio")
