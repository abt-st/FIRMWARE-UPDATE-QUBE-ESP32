"""
QUBE Signal Identifier — Interfaz gráfica de identificación de señales
Arquitectura: ESP32 + L298N + INA219

Uso:
    python app.py

Requiere:
    pip install -r requirements.txt
"""

import collections
import csv
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import matplotlib
import numpy as np

matplotlib.use("TkAgg")
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from esp32_client import ESP32Client, QubeState
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

# ──────────────────────────────────────────────────────────────────────────────
#  Constantes de diseño
# ──────────────────────────────────────────────────────────────────────────────

WINDOW_TITLE = "QUBE Signal Identifier — ESP32 + L298N + INA219"
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
MODE_NAMES = {0: "STOP", 1: "PWM Manual", 2: "PID Posición"}


# ──────────────────────────────────────────────────────────────────────────────
#  Buffer de datos en tiempo real (thread-safe)
# ──────────────────────────────────────────────────────────────────────────────


class SignalBuffer:
    """Mantiene los últimos N segundos de datos de cada señal."""

    def __init__(self, maxlen: int = BUFFER_SIZE):
        self._lock = threading.Lock()
        self.t = collections.deque(maxlen=maxlen)
        self.position = collections.deque(maxlen=maxlen)
        self.setpoint = collections.deque(maxlen=maxlen)
        self.error = collections.deque(maxlen=maxlen)
        self.pwm = collections.deque(maxlen=maxlen)
        self.current_ma = collections.deque(maxlen=maxlen)
        self.voltage_v = collections.deque(maxlen=maxlen)
        self.power_mw = collections.deque(maxlen=maxlen)
        self._t0: float = time.time()

    def push(self, state: QubeState):
        with self._lock:
            t = state.timestamp - self._t0
            self.t.append(t)
            self.position.append(state.position_deg)
            self.setpoint.append(state.setpoint_deg)
            self.error.append(state.error_deg)
            self.pwm.append(state.pwm)
            self.current_ma.append(state.i_ma)
            self.voltage_v.append(state.v_bus)
            self.power_mw.append(state.p_mw)

    def snapshot(self):
        """Retorna copias numpy de todos los buffers (thread-safe)."""
        with self._lock:
            t = np.array(self.t)
            pos = np.array(self.position)
            sp = np.array(self.setpoint)
            err = np.array(self.error)
            pwm = np.array(self.pwm)
            ima = np.array(self.current_ma)
            vb = np.array(self.voltage_v)
            pmw = np.array(self.power_mw)
        return t, pos, sp, err, pwm, ima, vb, pmw

    def reset(self):
        with self._lock:
            for q in (
                self.t,
                self.position,
                self.setpoint,
                self.error,
                self.pwm,
                self.current_ma,
                self.voltage_v,
                self.power_mw,
            ):
                q.clear()
            self._t0 = time.time()

    def export_csv(self, path: str):
        t, pos, sp, err, pwm, ima, vb, pmw = self.snapshot()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "t_s",
                    "position_deg",
                    "setpoint_deg",
                    "error_deg",
                    "pwm",
                    "current_ma",
                    "voltage_v",
                    "power_mw",
                ]
            )
            for row in zip(t, pos, sp, err, pwm, ima, vb, pmw, strict=True):
                writer.writerow([f"{v:.4f}" for v in row])


# ──────────────────────────────────────────────────────────────────────────────
#  Ventana principal
# ──────────────────────────────────────────────────────────────────────────────


