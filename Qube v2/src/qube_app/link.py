"""Enlace HTTP con la placa: comandos, estado y paro de emergencia.

Reintentos generosos a propósito, por la misma razón que los documenta
``demo/demo_avance.py``: el lazo de la ESP32 llega a bloquearse ~95 ms cuando el stack
WiFi le roba tiempo, y ahí el servidor HTTP deja de responder unos segundos. Es
transitorio —la placa no se reinicia— pero una app que se cae por eso no sirve para
operar un banco.

**El failsafe del firmware no cubre a esta app.** Sólo vigila los modos 1 (PWM manual) y
6 (RL por HTTP); los modos 2, 4 y 5 son autónomos por diseño y siguen corriendo aunque
muera el enlace. El único respaldo entonces es el límite duro del brazo
(``SERVO_HARD_LIMIT_DEG = 95``), que dispara ``setMode(0)``. La UI lo declara en pantalla.
"""

from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter

from qube_rl.config import DEFAULT_ESP32_IP

logger = logging.getLogger(__name__)

#: Modos que mueven el brazo contra los topes mecánicos: exigen confirmación explícita.
MODES_THAT_MOVE_TO_STOPS = (3, 5)

#: Modos que el firmware **rechaza** si no se hizo homing (``hr=1``, por omisión activa
#: desde v1.60.0). Los modos 0 (parado), 1 (PWM manual, con el operador mirando) y 3 (el
#: homing mismo) no la necesitan. La lista está atada al ``setMode()`` del ``.ino``, y
#: ``tests/test_app_ui.py`` la verifica leyendo el firmware: si allá se agrega o se quita
#: un modo de la compuerta y acá no, la app vuelve a mentir sobre por qué no pasó nada.
MODES_REQUIRING_HOMING = (2, 4, 5, 6, 7)

#: Modos que el firmware rechaza con el INA219 caído (``sf=1``, por omisión activa).
#: Sin INA219 ``applySafetyLimits()`` saltea el brownout y el límite de corriente enteros
#: y en silencio: el stub de la librería devuelve 0,0 en todo.
MODES_REQUIRING_INA = (1, 2, 4, 5, 6, 7)

#: ``mode_reject`` de ``/state``: por qué el último ``?m=`` no tuvo efecto.
#:
#: Existe en el firmware desde v1.60.0 **justamente** para que un cliente pueda
#: explicarlo, y esta app no lo leía: un modo rechazado se veía igual que uno aplicado
#: —el encabezado seguía mostrando el modo anterior— y el único aviso salía por Serial,
#: que en este banco no se puede abrir sin reiniciar la placa.
MODE_REJECT_REASONS = {
    0: "",
    1: "modo fuera de rango (el firmware acepta 0–7)",
    2: "falta el homing: hacer «Homing (m3)», o soltar la compuerta con /cmd?hr=0",
    3: "INA219 caído: sin brownout ni límite de corriente. Soltar con /cmd?sf=0 sólo si se sabe lo que se hace",
}

#: ``safety_action`` de ``/state``: por qué la capa de seguridad intervino. Sin esto un
#: corte se ve como «el modo dejó de andar» y hay que adivinar.
#:
#: El valor 4 —corte por cordura del péndulo en los modos RL— no está en el comentario
#: del firmware, que sólo enumera 0–3; sale de la rama de [P17] en el despacho del lazo.
SAFETY_ACTIONS = {
    0: "",
    1: "derate por tensión",
    2: "CORTE por tensión (brownout)",
    3: "CORTE por corriente (calado)",
    4: "CORTE por cordura del péndulo (m6/m7): |α| crudo o vueltas fuera de rango",
}

#: ``swing_fail_reason`` de ``/state``: cómo terminó el último intento de balanceo.
SWING_FAIL_REASONS = {
    0: "",
    1: "el péndulo se cayó",
    2: "el péndulo dio una vuelta",
    3: "el brazo llegó al tope",
    4: "nunca llegó a la vertical",
    5: "el recentrado no pudo volver",
}

#: Etiquetas del selector de modos. El firmware acepta 0..7 sin huecos.
MODE_NAMES = {
    0: "0 · Libre (STOP)",
    1: "1 · PWM manual",
    2: "2 · PID servo",
    3: "3 · Homing (topes)",
    4: "4 · LQR",
    5: "5 · Swing-up",
    6: "6 · Deep RL (HTTP)",
    7: "7 · Deep RL (chip)",
}


