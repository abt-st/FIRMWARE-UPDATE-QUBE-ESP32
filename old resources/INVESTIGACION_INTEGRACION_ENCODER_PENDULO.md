# Investigacion: Integracion del Encoder del Pendulo en QUBE Servo (ESP32)

**Fecha:** 2026-05-07  
**Contexto:** La plataforma actualmente lee el encoder del motor (base) y falta incorporar el encoder del pendulo para control completo tipo rotary inverted pendulum.

---

## 1) Estado Actual del Sistema

Firmware actual:
- Control motor por L298N (GPIO26/GPIO27).
- Encoder motor en cuadratura A/B (GPIO34/GPIO35).
- INA219 por I2C (GPIO21/GPIO22).
- Decodificacion de encoder por polling LUT (X4), periodo de control 200 Hz.

Hallazgo clave para el pendulo:
- El conjunto Premotec reporta dos conectores de encoder: uno para base y otro para pendulo (A, B, GND, VCC, Index).
- El pendulo aun no entra al lazo de control.

Implicacion:
- Sin angulo de pendulo no es posible implementar swing-up + estabilizacion vertical de forma robusta.

---

## 2) Objetivo Tecnico

Agregar un segundo canal de encoder cuadratura (pendulo) con:
- Lectura confiable de angulo absoluto relativo.
- Derivada angular filtrada para control.
- Carga de CPU baja y latencia predecible.
- Compatibilidad electrica con ESP32 (3.3 V logica).

---

## 3) Recomendacion de Arquitectura (Prioridad)

## Opcion A (recomendada): Dual encoder con hardware PCNT en ESP32

Descripcion:
- Encoder base y encoder pendulo decodificados por perifero PCNT (contador de pulsos).
- El loop de control solo lee contadores atomicos y calcula angulos/velocidades.

Ventajas:
- Menor jitter que polling puro.
- Menor uso de CPU en comparacion con ISR por flanco para ambos encoders.
- Escalable para frecuencias de borde mas altas.

Riesgos:
- Requiere refactor de la capa de lectura de encoder.
- Configuracion de PCNT cuadratura debe probarse con ruido real.

## Opcion B (intermedia): Mantener polling para base + ISR para pendulo

Descripcion:
- Base sigue como esta.
- Pendulo se agrega con ISR en dos pines y LUT cuadratura.

Ventajas:
- Cambios minimos al firmware existente.

Riesgos:
- Mas carga de CPU y mayor sensibilidad a jitter cuando ambos encoders esten activos.

## Opcion C (no recomendada para objetivo final): polling para ambos encoders

Descripcion:
- Duplicar la logica de polling LUT para base y pendulo.

Riesgos:
- Probabilidad alta de perder transiciones a mayor velocidad.
- Precision de velocidad angular del pendulo degradada.

---

## 4) Propuesta de Pines para Encoder del Pendulo

Pines actuales ocupados:
- GPIO34/GPIO35: encoder base A/B.
- GPIO26/GPIO27: motor.
- GPIO21/GPIO22: I2C.

Asignacion sugerida para pendulo:
- PEND_A -> GPIO32
- PEND_B -> GPIO33
- PEND_Z (index, opcional) -> GPIO39 (solo entrada) o dejar sin conectar en Fase 1

Justificacion:
- GPIO32/33 son estables para entrada digital y faciles de rutear en devkits.
- Evitar pines de arranque (0, 2, 12, 15) para no introducir problemas de boot.

---

## 5) Acondicionamiento Electrico Recomendado

Primero identificar tipo de salida del encoder del pendulo (open-drain o push-pull).

Regla practica:
- Si en estado alto sin carga la linea no sube de forma firme -> open-drain.
- Si entrega alto activo claramente (cercano a VCC encoder) -> push-pull.

### Caso 1: Open-drain (muy probable por experiencia en este proyecto)

Topologia por canal (A y B):

3V3 ESP32 -> 4.7k ohm -> nodo senal -> GPIO32/33
                              |
                         salida encoder (NPN open-drain)
                              |
                             GND comun

Notas:
- No usar divisor a GND para open-drain (puede colapsar el nivel alto).
- Mantener GND comun unico (estrella) para reducir ruido.

### Caso 2: Push-pull a 5V

Topologia por canal:
- Divisor resistivo (ej. 4.7k serie + 8.2k a GND en nodo) para limitar a ~3.2 V.

