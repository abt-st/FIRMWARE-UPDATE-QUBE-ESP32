# 📚 Documentos de Investigación

Esta carpeta contiene la investigación académica y técnica consolidada del proyecto QUBE Servo Modernizado.

## Documentos

| Archivo | Propósito |
|---------|-----------|
| `Investigación Modernización del QUBE Servo.md` | Investigación unificada completa: estado del arte, arquitectura, metodología experimental, métricas |
| `DRL_IMPLEMENTATION_PLAN.md` | Plan de implementación del control por aprendizaje por refuerzo profundo (DRL) |
| `METODOS_ALTERNATIVOS_RL_BALANCE.md` | Métodos alternativos de RL evaluados para la fase de balance |
| `METODOS_ESTABILIZACION_PENDULOS_INVERTIDOS.md` | Estado del arte de métodos de estabilización de péndulos invertidos |
| `softap_app_escritorio.md` | Evaluación de operar la ESP32 como SoftAP puro (sin STA) con una aplicación de escritorio: transportes, ventajas/desventajas, riesgos y protocolo de medición |
| `adquisicion_por_bloques.md` | Arquitectura de adquisición: el ESP32 muestrea a 500 Hz en buffer circular y el PC reconstruye y analiza. Formato binario, contratos y por qué el lazo de control NO se mueve al computador |
| `estabilizacion_senales.md` | Análisis de estabilización de señales, ruido y filtrado |
| `frecuencias_control_pendulos_quanser.md` | Frecuencias de control usadas en péndulos Quanser de referencia |
| `integracion_encoder_pendulo.md` | Investigación sobre integración del encoder del péndulo |
| `ai_research/` | Sub-investigaciones puntuales: modelado LQR, viabilidad de RL, acondicionamiento de señal del encoder, CD40106BE, plan del gemelo digital DRL |
| `../../ref/` | PDFs, datasheets y papers de referencia |

## Historial de cambios

- 2026-05-26: Creación de estructura organizada de documentación (consolidado de `old resources/`, ver `~TESIS/recursos antiguos/` — pendiente de archivar).
- 2026-07-28: Tabla de documentos actualizada para reflejar los nombres/archivos reales (habían sido renombrados desde la creación de esta carpeta).
- 2026-07-31: Se agrega `softap_app_escritorio.md` (investigación de SoftAP puro + aplicación de escritorio; recomendación condicionada a la medición A/B que el propio documento define).
- 2026-07-31: Se agrega `adquisicion_por_bloques.md` (implementado en v1.57.0: firmware + `src/qube_daq/`; probado en tests, pendiente de banco).