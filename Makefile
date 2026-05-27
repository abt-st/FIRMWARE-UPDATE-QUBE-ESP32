# ──────────────────────────────────────────────────────────────────────────────
#  Makefile — QUBE ESP32 Project
#  Usa `uv` para gestionar el entorno Python y ejecutar herramientas.
# ──────────────────────────────────────────────────────────────────────────────

.PHONY: install run lint format check typecheck clean test help

# ── Configuración ──────────────────────────────────────────────────────────
PYTHON     := uv run python
RUFF       := uv run ruff
PYRIGHT    := uv run pyright
UV         := uv

# ── Goals ──────────────────────────────────────────────────────────────────

install:           ## Instalar todas las dependencias (uv sync)
	$(UV) sync

run:               ## Ejecutar la GUI del QUBE Signal Identifier
	$(PYTHON) gui/app.py

lint:              ## Ejecutar ruff check (linteo estático)
	$(RUFF) check .

format:            ## Formatear todo el código Python con ruff
	$(RUFF) format .

check:             ## Verificar lint + formato (CI)
	$(RUFF) check .
	$(RUFF) format --check .

typecheck:         ## Verificar tipos con pyright (si está instalado)
	$(PYRIGHT) .

test:              ## Ejecutar tests (pytest, si existen)
	$(PYTHON) -m pytest -v

clean:             ## Limpiar archivos temporales de Python
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name ".DS_Store" -delete
	rm -rf .pytest_cache
	rm -rf .ruff_cache
	rm -rf *.egg-info

help:              ## Mostrar esta ayuda
	@grep -Eh '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| sort \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'