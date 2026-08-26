# Investigacion Detallada de la Modernizacion del QUBE Servo

Fecha: 2026-05-11  
Proyecto: Modernizacion de plataforma QUBE Servo con arquitectura abierta de bajo costo  
Autor: Documento tecnico para integracion a tesis

---

## 1. Resumen Ejecutivo

Este documento presenta una investigacion extensa y detallada sobre la viabilidad tecnica, experimental y academica de modernizar una plataforma tipo QUBE Servo utilizando componentes accesibles: ESP32, L298N, INA219 y conversion de potencia mediante modulo buck. El objetivo central es aproximar funcionalidades clave de una plataforma educativa/comercial de control rotatorio, reduciendo costo y manteniendo valor pedagogico para cursos de control, instrumentacion y sistemas embebidos.

La revision realizada permite concluir que:

- No se identifico un proyecto abierto que integre exactamente la combinacion completa propuesta (ESP32 + L298N + INA219 + regulacion buck) en una arquitectura unica y documentada de principio a fin para emulacion de QUBE.
- Si existe evidencia solida de viabilidad por componentes y por subsistemas: control PID de motor DC, lectura de encoder incremental, telemetria de corriente/voltaje por I2C y supervisiones de interfaz en aplicaciones de laboratorio.
- La arquitectura propuesta tiene potencial de contribucion original, tanto en formato de repositorio tecnico como en formato de aporte academico aplicado.

Esta investigacion tambien define riesgos principales, criterios de validacion, protocolo experimental, metrica de desempeno y hoja de ruta de implementacion por fases.

---

## 2. Contexto y Motivacion

Los sistemas comerciales para control de pendulo rotatorio y servo de laboratorio ofrecen alta calidad de instrumentacion, pero su costo limita adopcion en entornos con presupuesto reducido. La modernizacion con hardware abierto busca:

- Democratizar el acceso a practicas de control avanzado.
- Permitir replicabilidad y trazabilidad de resultados.
- Facilitar mantenimiento y escalabilidad por modularidad.
- Integrar telemetria para diagnostico experimental continuo.

En este marco, el proyecto no solo replica funciones basicas de actuacion y sensado; tambien incorpora una capa de observabilidad energetica (INA219) y una base de software extensible para iterar hacia control clasico y moderno.

---

## 3. Objetivos de la Investigacion

### 3.1 Objetivo general

Evaluar y consolidar una arquitectura tecnica de bajo costo para emulacion funcional de una plataforma QUBE Servo, con capacidad de control de posicion/velocidad y adquisicion de senales para analisis experimental.

### 3.2 Objetivos especificos

- Caracterizar factibilidad de cada bloque hardware de la arquitectura.
- Definir topologia de integracion electrica y de software embebido.
- Establecer protocolo de pruebas de desempeno y estabilidad.
- Identificar riesgos de instrumentacion (ruido, latencia, no linealidades, saturacion).
- Proponer ruta de evolucion hacia control de pendulo invertido.

---

## 4. Alcance y Limites

### 4.1 Alcance

- Evaluacion de arquitectura de control rotatorio basada en ESP32.
- Uso de driver L298N para actuacion de motor DC con PWM.
- Lectura de encoder incremental para retroalimentacion.
- Integracion de INA219 para monitoreo de variables electricas.
- Integracion con GUI Python para monitoreo, comando y logging CSV.

### 4.2 Limites del estudio

- El documento se centra en viabilidad de plataforma y etapas iniciales de control.
- No asume validacion final de swing-up del pendulo en este punto.
- No se presenta aqui una identificacion parametricamente cerrada del modelo completo del sistema mecanico (queda como etapa experimental formal).

---

## 5. Estado del Arte Sintetizado

A partir de la investigacion previa en repositorios y notas internas del proyecto, se observa lo siguiente:

### 5.1 Control de motor con retroalimentacion

- Existen multiples implementaciones con Arduino y drivers H-bridge en lazo cerrado.
- En ESP32, hay proyectos con encoder y control de velocidad/posicion, aunque no siempre con enfasis academico.
- Los enfoques mas utiles para esta tesis son aquellos que reportan metodologia de ajuste y limitaciones observadas en hardware real.

