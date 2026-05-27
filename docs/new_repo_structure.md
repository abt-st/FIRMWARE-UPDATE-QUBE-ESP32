# Propuesta de Reordenamiento del Repositorio QUBE ESP32

> **Estado:** Propuesta  
> **Objetivo:** Definir una estructura de proyecto profesional, mantenible y escalable que cumpla con las mejores prácticas de ingeniería de software.

---

## 📋 Resumen de Problemas Detectados

| # | Problema | Ubicación | Impacto |
|---|----------|-----------|---------|
| 1 | Carpetas con espacios (`old resources/`) | Raíz | Incompatible con muchos CLI tools y CI/CD |
| 2 | Contenido duplicado entre `docs/` y `DOCUMENTACION_VALIDACION/` | Raíz | Confusión, información inconsistente |
| 3 | Mezcla de investigación académica, firmware y GUI en raíz | Raíz | Sin separación clara de dominios |
| 4 | `gui/requirements.txt` obsoleto (usamos `uv` + `pyproject.toml`) | `gui/` | Dependencias desactualizadas |
| 5 | `gui/README` sin extensión y `gui/INDEX.HTML`, `gui/ESP32-HTTP` sin propósito claro | `gui/` | Archivos huérfanos |
| 6 | `CHANGELOG.md` duplicado (raíz y `firmware/`) | Raíz | Ambiguo: ¿cuál es el oficial? |
| 7 | Sin directorio de tests | — | Imposible verificar calidad del código |
| 8 | Sin `src/` layout para Python | `gui/` | Dificulta imports, empaquetado y testeo |
| 9 | Documentos de validación científica en `docs/` pero sin separación de investigación | `docs/` | Mezcla documentación técnica con investigación |
| 10 | Sin `notebooks/` o `experiments/` para análisis de datos | — | Los CSVs en `Data/` no tienen código de análisis asociado |

---

## 🏗️ Estructura Propuesta

```
FIRMWARE-UPDATE-QUBE-ESP32/
├── .github/                        ← Agentes AI, skills, prompts, instrucciones
│   ├── AGENTS.md
│   ├── agents/
│   ├── instructions/
│   ├── prompts/
│   └── skills/
│
├── src/                            ← Código Python fuente (packaged)
│   ├── qube_ui/                    ← GUI del QUBE Signal Identifier
│   │   ├── __init__.py
│   │   ├── app.py                  ← Ventana principal Tkinter
│   │   ├── client.py               ← HTTP client for ESP32
│   │   └── buffer.py               ← SignalBuffer (thread-safe)
│   └── qube_analysis/              ← Análisis de datos experimentales
│       ├── __init__.py
│       ├── metrics.py              ← Cálculo de overshoot, ts, error
│       └── plotter.py              ← Generación de gráficos
│
├── tests/                          ← Tests unitarios y de integración
│   ├── conftest.py
│   ├── test_client.py
│   ├── test_buffer.py
│   └── test_metrics.py
│
├── experiments/                    ← Notebooks y scripts de análisis
│   ├── notebooks/                  ← Jupyter notebooks (si aplica)
│   └── analyze_pid.py              ← Script reusable de análisis PID
│
├── firmware/                       ← Firmware del ESP32
│   ├── esp32_qube_l298n/
│   │   └── esp32_qube_l298n.ino
│   └── CHANGELOG.md
│
├── docs/                           ← Documentación técnica e investigación
│   ├── research/                   ← Documentos de investigación académica
│   │   ├── INVESTIGACION.md
│   │   └── referencias/
│   ├── validation/                 ← Documentos de validación científica
│   │   ├── SCIENTIFIC_FRAMEWORK.md
│   │   ├── VERIFICATION_CHECKLIST.md
│   │   ├── EXECUTIVE_SUMMARY.md
│   │   ├── VALIDATION_REPORT.md
│   │   ├── REFERENCE_MATRIX.md
│   │   └── QUICK_START_GUIDE.md
│   ├── architecture.md             ← Diagramas, pinout, flujo de datos
│   └── hardware/                   ← Fotos, esquemas, BOM
│
├── data/                           ← Capturas de datos experimentales (CSV)
│   ├── .gitkeep
│   └── README.md                   ← Descripción del formato y origen
│
├── pyproject.toml                  ← Dependencias, tool config (ruff, pytest, etc.)
├── Makefile                        ← Atajos: install, lint, format, test, run
├── .python-version                 ← Versión de Python (3.14)
├── uv.lock                         ← Lockfile generado por uv
├── README.md                       ← Documentación principal del proyecto
├── LICENSE                         ← MIT License
└── .gitignore                      ← Python, firmware, OS files
```

---

## 📦 Paquete Python (`src/qube_ui/`)

La GUI actualmente son dos módulos sueltos (`app.py`, `esp32_client.py`). Se propone convertirlos en un paquete instalable:

