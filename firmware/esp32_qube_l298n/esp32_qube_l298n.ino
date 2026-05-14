// ============================================================
// QUBE Servo - Firmware base oficial
// Arquitectura: ESP32 + L298N + INA219 + LM2596 + shifter 5V->3.3V
// Fecha: 2026-04-27
// ============================================================
// Topologia de potencia y logica:
// 1) Fuente principal (12V-15V) -> VS del L298N
// 2) Fuente principal -> LM2596 -> 5V para logica auxiliar
// 3) Encoder servo (push-pull 5V) -> divisor 4.7kΩ/8.2kΩ (Vout=3.17V) -> ESP32 GPIO34/GPIO35
// 4) INA219 en I2C para telemetria de bus/corriente
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
// Encoder A -> GPIO34
// Encoder B -> GPIO35
// INA219 SDA -> GPIO21
// INA219 SCL -> GPIO22
//
// Comandos Serial:
// m0, m1, m2           -> modo 0: stop, 1: PWM manual, 2: PID posicion
// p-255..255           -> PWM manual (solo en m1)
// s<grados>            -> setpoint de posicion (m2)
// kp<val>, ki<val>, kd<val>
// r                    -> reset encoder y PID
// x                    -> paro inmediato
// ?                    -> imprime estado
//
// Endpoints HTTP:
// GET /state
// GET /cmd?m=2
// GET /cmd?s=45
// GET /cmd?p=100
// GET /cmd?x=1
// ============================================================

#include <WiFi.h>
#include <WebServer.h>
#include <Wire.h>

#if defined(__has_include)
#if __has_include(<Adafruit_INA219.h>)
#include <Adafruit_INA219.h>
#define HAS_ADAFRUIT_INA219 1
#endif
#endif

#ifndef HAS_ADAFRUIT_INA219
// Fallback: permite compilar sin la libreria INA219 instalada.
class Adafruit_INA219 {
public:
  Adafruit_INA219(uint8_t addr = 0x40) {
    (void)addr;
  }
  bool begin() {
    return false;
  }
  void setCalibration_32V_2A() {}
  float getShuntVoltage_mV() {
    return 0.0f;
  }
  float getBusVoltage_V() {
    return 0.0f;
  }
  float getCurrent_mA() {
    return 0.0f;
  }
  float getPower_mW() {
    return 0.0f;
  }
};
#endif

static const int PIN_ENC_A = 34;
static const int PIN_ENC_B = 35;

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

float countsPerRev = 2048.0f;               // Ajustable en runtime con cpr<val>
int encoderDir = 1;                         // Ajustable en runtime con ed<1|-1>
const bool USE_ENCODER_INTERRUPTS = false;  // true: ISR en A/B
const bool USE_ENCODER_POLLING = true;      // true: decodificacion por sondeo en loop

int mode = 0;
int lastPwmCmd = 0;
float setpoint_deg = 0.0f;

float Kp = 0.75f;
float Ki = 0.15f;  // Integral para eliminar error en regimen permanente
float Kd = 0.06f;
float integralTerm = 0.0f;
float prevError = 0.0f;
float prevPos = 0.0f;
float filteredVel = 0.0f;        // Velocidad filtrada (paso-bajo) para derivada
const float VEL_ALPHA = 0.12f;   // Factor filtro: 0=muy suave, 1=sin filtro
float positionOffsetDeg = 0.0f;  // Offset de referencia para alinear cero mecanico

volatile uint8_t encoderLastState = 0;

// Si el motor gira en direccion opuesta al encoder (feedback positivo),
// cambiar MOTOR_DIR a -1 para invertir la salida del PID.
const int MOTOR_DIR = -1;  // 1 = normal, -1 = invertido

const float INTEGRAL_LIMIT = 250.0f;
const int PWM_MIN = 12;
const int PWM_MAX = 210;

const unsigned long CONTROL_PERIOD_US = 5000;  // 200 Hz
const unsigned long TELEMETRY_PERIOD_MS = 100;
const unsigned long COMMAND_TIMEOUT_MS = 10000;
const bool ENABLE_COMMAND_TIMEOUT = false;  // true para seguridad en operacion, false para ajuste en banco

unsigned long lastControlUs = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastCommandMs = 0;

const char* AP_SSID = "QUBE-ESP32";
const char* AP_PASS = "qube1234";
const bool ENABLE_STA = true;            // true: conecta tambien a tu router LAN
const char* STA_SSID = "Guaifai";              // <-- coloca aqui el SSID de tu red local
const char* STA_PASS = "Azulito2020_";              // <-- coloca aqui la clave de tu red local
const unsigned long WIFI_CONNECT_TIMEOUT_MS = 15000;
WebServer server(80);

Adafruit_INA219 ina219(0x40);
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

    ina219 = Adafruit_INA219(addr);
    if (ina219.begin()) {
      ina219.setCalibration_32V_2A();
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
  setMotor(0);
}

void updateIna219() {
  if (!inaOk) {
    return;
  }
  shuntVoltagemV = ina219.getShuntVoltage_mV();
  busVoltageV = ina219.getBusVoltage_V();
  currentmA = ina219.getCurrent_mA();
  powermW = ina219.getPower_mW();
}

