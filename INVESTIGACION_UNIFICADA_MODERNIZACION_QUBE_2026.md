---
title: "Investigacion Unificada: Modernizacion QUBE Servo"
subtitle: "Arquitectura ESP32 + LM2596 + INA219 + L298N"
author: "Documento tecnico consolidado para tesis"
date: "2026-05-11"
lang: "es-ES"
toc: true
toc-depth: 3
numbersections: true
---

<!-- markdownlint-disable MD025 MD029 MD032 -->

# Investigacion Unificada de la Modernizacion del QUBE Servo

Fecha: 2026-05-11  
Proyecto: Modernizacion de plataforma QUBE Servo con arquitectura abierta de bajo costo  
Alcance: Consolidacion de investigacion tecnica, experimental y academica en un solo documento

---

## 1. Resumen ejecutivo

### 1.1 Pregunta central

Existe un proyecto abierto que integre exactamente la combinacion ESP32 + LM2596 + INA219 + L298N para emulacion tipo QUBE Servo?

### 1.2 Respuesta breve

No se identifico una implementacion abierta integral con esa combinacion exacta.  
Si existe evidencia suficiente de viabilidad por bloques y por subsistemas:

- Control de motor DC con encoder en lazo cerrado
- Telemetria electrica por INA219
- Conversion buck LM2596 para alimentacion
- Integracion embebida con ESP32 y supervision por GUI

### 1.3 Conclusion principal

La arquitectura propuesta es viable, replicable y con potencial de aporte original para tesis, debido a la ausencia de una referencia abierta completa y a la posibilidad de documentar metodologia reproducible extremo a extremo.

---

## 2. Contexto, motivacion y aporte academico

Los sistemas comerciales tipo QUBE tienen alto valor didactico pero costo elevado. La propuesta abierta busca:

- Reducir barrera de acceso economica
- Mantener rigor de control e instrumentacion
- Habilitar trazabilidad de decisiones tecnicas
- Integrar telemetria energetica para analisis experimental

Aporte esperado para tesis:

- Metodologia de modernizacion reproducible
- Base experimental para comparar control clasico y control por estados
- Evidencia de integracion hardware + firmware + datos
- Ruta clara de evolucion hacia pendulo invertido completo

---

## 3. Estado del arte consolidado

### 3.1 Hallazgos por componente

- Control PID + L298N: multiples repositorios y tesis de validacion educativa
- ESP32 + motor + encoder: casos funcionales en control de velocidad/posicion
- INA219: ecosistema maduro de librerias y casos de uso
- LM2596: componente ampliamente adoptado en conversion de potencia
- Sistemas rotary inverted pendulum: referencias academicas con LQR y validacion experimental

### 3.2 Repositorios de referencia recurrentes

- Ezward/Esp32CameraRover2
- ebrahimabdelghfar/Rotary-Inverted-Pendulum
- beanjamminb/PID-Motor-Controller
- wty-yy/arduino_pid_controlled_motor
- Hagar633/Speed-Control-of-a-DC-Motor-Using-Arduino-and-L298N

### 3.3 Brecha detectada

No se encontro una implementacion abierta que combine en un solo pipeline:

- ESP32 como nucleo de control
- L298N como etapa de potencia
- INA219 como canal energetico integrado
- Regulacion buck LM2596
- Flujo completo de validacion experimental con documentacion consolidada

---

## 4. Arquitectura tecnica propuesta

### 4.1 Bloques funcionales

1. Energia y conversion:
- Fuente DC principal
- LM2596 para rail de logica

2. Computo y control:
- ESP32 para adquisicion, control y comunicacion

3. Actuacion:
- L298N para control bidireccional por PWM + direccion

4. Sensado mecanico:
- Encoder incremental de base
- Integracion futura del encoder de pendulo

5. Sensado electrico:
- INA219 por I2C para voltaje, corriente y potencia

6. Supervision y logging:
- Endpoints de firmware
- GUI Python con registro CSV

### 4.2 Flujo de informacion

Referencia -> controlador en ESP32 -> accion PWM en L298N -> dinamica del motor -> encoder realimenta posicion/velocidad -> INA219 aporta contexto energetico -> estado consolidado hacia GUI y almacenamiento.

---

## 5. Integracion electrica consolidada

### 5.1 Asignacion base de pines

- GPIO26/GPIO27: control L298N (IN1/IN2)
- GPIO34/GPIO35: encoder base A/B
- GPIO21/GPIO22: I2C para INA219 (SDA/SCL)
- UART0 por USB: depuracion

