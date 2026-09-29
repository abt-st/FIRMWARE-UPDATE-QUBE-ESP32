"""Estima el tamaño de la respuesta de /state contra el `reserve()` de getStateJson.

Si el JSON supera el reserve, cada llamada a /state realoca el String — que es
exactamente la fragmentación que el `reserve()` existe para evitar.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
src = (RAIZ / "src/firmware/esp32_qube/esp32_qube.ino").read_text(encoding="utf-8", errors="replace")

i = src.find("String getStateJson()")
j = src.find("\nString ", i + 10)
cuerpo = src[i : j if j > 0 else i + 14000]
lineas = [ln for ln in cuerpo.splitlines() if "json +=" in ln]

m = re.search(r"json\.reserve\((\d+)\)", cuerpo)
reserve = int(m.group(1)) if m else None

# Consciente de escapes: en el fuente C un campo se escribe "\"nombre\":", y un
# `[^"]*` ingenuo corta en la primera comilla escapada y subcuenta todo.
LIT = re.compile(r'"((?:\\.|[^"\\])*)"')


def bytes_literales(linea: str) -> int:
    total = 0
    for trozo in LIT.findall(linea):
        # \" en el fuente C es UN byte (") en la salida
        total += len(trozo.replace('\\"', '"'))
    return total


lit = sum(bytes_literales(ln) for ln in lineas)
campos = len(re.findall(r'\\"[A-Za-z_0-9]+\\":', cuerpo))

# Valores: los String(x, 2/3) de float rondan 5-8 bytes; ints y bools, 1-10.
for por_campo in (5, 6, 7):
    print(f"  con ~{por_campo} bytes/valor -> total ~{lit + campos * por_campo} bytes")

print()
print(f"lineas 'json +=' : {len(lineas)}")
print(f"campos           : {campos}")
print(f"texto literal    : {lit} bytes")
print(f"reserve()        : {reserve}")

pw = [ln for ln in lineas if "pend_wn2" in ln]
if pw:
    aporte = bytes_literales(pw[0]) + 6
    print()
    print(f"la linea de pend_wn2 aporta ~{aporte} bytes")
    for por_campo in (6,):
        antes = lit + campos * por_campo - aporte
        ahora = lit + campos * por_campo
        print(f"  antes de mi cambio: ~{antes}   ahora: ~{ahora}   reserve: {reserve}")
        print(f"  -> {'YA se pasaba antes' if antes > reserve else 'antes entraba'};"
              f" {'AHORA se pasa' if ahora > reserve else 'ahora sigue entrando'}")