### 5.2 Instrumentacion de potencia

- INA219 presenta ecosistema maduro de librerias y casos de uso.
- Su uso en este proyecto agrega valor metodologico: permite correlacionar senales de control con consumo energetico.

### 5.3 Sistemas tipo pendulo rotatorio

- Se encuentran trabajos academicos con modelado y control, mayormente sobre plataformas propietarias o configuraciones custom con Arduino.
- La oportunidad de aporte del presente trabajo se ubica en unir accesibilidad, documentacion reproducible y telemetria integrada.

---

## 6. Arquitectura Tecnica Propuesta

## 6.1 Bloques funcionales

1. Fuente de energia y conversion:
- Entrada principal desde fuente externa.
- Buck converter para alimentacion regulada de logica/sensores.

2. Computo y control:
- ESP32 como nucleo de adquisicion, control y comunicacion.

3. Actuacion:
- L298N para control bidireccional del motor mediante PWM y direccion.

4. Sensado de estado mecanico:
- Encoder incremental del motor/eje para estimacion de posicion y velocidad.

5. Sensado electrico:
- INA219 por I2C para corriente, voltaje y potencia.

6. Capa de supervision:
- API local en el firmware y GUI en Python para visualizacion y comandos.

### 6.2 Flujo de informacion

- Referencia de control entra por interfaz local.
- ESP32 ejecuta lazo de control en tiempo real.
- Senal de control alimenta etapa de potencia (L298N).
- Encoder cierra la retroalimentacion mecanica.
- INA219 alimenta canal de diagnostico energetico.
- Estado consolidado se publica para GUI/registro.

---

## 7. Justificacion de Componentes

### 7.1 ESP32

Ventajas:
- Capacidad de procesamiento superior a placas clasicas de 8 bits.
- Conectividad integrada para telemetria y futuras extensiones remotas.
- Entorno de desarrollo consolidado.

Riesgos:
- Mayor complejidad de temporizacion y coexistencia de tareas.
- Necesidad de disciplina en arquitectura de firmware para evitar jitter.

### 7.2 L298N

Ventajas:
- Bajo costo, disponibilidad alta y adopcion extendida.
- Adecuado para etapa inicial de validacion de control.

Riesgos:
- Eficiencia inferior respecto a drivers MOSFET modernos.
- Posibles calentamientos y perdidas en escenarios de alta exigencia.

### 7.3 INA219

Ventajas:
- Medicion digital de potencia sin cadenas analogicas complejas.
- Integracion I2C simple y estable.

Riesgos:
- Error de medicion bajo ruido de conmutacion.
- Requiere filtrado y estrategia de muestreo consistente.

### 7.4 Buck converter

Ventajas:
- Solucion economica y difundida para regulacion.
- Permite separar rail de potencia y rail de logica.

Riesgos:
- Ripple y ruido si no se filtra adecuadamente.
- Integridad de tierra critica en laboratorio.

---

## 8. Consideraciones de Integracion Electrica

- Separar rutas de alta corriente y senales de baja amplitud.
- Implementar punto de tierra comun con criterio de estrella cuando sea posible.
- Evitar lazos de tierra amplios que inyecten ruido en lineas de sensado.
- Cuidar la adaptacion de niveles logicos de encoder a entradas del ESP32.
- Verificar estabilidad del rail de 3.3 V bajo perturbaciones de PWM.

### 8.1 Senal de encoder

La confiabilidad de lectura del encoder es condicion necesaria para cualquier controlador en lazo cerrado. Por ello, la etapa de acondicionamiento de senal debe verificarse con prioridad, evaluando:

- Niveles alto/bajo bien definidos en entradas del microcontrolador.
- Tiempo de subida y bajada compatible con frecuencia de conteo esperada.
- Ausencia de zonas intermedias persistentes que generen conteo erratico.

---

## 9. Arquitectura de Software y Firmware

### 9.1 Firmware embebido

Capas recomendadas:

1. Capa de hardware abstraction:
- PWM, GPIO, I2C, lectura encoder, temporizadores.

