// ============================================================
// QUBE Servo - Firmware base oficial
// Arquitectura: ESP32 + L298N + INA219 + LM2596 + CD40106BE Schmitt Trigger
// Fecha: 2026-05-28
// ============================================================
// Topologia de potencia y logica:
// 1) Fuente principal (12V-15V) -> INA219 (serie) -> L298N VS
// 2) Fuente principal -> LM2596 -> 5V para logica auxiliar
// 3) Encoder servo (open-drain 5V) -> pull-up 4.7kΩ a 3.3V
//    -> Schmitt Trigger CD40106BE (doble inversion, Vcc=3.3V)
//    -> salida limpia ~3.3V -> ESP32 GPIO34/GPIO35
// 4) INA219 en I2C para telemetria de voltaje, corriente y potencia
// 5) GND comun entre potencia y logica (topologia estrella)
//
// Pines recomendados:
// Opcion A (PWM en ENA):
// L298N ENA -> GPIO25 (PWM)
// L298N IN1 -> GPIO26
// L298N IN2 -> GPIO27
//
// Opcion B (sin cable ENA):
// Deja el jumper ENA habilitado en el L298N y usa PWM en IN1/IN2.
// En ese caso, ENA no se conecta al ESP32.
// L298N IN1 -> GPIO26
// L298N IN2 -> GPIO27
// Encoder servo A -> Schmitt INV_A (pin 1) -> GPIO34
// Encoder servo B -> Schmitt INV_C (pin 5) -> GPIO35
// INA219 SDA -> GPIO21
// INA219 SCL -> GPIO22
// CD40106BE Vcc -> 3.3V (pin 14), GND (pin 7), bypass 100nF
//
// Comandos Serial:
// m0, m1, m2           -> modo 0: stop, 1: PWM manual, 2: PID posicion
// p-255..255           -> PWM manual (solo en m1)
// s<grados>            -> setpoint de posicion (m2)
// kp<val>, ki<val>, kd<val>
// r                    -> reset encoder y PID
// x                    -> paro inmediato
// ?                    -> imprime estado
// wifi_ssid<TuRed>     -> configurar SSID WiFi (guarda en NVS/Preferences)
// wifi_pass<TuClave>   -> configurar password WiFi (guarda en NVS/Preferences)
// wifi_info            -> mostrar configuracion WiFi actual
//
// Endpoints HTTP:
// GET /state
// GET /cmd?m=2
// GET /cmd?s=45
// GET /cmd?p=100
// GET /cmd?x=1
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncTCP.h>
#include <Wire.h>
#include "credentials.h"
#include <SPIFFS.h>
#include <Preferences.h>
#include "driver/pcnt.h"

#if defined(__has_include)
#if __has_include(<INA219_WE.h>)
#include <INA219_WE.h>
#define HAS_INA219 1
#endif
#endif

#ifndef HAS_INA219
// Fallback: permite compilar sin la libreria INA219 instalada.
class INA219_WE {
public:
  INA219_WE(TwoWire *wire = &Wire, uint8_t addr = 0x40) {
    (void)wire;
    (void)addr;
  }
  bool init() {
    return false;
  }
  void setMeasureMode(int mode) {
    (void)mode;
  }
  float getShuntVoltage_mV() {
    return 0.0f;
  }
  float getBusVoltage_V() {
    return 0.0f;
  }
  float getCurrent_mA() {
    return 0.0f;
  }
  float getBusPower() {
    return 0.0f;
  }
};
enum INA219_MeasureMode { INA219_CONTINUOUS };
#endif

static const int PIN_ENC_A = 34;  // Encoder servo A
static const int PIN_ENC_B = 35;  // Encoder servo B
static const int PIN_PEND_A = 32;  // Encoder péndulo A
static const int PIN_PEND_B = 33;  // Encoder péndulo B

static const int PIN_ENA = 25;
static const int PIN_IN1 = 26;
static const int PIN_IN2 = 27;

// Si no puedes cablear ENA al ESP32, pon esto en false y deja el jumper ENA en el L298N.
static const bool USE_ENA_PWM = false;

static const int PIN_I2C_SDA = 21;
static const int PIN_I2C_SCL = 22;

static const int PWM_CH_ENA = 0;
static const int PWM_CH_IN1 = 1;
static const int PWM_CH_IN2 = 2;
static const int PWM_FREQ_HZ = 20000;
static const int PWM_RES_BITS = 8;

bool pwmAttachCompat(int pin, int channel) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  (void)channel;
  return ledcAttach(pin, PWM_FREQ_HZ, PWM_RES_BITS);
#else
  ledcSetup(channel, PWM_FREQ_HZ, PWM_RES_BITS);
  ledcAttachPin(pin, channel);
  return true;
#endif
}

void pwmWriteCompat(int pin, int channel, int duty) {
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
  (void)channel;
  ledcWrite(pin, duty);
#else
  (void)pin;
  ledcWrite(channel, duty);
#endif
}

float countsPerRev = 2048.0f;               // Ajustable en runtime con cpr<val>
int encoderDir = 1;                         // Ajustable en runtime con ed<1|-1>
float pendCountsPerRev = 2048.0f;           // CPR encoder péndulo
int pendulumDir = 1;                        // Dirección encoder péndulo

int mode = 0;
int lastPwmCmd = 0;
float setpoint_deg = 0.0f;
float pendulum_setpoint_deg = 0.0f;  // Setpoint para modo 3 (PID péndulo)

// PID Servo (modo 2)
float Kp = 3.0f;
float Ki = 0.5f;
float Kd = 0.15f;
float integralTerm = 0.0f;
float prevError = 0.0f;
float prevPos = 0.0f;
float filteredVel = 0.0f;
const float VEL_ALPHA = 0.12f;
float positionOffsetDeg = 0.0f;
// ── Gain Scheduling: Modo Fino vs Modo Grueso (modo 2) ──────────────────────
// Cuando |error| <= threshold -> usa gains finos (movimientos suaves)
// Cuando |error| > threshold  -> usa gains gruesos (respuesta rápida)
// Histéresis de ±hysteresis sobre el umbral para evitar chattering entre modos.
float Kp_fine = 2.0f;       // Ganancia proporcional modo fino
float Ki_fine = 0.8f;       // Ganancia integral modo fino
float Kd_fine = 0.2f;       // Ganancia derivativa modo fino
float Kp_coarse = 4.0f;     // Ganancia proporcional modo grueso
float Ki_coarse = 0.2f;     // Ganancia integral modo grueso
float Kd_coarse = 0.1f;     // Ganancia derivativa modo grueso
const float GAIN_THRESHOLD_DEG = 10.0f;  // Umbral para cambiar de modo (grados)
const float GAIN_HYSTERESIS_DEG = 2.0f;  // Histérisis sobre el umbral (grados)
int gainMode = 0;           // 0=fino, 1=grueso (estado actual, para telemetría)
bool useGainScheduling = false;  // true=activa dual-mode, false=PID clásico con gains Kp/Ki/Kd

