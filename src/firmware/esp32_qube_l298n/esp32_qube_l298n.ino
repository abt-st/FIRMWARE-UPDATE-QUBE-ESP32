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
#include <WebServer.h>
#include <Wire.h>
#include "credentials.h"
#include <Preferences.h>

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

volatile long encoderCount = 0;
volatile long pendulumCount = 0;

float countsPerRev = 2048.0f;               // Ajustable en runtime con cpr<val>
int encoderDir = 1;                         // Ajustable en runtime con ed<1|-1>
float pendCountsPerRev = 2048.0f;           // CPR encoder péndulo
int pendulumDir = 1;                        // Dirección encoder péndulo
const bool USE_ENCODER_INTERRUPTS = false;  // true: ISR en A/B
const bool USE_ENCODER_POLLING = true;      // true: decodificacion por sondeo en loop

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

// PID Péndulo (modo 3)
float Kp_pend = 15.0f;
float Ki_pend = 0.5f;
float Kd_pend = 2.0f;
float integralTermPend = 0.0f;
float prevErrorPend = 0.0f;
float prevPosPend = 0.0f;
float filteredVelPend = 0.0f;
const float VEL_ALPHA_PEND = 0.15f;
float pendulumOffsetDeg = 0.0f;

// LQR Péndulo Invertido (modo 4)
// Ganancias LQR: u = -(K1*theta + K2*alpha + K3*theta_dot + K4*alpha_dot)
float lqr_K1 = 1.0f;    // Ganancia posición servo
float lqr_K2 = 25.0f;   // Ganancia ángulo péndulo
float lqr_K3 = 0.5f;    // Ganancia velocidad servo
float lqr_K4 = 3.0f;    // Ganancia velocidad péndulo
float lqr_prevTheta = 0.0f;
float lqr_prevAlpha = 0.0f;
float lqr_filteredVelTheta = 0.0f;
float lqr_filteredVelAlpha = 0.0f;

volatile uint8_t encoderLastState = 0;
volatile uint8_t pendulumLastState = 0;

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
float balance_threshold = 20.0f;    // Umbral para cambiar a LQR (grados desde vertical) - ajustable
// Swing-up fase (modo 5)
int swingPhase = 0;              // 0=excitacion, 1=bombeo de energia
unsigned long exciteStartMs = 0;
void resetSwingUp() { swingPhase = 0; exciteStartMs = 0; }

const unsigned long CONTROL_PERIOD_US = 5000;  // 200 Hz
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
WebServer server(80);

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

void IRAM_ATTR isrEncoderA() {
  if (digitalRead(PIN_ENC_A) == digitalRead(PIN_ENC_B)) {
    encoderCount++;
  } else {
    encoderCount--;
  }
}

void IRAM_ATTR isrEncoderB() {
  if (digitalRead(PIN_ENC_A) != digitalRead(PIN_ENC_B)) {
    encoderCount++;
  } else {
    encoderCount--;
  }
}

void resetEncoderStateTracker() {
  const uint8_t a = (uint8_t)digitalRead(PIN_ENC_A);
  const uint8_t b = (uint8_t)digitalRead(PIN_ENC_B);
  encoderLastState = (a << 1) | b;
}

void updateEncoderPolling() {
  if (!USE_ENCODER_POLLING) {
    return;
  }

  const uint8_t a = (uint8_t)digitalRead(PIN_ENC_A);
  const uint8_t b = (uint8_t)digitalRead(PIN_ENC_B);
  const uint8_t state = (a << 1) | b;
  const uint8_t idx = (encoderLastState << 2) | state;

  // Tabla de transicion cuadratura (X4): +1, -1, 0 (invalida/sin cambio)
  static const int8_t QUAD_LUT[16] = {
    0, -1, +1, 0,
    +1, 0, 0, -1,
    -1, 0, 0, +1,
    0, +1, -1, 0
  };

  const int8_t delta = QUAD_LUT[idx];
  if (delta != 0) {
    noInterrupts();
    encoderCount += delta;
    interrupts();
  }

  encoderLastState = state;
}

void resetPendulumStateTracker() {
  const uint8_t a = (uint8_t)digitalRead(PIN_PEND_A);
  const uint8_t b = (uint8_t)digitalRead(PIN_PEND_B);
  pendulumLastState = (a << 1) | b;
}

