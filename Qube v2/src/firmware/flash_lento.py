"""flash_lento.py — sube el firmware a /update en bloques chicos y con pausa.

Existe porque `flash.py` dejó de pasar contra esta placa: el POST completo se
atasca siempre alrededor de los 128 kB y el servidor deja de leer ("Empty reply
from server", o read timeout del lado de requests). Medido el 2026-08-21.

La razón de fondo es la misma de [P28]: el lazo de control de 500 Hz y la tarea
de AsyncTCP se pelean, y un POST de 1 MB a toda velocidad se lleva la peor parte.
Mandando en bloques de `chunk` bytes con una pausa de `pausa` segundos entre
medio, la placa alcanza a escribir flash y a atender el lazo, y el upload entra
entero: 1017 kB en ~17 s a ~60 kB/s, verificado en banco.

Uso:
    uv run python src/firmware/flash_lento.py .pio/build/esp32dev/firmware.bin
    uv run python src/firmware/flash_lento.py <bin> [ip] [chunk] [pausa]

Los defaults (1460 B, 4 ms) son los que se verificaron. Subir `chunk` o bajar
`pausa` acelera, pero es exactamente la palanca que hace fallar el upload.

Compilar primero:  pio run -e esp32dev
Después de flashear la placa reinicia sola; `homing_ok` vuelve a `false`, así que
hay que rehacer el homing (`/cmd?m=3`) antes de cualquier modo con par.
"""

import socket
import sys
import time
from pathlib import Path

BIN = Path(sys.argv[1])
HOST = sys.argv[2] if len(sys.argv) > 2 else "192.168.4.1"
CHUNK = int(sys.argv[3]) if len(sys.argv) > 3 else 1460
PAUSA = float(sys.argv[4]) if len(sys.argv) > 4 else 0.004

data = BIN.read_bytes()
B = "----------------------------qubeflash"
pre = (
    f"--{B}\r\n"
    f'Content-Disposition: form-data; name="update"; filename="firmware.bin"\r\n'
    f"Content-Type: application/octet-stream\r\n\r\n"
).encode()
post = f"\r\n--{B}--\r\n".encode()
body_len = len(pre) + len(data) + len(post)
head = (
    f"POST /update HTTP/1.1\r\nHost: {HOST}\r\n"
    f"Content-Type: multipart/form-data; boundary={B}\r\n"
    f"Content-Length: {body_len}\r\nConnection: close\r\n\r\n"
).encode()

s = socket.create_connection((HOST, 80), timeout=30)
s.settimeout(30)
s.sendall(head)
s.sendall(pre)
t0 = time.time()
enviado = 0
ultimo = 0
try:
    while enviado < len(data):
        n = s.send(data[enviado : enviado + CHUNK])
        enviado += n
        if PAUSA:
            time.sleep(PAUSA)
        if enviado - ultimo >= 128 * 1024:
            ultimo = enviado
            v = enviado / 1024 / (time.time() - t0)
            print(f"  {enviado / 1024:7.0f} KB / {len(data) / 1024:.0f} KB   {v:5.1f} KB/s", flush=True)
    s.sendall(post)
    print(f"  cuerpo completo: {enviado / 1024:.0f} KB en {time.time() - t0:.1f}s", flush=True)
except Exception as e:
    print(f"  FALLO a los {enviado / 1024:.1f} KB ({100 * enviado / len(data):.1f}%): {e!r}")
    sys.exit(1)
s.settimeout(120)
resp = b""
try:
    while True:
        b = s.recv(4096)
        if not b:
            break
        resp += b
except Exception as e:
    print("  (sin respuesta:", repr(e), ")")
s.close()
print("  respuesta:", resp.decode(errors="replace").strip()[:300] or "(vacia)")
