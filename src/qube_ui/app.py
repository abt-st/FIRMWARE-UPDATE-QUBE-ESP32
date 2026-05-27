"""QUBE Signal Identifier — Tkinter GUI for QUBE Servo ESP32."""

from __future__ import annotations

import tkinter as tk


def main() -> None:
    """Launch the QUBE UI application."""
    root = tk.Tk()
    root.title("QUBE Signal Identifier — ESP32")
    root.geometry("1200x700")
    root.configure(bg="#0d0d1a")

    # Top bar
    topbar = tk.Frame(root, bg="#13132b", height=40)
    topbar.pack(fill=tk.X, side=tk.TOP)

    tk.Label(topbar, text="IP ESP32:", fg="#8888aa", bg="#13132b",
             font=("Consolas", 10)).pack(side=tk.LEFT, padx=(10, 2))
    ip_entry = tk.Entry(topbar, width=15, bg="#0f3460", fg="#d8d8f0",
                        insertbackground="#d8d8f0", relief=tk.FLAT,
                        font=("Consolas", 10))
    ip_entry.insert(0, "192.168.4.1")
    ip_entry.pack(side=tk.LEFT, padx=2)

    # Main content area
    main_frame = tk.Frame(root, bg="#0d0d1a")
    main_frame.pack(fill=tk.BOTH, expand=True)

    # Placeholder label for charts
    placeholder = tk.Label(
        main_frame,
        text="QUBE Signal Identifier\n\n"
             "Conecta al ESP32 en 192.168.4.1\n\n"
             "Modos: STOP | PWM Manual | PID Posición",
        fg="#8888aa",
        bg="#0d0d1a",
        font=("Consolas", 14),
        justify=tk.CENTER,
    )
    placeholder.pack(expand=True)

    # Status bar
    status_bar = tk.Label(
        root,
        text="⏹ STOP — Sin conexión",
        bg="#13132b",
        fg="#f44336",
        font=("Consolas", 9),
        anchor=tk.W,
    )
    status_bar.pack(fill=tk.X, side=tk.BOTTOM)

    root.mainloop()


if __name__ == "__main__":
    main()
