---
description: "Actualizar CHANGELOG del firmware. Usar cuando se modifique esp32_qube_l298n.ino: agregar nueva versión, registrar cambios, corregir bugs, ajustar parámetros PID, cambiar pines, o cualquier modificación al firmware del QUBE Servo. Aplica también en chats del agente cuando se proponga, discuta o implemente cualquier cambio de firmware, incluso si el archivo no está adjunto explícitamente."
applyTo: "firmware/**/*.ino"
---

# Regla: Actualizar CHANGELOG tras cada edición del firmware

Cada vez que modifiques `firmware/esp32_qube_l298n/esp32_qube_l298n.ino`, **debes** agregar una entrada al tope de `firmware/CHANGELOG.md` **en la misma respuesta**, antes de terminar.

## Formato de entrada

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
// Líneas modificadas con comentario de por qué
```

#### Notas
- Impacto esperado, comandos HTTP relevantes, valores de ajuste fino si aplica.
```

## Reglas de versionado (SemVer simplificado)

| Tipo de cambio | Incrementar |
|---|---|
| Nueva función (WiFi, endpoint, modo) | MINOR (Y) |
| Corrección de bug, ajuste de parámetro | PATCH (Z) |
| Cambio de arquitectura o pines | MAJOR (X) |

## Proceso obligatorio

1. Lee el encabezado del CHANGELOG para conocer la **versión actual** (`## [X.Y.Z]`).
2. Incrementa el número según la tabla anterior.
3. Inserta la nueva entrada **al tope** del archivo, inmediatamente después del párrafo introductorio y antes de la primera entrada existente.
4. **No elimines** entradas anteriores.
5. Usa la fecha actual del sistema (`2026-05-07` en este contexto).

## Ejemplo mínimo aceptable

```markdown
## [1.17.1] — 2026-05-07

### Fix: Divisor resistivo encoder corregido a pull-up 4.7 kΩ a 3.3 V

#### Problema identificado
- Señal en GPIO34/GPIO35 medía 15–40 mV en estado alto.
- Causa: divisor 4.7 kΩ / 8.2 kΩ sin fuente en estado alto (encoder open-drain).

#### Cambios aplicados
- Eliminado el 8.2 kΩ a GND de los canales A y B.
- Conectado pull-up 4.7 kΩ a 3.3 V en cada canal.

#### Cambios de hardware (no de firmware)
- No se modificó código; el fix es eléctrico.
```
