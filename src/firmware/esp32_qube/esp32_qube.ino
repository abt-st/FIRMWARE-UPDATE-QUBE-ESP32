// ============================================================
// QUBE Servo - Firmware base oficial
// Arquitectura: ESP32 + BTS7960 (IBT-2) + INA219 + LM2596 + CD40106BE Schmitt Trigger
// Fecha: 2026-05-28 (driver migrado de L298N a BTS7960 el 2026-06-08, commit 78b4e7e)
// ============================================================
// Topologia de potencia y logica:
// 1) Fuente principal (12V-15V) -> INA219 (serie) -> BTS7960 B+ (VS motor)
// 2) Fuente principal -> LM2596 -> 5V para logica auxiliar
// 3) Encoder servo (open-drain 5V) -> pull-up 4.7kΩ a 3.3V
//    -> Schmitt Trigger CD40106BE (doble inversion, Vcc=3.3V)
//    -> salida limpia ~3.3V -> ESP32 GPIO34/GPIO35
// 4) INA219 en I2C para telemetria de voltaje, corriente y potencia
// 5) GND comun entre potencia y logica (topologia estrella)
//
// Pines recomendados (BTS7960 / IBT-2):
// BTS7960 R_EN + L_EN -> GPIO25  (habilitacion; puentear R_EN->L_EN en el modulo)
// BTS7960 RPWM        -> GPIO26  (IN1: PWM sentido horario)
// BTS7960 LPWM        -> GPIO27  (IN2: PWM sentido antihorario)
// BTS7960 VCC (logica)-> 5V      | B+/B- -> potencia motor 12-15V (via INA219)
// Encoder servo A -> Schmitt INV_A (pin 1) -> GPIO34
// Encoder servo B -> Schmitt INV_C (pin 5) -> GPIO35
// INA219 SDA -> GPIO21
// INA219 SCL -> GPIO22
// CD40106BE Vcc -> 3.3V (pin 14), GND (pin 7), bypass 100nF
//
// Comandos Serial:
// m0, m1, m2, m6      -> modo 0: stop, 1: PWM manual, 2: PID posicion, 6: Deep RL
// p-255..255           -> PWM manual (solo en m1)
// s<grados>            -> setpoint de posicion (m2)
// kp<val>, ki<val>, kd<val>
// r                    -> reset encoder y PID
// kf<0|1>             -> activar/desactivar filtro de Kalman (LQG)
// ?                    -> imprime estado
// wifi_ssid<TuRed>     -> configurar SSID WiFi (guarda en NVS/Preferences)
// wifi_pass<TuClave>   -> configurar password WiFi (guarda en NVS/Preferences)
// wifi_info            -> mostrar configuracion WiFi actual
//
// Endpoints HTTP:
// GET /state               — estado completo (JSON)
// GET /cmd?m=2             — cambiar modo
// GET /cmd?s=45            — setpoint posición
// GET /cmd?p=100           — PWM manual (modo 1)
// GET /cmd?x=1             — parada segura
// GET /rl_state            — estado compacto para RL {th,al,thd,ald} (rad, rad/s)
// GET /rl_cmd?a=0.5        — acción RL [-1.0, 1.0]
// GET /rl_cmd?r=1          — reset encoders + estado RL
// GET /rl_cmd?z=1          — zero servo encoder (offset, sin reset PID)
// GET /rl_cmd?zp=1         — zero péndulo encoder (offset)
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <ESPAsyncWebServer.h>
#include <AsyncTCP.h>
#include <Wire.h>
#include "credentials.h"
#include <SPIFFS.h>
#include <ArduinoOTA.h>
#include <Update.h>
#include <Preferences.h>
#include "driver/pcnt.h"
#include "policy_weights.h"

// ══════════════════════════════════════════════════════════════════════════
// MODO 7: On-device RL inference (forward pass en ESP32)
// Red: [36 → 64 → 64 → 1], ReLU, tanh (SB3 SAC: acción determinista = tanh(mu))
// Observación: 4 pasos × [θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇, action]
// ══════════════════════════════════════════════════════════════════════════
constexpr int RL_HISTORY_STEPS = 4;
constexpr int RL_OBS_PER_STEP = 9;   // [θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇, action]
constexpr int RL_INPUT_DIM = RL_HISTORY_STEPS * RL_OBS_PER_STEP;  // 36
constexpr int RL_HIDDEN = 64;

float rl_obs_buf[RL_HISTORY_STEPS][RL_OBS_PER_STEP];
int rl_obs_idx = 0;
float rl_last_action = 0.0f;
// Runtime torque scale for mode 7 (sim2real dynamics gap tuning). Set via
// /rl_cmd?scale=X (0..1). 1.0 = full PWM; lower tames over-pumping on the real rig.
float rl_pwm_scale = 1.0f;
// Mode-7 velocity filter state — replicates the sim's discrete derivative filter
// H(s)=50s/(s+50) @ dt=0.02 (qube_rl/utils.py VelocityFilter). Reset on mode entry.
float rl_vf_thPrev = 0.0f, rl_vf_thVel = 0.0f;
float rl_vf_alPrev = 0.0f, rl_vf_alVel = 0.0f;
bool  rl_vf_init = false;

// Forward pass: input[36] → action in [-1, 1] via tanh (matches SB3 SAC
// deterministic output; verified numerically vs model.predict, err < 2e-7).
float rl_forward(const float* input) {
    float h1[RL_HIDDEN];
    for (int j = 0; j < RL_HIDDEN; j++) {
        float sum = policy_weights::LAYER_0_BIAS[j];
        for (int k = 0; k < RL_INPUT_DIM; k++) {
            sum += policy_weights::LAYER_0_WEIGHT[j * RL_INPUT_DIM + k] * input[k];
        }
        h1[j] = sum > 0.0f ? sum : 0.0f;  // ReLU
    }
    float h2[RL_HIDDEN];
    for (int j = 0; j < RL_HIDDEN; j++) {
        float sum = policy_weights::LAYER_1_BIAS[j];
        for (int k = 0; k < RL_HIDDEN; k++) {
            sum += policy_weights::LAYER_1_WEIGHT[j * RL_HIDDEN + k] * h1[k];
        }
        h2[j] = sum > 0.0f ? sum : 0.0f;  // ReLU
    }
    float raw_out = policy_weights::LAYER_2_BIAS[0];
    for (int k = 0; k < RL_HIDDEN; k++) {
        raw_out += policy_weights::LAYER_2_WEIGHT[k] * h2[k];
    }
    // SB3 SAC squashes the actor mean with tanh for the deterministic action.
    // (Previously Hardtanh(-2,2)*0.5 downstream — wrong fn, err up to 0.27.)
    return tanhf(raw_out);
}

// Build observation from current state and append to history
float rl_infer_step(float theta_rad, float alpha_rad, float theta_dot, float alpha_dot) {
    rl_obs_idx = (rl_obs_idx + 1) % RL_HISTORY_STEPS;
    rl_obs_buf[rl_obs_idx][0] = theta_rad;
    rl_obs_buf[rl_obs_idx][1] = alpha_rad;
    rl_obs_buf[rl_obs_idx][2] = cosf(theta_rad);
    rl_obs_buf[rl_obs_idx][3] = sinf(theta_rad);
    rl_obs_buf[rl_obs_idx][4] = cosf(alpha_rad);
    rl_obs_buf[rl_obs_idx][5] = sinf(alpha_rad);
    rl_obs_buf[rl_obs_idx][6] = theta_dot;
    rl_obs_buf[rl_obs_idx][7] = alpha_dot;
    rl_obs_buf[rl_obs_idx][8] = rl_last_action;

    // Flatten oldest-first into input[36]
    float input[RL_INPUT_DIM];
    for (int s = 0; s < RL_HISTORY_STEPS; s++) {
        int si = (rl_obs_idx - RL_HISTORY_STEPS + 1 + s + RL_HISTORY_STEPS) % RL_HISTORY_STEPS;
        for (int f = 0; f < RL_OBS_PER_STEP; f++) {
            input[s * RL_OBS_PER_STEP + f] = rl_obs_buf[si][f];
        }
    }

    float action = rl_forward(input);
    rl_last_action = action;
    return action;
}

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

// BTS7960: R_EN/L_EN habilitados por GPIO25 (opción B del README).
// Conectar GPIO25 → R_EN + puente R_EN→L_EN en el módulo IBT-2.
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
float lastServoPos = 0.0f;  // Posición del servo para soft saturation en setMotor
float setpoint_deg = 0.0f;
volatile float rlAction = 0.0f;  // Acción RL [-1.0, 1.0] — modo 6

// PID Servo (modo 2)
float Kp = 3.0f;
float Ki = 0.5f;
float Kd = 0.15f;
float integralTerm = 0.0f;
float prevPos = 0.0f;
float filteredVel = 0.0f;
float velAlpha = 0.12f;  // Filtro EMA velocidad servo (configurable por HTTP: va<val>)
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
float servo_ff_pwm = 0.0f;      // Feedforward: PWM constante para compensar torque gravitacional (desnivel mesa)
// prevPosPend: usado por swing-up (modo 5) para velocidad angular del péndulo
float prevPosPend = 0.0f;
const float VEL_ALPHA_PEND = 0.60f;  // Filtro velocidad péndulo (usado en LQR)
float swing_filteredVelAlpha = 0.0f;  // Filtro EMA velocidad péndulo para swing-up
float pendulumOffsetDeg = 0.0f;
// LQR Péndulo Invertido (modo 4)
// Ganancias LQR base (lejos del equilibrio)
float lqr_K1 = 2.0f;    // Ganancia posición servo
float lqr_K2 = 22.0f;   // Ganancia ángulo péndulo (valor original calibrado)
float lqr_K3 = 1.5f;
float lqr_K4 = 9.0f;    // Ganancia velocidad péndulo (valor original calibrado)

