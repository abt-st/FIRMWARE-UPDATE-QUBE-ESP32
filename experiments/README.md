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

Los datos CSV se generan desde la **GUI web** (`http://192.168.4.1/`) con el
botón **"Exportar CSV"** del panel _Recolección de datos_: graba mientras el
WebSocket transmite telemetría y descarga un `.csv` con columnas `time_s`,
`mode`, `position_deg`, `setpoint_deg`, `pend_position_deg`, `pwm`, `voltage_v`,
`current_mA`, `power_mW`.

Guardá el archivo descargado en la carpeta del experimento, p. ej.
`experiments/2026-05-07_pid_tuning/data/session_001.csv`.
