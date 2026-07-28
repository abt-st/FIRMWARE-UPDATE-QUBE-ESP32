"""QUBE Serial Tool — descubrir la IP y actualizar credenciales WiFi por serial.

GUI de escritorio (tkinter) que resuelve el problema del huevo y la gallina: la
GUI web se sirve DESDE el ESP32 por WiFi, así que para abrirla hay que conocer su
IP. Este lanzable habla por USB/serial (sin WiFi) para:

  * detectar el puerto del ESP32 (CP210x/CH340/Silicon Labs),
  * leer la IP LAN actual (comando `i`) y abrir la GUI web en el navegador,
  * escribir SSID/clave nuevos (`wifi_ssid`/`wifi_pass`) y reiniciar (`reboot`),
    reconectando para mostrar la IP nueva.

Uso:
    uv run python src/firmware/qube_serial_tool.py
    (o doble clic en QUBE-Serial-Tool.bat)

Requiere el firmware con el comando serial `reboot` (ver esp32_qube.ino).
"""

from __future__ import annotations

import queue
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import scrolledtext, ttk

import serial
import serial.tools.list_ports

# Reutiliza la autodetección de puerto ya validada en serial_cmd.py (mismo dir).
try:
    from serial_cmd import find_esp32_port
except ImportError:  # ejecutado fuera de la carpeta firmware
    def find_esp32_port() -> str:
        for p in serial.tools.list_ports.comports():
            desc = p.description.lower()
            if "cp210" in desc or "ch340" in desc or "silicon labs" in desc:
                return p.device
        ports = serial.tools.list_ports.comports()
        return ports[0].device if ports else "COM5"


BAUD = 115200
RESPONSE_WAIT = 1.2   # s a esperar tras cada comando antes de leer la respuesta
REBOOT_WAIT = 9.0     # s a esperar tras 'reboot' (re-enumeración USB + reconexión STA)
IP_RE = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})")


