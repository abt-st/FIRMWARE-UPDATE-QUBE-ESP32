"""Demostración de avance — QUBE Servo (péndulo de Furuta)
Antonio Badilla · Ingeniería Mecánica USACH

Ejecuta una secuencia guiada y auto-explicada sobre el hardware real. Cada bloque
imprime qué se va a hacer, lo hace, y muestra el resultado medido.

    python demo_avance.py                        # SoftAP: 192.168.4.1 por defecto
    python demo_avance.py --solo 1,2             # bloques sueltos
    python demo_avance.py --sin-pausa            # sin esperar ENTER
    python demo_avance.py --ip 192.168.100.50    # placa con firmware AP+STA

El PC debe estar asociado a la red WiFi QUBE-ESP32 antes de correr esto.

Diseñada para NO depender de resultados marginales: todo lo que muestra es
reproducible. Lo que aún no funciona se dice, no se esconde.
"""

from __future__ import annotations

import argparse
import contextlib
import math
import os
import statistics
import sys
import time

import requests

C = {"t": "\033[1;36m", "ok": "\033[1;32m", "no": "\033[1;31m",
     "d": "\033[0;33m", "n": "\033[0m", "b": "\033[1m"}
if sys.platform == "win32":
    os.system("")


def titulo(n: int, txt: str) -> None:
    print(f"\n{C['t']}{'═' * 74}\n  BLOQUE {n} — {txt}\n{'═' * 74}{C['n']}")


def nota(txt: str) -> None:
    for line in txt.strip().split("\n"):
        print(f"{C['d']}  {line.strip()}{C['n']}")


def dato(k: str, v: str, bien: bool | None = None) -> None:
    col = "" if bien is None else (C["ok"] if bien else C["no"])
    print(f"    {k:<34} {col}{v}{C['n']}")


class Qube:
    def __init__(self, ip: str) -> None:
        self.base = f"http://{ip}"
        self.s = requests.Session()
        self.s.headers.update({"Connection": "keep-alive"})

    # Reintentos generosos a proposito. Medido: el lazo de control de la ESP32 llega
    # a bloquearse ~95 ms (nominal 2 ms) cuando el stack WiFi le roba tiempo, y ahi
    # el servidor HTTP deja de responder unos segundos. Es transitorio —la placa NO
    # se reinicia, conserva su estado— pero una demo que se cae por eso delante de
    # alguien no sirve.
    #
    # OJO con el respaldo: el watchdog de comandos del firmware NO cubre a esta
    # demo. Solo guarda los modos 1 (PWM manual) y 6 (RL por HTTP) —ver
    # ENABLE_COMMAND_TIMEOUT en esp32_qube.ino— y aca se usan los modos 2, 3 y 5,
    # que son autonomos y siguen corriendo sin ordenes externas por diseño. El
    # unico respaldo real si se cae el HTTP a mitad de un bombeo es el limite duro
    # del brazo (SERVO_HARD_LIMIT_DEG = 95 deg), que dispara setMode(0) y deja el
    # motor en coast.
    def cmd(self, intentos: int = 5, **p):
        for i in range(intentos):
            try:
                return self.s.get(f"{self.base}/cmd", params=p, timeout=5).json()
            except requests.RequestException:
                if i == intentos - 1:
                    raise
                time.sleep(0.6)

    def st(self, intentos: int = 6):
        for i in range(intentos):
            try:
                r = self.s.get(f"{self.base}/state", timeout=4)
                r.raise_for_status()
                return r.json()
            except requests.RequestException:
                if i == intentos - 1:
                    raise
                time.sleep(0.5)

    def reposo(self, tmo: float = 30.0) -> bool:
        """Espera a que el péndulo se detenga. Por ESTABILIDAD, no por cercanía a
        cero: el cero puede haberse redefinido y el criterio ingenuo nunca pasa."""
        self.cmd(m=0)
        t0, win = time.monotonic(), []
        while time.monotonic() - t0 < tmo:
            try:
                a = float(self.st()["pend_position_deg"])
            except requests.RequestException:
                time.sleep(0.5)
                continue
            win.append((time.monotonic(), a))
            win = [(t, v) for t, v in win if time.monotonic() - t <= 2.5]
            if len(win) >= 12 and max(v for _, v in win) - min(v for _, v in win) < 1.5:
                return True
            time.sleep(0.1)
        return False

    def homing(self, tmo: float = 45.0, intentos: int = 3) -> dict:
        """Recalibra el cero. Reintenta: el fallo por recorrido fuera de tolerancia
        es esporádico (roce mecánico) y suele pasar al segundo intento. Si insiste,
        hay algo físico que revisar y ahí sí conviene detenerse."""
        for i in range(intentos):
            try:
                return self._homing_una(tmo)
            except RuntimeError as exc:
                if i == intentos - 1:
                    raise
                print(f"    {C['d']}({exc}; reintentando {i + 2}/{intentos}){C['n']}")
                time.sleep(2.0)
        raise RuntimeError("inalcanzable")

    def _homing_una(self, tmo: float = 45.0) -> dict:
        self.cmd(m=3)
        fin = time.monotonic() + tmo
        while time.monotonic() < fin:
            try:
                d = self.st()
            except requests.RequestException:
                # Un corte de lectura NO es un fallo del homing: la rutina sigue
                # corriendo sola en la placa. Se reintenta hasta el timeout.
                time.sleep(0.5)
                continue
            if d.get("homing_phase") == "DONE":
                return d
            if d.get("homing_phase") == "FAIL":
                raise RuntimeError(f"homing FAIL code={d.get('homing_fail')}")
            time.sleep(0.2)
        raise RuntimeError("homing: timeout")

    def grabar(self, seg: float, dt: float = 0.05) -> list[dict]:
        filas, t0 = [], time.monotonic()
        while (t := time.monotonic() - t0) < seg:
            try:
                d = self.st(2)
            except requests.RequestException:
                time.sleep(dt)
                continue
            filas.append({"t": t, "modo": d.get("mode"),
                          "th": float(d["position_deg"]),
                          "al": float(d["pend_position_deg"]),
                          "pwm": float(d["pwm"])})
            if d.get("mode") == 0:
                break
            time.sleep(dt)
        return filas