class App(tk.Tk):
    def __init__(self):
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

        self._build_ui()
        self._start_animation()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ #
    #  Construcción de la UI                                               #
    # ------------------------------------------------------------------ #

    def _build_ui(self):
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

    def _build_charts(self, parent):
        chart_frame = tk.Frame(parent, bg=COLORS["bg"])
        chart_frame.pack(side="left", fill="both", expand=True)

        plt.style.use("dark_background")
        self._fig = plt.Figure(figsize=(9, 6), facecolor=COLORS["bg"])
        gs = gridspec.GridSpec(
            3,
            1,
            figure=self._fig,
            hspace=0.45,
            top=0.95,
            bottom=0.08,
            left=0.08,
            right=0.97,
        )

        # Subplot 1: Posición, Setpoint, Error
        self._ax_pos = self._fig.add_subplot(gs[0])
        self._ax_pos.set_facecolor(COLORS["accent"])
        self._ax_pos.set_title("Posición angular [°]", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pos.set_ylabel("grados", color=COLORS["text"], fontsize=8)
        self._ax_pos.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pos.grid(True, color="#2a2a4a", linewidth=0.5)
        (self._ln_pos,) = self._ax_pos.plot([], [], color=COLORS["pos"], lw=1.5, label="Posición")
        (self._ln_sp,) = self._ax_pos.plot([], [], color=COLORS["setpoint"], lw=1.2, ls="--", label="Setpoint")
        (self._ln_err,) = self._ax_pos.plot([], [], color=COLORS["error"], lw=1.0, label="Error")
        self._ax_pos.legend(
            loc="upper left",
            fontsize=7,
            facecolor=COLORS["panel"],
            labelcolor=COLORS["text"],
        )

        # Subplot 2: PWM
        self._ax_pwm = self._fig.add_subplot(gs[1])
        self._ax_pwm.set_facecolor(COLORS["accent"])
        self._ax_pwm.set_title("Señal PWM (-255 … +255)", color=COLORS["text"], fontsize=9, pad=4)
        self._ax_pwm.set_ylabel("duty", color=COLORS["text"], fontsize=8)
        self._ax_pwm.tick_params(colors=COLORS["text"], labelsize=7)
        self._ax_pwm.grid(True, color="#2a2a4a", linewidth=0.5)
        self._ax_pwm.axhline(0, color="#555", lw=0.8, ls=":")
        (self._ln_pwm,) = self._ax_pwm.plot([], [], color=COLORS["pwm"], lw=1.5)

        # Subplot 3: Corriente y Voltaje
        self._ax_pwr = self._fig.add_subplot(gs[2])
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
        self._ax_pwr.legend(
            loc="upper left",
            fontsize=7,
            facecolor=COLORS["panel"],
            labelcolor=COLORS["text"],
        )

        self._canvas = FigureCanvasTkAgg(self._fig, master=chart_frame)
        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    # ── Panel de control ──────────────────────────────────────────────── #

    def _build_control_panel(self, parent):
        panel = tk.Frame(parent, bg=COLORS["panel"], width=270)
        panel.pack(side="right", fill="y", padx=(0, 6), pady=6)
        panel.pack_propagate(False)

        def section(text):
            tk.Label(
                panel,
                text=text,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                font=("Consolas", 9, "bold"),
                pady=3,
                padx=6,
                anchor="w",
            ).pack(fill="x", pady=(8, 2))

        def row(parent, label, widget_cb):
            f = tk.Frame(parent, bg=COLORS["panel"])
            f.pack(fill="x", padx=8, pady=2)
            tk.Label(
                f,
                text=label,
                bg=COLORS["panel"],
                fg=COLORS["text"],
                font=("Consolas", 9),
                width=12,
                anchor="w",
            ).pack(side="left")
            widget_cb(f)

        # ── Estado actual ─────────────────────────────────────────────
        section("ESTADO ACTUAL")
        self._lbl_mode = self._make_status_label(panel, "Modo:    STOP")
        self._lbl_pos = self._make_status_label(panel, "Pos:     —°")
        self._lbl_sp_disp = self._make_status_label(panel, "Setpnt:  —°")
        self._lbl_err = self._make_status_label(panel, "Error:   —°")
        self._lbl_pwm_d = self._make_status_label(panel, "PWM:     —")
        self._lbl_ima_d = self._make_status_label(panel, "I:       — mA")
        self._lbl_vb_d = self._make_status_label(panel, "V bus:   — V")
        self._lbl_pw_d = self._make_status_label(panel, "Potencia:— mW")

        # ── Modo ──────────────────────────────────────────────────────
        section("MODO DE OPERACIÓN")
        f_mode = tk.Frame(panel, bg=COLORS["panel"])
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
                font=("Consolas", 9),
                activebackground=COLORS["panel"],
            ).pack(anchor="w")

        # ── PWM Manual ────────────────────────────────────────────────
        section("PWM MANUAL (modo 1)")
        self._pwm_scale = tk.Scale(
            panel,
            from_=-255,
            to=255,
            orient="horizontal",
            resolution=1,
            command=self._on_pwm_scale,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            troughcolor=COLORS["accent"],
            highlightthickness=0,
            font=("Consolas", 8),
        )
        self._pwm_scale.pack(fill="x", padx=8)

        # ── Setpoint PID ──────────────────────────────────────────────
        section("SETPOINT PID (modo 2)")
        f_sp = tk.Frame(panel, bg=COLORS["panel"])
        f_sp.pack(fill="x", padx=8, pady=2)
        self._sp_var = tk.StringVar(value="0")
        tk.Entry(
            f_sp,
            textvariable=self._sp_var,
            width=8,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 10),
            insertbackground="white",
        ).pack(side="left")
        tk.Label(f_sp, text="°", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 10)).pack(side="left", padx=2)
        tk.Button(
            f_sp,
            text="Enviar",
            command=self._send_setpoint,
            bg=COLORS["green"],
            fg="white",
            font=("Consolas", 9),
            relief="flat",
            padx=6,
        ).pack(side="left", padx=4)

        # Botones rápidos de setpoint
        f_quick = tk.Frame(panel, bg=COLORS["panel"])
        f_quick.pack(fill="x", padx=8, pady=2)
        for deg in (-90, -45, 0, 45, 90, 180):
            tk.Button(
                f_quick,
                text=f"{deg}°",
                command=lambda d=deg: self._quick_setpoint(d),
                bg=COLORS["accent"],
                fg=COLORS["text"],
                font=("Consolas", 8),
                relief="flat",
                padx=4,
            ).pack(side="left", padx=1)

        # ── Ganancias PID ─────────────────────────────────────────────
        section("GANANCIAS PID")
        self._kp_var = tk.StringVar(value="0.75")
        self._ki_var = tk.StringVar(value="0.0")
        self._kd_var = tk.StringVar(value="0.06")

        for label, var in (
            ("Kp:", self._kp_var),
            ("Ki:", self._ki_var),
            ("Kd:", self._kd_var),
        ):

            def _row(lbl=label, v=var):
                row(
                    panel,
                    lbl,
                    lambda f, _v=v: tk.Entry(
                        f,
                        textvariable=_v,
                        width=8,
                        bg=COLORS["accent"],
                        fg=COLORS["text"],
                        font=("Consolas", 9),
                        insertbackground="white",
                    ).pack(side="left"),
                )

            _row()

        tk.Button(
            panel,
            text="Aplicar PID",
            command=self._send_pid,
            bg=COLORS["yellow"],
            fg="#1a1a1a",
            font=("Consolas", 9, "bold"),
            relief="flat",
        ).pack(fill="x", padx=8, pady=4)

        # ── Configuración encoder ─────────────────────────────────────
        section("ENCODER")
        f_cpr = tk.Frame(panel, bg=COLORS["panel"])
        f_cpr.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_cpr,
            text="CPR:",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
        ).pack(side="left")
        self._cpr_var = tk.StringVar(value="2048")
        tk.Entry(
            f_cpr,
            textvariable=self._cpr_var,
            width=7,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            insertbackground="white",
        ).pack(side="left", padx=4)
        tk.Button(
            f_cpr,
            text="Set",
            command=self._send_cpr,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 8),
            relief="flat",
        ).pack(side="left")

        f_dir = tk.Frame(panel, bg=COLORS["panel"])
        f_dir.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_dir,
            text="Dir:",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
        ).pack(side="left")
        self._dir_var = tk.IntVar(value=1)
        tk.Radiobutton(
            f_dir,
            text="+1",
            variable=self._dir_var,
            value=1,
            command=self._send_dir,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            selectcolor=COLORS["accent"],
            font=("Consolas", 9),
            activebackground=COLORS["panel"],
        ).pack(side="left")
        tk.Radiobutton(
            f_dir,
            text="-1",
            variable=self._dir_var,
            value=-1,
            command=self._send_dir,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            selectcolor=COLORS["accent"],
            font=("Consolas", 9),
            activebackground=COLORS["panel"],
        ).pack(side="left")

        tk.Button(
            panel,
            text="⬜ Zero aquí",
            command=self._zero_here,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(fill="x", padx=8, pady=2)

        # ── Ventana de tiempo visible ──────────────────────────────────
        section("VENTANA DE TIEMPO")
        f_win = tk.Frame(panel, bg=COLORS["panel"])
        f_win.pack(fill="x", padx=8, pady=2)
        tk.Label(
            f_win,
            text="Mostrar:",
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
        ).pack(side="left")
        self._window_var = tk.StringVar(value="30")
        tk.Entry(
            f_win,
            textvariable=self._window_var,
            width=5,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            insertbackground="white",
        ).pack(side="left", padx=4)
        tk.Label(f_win, text="s", bg=COLORS["panel"], fg=COLORS["text"], font=("Consolas", 9)).pack(side="left")

        # Selector de señales visibles
        section("SEÑALES VISIBLES")
        self._show_pos = tk.BooleanVar(value=True)
        self._show_sp = tk.BooleanVar(value=True)
        self._show_err = tk.BooleanVar(value=True)
        self._show_ima = tk.BooleanVar(value=True)
        self._show_vb = tk.BooleanVar(value=True)
        for label, var, color in (
            ("Posición", self._show_pos, COLORS["pos"]),
            ("Setpoint", self._show_sp, COLORS["setpoint"]),
            ("Error", self._show_err, COLORS["error"]),
            ("Corriente", self._show_ima, COLORS["current"]),
            ("V bus", self._show_vb, COLORS["voltage"]),
        ):
            cb = tk.Checkbutton(
                panel,
                text=label,
                variable=var,
                bg=COLORS["panel"],
                fg=color,
                selectcolor=COLORS["accent"],
                font=("Consolas", 9),
                activebackground=COLORS["panel"],
            )
            cb.pack(anchor="w", padx=10)

    def _make_status_label(self, parent, text):
        lbl = tk.Label(
            parent,
            text=text,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            anchor="w",
            padx=10,
        )
        lbl.pack(fill="x")
        return lbl

    # ------------------------------------------------------------------ #
    #  Animación de gráficas                                              #
    # ------------------------------------------------------------------ #

    def _start_animation(self):
        self._anim = FuncAnimation(
            self._fig,
            self._animate,
            interval=UPDATE_MS,
            blit=False,
            cache_frame_data=False,
        )

    def _animate(self, _frame):
        t, pos, sp, err, pwm, ima, vb, _pmw = self.buffer.snapshot()
        if len(t) < 2:
            return

        try:
            win = float(self._window_var.get())
        except ValueError:
            win = 30.0

        t_max = t[-1]
        t_min = max(t[0], t_max - win)
        mask = t >= t_min
        t_w, pos_w, sp_w, err_w, pwm_w, ima_w, vb_w = (
            t[mask],
            pos[mask],
            sp[mask],
            err[mask],
            pwm[mask],
            ima[mask],
            vb[mask],
        )

        # ── Subplot 1: posición ───────────────────────────────────────
        self._ln_pos.set_data(t_w, pos_w if self._show_pos.get() else ([], []))
        self._ln_sp.set_data(t_w, sp_w if self._show_sp.get() else ([], []))
        self._ln_err.set_data(t_w, err_w if self._show_err.get() else ([], []))
        self._ax_pos.relim()
        self._ax_pos.autoscale_view()
        self._ax_pos.set_xlim(t_min, t_max + 0.5)

        # ── Subplot 2: PWM ────────────────────────────────────────────
        self._ln_pwm.set_data(t_w, pwm_w)
        self._ax_pwm.relim()
        self._ax_pwm.autoscale_view()
        self._ax_pwm.set_xlim(t_min, t_max + 0.5)
        self._ax_pwm.set_ylim(-270, 270)

        # ── Subplot 3: corriente / voltaje ────────────────────────────
        self._ln_ima.set_data(t_w, ima_w if self._show_ima.get() else ([], []))
        self._ln_vb.set_data(t_w, vb_w if self._show_vb.get() else ([], []))
        self._ax_pwr.relim()
        self._ax_pwr.autoscale_view()
        self._ax_v.relim()
        self._ax_v.autoscale_view()
        self._ax_pwr.set_xlim(t_min, t_max + 0.5)

    # ------------------------------------------------------------------ #
    #  Callbacks del cliente ESP32                                        #
    # ------------------------------------------------------------------ #

    def _on_state_update(self, state: QubeState):
        """Llamado desde el hilo de polling — solo actualiza datos."""
        self.buffer.push(state)
        self._last_state = state

        # Actualizar etiquetas de estado (se programa en el hilo de UI)
        self.after(0, self._refresh_labels, state)

    def _on_connection_error(self, msg: str):
        self._connected = False
        self.after(0, self._update_status_label, False, msg)

    # ------------------------------------------------------------------ #
    #  Actualización de etiquetas (hilo principal)                       #
    # ------------------------------------------------------------------ #

    def _refresh_labels(self, s: QubeState):
        self._connected = True
        self._update_status_label(True)
        self._lbl_latency.config(text=f"latencia: {self.client.last_latency_ms:.0f} ms")
        self._lbl_mode.config(text=f"Modo:    {MODE_NAMES.get(s.mode, s.mode)}")
        self._lbl_pos.config(text=f"Pos:     {s.position_deg:+.2f}°")
        self._lbl_sp_disp.config(text=f"Setpnt:  {s.setpoint_deg:+.2f}°")
        self._lbl_err.config(text=f"Error:   {s.error_deg:+.2f}°")
        self._lbl_pwm_d.config(text=f"PWM:     {s.pwm}")
        self._lbl_ima_d.config(text=f"I:       {s.i_ma:.1f} mA")
        self._lbl_vb_d.config(text=f"V bus:   {s.v_bus:.2f} V")
        self._lbl_pw_d.config(text=f"Potencia:{s.p_mw:.1f} mW")

    def _update_status_label(self, ok: bool, msg: str = ""):
        if ok:
            self._lbl_status.config(text="● Conectado", fg=COLORS["green"])
        else:
            txt = f"● {msg}" if msg else "● Sin conexión"
            self._lbl_status.config(text=txt, fg=COLORS["red"])

    # ------------------------------------------------------------------ #
    #  Acciones de control                                                 #
    # ------------------------------------------------------------------ #

    def _toggle_connection(self):
        if self.client._running:
            self.client.stop()
            self._btn_connect.config(text="⚡ Conectar", bg=COLORS["green"])
            self._update_status_label(False, "Desconectado")
        else:
            ip = self._ip_var.get().strip()
            try:
                poll = int(self._poll_var.get())
            except ValueError:
                poll = 100
            self.client.ip = ip
            self.client.poll_ms = poll
            self.client.start()
            self._btn_connect.config(text="✕ Desconectar", bg=COLORS["red"])
            self._update_status_label(False, "Conectando…")

    def _emergency_stop(self):
        self.client.stop_motor()
        self._mode_var.set(0)
        self._pwm_scale.set(0)

    def _send_mode(self):
        self.client.set_mode(self._mode_var.get())
        if self._mode_var.get() != 1:
            self._pwm_scale.set(0)

    def _on_pwm_scale(self, val):
        if self._mode_var.get() == 1:
            self.client.set_pwm(int(float(val)))

    def _send_setpoint(self):
        try:
            deg = float(self._sp_var.get())
        except ValueError:
            messagebox.showerror("Error", "Setpoint inválido")
            return
        self.client.set_setpoint(deg)

    def _quick_setpoint(self, deg: int):
        self._sp_var.set(str(deg))
        self.client.set_setpoint(float(deg))

    def _send_pid(self):
        try:
            kp = float(self._kp_var.get())
            ki = float(self._ki_var.get())
            kd = float(self._kd_var.get())
        except ValueError:
            messagebox.showerror("Error", "Valores PID inválidos")
            return
        self.client.set_pid(kp, ki, kd)

    def _send_cpr(self):
        try:
            cpr = float(self._cpr_var.get())
        except ValueError:
            messagebox.showerror("Error", "CPR inválido")
            return
        self.client.set_cpr(cpr)

    def _send_dir(self):
        self.client.set_encoder_dir(self._dir_var.get())

    def _zero_here(self):
        self.client.zero_here()

    def _clear_buffer(self):
        self.buffer.reset()

    def _export_csv(self):
        if len(self.buffer.t) == 0:
            messagebox.showinfo("Info", "No hay datos para exportar.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Todos", "*.*")],
            initialfile=f"qube_{time.strftime('%Y%m%d_%H%M%S')}.csv",
            title="Guardar datos",
        )
        if path:
            self.buffer.export_csv(path)
            messagebox.showinfo("Exportado", f"Datos guardados en:\n{path}")

    # ------------------------------------------------------------------ #
    #  Cierre                                                              #
    # ------------------------------------------------------------------ #

    def _on_close(self):
        self.client.stop_motor()
        self.client.stop()
        self.destroy()


# ──────────────────────────────────────────────────────────────────────────────
#  Punto de entrada
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = App()
    app.mainloop()