class ReadOnlyError(RuntimeError):
    """Se intentó escribir con el enlace en modo sólo lectura.

    El contrato de concurrencia del proyecto (``qube_rl/envs/qube_real.py``) es *último
    que escribe gana*: si hay un entrenamiento RL corriendo, la app tiene que callarse.
    """


class QubeLink:
    """Cliente de ``/cmd`` y ``/state`` con reintentos y conexión persistente."""

    def __init__(self, ip: str = DEFAULT_ESP32_IP, timeout: float = 2.0) -> None:
        self.ip = ip
        self.base_url = f"http://{ip}"
        self.timeout = timeout
        #: Cuando es True, sólo pasa el paro de emergencia.
        self.read_only = False
        #: Round-trip de la última lectura de ``/state`` en ms, o ``None`` si aún no hubo.
        self.last_rtt_ms: float | None = None

        self._session = requests.Session()
        # Una sola conexión TCP reutilizada: la pila AsyncTCP de la ESP32 es sensible al
        # churn de conexiones, y el handshake se paga una vez en lugar de por petición.
        adapter = HTTPAdapter(pool_connections=1, pool_maxsize=4)
        self._session.mount("http://", adapter)
        self._session.headers.update({"Connection": "keep-alive"})

    # ── Escritura ─────────────────────────────────────────────────────────────

    def send(self, params: dict, retries: int = 5, force: bool = False) -> dict:
        """Envía ``GET /cmd`` con los parámetros dados. Lanza si no logra pasar.

        Toma el diccionario explícito —y no ``**kwargs``— porque los parámetros vienen
        armados desde la UI y desde la cola del sondeo, donde son datos, no literales.
        """
        if self.read_only and not force:
            raise ReadOnlyError(f"enlace en sólo lectura: no se envió {params}")
        last: Exception | None = None
        for attempt in range(retries):
            try:
                resp = self._session.get(f"{self.base_url}/cmd", params=params, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as exc:
                last = exc
                if attempt < retries - 1:
                    time.sleep(0.4)
        raise requests.RequestException(f"/cmd {params} falló tras {retries} intentos") from last

    def cmd(self, **params: object) -> dict:
        """Azúcar de :meth:`send` para las llamadas literales: ``link.cmd(m=2, s=20)``."""
        return self.send(params)

    def stop_motor(self, retries: int = 15) -> bool:
        """Paro de emergencia. **Nunca lanza** y **nunca respeta el sólo lectura**.

        Quince intentos, como en la demo: es la última orden que importa, y fallar en
        silencio aquí es dejar el motor energizado.
        """
        for _ in range(retries):
            try:
                self._session.get(f"{self.base_url}/cmd", params={"x": 1}, timeout=self.timeout)
                return True
            except requests.RequestException:
                time.sleep(0.2)
        logger.error("PARO DE EMERGENCIA SIN CONFIRMAR tras %d intentos — cortar la alimentación", retries)
        return False

    def reset_loop_metrics(self) -> dict:
        """``/cmd?rj=1``: reinicia ``loop_dt_max_us`` y ``loop_overruns``.

        Hay que llamarlo al arrancar cada captura o el peor caso del arranque —el
        escaneo WiFi bloqueante— domina la métrica y no se mide el lazo sino el boot.
        Es una lectura disfrazada de escritura: no mueve el motor, así que pasa también
        en modo sólo lectura.
        """
        return self.send({"rj": 1}, force=True)

    # ── Lectura ───────────────────────────────────────────────────────────────

    def state(self, retries: int = 3) -> dict:
        """Lee ``/state`` completo y actualiza :attr:`last_rtt_ms`."""
        last: Exception | None = None
        for attempt in range(retries):
            t0 = time.perf_counter()
            try:
                resp = self._session.get(f"{self.base_url}/state", timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                self.last_rtt_ms = (time.perf_counter() - t0) * 1000.0
                return data
            except requests.RequestException as exc:
                last = exc
                if attempt < retries - 1:
                    time.sleep(0.3)
        raise requests.RequestException(f"/state falló tras {retries} intentos") from last

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> QubeLink:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