// PID Péndulo (modo 3)
float Kp_pend = 15.0f;
float Ki_pend = 0.5f;
float Kd_pend = 2.0f;
float integralTermPend = 0.0f;
float prevErrorPend = 0.0f;
float prevPosPend = 0.0f;
float filteredVelPend = 0.0f;
const float VEL_ALPHA_PEND = 0.30f;  // Filtro velocidad péndulo (era 0.15, demasiado lento para LQR)
float pendulumOffsetDeg = 0.0f;

// LQR Péndulo Invertido (modo 4)
// Ganancias LQR: u = -(K1*theta + K2*alpha + K3*theta_dot + K4*alpha_dot)
float lqr_K1 = 1.5f;    // Ganancia posición servo (la que atrapó a 0.2°)
float lqr_K2 = 25.0f;   // Ganancia ángulo péndulo
float lqr_K3 = 1.0f;    // Ganancia velocidad servo
float lqr_K4 = 10.0f;   // Ganancia velocidad péndulo
float lqr_prevTheta = 0.0f;
float lqr_prevAlpha = 0.0f;
float lqr_filteredVelTheta = 0.0f;
float lqr_filteredVelAlpha = 0.0f;
unsigned long lqr_fallbackMs = 0;  // Timestamp para fallback automático LQR→swing-up

// Si el motor gira en direccion opuesta al encoder (feedback positivo),
// cambiar MOTOR_DIR a -1 para invertir la salida del PID.
const int MOTOR_DIR = -1;  // 1 = normal, -1 = invertido

const float INTEGRAL_LIMIT = 250.0f;
const int PWM_MIN = 12;
const int PWM_MAX = 100;

// Parametros del pendulo para calculo de energia (Quanser swing-up)
const float PEND_MASS = 0.025f;      // Masa del pendulo (kg) - ajustar
const float PEND_LENGTH = 0.065f;    // Distancia pivot-centro de masa (m) - ajustar
const float PEND_INERTIA = 0.00002f; // Momento de inercia (kg*m^2) - ajustar
const float GRAVITY = 9.81f;         // Gravedad (m/s^2)
float ke_gain = 0.5f;               // Ganancia del controlador de energia (ke) - ajustable
float balance_threshold = 12.0f;    // Umbral para cambiar a LQR (grados desde vertical) - ajustable
// Swing-up fase (modo 5)
int swingPhase = 0;              // 0=excitacion, 1=bombeo de energia
unsigned long exciteStartMs = 0;
void resetSwingUp() { swingPhase = 0; exciteStartMs = 0; }

const unsigned long CONTROL_PERIOD_US = 2000;  // 500 Hz (era 5000 = 200 Hz)
const unsigned long TELEMETRY_PERIOD_MS = 100;
const unsigned long COMMAND_TIMEOUT_MS = 10000;
const bool ENABLE_COMMAND_TIMEOUT = false;  // true para seguridad en operacion, false para ajuste en banco

unsigned long lastControlUs = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastCommandMs = 0;

// ── WiFi Configuration (stored in NVS/Preferences) ──────────────────────────
Preferences preferences;
const char* AP_SSID = "QUBE-ESP32";
const char* AP_PASS = "qube1234";
const bool ENABLE_STA = true;  // true: conecta tambien a tu router LAN
char staSsid[33] = "";         // Max 32 chars + null
char staPass[65] = "";         // Max 64 chars + null
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");
INA219_WE ina219(&Wire, 0x40);
bool inaOk = false;
uint8_t inaAddr = 0x40;
float busVoltageV = 0.0f;
float shuntVoltagemV = 0.0f;
float currentmA = 0.0f;
float powermW = 0.0f;

void scanI2CBus() {
  Serial.println("I2C scan: inicio");
  int found = 0;
  for (uint8_t addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    const uint8_t err = Wire.endTransmission();
    if (err == 0) {
      Serial.print("I2C dispositivo @ 0x");
      if (addr < 16) {
        Serial.print("0");
      }
      Serial.println(addr, HEX);
      found++;
    }
  }
  if (found == 0) {
    Serial.println("I2C scan: sin dispositivos");
  }
}

bool initIna219() {
  const uint8_t candidates[] = {0x40, 0x41, 0x44, 0x45};
  for (size_t i = 0; i < (sizeof(candidates) / sizeof(candidates[0])); i++) {
    const uint8_t addr = candidates[i];
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() != 0) {
      continue;
    }

    ina219 = INA219_WE(&Wire, addr);
    if (ina219.init()) {
      ina219.setMeasureMode(INA219_CONTINUOUS);
      inaAddr = addr;
      return true;
    }
  }
  return false;
}
// ══════════════════════════════════════════════════════════════════════════════
// PCNT (Pulse Counter) — decodificación de encoder en hardware
// Cuenta cada transición de GPIO sin intervención de CPU.
// X4 cuadratura: 4 conteos por ciclo eléctrico completo.
// ══════════════════════════════════════════════════════════════════════════════

static pcnt_unit_t pcnt_servo_unit = PCNT_UNIT_0;
static pcnt_unit_t pcnt_pendulum_unit = PCNT_UNIT_1;

void initPcntUnit(pcnt_unit_t unit, int pinA, int pinB) {
  // Channel 0: pulse=A, ctrl=B — X4 cuadratura
  pcnt_config_t ch0 = {
    .pulse_gpio_num = (gpio_num_t)pinA,
    .ctrl_gpio_num = (gpio_num_t)pinB,
    .lctrl_mode = PCNT_MODE_KEEP,    // B=0 → mantener dirección
    .hctrl_mode = PCNT_MODE_REVERSE, // B=1 → invertir dirección
    .pos_mode = PCNT_COUNT_INC,      // A↑ → +1 por defecto
    .neg_mode = PCNT_COUNT_DEC,      // A↓ → -1 por defecto
    .counter_h_lim = 32767,
    .counter_l_lim = -32768,
    .unit = unit,
    .channel = PCNT_CHANNEL_0,
  };
  pcnt_unit_config(&ch0);

  // Channel 1: pulse=B, ctrl=A — X4 cuadratura
  pcnt_config_t ch1 = {
    .pulse_gpio_num = (gpio_num_t)pinB,
    .ctrl_gpio_num = (gpio_num_t)pinA,
    .lctrl_mode = PCNT_MODE_REVERSE, // A=0 → invertir dirección
    .hctrl_mode = PCNT_MODE_KEEP,    // A=1 → mantener dirección
    .pos_mode = PCNT_COUNT_INC,      // B↑ → +1 por defecto
    .neg_mode = PCNT_COUNT_DEC,      // B↓ → -1 por defecto
    .counter_h_lim = 32767,
    .counter_l_lim = -32768,
    .unit = unit,
    .channel = PCNT_CHANNEL_1,
  };
  pcnt_unit_config(&ch1);

  pcnt_counter_pause(unit);
  pcnt_counter_clear(unit);
  pcnt_counter_resume(unit);
}