def picos(filas: list[dict]) -> list[float]:
    v = [abs(f["al"]) for f in filas]
    return [v[i] for i in range(1, len(v) - 1)
            if v[i] > v[i - 1] and v[i] >= v[i + 1] and v[i] > 20]


# ─────────────────────────────────────────────────────────────────────────────
def bloque1(q: Qube) -> None:
    titulo(1, "El problema: el encoder pierde el cero en cada reinicio")
    nota("""
        El encoder del brazo es incremental: mide desplazamiento, no posición
        absoluta. Al reiniciar la ESP32 el cero se pierde, y sin cero la lectura
        de theta no significa nada.

        Antes había que recentrar el brazo a mano. Eso impedía dejar el banco
        entrenando solo: cualquier corte y la sesión quedaba inservible.
    """)
    d = q.st()
    dato("modo actual", str(d["mode"]))
    dato("offset del brazo", f"{float(d['offset_deg']):.2f}°")
    ok = bool(d.get("homing_ok"))
    dato("cero validado", "sí" if ok else "NO — se perdió", ok)
    if ok:
        nota("""
            Está validado porque ya se calibró antes. Recién encendida la placa esto
            diría NO, y todo lo que dependa de theta sería inutilizable.
        """)
    dato("alimentación", f"{float(d['v_bus']):.2f} V")
    dato("protección de corriente (INA219)", "ok" if d.get("ina_ok") else "CAÍDA", bool(d.get("ina_ok")))


def bloque2(q: Qube) -> None:
    titulo(2, "La solución: homing automático por topes mecánicos")
    nota("""
        El brazo busca cada tope mecánico detectando el CALADO del encoder (deja
        de moverse con par aplicado), y adopta el punto medio como cero.

        Se hace por encoder y no por corriente a propósito: la protección por
        corriente depende del INA219, y si ese sensor cae la detección se queda
        sin red. El encoder siempre está.

        Van 3 corridas seguidas para mostrar la repetibilidad.
    """)
    rangos, centros = [], []
    for i in (1, 2, 3):
        print(f"\n  {C['b']}Corrida {i} de 3{C['n']}  (unos 12 s: busca un tope, retrocede, vuelve a tocar, repite)")
        h = q.homing()
        r, c = float(h["homing_range"]), float(h["homing_center"])
        rangos.append(r)
        centros.append(c)
        dato("recorrido medido", f"{r:.3f}°")
        dato("topes", f"{float(h['homing_stop_pos']):.2f}°  /  {float(h['homing_stop_neg']):.2f}°")
        dato("centro adoptado como cero", f"{c:.3f}°")

    disp = max(centros) - min(centros)
    print()
    dato("recorrido mecánico del brazo", f"{statistics.mean(rangos):.2f}°")
    dato("dispersión del centro", f"{disp:.3f}°", disp < 0.5)
    dato("resolución del encoder", "0.176° / conteo (2048 CPR)")
    nota(f"""
        La dispersión ({disp:.3f}°) está en el límite de resolución del sensor:
        no se puede medir mejor con este encoder. El cero es reproducible.
    """)


