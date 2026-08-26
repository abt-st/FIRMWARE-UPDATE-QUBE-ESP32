---
name: investigacion-hardware-qube
description: "Investiga hardware alternativo o componentes para la modernización del QUBE Servo con ESP32. Usa cuando el usuario quiera evaluar un nuevo componente, comparar alternativas de hardware, buscar proyectos similares en GitHub, o validar la viabilidad técnica de una arquitectura de hardware. Trigger phrases: investiga este componente, busca proyectos con, evalúa la viabilidad de, compara alternativas para, encuentra referencias para, qué tan viable es usar, existe algún proyecto que use, hardware para QUBE."
argument-hint: "Describe el componente, arquitectura o pregunta de investigación. Ej: ¿Es viable usar TB6612FNG en lugar de L298N?"
---

# Investigación de Hardware para Modernización QUBE Servo

## Contexto del Proyecto

**Plataforma:** QUBE Servo (péndulo rotatorio educativo)
**Arquitectura actual investigada:**
- Microcontrolador: ESP32-WROOM-32
- Driver de motor: L298N (H-bridge)
- Regulador de potencia: LM2596 (buck converter, 5V @ 3A)
- Sensor de corriente/potencia: INA219 (I2C, resolución 0.1 mA)
- Motor: DC con encoder incremental (Premotec 990412016913)
- **Objetivo:** Emular/modernizar el QUBE Servo original a ~25–70× menor costo

**Documentos clave del workspace:**
- `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md` — investigación principal (PARTE 1–9)
- `RESUMEN_HALLAZGOS.md` — resumen ejecutivo de hallazgos previos
- `SIGNAL_STABILIZATION_INVESTIGATION.md` — análisis de ruido y filtrado
- `Referencias/` — PDFs y referencias compiladas

---

## Cuándo Usar Esta Skill

- Evaluar si un componente nuevo es viable en la arquitectura ESP32 + L298N + INA219
- Buscar proyectos académicos o de GitHub con hardware similar
- Comparar alternativas a un componente existente (ej. L298N vs TB6612FNG)
- Investigar un problema técnico específico (ruido, eficiencia, disipación térmica)
- Buscar papers o fuentes académicas que validen una decisión de hardware
- Agregar una nueva sección a `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md`

---

## Procedimiento de Investigación

### Paso 1 — Leer el estado actual
Antes de cualquier búsqueda, leer:
1. `RESUMEN_HALLAZGOS.md` para conocer lo que ya fue investigado
2. La sección relevante de `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md`

Esto evita duplicar hallazgos ya documentados.

### Paso 2 — Definir la pregunta de investigación

Formular la pregunta central en este formato:
> "¿Existe algún proyecto que use [COMPONENTE/ARQUITECTURA] para [APLICACIÓN] con [RESTRICCIONES]?"

**Criterios de evaluación a cubrir:**
| Criterio | Descripción |
|----------|-------------|
| Viabilidad técnica | ¿El componente cumple los requisitos eléctricos del sistema? |
| Precedente en GitHub | ¿Cuántos repositorios lo usan? ¿Con qué combinación de HW? |
| Validación académica | ¿Hay papers o tesis que lo validen? |
| Costo aproximado | ¿El costo es consistente con el objetivo de ×25–70 reducción? |
| Disponibilidad | ¿Está disponible como módulo breakout? ¿Es fácil de conseguir? |
| Integración con ESP32 | ¿Requiere librería estable? ¿Protocolo I2C/SPI/UART? |

### Paso 3 — Búsqueda en GitHub

Buscar repositorios usando `github_repo` o búsqueda web. Documentar resultados en tabla:

```markdown
| Repositorio | Autor | Stars | Año | Hardware | Similitud QUBE |
|-------------|-------|-------|-----|----------|----------------|
| nombre/repo | autor | N     | AAAA| ESP32 + X| Alta/Media/Baja|
```

Criterios de similitud con QUBE:
- **Alta (>80%):** Péndulo rotatorio o robot de balance + ESP32 + encoder + PID cerrado
- **Media (50–80%):** Control de motor DC + ESP32 + PID, sin péndulo
- **Baja (<50%):** Solo un componente en común, propósito diferente

### Paso 4 — Búsqueda de Papers/Referencias Académicas

Buscar en ResearchGate, ArXiv, IEEE Xplore, Google Scholar. Priorizar:
- Papers con implementación experimental (no solo simulación)
- Publicaciones de 2020–2026 (estado del arte reciente)
- Tesis de maestría/doctorado de universidades reconocidas

Documentar en formato:
```
**[Título]** — [Autores] ([Año])
- DOI/URL: ...
- Relevancia: [Por qué importa para el proyecto QUBE]
- Resultado clave: [Dato experimental o conclusión principal]
```

### Paso 5 — Síntesis de Hallazgos

Producir un resumen estructurado con estas secciones:

```markdown
## Hallazgos: [Componente/Tema Investigado]

### Veredicto
✅/⚠️/❌ [VIABLE / VIABLE CON CONDICIONES / NO RECOMENDADO]

### Evidencia de GitHub
- N repositorios encontrados con [componente]
- Proyecto de referencia: [repo más relevante]
- ...

### Evidencia Académica
- [Paper 1]: [hallazgo clave]
- ...

### Comparación con Arquitectura Actual
| Aspecto | Actual (X) | Alternativa (Y) | Ventaja |
|---------|-----------|-----------------|---------|

### Riesgos/Limitaciones
- ...

### Recomendación
[Recomendación concreta: adoptar / descartar / investigar más]
```

### Paso 6 — Proponer Integración al Documento

Identificar dónde integrar los hallazgos en `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md`:

- **PARTE 1–2:** Estado del arte en GitHub → agregar proyectos nuevos a tablas existentes
- **PARTE 3–4:** Referencias académicas → agregar papers nuevos
- **PARTE 5–6:** Análisis técnico de componentes → agregar secciones de componentes nuevos
- **PARTE 7–8:** Validación y pruebas → agregar resultados experimentales
- **PARTE 9+:** Nueva sección si el tema no encaja en ninguna parte existente

**SIEMPRE pedir confirmación antes de modificar cualquier archivo.**

---

## Criterios de Calidad

Una investigación está completa cuando:
- [ ] Se revisó `RESUMEN_HALLAZGOS.md` antes de empezar (sin duplicados)
- [ ] Se encontraron ≥3 repositorios de GitHub con el componente investigado
- [ ] Se identificó al menos 1 proyecto de referencia de alta similitud (>70%)
- [ ] Se encontró al menos 1 paper o tesis con validación experimental
- [ ] Se evaluaron los 6 criterios de la tabla del Paso 2
- [ ] Se produjo un veredicto claro (Viable / Viable con condiciones / No recomendado)
- [ ] Se propuso una sección y texto concreto para integrar al documento principal

---

## Restricciones

- **NO inventar datos**, valores numéricos ni citas bibliográficas
- **NO modificar archivos** sin confirmación explícita del usuario
- **NO repetir** hallazgos ya documentados en `RESUMEN_HALLAZGOS.md`
- **SÍ citar siempre** la fuente (URL de repo, DOI de paper, nombre de archivo)

---

## Compilar a PDF (opcional)

Una vez integrados los hallazgos, compilar el documento actualizado:

```powershell
cd "c:\Users\Anton\OneDrive\Desktop\Uni\~TESIS - QUBE\Referencias"
.\build_pdf.ps1 -InputFile "..\INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md" -OutputFile "Investigacion_QUBE_Servo_Emulacion_ESP32_v2.pdf"
```

> Si el PDF está abierto en el lector, cerrarlo antes de compilar (error de permisos).
