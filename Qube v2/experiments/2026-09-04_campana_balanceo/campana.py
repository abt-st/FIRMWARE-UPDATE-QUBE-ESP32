"""Campana de balanceo: llevar el swing-up a un balanceo que se sostenga.

Que se mide, exactamente: **cuanto aguanta el modo 4 despues de un traspaso desde el
modo 5**, con el reintento ilimitado corriendo. El firmware ya tiene su propia
definicion de exito y es la que se usa aca, sin inventar otra: sobrevivir
`LQR_SUCCESS_MS` = 3000 ms re-arma el presupuesto de reintentos (`:4587`). Por debajo
de eso el propio firmware considera que el intento no prospero.

Linea base contra la que se compara (misma placa, 2026-08-30, defaults de fabrica):
supervivencia 0,79 s mediana / 1,76 s maxima sobre 20 traspasos en 300 s; **ninguno**
llego a 3 s. Esa tanda esta en `../2026-08-30_reintento_ilimitado/`.

⚠ El banco deriva DENTRO de una sesion (tras ~60 corridas el swing-up baja a 2/5
traspasos). Por eso la campana arranca siempre con `C0_base` y vuelve a correrlo cada
tantas condiciones: **solo se comparan configuraciones de la misma sesion**, y una
mejora medida contra una base de otro dia no es una mejora.

    python campana.py C0_base [minutos]
    python campana.py --lista
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

URL = "http://192.168.4.1"
AQUI = Path(__file__).parent
DATOS = AQUI / "data"
# ⚠ CADA peticion a /state cuesta UN atraso del lazo de control. Medido el 2026-09-04
# con el motor quieto, cuatro ventanas de 45 s: sin muestrear, 1 overrun; muestreando a
# 8 Hz, 257 overruns contra 256 peticiones. Uno por peticion, exacto. La telemetria
# serial no influye (254 contra 257). El peor periodo pasa de ~19 ms a ~22 ms, sobre un
# nominal de 2000 us.
#
# O sea que muestrear a 8 Hz deja al LQR ciego ~8 veces por segundo, y con
# w_n = 14,34 rad/s una desviacion crece x1,33 en cada hueco de 20 ms. Con balanceos que
# duran 1,3 s, el instrumento no es despreciable frente a lo que mide. `--hz` existe para
# poder medir cuanto de lo observado es la planta y cuanto es el sondeo.
PERIODO_S = 0.12  # ~8 Hz por defecto; se cambia con el 3er argumento
EXITO_MS = 3000  # LQR_SUCCESS_MS del firmware. No es un umbral inventado aca.

FALLAS = {
    0: "ninguna",
    1: "el pendulo se cayo",
    2: "el pendulo dio una vuelta",
    3: "el brazo llego al tope",
    4: "nunca llego a la vertical",
    5: "el recentrado no pudo volver",
    6: "el pendulo no se aquieto para el re-cero",
}

# ── Configuraciones ────────────────────────────────────────────────────────────
# Todas parten de los valores del firmware y se mueven poco. Lo que cambia cada una
# y por que esta en `nota`; `verificar` lista los campos de /state que deben quedar
# con el valor pedido (los que /state no publica quedan como no verificables).
#
# BASE_CMD son los defaults compilados y se manda ENTERO antes de cada condicion. Sin
# esto una condicion hereda en silencio los parametros de la anterior —la placa no se
# reinicia entre tandas— y la tanda mide una configuracion que nadie escribio.
BASE_CMD: dict[str, float | int] = {
    "lqr1": 2.0,
    "lc": 400,
    "lpm": 70,
    "cg": 0,
    "tn": 155,
    "sp": 60,
    "ke": -1,
    "lqr2": 22.0,
    "lqr4": 9.0,
    "lqr2n": 30.0,
    "lqr4n": 15.0,
    "lqr2vn": 55.0,
    "lqr4vn": 20.0,
    "pc": 0.0,
    "pr": 70.0,
    "ec": 1.15,
    "pl": 0,
    "sz": 1,
    "rt": 1,
    "tr": 1,
}

CONFIGS: dict[str, dict] = {
    "C0_base": {
        "cmd": {},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "defaults de fabrica. Linea base de ESTA sesion.",
    },
    # ── Rama A: el brazo se queda sin recorrido ────────────────────────────────
    # Medido en C0_base de esta sesion: 23 de 28 intentos mueren en el tope del brazo
    # (15 bombeando en m5, 8 balanceando en m4) y NINGUN episodio de m4 termino con el
    # pendulo caido. El pendulo no es el problema; el recorrido del brazo si.
    # El centro de oscilacion del bombeo se sento en -9,9 deg: el brazo usa 71 deg del
    # lado negativo y 50 del positivo, y toca -95 mientras por el otro lado sobra
    # recorrido. `pc` existe exactamente para eso y esta en 0.
    "C1_pc1": {
        "cmd": {"pc": 1.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "recentrado del bombeo `pc` 0 -> 1,0: resta la media lenta de la "
        "posicion a la referencia, o sea cancela justo el corrimiento de -9,9 deg "
        "medido. El comentario del firmware dice que la deriva no se reproduce desde "
        "v1.58.8; en esta sesion volvio.",
    },
    "C2_pc1_pr60": {
        "cmd": {"pc": 1.0, "pr": 60.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "ademas del recentrado, amplitud de la referencia `pr` 70 -> 60: deja "
        "35 deg de margen al limite de 95 en vez de 25. Cuesta energia por ciclo, asi "
        "que si el traspaso se cae, `pr` es lo primero que se devuelve a 70.",
    },
    # ── Rama B: el catch y la autoridad del LQR ────────────────────────────────
    # Con `pc=1.0` fijo (C1_pc1 lo gano: 8 -> 19 traspasos, fallas bombeando 15 -> 8).
    "C3_lc0": {
        "cmd": {"lc": 0, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 0, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "catch fuera (P4/H2). CORRIDA 2026-09-04: NO SIRVE — p50 246 ms contra "
        "606 de C1 y nueve caidas del pendulo contra una. El catch si hace trabajo: "
        "sin el, el LQR recibe el pendulo con demasiada velocidad y lo pierde. H2 queda "
        "refutada en su forma extrema (lc=0); queda abierto si 400 ms es demasiado.",
    },
    "C4_lc200": {
        "cmd": {"lc": 200, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 200, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "biseccion entre los 400 ms del firmware y el 0 que fallo: frena la "
        "entrega pero devuelve el control al LQR 200 ms antes. Si 400 es el optimo, "
        "esto tiene que salir entre C1 y C3.",
    },
    "C9_lc600": {
        "cmd": {"lc": 600},
        "verificar": {"lqr_catch_ms": 600, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "catch 400 -> 600 ms. Es la unica direccion que esta sesion respalda: "
        "`lc=0` fue lo unico que salio claramente FUERA de la banda de ruido, y salio "
        "para el lado malo (p50 246 contra una banda base de [530, 753]). Si mas freno "
        "sigue ayudando, el optimo esta por encima de los 400 del firmware.",
    },
    "C10_lc800": {
        "cmd": {"lc": 800},
        "verificar": {"lqr_catch_ms": 800, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "catch 600 -> 800 ms, solo si C9 sale por encima de la banda. Hay un "
        "techo: el catch aplica +-25 PWM en un sentido fijo, y cuanto mas dura mas "
        "recorrido de brazo se come antes de que el LQR tome el control.",
    },
    "C5_lpm110": {
        "cmd": {"lpm": 110, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 110, "lqr_centering_grace": 0},
        "nota": "techo del LQR 70 -> 110 sobre PWM_MAX = 200 (P4/H3): con 70 la salida "
        "esta saturada el 93 % del tiempo y las cuatro ganancias no pueden influir. "
        "Con mas techo el LQR corrige antes y con menos excursion de brazo, que es la "
        "falla dominante que quedo (13 de 27 mueren en el tope BALANCEANDO).",
    },
    "C6_tn162": {
        "cmd": {"lpm": 110, "tn": 162, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 110, "lqr_centering_grace": 0},
        "nota": "traspaso 155 -> 162 grados. OJO: medido en esta sesion, el traspaso ya "
        "dispara con |alpha| mediana 163,7 y E/E* 0,98, o sea que el umbral efectivo "
        "no lo fija `tn`. Se corre igual para ver si recorta la cola de entregas malas.",
    },
    "C7_k4_18": {
        "cmd": {"lpm": 110, "tn": 162, "lqr4": 18.0, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 110, "lqr_centering_grace": 0},
        "nota": "K4 9 -> 18: al corregir H4 (un RAD_TO_DEG de mas) el k4 efectivo se "
        "redujo a la mitad y la sintonia previa nunca se rehizo. Mas amortiguamiento "
        "de alpha = menos par pedido al brazo.",
    },
    # ── Rama C: las ganancias del LQR, ahora que los signos estan bien ─────────
    # v1.68.0 dice explicitamente que ninguna sintonia anterior de m4/m5/m7 es
    # transferible: todas se hicieron con los seis terminos de centrado invertidos.
    # La falla dominante sigue siendo el brazo sin recorrido (11 en m4 + 11 en m5 de
    # 27 en la base de v1.68.0), y `lqr_K1` es la unica ganancia que mira la POSICION
    # del brazo. Con K1 = 2 contra K2 = 22 el lazo casi no la regula.
    "C11_k1_4": {
        "cmd": {"lqr1": 4.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "K1 2 -> 4: la ganancia de POSICION del brazo, la unica que se opone a "
        "la deriva desde dentro del LQR en vez de desde el centering. Ataca directo la "
        "falla dominante. Se dobla y no mas: K1 grande pelea con la maniobra que el "
        "pendulo necesita.",
    },
    "C12_k1_4_lpm110": {
        "cmd": {"lqr1": 4.0, "lpm": 110},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 110, "lqr_centering_grace": 0},
        "nota": "K1 doblado mas el techo de PWM en 110. `lpm=110` solo subio la mediana "
        "de 360 a 556 y elimino los episodios que nunca llegaron a la vertical, pero "
        "bajo el mejor balanceo; con K1 pidiendo mas correccion de brazo, el techo "
        "extra tiene a que dedicarse.",
    },
    # H5 (las ganancias) es la unica hipotesis de P4 que queda viva, y desde v1.68.0 es
    # medible por primera vez fuera del regimen de rele: con los signos corregidos el
    # PWM esta contra su techo efectivo el 28,6 % del tiempo, no el 70,4 % de agosto, y
    # la mediana de |pwm| es 42 sobre 70. Hay margen para que una ganancia influya.
    # Medido a 500 Hz: alpha oscila con desviacion de 11 a 24 grados dentro del episodio,
    # o sea que el pendulo NO esta regulado. K4 es el amortiguamiento de alpha, y al
    # corregir H4 su valor efectivo se redujo a la mitad sin rehacer la sintonia.
    "C13_k4_18": {
        "cmd": {"lqr4": 18.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "K4 9 -> 18, sola y sin nada mas encima. Es la condicion que H5 pide "
        "primero: mas amortiguamiento de alpha con margen de PWM para aplicarlo.",
    },
    "C14_k4_18_k2_30": {
        "cmd": {"lqr4": 18.0, "lqr2": 30.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "K4 doblado mas K2 22 -> 30 (el valor que el firmware ya usa en la banda "
        "`near`, o sea nada exotico). El CARE pide K2 = 148,7; subir a 30 es el primer "
        "paso en esa direccion sin salirse de valores que el codigo ya contiene.",
    },
    # ── Rama D: la banda que de verdad manda durante el balanceo ───────────────
    # El gain scheduling tiene tres tramos: |alpha| < 5 -> (K2 55, K4 20);
    # |alpha| < 25 -> (30, 15); resto -> la base (22, 9). Medido a 500 Hz, alpha oscila
    # dentro del episodio con desviacion de 11 a 24 grados alrededor de una mediana de
    # +7, o sea que **el balanceo transcurre casi entero en la banda `near`**.
    #
    # Eso reinterpreta C13: `lqr4` es la K4 de la banda BASE, que solo actua con
    # |alpha| > 25, o sea cuando el pendulo ya se esta cayendo. Doblarla ayudo a
    # recuperar, no a balancear. Y explica C14: subir `lqr2` de 22 a 30 iguala la base
    # con `near` y lo unico que hace es borrar el escalon.
    #
    # Para tocar el regimen de balanceo hay que mover `lqr4n`.
    "C15_k4n_25": {
        "cmd": {"lqr4": 18.0, "lqr4n": 25.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "amortiguamiento de la banda `near` 15 -> 25, sobre el K4 base de 18 de "
        "C13 (la unica condicion que cruzo los 3 s alguna vez). 25 esta entre el 20 que "
        "el firmware ya usa en `very_near` y el doble del valor actual.",
    },
    "C16_k4n_25_solo": {
        "cmd": {"lqr4n": 25.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 70, "lqr_centering_grace": 0},
        "nota": "la banda `near` sola, con la base en su valor de fabrica. Separa el "
        "efecto de C15 en sus dos mitades: sin esto no se sabe cual de las dos K4 hizo "
        "algo, que es el error que ya se cometio al leer C13.",
    },
    "C8_pc2": {
        "cmd": {"lpm": 110, "pc": 2.0},
        "verificar": {"lqr_catch_ms": 400, "lqr_pwm_max": 110, "lqr_centering_grace": 0},
        "nota": "recentrado mas fuerte: con `pc=1` el centro del bombeo mejoro de -9,9 "
        "a -7,0 pero no llego a cero. Si el resto queda igual, el corrimiento residual "
        "todavia esta comiendo recorrido.",
    },
    # `cg=1` (gracia del centering, P4/H6) queda FUERA de la escalera a proposito: los
    # 8 episodios de m4 de la base murieron en el tope del brazo, y `cg=1` justamente
    # QUITA el centering durante los primeros 2 s. La hipotesis H6 sigue viva, pero
    # esta sesion no la respalda y probarla aqui seria empujar en el sentido contrario
    # a la evidencia. Se conserva como condicion suelta para medirla si la rama A cierra.
    "X_cg1": {
        "cmd": {"lpm": 110, "cg": 1, "pc": 1.0},
        "verificar": {"lqr_catch_ms": 0, "lqr_pwm_max": 110, "lqr_centering_grace": 1},
        "nota": "gracia del centering (P4/H6), fuera de la escalera: contradice la "
        "evidencia de esta sesion y se corre solo para cerrar la hipotesis.",
    },
}


def estado(timeout: float = 4.0) -> dict | None:
    try:
        return requests.get(URL + "/state", timeout=timeout).json()
    except (requests.RequestException, ValueError):
        return None


def cmd(q: str) -> bool:
    try:
        return requests.get(f"{URL}/cmd?{q}", timeout=4).status_code == 200
    except requests.RequestException:
        return False


def pedir_modo(m: int, espera_s: float = 3.0) -> bool:
    """Pide el modo y COMPRUEBA que entro (un 200 no es un comando aplicado)."""
    cmd(f"m={m}")
    t0 = time.time()
    while time.time() - t0 < espera_s:
        s = estado()
        if s and (s["mode"] == m or (m == 3 and s["homing_ok"])):
            return True
        time.sleep(0.2)
    s = estado()
    print(f"  el modo {m} NO entro (mode={s['mode'] if s else '?'}, mode_reject={s.get('mode_reject') if s else '?'})")
    return False


def aplicar(nombre: str) -> tuple[bool, list[str]]:
    """Manda los parametros de la configuracion y verifica los que /state publica.

    `tn` y `sp` NO se publican en /state: quedan declarados como no verificables en el
    encabezado de la traza en vez de darse por buenos en silencio.
    """
    conf = CONFIGS[nombre]
    avisos: list[str] = []
    efectivo = {**BASE_CMD, **conf["cmd"]}
    for k, v in efectivo.items():
        if not cmd(f"{k}={v}"):
            avisos.append(f"el comando {k}={v} no devolvio 200")
        time.sleep(0.05)
    cmd("rtn=-1")  # reintento ilimitado en toda la campana
    # Salud del lazo POR TANDA. `loop_overruns` y `loop_dt_max_us` son acumulados desde
    # el ultimo reset: sin esto, a mitad de sesion valen 1488 y no dicen nada de la tanda
    # que se esta por correr. El peor caso del arranque (escaneo WiFi bloqueante) domina
    # si no se reinicia el contador.
    cmd("rj=1")
    time.sleep(0.3)
    s = estado()
    if s is None:
        return False, ["la placa no responde tras aplicar la configuracion"]
    for campo, esperado in conf["verificar"].items():
        real = s.get(campo)
        if real is None or abs(float(real) - float(esperado)) > 1e-6:
            avisos.append(f"{campo}={real}, se pidio {esperado}")
    if s.get("swing_retry_max", 0) >= 0:
        avisos.append(f"swing_retry_max={s['swing_retry_max']}, se pidio ilimitado")
    return not avisos, avisos


# ── Metricas ───────────────────────────────────────────────────────────────────
def episodios(muestras: list[dict]) -> list[dict]:
    """Un episodio = una estadia en modo 4. Devuelve su supervivencia y como acabo.

    `lqr_alive_ms` deja de actualizarse al salir del modo 4 y conserva el valor final a
    proposito, asi que el maximo de la ventana [entrada a m4 .. 2 muestras despues de
    salir] es lo que aguanto ese intento, sin carrera con el muestreo.

    ⚠ Dos formas en que ese numero MIENTE, las dos encontradas el 2026-09-04 mirando por
    que las dos lineas base daban un maximo de 1502 ms exacto:

    1. **`lqr_alive_ms` no se pone en cero al entrar al modo 4.** Conserva el valor del
       episodio ANTERIOR hasta que termina el catch (400 ms). Un episodio corto muestreado
       a 8 Hz se lleva entonces la supervivencia del anterior: medido, tres episodios de
       una sola muestra figuraban con 498, 1238 y 1501 ms. Se acota contra el reloj de
       pared de la propia traza, que es un limite superior honesto de cuanto pudo estar
       ahi. No hace falta creerle al firmware para eso.
    2. **Un episodio que termina en `swing_fail_reason = 4` no es un balanceo.** Ese es
       `LQR_ARRIVE_TIMEOUT_MS`: el firmware se rinde a los 1500 ms porque el pendulo
       NUNCA se acerco a la vertical (`|alpha| < 25` ni una vez). Los cinco episodios de
       motivo 4 de las bases dieron 1501-1502 ms, o sea el timeout, y arrastraban el
       maximo de toda la tanda. Se marcan con `llego_arriba = False` y quedan fuera de la
       estadistica de supervivencia.
    """
    eps: list[dict] = []
    i = 0
    n = len(muestras)
    while i < n:
        if muestras[i]["mode"] != 4:
            i += 1
            continue
        j = i
        while j < n and muestras[j]["mode"] == 4:
            j += 1
        ventana = muestras[i : min(j + 2, n)]
        alive = max(m.get("lqr_alive_ms") or 0 for m in ventana)
        salida = muestras[j] if j < n else muestras[-1]
        # Cota por reloj de pared: no pudo estar en m4 mas de lo que duro el tramo.
        tope_ms = round((salida["t"] - muestras[i]["t"]) * 1000)
        alive = min(alive, tope_ms)
        eps.append(
            {
                "t": muestras[i]["t"],
                "alive_ms": alive,
                "llego_arriba": salida.get("swing_fail_reason", 0) != 4,
                "fail": salida.get("swing_fail_reason", 0),
                "trans_alpha": muestras[i].get("swing_trans_alpha"),
                "trans_vel": muestras[i].get("swing_trans_vel"),
                "trans_energy": muestras[i].get("swing_trans_energy"),
                "trans_reason": muestras[i].get("swing_trans_reason"),
            }
        )
        i = j + 1
    return eps


def metricas(muestras: list[dict]) -> dict:
    eps = episodios(muestras)
    # Solo los episodios en los que el pendulo LLEGO a la vertical cuentan como
    # balanceo. Los del timeout de llegada son 1500 ms de brazo administrando un
    # pendulo que nunca estuvo arriba, y arrastraban el maximo de la tanda.
    alives = [e["alive_ms"] for e in eps if e["llego_arriba"]]
    sin_llegar = sum(1 for e in eps if not e["llego_arriba"])
    intentos = max((m["swing_retry_count"] for m in muestras), default=0)
    fallas: dict[int, int] = {}
    prev = None
    for m in muestras:
        r = m.get("swing_fail_reason", 0)
        c = m["swing_retry_count"]
        if (r, c) != prev and r != 0:
            fallas[r] = fallas.get(r, 0) + 1
        prev = (r, c)
    return {
        "duracion_s": muestras[-1]["t"] if muestras else 0.0,
        "muestras": len(muestras),
        "reintentos": intentos,
        "traspasos": len(eps),
        "traspasos_sin_llegar": sin_llegar,
        "alive_p50_ms": statistics.median(alives) if alives else 0,
        "alive_max_ms": max(alives) if alives else 0,
        "exitos_3s": sum(1 for a in alives if a >= EXITO_MS),
        "fallas": fallas,
        "episodios": eps,
    }


def veredicto(met: dict, bases: list[dict]) -> tuple[str, list[str]]:
    """Sirve / no sirve, contra la ENVOLVENTE de las lineas base de esta sesion.

    ⚠ Por que una sola base no alcanza. El 2026-09-04 dos corridas de `C0_base` con
    parametros identicos, separadas por 20 minutos, dieron:

        traspasos  8 y 14   ·   p50  530 y 753 ms   ·   max  799 y 1174 ms

    Esa banda se traga la diferencia de casi cualquier condicion de la escalera. Un
    criterio que compare contra UNA base declara «mejora» a la mitad de las repeticiones
    de la propia base — que es precisamente el error que ya se cometio tres veces en este
    banco. Asi que aca la banda de ruido es explicita: [min, max] sobre todas las
    corridas de `C0_base` de la sesion, y una condicion tiene que salirse de ella.

    Cinco niveles:
      LOGRADO   — al menos un intento aguanto >= 3 s (`LQR_SUCCESS_MS`, del firmware).
      MEJORA    — p50 Y max por encima del techo de la banda de las bases.
      NO SIRVE  — p50 o max por debajo del piso de la banda.
      DENTRO DEL RUIDO — cae dentro de la banda: la tanda no distingue esta condicion
                  de no haber tocado nada. NO es un aval, es la falta de resolucion.
      INVALIDA  — cero traspasos: no se midio el balanceo.

    Con una sola base disponible no hay banda, y todo lo que no sea LOGRADO se informa
    como SIN BANDA: hace falta repetir `C0_base` antes de poder juzgar.
    """
    if met["traspasos"] == 0:
        return "INVALIDA", ["cero traspasos a modo 4: la tanda no midio el balanceo"]
    if met["exitos_3s"] > 0:
        return "LOGRADO", [f"{met['exitos_3s']} intento(s) aguantaron >= {EXITO_MS} ms"]

    p50, mx = met["alive_p50_ms"], met["alive_max_ms"]
    if len(bases) < 2:
        return "SIN BANDA", [
            f"p50 {p50:.0f} ms · max {mx} ms. Hacen falta >= 2 corridas de C0_base "
            f"para saber cuanto de esto es ruido; hay {len(bases)}."
        ]

    # ── Potencia de la tanda ───────────────────────────────────────────────────
    # Una tanda con muchos menos traspasos que las bases no midio lo mismo: la
    # supervivencia se calcula sobre un puñado de episodios y su mediana no es
    # comparable con una de veinte. El 2026-09-05 `C15_k4n_25` dio 4 traspasos contra
    # una banda de 14-26 y el criterio la declaro NO SIRVE; la base de control corrida
    # inmediatamente despues dio 14, o sea que el banco estaba sano y lo que fallo fue
    # el veredicto. Sin esta compuerta, media tanda floja se lee como un efecto.
    trasp_base = [b["traspasos"] for b in bases]
    if met["traspasos"] < 0.5 * min(trasp_base):
        return "SIN POTENCIA", [
            f"{met['traspasos']} traspasos contra una banda base de "
            f"[{min(trasp_base)}, {max(trasp_base)}]: la tanda no es comparable",
            "repetir la condicion antes de atribuirle nada",
        ]

    p50s = [b["alive_p50_ms"] for b in bases]
    mxs = [b["alive_max_ms"] for b in bases]
    banda = (
        f"p50 {p50:.0f} ms contra banda base [{min(p50s):.0f}, {max(p50s):.0f}]; "
        f"max {mx} ms contra banda base [{min(mxs)}, {max(mxs)}]  (n={len(bases)} bases)"
    )
    if p50 > max(p50s) and mx > max(mxs):
        return "MEJORA", [banda]
    if p50 < min(p50s) or mx < min(mxs):
        return "NO SIRVE", [banda]
    return "DENTRO DEL RUIDO", [banda, "la tanda no distingue esta condicion de no haber tocado nada"]


def autoprueba() -> None:
    """El criterio contra casos que DEBEN fallar. Sin esto el veredicto no vale.

    Traducir un criterio a codigo es donde este banco ya fallo tres veces: un veredicto
    que devuelve lo mismo pase lo que pase se ve igual que uno correcto.
    """

    def traza(*tramos: tuple[int, int, int], motivo: int = 1) -> list[dict]:
        """(modo, alive_ms, n_muestras) -> muestras sinteticas."""
        out: list[dict] = []
        t = 0.0
        for modo, alive, n in tramos:
            for _ in range(n):
                out.append(
                    {
                        "t": round(t, 2),
                        "mode": modo,
                        "lqr_alive_ms": alive,
                        "swing_retry_count": 0,
                        "swing_fail_reason": motivo,
                    }
                )
                t += 0.12
        return out

    def m4(alive_ms: int) -> tuple[int, int, int]:
        """Un tramo de modo 4 con SUFICIENTES muestras para que `alive_ms` sea posible.

        La cota por reloj de pared hace que una traza sintetica floja se recorte sola:
        pedir 4000 ms de supervivencia en 20 muestras de 0,12 s es pedir 4 s dentro de
        2,4 s. La primera version de esta autoprueba tenia justo ese error y lo delato
        la propia cota, que es exactamente para lo que sirve.
        """
        return (4, alive_ms, int(alive_ms / 1000 / PERIODO_S) + 3)

    # ── Los dos defectos de la metrica, cada uno contra un caso que DEBE fallar ────
    # 1. Un episodio corto NO puede heredar la supervivencia del anterior. Aca el
    #    episodio B dura una sola muestra (0,24 s de reloj entre entrada y salida) pero
    #    el firmware todavia reporta los 1500 ms congelados del episodio A.
    def muestra(t: float, modo: int, alive: int, cuenta: int) -> dict:
        return {"t": t, "mode": modo, "lqr_alive_ms": alive, "swing_retry_count": cuenta, "swing_fail_reason": 1}

    contagio = [
        *traza(m4(1500)),
        muestra(1.20, 5, 1500, 0),
        muestra(1.32, 4, 1500, 1),
        muestra(1.44, 5, 1500, 1),
    ]
    eps = episodios(contagio)
    assert len(eps) == 2, f"no separo los dos episodios: {eps}"
    assert eps[1]["alive_ms"] <= 240, f"el episodio corto heredo la supervivencia del anterior: {eps[1]['alive_ms']} ms"

    # 2. El timeout de llegada (motivo 4) NO es un balanceo: 1500 ms con el pendulo que
    #    nunca subio. Tiene que quedar fuera de la estadistica de supervivencia.
    timeout = metricas(traza((5, 0, 5), m4(1500), (5, 0, 5), motivo=4))
    assert timeout["traspasos"] == 1 and timeout["traspasos_sin_llegar"] == 1, timeout
    assert timeout["alive_p50_ms"] == 0, "conto un timeout de llegada como supervivencia"
    assert timeout["exitos_3s"] == 0, "un timeout de llegada no puede contar como exito"

    # Un episodio de 4 s: el firmware lo llama exito, el criterio tambien.
    m = metricas(traza((5, 0, 10), m4(4000), (5, 0, 10)))
    assert m["traspasos"] == 1, m
    assert veredicto(m, [])[0] == "LOGRADO", "no reconocio un balanceo de 4 s"

    # Cero traspasos: no se puede juzgar, aunque la tanda haya durado.
    m0 = metricas(traza((5, 0, 300)))
    assert veredicto(m0, [])[0] == "INVALIDA", "juzgo una tanda sin un solo traspaso"

    # Una sola base no habilita ningun veredicto comparativo.
    una = [metricas(traza(m4(1800), (5, 0, 5), m4(1600), (5, 0, 5)))]
    cualquiera = metricas(traza(m4(900), (5, 0, 5), m4(900), (5, 0, 5)))
    assert veredicto(cualquiera, una)[0] == "SIN BANDA", "juzgo con una sola linea base"

    # ── La banda de ruido, con los numeros REALES del 2026-09-04 ───────────────
    # Dos bases identicas: p50 530 y 753, max 799 y 1174.
    bases = [
        {"alive_p50_ms": 530, "alive_max_ms": 799, "traspasos": 8},
        {"alive_p50_ms": 753, "alive_max_ms": 1174, "traspasos": 14},
    ]

    def tanda(*alives: int) -> dict:
        """Una tanda sintetica con UN episodio por valor, separados por modo 5.

        Los casos de prueba llevan al menos ocho episodios a proposito: con menos, la
        compuerta de potencia los rechaza —correctamente— y el caso deja de probar lo
        que decia probar.
        """
        tramos: list[tuple[int, int, int]] = []
        for a in alives:
            tramos += [m4(a), (5, 0, 4)]
        return metricas(traza(*tramos))

    # C1_pc1 real (p50 606, max 1217): cae DENTRO de la banda. Este es el caso que el
    # criterio anterior aprobaba como MEJORA, y es el error que hay que no repetir.
    c1 = tanda(1217, 800, 700, 650, 606, 560, 500, 450, 400)
    assert c1["alive_p50_ms"] == 606 and c1["alive_max_ms"] == 1217, c1
    assert veredicto(c1, bases)[0] == "DENTRO DEL RUIDO", "volvio a llamar MEJORA a una tanda dentro del ruido"

    # C3_lc0 real (p50 246, max 290): por debajo del piso de la banda -> NO SIRVE.
    c3 = tanda(290, 280, 270, 260, 246, 240, 230, 210, 200)
    assert veredicto(c3, bases)[0] == "NO SIRVE", "no rechazo una tanda por debajo de la banda"

    # Max altisimo pero mediana por debajo del piso: NO SIRVE, no es un golpe de suerte.
    suerte = tanda(2900, 400, 350, 300, 250, 220, 200, 180, 150)
    assert veredicto(suerte, bases)[0] == "NO SIRVE", "confundio un outlier con una mejora"

    # Una tanda con 4 traspasos contra una banda de 14-26 no se puede juzgar, por buenos
    # que salgan sus numeros. Son los valores reales de C15_k4n_25.
    bases_trasp = [
        {"alive_p50_ms": 187, "alive_max_ms": 1297, "traspasos": 14},
        {"alive_p50_ms": 545, "alive_max_ms": 1484, "traspasos": 26},
    ]
    floja = tanda(856, 800, 745, 700)
    assert veredicto(floja, bases_trasp)[0] == "SIN POTENCIA", "juzgo una tanda con 4 traspasos"
    sana = tanda(*([2600] * 16))
    assert veredicto(sana, bases_trasp)[0] != "SIN POTENCIA", "la compuerta rechazo una tanda con potencia"

    # Mejora real: p50 Y max por encima del techo de la banda.
    buena = tanda(2600, 2550, 2500, 2450, 2400, 2350, 2300, 2250, 2200)
    assert veredicto(buena, bases)[0] == "MEJORA", "no reconocio una mejora que se sale de la banda"

    # Separacion de episodios: dos estadias en m4 no pueden contarse como una.
    assert metricas(traza(m4(900), (5, 0, 8), m4(900)))["traspasos"] == 2
    print("autoprueba del criterio: OK (6 casos que deben fallar, 3 que deben pasar)")


def asegurar_homing(intentos: int = 3) -> bool:
    """Homing con reintento: un `homing_fail=1` aislado no es un banco enfermo.

    El 2026-09-04 el primer m3 de la sesion midio 261,4 grados (fuera de la ventana
    262-278) arrancando con el brazo a 42,9 y el pendulo suelto; los tres siguientes
    dieron 269,5 / 270,7 / 270,5. Un tope falso por friccion se ve exactamente asi
    —el recorrido sale ~8 grados corto— y abortar la campana por el primero cuesta
    una tanda entera.
    """
    s = estado()
    if s is None:
        print(f"la placa no responde en {URL}")
        return False
    if s["homing_ok"]:
        return True
    for intento in range(1, intentos + 1):
        print(f"sin homing: se pide m3 ({intento}/{intentos}; el brazo va a buscar los dos topes)")
        if not pedir_modo(3):
            return False
        t0 = time.time()
        while time.time() - t0 < 60:
            time.sleep(1.0)
            s = estado()
            if s and s["homing_ok"] and s["mode"] != 3:
                print(f"homing OK (rango {s['homing_range']:.2f} grados, centro {s['homing_center']:.2f})")
                return True
            if s and s["mode"] != 3 and not s["homing_ok"]:
                print(
                    f"  el homing fallo (fase={s['homing_phase']}, homing_fail={s.get('homing_fail')}, "
                    f"rango={s['homing_range']:.2f})"
                )
                break
        else:
            print("  el homing no termino en 60 s")
        time.sleep(2.0)
    print("  el homing fallo en todos los intentos; no se sigue")
    return False


def correr(nombre: str, minutos: float, hz: float = 8.0) -> int:
    autoprueba()
    if nombre not in CONFIGS:
        print(f"configuracion desconocida: {nombre}. Opciones: {', '.join(CONFIGS)}")
        return 1

    s = estado()
    if s is None:
        print(f"la placa no responde en {URL}")
        return 1
    print(f"placa: mode={s['mode']} v_bus={s['v_bus']:.2f} V ina_ok={s['ina_ok']} wn2={s.get('pend_wn2')}")
    if not s["ina_ok"]:
        print("INA219 caido: sin el no hay corte por calado. No se energiza el motor.")
        return 1
    if not asegurar_homing():
        return 1

    ok, avisos = aplicar(nombre)
    print(f"\n=== {nombre} ===\n{CONFIGS[nombre]['nota']}")
    print(f"parametros (cambios sobre los defaults): {CONFIGS[nombre]['cmd']}")
    if not ok:
        print("AVISO: la configuracion no quedo como se pidio:")
        for a in avisos:
            print("  - " + a)
    print("no verificables (/state no los publica): tn, sp, ke, lqr4")

    if not pedir_modo(5):
        return 1
    periodo = 1.0 / hz
    t0 = time.time()
    sello = datetime.now().strftime("%Y%m%d_%H%M%S")
    sufijo = "" if abs(hz - 8.0) < 1e-6 else f"_{hz:g}hz"
    traza = DATOS / f"{nombre}{sufijo}_{sello}.jsonl"
    muestras: list[dict] = []
    prev = None
    print(f"\nm5 durante {minutos:.1f} min. Ctrl-C corta y deja el banco en modo 0.")
    try:
        with traza.open("w", encoding="utf-8") as fh:
            fh.write(
                json.dumps(
                    {
                        "_meta": True,
                        "config": nombre,
                        "cmd": {**BASE_CMD, **CONFIGS[nombre]["cmd"]},
                        "nota": CONFIGS[nombre]["nota"],
                        "avisos_de_aplicacion": avisos,
                        "no_verificables": ["tn", "sp", "ke", "lqr4"],
                        "inicio": sello,
                        "poll_hz": hz,
                        "v_bus_inicial": s["v_bus"],
                    }
                )
                + "\n"
            )
            while time.time() - t0 < minutos * 60:
                st = estado()
                if st is None:
                    time.sleep(periodo)
                    continue
                m = {
                    "t": round(time.time() - t0, 3),
                    "mode": st["mode"],
                    "lqr_alive_ms": st.get("lqr_alive_ms"),
                    "swing_retry_count": st["swing_retry_count"],
                    "swing_fail_reason": st.get("swing_fail_reason", 0),
                    "swing_recenter_phase": st.get("swing_recenter_phase", 0),
                    "swing_zero_phase": st.get("swing_zero_phase", 0),
                    "swing_trans_reason": st.get("swing_trans_reason"),
                    "swing_trans_alpha": st.get("swing_trans_alpha"),
                    "swing_trans_vel": st.get("swing_trans_vel"),
                    "swing_trans_energy": st.get("swing_trans_energy"),
                    "pend_position_deg": st.get("pend_position_deg"),
                    "position_deg": st.get("position_deg"),
                    "v_bus": st.get("v_bus"),
                    "safety_action": st.get("safety_action", 0),
                    "safety_cuts": st.get("safety_cuts", 0),
                    "loop_overruns": st.get("loop_overruns", 0),
                    "loop_dt_max_us": st.get("loop_dt_max_us", 0),
                }
                fh.write(json.dumps(m) + "\n")
                muestras.append(m)
                clave = (m["mode"], m["swing_retry_count"], m["swing_fail_reason"])
                if clave != prev:
                    print(
                        f"  t={m['t']:6.1f}s  modo={m['mode']}  intentos={m['swing_retry_count']}"
                        f"  alive={m['lqr_alive_ms']}ms  motivo={m['swing_fail_reason']}"
                        f" ({FALLAS.get(m['swing_fail_reason'], '?')})"
                    )
                    prev = clave
                if m["mode"] == 0:
                    print("  el banco cayo a modo 0 solo; se corta la tanda")
                    break
                time.sleep(periodo)
    except KeyboardInterrupt:
        print("\ncortado a mano")
    finally:
        cmd("m=0")

    met = metricas(muestras)
    # Las bases se ACUMULAN, no se pisan: la banda de ruido sale de todas las corridas
    # de C0_base de la sesion, y con una sola no hay banda que valga.
    base_f = DATOS / "bases_sesion.json"
    bases: list[dict] = json.loads(base_f.read_text(encoding="utf-8")) if base_f.exists() else []
    if nombre == "C0_base" and abs(hz - 8.0) < 1e-6:
        bases.append({"sello": sello, **{k: v for k, v in met.items() if k != "episodios"}})
        base_f.write_text(json.dumps(bases, indent=2), encoding="utf-8")

    vd, razones = veredicto(met, bases)
    resumen = {"config": nombre, "traza": traza.name, "veredicto": vd, "razones": razones, **met}
    (DATOS / f"{nombre}{sufijo}_{sello}_resumen.json").write_text(json.dumps(resumen, indent=2), encoding="utf-8")

    print(f"\ntraza: {traza.name}")
    print(f"duracion {met['duracion_s']:.0f} s  ·  {met['muestras']} muestras  ·  {met['reintentos']} reintentos")
    print(f"traspasos a m4: {met['traspasos']}")
    print(f"supervivencia: p50 {met['alive_p50_ms']} ms  ·  max {met['alive_max_ms']} ms  ·  >=3 s: {met['exitos_3s']}")
    print("fallas: " + (", ".join(f"{FALLAS.get(k, k)} x{v}" for k, v in sorted(met["fallas"].items())) or "ninguna"))
    if muestras:
        ult = muestras[-1]
        print(
            f"salud del lazo en esta tanda: {ult.get('loop_overruns', 0)} overruns, "
            f"peor periodo {ult.get('loop_dt_max_us', 0)} us (nominal 2000)"
        )
    print(f"\nVEREDICTO {nombre}: {vd}")
    for r in razones:
        print("  " + r)
    return 0


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] in ("--lista", "-l"):
        autoprueba()
        for k, v in CONFIGS.items():
            print(f"\n{k}\n  {v['nota']}\n  {v['cmd']}")
        return 0
    minutos = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
    hz = float(sys.argv[3]) if len(sys.argv) > 3 else 8.0
    return correr(sys.argv[1], minutos, hz)


if __name__ == "__main__":
    raise SystemExit(main())
