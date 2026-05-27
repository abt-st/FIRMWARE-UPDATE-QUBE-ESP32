# Experiments

Esta carpeta contiene los datos y scripts de experimentos realizados con el QUBE Servo.

## Estructura recomendada

```
experiments/
├── README.md                    # Este archivo
├── 2026-05-07_pid_tuning/      # Sesión de ajuste PID
│   ├── data/                    # Datos CSV capturados
│   ├── scripts/                 # Scripts de análisis
│   └── README.md               # Descripción del experimento
├── 2026-05-13_encoder_test/    # Pruebas de encoder
│   ├── data/
│   ├── scripts/
│   └── README.md
└── ...
```

## Convenciones

- **Nombre de carpetas**: `YYYY-MM-DD_descripción_corta`
- **Datos CSV**: Guardar en `data/` dentro de cada experimento
- **Scripts**: Guardar en `scripts/` dentro de cada experimento
- **Documentación**: Incluir `README.md` con:
  - Objetivo del experimento
  - Configuración del hardware
  - Parámetros PID utilizados
  - Resultados observados
  - Conclusiones

## Generación automática de datos

Los datos CSV se generan desde la GUI con el botón "Exportar CSV" o usando:

```python
from qube_ui.buffer import SignalBuffer

buffer = SignalBuffer()
buffer.export_csv("experiments/2026-05-07_pid_tuning/data/session_001.csv")
```
