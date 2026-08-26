@echo off
REM Lanzador de la app sin empaquetar: doble clic y listo, siempre con el codigo actual
REM del repositorio. Es la via recomendada en el PC de desarrollo — el .exe de
REM `make exe` es para llevarse el banco a otra maquina que no tiene el entorno.
cd /d "%~dp0.."
uv run python -m qube_app %*
if errorlevel 1 pause