long readPcnt(pcnt_unit_t unit) {
  int16_t count = 0;
  pcnt_get_counter_value(unit, &count);
  return (long)count;
}

void resetPcnt(pcnt_unit_t unit) {
  pcnt_counter_pause(unit);
  pcnt_counter_clear(unit);
  pcnt_counter_resume(unit);
}

long getPendulumCountAtomic() {
  return readPcnt(pcnt_pendulum_unit);
}

float getPendulumDegPerCount() {
  if (pendCountsPerRev < 1.0f) {
    pendCountsPerRev = 1.0f;
  }
  return 360.0f / pendCountsPerRev;
}

float getPendulumRawPositionDeg() {
  return pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
}

float getPendulumPositionDeg() {
  return getPendulumRawPositionDeg() - pendulumOffsetDeg;
}

void zeroPendulumHere() {
  pendulumOffsetDeg = getPendulumRawPositionDeg();
}

void resetPendulumPid() {
  integralTermPend = 0.0f;
  prevErrorPend = 0.0f;
  prevPosPend = getPendulumPositionDeg();
  filteredVelPend = 0.0f;
}

void resetLqr() {
  lqr_prevTheta = getPositionDeg();
  lqr_prevAlpha = getPendulumPositionDeg();
  lqr_filteredVelTheta = 0.0f;
  lqr_filteredVelAlpha = 0.0f;
}
// Normaliza ángulo a [-180, 180]
float normalizeAngle(float deg) {
  deg = fmodf(deg, 360.0f);
  if (deg > 180.0f) deg -= 360.0f;
  else if (deg < -180.0f) deg += 360.0f;
  return deg;
}

long getEncoderCountAtomic() {
  return readPcnt(pcnt_servo_unit);
}

float getDegPerCount() {
  if (countsPerRev < 1.0f) {
    countsPerRev = 1.0f;
  }
  return 360.0f / countsPerRev;
}

float getRawPositionDeg() {
  return encoderDir * getEncoderCountAtomic() * getDegPerCount();
}

float getPositionDeg() {
  return getRawPositionDeg() - positionOffsetDeg;
}

void zeroPositionHere() {
  positionOffsetDeg = getRawPositionDeg();
}

void resetPid() {
  integralTerm = 0.0f;
  prevError = 0.0f;
  prevPos = getPositionDeg();
  filteredVel = 0.0f;
}

void setMotor(int pwmValue) {
  pwmValue = constrain(pwmValue, -255, 255);
  lastPwmCmd = pwmValue;

  if (USE_ENA_PWM) {
    if (pwmValue > 0) {
      digitalWrite(PIN_IN1, HIGH);
      digitalWrite(PIN_IN2, LOW);
      pwmWriteCompat(PIN_ENA, PWM_CH_ENA, pwmValue);
      return;
    }

    if (pwmValue < 0) {
      digitalWrite(PIN_IN1, LOW);
      digitalWrite(PIN_IN2, HIGH);
      pwmWriteCompat(PIN_ENA, PWM_CH_ENA, -pwmValue);
      return;
    }

    digitalWrite(PIN_IN1, LOW);
    digitalWrite(PIN_IN2, LOW);
    pwmWriteCompat(PIN_ENA, PWM_CH_ENA, 0);
    return;
  }

  if (pwmValue > 0) {
    pwmWriteCompat(PIN_IN1, PWM_CH_IN1, pwmValue);
    pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 0);
    return;
  }

  if (pwmValue < 0) {
    pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 0);
    pwmWriteCompat(PIN_IN2, PWM_CH_IN2, -pwmValue);
    return;
  }

  pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 0);
  pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 0);
}

void safeStop() {
  mode = 0;
  resetPid();
  resetPendulumPid();
  resetLqr();
  setMotor(0);
}

void updateIna219() {
  if (!inaOk) {
    return;
  }
  shuntVoltagemV = ina219.getShuntVoltage_mV();
  busVoltageV = ina219.getBusVoltage_V();
  currentmA = ina219.getCurrent_mA();
  powermW = ina219.getBusPower();
}

String getStateJson() {
  updateIna219();
  // Servo encoder
  const long c = getEncoderCountAtomic();
  const int encA = digitalRead(PIN_ENC_A);
  const int encB = digitalRead(PIN_ENC_B);
  const float rawPos = encoderDir * c * getDegPerCount();
  const float pos = rawPos - positionOffsetDeg;
  const float err = setpoint_deg - pos;

  // Pendulum encoder
  const long pc = getPendulumCountAtomic();
  const float rawPendPos = pendulumDir * pc * getPendulumDegPerCount();
  const float pendPos = rawPendPos - pendulumOffsetDeg;
  const float pendErr = pendulum_setpoint_deg - pendPos;

  String json = "{";
  json += "\"mode\":" + String(mode) + ",";
  // Servo
  json += "\"count\":" + String(c) + ",";
  json += "\"enc_a\":" + String(encA) + ",";
  json += "\"enc_b\":" + String(encB) + ",";
  json += "\"encoder_dir\":" + String(encoderDir) + ",";
  json += "\"counts_per_rev\":" + String(countsPerRev, 3) + ",";
  json += "\"raw_position_deg\":" + String(rawPos, 3) + ",";
  json += "\"position_deg\":" + String(pos, 3) + ",";
  json += "\"offset_deg\":" + String(positionOffsetDeg, 3) + ",";
  json += "\"setpoint_deg\":" + String(setpoint_deg, 3) + ",";
  json += "\"error_deg\":" + String(err, 3) + ",";
  // Pendulum
  json += "\"pend_count\":" + String(pc) + ",";
  json += "\"pend_raw_position_deg\":" + String(rawPendPos, 3) + ",";
  json += "\"pend_position_deg\":" + String(pendPos, 3) + ",";
  json += "\"pend_offset_deg\":" + String(pendulumOffsetDeg, 3) + ",";
  json += "\"pend_setpoint_deg\":" + String(pendulum_setpoint_deg, 3) + ",";
  json += "\"pend_error_deg\":" + String(pendErr, 3) + ",";
  // Motor & power
  json += "\"pwm\":" + String(lastPwmCmd) + ",";
  json += "\"gain_scheduling\":" + String(useGainScheduling ? "true" : "false") + ",";
  json += "\"gain_mode\":" + String(gainMode) + ",";
  json += "\"ina_ok\":" + String(inaOk ? "true" : "false") + ",";
  json += "\"v_bus\":" + String(busVoltageV, 3) + ",";
  json += "\"v_shunt_mv\":" + String(shuntVoltagemV, 3) + ",";
  json += "\"i_ma\":" + String(currentmA, 3) + ",";
  json += "\"p_mw\":" + String(powermW, 3);
  json += "}";
  return json;
}