// Gain scheduling: gains moderados cerca del equilibrio
const float LQR_K2_NEAR = 30.0f;     // K2 cerca de vertical (probado: 55+ segundos)
const float LQR_K4_NEAR = 15.0f;     // K4 cerca de vertical (no subir a 20)
const float LQR_NEAR_DEG = 25.0f;    // Umbral para gains agresivos
const float LQR_K2_VERY_NEAR = 55.0f; // K2 cuando |alpha| < LQR_VERY_NEAR_DEG (muy cerca de vertical)
const float LQR_K4_VERY_NEAR = 20.0f; // K4 cuando |alpha| < LQR_VERY_NEAR_DEG
const float LQR_VERY_NEAR_DEG = 5.0f; // Umbral para gains muy agresivos
const float LQR_DAMPING_GAIN = 0.3f;  // Ganancia de disipación de energía dentro de LQR
float lqr_prevTheta = 0.0f;
float lqr_prevAlpha = 0.0f;
float lqr_filteredVelTheta = 0.0f;
float lqr_filteredVelAlpha = 0.0f;
bool lqr_inFallback = false;  // true mientras se está en swing-up por fallback LQR (evita rebote)
unsigned long lqr_fallbackMs = 0;  // Timestamp para fallback automático LQR→swing-up
unsigned long lqr_catchMs = 0;  // Timestamp para catch mode (frenado inicial al entrar a LQR)
const unsigned long LQR_CATCH_MS = 400;  // Duración del catch mode en ms (era 150, insuficiente para disipar inercia)
float pendPosRawPrev = 0.0f;  // Para detectar spinning
unsigned long spinCooldownMs = 0;  // Timestamp para cooldown post-spin
const unsigned long SPIN_COOLDOWN_MS = 1000;  // Duración del cooldown post-spin (ms)
// ── Filtro de Kalman (LQG) para LQR ─────────────────────────────────────────
// Estado: x = [theta, alpha, dtheta, dalpha] (4 estados)
// Medicion: z = [theta, alpha] (2 salidas — solo posiciones de encoder)
// Modelo linealizado del pendulo rotatorio invertido cerca del equilibrio vertical
bool kf_enabled = false;  // Toggle via HTTP: kf=1 / kf=0
// Matrices del modelo (discretizado con Euler, Ts = CONTROL_PERIOD_US)
// Ad = I + A*Ts (modelo discreto)
const float KF_TS = 0.002f;  // 500 Hz (2 ms)
// Parametros del modelo fisico para el KF
const float KF_MOTOR_GAIN = 50.0f;   // Ganancia motor: PWM -> deg/s^2 (ajustar experimentalmente)
const float KF_SERVO_FRIC = 2.0f;    // Friccion viscosa servo (1/s) — amortiguamiento
const float KF_PEND_FREQ = 12.3f;    // sqrt(g/l) del pendulo [rad/s] ≈ sqrt(9.81/0.065)
const float KF_PEND_FRIC = 0.5f;     // Friccion pendulo (1/s)
// Covarianzas (ajustables)
float kf_Q_pos = 0.1f;      // Ruido proceso: posicion (deg^2)
float kf_Q_vel = 10.0f;     // Ruido proceso: velocidad (deg/s^2) — mayor = confia mas en mediciones
float kf_R_pos = 0.5f;      // Ruido medicion: encoder (deg^2) — resolucion ~0.044°
// Estado estimado del KF
float kf_x[4] = {0.0f, 0.0f, 0.0f, 0.0f};  // [theta, alpha, dtheta, dalpha]
// Covarianza del error P (4x4, almacenada como array plano)
float kf_P[16] = {
  100.0f, 0.0f, 0.0f, 0.0f,
  0.0f, 100.0f, 0.0f, 0.0f,
  0.0f, 0.0f, 1000.0f, 0.0f,
  0.0f, 0.0f, 0.0f, 1000.0f
};
// Ganancia Kalman K (4x2)
float kf_K[8] = {0};

void kalmanReset() {
  kf_x[0] = 0.0f; kf_x[1] = 0.0f; kf_x[2] = 0.0f; kf_x[3] = 0.0f;
  // Reiniciar P a valores altos (incertidumbre inicial)
  for (int i = 0; i < 16; i++) kf_P[i] = 0.0f;
  kf_P[0] = 100.0f;   // theta
  kf_P[5] = 100.0f;   // alpha
  kf_P[10] = 1000.0f; // dtheta
  kf_P[15] = 1000.0f; // dalpha
}

// Predict: x_pred = Ad * x + Bd * u
//          P_pred = Ad * P * Ad^T + Q
// Ad es I + A*Ts (Euler discreto):
//   [1  0  Ts   0 ]
//   [0  1   0  Ts ]
//   [0  0 1-b1*Ts  0     ]   Bd = [0, 0, K_m*Ts, 0]^T
//   [0  w2*Ts  0  1-b2*Ts]
// donde w2 = (g/l)^2 (frecuencia natural al cuadrado, linearized)
void kalmanPredict(float pwmCmd) {
  const float Ts = KF_TS;
  const float b1s = KF_SERVO_FRIC * Ts;
  const float b2s = KF_PEND_FRIC * Ts;
  const float w2Ts = KF_PEND_FREQ * KF_PEND_FREQ * Ts;
  const float kmTs = KF_MOTOR_GAIN * Ts;
  // x_pred = Ad * x + Bd * u
  float x0 = kf_x[0] + Ts * kf_x[2];
  float x1 = kf_x[1] + Ts * kf_x[3];
  float x2 = (1.0f - b1s) * kf_x[2] + kmTs * pwmCmd;
  float x3 = w2Ts * kf_x[1] + (1.0f - b2s) * kf_x[3];
  kf_x[0] = x0; kf_x[1] = x1; kf_x[2] = x2; kf_x[3] = x3;
  // P_pred = Ad * P * Ad^T + Q (expanding since Ad is sparse)
  // Ad tiene forma: [I_2  Ts*I_2; Ad21  Ad22]
  // P es simetrica 4x4: indices [0..3][0..3] = P[i*4+j]
  float p00 = kf_P[0], p01 = kf_P[1], p02 = kf_P[2], p03 = kf_P[3];
  float p11 = kf_P[5], p12 = kf_P[6], p13 = kf_P[7];
  float p22 = kf_P[10], p23 = kf_P[11];
  float p33 = kf_P[15];
  // Ad*P (sparse multiplication)
  // Row 0: [p00+Ts*p02, p01+Ts*p03, p02+Ts*p22, p03+Ts*p23]
  float ap00 = p00 + Ts * p02;
  float ap01 = p01 + Ts * p03;
  float ap02 = p02 + Ts * p22;
  float ap03 = p03 + Ts * p23;
  // Row 1: [p01+Ts*p12, p11+Ts*p13, p12+Ts*p23, p13+Ts*p33]
  float ap10 = p01 + Ts * p12;
  float ap11 = p11 + Ts * p13;
  float ap12 = p12 + Ts * p23;
  float ap13 = p13 + Ts * p33;
  // Row 2: [(1-b1s)*p02, (1-b1s)*p12, (1-b1s)*p22, (1-b1s)*p23]
  float c2 = 1.0f - b1s;
  float ap20 = c2 * p02;
  float ap21 = c2 * p12;
  float ap22 = c2 * p22;
  float ap23 = c2 * p23;
  // Row 3: [w2Ts*p01+(1-b2s)*p03, w2Ts*p11+(1-b2s)*p13, w2Ts*p12+(1-b2s)*p23, w2Ts*p13+(1-b2s)*p33]
  float c3 = 1.0f - b2s;
  float ap30 = w2Ts * p01 + c3 * p03;
  float ap31 = w2Ts * p11 + c3 * p13;
  float ap32 = w2Ts * p12 + c3 * p23;
  float ap33 = w2Ts * p13 + c3 * p33;
  // P_new = Ad*P*Ad^T + Q, but Ad^T has structure:
  // [I_2      Ad21^T]
  // [Ts*I_2  Ad22^T]
  // where Ad21 = [0 w2Ts; 0 0], Ad22 = diag(1-b1s, 1-b2s)
  // Resultado (aprovechando simetria):
  kf_P[0]  = ap00 + Ts * ap02 + kf_Q_pos;                        // P[0][0]
  kf_P[1]  = ap01 + Ts * ap03;                                     // P[0][1]
  kf_P[2]  = ap02 + Ts * ap22;                                     // P[0][2]
  kf_P[3]  = ap03 + Ts * ap23;                                     // P[0][3]
  kf_P[5]  = ap11 + Ts * ap13 + kf_Q_pos;                        // P[1][1]
  kf_P[6]  = ap12 + Ts * ap23;                                     // P[1][2]
  kf_P[7]  = ap13 + Ts * ap33;                                     // P[1][3]
  kf_P[10] = c2 * ap22 + kf_Q_vel;                                // P[2][2]
  kf_P[11] = c2 * ap23;                                            // P[2][3]
  kf_P[15] = w2Ts * ap13 + c3 * ap33 + kf_Q_vel;                 // P[3][3]
  // Simetria
  kf_P[4]  = kf_P[1];
  kf_P[8]  = kf_P[2];  kf_P[9]  = kf_P[6];
  kf_P[12] = kf_P[3];  kf_P[13] = kf_P[7];  kf_P[14] = kf_P[11];
}

