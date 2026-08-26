"""Preferencias y presets de ganancias, en un JSON del usuario.

La GUI web guarda sus juegos de ganancias en ``localStorage`` desde hace tiempo y la app
no tenía nada: cada sesión arrancaba con los defaults y había que volver a tipear el
juego que uno venía usando. Con el banco derivando dentro de una misma sesión, retipear
ganancias es una fuente de error evitable.

Es un JSON y no ``QSettings`` por dos razones concretas: se puede abrir, leer y versionar
—un juego de ganancias que funcionó es un dato experimental, no una preferencia de
interfaz— y no obliga al núcleo a depender de Qt, que es la línea que separa este paquete
de ``ui/``.

**Nada de esto puede impedir que la app abra.** Un archivo corrupto, un disco de sólo
lectura o un perfil sin permisos se registran y se siguen de largo con los defaults: la
app sirve para operar un banco, y perder las preferencias no es motivo para no arrancar.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Junto al resto de lo que el usuario guarda, no dentro del repositorio: el `.exe`
#: empaquetado se copia a otra máquina y `Path.cwd()` allí es cualquier cosa.
DEFAULT_PATH = Path.home() / ".qube_app" / "settings.json"

#: Preferencias con su valor por omisión. Lo que no esté acá no se persiste, para que el
#: archivo no se llene de claves que nadie vuelve a leer.
DEFAULTS: dict[str, Any] = {
    "ip": "",
    "rate_hz": 500,
    "poll_s": 0.2,
    "window_s": 20.0,
    "record_dir": "",
    "read_only": False,
}


class AppSettings:
    """Preferencias y presets, cargados al abrir y escritos en cada cambio."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else DEFAULT_PATH
        self.prefs: dict[str, Any] = dict(DEFAULTS)
        self.presets: dict[str, dict[str, float]] = {}
        self.load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            logger.warning("no se pudo leer %s (%s): se usan los valores por omisión", self.path, exc)
            return
        if not isinstance(raw, dict):
            return
        # Sólo las claves conocidas: un archivo viejo con claves que ya no existen no
        # debe reaparecer en la interfaz por la puerta de atrás.
        for key in DEFAULTS:
            if key in raw.get("prefs", {}):
                self.prefs[key] = raw["prefs"][key]
        presets = raw.get("presets", {})
        if isinstance(presets, dict):
            self.presets = {
                str(name): {str(k): float(v) for k, v in values.items()}
                for name, values in presets.items()
                if isinstance(values, dict)
            }

    def save(self) -> bool:
        """Escribe el archivo. Devuelve ``False`` si no se pudo, sin lanzar."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"prefs": self.prefs, "presets": self.presets}
            self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return True
        except OSError as exc:
            logger.warning("no se pudieron guardar las preferencias en %s: %s", self.path, exc)
            return False

    # ── Preferencias ──────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self.prefs.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        if key not in DEFAULTS:
            raise KeyError(f"preferencia desconocida: {key}")
        self.prefs[key] = value

    def update(self, **values: Any) -> None:
        for key, value in values.items():
            self.set(key, value)
        self.save()

    # ── Presets ───────────────────────────────────────────────────────────────

    def save_preset(self, name: str, values: dict[str, float]) -> None:
        name = name.strip()
        if not name:
            raise ValueError("el preset necesita un nombre")
        self.presets[name] = {str(k): float(v) for k, v in values.items()}
        self.save()

    def delete_preset(self, name: str) -> None:
        if self.presets.pop(name, None) is not None:
            self.save()

    def names(self) -> list[str]:
        return sorted(self.presets)