String getStateJson() {
  updateIna219();
  const long c = getEncoderCountAtomic();
  const int encA = digitalRead(PIN_ENC_A);
  const int encB = digitalRead(PIN_ENC_B);
  const float rawPos = encoderDir * c * getDegPerCount();
  const float pos = rawPos - positionOffsetDeg;
  const float err = setpoint_deg - pos;

  String json = "{";
  json += "\"mode\":" + String(mode) + ",";
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
  html += "<p>GET /state para JSON de telemetria</p>";
  html += "<p>GET /cmd?m=2 /cmd?s=45 /cmd?p=120 /cmd?x=1 /cmd?z=1 /cmd?o=45 /cmd?ed=-1 /cmd?cpr=2048</p>";
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
    if (m >= 0 && m <= 2) {
      mode = m;
      resetPid();
      if (mode == 0) {
        setMotor(0);
      }
      lastCommandMs = millis();
    }
  }

  if (server.hasArg("s")) {
    setpoint_deg = server.arg("s").toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  if (server.hasArg("z")) {
    zeroPositionHere();
    setpoint_deg = 0.0f;
    resetPid();
    lastCommandMs = millis();
  }

  if (server.hasArg("o")) {
    positionOffsetDeg = server.arg("o").toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  if (server.hasArg("ed")) {
    const int v = server.arg("ed").toInt();
    encoderDir = (v >= 0) ? 1 : -1;
    resetPid();
    lastCommandMs = millis();
  }

  if (server.hasArg("cpr")) {
    const float v = server.arg("cpr").toFloat();
    if (v >= 1.0f) {
      countsPerRev = v;
      resetPid();
      lastCommandMs = millis();
    }
  }

  if (server.hasArg("p") && mode == 1) {
    const int pwm = constrain(server.arg("p").toInt(), -255, 255);
    setMotor(pwm);
    lastCommandMs = millis();
  }

  if (server.hasArg("x")) {
    safeStop();
    lastCommandMs = millis();
  }

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

  server.send(200, "application/json", getStateJson());
}

void connectStaIfConfigured() {
  if (!ENABLE_STA) {
    return;
  }

  if (STA_SSID[0] == '\0') {
    Serial.println("STA: deshabilitado (sin credenciales)");
    return;
  }

  Serial.print("STA: conectando a ");
  Serial.println(STA_SSID);
  WiFi.begin(STA_SSID, STA_PASS);

  const unsigned long startMs = millis();
  while (WiFi.status() != WL_CONNECTED && (millis() - startMs) < WIFI_CONNECT_TIMEOUT_MS) {
    delay(250);
    Serial.print(".");
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("STA: conectado. IP LAN: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println("STA: no se pudo conectar (timeout)");
  }
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
  Serial.println("Comandos: m0/m1/m2, p-255..255, s<deg>, kp<val>, ki<val>, kd<val>, o<deg>, z, ed<1|-1>, cpr<val>, r, x, i(IP), n(ina scan), ?");
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
        if (m >= 0 && m <= 2) {
          mode = m;
          resetPid();
          if (mode == 0) {
            setMotor(0);
          }
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
        interrupts();
        resetEncoderStateTracker();
        positionOffsetDeg = 0.0f;
        setpoint_deg = 0.0f;
        resetPid();
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

  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  delay(50);
  scanI2CBus();
  inaOk = initIna219();

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

  server.handleClient();

  if (Serial.available()) {
    processSerialCommand();
  }

  const unsigned long nowUs = micros();
  if ((nowUs - lastControlUs) >= CONTROL_PERIOD_US) {
    lastControlUs += CONTROL_PERIOD_US;

    const float pos = getPositionDeg();

    if (mode == 2) {
      const float dt = CONTROL_PERIOD_US / 1000000.0f;
      const float err = setpoint_deg - pos;

      if (abs(err) < 45.0f && abs(filteredVel) < 60.0f) {
        integralTerm += err * dt;
        integralTerm = constrain(integralTerm, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
      } else {
        integralTerm = 0.0f;
      }

      // Derivada sobre la medicion con filtro paso-bajo para suprimir ruido del encoder
      const float rawVel = -(pos - prevPos) / dt;
      filteredVel = VEL_ALPHA * rawVel + (1.0f - VEL_ALPHA) * filteredVel;
      prevError = err;
      prevPos = pos;

      float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
      int pwm = (int)(MOTOR_DIR * u);

      // Solo forzar PWM_MIN si el motor esta casi parado y aun queda un error significativo.
      // Reducimos la compensacion de friccion para evitar comportamiento tipo bang-bang.
      if (abs(pwm) < PWM_MIN && abs(err) > 8.0f && abs(filteredVel) < 15.0f) {
        pwm = (pwm >= 0) ? PWM_MIN : -PWM_MIN;
      }
      if (abs(err) <= 0.8f) {
        pwm = 0;
      }

      int pwmLimit = PWM_MAX;
      if (abs(err) < 20.0f) {
        pwmLimit = 80;
      }
      if (abs(err) < 10.0f) {
        pwmLimit = 55;
      }
      if (abs(err) < 5.0f) {
        pwmLimit = 35;
      }

      pwm = constrain(pwm, -pwmLimit, pwmLimit);
      setMotor(pwm);
    }
  }

  const unsigned long nowMs = millis();

  // Failsafe: si no hay comandos recientes en modos activos, detener.
  if (ENABLE_COMMAND_TIMEOUT && (mode == 1 || mode == 2) && (nowMs - lastCommandMs > COMMAND_TIMEOUT_MS)) {
    safeStop();
  }

  if (nowMs - lastTelemetryMs >= TELEMETRY_PERIOD_MS) {
    lastTelemetryMs = nowMs;
    const long c = getEncoderCountAtomic();
    const float pos = encoderDir * c * getDegPerCount() - positionOffsetDeg;

    updateIna219();

    Serial.print("POS:");
    Serial.print(pos, 2);
    Serial.print(" CNT:");
    Serial.print(c);
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