// Update: z = [theta_meas, alpha_meas]
// H = [1 0 0 0; 0 1 0 0] (mide solo posiciones)
// S = H*P*H^T + R = P[0:2,0:2] + R  (2x2)
// K = P*H^T * S^-1  (4x2)
// x = x + K*(z - H*x)
// P = (I - K*H)*P
void kalmanUpdate(float theta_meas, float alpha_meas) {
  // Innovation: y = z - H*x
  float y0 = theta_meas - kf_x[0];
  float y1 = alpha_meas - kf_x[1];
  // S = H*P*H^T + R (2x2 symmetric)
  float s00 = kf_P[0] + kf_R_pos;
  float s01 = kf_P[1];
  float s11 = kf_P[5] + kf_R_pos;
  // S^-1 (2x2 analytic inverse)
  float det = s00 * s11 - s01 * s01;
  if (det < 1e-10f) det = 1e-10f;  // Evitar singularidad
  float inv_det = 1.0f / det;
  float si00 = s11 * inv_det;
  float si01 = -s01 * inv_det;
  float si11 = s00 * inv_det;
  // K = P * H^T * S^-1
  // P*H^T = columnas 0 y 1 de P (4x2)
  // K[i][j] = sum_k P[i][k] * (H^T)[k][j] * S^-1...
  // K = [P[0], P[1]] * S^-1  (donde P[k] = columna k de P)
  float pcol0[4] = {kf_P[0], kf_P[4], kf_P[8], kf_P[12]};
  float pcol1[4] = {kf_P[1], kf_P[5], kf_P[9], kf_P[13]};
  for (int i = 0; i < 4; i++) {
    kf_K[i * 2]     = pcol0[i] * si00 + pcol1[i] * si01;
    kf_K[i * 2 + 1] = pcol0[i] * si01 + pcol1[i] * si11;
  }
  // x = x + K * y
  for (int i = 0; i < 4; i++) {
    kf_x[i] += kf_K[i * 2] * y0 + kf_K[i * 2 + 1] * y1;
  }
  // P = (I - K*H) * P
  // K*H es 4x2 * 2x4 = 4x4, pero H es [I 0], entonces K*H solo llena cols 0-1
  // P_new[i][j] = P[i][j] - K[i][0]*P[0][j] - K[i][1]*P[1][j]
  float P_new[16];
  for (int i = 0; i < 4; i++) {
    for (int j = 0; j < 4; j++) {
      P_new[i * 4 + j] = kf_P[i * 4 + j]
                        - kf_K[i * 2] * kf_P[j]
                        - kf_K[i * 2 + 1] * kf_P[4 + j];
    }
  }
  // Copiar resultado y forzar simetria
  for (int i = 0; i < 4; i++) {
    for (int j = i; j < 4; j++) {
      float val = 0.5f * (P_new[i * 4 + j] + P_new[j * 4 + i]);
      kf_P[i * 4 + j] = val;
      kf_P[j * 4 + i] = val;
    }
  }
}

// Si el motor gira en direccion opuesta al encoder (feedback positivo),
// cambiar MOTOR_DIR a -1 para invertir la salida del PID.
const int MOTOR_DIR = -1;  // 1 = normal, -1 = invertido

const float INTEGRAL_LIMIT = 250.0f;
const int PWM_MIN = 12;
const int PWM_MAX = 200;

// Parametros del pendulo para calculo de energia (Quanser swing-up)
const float PEND_MASS = 0.025f;      // Masa del pendulo (kg) - ajustar
const float PEND_LENGTH = 0.065f;    // Distancia pivot-centro de masa (m) - ajustar
const float PEND_INERTIA = 0.00002f; // Momento de inercia (kg*m^2) - ajustar
const float PEND_LIMIT_DEG = 90.0f;    // Limite fisico del pendulo (±90° desde reposo)
const float GRAVITY = 9.81f;         // Gravedad (m/s^2)
float ke_gain = 0.65f;  // Ganancia BTS7960: 25% catch rate, hold 86s
// Adaptive ke_gain: increase energy gain when pendulum stalls
float swing_maxAngleAchieved = 0.0f;    // Max absolute angle achieved since last reset
unsigned long swing_lastImprovementMs = 0;  // Timestamp of last angle improvement
const float KE_GAIN_BASE = 0.75f;       // Base energy gain (era 0.65)
const float KE_GAIN_BOOST = 1.5f;       // Boosted gain when stalled (era 1.2)
const unsigned long STALL_TIMEOUT_MS = 6000;  // 6s without improvement → boost (era 4s)
// Complementary filter for velocity estimation (physics + measurement)
float swing_predictedVelAlpha = 0.0f;  // Physics-model predicted velocity
const float COMP_FILTER_ALPHA = 0.7f;  // Weight for measurement (0= pure model, 1= pure derivative)
const float PEND_DAMPING = 0.02f;  // Estimated damping coefficient (N·m·s/rad)
float balance_threshold = 1.0f;     // Umbral para cambiar a LQR (grados desde vertical) - reducido de 3
bool swing_recovering = false;       // Estado de recovery: motor apagado esperando que el péndulo caiga
const float SWING_RECOVERY_THRESHOLD = 30.0f;  // |pendPos| < esto para salir de recovery (cerca del fondo)
const unsigned long CONTROL_PERIOD_US = 2000;             // 500 Hz (era 5000 = 200 Hz)
int swingupPwmMax = 50;  // PWM limit para swing-up (configurable por HTTP: sp<val>)
unsigned long telemetryPeriodMs = 100;          // Ajustable por HTTP: tp<ms>
float prev_alpha_dot_peak = 0.0f;  // Peak detection para transicion LQR
const unsigned long COMMAND_TIMEOUT_MS = 10000;
const bool ENABLE_COMMAND_TIMEOUT = false;               // true para seguridad en operacion, false para ajuste en banco
// ── Umbrales LQR ─────────────────────────────────────────────────────────────
const unsigned long LQR_FALLBACK_TIME_MS = 500;          // Tiempo fuera de vertical antes de fallback (era 1000)
const float LQR_FALLBACK_ALPHA_DEG = 45.0f;              // |α| mínimo para iniciar fallback (subido de 30 para dar más tiempo al LQR)
const float LQR_REARM_ALPHA_DEG = 60.0f;                 // |α| por debajo del cual se re-arma la transición
const float LQR_SERVO_LIMIT_DEG = 90.0f;                 // Saturación del ángulo del servo en el lazo
const float LQR_HARDSTOP_DEG = 120.0f;                   // |θ| por encima del cual se fuerza PWM máxima hacia el centro
const float LQR_PROTECT_ALPHA_DEG = 140.0f;              // |α| por encima del cual LQR apaga el motor (cerca del fondo)

// ── Umbrales PID Servo (modo 2) ──────────────────────────────────────────────
const float PID_ANTIWIND_ERR_DEG = 45.0f;               // |err| máx. para integrar (anti-windup)
const float PID_ANTIWIND_VEL_DPS = 60.0f;               // |vel| máx. para integrar (anti-windup)
const float DEADBAND_FINE_DEG = 0.5f;                   // Dead band modo fino
const float DEADBAND_COARSE_DEG = 1.0f;                 // Dead band modo grueso
const float DEADBAND_CLASSIC_DEG = 0.8f;                // Dead band PID clásico
const float STICTION_ERR_THRESH_DEG = 8.0f;              // |err| mín. para aplicar kick de fricción
const float STICTION_VEL_THRESH_DPS = 15.0f;            // |vel| máx. para aplicar kick de fricción
const float PWM_LIMIT_FINE_NEAR_DEG = 5.0f;             // Cerca del setpoint (modo fino)
const float PWM_LIMIT_FINE_MID_DEG = 10.0f;             // Medio (modo fino)
const int PWM_LIMIT_FINE_NEAR = 30;
const int PWM_LIMIT_FINE_MID = 50;
const int PWM_LIMIT_COARSE_NEAR = 80;                   // PWM máx. si |err| < 20° (modo grueso)
const float PWM_LIMIT_COARSE_NEAR_DEG = 20.0f;
const int PWM_LIMIT_CLASSIC_NEAR = 35;
const int PWM_LIMIT_CLASSIC_MID = 55;
const int PWM_LIMIT_CLASSIC_FAR = 80;

// ── INA219 watchdog ───────────────────────────────────────────────────────────
const unsigned long INA_WATCHDOG_PERIOD_MS = 1000;       // Periodo del watchdog I2C
const unsigned long INA_INIT_RETRY_MS = 5000;            // Periodo de reintento de init

// ── Umbrales swing-up (modo 5) ────────────────────────────────────────────────
const float SWINGUP_TRANSITION_VEL_DPS = 30.0f;          // Velocidad angular máx. para transicionar a LQR (subido de 15)
const float SWINGUP_KICK_DUTY_FRAC = 0.7f;               // Amplitud del kick inicial (% de PWM_MAX)
const unsigned long SWINGUP_KICK_PERIOD_MS = 450;         // Semi-periodo del kick (~frecuencia natural del péndulo)
const float SWINGUP_QUIET_THRESHOLD_RADPS = 0.15f;       // |α̇| por debajo del cual se aplica kick alternante
const float SWINGUP_PROD_DEADZONE = 0.001f;              // Dead-zone para sign(α̇·cos α)

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


