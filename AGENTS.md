# AGENTS.md — Guía de Agentes AI para el Proyecto QUBE ESP32

Este repositorio cuenta con un ecosistema de **agentes, skills, instrucciones y prompts** diseñados para asistir en las distintas áreas del proyecto: firmware embebido, análisis de datos experimentales, investigación académica y documentación.

---

## 📋 Índice

- [Agentes Disponibles](#agentes-disponibles)
- [Skills Disponibles](#skills-disponibles)
- [Instrucciones](#instrucciones)
- [Prompts](#prompts)
- [Estructura del Repositorio para Agentes](#estructura-del-repositorio-para-agentes)
- [Convenciones y Reglas](#convenciones-y-reglas)

---

## 🤖 Agentes Disponibles

| Agente | Archivo | Propósito | Triggers |
|--------|---------|-----------|----------|
| **Analista de Investigación QUBE** | `.github/agents/analista-investigacion.agent.md` | Analiza PDFs/papers académicos y extrae puntos relevantes para la tesis de modernización del QUBE Servo | "analiza el pdf", "extrae puntos del paper", "puntos relevantes del paper", "revisar referencias" |
| **Analista PID QUBE** | `.github/agents/analista-pid-qube.agent.md` | Analiza datos CSV de control PID, identifica desempeño, overshoot, oscilaciones y sugiere ajustes | "analiza los datos del PID", "explica el desempeño del control", "grafica la respuesta del sistema", "sugiere ajustes PID" |
| **Changelog Manager** | `.github/agents/changelog-manager.agent.md` | Mantiene el CHANGELOG.md sincronizado con cambios reales del proyecto, clasifica por SemVer y genera entradas con formato correcto | "actualiza el changelog", "mantén el changelog actualizado", "revisa el changelog", "changelog", "qué falta en el changelog", "versiona el proyecto" |

### Analista de Investigación QUBE

**Archivo:** `.github/agents/analista-investigacion.agent.md`
**Rol:** Asistente de investigación académica especializado en sistemas de control, microcontroladores embebidos y plataformas educativas de péndulo rotatorio.

**Capacidades:**
- Lectura y análisis de PDFs/papers académicos
- Identificación de puntos relevantes para la investigación QUBE
- Clasificación en categorías: modelado matemático, resultados experimentales, limitaciones, arquitecturas HW, validación académica
- Filtrado de duplicados contra el documento de investigación existente
- Propuesta de integración con sección destino y texto sugerido

**Formato de salida:**
```markdown
## Puntos Relevantes Encontrados

### [N]. [Título del punto]
- **Fuente:** [Nombre del paper, año, autores]
- **Contenido:** [Extracto o síntesis]
- **Relevancia para QUBE:** [Por qué importa]
- **Sección sugerida:** [PARTE X: nombre]
- **Texto propuesto:**
  > [Texto redactado listo para insertar]
```

**Restricciones:**
- ❌ No modifica archivos sin confirmación explícita
- ❌ No inventa datos, valores o citas
- ❌ No repite puntos ya cubiertos en la investigación
- ✅ Solo propone integraciones concretas

---

### Analista PID QUBE

**Archivo:** `.github/agents/analista-pid-qube.agent.md`
**Rol:** Experto en análisis de datos de sistemas de control, especializado en PID para servomecanismos educativos.

**Capacidades:**
- Análisis de archivos CSV generados por el QUBE Servo
- Identificación de desempeño del lazo PID
- Detección de sobreimpulsos, oscilaciones y errores de seguimiento
- Sugerencia de ajustes de parámetros PID
- Cálculo de métricas clave: overshoot, tiempo de establecimiento, error estacionario
- Generación de gráficos con Python, matplotlib, pandas y numpy

**Ejemplos de uso:**
- _"Analiza el archivo experiments/2026-05-07_pid_tuning/data/qube_2026-05-07T00_32_35.csv y dime si el control PID está bien ajustado."_- _"Grafica la respuesta al escalón y calcula el overshoot."_
- _"¿Qué parámetros PID debería ajustar para mejorar el tiempo de establecimiento?"_

---

### Changelog Manager

**Archivo:** `.github/agents/changelog-manager.agent.md`
**Rol:** Gestor de documentación de cambios, experto en versionado semántico (SemVer).

**Capacidades:**
- Detección de cambios pendientes entre código actual y último registro del CHANGELOG
- Clasificación automática de cambios por tipo: MAJOR (arquitectura/pines), MINOR (nuevas funcionalidades), PATCH (correcciones/ajustes)
- Generación de entradas de changelog con el formato correcto del proyecto
- Verificación de integridad: versiones incrementales, fechas correctas, sin duplicados
- Registro de cambios en firmware, documentación, dependencias y configuración

**Archivos monitoreados:**
- `firmware/esp32_qube_l298n/esp32_qube_l298n.ino` — siempre
- `firmware/platformio.ini` — dependencias, flags, plataforma
- `gui/app.py`, `gui/esp32_client.py` — interfaz
- `pyproject.toml` — dependencias Python
- `mcp/esp32_qube_server.py` — herramientas MCP

**Formato de salida:**
```markdown
## [X.Y.Z] — YYYY-MM-DD

### <Título descriptivo>

#### Problema identificado (si aplica)
- Descripción y causa raíz.

#### Cambios aplicados
**1. <Cambio específico>**
- Detalle técnico.

#### Cambios de firmware
\`\`\`cpp
// Código modificado
\`\`\`

#### Notas
- Impacto, comandos relevantes.
```

**Ejemplos de uso:**
- _"Actualiza el changelog con los cambios que hicimos hoy."_
- _"Revisa si el changelog refleja todos los cambios recientes."_
- _"¿Falta documentar algún cambio en el CHANGELOG?"_

---

## 🛠️ Skills Disponibles

| Skill | Archivo | Propósito |
|-------|---------|-----------|
| **Investigación de Hardware QUBE** | `.github/skills/investigacion-hardware-qube/SKILL.md` | Investiga hardware alternativo, evalúa viabilidad técnica, busca proyectos similares en GitHub |

### Investigación de Hardware QUBE

**Archivo:** `.github/skills/investigacion-hardware-qube/SKILL.md`

Procedimiento completo para investigar componentes o arquitecturas de hardware alternativas:

1. **Leer estado actual** — revisar `RESUMEN_HALLAZGOS.md` y la sección relevante del documento de investigación
2. **Definir pregunta de investigación** — formular con criterios: viabilidad técnica, precedente en GitHub, validación académica, costo, disponibilidad, integración con ESP32
3. **Búsqueda en GitHub** — documentar repos con tabla de similitud QUBE (Alta >80%, Media 50–80%, Baja <50%)
4. **Búsqueda académica** — ResearchGate, ArXiv, IEEE Xplore, Google Scholar (2020–2026)
5. **Síntesis de hallazgos** — veredicto claro (✅/⚠️/❌) con evidencia, comparación y riesgos
6. **Propuesta de integración** — sección destino + texto concreto

**Criterios de calidad:**
- [ ] Revisión de `RESUMEN_HALLAZGOS.md` antes de empezar
- [ ] ≥3 repositorios de GitHub encontrados
- [ ] ≥1 proyecto de referencia con similitud >70%
- [ ] ≥1 paper o tesis con validación experimental
- [ ] Evaluación de los 6 criterios técnicos
- [ ] Veredicto claro
- [ ] Propuesta de integración con texto concreto

---

## 📝 Instrucciones

| Instrucción | Archivo | Aplica a | Propósito |
|-------------|---------|----------|-----------|
| **Actualizar CHANGELOG del firmware** | `.github/instructions/firmware-changelog.instructions.md` | `firmware/**/*.ino` | Cada modificación al firmware requiere actualizar el CHANGELOG automáticamente |

### Actualizar CHANGELOG del Firmware

**Regla obligatoria:** Cada vez que se modifique `firmware/esp32_qube_l298n/esp32_qube_l298n.ino`, **debe** agregarse una entrada al tope de `firmware/CHANGELOG.md` en la misma respuesta.

**Formato de entrada CHANGELOG:**
```markdown
## [X.Y.Z] — YYYY-MM-DD

### <Título descriptivo del cambio>

#### Problema identificado (si aplica)
- Descripción del síntoma o motivación del cambio.
- Causa raíz identificada.

#### Cambios aplicados
**1. <Cambio específico>**
- Descripción técnica.
- Valor anterior → valor nuevo (si corresponde).

#### Cambios de firmware
```cpp
// Líneas modificadas con comentario
```

#### Notas
- Impacto esperado, comandos HTTP relevantes.
```

**Versionado (SemVer simplificado):**

| Tipo de cambio | Incrementar |
|----------------|-------------|
| Nueva función (WiFi, endpoint, modo) | MINOR (Y) |
| Corrección de bug, ajuste de parámetro | PATCH (Z) |
| Cambio de arquitectura o pines | MAJOR (X) |

---

## 🔖 Prompts

| Prompt | Archivo | Propósito |
|--------|---------|-----------|
| **Exportar Bibliografía** | `.github/prompts/exportar-bibliografia.prompt.md` | Genera/exporta la bibliografía del proyecto en formato académico |
| **Compilar PDF** | `.github/prompts/build_pdf.ps1` | Script PowerShell para compilar la investigación a PDF |

---

## 📁 Estructura del Repositorio para Agentes

```
.github/
├── AGENTS.md                    ← Este archivo (índice general)
├── agents/                      ← Definiciones de agentes AI
│   ├── analista-investigacion.agent.md
│   ├── analista-pid-qube.agent.md
│   └── changelog-manager.agent.md
├── instructions/                ← Instrucciones para agentes
│   └── firmware-changelog.instructions.md
├── prompts/                     ← Prompts y scripts reutilizables
│   ├── build_pdf.ps1
│   └── exportar-bibliografia.prompt.md
└── skills/                      ← Skills especializados
    └── investigacion-hardware-qube/
        └── SKILL.md
```

### Archivos clave del proyecto (para contexto de agentes)

| Archivo | Propósito |
|---------|-----------|
| `firmware/esp32_qube_l298n/esp32_qube_l298n.ino` | Firmware principal del sistema de control |
| `firmware/CHANGELOG.md` | Historial de versiones del firmware |
| `gui/app.py` | Interfaz Tkinter para monitoreo y control |
| `gui/esp32_client.py` | Cliente HTTP (`/state`, `/cmd`) para ESP32 |
| `experiments/` | Datos CSV organizados por experimento |
| `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md` | Documento principal de investigación (PARTE 1–9) |
| `RESUMEN_HALLAZGOS.md` | Resumen ejecutivo de hallazgos de investigación |
| `SIGNAL_STABILIZATION_INVESTIGATION.md` | Análisis de ruido y filtrado de señal |

---

## ⚙️ Convenciones y Reglas

### Reglas generales para agentes AI

1. **No inventar datos** — valores numéricos, citas bibliográficas o especificaciones técnicas deben tener fuente verificable
2. **No modificar archivos sin confirmación** — siempre preguntar antes de realizar cambios
3. **Mantener cambios pequeños y enfocados** — evitar reformateos masivos
4. **Preservar endpoints HTTP existentes** — `/state` y `/cmd` no deben modificarse sin solicitud explícita
5. **Citar siempre la fuente** — URL de repositorio, DOI de paper, nombre de archivo
6. **Actualizar CHANGELOG del firmware** — cada modificación a `*.ino` requiere entrada en CHANGELOG

### 🐍 Reglas estrictas de calidad para Python

1. **Usar `uv` como gestor de paquetes y ejecutor** — siempre usar `uv run python`, `uv run ruff`, `uv sync`, etc. No usar `pip install` ni `python` directamente.
2. **Ejecutar `ruff check` y `ruff format` en cada cambio** — antes de dar por terminada cualquier modificación a archivos `.py`, ejecutar:
   ```bash
   uv run ruff check .
   uv run ruff format .
   ```
   Y resolver todos los errores antes de continuar.
3. **Tipado obligatorio** — todas las funciones, métodos y variables deben tener anotaciones de tipo (`def fn(x: int) -> str:`) siguiendo PEP 484. No se aceptan funciones sin anotaciones.
4. **Opcional: usar pyright/pyrefly** — se recomienda ejecutar `uv run pyright .` para verificar tipos estáticamente. Si el agente tiene acceso a pyright, debe usarlo en cada cambio.
5. **No usar `from module import *`** — todas las importaciones deben ser explícitas.
6. **Docstrings** — todas las funciones públicas y clases deben tener docstring (estilo Google o reStructuredText).

### 🧰 Herramientas de calidad de código recomendadas por lenguaje

| Lenguaje | Herramienta | Comando / Uso |
|----------|-------------|---------------|
| **Python** | [Ruff](https://docs.astral.sh/ruff/) | `uv run ruff check .` + `uv run ruff format .` |
| **Python (tipado)** | [Pyright](https://github.com/microsoft/pyright) | `uv run pyright .` |
| **Python (tests)** | [pytest](https://docs.pytest.org/) | `uv run pytest -v` |
| **HTML / JS / CSS / JSON / Markdown** | [Biome](https://biomejs.dev/) | `npx @biomejs/biome check --write .` |
| **JavaScript / TypeScript** | [Biome](https://biomejs.dev/) | `npx @biomejs/biome check --write .` |
| **Markdown** | [markdownlint](https://github.com/DavidAnson/markdownlint) | `npx markdownlint-cli "**/*.md" --fix` |
| **C / C++ (firmware)** | [clang-format](https://clang.llvm.org/docs/ClangFormat.html) | `clang-format -i firmware/esp32_qube_l298n/*.ino` |
| **C / C++ (firmware)** | [clang-tidy](https://clang.llvm.org/extra/clang-tidy/) | `clang-tidy firmware/esp32_qube_l298n/*.ino` |
| **TOML** | [taplo](https://taplo.tamasfe.dev/) | `taplo format pyproject.toml` |
| **PowerShell** | [PSScriptAnalyzer](https://github.com/PowerShell/PSScriptAnalyzer) | `Invoke-ScriptAnalyzer -Path script.ps1` |

### 📦 Gestión de dependencias con `uv`

- **Instalar todo** → `uv sync`
- **Agregar una dependencia** → `uv add <package>` (actualiza `pyproject.toml` + `uv.lock`)
- **Agregar dependencia dev** → `uv add --dev <package>`
- **Ejecutar un script** → `uv run python gui/app.py`
- **Ejecutar una herramienta** → `uv run ruff check .`
- **Actualizar lockfile** → `uv lock`

> ⚠️ No usar `pip install` bajo ninguna circunstancia. `uv` reemplaza por completo a `pip`, `pip-tools` y `virtualenv`.

### Pitfalls conocidos

- `gui/esp32_client.py` usa por defecto la IP `192.168.4.1` (modo AP del ESP32)
- En el firmware existen credenciales STA configurables (`STA_SSID`, `STA_PASS`); tratarlas con cuidado y no exponerlas fuera del repositorio
- Al compilar PDF, si el archivo destino está abierto en el lector, el script falla por permisos (el script genera un nombre alternativo con timestamp)

### Arquitectura base del proyecto

| Componente | Modelo | Función |
|------------|--------|---------|
| Microcontrolador | ESP32-WROOM-32 | Control principal, WiFi, ADC |
| Driver de motor | L298N (H-bridge) | Control del motor DC |
| Regulador de potencia | LM2596 (buck converter, 5V @ 3A) | Alimentación regulada |
| Sensor corriente/potencia | INA219 (I2C) | Monitoreo de consumo |
| Motor | DC con encoder incremental (Premotec 990412016913) | Actuador del péndulo |
| **Objetivo** | Emular/modernizar QUBE Servo original | ~25–70× menor costo |

---

## 🚀 Comandos de Trabajo Frecuentes

### GUI (Python) — usando uv
```bash
uv sync                          # Instalar dependencias
uv run python gui/app.py         # Ejecutar GUI
uv run ruff check .              # Linter
uv run ruff format .             # Formatear código
uv run pyright .                 # Verificación de tipos
```

### Compilar PDF de investigación
```powershell
cd Referencias
.\build_pdf.ps1 -InputFile "..\INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md" -OutputFile "Investigacion_QUBE_Servo_Emulacion_ESP32_v2.pdf"
```

### Makefile (atajos disponibles)
```bash
make install     # uv sync
make lint        # uv run ruff check .
make format      # uv run ruff format .
make check       # lint + format check (CI)
make typecheck   # uv run pyright .
make run         # uv run python gui/app.py
make test        # uv run pytest -v
make clean       # Limpiar __pycache__, .pyc, etc.
make help        # Mostrar todos los goals
```

---