2. Capa de estimacion:
- Conteo de pulsos, conversion a angulo/velocidad, normalizacion.

3. Capa de control:
- Modos manual, abierto y cerrado (PID).
- Saturaciones, anti-windup y validaciones de seguridad.

4. Capa de comunicacion:
- Endpoints de estado y comando.
- Serial para depuracion y trazas.

5. Capa de telemetria:
- Publicacion de estado consolidado y valores electricos.

### 9.2 GUI en Python

Funciones objetivo:

- Monitoreo en tiempo real de posicion, velocidad, corriente y potencia.
- Emision de comandos de referencia y modos de control.
- Registro CSV para analisis posterior.
- Visualizacion de eventos de saturacion o perdida de seguimiento.

---

## 10. Metodologia Experimental Propuesta

### 10.1 Estrategia por fases

Fase A: validacion de infraestructura
- Energia estable.
- Comunicacion con ESP32.
- Lecturas basicas de sensores.

Fase B: caracterizacion de actuador
- Relacion PWM vs velocidad en vacio.
- Deteccion de zona muerta y saturacion.

Fase C: cierre de lazo de velocidad
- Ajuste inicial de ganancia proporcional.
- Introduccion gradual de termino integral y derivativo.

Fase D: cierre de lazo de posicion
- Seguimiento de consignas escalon y rampa.
- Medicion de sobreimpulso y tiempo de establecimiento.

Fase E: telemetria energetica integrada
- Correlacion entre esfuerzo de control y consumo.
- Deteccion de regimenes ineficientes o inestables.

### 10.2 Protocolo de prueba minimo

Para cada corrida experimental registrar:

- Fecha y version de firmware.
- Parametros de control activos.
- Frecuencia de muestreo y ventana de analisis.
- Tipo de referencia aplicada.
- Metricas resultantes.
- Observaciones cualitativas (ruido, vibracion, calentamiento).

---

## 11. Metricas de Evaluacion

### 11.1 Metricas de seguimiento

- Error estacionario.
- Tiempo de subida.
- Tiempo de establecimiento.
- Sobreimpulso maximo.
- Error absoluto medio en ventana de prueba.

### 11.2 Metricas de robustez

- Sensibilidad a perturbacion externa breve.
- Variacion de respuesta ante cambios de carga.
- Repetibilidad entre corridas bajo mismo setpoint.

### 11.3 Metricas energeticas

- Corriente promedio y pico por maniobra.
- Potencia promedio en regimen estacionario.
- Energia consumida por ciclo de control.

### 11.4 Metricas de calidad de instrumentacion

- Perdida de paquetes o lecturas nulas.
- Jitter de muestreo efectivo.
- Coherencia entre estimaciones mecanicas y electricas.

---

## 12. Riesgos Tecnicos y Mitigaciones

1. Ruido electromagnetico en mediciones
- Mitigacion: desacoplo local, filtrado digital y orden de cableado.

2. Lectura no confiable de encoder
- Mitigacion: acondicionamiento de entrada, validacion de niveles y prueba de conteo en banco.

3. Saturacion termica del driver
- Mitigacion: limites de duty, disipacion adecuada y monitoreo de temperatura.

4. Inestabilidad por mala sintonizacion
- Mitigacion: procedimiento de ajuste incremental y limites de seguridad.

5. Latencia de interfaz afectando control
- Mitigacion: ejecutar lazo local y usar interfaz solo para supervision/comando.

---

## 13. Aporte Academico Esperado

El valor academico de esta investigacion no depende unicamente de replicar hardware, sino de estructurar evidencia reproducible de diseno, pruebas y resultados. Se esperan los siguientes aportes:

- Metodologia abierta para reconstruccion de plataforma tipo QUBE a bajo costo.
- Integracion de telemetria energetica como variable explicativa del desempeno de control.
- Base experimental para comparar control clasico y potencial control por estados.
- Evidencia de decisiones de ingenieria con trazabilidad (hardware, firmware y datos).

---

## 14. Hoja de Ruta Tecnica Recomendada

### Etapa 1: Consolidacion de base servo