void resetLqr() {
  lqr_prevTheta = getPositionDeg();
  lqr_prevAlpha = getPendulumPositionDeg();
  lqr_filteredVelTheta = 0.0f;
  lqr_filteredVelAlpha = 0.0f;
  kalmanReset();
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
  prevPos = getPositionDeg();
  filteredVel = 0.0f;
}
void setMotor(int pwmValue) {
  // Soft saturation: reducir PWM gradualmente cerca de los límites mecánicos del servo.
  // Factor = 1 / (1 + (|pos|/k)^y), con k=120° (umbral BTS7960) y y=2 (agresividad).
  // En pos=0: factor=1.0. En pos=60°: factor=0.80. En pos=90°: factor=0.64.
  float pos_factor = 1.0f / (1.0f + powf(fabsf(lastServoPos) / 200.0f, 2.0f));
  pwmValue = (int)(pwmValue * pos_factor);
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

  // pwmValue == 0: ambos INx a 0

  pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 0);
  pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 0);
}
// setMotorDirect: como setMotor pero SIN soft saturation. Para frenado de emergencia.
void setMotorDirect(int pwmValue) {
  pwmValue = constrain(pwmValue, -255, 255);
  lastPwmCmd = pwmValue;
  if (USE_ENA_PWM) {
    if (pwmValue > 0) { digitalWrite(PIN_IN1, HIGH); digitalWrite(PIN_IN2, LOW); pwmWriteCompat(PIN_ENA, PWM_CH_ENA, pwmValue); return; }
    if (pwmValue < 0) { digitalWrite(PIN_IN1, LOW); digitalWrite(PIN_IN2, HIGH); pwmWriteCompat(PIN_ENA, PWM_CH_ENA, -pwmValue); return; }
    digitalWrite(PIN_IN1, LOW); digitalWrite(PIN_IN2, LOW); pwmWriteCompat(PIN_ENA, PWM_CH_ENA, 0); return;
  }
  if (pwmValue > 0) { pwmWriteCompat(PIN_IN1, PWM_CH_IN1, pwmValue); pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 0); return; }
  if (pwmValue < 0) { pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 0); pwmWriteCompat(PIN_IN2, PWM_CH_IN2, -pwmValue); return; }
  pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 0); pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 0);
}
// brakeMotor: frenado ACTIVO (ambos H-bridge HIGH = cortocircuito del motor).
// Detiene el servo mucho más rápido que coast (PWM=0).
void brakeMotor() {
  if (USE_ENA_PWM) {
    digitalWrite(PIN_IN1, HIGH);
    digitalWrite(PIN_IN2, HIGH);
    pwmWriteCompat(PIN_ENA, PWM_CH_ENA, 255);
    Serial.println("[BRAKE] ENA brake");
    return;
  }
  Serial.printf("[BRAKE] IN1=255 IN2=255 sv=%.1f\n", getRawPositionDeg());
  pwmWriteCompat(PIN_IN1, PWM_CH_IN1, 255);
  pwmWriteCompat(PIN_IN2, PWM_CH_IN2, 255);
}


void setMode(int newMode) {
  // Punto único de cambio de modo. Usado por HTTP y Serial para garantizar
  // que las mismas rutinas de reset y flags se ejecuten siempre.
  if (newMode < 0 || newMode > 7) return;
  mode = newMode;
  swing_recovering = false;  // Reset recovery state al cambiar de modo
  resetPid();
  if (mode == 4) {
    resetLqr();
    lqr_inFallback = false;
    lqr_fallbackMs = 0;
    spinCooldownMs = 0;  // Reset cooldown anti-spin para no interferir con LQR
  }
  if (mode == 0) {
    setMotor(0);
    lqr_inFallback = false;
  }
  if (mode == 5) {
    swing_filteredVelAlpha = 0.0f;
    swing_predictedVelAlpha = 0.0f;  // Reset complementary filter
    prev_alpha_dot_peak = 0.0f;  // Reset peak detection
    swing_maxAngleAchieved = 0.0f;  // Reset adaptive ke_gain
    swing_lastImprovementMs = millis();
    // Solo reset ke_gain si no fue configurado por HTTP
    // (ke_gain fue seteado por cmd?ke= antes de cmd?m=5)
  }
  if (mode == 6) {
    rlAction = 0.0f;
    lqr_prevTheta = getPositionDeg();
    lqr_prevAlpha = getPendulumPositionDeg();
    lqr_filteredVelTheta = 0.0f;
    lqr_filteredVelAlpha = 0.0f;
  }
  if (mode == 7) {
    // Reset RL inference buffer
    rl_obs_idx = 0;
    rl_last_action = 0.0f;
    memset(rl_obs_buf, 0, sizeof(rl_obs_buf));
    lqr_prevTheta = getPositionDeg();
    lqr_prevAlpha = getPendulumPositionDeg();
    lqr_filteredVelTheta = 0.0f;
    lqr_filteredVelAlpha = 0.0f;
    rl_vf_init = false;  // re-init the mode-7 velocity filter
  }
}

void safeStop() {
  setMode(0);
}