### 5.2 Conexion de potencia recomendada

- Fuente 12V a etapa de motor
- LM2596 para rail de logica
- GND comun en topologia estrella
- INA219 en high-side para medir consumo de la etapa de potencia

### 5.3 Nota de compatibilidad de niveles

- GPIO del ESP32 no son tolerantes a 5V en entrada digital
- Encoder debe acondicionarse a 3.3V de forma segura segun su tipo de salida

---

## 6. Diagnostico de campo confirmado: HW-FIX-1

### 6.1 Problema observado

Se detecto lectura no confiable del encoder de base:

- CNT no avanzaba de forma estable
- POS permanecia fija o erratica
- A/B en zona intermedia de voltaje
- PID sin retroalimentacion robusta

### 6.2 Causa raiz

El encoder opera como open-drain. El esquema inicial con level shifter de alta impedancia y luego divisor resistivo fue inadecuado para ese tipo de salida.

### 6.3 Solucion validada

- Eliminar level shifter inadecuado
- Pull-up externo de 4.7k ohm a 3.3V en A y B
- Mantener entradas GPIO34/GPIO35 como INPUT

### 6.4 Resultado

- CNT incremento monotono
- POS coherente con rotacion real
- Transiciones A/B limpias
- Convergencia del modo PID restablecida

---

## 7. Estabilizacion de senales y robustez

### 7.1 Fuentes de ruido relevantes

- Conmutacion PWM del L298N
- Ripple del LM2596
- Ruido impulsivo del motor DC
- Ground bounce por retornos mal distribuidos

### 7.2 Estrategia de mitigacion por capas

1. Capa de cableado y tierra:
- Star ground real
- Separacion de retornos de potencia y senal

2. Capa de desacoplo:
- Capacitancia bulk en rail principal
- Bypass local en ESP32, INA219 y L298N

3. Capa de entrada encoder:
- Pull-up correcto segun topologia open-drain
- RC moderado cerca del microcontrolador si hay picos
- Opcion recomendada para revision futura: buffer Schmitt trigger

4. Capa de firmware:
- Migrar a captura mas robusta (ISR/PCNT)
- Filtro digital de velocidad (EMA)
- Indicadores de ruido en telemetria

### 7.3 Capacidad de muestreo y riesgo de alias

Con polling lento puede haber perdida de transiciones en cuadratura. Se recomienda:

- Aumentar frecuencia de captura
- O usar interrupciones
- O migrar a PCNT como solucion escalable

---

## 8. Integracion del encoder del pendulo

### 8.1 Objetivo tecnico

Agregar segundo encoder en cuadratura para habilitar:

- Medicion de angulo de pendulo
- Estimacion de velocidad angular del pendulo
- Base para swing-up y estabilizacion vertical

### 8.2 Arquitectura recomendada

Prioridad: dual encoder con periferico PCNT del ESP32.

Ventajas:

- Menor jitter que polling puro
- Menor carga de CPU frente a ISR por ambos canales
- Escalabilidad para mayores frecuencias de borde

### 8.3 Pines sugeridos para pendulo

- PEND_A -> GPIO32
- PEND_B -> GPIO33
- PEND_Z opcional -> GPIO39 o sin conectar en fase inicial

### 8.4 Acondicionamiento del encoder de pendulo

Primero determinar si su salida es open-drain o push-pull:

- Open-drain: pull-up 4.7k a 3.3V
- Push-pull a 5V: divisor para limitar nivel a dominio 3.3V

### 8.5 Variables y funciones de firmware sugeridas

- pendCount
- pendCountsPerRev
- pendDir
- pendOffsetDeg
- pendFilteredVel
- getPendRawDeg()
- getPendDeg()
- zeroPendHere()

### 8.6 Plan incremental

1. Cableado y validacion electrica
2. Lectura en firmware sin control
3. Calibracion CPR y signo
4. Filtrado de velocidad
5. Activacion de modo de control dual

---

## 9. Arquitectura de firmware y GUI

### 9.1 Capas de firmware

1. HAL:
- PWM, GPIO, I2C, timers, lectura encoder

2. Estimacion:
- Conteo, conversion angular, derivadas y filtrado

3. Control:
- Modos manual, abierto, cerrado (PID), y futuro modo pendulo

4. Comunicacion:
- Endpoints de estado/comando
- Serial para diagnostico

5. Telemetria:
- Estado mecanico + electrico unificado

### 9.2 GUI Python

Funciones objetivo:

- Monitoreo en tiempo real
- Comandos de referencia y modo
- Registro CSV de corridas
- Soporte de analisis post ensayo