def bloque3(q: Qube) -> None:
    titulo(3, "Control de posición del brazo (PID) — el lazo que sí cierra")
    nota("""
        Escalón de 0° a 25° y vuelta. Es el único de los modos implementados que
        hoy cierra un lazo limpio, y sirve de referencia de que la planta y la
        instrumentación responden como se espera.
    """)
    q.homing()
    q.cmd(m=2, s=25)
    f1 = q.grabar(6.0)
    q.cmd(s=0)
    f2 = q.grabar(6.0)
    q.cmd(m=0)
    if f1:
        cola = [x["th"] for x in f1[int(len(f1) * 0.7):]]
        pico = max(x["th"] for x in f1)
        dato("consigna", "25.00°")
        dato("valor en régimen", f"{statistics.mean(cola):.2f}°")
        e1 = abs(statistics.mean(cola) - 25)
        dato("error en régimen", f"{e1:.2f}°  (tolerancia 8°)", e1 < 8)
        dato("sobrepaso", f"{(pico - 25) / 25 * 100:.0f}%")
    if f2:
        cola = [x["th"] for x in f2[int(len(f2) * 0.7):]]
        e2 = abs(statistics.mean(cola))
        dato("vuelta a 0°, valor final", f"{statistics.mean(cola):.2f}°  (tolerancia 8°)", e2 < 8)
    nota("""
        Converge en ambos sentidos. El ajuste está suelto —sobrepaso alto y unos
        grados de error residual por fricción estática— pero es trabajo de ajuste
        pendiente, no un defecto de la planta ni de la instrumentación.
    """)