void handleOptions(AsyncWebServerRequest *request) {
  AsyncWebServerResponse *response = request->beginResponse(204);
  response->addHeader("Access-Control-Allow-Origin", "*");
  response->addHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  response->addHeader("Access-Control-Allow-Headers", "*");
  request->send(response);
}


void handleState(AsyncWebServerRequest *request) {
  request->send(200, "application/json", getStateJson());
}

void handleCmd(AsyncWebServerRequest *request) {
  if (request->hasParam("m")) {
    const int m = request->getParam("m")->value().toInt();
    if (m >= 0 && m <= 5) {
      mode = m;
      resetPid();
      resetPendulumPid();
      if (mode == 4) resetLqr();
      if (mode == 5) resetSwingUp();
      if (mode == 0) setMotor(0);
      lastCommandMs = millis();
    }
  }

  if (request->hasParam("s")) {
    setpoint_deg = request->getParam("s")->value().toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("sp")) {
    pendulum_setpoint_deg = request->getParam("sp")->value().toFloat();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("z")) {
    zeroPositionHere();
    setpoint_deg = 0.0f;
    resetPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("zp")) {
    zeroPendulumHere();
    pendulum_setpoint_deg = 0.0f;
    resetPendulumPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("o")) {
    positionOffsetDeg = request->getParam("o")->value().toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("op")) {
    pendulumOffsetDeg = request->getParam("op")->value().toFloat();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("ed")) {
    const int v = request->getParam("ed")->value().toInt();
    encoderDir = (v >= 0) ? 1 : -1;
    resetPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("edp")) {
    const int v = request->getParam("edp")->value().toInt();
    pendulumDir = (v >= 0) ? 1 : -1;
    resetPendulumPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("cpr")) {
    const float v = request->getParam("cpr")->value().toFloat();
    if (v >= 1.0f) {
      countsPerRev = v;
      resetPid();
      lastCommandMs = millis();
    }
  }

  if (request->hasParam("cprp")) {
    const float v = request->getParam("cprp")->value().toFloat();
    if (v >= 1.0f) {
      pendCountsPerRev = v;
      resetPendulumPid();
      lastCommandMs = millis();
    }
  }

  if (request->hasParam("wifi_ssid")) {
    const String ssid = request->getParam("wifi_ssid")->value();
    if (ssid.length() > 0 && ssid.length() < 33) {
      saveWifiCredentials(ssid.c_str(), staPass);
    }
    lastCommandMs = millis();
  }
  if (request->hasParam("wifi_pass")) {
    const String pass = request->getParam("wifi_pass")->value();
    if (pass.length() >= 8) {
      saveWifiCredentials(staSsid, pass.c_str());
    }
    lastCommandMs = millis();
  }
  if (request->hasParam("wifi_reconnect")) {
    WiFi.disconnect();
    delay(100);
    connectStaIfConfigured();
    lastCommandMs = millis();
  }

  if (request->hasParam("p") && mode == 1) {
    const int pwm = constrain(request->getParam("p")->value().toInt(), -255, 255);
    setMotor(pwm);
    lastCommandMs = millis();
  }

  if (request->hasParam("x")) {
    safeStop();
    lastCommandMs = millis();
  }

  if (request->hasParam("r")) {
    resetPcnt(pcnt_servo_unit);
    resetPcnt(pcnt_pendulum_unit);
    positionOffsetDeg = 0.0f;
    pendulumOffsetDeg = 0.0f;
    setpoint_deg = 0.0f;
    pendulum_setpoint_deg = 0.0f;
    resetPid();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("kp")) {
    Kp = request->getParam("kp")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("ki")) {
    Ki = request->getParam("ki")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kd")) {
    Kd = request->getParam("kd")->value().toFloat();
    resetPid();
  }

  if (request->hasParam("kpp")) {
    Kp_pend = request->getParam("kpp")->value().toFloat();
    resetPendulumPid();
  }
  if (request->hasParam("kip")) {
    Ki_pend = request->getParam("kip")->value().toFloat();
    resetPendulumPid();
  }
  if (request->hasParam("kdp")) {
    Kd_pend = request->getParam("kdp")->value().toFloat();
    resetPendulumPid();
  }

  if (request->hasParam("lqr1")) {
    lqr_K1 = request->getParam("lqr1")->value().toFloat();
    resetLqr();
  }
  if (request->hasParam("lqr2")) {
    lqr_K2 = request->getParam("lqr2")->value().toFloat();
    resetLqr();
  }
  if (request->hasParam("lqr3")) {
    lqr_K3 = request->getParam("lqr3")->value().toFloat();
    resetLqr();
  }
  if (request->hasParam("lqr4")) {
    lqr_K4 = request->getParam("lqr4")->value().toFloat();
    resetLqr();
  }

  if (request->hasParam("ke")) {
    ke_gain = request->getParam("ke")->value().toFloat();
  }
  if (request->hasParam("bt")) {
    balance_threshold = request->getParam("bt")->value().toFloat();
  }

  if (request->hasParam("gs")) {
    useGainScheduling = (request->getParam("gs")->value().toInt() != 0);
    gainMode = 0;
    resetPid();
  }
  if (request->hasParam("kpf")) {
    Kp_fine = request->getParam("kpf")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kif")) {
    Ki_fine = request->getParam("kif")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kdf")) {
    Kd_fine = request->getParam("kdf")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kpc")) {
    Kp_coarse = request->getParam("kpc")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kic")) {
    Ki_coarse = request->getParam("kic")->value().toFloat();
    resetPid();
  }
  if (request->hasParam("kdc")) {
    Kd_coarse = request->getParam("kdc")->value().toFloat();
    resetPid();
  }

  request->send(200, "application/json", getStateJson());
}

