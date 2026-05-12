# AGENTS.md

Instrucciones base para agentes AI que trabajen en este repositorio.

## Objetivo del repositorio

- Modernizacion del QUBE Servo con arquitectura ESP32 + L298N + INA219.
- Trabajo dividido entre firmware embebido, GUI Python para adquisicion de senales e investigacion academica en Markdown.

## Estructura clave

- `firmware/esp32_qube_l298n/esp32_qube_l298n.ino`: firmware principal del sistema de control.
- `firmware/CHANGELOG.md`: historial de versiones del firmware.
- `gui/app.py`: interfaz Tkinter para monitoreo y control.
- `gui/esp32_client.py`: cliente HTTP (`/state`, `/cmd`) para ESP32.
- `Data/`: capturas CSV de sesiones experimentales.
- `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md`: documento principal de investigacion.
- `Referencias/build_pdf.ps1`: script para compilar investigacion a PDF.

## Comandos de trabajo frecuentes

### GUI (Python)

```powershell
python -m pip install -r gui/requirements.txt
python gui/app.py
```

### Compilar PDF de investigacion

```powershell
cd Referencias
.\build_pdf.ps1 -InputFile "..\INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md" -OutputFile "Investigacion_QUBE_Servo_Emulacion_ESP32_v2.pdf"
```

Nota: si el PDF destino esta abierto, el script genera un nombre alternativo con timestamp.

## Convenciones y reglas criticas

- Si se modifica `firmware/**/*.ino`, actualizar `firmware/CHANGELOG.md` en la misma respuesta de trabajo.
- Mantener cambios pequenos y enfocados; evitar reformateos masivos sin necesidad.
- En investigacion academica: no inventar datos ni referencias; marcar faltantes como pendientes.
- Para cambios de firmware, preservar endpoints HTTP existentes (`/state`, `/cmd`) salvo solicitud explicita.

## Pitfalls conocidos

- `gui/esp32_client.py` usa por defecto la IP `192.168.4.1` (AP del ESP32).
- En `firmware/esp32_qube_l298n/esp32_qube_l298n.ino` existen credenciales STA configurables (`STA_SSID`, `STA_PASS`); tratarlas con cuidado y no exponerlas fuera del repo.
- En compilacion PDF, un archivo abierto puede bloquear sobrescritura.

## Personalizaciones existentes (usar en lugar de duplicar)

- Instruccion de changelog firmware: `.github/instructions/firmware-changelog.instructions.md`
- Skill de investigacion de hardware: `.github/skills/investigacion-hardware-qube/SKILL.md`
- Agente de analisis de papers: `.github/agents/analista-investigacion.agent.md`
- Prompt de bibliografia: `.github/prompts/exportar-bibliografia.prompt.md`
