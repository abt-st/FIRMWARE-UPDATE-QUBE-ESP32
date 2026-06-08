"""QUBE Signal Identifier — Interfaz gráfica de identificación de señales
Arquitectura: ESP32 + BTS7960 + INA219

Uso:
    python -m qube_ui

Requiere:
    uv sync (instala todas las dependencias)
"""

from __future__ import annotations

import collections
import csv
import re
import subprocess
import threading
import time
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext

import matplotlib
import numpy as np

matplotlib.use("TkAgg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.artist import Artist
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from .client import ESP32Client, QubeState

# ──────────────────────────────────────────────────────────────────────────────
#  Constantes de diseño
# ──────────────────────────────────────────────────────────────────────────────

WINDOW_TITLE = "QUBE Signal Identifier — ESP32 + BTS7960 + INA219"
BUFFER_SIZE = 600  # muestras en memoria (~60 s @ 10 Hz)
UPDATE_MS = 100  # refresco de la gráfica (ms)
COLORS = {
    "pos": "#00C8FF",  # azul cian  → posición real
    "setpoint": "#FFD700",  # dorado     → setpoint
    "error": "#FF6060",  # rojo       → error
    "pwm": "#7FFF7F",  # verde      → PWM
    "current": "#FF9F40",  # naranja    → corriente
    "voltage": "#BF7FFF",  # violeta    → voltaje bus
    "bg": "#1A1A2E",  # fondo oscuro
    "panel": "#16213E",
    "text": "#E0E0E0",
    "accent": "#0F3460",
    "green": "#4CAF50",
    "red": "#F44336",
    "yellow": "#FFC107",
}
MODE_NAMES = {0: "STOP", 1: "PWM Manual", 2: "PID Servo", 4: "LQR Invertido", 5: "Swing-up"}
FIRMWARE_DIR = Path(__file__).resolve().parent.parent.parent / "firmware"


# ──────────────────────────────────────────────────────────────────────────────
#  Flasher de firmware via PlatformIO
# ──────────────────────────────────────────────────────────────────────────────
def list_serial_ports() -> list[tuple[str, str]]:
    """Detectar puertos serie disponibles. Retorna lista de (device, description)."""
    try:
        from serial.tools.list_ports import comports

        return [(p.device, f"{p.device} — {p.description}") for p in comports()]
    except ImportError:
        return []


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[a-zA-Z]")


class FirmwareFlasher:
    """Ejecuta pio build/upload como subprocesso con output en tiempo real."""

    def __init__(self) -> None:
        self._proc: subprocess.Popen[str] | None = None

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def cancel(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()

    def flash(
        self,
        env: str,
        port: str,
        on_line: Callable[[str], None],
        on_done: Callable[[bool, str], None],
    ) -> None:
        """Flasheo completo: build + upload en thread background."""
        threading.Thread(target=self._flash_worker, args=(env, port, on_line, on_done), daemon=True).start()

    def _flash_worker(
        self,
        env: str,
        port: str,
        on_line: Callable[[str], None],
        on_done: Callable[[bool, str], None],
    ) -> None:
        if not FIRMWARE_DIR.is_dir():
            on_done(False, f"Directorio de firmware no encontrado:\n{FIRMWARE_DIR}")
            return
        for label, args in [
            ("BUILD", ["pio", "run", "-e", env]),
            ("UPLOAD", ["pio", "run", "-e", env, "--target", "upload", "--upload-port", port]),
        ]:
            on_line(f"\n{'═' * 50}\n  {label}: {' '.join(args)}\n{'═' * 50}\n")
            try:
                self._proc = subprocess.Popen(
                    args,
                    cwd=str(FIRMWARE_DIR),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    bufsize=1,
                )
            except FileNotFoundError:
                on_done(False, "PlatformIO no encontrado. Instala con:\npip install platformio")
                return
            except OSError as exc:
                on_done(False, f"Error ejecutando PlatformIO:\n{exc}")
                return
            assert self._proc.stdout is not None
            for raw_line in self._proc.stdout:
                clean = _ANSI_RE.sub("", raw_line.rstrip("\r\n"))
                if clean:
                    on_line(clean)
            self._proc.wait()
            if self._proc.returncode != 0:
                on_done(False, f"{label} falló (código {self._proc.returncode})")
                self._proc = None
                return
            self._proc = None
        on_done(True, "¡Firmware flasheado exitosamente!")


# ──────────────────────────────────────────────────────────────────────────────
#  Buffer de datos en tiempo real (thread-safe)
# ──────────────────────────────────────────────────────────────────────────────


class SignalBuffer:
    """Mantiene los últimos N segundos de datos de cada señal."""

    def __init__(self, maxlen: int = BUFFER_SIZE):
        self._lock = threading.Lock()
        self.t = collections.deque(maxlen=maxlen)
        # Servo
        self.position = collections.deque(maxlen=maxlen)
        self.setpoint = collections.deque(maxlen=maxlen)
        self.error = collections.deque(maxlen=maxlen)
        # Pendulum
        self.pend_position = collections.deque(maxlen=maxlen)
        self.pend_setpoint = collections.deque(maxlen=maxlen)
        self.pend_error = collections.deque(maxlen=maxlen)
        # Motor & power
        self.pwm = collections.deque(maxlen=maxlen)
        self.current_ma = collections.deque(maxlen=maxlen)
        self.voltage_v = collections.deque(maxlen=maxlen)
        self.power_mw = collections.deque(maxlen=maxlen)
        self._t0: float = time.time()

    def push(self, state: QubeState) -> None:
        """Agregar un estado al buffer."""
        with self._lock:
            t = state.timestamp - self._t0
            self.t.append(t)
            self.position.append(state.position_deg)
            self.setpoint.append(state.setpoint_deg)
            self.error.append(state.error_deg)
            self.pend_position.append(state.pend_position_deg)
            self.pend_setpoint.append(state.pend_setpoint_deg)
            self.pend_error.append(state.pend_error_deg)
            self.pwm.append(state.pwm)
            self.current_ma.append(state.i_ma)
            self.voltage_v.append(state.v_bus)
            self.power_mw.append(state.p_mw)

    def snapshot(self) -> tuple:
        """Retorna copias numpy de todos los buffers (thread-safe)."""
        with self._lock:
            t = np.array(self.t)
            pos = np.array(self.position)
            sp = np.array(self.setpoint)
            err = np.array(self.error)
            ppos = np.array(self.pend_position)
            psp = np.array(self.pend_setpoint)
            perr = np.array(self.pend_error)
            pwm = np.array(self.pwm)
            ima = np.array(self.current_ma)
            vb = np.array(self.voltage_v)
            pmw = np.array(self.power_mw)
        return t, pos, sp, err, ppos, psp, perr, pwm, ima, vb, pmw

    def reset(self) -> None:
        """Limpiar todos los buffers."""
        with self._lock:
            for q in (
                self.t,
                self.position,
                self.setpoint,
                self.error,
                self.pend_position,
                self.pend_setpoint,
                self.pend_error,
                self.pwm,
                self.current_ma,
                self.voltage_v,
                self.power_mw,
            ):
                q.clear()
            self._t0 = time.time()

    def export_csv(self, path: str) -> None:
        """Exportar datos a CSV."""
        t, pos, sp, err, ppos, psp, perr, pwm, ima, vb, pmw = self.snapshot()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "t_s",
                    "servo_position_deg",
                    "servo_setpoint_deg",
                    "servo_error_deg",
                    "pend_position_deg",
                    "pend_setpoint_deg",
                    "pend_error_deg",
                    "pwm",
                    "current_ma",
                    "voltage_v",
                    "power_mw",
                ]
            )
            for row in zip(t, pos, sp, err, ppos, psp, perr, pwm, ima, vb, pmw, strict=True):
                writer.writerow([f"{v:.4f}" for v in row])