void connectStaIfConfigured() {
  if (!ENABLE_STA) {
    return;
  }

  if (staSsid[0] == '\0') {
    Serial.println("STA: deshabilitado (sin credenciales)");
    return;
  }

  Serial.print("STA: conectando a ");
  Serial.println(staSsid);
  IPAddress local_IP(192, 168, 100, 50);
  IPAddress gateway(192, 168, 100, 1);
  IPAddress subnet(255, 255, 255, 0);
  WiFi.config(local_IP, gateway, subnet);
  WiFi.begin(staSsid, staPass);
  // No bloquear: WiFi.begin() conecta en background
  // La IP se mostrara en printNetworkInfo() cuando este listo
}

// ── WiFi credential management (NVS/Preferences) ────────────────────────────

void loadWifiCredentials() {
  preferences.begin("qube-wifi", true);  // Read-only
  preferences.getString("ssid", staSsid, sizeof(staSsid));
  preferences.getString("pass", staPass, sizeof(staPass));
  preferences.end();
  
  // Si NVS está vacío, usar credenciales por defecto de credentials.h
  if (staSsid[0] == '\0') {
    strncpy(staSsid, DEFAULT_STA_SSID, sizeof(staSsid) - 1);
    staSsid[sizeof(staSsid) - 1] = '\0';
    strncpy(staPass, DEFAULT_STA_PASS, sizeof(staPass) - 1);
    staPass[sizeof(staPass) - 1] = '\0';
    Serial.println("WiFi: usando credenciales por defecto de credentials.h");
  } else {
    Serial.print("WiFi: SSID cargado desde NVS: ");
    Serial.println(staSsid);
  }
}

void saveWifiCredentials(const char* ssid, const char* pass) {
  preferences.begin("qube-wifi", false);  // Read-write
  preferences.putString("ssid", ssid);
  preferences.putString("pass", pass);
  preferences.end();
  
  // Update runtime variables
  strncpy(staSsid, ssid, sizeof(staSsid) - 1);
  staSsid[sizeof(staSsid) - 1] = '\0';
  strncpy(staPass, pass, sizeof(staPass) - 1);
  staPass[sizeof(staPass) - 1] = '\0';
  
  Serial.print("WiFi: Credenciales guardadas. SSID=");
  Serial.println(staSsid);
  Serial.println("WiFi: Reiniciar para conectar con nuevas credenciales");
}

void printWifiInfo() {
  Serial.println("=== WiFi Configuration ===");
  Serial.print("AP SSID: ");
  Serial.println(AP_SSID);
  Serial.print("AP IP:   ");
  Serial.println(WiFi.softAPIP());
  Serial.print("STA SSID: ");
  Serial.println(staSsid[0] != '\0' ? staSsid : "(no configurado)");
  Serial.print("STA PASS: ");
  Serial.println(staPass[0] != '\0' ? "****" : "(no configurado)");
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("LAN IP:  ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("LAN: no conectado");
  }
  Serial.println("==========================");
}

void printNetworkInfo() {
  Serial.println("=== RED WiFi ===");
  Serial.print("AP SSID: ");
  Serial.println(AP_SSID);
  Serial.print("AP IP:   ");
  Serial.println(WiFi.softAPIP());
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("LAN SSID:");
    Serial.println(WiFi.SSID());
    Serial.print("LAN IP:  ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("LAN: no conectado");
  }
  Serial.println("===============");
}

void printHelp() {
  Serial.println("=== Comandos QUBE ESP32 ===");
  Serial.println("Modos: m0(stop) m1(PWM) m2(PID servo) m3(PID pendulo) m4(LQR) m5(Swing-up)");
  Serial.println("Servo: s<deg>, kp<val>, ki<val>, kd<val>, o<deg>, z, ed<1|-1>, cpr<val>");
  Serial.println("Pendulo: sp<deg>, kpp<val>, kip<val>, kdp<val>, op<deg>, zp, edp<1|-1>, cprp<val>");
  Serial.println("LQR: lqr1<val>, lqr2<val>, lqr3<val>, lqr4<val>");
  Serial.println("GainSched: g1(on) g0(off) gf<val> gi<val> gd<val> (fino) GC<val> GI<val> Gd<val> (grueso)");
  Serial.println("Motor: p-255..255 (modo 1), x(stop), r(reset)");
  Serial.println("Info: ?(estado), i(IP), n(ina scan)");
  Serial.println("WiFi: wifi_ssid<TuRed>, wifi_pass<TuClave>, wifi_info");
}

