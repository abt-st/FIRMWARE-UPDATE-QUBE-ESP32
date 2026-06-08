"""CLI para enviar comandos al ESP32 por serial.

Uso:
    uv run python src/firmware/serial_cmd.py wifi_info
    uv run python src/firmware/serial_cmd.py "kp5" "ki1" "m2"
    uv run python src/firmware/serial_cmd.py              # modo interactivo
"""

from __future__ import annotations

import sys
import time

import serial
import serial.tools.list_ports

PORT = "COM5"
BAUD = 115200
RESPONSE_WAIT = 1.0  # seconds to wait after each command


def find_esp32_port() -> str:
    """Find the first CP210x or CH340 serial port (ESP32)."""
    for p in serial.tools.list_ports.comports():
        desc = p.description.lower()
        if "cp210" in desc or "ch340" in desc or "silicon labs" in desc:
            return p.device
    return PORT


def send_command(ser: serial.Serial, cmd: str) -> str:
    """Send a command and collect the response, filtering telemetry lines."""
    ser.reset_input_buffer()
    ser.write((cmd.strip() + "\r\n").encode())
    time.sleep(RESPONSE_WAIT)
    raw = ser.read(ser.in_waiting or 4096).decode(errors="replace")
    lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Skip telemetry spam (POS:... lines)
        if stripped.startswith("POS:"):
            continue
        lines.append(stripped)
    return "\n".join(lines)


def interactive(ser: serial.Serial) -> None:
    """Interactive serial console — type commands, see filtered responses."""
    print(f"Connected to {ser.port} @ {ser.baudrate}")
    print("Type commands (e.g. wifi_info, m2, kp5). Ctrl+C to exit.\n")
    try:
        while True:
            cmd = input(">> ").strip()
            if not cmd:
                continue
            resp = send_command(ser, cmd)
            if resp:
                print(resp)
    except (KeyboardInterrupt, EOFError):
        print("\nBye.")


def main() -> None:
    port = find_esp32_port()
    args = sys.argv[1:]

    ser = serial.Serial(port, BAUD, timeout=2)
    time.sleep(0.5)

    try:
        if args:
            # Batch mode: send each arg as a command
            for cmd in args:
                print(f">> {cmd}")
                resp = send_command(ser, cmd)
                if resp:
                    print(resp)
        else:
            interactive(ser)
    finally:
        ser.close()


if __name__ == "__main__":
    main()