def bloque4(q: Qube) -> None:
    titulo(4, "Swing-up: llevar el péndulo desde abajo hacia la vertical")
    nota("""
        El péndulo es un eslabón PASIVO: no tiene motor. La única forma de subirlo
        es bombear energía moviendo el brazo en fase con su oscilación.

        Convención: colgando = 0°, VERTICAL = 180°.
    """)
    q.homing()
    print("\n  Esperando que el péndulo se detenga…")
    # El cero se fija AQUI, con el pendulo colgando quieto. Si no llego a
    # detenerse, `zp=1` lo fija corrido y TODOS los angulos de este bloque quedan
    # desplazados por esa misma cantidad — es exactamente el defecto P13 que se
    # discute en el bloque 6. Se avisa en vez de presentar numeros contaminados.
    if not q.reposo():
        dato("péndulo detenido antes de fijar su cero",
             "NO — los ángulos de este bloque no son confiables", False)
        nota("""
            Conviene esperar a que se aquiete y repetir sólo este bloque:
            python demo_avance.py --solo 4
        """)
    q.cmd(zp=1)
    q.cmd(pl=0, pc=0, pr=70, sp=60, tr=1, tn=155)
    print(f"  {C['b']}Bombeando…{C['n']}")
    q.cmd(m=5)
    filas = q.grabar(24.0)
    q.cmd(m=0)

    p = picos(filas)
    if not p:
        dato("resultado", "sin oscilación detectada", False)
        return
    amax = max(p)
    print()
    print(f"    {C['b']}Crecimiento del bombeo, ciclo a ciclo:{C['n']}")
    print("      " + " → ".join(f"{v:.0f}" for v in p[:14]) + ("  …" if len(p) > 14 else ""))
    print()
    dato("ángulo máximo alcanzado", f"{amax:.1f}°  (vertical = 180°)")
    dato("energía respecto de la necesaria", f"{(1 - math.cos(math.radians(min(amax, 180)))) / 2:.3f}")
    th_max = max(abs(x["th"]) for x in filas)
    corto = any(x["modo"] == 0 for x in filas)
    if corto:
        # `grabar` corta en la PRIMERA muestra con modo 0, asi que esto es el brazo
        # en el instante del corte (mas lo que alcance a arrastrar entre muestras),
        # NO su excursion inercial final: para eso habria que seguir muestreando
        # despues del corte. En banco se midio un arrastre de ~27 deg a PWM 50.
        dato("brazo: cruzó su límite de 95°",
             f"corte automático (última muestra: {th_max:.1f}°)", True)
    else:
        dato("brazo, excursión máxima", f"{th_max:.1f}°  (límite 95°)", True)
    d = q.st()
    if int(d.get("swing_trans_reason", 0)):
        criterios = {1: "cerca+lento", 2: "pico", 4: "forzado", 8: "energía"}
        m = int(d["swing_trans_reason"])
        dato("entregó al LQR por", "+".join(v for k, v in criterios.items() if m & k))
        dato("  ángulo en la entrega", f"{float(d['swing_trans_alpha']):.1f}°")
        dato("  velocidad en la entrega", f"{float(d['swing_trans_vel']):.1f} °/s")
    else:
        dato("entrega al LQR", "no se disparó en esta corrida")
    nota("""
        El bombeo funciona: la amplitud crece de forma sostenida. Medido el
        2026-07-31 con el traspaso desactivado, plafona entre 142° y 154° y en 2
        de 3 corridas llega a 179.8° pasando de largo por arriba: la energía
        alcanza.

        Lo que NO está resuelto es la captura: entregar el péndulo al controlador
        de equilibrio en el instante correcto. Con la compuerta de velocidad ya
        corregida, un barrido de 4 corridas en tn=175 no disparó ninguna.
        Es el trabajo en curso.

        Que el brazo termine cruzando su límite de 95° es el final ESPERADO, no
        una excepción: ocurrió en las 7 corridas registradas.
    """)


def bloque5(q: Qube) -> None:
    titulo(5, "Integración: el entorno de entrenamiento se recalibra solo")
    nota("""
        El objetivo de todo lo anterior es poder dejar el banco entrenando sin
        supervisión. `QubeRealEnv` es el entorno Gymnasium que habla con la placa;
        acá se le pide un reset PIDIENDO el homing, y devuelve la geometría medida.

        `zero_epoch` es la pieza que evita un error silencioso: cada homing REDEFINE
        theta=0, así que episodios de antes y después están en marcos distintos y no
        deben mezclarse. El entorno lo etiqueta en cada reset.
    """)
    import os
    import sys as _sys
    raiz = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
    if raiz not in _sys.path:
        _sys.path.insert(0, raiz)
    try:
        from qube_rl.envs.qube_real import QubeRealEnv
    except ImportError as exc:
        dato("entorno de entrenamiento", f"no disponible ({exc})", False)
        nota("Requiere el venv del proyecto. No afecta al resto de la demostración.")
        return

    ip = q.base.replace("http://", "")
    # `homing_settle_time` va explicito y NO en su default (0.0). Este bloque corre
    # justo despues del swing-up, con el pendulo todavia girando: lanzar el homing
    # asi hace que la rutina lea como tope una perturbacion del mecanismo. Medido
    # en qube_real.py: 3 de 24 corridas detectaron el tope 19 deg antes del real, y
    # hoy el firmware directamente aborta con codigo 5. A diferencia de
    # `Qube.homing()`, el entorno NO reintenta: levanta excepcion y el bloque muere.
    print("\n  Esperando que el mecanismo se aquiete antes del homing…")
    q.reposo()
    env = QubeRealEnv(esp32_ip=ip, reset_settle_time=1.0, homing_settle_time=3.0)
    try:
        obs, info = env.reset(options={"homing": True})
        h = info.get("homing", {})
        dato("reset con recalibración", "completado", True)
        dato("  recorrido medido", f"{h.get('range_deg', 0):.2f}°")
        dato("  centro adoptado", f"{h.get('center_raw_deg', 0):.2f}°")
        dato("  error de estacionamiento", f"{h.get('park_error_deg', 0):.2f}°")
        dato("  marco de referencia (zero_epoch)", str(info.get("zero_epoch")))
        dato("theta al inicio del episodio", f"{float(obs[0]) * 57.2958:.2f}°",
             abs(float(obs[0]) * 57.2958) < 5)
        nota("""
            El episodio arranca centrado y con el cero recién validado. Si el homing
            fallara, el entorno levanta excepción en vez de entrenar contra una
            referencia desconocida: es preferible caerse a generar datos corruptos.
        """)
    finally:
        env.close()


