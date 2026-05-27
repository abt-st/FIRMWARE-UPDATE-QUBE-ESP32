"""QUBE Signal Identifier — Interfaz gráfica de identificación de señales
Arquitectura: ESP32 + L298N + INA219

Uso:
    python -m qube_ui

Requiere:
    uv sync (instala todas las dependencias)
"""

from __future__ import annotations

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
from matplotlib.animation import FuncAnimation
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

from .client import ESP32Client, QubeState

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

    def push(self, state: QubeState) -> None:
        """Agregar un estado al buffer."""
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

    def snapshot(self) -> tuple:
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

    def reset(self) -> None:
        """Limpiar todos los buffers."""
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

    def export_csv(self, path: str) -> None:
        """Exportar datos a CSV."""
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

    def _build_control_panel(self, parent: tk.Frame) -> None:
        """Construir panel de control lateral."""
        panel = tk.Frame(parent, bg=COLORS["panel"], width=270)
        panel.pack(side="right", fill="y", padx=(0, 6), pady=6)
        panel.pack_propagate(False)

        def section(text: str) -> None:
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

        def row(parent_frame: tk.Frame, label: str, widget_cb: callable) -> None:
            f = tk.Frame(parent_frame, bg=COLORS["panel"])
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
                activebackground=COLORS["panel"],
                activeforeground=COLORS["text"],
                font=("Consolas", 9),
            ).pack(anchor="w")

        # ── Setpoint ──────────────────────────────────────────────────
        section("SETPOINT (°)")
        f_sp = tk.Frame(panel, bg=COLORS["panel"])
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
        f_pwm = tk.Frame(panel, bg=COLORS["panel"])
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

        # ── PID Gains ────────────────────────────────────────────────
        section("PID GAINS")
        self._kp_var = tk.StringVar(value="0.75")
        self._ki_var = tk.StringVar(value="0.15")
        self._kd_var = tk.StringVar(value="0.06")

        row(
            panel,
            "Kp:",
            lambda p: tk.Entry(
                p,
                textvariable=self._kp_var,
                width=8,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                insertbackground="white",
                font=("Consolas", 10),
            ).pack(side="left"),
        )
        row(
            panel,
            "Ki:",
            lambda p: tk.Entry(
                p,
                textvariable=self._ki_var,
                width=8,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                insertbackground="white",
                font=("Consolas", 10),
            ).pack(side="left"),
        )
        row(
            panel,
            "Kd:",
            lambda p: tk.Entry(
                p,
                textvariable=self._kd_var,
                width=8,
                bg=COLORS["accent"],
                fg=COLORS["text"],
                insertbackground="white",
                font=("Consolas", 10),
            ).pack(side="left"),
        )

        tk.Button(
            panel,
            text="Aplicar PID",
            command=self._send_pid,
            bg=COLORS["accent"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            relief="flat",
        ).pack(padx=8, pady=4, anchor="w")

        # ── Acciones ──────────────────────────────────────────────────
        section("ACCIONES")
        f_act = tk.Frame(panel, bg=COLORS["panel"])
        f_act.pack(fill="x", padx=8, pady=4)
        tk.Button(
            f_act,
            text="Zero",
            command=self._send_zero,
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

    def _make_status_label(self, parent: tk.Frame, text: str) -> tk.Label:
        """Crear una etiqueta de estado en el panel."""
        lbl = tk.Label(
            parent,
            text=text,
            bg=COLORS["panel"],
            fg=COLORS["text"],
            font=("Consolas", 9),
            anchor="w",
        )
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
        )

    def _update_charts(self, _frame: int) -> None:
        """Actualizar todas las gráficas con los datos más recientes."""
        t, pos, sp, err, pwm, ima, vb, _pmw = self.buffer.snapshot()

        if len(t) == 0:
            return

        # Actualizar posición
        self._ln_pos.set_data(t, pos)
        self._ln_sp.set_data(t, sp)
        self._ln_err.set_data(t, err)
        self._ax_pos.set_xlim(t[0], max(t[-1], 1.0))
        all_pos = np.concatenate([pos, sp])
        margin = max(np.std(all_pos) * 0.5, 5.0)
        self._ax_pos.set_ylim(np.min(all_pos) - margin, np.max(all_pos) + margin)

        # Actualizar PWM
        self._ln_pwm.set_data(t, pwm)
        self._ax_pwm.set_xlim(t[0], max(t[-1], 1.0))
        self._ax_pwm.set_ylim(-280, 280)

        # Actualizar potencia
        self._ln_ima.set_data(t, ima)
        self._ln_vb.set_data(t, vb)
        self._ax_pwr.set_xlim(t[0], max(t[-1], 1.0))
        if len(ima) > 0:
            self._ax_pwr.set_ylim(0, max(np.max(ima) * 1.2, 10))
        if len(vb) > 0:
            self._ax_v.set_ylim(min(np.min(vb) - 0.5, 10), max(np.max(vb) + 0.5, 14))

        # Actualizar panel de estado
        state = self._last_state
        mode_name = MODE_NAMES.get(state.mode, "???")
        self._lbl_mode.config(text=f"Modo:    {mode_name}")
        self._lbl_pos.config(text=f"Pos:     {state.position_deg:.2f}°")
        self._lbl_sp_disp.config(text=f"Setpnt:  {state.setpoint_deg:.2f}°")
        self._lbl_err.config(text=f"Error:   {state.error_deg:.2f}°")
        self._lbl_pwm_d.config(text=f"PWM:     {state.pwm}")
        self._lbl_ima_d.config(text=f"I:       {state.i_ma:.1f} mA")
        self._lbl_vb_d.config(text=f"V bus:   {state.v_bus:.2f} V")
        self._lbl_pw_d.config(text=f"Potencia:{state.p_mw:.1f} mW")

        self._canvas.draw_idle()

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
        """Enviar ganancias PID al ESP32."""
        try:
            kp = float(self._kp_var.get())
            ki = float(self._ki_var.get())
            kd = float(self._kd_var.get())
            self.client.set_pid(kp, ki, kd)
        except ValueError:
            messagebox.showerror("Error", "Los valores PID deben ser números")

    def _send_zero(self) -> None:
        """Enviar comando de zero position."""
        self.client.zero_here()

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
    #  Cierre de la aplicación                                             #
    # ------------------------------------------------------------------ #

    def _on_close(self) -> None:
        """Manejar cierre de la ventana."""
        if self.client._running:
            self.client.stop()
        self.destroy()


def main() -> None:
    """Punto de entrada principal."""
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