class QubeSerialTool:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.ser: serial.Serial | None = None
        self.lan_ip: str | None = None
        self.log_q: "queue.Queue[str]" = queue.Queue()
        self.busy = False

        root.title("QUBE Serial Tool — IP y credenciales WiFi")
        root.geometry("560x560")
        root.minsize(520, 480)

        pad = {"padx": 8, "pady": 4}

        # ── Puerto ────────────────────────────────────────────────────────
        fPort = ttk.LabelFrame(root, text="1. Puerto serial")
        fPort.pack(fill="x", **pad)
        self.portVar = tk.StringVar()
        self.portCombo = ttk.Combobox(fPort, textvariable=self.portVar, width=28, state="readonly")
        self.portCombo.grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(fPort, text="Refrescar", command=self.refresh_ports).grid(row=0, column=1, padx=4)
        self.connBtn = ttk.Button(fPort, text="Conectar", command=self.toggle_connection)
        self.connBtn.grid(row=0, column=2, padx=4)
        self.connLbl = ttk.Label(fPort, text="Desconectado", foreground="#b00")
        self.connLbl.grid(row=1, column=0, columnspan=3, padx=6, sticky="w")

        # ── IP / Red ──────────────────────────────────────────────────────
        fNet = ttk.LabelFrame(root, text="2. Red / IP")
        fNet.pack(fill="x", **pad)
        self.detectBtn = ttk.Button(fNet, text="Detectar IP", command=self.detect_ip, state="disabled")
        self.detectBtn.grid(row=0, column=0, padx=6, pady=6)
        self.openBtn = ttk.Button(fNet, text="Abrir GUI web", command=self.open_web, state="disabled")
        self.openBtn.grid(row=0, column=1, padx=4)
        self.ipVar = tk.StringVar(value="LAN IP: --")
        ttk.Label(fNet, textvariable=self.ipVar, font=("Consolas", 11, "bold")).grid(
            row=1, column=0, columnspan=3, padx=6, sticky="w")
        self.netVar = tk.StringVar(value="")
        ttk.Label(fNet, textvariable=self.netVar, foreground="#666").grid(
            row=2, column=0, columnspan=3, padx=6, pady=(0, 6), sticky="w")

        # ── Credenciales ──────────────────────────────────────────────────
        fWifi = ttk.LabelFrame(root, text="3. Credenciales WiFi (STA)")
        fWifi.pack(fill="x", **pad)
        ttk.Label(fWifi, text="SSID:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
        self.ssidVar = tk.StringVar()
        ttk.Entry(fWifi, textvariable=self.ssidVar, width=32).grid(row=0, column=1, padx=4, sticky="w")
        ttk.Label(fWifi, text="Clave:").grid(row=1, column=0, padx=6, pady=4, sticky="e")
        self.passVar = tk.StringVar()
        self.passEntry = ttk.Entry(fWifi, textvariable=self.passVar, width=32, show="•")
        self.passEntry.grid(row=1, column=1, padx=4, sticky="w")
        self.showPass = tk.BooleanVar(value=False)
        ttk.Checkbutton(fWifi, text="Ver", variable=self.showPass,
                        command=self._toggle_pass).grid(row=1, column=2, padx=4, sticky="w")
        self.saveBtn = ttk.Button(fWifi, text="Guardar y reiniciar",
                                  command=self.save_wifi, state="disabled")
        self.saveBtn.grid(row=2, column=1, padx=4, pady=6, sticky="w")
        ttk.Label(fWifi, text="La clave debe tener ≥ 8 caracteres.",
                  foreground="#666").grid(row=3, column=0, columnspan=3, padx=6, sticky="w")

        # ── Log ───────────────────────────────────────────────────────────
        fLog = ttk.LabelFrame(root, text="Registro serial")
        fLog.pack(fill="both", expand=True, **pad)
        self.log = scrolledtext.ScrolledText(fLog, height=10, font=("Consolas", 9),
                                             state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True, padx=4, pady=4)

        self.refresh_ports()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(120, self._drain_log)

    # ── Utilidades de log (thread-safe vía cola) ──────────────────────────
    def _log(self, msg: str) -> None:
        self.log_q.put(msg)

    def _drain_log(self) -> None:
        try:
            while True:
                msg = self.log_q.get_nowait()
                self.log.configure(state="normal")
                self.log.insert("end", msg.rstrip() + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._drain_log)

    def _toggle_pass(self) -> None:
        self.passEntry.configure(show="" if self.showPass.get() else "•")

    # ── Puerto / conexión ─────────────────────────────────────────────────
    def refresh_ports(self) -> None:
        ports = [p.device for p in serial.tools.list_ports.comports()]
        self.portCombo["values"] = ports
        auto = find_esp32_port()
        if auto in ports:
            self.portVar.set(auto)
        elif ports:
            self.portVar.set(ports[0])
        else:
            self.portVar.set("")

    def toggle_connection(self) -> None:
        if self.ser and self.ser.is_open:
            self._disconnect()
        else:
            self._connect()

    def _connect(self) -> None:
        port = self.portVar.get().strip()
        if not port:
            self._log("[ERROR] No hay puerto seleccionado.")
            return
        try:
            self.ser = serial.Serial(port, BAUD, timeout=2)
            time.sleep(0.4)
            self._log(f"[OK] Conectado a {port} @ {BAUD}.")
            self.connLbl.configure(text=f"Conectado: {port}", foreground="#080")
            self.connBtn.configure(text="Desconectar")
            self._set_actions(True)
        except serial.SerialException as e:
            self.ser = None
            self._log(f"[ERROR] No se pudo abrir {port}: {e}")
            self._log("        ¿Está el monitor de PlatformIO u otra app usando el puerto?")

    def _disconnect(self) -> None:
        try:
            if self.ser:
                self.ser.close()
        except serial.SerialException:
            pass
        self.ser = None
        self.connLbl.configure(text="Desconectado", foreground="#b00")
        self.connBtn.configure(text="Conectar")
        self._set_actions(False)
        self._log("[OK] Desconectado.")

    def _set_actions(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.detectBtn.configure(state=state)
        self.saveBtn.configure(state=state)
        if not enabled:
            self.openBtn.configure(state="disabled")

    # ── Comunicación serial (patrón de serial_cmd.send_command) ───────────
    def _send(self, cmd: str, wait: float = RESPONSE_WAIT) -> str:
        """Envía un comando y devuelve la respuesta (filtra telemetría POS:)."""
        assert self.ser is not None
        self.ser.reset_input_buffer()
        self.ser.write((cmd.strip() + "\r\n").encode())
        time.sleep(wait)
        raw = self.ser.read(self.ser.in_waiting or 4096).decode(errors="replace")
        lines = [ln.strip() for ln in raw.splitlines()
                 if ln.strip() and not ln.strip().startswith("POS:")]
        return "\n".join(lines)

    def _run_bg(self, target) -> None:
        """Ejecuta I/O serial en un hilo para no congelar la GUI."""
        if self.busy:
            self._log("[..] Ocupado, esperá a que termine la operación anterior.")
            return
        self.busy = True
        self._set_actions(False)

        def wrapper():
            try:
                target()
            except serial.SerialException as e:
                self._log(f"[ERROR] Serial: {e}")
            except Exception as e:  # noqa: BLE001 — mostrar cualquier fallo en el log
                self._log(f"[ERROR] {e}")
            finally:
                self.busy = False
                # re-habilitar acciones desde el hilo de la GUI
                self.root.after(0, lambda: self._set_actions(bool(self.ser and self.ser.is_open)))

        threading.Thread(target=wrapper, daemon=True).start()

    # ── Acciones ──────────────────────────────────────────────────────────
    def detect_ip(self) -> None:
        self._run_bg(self._detect_ip_task)

    def _detect_ip_task(self) -> None:
        self._log(">> i")
        resp = self._send("i")
        self._log(resp or "(sin respuesta)")
        self._parse_net(resp)

    def _parse_net(self, resp: str) -> None:
        lan_ip = None
        ap_ip = None
        ssid = None
        for line in resp.splitlines():
            low = line.lower()
            m = IP_RE.search(line)
            if "lan ip" in low and m:
                lan_ip = m.group(1)
            elif "ap ip" in low and m:
                ap_ip = m.group(1)
            elif "lan ssid" in low:
                ssid = line.split(":", 1)[-1].strip()
        self.lan_ip = lan_ip
        if lan_ip:
            self.ipVar.set(f"LAN IP: {lan_ip}")
            self.root.after(0, lambda: self.openBtn.configure(state="normal"))
        else:
            self.ipVar.set("LAN IP: (no conectado a WiFi)")
            self.root.after(0, lambda: self.openBtn.configure(state="disabled"))
        extra = []
        if ssid:
            extra.append(f"SSID: {ssid}")
        if ap_ip:
            extra.append(f"AP IP: {ap_ip}")
        self.netVar.set("   ".join(extra))

    def open_web(self) -> None:
        if self.lan_ip:
            webbrowser.open(f"http://{self.lan_ip}/")

    def save_wifi(self) -> None:
        ssid = self.ssidVar.get().strip()
        passwd = self.passVar.get()
        if not ssid:
            self._log("[ERROR] Ingresá un SSID.")
            return
        if len(passwd) < 8:
            self._log("[ERROR] La clave debe tener al menos 8 caracteres.")
            return
        self._run_bg(lambda: self._save_wifi_task(ssid, passwd))

    def _save_wifi_task(self, ssid: str, passwd: str) -> None:
        # Orden importa: wifi_ssid actualiza staSsid; wifi_pass lo reutiliza.
        self._log(f">> wifi_ssid{ssid}")
        self._log(self._send("wifi_ssid" + ssid) or "(sin respuesta)")
        self._log(">> wifi_pass********")
        self._log(self._send("wifi_pass" + passwd) or "(sin respuesta)")
        self._log(">> reboot")
        self._log(self._send("reboot", wait=0.5) or "(reiniciando)")

        # El ESP re-enumera el USB al reiniciar: cerrar y reabrir el puerto.
        port = self.ser.port if self.ser else self.portVar.get()
        try:
            if self.ser:
                self.ser.close()
        except serial.SerialException:
            pass
        self.ser = None
        self._log(f"[..] Esperando reinicio y reconexión WiFi (~{REBOOT_WAIT:.0f}s)...")
        time.sleep(REBOOT_WAIT)

        try:
            self.ser = serial.Serial(port, BAUD, timeout=2)
            time.sleep(0.4)
            self.root.after(0, lambda: (
                self.connLbl.configure(text=f"Conectado: {port}", foreground="#080"),
                self.connBtn.configure(text="Desconectar"),
            ))
            self._log("[OK] Reconectado. Leyendo IP nueva...")
            resp = self._send("i")
            self._log(resp or "(sin respuesta)")
            self._parse_net(resp)
            if not self.lan_ip:
                self._log("[..] Aún sin IP LAN: puede tardar unos segundos más. "
                          "Reintentá 'Detectar IP'.")
        except serial.SerialException as e:
            self._log(f"[ERROR] No se pudo reabrir {port} tras el reinicio: {e}")
            self.root.after(0, lambda: self.connLbl.configure(
                text="Desconectado", foreground="#b00"))

    def on_close(self) -> None:
        self._disconnect()
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    QubeSerialTool(root)
    root.mainloop()


if __name__ == "__main__":
    main()