void processSerialCommand() {
  const String raw = Serial.readStringUntil('\n');
  String cmd = raw;
  cmd.trim();
  if (cmd.length() == 0) {
    return;
  }

  const char c = cmd.charAt(0);
  switch (c) {
    case 'm':
      {
        const int m = cmd.substring(1).toInt();
        if (m >= 0 && m <= 5) {
          mode = m;
          resetPid();
          resetPendulumPid();
          if (mode == 4) resetLqr();
          if (mode == 0) setMotor(0);
          lastCommandMs = millis();
        }
        break;
      }

    case 'p':
      {
        if (mode == 1) {
          const int pwm = constrain(cmd.substring(1).toInt(), -255, 255);
          setMotor(pwm);
          lastCommandMs = millis();
        }
        break;
      }

    case 's':
      {
        if (cmd.length() > 2 && cmd.charAt(1) == 'p') {
          // sp<deg> — pendulum setpoint
          pendulum_setpoint_deg = cmd.substring(2).toFloat();
          resetPendulumPid();
        } else {
          // s<deg> — servo setpoint
          setpoint_deg = cmd.substring(1).toFloat();
          resetPid();
        }
        lastCommandMs = millis();
        break;
      }

    case 'k':
      {
        if (cmd.length() > 2) {
          const char param = cmd.charAt(1);
          const float val = cmd.substring(2).toFloat();
          if (param == 'p') {
            Kp = val;
          } else if (param == 'i') {
            Ki = val;
          } else if (param == 'd') {
            Kd = val;
          }
          resetPid();
        }
        lastCommandMs = millis();
        break;
      }

    case 'r':
      {
        resetPcnt(pcnt_servo_unit);
        resetPcnt(pcnt_pendulum_unit);
        positionOffsetDeg = 0.0f;
        pendulumOffsetDeg = 0.0f;
        setpoint_deg = 0.0f;
        pendulum_setpoint_deg = 0.0f;
        resetPid();
        resetPendulumPid();
        lastCommandMs = millis();
        break;
      }

    case 'o':
      {
        positionOffsetDeg = cmd.substring(1).toFloat();
        resetPid();
        lastCommandMs = millis();
        break;
      }

    case 'e':
      {
        if (cmd.length() > 2 && cmd.charAt(1) == 'd') {
          const int v = cmd.substring(2).toInt();
          encoderDir = (v >= 0) ? 1 : -1;
          resetPid();
          lastCommandMs = millis();
        }
        break;
      }

    case 'c':
      {
        if (cmd.length() > 3 && cmd.charAt(1) == 'p' && cmd.charAt(2) == 'r') {
          const float v = cmd.substring(3).toFloat();
          if (v >= 1.0f) {
            countsPerRev = v;
            resetPid();
            lastCommandMs = millis();
          }
        }
        break;
      }
    // ── Gain Scheduling: g0=off, g1=on, gf<val>=Kp_fine, gi<val>=Ki_fine,
    //    gd<val>=Kd_fine, GC<val>=Kp_coarse, GI<val>=Ki_coarse, Gd<val>=Kd_coarse ──
    case 'g':
      {
        if (cmd.length() > 1) {
          const char sub = cmd.charAt(1);
          if (sub == '0' || sub == '1') {
            useGainScheduling = (sub == '1');
            gainMode = 0;
            resetPid();
          } else if (cmd.length() > 2) {
            const float val = cmd.substring(2).toFloat();
            if (sub == 'f') Kp_fine = val;
            else if (sub == 'i') Ki_fine = val;
            else if (sub == 'd') Kd_fine = val;
            else if (sub == 'C') Kp_coarse = val;
            else if (sub == 'I') Ki_coarse = val;
            else if (sub == 'D') Kd_coarse = val;
            resetPid();
          }
        }
        lastCommandMs = millis();
        break;
      }

    case 'z':
      {
        zeroPositionHere();
        setpoint_deg = 0.0f;
        resetPid();
        lastCommandMs = millis();
        break;
      }

    case 'x':
      {
        safeStop();
        lastCommandMs = millis();
        break;
      }

    case '?':
      {
        Serial.println(getStateJson());
        break;
      }

    case 'i':
      {
        printNetworkInfo();
        break;
      }

    case 'n':
      {
        scanI2CBus();
        inaOk = initIna219();
        Serial.print("INA219: ");
        if (inaOk) {
          Serial.print("OK @ 0x");
          if (inaAddr < 16) {
            Serial.print("0");
          }
          Serial.println(inaAddr, HEX);
        } else {
          Serial.println("NO DETECTADO");
        }
        break;
      }

    case 'w':
      {
        // WiFi commands: wifi_ssid, wifi_pass, wifi_info
        if (cmd.length() > 9 && cmd.startsWith("wifi_ssid")) {
          const String ssid = cmd.substring(9);
          if (ssid.length() > 0 && ssid.length() < 33) {
            saveWifiCredentials(ssid.c_str(), staPass);
          } else {
            Serial.println("Error: SSID debe tener 1-32 caracteres");
          }
        } else if (cmd.length() > 9 && cmd.startsWith("wifi_pass")) {
          const String pass = cmd.substring(9);
          if (pass.length() >= 8) {
            saveWifiCredentials(staSsid, pass.c_str());
          } else {
            Serial.println("Error: Password debe tener al menos 8 caracteres");
          }
        } else if (cmd == "wifi_info") {
          printWifiInfo();
        } else {
          Serial.println("Comandos WiFi: wifi_ssid<TuRed>, wifi_pass<TuClave>, wifi_info");
        }
        break;
      }

    case 'h':
      {
        printHelp();
        break;
      }

    default:
      {
        printHelp();
        break;
      }
  }
}
// ── WebSocket Event Handler ─────────────────────────────────────────────────
void onWsEvent(AsyncWebSocket *server, AsyncWebSocketClient *client,
               AwsEventType type, void *arg, uint8_t *data, size_t len) {
  switch (type) {
    case WS_EVT_CONNECT:
      Serial.printf("[WS] Cliente conectado #%u desde %s\n", client->id(),
                    client->remoteIP().toString().c_str());
      break;
    case WS_EVT_DISCONNECT:
      Serial.printf("[WS] Cliente #%u desconectado\n", client->id());
      break;
    case WS_EVT_DATA:
      break;
    case WS_EVT_PONG:
    case WS_EVT_ERROR:
      break;
  }
}

void broadcastTelemetry() {
  if (ws.count() == 0) return;
  ws.textAll(getStateJson());
}

void setup() {
  Serial.begin(115200);

  pinMode(PIN_IN1, OUTPUT);
  pinMode(PIN_IN2, OUTPUT);

  if (USE_ENA_PWM) {
    pwmAttachCompat(PIN_ENA, PWM_CH_ENA);
  } else {
    pwmAttachCompat(PIN_IN1, PWM_CH_IN1);
    pwmAttachCompat(PIN_IN2, PWM_CH_IN2);
  }

  setMotor(0);

  // Encoder servo: PCNT en hardware (X4 cuadratura)
  initPcntUnit(pcnt_servo_unit, PIN_ENC_A, PIN_ENC_B);

  // Encoder péndulo: PCNT en hardware (X4 cuadratura)
  initPcntUnit(pcnt_pendulum_unit, PIN_PEND_A, PIN_PEND_B);

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  delay(50);
  scanI2CBus();
  inaOk = initIna219();
  // Initialize SPIFFS for web GUI
  if (!SPIFFS.begin(true)) {
    Serial.println("[SPIFFS] Error al montar");
  } else {
    Serial.println("[SPIFFS] OK");
  }


  // Load WiFi credentials from NVS
  loadWifiCredentials();

  WiFi.mode(ENABLE_STA ? WIFI_AP_STA : WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS, 6, false, 4);  // canal 6, SSID visible, max 4 clientes
  connectStaIfConfigured();

  ws.onEvent(onWsEvent);
  server.addHandler(&ws);
  server.on("/", HTTP_GET, [](AsyncWebServerRequest *request){
    request->send(SPIFFS, "/index.html", "text/html");
  });
  server.on("/state", HTTP_GET, handleState);
  server.on("/cmd", HTTP_GET, handleCmd);
  server.on("/state", HTTP_OPTIONS, handleOptions);
  server.on("/cmd", HTTP_OPTIONS, handleOptions);
  server.begin();

  lastControlUs = micros();
  lastTelemetryMs = millis();
  lastCommandMs = millis();

  Serial.println("=== QUBE ESP32 + L298N + INA219 ===");
  Serial.print("AP: ");
  Serial.println(AP_SSID);
  Serial.print("IP: ");
  Serial.println(WiFi.softAPIP());
  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("IP LAN: ");
    Serial.println(WiFi.localIP());
  }
  Serial.print("INA219: ");
  if (inaOk) {
    Serial.print("OK @ 0x");
    if (inaAddr < 16) {
      Serial.print("0");
    }
    Serial.println(inaAddr, HEX);
  } else {
    Serial.println("NO DETECTADO");
  }
  printHelp();
}