- Garantizar estabilidad en control de posicion y velocidad del eje principal.
- Cerrar pipeline confiable de datos: firmware -> GUI -> CSV.

### Etapa 2: Identificacion de parametros

- Estimar parametros electromecanicos clave del sistema.
- Construir modelo simplificado util para simulacion y ajuste.

### Etapa 3: Integracion pendulo

- Agregar dinamica acoplada del pendulo.
- Validar medicion angular y linealidad de sensores adicionales.

### Etapa 4: Control avanzado

- Implementar control por espacio de estados o estrategia equivalente.
- Evaluar region de operacion estable y condiciones de recuperacion.

### Etapa 5: Cierre academico

- Comparar resultados con referencias reportadas en literatura/tesis.
- Preparar documento final con anexos de datos y reproducibilidad.

---

## 15. Criterios de Exito del Proyecto

Se considera que la modernizacion cumple su objetivo si se alcanzan de forma verificable los siguientes puntos:

- Control de posicion repetible con error estacionario acotado.
- Registro estable de telemetria mecanica y energetica durante ensayos.
- Operacion continua sin fallas criticas en sesiones de laboratorio.
- Documentacion tecnica suficiente para reproduccion por terceros.
- Relacion costo/beneficio claramente favorable frente a plataformas comerciales.

---

## 16. Plan de Documentacion y Reproducibilidad

Para asegurar calidad academica y transferencia de conocimiento:

- Versionar firmware y registrar cambios por version.
- Etiquetar datasets por fecha, condicion y parametros de control.
- Mantener guia de puesta en marcha con esquema de conexion.
- Preservar trazabilidad de decisiones tecnicas y desviaciones observadas.

### 16.1 Estructura sugerida de anexos

- Anexo A: Esquemas electricos y tabla de pines.
- Anexo B: Parametros de firmware por version.
- Anexo C: Tablas de metricas por experimento.
- Anexo D: Scripts de postproceso de datos.
- Anexo E: Limitaciones abiertas y trabajo futuro.

---

## 17. Discusion Integrada

La investigacion actual muestra un escenario favorable: los bloques de hardware son accesibles, la curva de implementacion es razonable para entorno universitario, y existe suficiente masa critica de referencias parciales para reducir incertidumbre de integracion. El principal reto no es encontrar componentes, sino asegurar calidad de instrumentacion, rigor experimental y arquitectura de software ordenada.

Desde la perspectiva de tesis, esto representa una ventaja: permite transformar una integracion de hardware en una contribucion metodologica valida, con resultados medibles y comparables.

---

## 18. Conclusiones

1. La arquitectura de modernizacion propuesta es tecnicamente viable y pertinente para docencia e investigacion aplicada.
2. No se detecta una implementacion abierta integral identica; esto abre espacio para aporte original.
3. Los riesgos clave son manejables mediante buenas practicas de integracion electrica, control incremental y telemetria estructurada.
4. El proyecto tiene potencial de impacto alto en relacion costo, accesibilidad y valor formativo.
5. La siguiente etapa critica es consolidar protocolo experimental con metrica uniforme para fortalecer resultados de tesis.

---

## 19. Trabajo Futuro Propuesto

- Integrar modelado formal con estimacion de parametros basada en datos reales.
- Evaluar migracion a driver de mayor eficiencia para comparar consumo y respuesta.
- Extender GUI con herramientas de identificacion y ajuste asistido.
- Implementar reportes automaticos por corrida experimental.
- Analizar sensibilidad del sistema a variaciones de alimentacion y carga mecanica.

---

## 20. Referencias y Evidencia

Este documento se construye a partir de la investigacion previa del repositorio y sus hallazgos consolidados. Para fortalecer el capitulo bibliografico final de tesis se recomienda:

- Verificar y normalizar citas de repositorios relevantes.
- Complementar con articulos revisados por pares sobre rotary inverted pendulum.
- Mantener separacion explicita entre evidencia validada y trabajo en curso.

Nota metodologica:
Este documento evita inventar datos experimentales no medidos. Los valores numericos de desempeno deben incorporarse solo desde corridas registradas y auditables en archivos de datos del proyecto.
