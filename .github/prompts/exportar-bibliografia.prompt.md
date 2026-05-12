---
description: "Genera la sección de Referencias Bibliográficas en formato APA o IEEE a partir de los papers, libros y repositorios ya integrados en la investigación QUBE."
---

Lee el documento de investigación principal en `INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md` y extrae todas las fuentes citadas: papers académicos, libros, repositorios de GitHub, librerías, datasheets y recursos web.

Para cada fuente encontrada, genera la referencia completa en formato **${format:APA|IEEE}**.

Si falta información (año, autor, DOI, editorial), intenta completarla buscando en internet. Si no puedes confirmarla, marca el campo con `[PENDIENTE]` en lugar de inventarlo.

## Reglas de formato

**APA:**
- Artículo: Apellido, I. (Año). Título del artículo. *Nombre de la revista*, *Volumen*(Número), páginas. https://doi.org/...
- Libro: Apellido, I. (Año). *Título del libro*. Editorial.
- Repositorio GitHub: Apellido, I. [usuario]. (Año). *Nombre del repositorio* [Software]. GitHub. https://github.com/...
- Datasheet: Fabricante. (Año). *Nombre del componente datasheet* (Rev. X). URL

**IEEE:**
- Artículo: I. Apellido, "Título," *Nombre de revista*, vol. X, no. Y, pp. Z–Z, Año.
- Libro: I. Apellido, *Título del libro*. Ciudad: Editorial, Año.
- Repositorio GitHub: I. Apellido. (Año). *Nombre del repositorio* [Online]. Disponible: https://github.com/...
- Datasheet: Fabricante, "Nombre del componente," Datasheet Rev. X, Año. [Online]. Disponible: URL

## Salida esperada

Devuelve únicamente la lista de referencias ordenada alfabéticamente (APA) o por orden de citación (IEEE), lista para pegar directamente en la sección `## REFERENCIAS BIBLIOGRÁFICAS RECOPILADAS` del documento.

Al final indica cuántas referencias tienen campos `[PENDIENTE]` y cuáles son.