def bloque6(q: Qube) -> None:
    titulo(6, "Metodología: por qué los números son confiables")
    nota("""
        Buena parte del trabajo fue descubrir que mediciones anteriores estaban
        contaminadas. Tres ejemplos, todos detectados y corregidos:

        1. El cero del péndulo se redefinía solo a mitad de ensayo. Un péndulo
           colgando e inmóvil llegó a leer 98°. Cualquier umbral absoluto sobre
           ese ángulo era falso.

        2. El estimador de velocidad tiene ganancia 1.52, no 1. Para el
           aprendizaje por refuerzo da igual —el simulador usa el mismo filtro y
           lo que importa es que coincidan— pero para calcular ENERGÍA es un
           error de 2.3× en el término cinético.

        3. Un "traspaso perfecto" registrado como velocidad 0.0 resultó ser un
           artefacto: el filtro se reiniciaba justo al cruzar la vertical. La
           traza mostraba al péndulo pasando a 470°/s.

        La conclusión metodológica: en este banco, una medición que no se
        contrasta con una vía independiente no es un resultado.
    """)
    print("\n  Esperando que el péndulo se detenga para leer su cero…")
    quieto = q.reposo()
    d = q.st()
    a = float(d["pend_position_deg"])
    dato("péndulo en reposo", "sí" if quieto else "no se detuvo a tiempo", quieto)
    if quieto:
        dato("su cero tras todos los ensayos", f"{a:.2f}°", abs(a) < 5)
        nota("""
            Colgando en reposo debe leer 0. Antes de corregir el defecto (1), tras un
            swing-up con giro este mismo número llegaba a 98°.
        """)
    # `pend_wraps` es MONOTONICO desde el arranque de la placa: el valor crudo
    # arrastra todo lo que haya girado antes de esta demo. Lo informativo es la
    # diferencia contra la linea base tomada al empezar.
    w = d.get("pend_wraps")
    w0 = getattr(q, "wraps0", None)
    if w is not None and w0 is not None:
        dato("vueltas de péndulo acotadas", f"{int(w) - int(w0)}  (durante esta demo)")
    else:
        dato("vueltas de péndulo acotadas", f"{w if w is not None else '—'}  (acumulado)")
    dato("recorrido del brazo", f"{float(d.get('homing_range', 0)):.2f}°")


def cierre(_q: Qube) -> None:
    titulo(7, "Estado y trabajo pendiente")
    print(f"""
  {C['ok']}Funcionando y verificado{C['n']}
    · Homing automático: recupera el cero con dispersión de 1 conteo de encoder
    · Los 8 modos del firmware entran y responden (validado con 3 repeticiones)
    · Control de posición del brazo (PID) converge de forma repetible
    · Bombeo del swing-up: crece de forma sostenida y plafona en 142–154°
      (y en 2 de 3 corridas pasa de largo por arriba: la energía alcanza)
    · Entorno de entrenamiento con recuperación autónoma del cero

  {C['no']}Pendiente{C['n']}
    · Captura: el controlador de equilibrio no sostiene el péndulo arriba
    · Ajuste del PID (sobrepaso alto, no bloqueante)

  {C['d']}Registro completo de problemas, con evidencia y estado:
    docs/REGISTRO_PROBLEMAS.md
  Experimentos con datos crudos y scripts reproducibles:
    experiments/2026-07-30_*/{C['n']}
""")