---

## 10. Metodologia experimental unificada

### 10.1 Fases

Fase A: infraestructura
- Energia estable
- Comunicacion estable
- Sensado basico validado

Fase B: caracterizacion del actuador
- Curva PWM vs velocidad
- Zona muerta y saturacion

Fase C: lazo de velocidad
- Ajuste progresivo de Kp, Ki, Kd

Fase D: lazo de posicion
- Escalon, rampa, perturbaciones

Fase E: telemetria energetica
- Correlacion esfuerzo-control y consumo

Fase F: integracion pendulo
- Medicion dual
- Estrategia swing-up + estabilizacion

### 10.2 Registro minimo por corrida

- Fecha
- Version de firmware
- Parametros de control
- Frecuencia de muestreo
- Tipo de referencia
- Metricas calculadas
- Observaciones cualitativas

---

## 11. Metricas de evaluacion

### 11.1 Seguimiento

- Error estacionario
- Tiempo de subida
- Tiempo de establecimiento
- Sobreimpulso maximo
- Error absoluto medio

### 11.2 Robustez

- Rechazo a perturbacion
- Sensibilidad a variacion de carga
- Repetibilidad entre corridas

### 11.3 Energia

- Corriente promedio y pico
- Potencia promedio
- Energia por maniobra o ciclo

### 11.4 Calidad de instrumentacion

- Perdida de muestras
- Jitter efectivo
- Coherencia mecanica/electrica

---

## 12. Riesgos tecnicos y mitigaciones

1. Ruido electromagnetico
- Mitigacion: desacoplo, grounding correcto, filtrado

2. Lectura inestable de encoder
- Mitigacion: condicionamiento correcto segun topologia de salida

3. Saturacion termica del driver
- Mitigacion: limites de duty y gestion termica

4. Inestabilidad por sintonizacion
- Mitigacion: ajuste incremental y protecciones

5. Sobrecarga de CPU con doble encoder
- Mitigacion: migracion a PCNT

6. Latencia de interfaz
- Mitigacion: lazo de control local en ESP32

---

## 13. Costos y viabilidad

### 13.1 Estimacion de costo

- ESP32-WROOM-32: 6-10 USD
- LM2596: 1-3 USD
- INA219: 2-4 USD
- L298N: 1.5-3 USD
- Motor + encoder: 15-30 USD

Subtotal sin fuente: 25.5-50 USD  
Total estimado con fuente/bateria y extras: 45-80 USD

### 13.2 Comparacion cualitativa con plataforma comercial

- Costo drasticamente menor
- Mayor libertad de personalizacion
- Menor integracion de fabrica
- Mayor carga de ingenieria experimental

---

## 14. Hoja de ruta recomendada para tesis

Etapa 1: consolidar base servo
- Estabilidad de posicion/velocidad
- Pipeline de datos estable

Etapa 2: identificacion de parametros
- Modelo simplificado calibrado con datos reales

Etapa 3: integracion del pendulo
- Doble medicion angular validada

Etapa 4: control avanzado
- Estrategia de swing-up + estabilizacion

Etapa 5: cierre academico
- Comparativa contra literatura
- Anexos de reproducibilidad

---

## 15. Criterios de exito

Se considera cumplido el objetivo de modernizacion si se verifica:

- Control de posicion repetible con error acotado
- Telemetria mecanica y energetica estable
- Operacion continua sin fallas criticas en sesion
- Documentacion suficiente para replicacion por terceros
- Relacion costo/beneficio favorable

---

## 16. Conclusiones finales

1. La arquitectura es tecnicamente viable para docencia e investigacion aplicada.
2. La combinacion completa en abierto representa oportunidad de contribucion original.
3. El mayor riesgo no es la disponibilidad de componentes, sino la calidad de integracion electrica y metodologica.
4. El HW-FIX-1 (encoder open-drain con pull-up correcto) fue un hito tecnico clave para estabilidad del lazo.
5. El siguiente salto de valor es integrar formalmente el encoder del pendulo con backend robusto y protocolo experimental uniforme.

---

## 17. Referencias base consolidadas

- Repositorios tecnicos de control y pendulo rotatorio ya identificados en la investigacion previa.
- Datasheets de LM2596, INA219, L298N y ESP32.
- Literatura academica de rotary inverted pendulum para modelado y control.

Nota metodologica: este documento consolida evidencia disponible y evita inventar resultados no medidos. Cualquier valor de desempeno final debe derivarse de corridas registradas y auditables.