```
src/qube_ui/
├── __init__.py           ← from .app import App; from .client import ESP32Client, QubeState
├── app.py                ← Ventana principal (solo UI Tkinter)
├── client.py             ← ESP32Client, QubeState (sin Tkinter)
└── buffer.py             ← SignalBuffer (thread-safe, desacoplado de UI)
```

**Beneficios:**
- Importaciones limpias (`from qube_ui import App`)
- Tests unitarios posibles (separación UI/lógica)
- Empaquetado con `uv build` o `pip install -e .`

---

## 🗑️ Archivos a Eliminar o Migrar

| Archivo actual | Acción | Destino / Razón |
|----------------|--------|-----------------|
| `gui/requirements.txt` | **Eliminar** | Reemplazado por `pyproject.toml` + `uv sync` |
| `gui/README` | **Eliminar** | Sin extensión ni contenido relevante |
| `gui/INDEX.HTML` | **Migrar a docs/** o eliminar | Si es útil, mover a `docs/architecture.md` |
| `gui/ESP32-HTTP` | **Eliminar** | Propósito desconocido |
| `DOCUMENTACION_VALIDACION/` | **Migrar a docs/validation/** | Unificar documentación |
| `old resources/` | **Archivar o eliminar** | Contenido histórico, reemplazado por `docs/research/` y `docs/validation/` |
| `CHANGELOG.md` (raíz) | **Eliminar** | Ya existe en `firmware/CHANGELOG.md`; si hay cambios de Python, agregar sección allí |
| `Data/` | **Renombrar a `data/`** | Convención minúscula |

---

## 📋 Plan de Migración por Fases

### Fase 1 — Limpieza inmediata (días 1-2)

- [ ] Renombrar `Data/` → `data/`
- [ ] Mover `DOCUMENTACION_VALIDACION/` → `docs/validation/`
- [ ] Mover documentos de investigación → `docs/research/`
- [ ] Eliminar `gui/requirements.txt`, `gui/README`, `gui/INDEX.HTML`, `gui/ESP32-HTTP`
- [ ] Eliminar `CHANGELOG.md` duplicado en raíz
- [ ] Mover `old resources/` → `docs/archive/` (con README explicativo)

### Fase 2 — Reestructuración del código Python (días 3-5)

- [ ] Crear `src/qube_ui/` como paquete
- [ ] Mover `gui/app.py` → `src/qube_ui/app.py`
- [ ] Mover `gui/esp32_client.py` → `src/qube_ui/client.py`
- [ ] Extraer `SignalBuffer` → `src/qube_ui/buffer.py`
- [ ] Actualizar imports en `app.py`
- [ ] Crear `__init__.py` con exports explícitos
- [ ] Verificar que `uv run python -m qube_ui.app` funciona

### Fase 3 — Infraestructura de calidad (días 5-7)

- [ ] Crear `tests/` con pytest
- [ ] Agregar tests para `client.py`, `buffer.py`
- [ ] Verificar que `make check` (ruff lint + format) pasa
- [ ] Verificar que `make test` (pytest) pasa
- [ ] Opcional: configurar CI con GitHub Actions

### Fase 4 — Documentación final (día 8)

- [ ] Actualizar `README.md` con la nueva estructura
- [ ] Actualizar `AGENTS.md` reflejando las nuevas rutas
- [ ] Agregar `data/README.md` explicando formato CSV
- [ ] Documentar en `Makefile` los comandos disponibles

---

## ✅ Criterios de Aceptación

- [ ] `ruff check .` retorna 0 errores en todo el proyecto
- [ ] `ruff format .` retorna 0 cambios pendientes
- [ ] `uv run python -m qube_ui.app` inicia la GUI sin errores
- [ ] `pytest -v` ejecuta y pasa todos los tests
- [ ] No hay archivos con espacios en nombres de carpeta
- [ ] No hay archivos duplicados o huérfanos
- [ ] `docs/` es la única fuente de documentación
- [ ] `pyproject.toml` es la única fuente de dependencias Python
- [ ] `gui/requirements.txt` ha sido eliminado
- [ ] README actualizado con instrucciones usando `uv`

---

## 🔗 Referencias

- [Python Packaging: src Layout](https://packaging.python.org/en/latest/discussions/src-layout-vs-flat-layout/)
- [Ruff documentation](https://docs.astral.sh/ruff/)
- [uv documentation](https://docs.astral.sh/uv/)
- [BiomeJS](https://biomejs.dev/) — Linter/formatter para HTML, JS, CSS, JSON, Markdown
- [clang-format](https://clang.llvm.org/docs/ClangFormat.html) — Formatter para C/C++ (firmware)
- [markdownlint](https://github.com/DavidAnson/markdownlint) — Linter para archivos Markdown