void updatePendulumPolling() {
  if (!USE_ENCODER_POLLING) {
    return;
  }

  const uint8_t a = (uint8_t)digitalRead(PIN_PEND_A);
  const uint8_t b = (uint8_t)digitalRead(PIN_PEND_B);
  const uint8_t state = (a << 1) | b;
  const uint8_t idx = (pendulumLastState << 2) | state;

  static const int8_t QUAD_LUT[16] = {
    0, -1, +1, 0,
    +1, 0, 0, -1,
    -1, 0, 0, +1,
    0, +1, -1, 0
  };

  const int8_t delta = QUAD_LUT[idx];
  if (delta != 0) {
    noInterrupts();
    pendulumCount += delta;
    interrupts();
  }

  pendulumLastState = state;
}

long getPendulumCountAtomic() {
  noInterrupts();
  long c = pendulumCount;
  interrupts();
  return c;
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

long getEncoderCountAtomic() {
  noInterrupts();
  long c = encoderCount;
  interrupts();
  return c;
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
  json += "\"ina_ok\":" + String(inaOk ? "true" : "false") + ",";
  json += "\"v_bus\":" + String(busVoltageV, 3) + ",";
  json += "\"v_shunt_mv\":" + String(shuntVoltagemV, 3) + ",";
  json += "\"i_ma\":" + String(currentmA, 3) + ",";
  json += "\"p_mw\":" + String(powermW, 3);
  json += "}";
  return json;
}

void addCorsHeaders() {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.sendHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  server.sendHeader("Access-Control-Allow-Headers", "*");
}

void handleOptions() {
  addCorsHeaders();
  server.send(204);
}

void handleRoot() {
  addCorsHeaders();
  String html = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>";
  html += "<title>QUBE ESP32 L298N INA219</title></head><body>";
  html += "<h2>QUBE ESP32 + L298N + INA219</h2>";
  html += "<p>GET /state — JSON de telemetria (servo + pendulo)</p>";
  html += "<p>GET /cmd?m=0..5 — Modo (0=stop, 1=PWM, 2=PID servo, 3=PID pendulo, 4=LQR, 5=Swing-up)</p>";
  html += "<p>GET /cmd?s=45 — Setpoint servo</p>";
  html += "<p>GET /cmd?sp=0 — Setpoint pendulo</p>";
  html += "<p>GET /cmd?x=1 — Paro de emergencia</p>";
  html += "<p>GET /cmd?z=1 / zp=1 — Zero servo / pendulo</p>";
  html += "<p>GET /cmd?wifi_ssid=TuRed&wifi_pass=TuClave — Guardar WiFi (NVS)</p>";
  html += "<p>GET /cmd?wifi_reconnect=1 — Reconectar WiFi</p>";
  html += "</body></html>";
  server.send(200, "text/html", html);
}

void handleState() {
  addCorsHeaders();
  server.send(200, "application/json", getStateJson());
}

void handleCmd() {
  addCorsHeaders();
  if (server.hasArg("m")) {
    const int m = server.arg("m").toInt();
    if (m >= 0 && m <= 5) {
      mode = m;
      resetPid();
      resetPendulumPid();
      if (mode == 4) resetLqr();
      if (mode == 5) resetSwingUp();  // Reset fase de excitacion
      if (mode == 0) setMotor(0);
      lastCommandMs = millis();
    }
  }

  // Servo setpoint (modo 2)
  if (server.hasArg("s")) {
    setpoint_deg = server.arg("s").toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  // Pendulum setpoint (modo 3)
  if (server.hasArg("sp")) {
    pendulum_setpoint_deg = server.arg("sp").toFloat();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  // Zero servo
  if (server.hasArg("z")) {
    zeroPositionHere();
    setpoint_deg = 0.0f;
    resetPid();
    lastCommandMs = millis();
  }

  // Zero pendulum
  if (server.hasArg("zp")) {
    zeroPendulumHere();
    pendulum_setpoint_deg = 0.0f;
    resetPendulumPid();
    lastCommandMs = millis();
  }

  // Servo offset
  if (server.hasArg("o")) {
    positionOffsetDeg = server.arg("o").toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  // Pendulum offset
  if (server.hasArg("op")) {
    pendulumOffsetDeg = server.arg("op").toFloat();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  // Servo encoder direction
  if (server.hasArg("ed")) {
    const int v = server.arg("ed").toInt();
    encoderDir = (v >= 0) ? 1 : -1;
    resetPid();
    lastCommandMs = millis();
  }

  // Pendulum encoder direction
  if (server.hasArg("edp")) {
    const int v = server.arg("edp").toInt();
    pendulumDir = (v >= 0) ? 1 : -1;
    resetPendulumPid();
    lastCommandMs = millis();
  }

  // Servo CPR
  if (server.hasArg("cpr")) {
    const float v = server.arg("cpr").toFloat();
    if (v >= 1.0f) {
      countsPerRev = v;
      resetPid();
      lastCommandMs = millis();
    }
  }

  // Pendulum CPR
  if (server.hasArg("cprp")) {
    const float v = server.arg("cprp").toFloat();
    if (v >= 1.0f) {
      pendCountsPerRev = v;
      resetPendulumPid();
      lastCommandMs = millis();
    }
  }
  // WiFi credentials (save to NVS)
  if (server.hasArg("wifi_ssid")) {
    const String ssid = server.arg("wifi_ssid");
    if (ssid.length() > 0 && ssid.length() < 33) {
      saveWifiCredentials(ssid.c_str(), staPass);
    }
    lastCommandMs = millis();
  }
  if (server.hasArg("wifi_pass")) {
    const String pass = server.arg("wifi_pass");
    if (pass.length() >= 8) {
      saveWifiCredentials(staSsid, pass.c_str());
    }
    lastCommandMs = millis();
  }
  // WiFi reconnect (after saving credentials)
  if (server.hasArg("wifi_reconnect")) {
    WiFi.disconnect();
    delay(100);
    connectStaIfConfigured();
    lastCommandMs = millis();
  }

  // Manual PWM (mode 1)
  if (server.hasArg("p") && mode == 1) {
    const int pwm = constrain(server.arg("p").toInt(), -255, 255);
    setMotor(pwm);
    lastCommandMs = millis();
  }

  // Emergency stop
  if (server.hasArg("x")) {
    safeStop();
    lastCommandMs = millis();
  }

  // Reset encoders (servo + pendulum)
  if (server.hasArg("r")) {
    noInterrupts();
    encoderCount = 0;
    pendulumCount = 0;
    interrupts();
    resetEncoderStateTracker();
    resetPendulumStateTracker();
    positionOffsetDeg = 0.0f;
    pendulumOffsetDeg = 0.0f;
    setpoint_deg = 0.0f;
    pendulum_setpoint_deg = 0.0f;
    resetPid();
    resetPendulumPid();
    lastCommandMs = millis();
  }

  // Servo PID gains
  if (server.hasArg("kp")) {
    Kp = server.arg("kp").toFloat();
    resetPid();
  }
  if (server.hasArg("ki")) {
    Ki = server.arg("ki").toFloat();
    resetPid();
  }
  if (server.hasArg("kd")) {
    Kd = server.arg("kd").toFloat();
    resetPid();
  }

  // Pendulum PID gains
  if (server.hasArg("kpp")) {
    Kp_pend = server.arg("kpp").toFloat();
    resetPendulumPid();
  }
  if (server.hasArg("kip")) {
    Ki_pend = server.arg("kip").toFloat();
    resetPendulumPid();
  }
  if (server.hasArg("kdp")) {
    Kd_pend = server.arg("kdp").toFloat();
    resetPendulumPid();
  }

  // LQR gains
  if (server.hasArg("lqr1")) {
    lqr_K1 = server.arg("lqr1").toFloat();
    resetLqr();
  }
  if (server.hasArg("lqr2")) {
    lqr_K2 = server.arg("lqr2").toFloat();
    resetLqr();
  }
  if (server.hasArg("lqr3")) {
    lqr_K3 = server.arg("lqr3").toFloat();
    resetLqr();
  }
  if (server.hasArg("lqr4")) {
    lqr_K4 = server.arg("lqr4").toFloat();
    resetLqr();
  }
  // Swing-up parameters
  if (server.hasArg("ke")) {
    ke_gain = server.arg("ke").toFloat();
  }
  if (server.hasArg("bt")) {
    balance_threshold = server.arg("bt").toFloat();
  }

  server.send(200, "application/json", getStateJson());
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
        setpoint_deg = cmd.substring(1).toFloat();
        resetPid();
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
        break;
      }

    case 'r':
      {
        noInterrupts();
        encoderCount = 0;
        pendulumCount = 0;
        interrupts();
        resetEncoderStateTracker();
        resetPendulumStateTracker();
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

  // GPIO34/GPIO35 son pines solo-entrada en ESP32 y no soportan pull-up interno.
  pinMode(PIN_ENC_A, INPUT);
  pinMode(PIN_ENC_B, INPUT);
  resetEncoderStateTracker();
  if (USE_ENCODER_INTERRUPTS) {
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_A), isrEncoderA, CHANGE);
    attachInterrupt(digitalPinToInterrupt(PIN_ENC_B), isrEncoderB, CHANGE);
  }

  // GPIO32/GPIO33 encoder péndulo (también input-only)
  pinMode(PIN_PEND_A, INPUT);
  pinMode(PIN_PEND_B, INPUT);
  resetPendulumStateTracker();

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  delay(50);
  scanI2CBus();
  inaOk = initIna219();

  // Load WiFi credentials from NVS
  loadWifiCredentials();

  WiFi.mode(ENABLE_STA ? WIFI_AP_STA : WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS, 6, false, 4);  // canal 6, SSID visible, max 4 clientes
  connectStaIfConfigured();

  server.on("/", HTTP_GET, handleRoot);
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
  updateEncoderPolling();
  updatePendulumPolling();

  server.handleClient();

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

      if (abs(err) < 45.0f && abs(filteredVel) < 60.0f) {
        integralTerm += err * dt;
        integralTerm = constrain(integralTerm, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
      } else {
        integralTerm = 0.0f;
      }

      const float rawVel = -(pos - prevPos) / dt;
      filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;
      prevError = err;
      prevPos = pos;

      float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
      int pwm = (int)(MOTOR_DIR * u);

      if (abs(pwm) < PWM_MIN && abs(err) > 8.0f && abs(filteredVel) < 15.0f) {
        pwm = (pwm >= 0) ? PWM_MIN : -PWM_MIN;
      }
      if (abs(err) <= 0.8f) {
        pwm = 0;
      }

      int pwmLimit = PWM_MAX;
      if (abs(err) < 20.0f) pwmLimit = 80;
      if (abs(err) < 10.0f) pwmLimit = 55;
      if (abs(err) < 5.0f) pwmLimit = 35;

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
      // theta = posición servo (grados), alpha = posición péndulo (grados)
      const float theta = pos;
      const float alpha = pendPos;

      // Velocidades con filtro EMA
      const float rawVelTheta = -(theta - lqr_prevTheta) / dt;
      const float rawVelAlpha = -(alpha - lqr_prevAlpha) / dt;
      lqr_filteredVelTheta = VEL_ALPHA * rawVelTheta + (1.0f - VEL_ALPHA) * lqr_filteredVelTheta;
      lqr_filteredVelAlpha = VEL_ALPHA_PEND * rawVelAlpha + (1.0f - VEL_ALPHA_PEND) * lqr_filteredVelAlpha;
      lqr_prevTheta = theta;
      lqr_prevAlpha = alpha;

      // LQR: u = -(K1*theta + K2*alpha + K3*theta_dot + K4*alpha_dot)
      // alpha=0 es la posición vertical (invertido)
      float u = -(lqr_K1 * theta + lqr_K2 * alpha + lqr_K3 * lqr_filteredVelTheta + lqr_K4 * lqr_filteredVelAlpha);
      int pwm = (int)(MOTOR_DIR * u);

      // Protección: si el péndulo está muy lejos de la vertical, no aplicar torque
      // (evita que el motor se vuelva loco si el péndulo está abajo)
      if (abs(alpha) > 150.0f) {
        pwm = 0;
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

      // Bombeo de energia (Quanser) con ganancia alta
      const float E = 0.5f * PEND_INERTIA * alpha_dot * alpha_dot + mgl * (1.0f - cosf(alpha));
      const float Er = 2.0f * mgl;
      const float E_err = E - Er;

      float sign_val = 0.0f;
      float prod = alpha_dot * cosf(alpha);
      if (prod > 0.001f) sign_val = 1.0f;
      else if (prod < -0.001f) sign_val = -1.0f;

      // Kick solo cuando el pendulo esta muy quieto
      if (abs(alpha_dot) < 0.1f) {
        pwm = MOTOR_DIR * PWM_MAX * 0.8f;
      } else {
        float u = ke_gain * E_err * sign_val * 80.0f;
        u = constrain(u, -1.0f, 1.0f);
        pwm = (int)(MOTOR_DIR * u * PWM_MAX);
      }

      // Transicion a LQR si esta cerca de la vertical arriba (180°)
      float alpha_abs = abs(pendPos);
      float mod360 = fmodf(alpha_abs, 360.0f);
      float dist_from_up = abs(mod360 - 180.0f);
      if (dist_from_up < balance_threshold) {
        mode = 4;
        resetLqr();
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
  }
}