BLOQUES = {1: bloque1, 2: bloque2, 3: bloque3, 4: bloque4,
           5: bloque5, 6: bloque6, 7: cierre}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ip", default=os.environ.get("QUBE_IP", "192.168.4.1"))
    ap.add_argument("--solo", default="", help="p.ej. 1,2,4")
    ap.add_argument("--sin-pausa", action="store_true")
    a = ap.parse_args()

    # Validar --solo ANTES de tocar la placa: un typo no tiene por que costar el
    # arranque del hardware ni descubrirse recien cuando la ESP32 contesta.
    if a.solo:
        try:
            quiere = [int(x) for x in a.solo.split(",") if x.strip()]
        except ValueError:
            print(f"\n{C['no']}  --solo espera números separados por coma, p.ej. 2,4,5{C['n']}\n")
            sys.exit(2)
        desconocidos = [n for n in quiere if n not in BLOQUES]
        if desconocidos or not quiere:
            print(f"\n{C['no']}  Bloques inexistentes: "
                  f"{', '.join(str(x) for x in desconocidos) or '(ninguno indicado)'}."
                  f"  Disponibles: {', '.join(str(x) for x in BLOQUES)}{C['n']}\n")
            sys.exit(2)
    else:
        quiere = list(BLOQUES)

    q = Qube(a.ip)
    print(f"\n{C['b']}  DEMOSTRACIÓN DE AVANCE — QUBE Servo (péndulo de Furuta){C['n']}")
    print(f"{C['d']}  Antonio Badilla · Ingeniería Mecánica USACH{C['n']}")
    try:
        d = q.st()
    except requests.RequestException:
        print(f"\n{C['no']}  No responde la placa en {a.ip}.{C['n']}")
        print(f"{C['d']}  Verificar que esté encendida y en la misma red.{C['n']}\n")
        sys.exit(1)
    if not d.get("ina_ok"):
        print(f"\n{C['no']}  El INA219 no responde: sin protección de corriente no se energiza el motor.{C['n']}\n")
        sys.exit(1)

    # Linea base de `pend_wraps` (monotonico desde el arranque de la placa): el
    # bloque 6 informa la diferencia contra este valor, no el crudo.
    try:
        q.wraps0 = int(d["pend_wraps"])
    except (KeyError, TypeError, ValueError):
        q.wraps0 = None

    fallidos: list[int] = []
    try:
        for n in quiere:
            if not a.sin_pausa and n != quiere[0]:
                input(f"\n{C['d']}  [ENTER para continuar]{C['n']}")
            try:
                BLOQUES[n](q)
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                # Aislado a proposito: que falle un bloque no debe costar los que
                # siguen. En una presentacion es peor quedarse sin el resto.
                fallidos.append(n)
                print(f"\n{C['no']}  El bloque {n} falló: {exc}{C['n']}")
                print(f"{C['d']}  Se continúa con el resto. Para reintentarlo solo:")
                print(f"    python demo_avance.py --ip {a.ip} --solo {n}{C['n']}")
                with contextlib.suppress(requests.RequestException):
                    q.cmd(intentos=1, m=0)
    except KeyboardInterrupt:
        print(f"\n{C['d']}  Interrumpido.{C['n']}")
    finally:
        # El motor NUNCA queda energizado al salir. Se insiste bastante: una caída
        # transitoria de HTTP no debe traducirse en una alarma innecesaria, pero
        # tampoco se declara detenido sin haberlo confirmado.
        #
        # `intentos=1` es deliberado: `cmd()` ya reintenta 5 veces con 5 s de
        # timeout, y anidar eso dentro de este lazo daba hasta ~7 min de terminal
        # congelada al salir. Aca se quiere UN intento rapido por vuelta.
        parado = False
        for i in range(15):
            try:
                q.cmd(intentos=1, m=0)
                parado = True
                break
            except requests.RequestException:
                if i == 0:
                    print(f"\n{C['d']}  Placa sin responder; insistiendo con el corte…{C['n']}")
                time.sleep(1.0)
        if parado:
            print(f"\n{C['d']}  Motor detenido.{C['n']}")
        else:
            print(f"\n{C['no']}  NO se pudo confirmar el corte tras 15 intentos.{C['n']}")
            print(f"{C['d']}  ATENCIÓN: el watchdog de comandos del firmware NO cubre los")
            print("  modos de esta demo (sólo el 1 y el 6). El único respaldo es el")
            print(f"  límite de 95° del brazo. Verificar la placa o cortar la alimentación.{C['n']}")
        if fallidos:
            print(f"\n{C['no']}  Bloques con fallo: "
                  f"{', '.join(str(x) for x in fallidos)}{C['n']}")
            print(f"{C['d']}  El resto se completó.{C['n']}")
        print()


if __name__ == "__main__":
    main()