void loop() {
  ws.cleanupClients();


  if (Serial.available()) {
    processSerialCommand();
  }
  const unsigned long nowUs = micros();
  if ((nowUs - lastControlUs) >= CONTROL_PERIOD_US) {
    lastControlUs += CONTROL_PERIOD_US;

    const float pos = getPositionDeg();
    const float pendPos = getPendulumPositionDeg();
    const float dt = CONTROL_PERIOD_US / 1000000.0f;

    // ══════════════════════════════════════════════════════════════════════════
    // MODO 2: PID Posición Servo
    // ══════════════════════════════════════════════════════════════════════════
    if (mode == 2) {
      const float err = setpoint_deg - pos;
      const float absErr = abs(err);

      // ── Gain Scheduling: elegir gains según magnitud del error ──────────
      float Kp, Ki, Kd;
      if (useGainScheduling) {
        // Histérisis: si estamos en modo fino, solo cambiamos a grueso si err > threshold + hysteresis
        //            si estamos en modo grueso, solo cambiamos a fino si err < threshold - hysteresis
        float upperBound = GAIN_THRESHOLD_DEG + GAIN_HYSTERESIS_DEG;
        float lowerBound = GAIN_THRESHOLD_DEG - GAIN_HYSTERESIS_DEG;

        if (gainMode == 0) {
          // Actualmente en modo fino — cambiar a grueso solo si supera el límite superior
          if (absErr > upperBound) gainMode = 1;
        } else {
          // Actualmente en modo grueso — volver a fino solo si baja del límite inferior
          if (absErr < lowerBound) gainMode = 0;
        }

        if (gainMode == 0) {
          Kp = Kp_fine;   Ki = Ki_fine;   Kd = Kd_fine;
        } else {
          Kp = Kp_coarse; Ki = Ki_coarse; Kd = Kd_coarse;
        }
      } else {
        // PID clásico: usa los gains globales Kp/Ki/Kd
        Kp = ::Kp;  Ki = ::Ki;  Kd = ::Kd;
      }

      // ── Integral anti-windup ────────────────────────────────────────────
      if (absErr < 45.0f && abs(filteredVel) < 60.0f) {
        integralTerm += err * dt;
        integralTerm = constrain(integralTerm, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
      } else {
        integralTerm = 0.0f;
      }

      // ── Velocidad filtrada (EMA) ───────────────────────────────────────
      const float rawVel = -(pos - prevPos) / dt;
      filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;
      prevError = err;
      prevPos = pos;

      // ── PID output ─────────────────────────────────────────────────────
      float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
      int pwm = (int)(MOTOR_DIR * u);

      // ── Dead band ──────────────────────────────────────────────────────
      const float deadBand = useGainScheduling ? (gainMode == 0 ? 0.5f : 1.0f) : 0.8f;
      if (absErr <= deadBand) {
        pwm = 0;
      }

      // ── Kick mínimo para vencer fricción ───────────────────────────────
      if (abs(pwm) < PWM_MIN && absErr > 8.0f && abs(filteredVel) < 15.0f) {
        pwm = (pwm >= 0) ? PWM_MIN : -PWM_MIN;
      }

      // ── Limitación dinámica de PWM ─────────────────────────────────────
      int pwmLimit = PWM_MAX;
      if (useGainScheduling) {
        if (gainMode == 0) {
          // Modo fino: PWM acotado para movimientos suaves
          if (absErr < 5.0f) pwmLimit = 30;
          else if (absErr < 10.0f) pwmLimit = 50;
        } else {
          // Modo grueso: PWM libre para respuesta rápida
          if (absErr < 20.0f) pwmLimit = 80;
        }
      } else {
        // PID clásico: escalonamiento original
        if (absErr < 5.0f) pwmLimit = 35;
        else if (absErr < 10.0f) pwmLimit = 55;
        else if (absErr < 20.0f) pwmLimit = 80;
      }

      pwm = constrain(pwm, -pwmLimit, pwmLimit);
      setMotor(pwm);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MODO 3: PID Posición Péndulo
    // ══════════════════════════════════════════════════════════════════════════
    if (mode == 3) {
      const float err = pendulum_setpoint_deg - pendPos;

      if (abs(err) < 90.0f && abs(filteredVelPend) < 120.0f) {
        integralTermPend += err * dt;
        integralTermPend = constrain(integralTermPend, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
      } else {
        integralTermPend = 0.0f;
      }

      const float rawVel = -(pendPos - prevPosPend) / dt;
      filteredVelPend = VEL_ALPHA_PEND * rawVel + (1.0f - VEL_ALPHA_PEND) * filteredVelPend;
      prevErrorPend = err;
      prevPosPend = pendPos;

      float u = Kp_pend * err + Ki_pend * integralTermPend + Kd_pend * filteredVelPend;
      int pwm = (int)(MOTOR_DIR * u);

      if (abs(pwm) < PWM_MIN && abs(err) > 5.0f && abs(filteredVelPend) < 20.0f) {
        pwm = (pwm >= 0) ? PWM_MIN : -PWM_MIN;
      }
      if (abs(err) <= 0.5f) {
        pwm = 0;
      }

      int pwmLimit = PWM_MAX;
      if (abs(err) < 30.0f) pwmLimit = 120;
      if (abs(err) < 15.0f) pwmLimit = 70;
      if (abs(err) < 5.0f) pwmLimit = 40;

      pwm = constrain(pwm, -pwmLimit, pwmLimit);
      setMotor(pwm);
    }
    // ══════════════════════════════════════════════════════════════════════════
    // MODO 4: LQR Péndulo Invertido
    // ══════════════════════════════════════════════════════════════════════════
    if (mode == 4) {
      // Estado: [theta, alpha, theta_dot, alpha_dot]
      // theta = posición servo (grados)
      // alpha = ángulo péndulo normalizado, 0 = vertical arriba (invertido)
      const float theta = constrain(pos, -90.0f, 90.0f);  // Limitar servo a ±90 para evitar crash mecánico
      const float alpha_raw = pendPos;  // Crudo para cálculo de velocidad
      const float alpha = normalizeAngle(pendPos - 180.0f);  // 0=arriba, ±180=abajo

      // Velocidades con filtro EMA (usar ángulo crudo para evitar errores en wrap-around)
      const float rawVelTheta = -(theta - lqr_prevTheta) / dt;
      const float rawVelAlpha = -(alpha_raw - lqr_prevAlpha) / dt;
      lqr_filteredVelTheta = VEL_ALPHA * rawVelTheta + (1.0f - VEL_ALPHA) * lqr_filteredVelTheta;
      lqr_filteredVelAlpha = VEL_ALPHA_PEND * rawVelAlpha + (1.0f - VEL_ALPHA_PEND) * lqr_filteredVelAlpha;
      lqr_prevTheta = theta;
      lqr_prevAlpha = alpha_raw;  // Guardar crudo para siguiente velocidad

      // LQR: u = -(K1*theta + K2*alpha + K3*theta_dot + K4*alpha_dot)
      // alpha=0 es la posición vertical (invertido)
      float u = -(lqr_K1 * theta + lqr_K2 * alpha + lqr_K3 * lqr_filteredVelTheta + lqr_K4 * lqr_filteredVelAlpha);
      int pwm = (int)(MOTOR_DIR * u);

      // Protección: solo apagar motor cuando el péndulo está muy cerca del fondo
      // alpha normalizado: 0=arriba, ±180=abajo
      // |alpha|>140 = más de 40° del fondo → LQR puede intentar atrapar
      if (abs(alpha) > 140.0f) {
        pwm = 0;
      }

      // Fallback automático: si el péndulo cayó lejos de la vertical por >2s,
      // volver a swing-up para reintentar
      if (abs(alpha) > 90.0f) {
        if (lqr_fallbackMs == 0) lqr_fallbackMs = millis();
        if (millis() - lqr_fallbackMs > 2000) {
          mode = 5;
          resetSwingUp();
          lqr_fallbackMs = 0;
          Serial.println("LQR: Fallback a swing-up (péndulo lejos de vertical)");
        }
      } else {
        lqr_fallbackMs = 0;  // Reset timer if pendulum comes back near upright
      }

      // Hard stop: si el servo se desborda, forzar de vuelta al centro
      if (abs(pos) > 120.0f) {
        pwm = (pos > 0) ? -PWM_MAX : PWM_MAX;
      }



      pwm = constrain(pwm, -PWM_MAX, PWM_MAX);
      setMotor(pwm);
    }

    // ══════════════════════════════════════════════════════════════════════════
    // MODO 5: Swing-up por energia con kick continuo
    // ══════════════════════════════════════════════════════════════════════════
    if (mode == 5) {
      int pwm = 0;
      const float alpha = pendPos * DEG_TO_RAD;
      const float alpha_dot = (pendPos - prevPosPend) / dt * DEG_TO_RAD;
      prevPosPend = pendPos;

      const float mgl = PEND_MASS * GRAVITY * PEND_LENGTH;

      // Energía total del péndulo (0 en fondo, 2*mgl en vertical arriba)
      const float E = 0.5f * PEND_INERTIA * alpha_dot * alpha_dot + mgl * (1.0f - cosf(alpha));
      const float Er = 2.0f * mgl;

      // Ley de swing-up por energía (Quanser / Åström-Furuta):
      //   u = sign(α̇ · cos α) · sign(Er - E)
      // Bombea energía cuando E < Er, la reduce cuando E > Er.
      const float prod = alpha_dot * cosf(alpha);
      float motion_sign = 0.0f;
      if (prod > 0.001f) motion_sign = 1.0f;
      else if (prod < -0.001f) motion_sign = -1.0f;

      const float energy_sign = (Er > E) ? 1.0f : -1.0f;

      if (abs(alpha_dot) < 0.15f) {
        // Péndulo casi quieto — kick alternante para iniciar oscilación.
        // Alterna cada ~250ms (≈ periodo natural del péndulo / 2) para
        // construir amplitud por resonancia.
        const unsigned long halfPeriodMs = 250;
        if (((millis() / halfPeriodMs) % 2) == 0) {
          pwm = MOTOR_DIR * (int)(PWM_MAX * 0.7f);
        } else {
          pwm = -MOTOR_DIR * (int)(PWM_MAX * 0.7f);
        }
      } else {
        // Bombeo de energía normal
        float u = ke_gain * energy_sign * motion_sign;
        pwm = (int)(MOTOR_DIR * u * PWM_MAX);
      }

      // Transición a LQR si el péndulo está cerca de la vertical arriba
      // Y la velocidad angular es baja (evita transiciones prematuras)
      // normalizeAngle(pendPos - 180): 0=arriba, ±180=abajo
      float alpha_lqr = normalizeAngle(pendPos - 180.0f);
      float dist_from_up = abs(alpha_lqr);
      float vel_abs = abs(alpha_dot) * RAD_TO_DEG;  //_velocidad en deg/s
      if (dist_from_up < balance_threshold && vel_abs < 500.0f) {
        mode = 4;
        resetLqr();
        Serial.println("Swing-up: TRANSICION a LQR");
      }

      pwm = constrain(pwm, -PWM_MAX, PWM_MAX);
      setMotor(pwm);
    }
  }
  const unsigned long nowMs = millis();

  // Failsafe: si no hay comandos recientes en modos activos, detener.
  if (ENABLE_COMMAND_TIMEOUT && mode >= 1 && mode <= 5 && (nowMs - lastCommandMs > COMMAND_TIMEOUT_MS)) {
    safeStop();
  }

  if (nowMs - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = nowMs;
    const long c = getEncoderCountAtomic();
    const float pos = encoderDir * c * getDegPerCount() - positionOffsetDeg;
    const long pc = getPendulumCountAtomic();
    const float pendPos = pendulumDir * pc * getPendulumDegPerCount() - pendulumOffsetDeg;

    updateIna219();

    Serial.print("POS:");
    Serial.print(pos, 2);
    Serial.print(" CNT:");
    Serial.print(c);
    Serial.print(" PPOS:");
    Serial.print(pendPos, 2);
    Serial.print(" PCNT:");
    Serial.print(pc);
    Serial.print(" SP:");
    Serial.print(setpoint_deg, 2);
    Serial.print(" PWM:");
    Serial.print(lastPwmCmd);
    Serial.print(" M:");
    Serial.print(mode);
    if (inaOk) {
      Serial.print(" V:");
      Serial.print(busVoltageV, 2);
      Serial.print(" I[mA]:");
      Serial.print(currentmA, 1);
      Serial.print(" P[mW]:");
      Serial.print(powermW, 1);
    }
    Serial.println();
    // Broadcast via WebSocket to connected clients
    broadcastTelemetry();
  }
}
