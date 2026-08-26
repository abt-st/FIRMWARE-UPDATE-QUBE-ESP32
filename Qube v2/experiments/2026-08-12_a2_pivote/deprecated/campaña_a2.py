"""Campaña A2 — Decaimiento libre del péndulo
Antonio Badilla · Ingeniería Mecánica USACH

Mide la fricción del pivote del péndulo mediante ensayos de oscilación libre
con motor desenergizado. El script guía cada liberación, registra el ángulo del
péndulo y cuenta ciclos automáticamente.

Uso:
    python campaña_a2.py                    # SoftAP default 192.168.4.1
    python campaña_a2.py --ip 192.168.100.5  # IP personalizada

Requisitos:
    pip install requests
    PC conectado a la WiFi QUBE-ESP32
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import requests

# ── utilería de terminal ────────────────────────────────────────────────────
C = {"t": "\033[1;36m", "ok": "\033[1;32m", "no": "\033[1;31m",
     "d": "\033[0;33m", "n": "\033[0m", "b": "\033[1m"}
if sys.platform == "win32":
    import os
    os.system("")

def encabezado(txt: str):
    print(f"\n{C['t']}{'═' * 60}\n  {txt}\n{'═' * 60}{C['n']}")

def info(txt: str):
    for line in txt.strip().split("\n"):
        print(f"{C['d']}  {line.strip()}{C['n']}")

def resultado(k: str, v: str, ok: bool | None = None):
    col = "" if ok is None else (C["ok"] if ok else C["no"])
    print(f"    {k:<36} {col}{v}{C['n']}")

# ── comunicación con el banco ───────────────────────────────────────────────
def conectar(ip: str, intentos: int = 5) -> requests.Session:
    s = requests.Session()
    s.headers.update({"Connection": "keep-alive"})
    for i in range(intentos):
        try:
            r = s.get(f"http://{ip}/state", timeout=4)
            r.raise_for_status()
            return s
        except requests.RequestException:
            if i == intentos - 1:
                print(f"{C['no']}  Error: no se pudo conectar a {ip}{C['n']}")
                sys.exit(1)
            time.sleep(1)
    raise RuntimeError("inalcanzable")

def leer_estado(s: requests.Session, ip: str) -> dict:
    """Lee /state con reintentos cortos."""
    for _ in range(3):
        try:
            r = s.get(f"http://{ip}/state", timeout=3)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(0.3)
    return {}

def set_modo(s: requests.Session, ip: str, modo: int) -> dict:
    for _ in range(3):
        try:
            r = s.get(f"http://{ip}/cmd", params={"m": modo}, timeout=3)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            time.sleep(0.3)
    return {}

# ── adquisición ─────────────────────────────────────────────────────────────
def capturar_decaimiento(s: requests.Session, ip: str,
                         duracion: float = 15.0,
                         label: str = "",
                         archivo: Path | None = None) -> list[dict]:
    """Registra ángulo del péndulo vs tiempo durante un decaimiento libre.

    Retorna lista de dicts {t, angulo}. Opcionalmente guarda CSV.
    """
    filas: list[dict] = []
    t0 = time.monotonic()

    print(f"\n  {C['b']}Grabando {label}...{C['n']}  (suelta el péndulo AHORA)")
    sys.stdout.flush()

    while (t := time.monotonic() - t0) < duracion:
        d = leer_estado(s, ip)
        if d:
            filas.append({
                "t": t,
                "angulo": float(d.get("pend_position_deg", 0)),
                "theta": float(d.get("position_deg", 0)),
            })
        # Mostrar progreso cada ~1 s
        if int(t * 2) % 2 == 0 and int(t * 2) != int((t - 0.5) * 2):
            ang = filas[-1]["angulo"] if filas else 0
            print(f"    t={t:5.1f}s  ángulo={ang:7.2f}°", end="\r")
            sys.stdout.flush()
        time.sleep(0.03)  # ~30 Hz nominal

    print(f"\n  {C['ok']}Registro completado ({len(filas)} muestras){C['n']}")

    if archivo:
        with archivo.open("w") as f:
            f.write("t,angulo,theta\n")
            for row in filas:
                f.write(f"{row['t']:.4f},{row['angulo']:.4f},{row['theta']:.4f}\n")
        print(f"    Guardado: {archivo}")

    return filas

# ── análisis ────────────────────────────────────────────────────────────────
def analizar_decaimiento(filas: list[dict], freq_natural: float = 1.70) -> dict:
    """Cuenta cruces por cero del péndulo. Retorna métricas."""
    angulos = [f["angulo"] for f in filas]
    tiempos = [f["t"] for f in filas]

    # Detectar condición inicial: el ángulo antes de soltar
    # (los primeros samples son el péndulo quieto en una posición)
    ang_inicial = max(abs(a) for a in angulos[:10]) if len(angulos) >= 10 else 0

    # Cruces por cero (vertical = 0°)
    # Un cruce ocurre cuando el signo cambia entre muestras consecutivas
    cruces_idx = []
    for i in range(1, len(angulos)):
        if angulos[i-1] * angulos[i] < 0:
            # Interpolar para encontrar el cruce exacto
            t_cruce = tiempos[i-1] + (tiempos[i] - tiempos[i-1]) * (
                abs(angulos[i-1]) / (abs(angulos[i-1]) + abs(angulos[i])))
            cruces_idx.append({"t": t_cruce, "i": i})

    # Cada 2 cruces = 1 ciclo completo
    n_cruces = len(cruces_idx)
    n_ciclos = n_cruces // 2

    # Amplitud de los picos (máximo valor absoluto entre cruces)
    picos = []
    for j in range(len(cruces_idx) - 1):
        ini = cruces_idx[j]["i"]
        fin = cruces_idx[j+1]["i"]
        seg = angulos[ini:fin+1]
        if seg:
            picos.append(max(abs(v) for v in seg))

    # Amplitud inicial y final
    amp_inicial = picos[0] if picos else ang_inicial
    amp_final_prom = statistics.mean(picos[-3:]) if len(picos) >= 3 else (picos[-1] if picos else 0)

    # Tiempo de oscilación (período observado)
    if n_ciclos >= 1:
        t_inicio = cruces_idx[0]["t"]
        t_fin = cruces_idx[-1]["t"]
        t_total_oscilacion = t_fin - t_inicio
        periodo_obs = t_total_oscilacion / n_ciclos if n_ciclos > 0 else 0
        freq_obs = 1.0 / periodo_obs if periodo_obs > 0 else 0
    else:
        # Si no hay cruces, estimar desde el tiempo total de la captura
        # (el péndulo no osciló o la fricción lo detuvo instantáneamente)
        periodo_obs = 0
        freq_obs = 0
        t_total_oscilacion = 0

    # Clasificación de fricción
    if n_ciclos >= 20:
        tipo_friccion = "Viscosa (pivote sano)"
        ok = True
        detalle = (f"El pivote se comporta como el 2026-08-04: "
                   f"oscilación limpia. Se puede proceder a Grupo B.")
    elif n_ciclos >= 5:
        tipo_friccion = "Fricción seca moderada"
        ok = False
        detalle = (f"Hay fricción seca apreciable. Vale la pena lubricar "
                   f"los bujes del motor antes de continuar.")
    elif n_ciclos >= 1:
        tipo_friccion = "Fricción seca severa"
        ok = False
        detalle = (f"Consistente con la medición del 2026-08-05 "
                   f"($1.26\\times10^{{-3}}$ N·m). El pivote necesita "
                   f"inspección más profunda (A3).")
    else:
        tipo_friccion = "Fricción seca bloqueante"
        ok = False
        detalle = (f"El péndulo no cruza la vertical. Fricción seca "
                   f"≥ el valor reportado en §5.8. Requiere A3.")

    return {
        "angulo_inicial": ang_inicial,
        "n_cruces": n_cruces,
        "n_ciclos": n_ciclos,
        "picos": picos,
        "amp_inicial": amp_inicial,
        "amp_final_prom": amp_final_prom,
        "t_oscilacion": t_total_oscilacion,
        "periodo_obs": periodo_obs,
        "freq_obs": freq_obs,
        "tipo_friccion": tipo_friccion,
        "detalle": detalle,
        "ok": ok,
    }

def imprimir_resultados(res: dict, label: str):
    print(f"\n  {C['b']}── {label} ──{C['n']}")
    resultado("Ángulo inicial", f"{res['angulo_inicial']:.1f}°")
    resultado("Ciclos completos", str(res["n_ciclos"]))
    resultado("Cruces por cero", str(res["n_cruces"]))
    if res["periodo_obs"] > 0:
        resultado("Período observado", f"{res['periodo_obs']*1000:.0f} ms")
        resultado("Frecuencia observada", f"{res['freq_obs']:.2f} Hz")
        resultado("Duración oscilación", f"{res['t_oscilacion']:.1f} s")
    if res["picos"]:
        picos_str = ", ".join(f"{p:.1f}°" for p in res["picos"][:8])
        if len(res["picos"]) > 8:
            picos_str += "..."
        resultado("Amplitudes pico a pico", picos_str)
    resultado("Tipo de fricción", res["tipo_friccion"], res["ok"])
    print(f"  → {res['detalle']}")

# ── campaña completa ───────────────────────────────────────────────────────
AMPLITUDES = [
    (15, "~15° (cerca del umbral de fricción)"),
    (30, "~30° (mitad del rango)"),
    (60, "~60° (casi horizontal, como ref. 2026-08-04)"),
]

def main():
    parser = argparse.ArgumentParser(description="Campaña A2 — Decaimiento libre")
    parser.add_argument("--ip", default="192.168.4.1", help="IP de la ESP32")
    parser.add_argument("--sin-pausa", action="store_true", help="omitir pausas")
    parser.add_argument("--solo", type=int, nargs="+", help="solo estas amplitudes (grados)")
    args = parser.parse_args()

    out_dir = Path(f"campaña_a2_{time.strftime('%Y%m%d_%H%M%S')}")
    out_dir.mkdir(exist_ok=True)

    ip = args.ip

    encabezado("Campaña A2 — Decaimiento libre del péndulo")
    info(f"""
    Este script mide la fricción del pivote soltando el péndulo desde
    distintas amplitudes y contando cuántas veces cruza la vertical.

    ANTES DE EMPEZAR:
    1. PC conectado a la WiFi QUBE-ESP32
    2. BRAZO DEL SERVO inmovilizado (sujetar a mano o con prensa)
       para que no gire durante la prueba
    3. PÉNDULO COLGANDO LIBRE (vertical hacia abajo)
    4. ALIMENTACIÓN ENCENDIDA pero MOTOR DESENERGIZADO
    5. Despejar el área: nadie debe tocar el banco durante la grabación
    """)

    if not args.sin_pausa:
        input(f"  {C['b']}¿Listo? Presiona ENTER para conectar...{C['n']}")

    # Conectar
    print(f"\n  Conectando a {ip}...")
    s = conectar(ip)
    d = leer_estado(s, ip)
    resultado("Modo actual", str(d.get("mode", "?")))
    resultado("Ángulo péndulo", f"{float(d.get('pend_position_deg', 0)):.2f}°")
    resultado("Ángulo brazo", f"{float(d.get('position_deg', 0)):.2f}°")
    resultado("Alimentación", f"{float(d.get('v_bus', 0)):.2f} V")
    resultado("INA219", "ok" if d.get("ina_ok") else "CAÍDA", bool(d.get("ina_ok")))

    # Poner en modo 0 (motor off, coast)
    print(f"\n  {C['b']}Motor en modo 0 (off){C['n']}")
    set_modo(s, ip, 0)
    time.sleep(0.5)
    d2 = leer_estado(s, ip)
    resultado("Modo confirmado", str(d2.get("mode", "?")))

    # Preguntar estado inicial del péndulo
    info("""
    Verifica que el péndulo esté colgando libre y quieto.
    El ángulo reportado debe ser ≈ 0° (± ruido de 0.2°).
    """)

    # Seleccionar amplitudes
    amps = args.solo or [a[0] for a in AMPLITUDES]
    amps_info = {a[0]: a[1] for a in AMPLITUDES}

    # Resultados acumulados
    todos_resultados = []

    for ia, ang_obj in enumerate(amps):
        desc = amps_info.get(ang_obj, f"~{ang_obj}°")
        encabezado(f"Liberación {ia+1}/{len(amps)} — {desc}")

        info(f"""
    Prepara el péndulo:
    1. Lleva el péndulo a ~{ang_obj}° de la vertical
       (estíralo hacia un lado, NO lo impulses)
    2. Espera a que se aquiete completamente (≈2 s)
    3. Suelta LIMPIAMENTE sin empujar
    4. NO TOQUES nada durante 15 s
        """)

        if not args.sin_pausa:
            input(f"  {C['b']}¿Listo? Presiona ENTER y SUELTA EL PÉNDULO ahora...{C['n']}")

        # Capturar
        archivo_csv = out_dir / f"decaimiento_{ang_obj}deg.csv"
        filas = capturar_decaimiento(s, ip, duracion=15.0,
                                     label=f"{ang_obj}°",
                                     archivo=archivo_csv)

        if len(filas) < 5:
            print(f"\n  {C['no']}Muy pocas muestras. ¿Hay conexión con la placa?{C['n']}")
            continue

        # Analizar
        res = analizar_decaimiento(filas)
        imprimir_resultados(res, f"Liberación desde ~{ang_obj}°")
        todos_resultados.append({"angulo": ang_obj, **res})

        # Guardar JSON
        (out_dir / f"resultados_{ang_obj}deg.json").write_text(
            json.dumps(res, indent=2, default=str))

        # Esperar a que el péndulo se aquiete para la siguiente
        if ia < len(amps) - 1:
            info("\n  Esperando que el péndulo se aquiete para la siguiente liberación...")
            time.sleep(3)

    # ── resumen final ────────────────────────────────────────────────────
    encabezado("Resumen de la campaña A2")
    for r in todos_resultados:
        resultado(f"Desde ~{r['angulo']}°",
                  f"{r['n_ciclos']} ciclos → {r['tipo_friccion']}",
                  r["ok"])
        print(f"    {r['detalle']}")

    # Diagnóstico consolidado
    if all(r["ok"] for r in todos_resultados):
        print(f"\n{C['ok']}  ✅ PIVOTE SANO — {todos_resultados[0]['tipo_friccion']}{C['n']}")
        print(f"\n{C['b']}  Siguiente paso: Grupo B — control del péndulo{C['n']}")
    elif any(r["n_ciclos"] >= 5 for r in todos_resultados):
        print(f"\n{C['d']}  ⚠️  Fricción moderada — lubricar y repetir{C['n']}")
        print(f"\n  Recomendación: lubricar bujes del motor con aceite ")
        print(f"  sintético ligero, esperar 30 min y volver a medir.")
    else:
        print(f"\n{C['no']}  ❌ FRICCIÓN SECA PERSISTE — requiere A3{C['n']}")
        print(f"\n  La fricción seca sigue presente. El pivote necesita:")
        print(f"  1. Desmontar y limpiar bujes con alcohol isopropílico")
        print(f"  2. Re-lubricar")
        print(f"  3. Repetir A2")
        print(f"  4. Si no mejora: reemplazo de motor")

    # Guardar resumen
    (out_dir / "resumen.json").write_text(
        json.dumps(todos_resultados, indent=2, default=str))
    print(f"\n  Resultados guardados en: {out_dir.resolve()}")


if __name__ == "__main__":
    main()