Notas:
- ESP32 no es 5V tolerante en GPIO.

### Filtro RC recomendado (si hay ruido)

Por canal, cerca del ESP32:
- R serie 100 ohm
- C a GND 10 nF
- Frecuencia de corte aproximada: 159 kHz

---

## 6) Modelo de Senal y Variables Nuevas de Firmware

Agregar estado del encoder pendulo:
- volatile long pendCount
- float pendCountsPerRev
- int pendDir
- float pendOffsetDeg
- float pendFilteredVel

Funciones nuevas:
- getPendRawDeg()
- getPendDeg()
- zeroPendHere()
- updatePendEncoder() o backend PCNT

Convenciones de angulo recomendadas:
- 0 deg: pendulo colgando hacia abajo (o vertical arriba, pero elegir una y mantener).
- Rango mostrado: [-180, +180] para control y telemetria.

Normalizacion angular:
- Aplicar wrap para evitar saltos numericos al cruzar +/-180.

---

## 7) Estrategia de Control para Integrar el Pendulo

Fase 1: Medicion y telemetria
- Incorporar lectura del pendulo sin cambiar el controlador actual.
- Publicar en serial/JSON: pend_deg, pend_vel_dps, pend_cnt.

Fase 2: Seguridad y validacion
- Limites de angulo para corte de motor (ej. si pendulo excede umbral mecanico).
- Verificar coherencia de signo (pendDir) con movimiento real.

Fase 3: Control dual
- Mantener lazo de posicion base.
- Agregar controlador de pendulo:
  - Swing-up energetico cuando lejos del equilibrio.
  - Estabilizacion (LQR o PID acoplado) cerca del equilibrio.

---

## 8) Plan de Implementacion en 5 Pasos

1. Cableado y validacion electrica
- Conectar PEND_A/PEND_B a GPIO32/GPIO33 con topologia correcta (pull-up o divisor segun tipo).
- Confirmar niveles logicos con multimetro/osciloscopio.

2. Lectura en firmware (sin control)
- Implementar contador de pendulo y conversion a grados.
- Exponer valores por serial y HTTP /state.

3. Calibracion
- Medir CPR real del pendulo.
- Ajustar pendCountsPerRev y pendDir.
- Definir referencia de cero con comando nuevo (ej. rz para zero pendulo).

4. Filtrado y velocidad
- Implementar derivada + filtro EMA para pend_vel.
- Validar ruido a 200 Hz.

5. Integracion de control
- Agregar modo m3 para pruebas de swing-up/estabilizacion.
- Mantener fallback a m2 (base-only) para pruebas seguras.

---

## 9) Checklist de Validacion

Electrico:
- [ ] Nivel alto estable > 2.6 V en GPIO del ESP32.
- [ ] Nivel bajo < 0.4 V.
- [ ] No hay picos > 3.3 V en pines ESP32.

Firmware:
- [ ] pend_cnt cambia monotonicamente al mover pendulo.
- [ ] pend_deg recorre rango esperado sin saltos espurios.
- [ ] pend_vel no presenta ruido excesivo en reposo.

Control:
- [ ] El sistema puede operar en modo base-only sin regresiones.
- [ ] El nuevo modo con pendulo no rompe telemetria ni comandos existentes.

---

## 10) Riesgos y Mitigaciones

Riesgo 1: Tipo de salida del encoder mal identificado
- Mitigacion: prueba A/B con pull-up temporal y medicion de nivel alto real.

Riesgo 2: Ruido por cableado largo
- Mitigacion: par trenzado para A/GND y B/GND, RC minimo, star-ground.

Riesgo 3: Sobrecarga de CPU con dos encoders
- Mitigacion: migrar a PCNT para ambos canales.

Riesgo 4: Signo invertido de angulo/velocidad
- Mitigacion: parametro runtime pendDir = +/-1 y prueba de sentido.

---

## 11) Recomendacion Final

Implementar el encoder del pendulo con enfoque incremental:
- Empezar por Fase 1 (medicion + telemetria).
- Confirmar capa electrica y CPR real.
- Migrar a backend PCNT para robustez.
- Despues activar estrategia swing-up + estabilizacion.

Esto minimiza riesgo de regresion y prepara la base para control de pendulo invertido completo.