// Watchdog del INA219: cada WATCHDOG_PERIOD_MS verificamos que el sensor
// sigue respondiendo en I2C. Si falla, marcamos inaOk=false y reintentamos
// la inicialización con la lista de direcciones candidatas.
static unsigned long lastInaWatchdogMs = 0;
void updateIna219() {
  const unsigned long nowMs = millis();
  if (inaOk && (nowMs - lastInaWatchdogMs) >= INA_WATCHDOG_PERIOD_MS) {
    lastInaWatchdogMs = nowMs;
    // ACK-poll: si el dispositivo no responde, endTransmission() != 0.
    Wire.beginTransmission(inaAddr);
    if (Wire.endTransmission() != 0) {
      inaOk = false;
      Serial.println("[INA219] Watchdog: sensor no responde, reintentando…");
    }
  }
  if (!inaOk) {
    // Reintentar inicialización cada WATCHDOG_PERIOD_MS
    if (nowMs - lastInaWatchdogMs == 0 || (nowMs - lastInaWatchdogMs) >= INA_WATCHDOG_PERIOD_MS) {
      inaOk = initIna219();
      if (inaOk) Serial.println("[INA219] Re-inicializado OK");
    }
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
  // (pendulum setpoint/error removed — no PID pendulum)

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
  // Motor & power
  json += "\"pwm\":" + String(lastPwmCmd) + ",";
  json += "\"gain_scheduling\":" + String(useGainScheduling ? "true" : "false") + ",";
  json += "\"gain_mode\":" + String(gainMode) + ",";
  json += "\"ina_ok\":" + String(inaOk ? "true" : "false") + ",";
  json += "\"v_bus\":" + String(busVoltageV, 3) + ",";
  json += "\"v_shunt_mv\":" + String(shuntVoltagemV, 3) + ",";
  json += "\"i_ma\":" + String(currentmA, 3) + ",";
  json += "\"p_mw\":" + String(powermW, 3) + ",";
  json += "\"servo_ff_pwm\":" + String(servo_ff_pwm, 1) + ",";
  json += "\"vel_alpha\":" + String(velAlpha, 3) + ",";
  json += "\"kf_enabled\":" + String(kf_enabled ? "true" : "false") + ",";
  json += "\"kf_theta\":" + String(kf_x[0], 3) + ",";
  json += "\"kf_alpha\":" + String(kf_x[1], 3) + ",";
  json += "\"kf_dtheta\":" + String(kf_x[2], 2) + ",";
  json += "\"kf_dalpha\":" + String(kf_x[3], 2);
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
volatile bool fsUploadOk = false;
void handleUpdate(AsyncWebServerRequest *request) {
  AsyncWebServerResponse *response = request->beginResponse(
    Update.hasError() ? 500 : 200,
    "application/json",
    Update.hasError() ? "{\"ok\":false}" : "{\"ok\":true}");
  response->addHeader("Access-Control-Allow-Origin", "*");
  request->send(response);
  if (!Update.hasError()) {
    delay(500);
    ESP.restart();
  }
}


void handleState(AsyncWebServerRequest *request) {
  request->send(200, "application/json", getStateJson());
}

// ── RL Endpoints (modo 6) ─────────────────────────────────────────────────
void handleRlState(AsyncWebServerRequest *request) {
  // JSON compacto de baja latencia para el agente RL
  const float theta_rad = getPositionDeg() * DEG_TO_RAD;
  const float alpha_rad = getPendulumPositionDeg() * DEG_TO_RAD;
  const float theta_dot = lqr_filteredVelTheta * DEG_TO_RAD;  // deg/s -> rad/s
  const float alpha_dot = lqr_filteredVelAlpha * DEG_TO_RAD;  // deg/s -> rad/s
  String json = "{";
  json += "\"th\":" + String(theta_rad, 4) + ",";
  json += "\"al\":" + String(alpha_rad, 4) + ",";
  json += "\"thd\":" + String(theta_dot, 4) + ",";
  json += "\"ald\":" + String(alpha_dot, 4);
  json += "}";
  request->send(200, "application/json", json);
}

void handleRlCmd(AsyncWebServerRequest *request) {
  if (request->hasParam("a")) {
    rlAction = constrain(request->getParam("a")->value().toFloat(), -1.0f, 1.0f);
    lastCommandMs = millis();
  }
  if (request->hasParam("r")) {
    resetPcnt(pcnt_servo_unit);
    resetPcnt(pcnt_pendulum_unit);
    positionOffsetDeg = 0.0f;
    pendulumOffsetDeg = 0.0f;
    lqr_filteredVelTheta = 0.0f;
    lqr_filteredVelAlpha = 0.0f;
    lqr_prevTheta = getPositionDeg();
    lqr_prevAlpha = getPendulumPositionDeg();
    rlAction = 0.0f;
    setMotor(0);
    lastCommandMs = millis();
  }
  if (request->hasParam("z")) {
    zeroPositionHere();
    lqr_prevTheta = 0.0f;
    lastCommandMs = millis();
  }
  if (request->hasParam("zp")) {
    zeroPendulumHere();
    lqr_prevAlpha = 0.0f;
    lastCommandMs = millis();
  }
  if (request->hasParam("scale")) {
    rl_pwm_scale = constrain(request->getParam("scale")->value().toFloat(), 0.0f, 1.0f);
    lastCommandMs = millis();
  }
  request->send(200, "application/json", "{\"ok\":true}");
}

void handleCmd(AsyncWebServerRequest *request) {
  if (request->hasParam("m")) {
    const int m = request->getParam("m")->value().toInt();
    if (m >= 0 && m <= 7) {
      setMode(m);
      lastCommandMs = millis();
    }
  }

  if (request->hasParam("s")) {
    setpoint_deg = request->getParam("s")->value().toFloat();
    resetPid();
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
    lastCommandMs = millis();
  }

  if (request->hasParam("o")) {
    positionOffsetDeg = request->getParam("o")->value().toFloat();
    resetPid();
    lastCommandMs = millis();
  }

  if (request->hasParam("op")) {
    pendulumOffsetDeg = request->getParam("op")->value().toFloat();
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
    resetPid();
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
  if (request->hasParam("ff")) {
    servo_ff_pwm = request->getParam("ff")->value().toFloat();
  }
  if (request->hasParam("va")) {
    velAlpha = constrain(request->getParam("va")->value().toFloat(), 0.01f, 1.0f);
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

  if (request->hasParam("kf")) {
    kf_enabled = (request->getParam("kf")->value().toInt() != 0);
    if (kf_enabled) kalmanReset();
  }
  if (request->hasParam("ke")) {
    ke_gain = request->getParam("ke")->value().toFloat();
  }
  if (request->hasParam("sp")) {
    swingupPwmMax = constrain(request->getParam("sp")->value().toInt(), 10, 100);
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
  if (request->hasParam("tp")) {
    const unsigned long v = request->getParam("tp")->value().toInt();
    if (v >= 50 && v <= 5000) {
      telemetryPeriodMs = v;
    }
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
  // IP estática: 192.168.100.50
  IPAddress local_IP(192, 168, 100, 50);
  IPAddress gateway(192, 168, 100, 1);
  IPAddress subnet(255, 255, 255, 0);
  IPAddress dns(8, 8, 8, 8);
  WiFi.config(local_IP, gateway, subnet, dns);
  WiFi.begin(staSsid, staPass);
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
  Serial.println("Modos: m0(stop) m1(PWM) m2(PID servo) m4(LQR) m5(Swing-up)");
  Serial.println("Servo: s<deg>, kp<val>, ki<val>, kd<val>, o<deg>, z, ed<1|-1>, cpr<val>");
  Serial.println("Pendulo: op<deg>, zp, edp<1|-1>, cprp<val>");
  Serial.println("LQR: lqr1<val>, lqr2<val>, lqr3<val>, lqr4<val>");
  Serial.println("GainSched: g1(on) g0(off) gf<val> gi<val> gd<val> (fino) GC<val> GI<val> Gd<val> (grueso)");
  Serial.println("Motor: p-255..255 (modo 1), x(stop), r(reset)");
  Serial.println("Info: ?(estado), i(IP), n(ina scan)");
  Serial.println("WiFi: wifi_ssid<TuRed>, wifi_pass<TuClave>, wifi_info");
}

void processSerialCommand() {
  // Leer caracter por caracter con timeout corto. Esto evita que lazo de
  // control a 500 Hz quede bloqueado cuando un usuario envía una línea
  // sin terminador (readStringUntil por defecto espera hasta 1 s).
  static char buf[64];
  size_t idx = 0;
  const unsigned long tStart = millis();
  while (Serial.available() > 0 && (millis() - tStart) < 50) {
    const int c = Serial.read();
    if (c < 0) break;
    if (c == '\n' || c == '\r') {
      if (idx > 0) break;        // línea completa
      continue;                  // ignorar CRLF al inicio
    }
    if (idx < sizeof(buf) - 1) {
      buf[idx++] = static_cast<char>(c);
    } else {
      // overflow: descartar resto de la línea y procesar lo que hay
      while (Serial.read() >= 0) { /* flush */ }
      break;
    }
  }
  if (idx == 0) return;          // no había línea completa
  buf[idx] = '\0';
  String cmd(buf);
  cmd.trim();
  if (cmd.length() == 0) return;
  const char c = cmd.charAt(0);
  switch (c) {
    case 'm':
      {
        const int m = cmd.substring(1).toInt();
        // Modes 0,1,2,4,5,6,7 (mode 3 / pendulum-PID was removed in v1.34).
        // Upper bound was 5, which silently blocked selecting the RL modes
        // (6 = RL over HTTP, 7 = on-device RL) from the serial console.
        if (m >= 0 && m <= 7) {
          setMode(m);
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
        // s<deg> — servo setpoint
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
      break;
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
    // BTS7960 enable: R_EN/L_EN habilitados via GPIO25
    pinMode(PIN_ENA, OUTPUT);
    digitalWrite(PIN_ENA, HIGH);
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
  // Coexistencia AP+STA: el ESP32 tiene UNA sola radio, por lo que el SoftAP
  // debe operar en el MISMO canal que el router STA. Si se fuerza un canal
  // distinto al del router, el STA no logra autenticar (Reason 2 AUTH_EXPIRE).
  // Detectamos el canal del SSID objetivo por escaneo; fallback a 6.
  uint8_t apChannel = 6;
  if (ENABLE_STA && staSsid[0] != '\0') {
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      if (WiFi.SSID(i) == staSsid) { apChannel = WiFi.channel(i); break; }
    }
    WiFi.scanDelete();
  }
  WiFi.softAP(AP_SSID, AP_PASS, apChannel, false, 4);  // canal = STA, SSID visible, max 4
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
  server.on("/rl_state", HTTP_GET, handleRlState);
  server.on("/rl_cmd", HTTP_GET, handleRlCmd);
  server.on("/rl_state", HTTP_OPTIONS, handleOptions);
  server.on("/rl_cmd", HTTP_OPTIONS, handleOptions);
  server.on("/update", HTTP_POST, handleUpdate,
    [](AsyncWebServerRequest *request, const String& filename, size_t index,
       uint8_t *data, size_t len, bool final) {
      if (index == 0) {
        Serial.printf("[OTA Web] Recibiendo: %s\n", filename.c_str());
        setMode(0);
        setMotor(0);
        if (!Update.begin(UPDATE_SIZE_UNKNOWN)) {
          Update.printError(Serial);
        }
      }
      if (len) {
        if (Update.write(data, len) != len) {
          Update.printError(Serial);
        }
      }
      if (final) {
        if (Update.end(true)) {
          Serial.printf("[OTA Web] Completado: %u bytes\n", index + len);
        } else {
          Update.printError(Serial);
        }
      }
    });
  server.on("/fs", HTTP_POST,
    [](AsyncWebServerRequest *request) {
      AsyncWebServerResponse *response = request->beginResponse(
        fsUploadOk ? 200 : 500,
        "application/json",
        fsUploadOk ? "{\"ok\":true}" : "{\"ok\":false}");
      response->addHeader("Access-Control-Allow-Origin", "*");
      request->send(response);
    },
    [](AsyncWebServerRequest *request, const String& filename, size_t index,
       uint8_t *data, size_t len, bool final) {
      if (index == 0) {
        fsUploadOk = false;
        Serial.printf("[SPIFFS] Subiendo: %s\n", filename.c_str());
        String path = "/" + filename;
        request->_tempFile = SPIFFS.open(path, "w");
      }
      if (request->_tempFile) {
        request->_tempFile.write(data, len);
      }
      if (final) {
        if (request->_tempFile) {
          request->_tempFile.close();
          Serial.printf("[SPIFFS] OK: %s (%u bytes)\n", filename.c_str(), index + len);
          fsUploadOk = true;
        } else {
          Serial.printf("[SPIFFS] ERROR: %s\n", filename.c_str());
          fsUploadOk = false;
        }
      }
    });
  server.on("/restart", HTTP_GET, [](AsyncWebServerRequest *request) {
    request->send(200, "application/json", "{\"ok\":true,\"restarting\":true}");
    delay(500);
    ESP.restart();
  });
  server.on("/format", HTTP_GET, [](AsyncWebServerRequest *request) {
    Serial.println("[SPIFFS] Formateando...");
    bool ok = SPIFFS.format();
    Serial.printf("[SPIFFS] Formato: %s\n", ok ? "OK" : "ERROR");
    request->send(200, "application/json", ok ? "{\"ok\":true,\"formatted\":true}" : "{\"ok\":false}");
    delay(500);
    ESP.restart();
  });
  // Serve static files from SPIFFS (chart.min.js, etc.)
  server.serveStatic("/", SPIFFS, "/").setDefaultFile("index.html");
  server.begin();

  lastControlUs = micros();
  lastTelemetryMs = millis();
  lastCommandMs = millis();

  Serial.println("=== QUBE ESP32 + BTS7960 + INA219 ===");
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

  // ── ArduinoOTA (flasheo por WiFi) ────────────────────────────────────────
  ArduinoOTA.setHostname("qube-esp32");
  ArduinoOTA.onStart([]() {
    setMode(0);
    setMotor(0);
    Serial.println("[OTA] Iniciando actualización...");
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\n[OTA] Actualización completada.");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("[OTA] %u%%\r", (progress / (total / 100)));
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("[OTA] Error[%u]: ", error);
  });
  ArduinoOTA.begin();
  Serial.println("[OTA] Listo para actualización por WiFi");
}

void loop() {
  ArduinoOTA.handle();
  ws.cleanupClients();
  yield();  // Alimentar watchdog timer para evitar crash por loop largo

  if (Serial.available()) {
    processSerialCommand();
  }
  const unsigned long nowUs = micros();
  if ((nowUs - lastControlUs) >= CONTROL_PERIOD_US) {
    lastControlUs += CONTROL_PERIOD_US;

    const float pos = getPositionDeg();
    lastServoPos = pos;  // Para soft saturation en setMotor()
    const float pendPosRaw = getPendulumPositionDeg();  // Sin wrap (para velocidad)
    const float pendPos = fmod(pendPosRaw + 180.0f, 360.0f) - 180.0f;  // Wrap a [-180, 180]
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
      if (absErr < PID_ANTIWIND_ERR_DEG && abs(filteredVel) < PID_ANTIWIND_VEL_DPS) {
        integralTerm += err * dt;
        integralTerm = constrain(integralTerm, -INTEGRAL_LIMIT, INTEGRAL_LIMIT);
      } else {
        integralTerm = 0.0f;
      }

      // ── Velocidad filtrada (EMA) ───────────────────────────────────────
      const float rawVel = -(pos - prevPos) / dt;
      filteredVel = velAlpha * rawVel + (1.0f - velAlpha) * filteredVel;
      prevPos = pos;
      // ── PID output ─────────────────────────────────────────────────────
      float u = Kp * err + Ki * integralTerm + Kd * filteredVel;
      int pwm = (int)(MOTOR_DIR * u);

      // ── Dead band ──────────────────────────────────────────────────────
      const float deadBand = useGainScheduling ? (gainMode == 0 ? DEADBAND_FINE_DEG : DEADBAND_COARSE_DEG) : DEADBAND_CLASSIC_DEG;
      if (absErr <= deadBand) {
        pwm = 0;
      }
      // ── Feedforward gravitacional: compensa torque proporcional a sin(pos) ──
      // Modelo: τ_gravedad ∝ sin(ángulo). Compensa la soft saturation que
      // reduce PWM a medida que el brazo se aleja del centro.
      // ff=15 → ~7.5 PWM a 30°, ~13 PWM a 60°, ~15 PWM a 90°.
      // Calibrar: subir ff hasta que el SS error se minimice.
      const float ff = servo_ff_pwm * sinf(pos * DEG_TO_RAD);
      pwm += (int)(MOTOR_DIR * ff);
      // ── Kick mínimo para vencer fricción ───────────────────────────────
      if (abs(pwm) < PWM_MIN && absErr > STICTION_ERR_THRESH_DEG && abs(filteredVel) < STICTION_VEL_THRESH_DPS) {
        pwm = (pwm >= 0) ? PWM_MIN : -PWM_MIN;
      }

      // ── Limitación dinámica de PWM ─────────────────────────────────────
      int pwmLimit = PWM_MAX;
      if (useGainScheduling) {
        if (gainMode == 0) {
          // Modo fino: PWM acotado para movimientos suaves
          if (absErr < PWM_LIMIT_FINE_NEAR_DEG) pwmLimit = PWM_LIMIT_FINE_NEAR;
          else if (absErr < PWM_LIMIT_FINE_MID_DEG) pwmLimit = PWM_LIMIT_FINE_MID;
        } else {
          // Modo grueso: PWM libre para respuesta rápida
          if (absErr < PWM_LIMIT_COARSE_NEAR_DEG) pwmLimit = PWM_LIMIT_COARSE_NEAR;
        }
      } else {
        // PID clásico: escalonamiento original
        if (absErr < PWM_LIMIT_FINE_NEAR_DEG) pwmLimit = PWM_LIMIT_CLASSIC_NEAR;
        else if (absErr < PWM_LIMIT_FINE_MID_DEG) pwmLimit = PWM_LIMIT_CLASSIC_MID;
        else if (absErr < PWM_LIMIT_COARSE_NEAR_DEG) pwmLimit = PWM_LIMIT_CLASSIC_FAR;
      }

      pwm = constrain(pwm, -pwmLimit, pwmLimit);
      setMotor(pwm);
    } else if (mode == 4) {
      // ── Catch mode: frenar péndulo al entrar a LQR ────────────────────
      // Direction-locked proportional braking: locks brake direction on entry
      // to prevent overshoot when pendulum crosses zero velocity.
      int pwm = 0;
      if (lqr_catchMs > 0 && (millis() - lqr_catchMs) < LQR_CATCH_MS) {
        float rawVelForCatch = -(pendPosRaw - lqr_prevAlpha) / dt;
        // Lock brake direction on first call (use static variable)
        static float lockedBrakeDir = 0.0f;
        if ((millis() - lqr_catchMs) < 10) {  // First ~10ms: lock direction
          lockedBrakeDir = (rawVelForCatch > 0) ? 1.0f : -1.0f;
        }
        // Proportional braking with locked direction: ±25 PWM max, gain suave
        float brake_pwm = lockedBrakeDir * fabsf(rawVelForCatch) * 0.10f;
        pwm = constrain((int)brake_pwm, -25, 25);
        setMotor(pwm);
        return;
      }
      lqr_catchMs = 0;
      const float theta = constrain(pos, -LQR_SERVO_LIMIT_DEG, LQR_SERVO_LIMIT_DEG);
      const float alpha_raw = pendPosRaw;
      // alpha continuo: distancia mínima al vertical (±180°) usando aritmética modular.
      // Evita la discontinuidad de ±180° cuando pendPos cruza el vertical.
      // alpha = 0 en vertical, negativo debajo, positivo arriba (cruzado).
      float alpha = fmodf(alpha_raw - 180.0f, 360.0f);
      if (alpha < -180.0f) alpha += 360.0f;
      else if (alpha > 180.0f) alpha -= 360.0f;
      alpha = -alpha;  // Invertir: negativo=debajo, positivo=arriba
      // ── Filtro de Kalman: Predict + Update ─────────────────────────
      if (kf_enabled) {
        kalmanPredict((float)lastPwmCmd / (float)PWM_MAX);
        kalmanUpdate(theta, alpha_raw);
      }
      // Velocidades con filtro EMA (siempre se calculan como fallback)
      const float rawVelTheta = -(theta - lqr_prevTheta) / dt;
      const float rawVelAlpha = -(alpha_raw - lqr_prevAlpha) / dt;
      lqr_filteredVelTheta = velAlpha * rawVelTheta + (1.0f - velAlpha) * lqr_filteredVelTheta;
      lqr_filteredVelAlpha = VEL_ALPHA_PEND * rawVelAlpha + (1.0f - VEL_ALPHA_PEND) * lqr_filteredVelAlpha;
      lqr_prevTheta = theta;
      lqr_prevAlpha = alpha_raw;  // Guardar crudo para siguiente velocidad

      // Gain scheduling en 3 tiers: base → NEAR → VERY_NEAR
      float k2_eff = lqr_K2;
      float k4_eff = lqr_K4;
      if (abs(alpha) < LQR_VERY_NEAR_DEG) {
        k2_eff = LQR_K2_VERY_NEAR;
        k4_eff = LQR_K4_VERY_NEAR;
      } else if (abs(alpha) < LQR_NEAR_DEG) {
        k2_eff = LQR_K2_NEAR;
        k4_eff = LQR_K4_NEAR;
      }
      // Usar velocidades: KF si habilitado, EMA como fallback
      float velTheta_ctrl = kf_enabled ? kf_x[2] : lqr_filteredVelTheta;
      float velAlpha_ctrl = kf_enabled ? kf_x[3] : lqr_filteredVelAlpha;
      // Velocity-dependent gain scaling: boost damping for high-velocity entries
      float vel_alpha_dps = fabsf(velAlpha_ctrl) * RAD_TO_DEG;
      if (vel_alpha_dps > 200.0f) {
        float vel_scale = 1.0f + (vel_alpha_dps - 200.0f) / 300.0f;
        vel_scale = constrain(vel_scale, 1.0f, 2.0f);
        k4_eff *= vel_scale;
      }

      // LQR: u = -(K1*theta + K2*alpha + K3*theta_dot + K4*alpha_dot)
      // alpha=0 es la posición vertical (invertido)
      float u = -(lqr_K1 * theta + k2_eff * alpha + lqr_K3 * velTheta_ctrl + k4_eff * velAlpha_ctrl);

      // Energy dissipation dentro de LQR: agregar término de amortiguamiento
      // proporcional a la velocidad angular del péndulo. Esto reduce el ciclo
      // límite alrededor de ±180° sin afectar la estabilidad del LQR.
      if (abs(alpha) < LQR_NEAR_DEG) {
        u -= LQR_DAMPING_GAIN * velAlpha_ctrl;
      }

      pwm = constrain((int)(MOTOR_DIR * u), -70, 70);

      // Servo centering en LQR: mantener el servo cerca del centro para
      // maximizar el rango de actuación y reducir oscilación del servo.
      // Centering agresivo: si el servo se aleja del centro, la fuerza de
      // retorno crece linealmente. Esto previene que el servo pegue contra
      // el stop mecánico y cause brownout.
      {
        // Centering: solo activo 2+ segundos después del catch.
        // Durante los primeros 2s, el LQR necesita control total del servo
        // para estabilizar el péndulo sin interferencia del centering.
        float centering_sec = (millis() - lqr_catchMs) / 1000.0f;
        if (centering_sec > 2.0f) {
          float absTheta = fabsf(theta);
          // Ramp: centering crece gradualmente de 0 a full en 2s adicionales
          float ramp = constrain((centering_sec - 2.0f) / 2.0f, 0.0f, 1.0f);
          float centering_gain = 0.5f * ramp;
          if (absTheta > 40.0f) centering_gain = 1.0f * ramp;
          else if (absTheta > 20.0f) centering_gain = 0.75f * ramp;
          float centering = -centering_gain * theta;
          centering = constrain(centering, -25.0f, 25.0f);
          pwm += (int)centering;
        }
      }

      // Límite de PWM del servo en LQR.
      // CRITICO: solo forzar centering cuando el péndulo NO está cerca
      // de la vertical. Si el péndulo está arriba, el LQR necesita
      // control completo del servo para mantener el equilibrio.
      {
        float absAlpha = fabsf(alpha);
        float absTheta = fabsf(theta);
        bool pendulumNearVertical = (absAlpha < 30.0f);  // alpha≈0 = vertical arriba
        int servoPwmLimit = 70;

        if (absTheta > 70.0f && !pendulumNearVertical) {
          // FORZAR centro solo cuando el péndulo NO está arriba.
          // Cuando el péndulo está en la vertical, dejar al LQR decidir.
          float center_dir = (theta > 0) ? -1.0f : 1.0f;
          pwm = (int)(center_dir * 70.0f);
          servoPwmLimit = 70;
        } else if (absTheta > 70.0f && pendulumNearVertical) {
          // Péndulo arriba + servo lejos: limitar PWM que se ALEJA del centro,
          // pero permitir PWM que va AL centro. No reemplazar el output del LQR.
          float stop_dir = (theta > 0) ? 1.0f : -1.0f;
          float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
          if (pwm_dir == stop_dir) {
            // PWM va contra stop: limitar fuertemente
            servoPwmLimit = 30;
          } else {
            // PWM va al centro: permitir hasta 70
            servoPwmLimit = 70;
          }
        } else if (absTheta > 50.0f) {
          // Región transicional: limitar PWM que se aleja
          float stop_dir = (theta > 0) ? 1.0f : -1.0f;
          float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
          if (pwm_dir == stop_dir) {
            servoPwmLimit = (int)(70.0f - (absTheta - 50.0f) * (70.0f / 20.0f));
            servoPwmLimit = constrain(servoPwmLimit, 10, 70);
          }
        }
        pwm = constrain(pwm, -servoPwmLimit, servoPwmLimit);
      }

      // Protección: apagar motor si el péndulo acumuló rotación (raw>250°).
      // Usar raw en vez de alpha (wrapped) que cruza ±180° discontinuamente.
      if (fabsf(pendPosRaw) > 250.0f) {
        pwm = 0;
      }

      // Fallback: si raw>360°, el péndulo hizo una vuelta → LQR falló.
      // Fallback inmediato + reset offset para que swing-up arranque limpio.
      if (fabsf(pendPosRaw) > 360.0f) {
        if (!lqr_inFallback) {
          pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
          prevPosPend = 0.0f;
          pendPosRawPrev = 0.0f;
          setMode(5);
          lqr_inFallback = true;
          Serial.printf("LQR: FALLBACK (raw=%.1f, offset reset)\n", pendPosRaw);
        }
      } else if (fabsf(pendPosRaw) < 45.0f) {
        // Rearm: péndulo cerca del fondo, listo para nuevo intento
        lqr_fallbackMs = 0;
        lqr_inFallback = false;
      }

      // HARD CLAMP: cuando |pos| > 100°, solo permitir PWM hacia centro.
      // NO override si el PWM ya va al centro (forced centering lo hace).
      if (fabsf(pos) > 100.0f) {
        float stop_dir = (pos > 0) ? 1.0f : -1.0f;
        float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
        if (pwm_dir == stop_dir) {
          pwm = (int)(stop_dir * -30.0f);  // Solo cortar si va contra stop
        }
        // Si va al centro → permitir sin cambio
      } else if (fabsf(pos) > 85.0f) {
        // Direction-aware: solo cortar PWM que empuja contra el stop.
        // PWM que va AL centro se permite SIN reducción.
        float stop_dir = (pos > 0) ? 1.0f : -1.0f;
        float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
        if (pwm_dir == stop_dir) {
          pwm = 0;  // Empuja contra stop → cortar
        }
        // Si va al centro → permitir sin restricción (para recuperar)
      } else if (fabsf(pos) > 70.0f) {
        // Cortar solo el PWM que empuja hacia el stop (direction-aware)
        float stop_dir = (pos > 0) ? 1.0f : -1.0f;
        float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
        if (pwm_dir == stop_dir) {
          float factor = 1.0f - (fabsf(pos) - 70.0f) / 15.0f;
          pwm = (int)(pwm * constrain(factor, 0.0f, 1.0f));
        }
      }
      // ── Voltage-based brownout protection (LQR) ───────────────────────
      if (inaOk && busVoltageV > 0.1f) {
        if (busVoltageV < 12.5f) {
          pwm = 0;
          setMotor(0);
          return;
        } else if (busVoltageV < 13.5f) {
          float factor = (busVoltageV - 12.5f) / 1.0f;
          pwm = (int)(pwm * constrain(factor, 0.3f, 1.0f));
        }
      }
      pwm = constrain(pwm, -PWM_MAX, PWM_MAX);
      setMotor(pwm);

    } else if (mode == 5) {
    // ══════════════════════════════════════════════════════════════════════════
    // MODO 5: Swing-up por energia con kick continuo
      int pwm = 0;
      // ── HARD SAFETY: frenar si servo > 85° (prevenir atasco) ──────
      {
        if (fabsf(pos) > 90.0f) {
          float brake_dir = (pos > 0) ? -1.0f : 1.0f;
          setMotor((int)(brake_dir * 70.0f));
          return;
        }
      }
      swing_predictedVelAlpha = swing_filteredVelAlpha;  // Sync prediction with blended result
      const float alpha_dot = swing_filteredVelAlpha;  // Filtrado para energy pumping
      prevPosPend = pendPosRaw;

      // ── Detección de spinning ──────────────────────────────────────────
      // Si el péndulo acumula >360° en crudo entre samples, está girando.
      float rawDelta = fabsf(pendPosRaw - pendPosRawPrev);
      bool spinning = (rawDelta > 200.0f);  // >200° entre samples = spinning rápido
      pendPosRawPrev = pendPosRaw;

      // Contador de vueltas: si |pendPosRaw| > 360° (1 vuelta), forzar frenado
      if (fabsf(pendPosRaw) > 360.0f) spinning = true;

      const float mgl = PEND_MASS * GRAVITY * PEND_LENGTH;

      // Cooldown post-spin: aplicar freno durante SPIN_COOLDOWN_MS después de detectar spinning
      bool inCooldown = (spinCooldownMs > 0) && ((millis() - spinCooldownMs) < SPIN_COOLDOWN_MS);

      if (spinning || inCooldown) {
        // ── Anti-spin: freno máximo + reset offset ──────────────────────
        if (spinning) {
          // Reset offset INMEDIATAMENTE para que pendPos refleje posición real
          pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
          prevPosPend = 0.0f;
          pendPosRawPrev = 0.0f;
          swing_filteredVelAlpha = 0.0f;
          spinCooldownMs = millis();  // Iniciar cooldown
          Serial.printf("Swing-up: SPIN detected, raw=%.1f, braking + cooldown\n", pendPosRaw);
        }

        // Freno máximo (durante todo el cooldown)
        int brake_pwm = (alpha_dot > 0.0f) ? -PWM_MAX : PWM_MAX;
        pwm = brake_pwm;
      } else {
        // ══════════════════════════════════════════════════════════════════
        // TRANSICION A LQR: solo cuando el péndulo está cerca de la vertical.
        // Transicion a LQR cuando el pendulo esta dentro de ±60° de vertical.
        // Vertical = |pendPos| ≈ 180°. ±60° = |pendPos| > 120°.
        // ══════════════════════════════════════════════════════════════════
        float vel_raw_dps = fabsf(alpha_dot) * RAD_TO_DEG;
        bool nearVertical = fabsf(pendPos) > 120.0f;
        bool verySlow = vel_raw_dps < 30.0f;
        bool canTransition = nearVertical && verySlow;

        // Peak detection: detect position peak (alpha_dot crosses zero)
        bool atPeak = (prev_alpha_dot_peak > 0.0f && alpha_dot <= 0.0f) ||
                       (prev_alpha_dot_peak < 0.0f && alpha_dot >= 0.0f);
        prev_alpha_dot_peak = alpha_dot;

        // At position peak AND near vertical
        bool atPeakTransition = atPeak && (180.0f - fabsf(pendPos) < 60.0f);

        // FORCED transition
        bool forcedTransition = fabsf(pendPos) > 125.0f;

        // Energy-based
        const float mgl_eb = PEND_MASS * GRAVITY * PEND_LENGTH;
        const float alpha_eb_rad = pendPosRaw * DEG_TO_RAD;
        float E_current = 0.5f * PEND_INERTIA * alpha_dot * alpha_dot +
                          mgl_eb * (1.0f - cosf(alpha_eb_rad));
        float E_target_eb = 2.0f * mgl_eb;
        bool energyReady = (E_target_eb > 0.0f) &&
                           (fabsf(E_current - E_target_eb) / E_target_eb < 0.10f) &&
                           fabsf(pendPos) > 120.0f &&
                           (vel_raw_dps < 60.0f);


        if (canTransition || atPeakTransition || forcedTransition || energyReady) {
          setMode(4);
          lqr_inFallback = false;
          lqr_catchMs = millis();
          spinCooldownMs = 0;
          Serial.printf("LQR TRANS (pend=%.1f vel=%.1f peak=%d forced=%d energy=%.3f raw=%.1f)\n", pendPos, vel_raw_dps, atPeakTransition, forcedTransition, E_current / E_target_eb, pendPosRaw);
          pwm = 0;
          setMotor(pwm);
          return;
        }

        // ── Recovery: péndulo cruzó la vertical sin transicionar ───────
        if (swing_recovering) {
          // Recovery con frenado proporcional a velocidad (preserva algo de energía)
          float recover_brake = -0.4f * alpha_dot;  // Frenado proporcional
          pwm = constrain((int)(MOTOR_DIR * recover_brake * swingupPwmMax), -swingupPwmMax, swingupPwmMax);
          if (fabsf(pendPos) < SWING_RECOVERY_THRESHOLD) {
            swing_recovering = false;
            // Reset offset al salir de recovery para que raw esté en [-180,180]
            pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
            prevPosPend = 0.0f;
            pendPosRawPrev = 0.0f;
            swing_filteredVelAlpha = 0.0f;
            swing_predictedVelAlpha = 0.0f;
            Serial.printf("Swing-up: recovery COMPLETE (pend=%.1f)\n", pendPos);
          }
        } else if (fabsf(pendPosRaw) > 180.0f) {
          // El péndulo cruzó la vertical sin transicionar → recovery.
          // Reset offset para que raw se mantenga acotado.
          swing_recovering = true;
          pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
          prevPosPend = 0.0f;
          pendPosRawPrev = 0.0f;
          swing_filteredVelAlpha = 0.0f;
          swing_predictedVelAlpha = 0.0f;
          Serial.printf("Swing-up: RECOVERY START (raw=%.1f, pend=%.1f, vel=%.1f)\n", pendPosRaw, pendPos, vel_raw_dps);
        } else if (fabsf(pendPosRaw) > 165.0f) {
          // ── Damping: disipar energía desde 165° hasta la vertical ──
          float dampStrength = (fabsf(pendPosRaw) - 165.0f) / 15.0f;
          dampStrength = constrain(dampStrength, 0.0f, 1.0f);
          float damping = -(0.3f + 0.7f * dampStrength) * alpha_dot;
          pwm = constrain((int)(MOTOR_DIR * damping * swingupPwmMax), -swingupPwmMax, swingupPwmMax);
        } else {
          // ── Resonant pumping: servo oscila a frecuencia del péndulo ────
          if (fabsf(alpha_dot) < SWINGUP_QUIET_THRESHOLD_RADPS) {
            // Péndulo quieto: kick sinusoidal para iniciar oscilación
            float t_sec = millis() / 1000.0f;
            float kick_ref = 40.0f * sinf(2.0f * PI * 2.0f * t_sec);
            float error = kick_ref - pos;
            pwm = (int)(MOTOR_DIR * error * 3.0f);
            pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
          } else {
            // Péndulo oscilando: resonant pumping
            float pump_ref = alpha_dot * 120.0f;
            pump_ref = constrain(pump_ref, -70.0f, 70.0f);  // ±70° (hard safety a 85° protege)
            // Adaptive gain: boost when pendulum stalls
            float currentAbsAngle = fabsf(pendPos);
            if (currentAbsAngle > swing_maxAngleAchieved + 5.0f) {
              swing_maxAngleAchieved = currentAbsAngle;
              swing_lastImprovementMs = millis();
              ke_gain = KE_GAIN_BASE;
            } else if ((millis() - swing_lastImprovementMs) > STALL_TIMEOUT_MS) {
              ke_gain = KE_GAIN_BOOST;
            }

            float error = pump_ref - pos;
            float Kp_pump = ke_gain * 4.0f;
            pwm = (int)(MOTOR_DIR * error * Kp_pump);
            pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
          }
        }
      }

      // ── Voltage-based brownout protection ──────────────────────────────
      // Read INA219 voltage (updated at telemetry rate, ~100ms)
      // If v_bus drops, reduce PWM proportionally to prevent brownout.
      // Normal: ~14.8V. Brownout threshold: ~12.5V (ESP32 minimum ~3.0V on 5V rail).
      if (inaOk && busVoltageV > 0.1f) {
        if (busVoltageV < 12.5f) {
          // Critical: motor stalled against hard stop → cut completely
          pwm = 0;
          setMotor(0);
          return;
        } else if (busVoltageV < 13.5f) {
          // Warning: reduce PWM to 50% to prevent further drop
          float factor = (busVoltageV - 12.5f) / 1.0f;  // 0.0 at 12.5V, 1.0 at 13.5V
          pwm = (int)(pwm * constrain(factor, 0.3f, 1.0f));
        }
      }

      pwm = constrain(pwm, -PWM_MAX, PWM_MAX);
      setMotor(pwm);
    } else if (mode == 6) {
    // ══════════════════════════════════════════════════════════════════════════
    // MODO 6: Deep RL — recibe acción por HTTP, aplica PWM directo
    // Endpoints: GET /rl_state (obs), GET /rl_cmd?a=X (action)
    // ══════════════════════════════════════════════════════════════════════════
      // ── Action clamping: restrict RL to push TOWARD center when far ──
      // When |theta| > SAFE_RANGE, the RL action is clamped so it can only
      // push the servo back toward 0°. This prevents the policy from slamming
      // into mechanical stops.  Beyond HARD_LIMIT, full centering PWM.
      const float SAFE_RANGE = 80.0f;   // RL acts freely within ±80°
      const float HARD_LIMIT = 110.0f;  // Beyond ±110°, pure centering

      if (fabsf(pos) > HARD_LIMIT) {
        // Pure centering — RL action ignored entirely
        int center_pwm = (int)(-pos * 3.0f);
        setMotorDirect(constrain(center_pwm, -PWM_MAX, PWM_MAX));
        lqr_prevTheta = pos;
        lqr_prevAlpha = pendPosRaw;
        return;
      }

      // Compute velocities
      const float theta_rl = pos;
      const float alpha_rl_raw = pendPosRaw;
      const float rawVelTheta_rl = -(theta_rl - lqr_prevTheta) / dt;
      const float rawVelAlpha_rl = -(alpha_rl_raw - lqr_prevAlpha) / dt;
      lqr_filteredVelTheta = velAlpha * rawVelTheta_rl + (1.0f - velAlpha) * lqr_filteredVelTheta;
      lqr_filteredVelAlpha = VEL_ALPHA_PEND * rawVelAlpha_rl + (1.0f - VEL_ALPHA_PEND) * lqr_filteredVelAlpha;
      lqr_prevTheta = theta_rl;
      lqr_prevAlpha = alpha_rl_raw;

      int rl_pwm = (int)(rlAction * PWM_MAX);
      rl_pwm = constrain(rl_pwm, -PWM_MAX, PWM_MAX);

      if (fabsf(pos) > SAFE_RANGE) {
        // Clamp: only allow action that pushes TOWARD center
        if (pos > 0 && rl_pwm > 0) rl_pwm = 0;  // positive pos, block positive action
        if (pos < 0 && rl_pwm < 0) rl_pwm = 0;  // negative pos, block negative action
        // Add centering assist
        int center_pwm = (int)(-pos * 2.0f);
        rl_pwm += constrain(center_pwm, -PWM_MAX, PWM_MAX);
        rl_pwm = constrain(rl_pwm, -PWM_MAX, PWM_MAX);
      }

      setMotor(rl_pwm);
    } else if (mode == 7) {
    // ══════════════════════════════════════════════════════════════════════════
    // MODO 7: On-device RL inference — forward pass en ESP32
    // Red entrenada: [36→64→64→1] ReLU, tanh (SB3 SAC deterministic = tanh(mu))
    // Observación: 4 pasos × [θ, α, cosθ, sinθ, cosα, sinα, θ̇, α̇, action]
    // Replica EXACTA del env Python corregido (QubeRealEnv, bring-up 2026-06-22):
    //   theta tal cual; alpha y alpha_dot INVERTIDOS (encoder péndulo espejado vs
    //   sim) y alpha envuelta a [-pi,pi]; la acción se NIEGA hacia el motor (torque
    //   espejado) pero el historial guarda la acción de política sin negar.
    // ══════════════════════════════════════════════════════════════════════════
      // Sub-gate the RL policy to 50 Hz (the training rate). The outer control
      // loop runs at 500 Hz (CONTROL_PERIOD_US=2000); inference must tick every
      // 20 ms or the 50Hz-trained net runs 10x too fast and its history/velocity
      // time-scale is wrong. Hold the last PWM (zero-order hold) between ticks.
      static unsigned long lastRlUs7 = 0;
      const unsigned long nowRl7 = micros();
      if (lastRlUs7 != 0 && (nowRl7 - lastRlUs7) < 20000UL) {
        return;  // zero-order hold — keep last motor command
      }
      lastRlUs7 = nowRl7;

      // Safety: brake if servo out of range
      if (fabsf(pos) > 90.0f) {
        float brake_dir = (pos > 0) ? -1.0f : 1.0f;
        setMotor((int)(brake_dir * 70.0f));
        rl_vf_init = false;  // re-init velocity filter when control resumes
        return;
      }

      // Build network input in SIM convention (matches QubeRealEnv invert_alpha):
      //   theta as-is; alpha FLIPPED, wrapped to [-pi,pi] for the position features.
      const float theta_rad = pos * DEG_TO_RAD;            // theta_sim
      const float xth = theta_rad;                          // vel-filter input (unwrapped)
      const float xal = -pendPosRaw * DEG_TO_RAD;           // alpha_sim, UNWRAPPED (clean derivative)
      float alpha_rad = xal;
      while (alpha_rad >  PI) alpha_rad -= TWO_PI;           // wrapped only for the obs features
      while (alpha_rad < -PI) alpha_rad += TWO_PI;

      // Velocities via the sim's EXACT discrete derivative filter H(s)=50s/(s+50)
      // @ dt=0.02 (VelocityFilter): v[n] = 50*(x[n]-x[n-1]) + 0.36788*v[n-1].
      // Positive finite difference -> the +d/dt sign the policy trained on; the old
      // firmware EMA used -(x-prev)/dt, i.e. the velocity sign was INVERTED (a real
      // swing-up bug: the policy damped when it should pump and vice-versa).
      if (!rl_vf_init) {
        rl_vf_thPrev = xth; rl_vf_alPrev = xal;
        rl_vf_thVel = 0.0f; rl_vf_alVel = 0.0f;
        rl_vf_init = true;
      }
      rl_vf_thVel = 50.0f * (xth - rl_vf_thPrev) + 0.36787944f * rl_vf_thVel;
      rl_vf_alVel = 50.0f * (xal - rl_vf_alPrev) + 0.36787944f * rl_vf_alVel;
      rl_vf_thPrev = xth;
      rl_vf_alPrev = xal;
      const float theta_dot_rad = rl_vf_thVel;
      const float alpha_dot_rad = rl_vf_alVel;

      // Run on-device inference (returns policy action = tanh(mu) in [-1,1]).
      // rl_last_action stored inside is the un-negated policy action (sim convention).
      float action = rl_infer_step(theta_rad, alpha_rad, theta_dot_rad, alpha_dot_rad);

      // Motor torque is mirrored vs sim -> negate the command (QubeRealEnv invert_action).
      // rl_pwm_scale (runtime, /rl_cmd?scale=) tames over-pumping from the sim2real
      // dynamics gap without re-flashing.
      float action_norm = constrain(-action, -1.0f, 1.0f);
      int rl_pwm = (int)(action_norm * PWM_MAX * rl_pwm_scale);
      rl_pwm = constrain(rl_pwm, -PWM_MAX, PWM_MAX);
      setMotor(rl_pwm);
    }
  }
  const unsigned long nowMs = millis();
  // Failsafe: si no hay comandos recientes en modos activos, detener.
  if (ENABLE_COMMAND_TIMEOUT && mode >= 1 && mode <= 7 && (nowMs - lastCommandMs > COMMAND_TIMEOUT_MS)) {
    safeStop();
  }

  if (nowMs - lastTelemetryMs >= telemetryPeriodMs) {
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
    Serial.print(" PA:");
    Serial.print(digitalRead(PIN_PEND_A));
    Serial.print(" PB:");
    Serial.print(digitalRead(PIN_PEND_B));
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