# ──────────────────────────────────────────────────────────────────────────────
#  Ventana principal
# ──────────────────────────────────────────────────────────────────────────────


class App(tk.Tk):
    """Aplicación principal del QUBE Signal Identifier."""

    def __init__(self) -> None:
        super().__init__()
        self.title(WINDOW_TITLE)
        self.configure(bg=COLORS["bg"])
        self.minsize(1100, 700)

        self.buffer = SignalBuffer()
        self.client = ESP32Client()
        self.client.on_update = self._on_state_update
        self.client.on_error = self._on_connection_error

        self._last_state: QubeState = QubeState()
        self._connected = False
        self._recording = False
        self._flasher = FirmwareFlasher()

        self._build_ui()
        self._start_animation()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    #  Construcción de la UI                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self) -> None:
        # ── Barra superior (conexión + estado) ──────────────────────────
        top = tk.Frame(self, bg=COLORS["panel"], pady=6, padx=10)
        top.pack(fill="x", side="top")

        tk.Label(
            top,
            text="IP ESP32:",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 10),
        ).pack(side="left")
        self._ip_var = tk.StringVar(value=ESP32Client.DEFAULT_IP)
        tk.Entry(
            top,
            textvariable=self._ip_var,
            width=14,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(4, 10))

        tk.Label(
            top,
            text="Poll (ms):",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 10),
        ).pack(side="left")
        self._poll_var = tk.StringVar(value="100")
        tk.Entry(
            top,
            textvariable=self._poll_var,
            width=5,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(4, 10))

        self._btn_connect = tk.Button(
            top,
            text="⚡ Conectar",
            command=self._toggle_connection,
            bg=COLORS["green"],
            fg="white",
            font=("Consolas", 10, "bold"),
            relief="flat",
            padx=10,
        )
        self._btn_connect.pack(side="left", padx=(0, 8))

        self._lbl_status = tk.Label(
            top,
            text="● Sin conexión",
            bg=COLORS["panel"],
            fg=COLORS["red"],
            font=("Consolas", 10, "bold"),
        )
        self._lbl_status.pack(side="left", padx=8)

        self._lbl_latency = tk.Label(
            top,
            text="latencia: —",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
        )
        self._lbl_latency.pack(side="left", padx=8)

        # Botón STOP siempre visible
        tk.Button(
            top,
            text="■ STOP",
            command=self._emergency_stop,
            bg=COLORS["red"],
            fg="white",
            font=("Consolas", 11, "bold"),
            relief="flat",
            padx=12,
        ).pack(side="right", padx=4)

        tk.Button(
            top,
            text="⬛ Borrar buffer",
            command=self._clear_buffer,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
            padx=8,
        ).pack(side="right", padx=4)

        tk.Button(
            top,
            text="💾 Exportar CSV",
            command=self._export_csv,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
            padx=8,
        ).pack(side="right", padx=4)

        # ── Cuerpo principal (izquierda: gráficas | derecha: controles) ─
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True)

        self._build_charts(body)
        self._build_control_panel(body)

    # ── Panel de gráficas ─────────────────────────────────────────────── #

    def _build_charts(self, parent: tk.Frame) -> None:
        """Construir panel de gráficas matplotlib."""
        chart_frame = tk.Frame(parent, bg=COLORS["bg"])
        chart_frame.pack(side="left", fill="both", expand=True)

        plt.style.use("dark_background")
        self._fig = Figure(figsize=(9, 8), facecolor=COLORS["bg"])
        gs = gridspec.GridSpec(
            4,
            1,
            figure=self._fig,
            hspace=0.28,
            top=0.97,
            bottom=0.07,
            left=0.09,
            right=0.95,
        )

        # Subplot 1: Posición Servo
        self._ax_pos = self._fig.add_subplot(gs[0])
        self._ax_pos.set_facecolor(COLORS["accent"])
        self._ax_pos.set_title("Servo — Posición angular [°]", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pos.set_ylabel("grados", color=COLORS["text"], fontsize=8)
        self._ax_pos.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pos.grid(True, color="#2a2a4a", linewidth=0.5)
        (self._ln_pos,) = self._ax_pos.plot([], [], color=COLORS["pos"], lw=1.5, label="Servo")
        (self._ln_sp,) = self._ax_pos.plot([], [], color=COLORS["setpoint"], lw=1.2, ls="--", label="Setpoint")
        self._ax_pos.legend(loc="upper left", fontsize=7, facecolor=COLORS["panel"], labelcolor=COLORS["text"])

        # Subplot 2: Posición Péndulo
        self._ax_pend = self._fig.add_subplot(gs[1])
        self._ax_pend.set_facecolor(COLORS["accent"])
        self._ax_pend.set_title("Péndulo — Posición angular [°]", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pend.set_ylabel("grados", color=COLORS["text"], fontsize=8)
        self._ax_pend.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pend.grid(True, color="#2a2a4a", linewidth=0.5)
        (self._ln_ppos,) = self._ax_pend.plot([], [], color="#FF69B4", lw=1.5, label="Péndulo")
        (self._ln_psp,) = self._ax_pend.plot([], [], color=COLORS["setpoint"], lw=1.2, ls="--", label="Setpoint")
        self._ax_pend.legend(loc="upper left", fontsize=7, facecolor=COLORS["panel"], labelcolor=COLORS["text"])

        # Subplot 3: PWM
        self._ax_pwm = self._fig.add_subplot(gs[2])
        self._ax_pwm.set_facecolor(COLORS["accent"])
        self._ax_pwm.set_title("Señal PWM (-255 … +255)", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pwm.set_ylabel("duty", color=COLORS["text"], fontsize=8)
        self._ax_pwm.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pwm.grid(True, color="#2a2a4a", linewidth=0.5)
        self._ax_pwm.axhline(0, color="#555", lw=0.8, ls=":")
        (self._ln_pwm,) = self._ax_pwm.plot([], [], color=COLORS["pwm"], lw=1.5)

        # Subplot 4: Corriente y Voltaje
        self._ax_pwr = self._fig.add_subplot(gs[3])
        self._ax_pwr.set_facecolor(COLORS["accent"])
        self._ax_pwr.set_title("Potencia eléctrica (INA219)", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pwr.set_ylabel("mA", color=COLORS["text"], fontsize=8)
        self._ax_pwr.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pwr.grid(True, color="#2a2a4a", linewidth=0.5)
        self._ax_pwr.set_xlabel("tiempo (s)", color=COLORS["text"], fontsize=8)
        (self._ln_ima,) = self._ax_pwr.plot([], [], color=COLORS["current"], lw=1.5, label="Corriente (mA)")
        self._ax_v = self._ax_pwr.twinx()
        self._ax_v.set_facecolor(COLORS["accent"])
        self._ax_v.tick_params(colors=COLORS["voltage"], labelsize=7)
        self._ax_v.set_ylabel("V bus", color=COLORS["voltage"], fontsize=8)
        (self._ln_vb,) = self._ax_v.plot([], [], color=COLORS["voltage"], lw=1.2, ls="--", label="V bus")
        self._ax_pwr.legend(loc="upper left", fontsize=7, facecolor=COLORS["panel"], labelcolor=COLORS["text"])

        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    # ── Panel de control (scrollable) ────────────────────────────────── #

    def _build_control_panel(self, parent: tk.Frame) -> None:
        """Construir panel de control lateral con scrollbar."""
        panel = tk.Frame(parent, bg=COLORS["panel"], width=270)
        panel.pack(side="right", fill="y", padx=(0, 6), pady=6)
        panel.pack_propagate(False)

        # Scrollbar
        scrollbar = tk.Scrollbar(panel, orient="vertical", bg=COLORS["panel"])
        scrollbar.pack(side="right", fill="y")

        # Canvas scrolleable
        canvas = tk.Canvas(panel, bg=COLORS["panel"], highlightthickness=0, yscrollcommand=scrollbar.set, width=255)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=canvas.yview)

        # Inner frame dentro del canvas
        self._canvas_panel_inner = tk.Frame(canvas, bg=COLORS["panel"])
        inner = self._canvas_panel_inner
        inner_window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event: object) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(_event: tk.Event[tk.Canvas]) -> None:
            canvas.itemconfig(inner_window, width=_event.width)

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)

        # Mouse wheel scroll
        def _on_mousewheel(event: tk.Event[tk.Misc]) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def section(text: str) -> None:
            tk.Label(
                inner,
                text=text,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                font=("Consolas", 9, "bold"),
                pady=3,
                padx=6,
                anchor="w",
            ).pack(fill="x", pady=(8, 2))

        def row(label: str, widget_cb: Callable[[tk.Frame], None]) -> None:
            f = tk.Frame(inner, bg=COLORS["panel"])
            f.pack(fill="x", padx=8, pady=2)
            tk.Label(
                f, text=label, bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=12, anchor="w"
            ).pack(side="left")
            widget_cb(f)

        def entry_widget(parent_frame: tk.Frame, var: tk.StringVar) -> None:
            tk.Entry(
                parent_frame,
                textvariable=var,
                width=8,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                insertbackground="white",
                font=("Consolas", 10),
            ).pack(side="left")

        # ── Flasheo de firmware ────────────────────────────────────────
        section("⚡ FIRMWARE")
        f_env = tk.Frame(inner, bg=COLORS["panel"])
        f_env.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_env, text="Entorno:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=10, anchor="w"
        ).pack(side="left")
        self._flash_env_var = tk.StringVar(value="esp32dev")
        env_combo = tk.OptionMenu(f_env, self._flash_env_var, "esp32dev", "esp32dev_debug", "esp32dev_ota")
        env_combo.config(bg=COLORS["accent"], fg=COLORS["text"], font=("Consolas", 9), width=11, highlightthickness=0)
        env_combo["menu"].config(bg=COLORS["accent"], fg=COLORS["text"], font=("Consolas", 9))
        env_combo.pack(side="left", padx=(2, 0))
        f_port = tk.Frame(inner, bg=COLORS["panel"])
        f_port.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_port, text="Puerto:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=10, anchor="w"
        ).pack(side="left")
        self._flash_port_var = tk.StringVar()
        self._flash_port_menu = tk.OptionMenu(f_port, self._flash_port_var, "")
        self._flash_port_menu.config(
            bg=COLORS["accent"], fg=COLORS["text"], font=("Consolas", 9), width=14, highlightthickness=0
        )
        self._flash_port_menu["menu"].config(bg=COLORS["accent"], fg=COLORS["text"], font=("Consolas", 9))
        self._flash_port_menu.pack(side="left", padx=(2, 4))
        tk.Button(
            f_port,
            text="⟳",
            command=self._refresh_flash_ports,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 10, "bold"),
            relief="flat",
            width=2,
        ).pack(side="left")
        f_flash_btns = tk.Frame(inner, bg=COLORS["panel"])
        f_flash_btns.pack(fill="x", padx=8, pady=4)
        self._btn_flash = tk.Button(
            f_flash_btns,
            text="⚡ Flashear",
            command=self._start_flash,
            bg=COLORS["green"],
            fg="white",
            font=("Consolas", 10, "bold"),
            relief="flat",
            padx=10,
        )
        self._btn_flash.pack(side="left", padx=(0, 4))
        self._btn_flash_cancel = tk.Button(
            f_flash_btns,
            text="✕ Cancelar",
            command=self._cancel_flash,
            bg=COLORS["red"],
            fg="white",
            font=("Consolas", 9),
            relief="flat",
            padx=6,
            state="disabled",
        )
        self._btn_flash_cancel.pack(side="left")
        self._flash_log = scrolledtext.ScrolledText(
            inner,
            height=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 8),
            state="disabled",
            wrap="word",
            highlightthickness=0,
        )
        self._flash_log.pack(fill="x", padx=8, pady=(2, 6))
        self._refresh_flash_ports()
        # ── Estado actual ─────────────────────────────────────────────
        section("ESTADO ACTUAL")
        self._lbl_mode = self._make_status_label("Modo:    STOP")
        self._lbl_pos = self._make_status_label("Servo:   —°")
        self._lbl_sp_disp = self._make_status_label("SP servo:—°")
        self._lbl_ppos = self._make_status_label("Péndulo: —°")
        self._lbl_psp_disp = self._make_status_label("SP pénd: —°")
        self._lbl_pwm_d = self._make_status_label("PWM:     —")
        self._lbl_ima_d = self._make_status_label("I:       — mA")
        self._lbl_vb_d = self._make_status_label("V bus:   — V")
        self._lbl_gs_d = self._make_status_label("GainSch: off (—)")
        self._lbl_cpr_d = self._make_status_label("CPR servo: —")

        # ── Modo ──────────────────────────────────────────────────────
        section("MODO DE OPERACIÓN")
        f_mode = tk.Frame(inner, bg=COLORS["panel"])
        f_mode.pack(fill="x", padx=8, pady=4)
        self._mode_var = tk.IntVar(value=0)
        for val, label in MODE_NAMES.items():
            tk.Radiobutton(
                f_mode,
                text=label,
                variable=self._mode_var,
                value=val,
                command=self._send_mode,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                selectcolor=COLORS["accent"],
                activebackground=COLORS["panel"],
                activeforeground=COLORS["text"],
                font=("Consolas", 9),
            ).pack(anchor="w")

        # ── Setpoint Servo ────────────────────────────────────────────
        section("SETPOINT SERVO (°)")
        f_sp = tk.Frame(inner, bg=COLORS["panel"])
        f_sp.pack(fill="x", padx=8, pady=4)
        self._sp_var = tk.StringVar(value="0")
        tk.Entry(
            f_sp,
            textvariable=self._sp_var,
            width=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            f_sp,
            text="Enviar",
            command=self._send_setpoint,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left")


        # ── PWM Manual ────────────────────────────────────────────────
        section("PWM MANUAL (-255…255)")
        f_pwm = tk.Frame(inner, bg=COLORS["panel"])
        f_pwm.pack(fill="x", padx=8, pady=4)
        self._pwm_var = tk.StringVar(value="0")
        tk.Entry(
            f_pwm,
            textvariable=self._pwm_var,
            width=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            f_pwm,
            text="Enviar",
            command=self._send_pwm,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left")

        # ── PID Servo ────────────────────────────────────────────────
        section("PID SERVO")
        self._kp_var = tk.StringVar(value="3.0")
        self._ki_var = tk.StringVar(value="0.5")
        self._kd_var = tk.StringVar(value="0.15")
        row("Kp:", lambda p: entry_widget(p, self._kp_var))
        row("Ki:", lambda p: entry_widget(p, self._ki_var))
        row("Kd:", lambda p: entry_widget(p, self._kd_var))
        tk.Button(
            inner,
            text="Aplicar PID Servo",
            command=self._send_pid,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")


        # ── LQR Gains ────────────────────────────────────────────────
        section("LQR GANANCIAS")
        self._lqr1_var = tk.StringVar(value="1.0")
        self._lqr2_var = tk.StringVar(value="25.0")
        self._lqr3_var = tk.StringVar(value="0.5")
        self._lqr4_var = tk.StringVar(value="3.0")
        row("K1 (th):", lambda p: entry_widget(p, self._lqr1_var))
        row("K2 (al):", lambda p: entry_widget(p, self._lqr2_var))
        row("K3 (th'):", lambda p: entry_widget(p, self._lqr3_var))
        row("K4 (al'):", lambda p: entry_widget(p, self._lqr4_var))
        tk.Button(
            inner,
            text="Aplicar LQR",
            command=self._send_lqr,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")

        # ── Swing-up Parameters
        section("SWING-UP")
        self._ke_var = tk.StringVar(value="0.5")
        self._bt_var = tk.StringVar(value="20.0")
        row("ke (gain):", lambda p: entry_widget(p, self._ke_var))
        row("threshold:", lambda p: entry_widget(p, self._bt_var))
        tk.Button(
            inner,
            text="Aplicar Swing-up",
            command=self._send_swing_up,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")

        # ── Calibración (CPR + dir encoder) ─────────────────────────
        section("CALIBRACIÓN (CPR / DIR)")
        self._cpr_s_var = tk.StringVar(value="2048")
        self._cpr_p_var = tk.StringVar(value="2048")
        self._ed_s_var = tk.IntVar(value=1)
        self._ed_p_var = tk.IntVar(value=1)
        row("CPR servo:", lambda p: entry_widget(p, self._cpr_s_var))
        row("CPR pénd:", lambda p: entry_widget(p, self._cpr_p_var))
        f_ed = tk.Frame(inner, bg=COLORS["panel"])
        f_ed.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_ed, text="dir servo:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=10, anchor="w"
        ).pack(side="left")
        for val, label in ((1, "+1"), (-1, "-1")):
            tk.Radiobutton(
                f_ed,
                text=label,
                variable=self._ed_s_var,
                value=val,
                command=self._send_encoder_dir,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                selectcolor=COLORS["accent"],
                activebackground=COLORS["panel"],
                activeforeground=COLORS["text"],
                font=("Consolas", 9),
            ).pack(side="left")
        f_edp = tk.Frame(inner, bg=COLORS["panel"])
        f_edp.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_edp, text="dir pénd:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=10, anchor="w"
        ).pack(side="left")
        for val, label in ((1, "+1"), (-1, "-1")):
            tk.Radiobutton(
                f_edp,
                text=label,
                variable=self._ed_p_var,
                value=val,
                command=self._send_pendulum_encoder_dir,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                selectcolor=COLORS["accent"],
                activebackground=COLORS["panel"],
                activeforeground=COLORS["text"],
                font=("Consolas", 9),
            ).pack(side="left")
        tk.Button(
            inner,
            text="Aplicar Calibración",
            command=self._send_calibration,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")

        # ── Gain Scheduling ────────────────────────────────────────
        section("GAIN SCHEDULING (PID SERVO)")
        self._gs_var = tk.BooleanVar(value=False)
        f_gs = tk.Frame(inner, bg=COLORS["panel"])
        f_gs.pack(fill="x", padx=8, pady=2)
        tk.Checkbutton(
            f_gs,
            text="Activar dual-mode",
            variable=self._gs_var,
            command=self._send_gain_scheduling,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            selectcolor=COLORS["accent"],
            activebackground=COLORS["panel"],
            activeforeground=COLORS["text"],
            font=("Consolas", 9),
        ).pack(side="left")
        section("  → Modo fino (|err| ≤ 10°)")
        self._kpf_var = tk.StringVar(value="2.0")
        self._kif_var = tk.StringVar(value="0.8")
        self._kdf_var = tk.StringVar(value="0.2")
        row("Kp:", lambda p: entry_widget(p, self._kpf_var))
        row("Ki:", lambda p: entry_widget(p, self._kif_var))
        row("Kd:", lambda p: entry_widget(p, self._kdf_var))
        section("  → Modo grueso (|err| > 10°)")
        self._kpc_var = tk.StringVar(value="4.0")
        self._kic_var = tk.StringVar(value="0.2")
        self._kdc_var = tk.StringVar(value="0.1")
        row("Kp:", lambda p: entry_widget(p, self._kpc_var))
        row("Ki:", lambda p: entry_widget(p, self._kic_var))
        row("Kd:", lambda p: entry_widget(p, self._kdc_var))
        tk.Button(
            inner,
            text="Aplicar Gains Fino/Grue.",
            command=self._send_gain_gains,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")

        # ── WiFi STA ──────────────────────────────────────────────
        section("WIFI STA")
        f_ssid = tk.Frame(inner, bg=COLORS["panel"])
        f_ssid.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_ssid, text="SSID:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=8, anchor="w"
        ).pack(side="left")
        self._ssid_var = tk.StringVar()
        tk.Entry(
            f_ssid,
            textvariable=self._ssid_var,
            width=18,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 9),
        ).pack(side="left", padx=(2, 4))
        f_pwd = tk.Frame(inner, bg=COLORS["panel"])
        f_pwd.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_pwd, text="Pass:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=8, anchor="w"
        ).pack(side="left")
        self._wifi_pwd_var = tk.StringVar()
        tk.Entry(
            f_pwd,
            textvariable=self._wifi_pwd_var,
            width=18,
            show="•",
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 9),
        ).pack(side="left", padx=(2, 4))
        f_wifi = tk.Frame(inner, bg=COLORS["panel"])
        f_wifi.pack(fill="x", padx=8, pady=4)
        tk.Button(
            f_wifi,
            text="Aplicar WiFi",
            command=self._send_wifi,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left", padx=2)
        tk.Button(
            f_wifi,
            text="Reconectar",
            command=self._send_wifi_reconnect,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left", padx=2)

        # ── Offset / Calibración ──────────────────────────────────────
        section("OFFSET (°)")
        f_ofs = tk.Frame(inner, bg=COLORS["panel"])
        f_ofs.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_ofs, text="servo:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=8, anchor="w"
        ).pack(side="left")
        self._ofs_var = tk.StringVar(value="0")
        tk.Entry(
            f_ofs,
            textvariable=self._ofs_var,
            width=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            f_ofs,
            text="Set",
            command=self._send_offset,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left")
        f_op = tk.Frame(inner, bg=COLORS["panel"])
        f_op.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_op, text="péndulo:", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), width=8, anchor="w"
        ).pack(side="left")
        self._op_var = tk.StringVar(value="0")
        tk.Entry(
            f_op,
            textvariable=self._op_var,
            width=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            insertbackground="white",
            font=("Consolas", 10),
        ).pack(side="left", padx=(0, 4))
        tk.Button(
            f_op,
            text="Set",
            command=self._send_pendulum_offset,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left")

        # ── Acciones ──────────────────────────────────────────────────
        section("ACCIONES")
        f_act = tk.Frame(inner, bg=COLORS["panel"])
        f_act.pack(fill="x", padx=8, pady=4)
        tk.Button(
            f_act,
            text="Zero Servo",
            command=self._send_zero,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left", padx=2)
        tk.Button(
            f_act,
            text="Zero Pénd",
            command=self._send_zero_pendulum,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left", padx=2)
        tk.Button(
            f_act,
            text="Reset",
            command=self._send_reset,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(side="left", padx=2)

    def _make_status_label(self, text: str) -> tk.Label:
        """Crear una etiqueta de estado en el panel (usa inner frame via winfo_toplevel)."""
        # Encuentra el canvas inner frame via el widget padre
        parent = self._canvas_panel_inner
        lbl = tk.Label(parent, text=text, bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9), anchor="w")
        lbl.pack(fill="x", padx=8, pady=1)
        return lbl

    # ------------------------------------------------------------------ #
    #  Conexión / Desconexión                                              #
    # ------------------------------------------------------------------ #

    def _toggle_connection(self) -> None:
        """Alternar conexión con el ESP32."""
        if self.client._running:
            self.client.stop()
            self._btn_connect.config(text="⚡ Conectar", bg=COLORS["green"])
            self._lbl_status.config(text="● Sin conexión", fg=COLORS["red"])
            self._connected = False
        else:
            self.client.ip = self._ip_var.get()
            try:
                self.client.poll_ms = int(self._poll_var.get())
            except ValueError:
                self.client.poll_ms = 100
            self.client.start()
            self._btn_connect.config(text="⏹ Desconectar", bg=COLORS["red"])
            self._lbl_status.config(text="● Conectando...", fg=COLORS["yellow"])
            self._connected = True

    def _on_state_update(self, state: QubeState) -> None:
        """Callback cuando llega un nuevo estado del ESP32."""
        self._last_state = state
        self.buffer.push(state)
        self._lbl_status.config(text="● Conectado", fg=COLORS["green"])
        self._lbl_latency.config(text=f"latencia: {self.client.last_latency_ms:.0f} ms")

    def _on_connection_error(self, msg: str) -> None:
        """Callback cuando hay error de conexión."""
        self._lbl_status.config(text=f"● {msg}", fg=COLORS["red"])

    # ------------------------------------------------------------------ #
    #  Animación de gráficas                                               #
    # ------------------------------------------------------------------ #

    def _start_animation(self) -> None:
        """Iniciar la animación de las gráficas."""
        self._anim = FuncAnimation(
            self._fig,
            self._update_charts,
            interval=UPDATE_MS,
            blit=False,
            cache_frame_data=False,
        )

    def _update_charts(self, _frame: int) -> list[Artist]:
        """Actualizar todas las gráficas con los datos más recientes."""
        t, pos, sp, _err, ppos, psp, _perr, pwm, ima, vb, _pmw = self.buffer.snapshot()

        if len(t) == 0:
            return []

        # Subplot 1: Servo
        self._ln_pos.set_data(t, pos)
        self._ln_sp.set_data(t, sp)
        self._ax_pos.set_xlim(t[0], max(t[-1], 1.0))
        all_pos = np.concatenate([pos, sp])
        pos_range = np.ptp(all_pos)
        pos_margin = max(pos_range * 0.1, 5.0)
        self._ax_pos.set_ylim(np.min(all_pos) - pos_margin, np.max(all_pos) + pos_margin)
        # Subplot 2: Péndulo
        self._ln_ppos.set_data(t, ppos)
        self._ln_psp.set_data(t, psp)
        self._ax_pend.set_xlim(t[0], max(t[-1], 1.0))
        if len(ppos) > 0:
            all_pend = np.concatenate([ppos, psp])
            pend_range = np.ptp(all_pend)
            pend_margin = max(pend_range * 0.1, 5.0)
            y_min = max(np.min(all_pend) - pend_margin, -200.0)
            y_max = min(np.max(all_pend) + pend_margin, 200.0)
            self._ax_pend.set_ylim(y_min, y_max)

        # Subplot 3: PWM
        self._ln_pwm.set_data(t, pwm)
        self._ax_pwm.set_xlim(t[0], max(t[-1], 1.0))
        self._ax_pwm.set_ylim(-280, 280)

        # Subplot 4: Potencia
        self._ln_ima.set_data(t, ima)
        self._ln_vb.set_data(t, vb)
        self._ax_pwr.set_xlim(t[0], max(t[-1], 1.0))
        if len(ima) > 0:
            self._ax_pwr.set_ylim(0, max(np.max(ima) * 1.2, 10))
        if len(vb) > 0:
            self._ax_v.set_ylim(min(np.min(vb) - 0.5, 10), max(np.max(vb) + 0.5, 14))

        # Panel de estado
        state = self._last_state
        mode_name = MODE_NAMES.get(state.mode, "???")
        self._lbl_mode.config(text=f"Modo:    {mode_name}")
        self._lbl_pos.config(text=f"Servo:   {state.position_deg:.2f}°")
        self._lbl_sp_disp.config(text=f"SP servo:{state.setpoint_deg:.2f}°")
        self._lbl_ppos.config(text=f"Péndulo: {state.pend_position_deg:.2f}°")
        self._lbl_psp_disp.config(text=f"SP pénd: {state.pend_setpoint_deg:.2f}°")
        self._lbl_pwm_d.config(text=f"PWM:     {state.pwm}")
        self._lbl_ima_d.config(text=f"I:       {state.i_ma:.1f} mA")
        self._lbl_vb_d.config(text=f"V bus:   {state.v_bus:.2f} V")
        gs_state = "on" if state.gain_scheduling else "off"
        gs_mode = "fino" if state.gain_mode == 0 else "grueso"
        self._lbl_gs_d.config(text=f"GainSch: {gs_state} ({gs_mode})")
        self._lbl_cpr_d.config(text=f"CPR servo: {state.counts_per_rev:.0f}")

        self._canvas.draw_idle()
        return []

    # ------------------------------------------------------------------ #
    #  Envío de comandos                                                   #
    # ------------------------------------------------------------------ #

    def _send_mode(self) -> None:
        """Enviar modo de operación al ESP32."""
        self.client.set_mode(self._mode_var.get())

    def _send_setpoint(self) -> None:
        """Enviar setpoint al ESP32."""
        try:
            val = float(self._sp_var.get())
            self.client.set_setpoint(val)
        except ValueError:
            messagebox.showerror("Error", "Setpoint debe ser un número")

    def _send_pwm(self) -> None:
        """Enviar PWM manual al ESP32."""
        try:
            val = int(self._pwm_var.get())
            self.client.set_pwm(val)
        except ValueError:
            messagebox.showerror("Error", "PWM debe ser un entero")

    def _send_pid(self) -> None:
        """Enviar ganancias PID servo al ESP32."""
        try:
            kp = float(self._kp_var.get())
            ki = float(self._ki_var.get())
            kd = float(self._kd_var.get())
            self.client.set_pid(kp, ki, kd)
        except ValueError:
            messagebox.showerror("Error", "Los valores PID deben ser números")


    def _send_lqr(self) -> None:
        """Enviar ganancias LQR al ESP32."""
        try:
            k1 = float(self._lqr1_var.get())
            k2 = float(self._lqr2_var.get())
            k3 = float(self._lqr3_var.get())
            k4 = float(self._lqr4_var.get())
            self.client.set_lqr_gains(k1, k2, k3, k4)
        except ValueError:
            messagebox.showerror("Error", "Los valores LQR deben ser números")

    def _send_swing_up(self) -> None:
        """Enviar parámetros de swing-up al ESP32."""
        try:
            ke = float(self._ke_var.get())
            bt = float(self._bt_var.get())
            self.client.set_swing_up_params(ke, bt)
        except ValueError:
            messagebox.showerror("Error", "Los valores deben ser números")

    def _send_zero(self) -> None:
        """Enviar comando de zero servo."""
        self.client.zero_here()

    def _send_zero_pendulum(self) -> None:
        """Enviar comando de zero péndulo."""
        self.client.zero_pendulum()

    def _send_offset(self) -> None:
        """Enviar offset manual al ESP32."""
        try:
            val = float(self._ofs_var.get())
            self.client.send_cmd(o=round(val, 2))
        except ValueError:
            messagebox.showerror("Error", "Offset debe ser un numero")

    def _send_pendulum_offset(self) -> None:
        """Enviar offset manual del péndulo al ESP32."""
        try:
            val = float(self._op_var.get())
            self.client.set_pendulum_offset(val)
        except ValueError:
            messagebox.showerror("Error", "Offset debe ser un numero")

    def _send_encoder_dir(self) -> None:
        """Enviar dirección de encoder servo al ESP32."""
        self.client.set_encoder_dir(self._ed_s_var.get())

    def _send_pendulum_encoder_dir(self) -> None:
        """Enviar dirección de encoder péndulo al ESP32."""
        self.client.set_pendulum_encoder_dir(self._ed_p_var.get())

    def _send_calibration(self) -> None:
        """Aplicar CPR servo y péndulo, y direcciones de encoder."""
        try:
            cpr_s = float(self._cpr_s_var.get())
            cpr_p = float(self._cpr_p_var.get())
            self.client.set_cpr(cpr_s)
            self.client.set_pendulum_cpr(cpr_p)
            self.client.set_encoder_dir(self._ed_s_var.get())
            self.client.set_pendulum_encoder_dir(self._ed_p_var.get())
        except ValueError:
            messagebox.showerror("Error", "CPR debe ser un número")

    def _send_gain_scheduling(self) -> None:
        """Activar/desactivar gain scheduling dual-mode en PID servo."""
        self.client.set_gain_scheduling(self._gs_var.get())

    def _send_gain_gains(self) -> None:
        """Enviar ganancias fino/grueso al firmware."""
        try:
            kp_f = float(self._kpf_var.get())
            ki_f = float(self._kif_var.get())
            kd_f = float(self._kdf_var.get())
            kp_c = float(self._kpc_var.get())
            ki_c = float(self._kic_var.get())
            kd_c = float(self._kdc_var.get())
            self.client.set_servo_pid_fine(kp_f, ki_f, kd_f)
            self.client.set_servo_pid_coarse(kp_c, ki_c, kd_c)
        except ValueError:
            messagebox.showerror("Error", "Las ganancias deben ser números")

    def _send_wifi(self) -> None:
        """Aplicar configuración WiFi STA al ESP32."""
        ssid = self._ssid_var.get().strip()
        password = self._wifi_pwd_var.get()
        if not ssid:
            messagebox.showerror("Error", "SSID no puede estar vacío")
            return
        if password and len(password) < 8:
            messagebox.showerror("Error", "Password debe tener al menos 8 caracteres")
            return
        if not self.client.set_wifi_ssid(ssid):
            messagebox.showerror("Error", "SSID inválido (1-32 caracteres)")
            return
        if password and not self.client.set_wifi_password(password):
            messagebox.showerror("Error", "Password inválido (>= 8 caracteres)")
            return
        messagebox.showinfo("WiFi", f"SSID '{ssid}' aplicado. Use 'Reconectar' para activar.")

    def _send_wifi_reconnect(self) -> None:
        """Forzar reconexión WiFi en el ESP32."""
        if not self.client.wifi_reconnect():
            messagebox.showerror("Error", "No se pudo enviar comando de reconexión")

    def _send_reset(self) -> None:
        """Enviar comando de reset."""
        self.client.send_cmd(r=1)

    def _emergency_stop(self) -> None:
        """Paro de emergencia."""
        self.client.stop_motor()

    def _clear_buffer(self) -> None:
        """Limpiar buffer de datos."""
        self.buffer.reset()

    def _export_csv(self) -> None:
        """Exportar datos a CSV."""
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
            initialfile=f"qube_{time.strftime('%Y-%m-%dT%H_%M_%S')}.csv",
        )
        if path:
            self.buffer.export_csv(path)
            messagebox.showinfo("Exportado", f"Datos guardados en:\n{path}")

    # ------------------------------------------------------------------ #
    #  Flasheo de firmware                                                  #
    # ------------------------------------------------------------------ #
    def _refresh_flash_ports(self) -> None:
        """Escanear puertos serie y actualizar el menú desplegable."""
        ports = list_serial_ports()
        menu = self._flash_port_menu["menu"]
        menu.delete(0, "end")
        for device, desc in ports:
            menu.add_command(label=desc, command=lambda d=device: self._flash_port_var.set(d))
        if ports:
            self._flash_port_var.set(ports[0][0])
        else:
            self._flash_port_var.set("")

    def _flash_log_line(self, line: str) -> None:
        """Callback de línea de output del flasheo (ejecutado en thread)."""
        self.after(0, self._flash_log_append, line)

    def _flash_log_append(self, line: str) -> None:
        """Insertar línea en el log de flasheo (debe correr en main thread)."""
        self._flash_log.config(state="normal")
        self._flash_log.insert("end", line + "\n")
        self._flash_log.see("end")
        self._flash_log.config(state="disabled")

    def _flash_done(self, success: bool, msg: str) -> None:
        """Callback de fin de flasheo (ejecutado en thread)."""
        self.after(0, self._flash_finished, success, msg)

    def _flash_finished(self, success: bool, msg: str) -> None:
        """Procesar resultado del flasheo en el thread principal."""
        self._btn_flash.config(state="normal")
        self._btn_flash_cancel.config(state="disabled")
        self._flash_log_append(msg)
        if success:
            messagebox.showinfo("Flasheo", msg)
        else:
            messagebox.showerror("Flasheo", msg)

    def _start_flash(self) -> None:
        """Iniciar proceso de flasheo."""
        env = self._flash_env_var.get()
        port = self._flash_port_var.get()
        if not port:
            messagebox.showwarning("Flasheo", "Seleccioná un puerto serie. Conectá el ESP32 y presioná ⟳.")
            return
        self._flash_log.config(state="normal")
        self._flash_log.delete("1.0", "end")
        self._flash_log.config(state="disabled")
        self._btn_flash.config(state="disabled")
        self._btn_flash_cancel.config(state="normal")
        self._flasher.flash(env, port, self._flash_log_line, self._flash_done)

    def _cancel_flash(self) -> None:
        """Cancelar flasheo en progreso."""
        self._flasher.cancel()

    # ------------------------------------------------------------------ #
    #  Cierre de la aplicación                                             #
    # ------------------------------------------------------------------ #

    def _on_close(self) -> None:
        """Manejar cierre de la ventana."""
        try:
            if self._flasher.running:
                self._flasher.cancel()
        except Exception:
            pass
        try:
            if self.client._running:
                self.client.stop()
        except Exception:
            pass
        self.destroy()


def main() -> None:
    """Punto de entrada principal."""
    try:
        app = App()
        app.mainloop()
    except KeyboardInterrupt:
        pass
    except Exception:
        import traceback

        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
