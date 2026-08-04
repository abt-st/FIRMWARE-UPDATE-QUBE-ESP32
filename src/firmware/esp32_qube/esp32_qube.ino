// ============================================================
// QUBE Servo - Firmware base oficial
// Arquitectura: ESP32 + L298N + INA219 + 2x LM2596 + 2x CD40106BE Schmitt Trigger
// Placa: DOIT ESP32 DevKit V1, 30 pines (modulo WROOM-32). El cambio desde la
//        placa de 38 pines (2026-08-01, v1.57.1) no altero ningun GPIO: los 30
//        pines exponen los 9 que usa este firmware. Posiciones fisicas en el
//        header: docs/hardware/pinout.md
// Fecha: 2026-05-28 (migrado L298N->BTS7960 el 2026-06-08, commit 78b4e7e;
//        revertido BTS7960->L298N el 2026-07-28 por errores de esa migracion,
//        ver CHANGELOG.md v1.52.0. El GPIO26/27 dual-PWM no cambio: solo el
//        recableado fisico de RPWM/LPWM a IN1/IN2)
// ============================================================
// Topologia de potencia y logica:
// 1) Transformador 15V-2A -> INA219 (serie) -> L298N VS (motor, directo)
// 2) Transformador -> LM2596 #1 -> 5V riel "logica" (L298N VSS + encoders + Schmitt)
//    Transformador -> LM2596 #2 -> 5V riel dedicado (solo ESP32 VIN, anti-brownout)
// 3) Encoder servo (open-drain 5V) -> pull-up 2.2kΩ a 3.3V
//    -> Schmitt Trigger CD40106BE (doble inversion, Vcc=3.3V)
//    -> salida limpia ~3.3V -> ESP32 GPIO34/GPIO35
// 4) INA219 en I2C para telemetria de voltaje, corriente y potencia
// 5) GND comun entre potencia y logica (topologia estrella)
//
// Pines recomendados (L298N):
// L298N ENA           -> jumper puesto, GPIO25 sin conectar (ver nota PIN_ENA abajo)
// L298N IN1           -> GPIO26  (PWM sentido horario)
// L298N IN2           -> GPIO27  (PWM sentido antihorario)
// L298N VSS (logica)  -> 5V (LM2596 #1) | VS (motor) -> 15V directo (via INA219)
// Encoder servo A -> Schmitt INV_A (pin 1) -> GPIO34
// Encoder servo B -> Schmitt INV_C (pin 5) -> GPIO35
// INA219 SDA -> GPIO21
// INA219 SCL -> GPIO22
// CD40106BE Vcc -> 3.3V (pin 14), GND (pin 7), bypass 100nF
//
// Modos de operacion:
// 0 stop · 1 PWM manual · 2 PID posicion servo · 3 homing por topes
// 4 LQR balance · 5 swing-up · 6 Deep RL por HTTP · 7 Deep RL on-device
//
// Comandos Serial (lista completa: comando `h`):
// m<0..7>              -> cambiar de modo
// p-255..255           -> PWM manual (solo en m1)
// s<grados>            -> setpoint de posicion (m2)
// kp<val>, ki<val>, kd<val>
// lqr1..lqr4<val>      -> ganancias LQR;  L<n> <val> -> tuning fino (ver `h`)
// b/j/y/q<val>         -> umbrales del hibrido RL->LQR del modo 7
// r                    -> reset encoder y PID
// kf<0|1>             -> activar/desactivar filtro de Kalman (LQG)
// ?                    -> imprime estado ·  h -> ayuda ·  reboot -> reinicia
// wifi_ssid<TuRed>     -> configurar SSID WiFi (guarda en NVS/Preferences)
// wifi_pass<TuClave>   -> configurar password WiFi (guarda en NVS/Preferences)
// wifi_info            -> mostrar configuracion WiFi actual
//
// Endpoints HTTP (detalle en docs/http_api.md):
// GET  /state              — estado completo (JSON)
// GET  /cmd?m=2            — cambiar modo (m=3 homing: asincrono, polling en /state)
// GET  /cmd?s=45           — setpoint posición
// GET  /cmd?p=100          — PWM manual (modo 1)
// GET  /cmd?x=1            — parada segura
// GET  /cmd?rj=1           — reset de las metricas de salud del lazo
// GET  /rl_state           — estado compacto para RL {th,al,thd,ald} (rad, rad/s)
// GET  /rl_step?a=0.5      — fija accion Y devuelve el estado en 1 round-trip (proto v3)
// GET  /rl_cmd?a=0.5       — acción RL [-1.0, 1.0]
// GET  /rl_cmd?r=1         — reset encoders + estado RL
// GET  /rl_cmd?z=1         — zero servo encoder (offset, sin reset PID)
// GET  /rl_cmd?zp=1        — zero péndulo encoder (offset)
// POST /update             — OTA de firmware por navegador
// POST /fs                 — subida de archivos a SPIFFS (GUI)
// GET  /restart, /format   — reinicio y formateo de SPIFFS  [SIN AUTENTICAR]
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
#include "esp_wifi.h"   // esp_wifi_set_ps: forzar WIFI_PS_NONE (sin modem-sleep)
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
// Espejo del wrapper DeadZone con el que se ENTRENA la politica (qube_rl/config.py,
// WrapperConfig). Tienen que moverse juntos: si cambian alla y no aca, el modo 7
// aplica una transformacion distinta de la del entrenamiento y la politica entrega un
// torque que no es el que aprendio. Solo lo usa el modo 7 — ver el comentario en su
// rama de politica.
const float RL_DEADZONE        = 0.20f;
const float RL_DEADZONE_CENTER = 0.01f;
const float RL_DEADZONE_MAX_ACT = 0.75f;
// RL velocity filter state — replicates the sim's discrete derivative filter
// H(s)=50s/(s+50) @ dt=0.02 (qube_rl/utils.py VelocityFilter). Reset on mode entry.
// Shared by mode 6 (HTTP) and mode 7 (on-device): both tick it at 50 Hz.
float rl_vf_thPrev = 0.0f, rl_vf_thVel = 0.0f;
float rl_vf_alPrev = 0.0f, rl_vf_alVel = 0.0f;
bool  rl_vf_init = false;

// Sim-convention RL observation — single source of truth for what the policy
// sees, computed by updateRlObservation() in the control loop (modes 6 & 7) and
// reported verbatim by /rl_state. Keeping the convention in ONE place fixes the
// old bug where /rl_state (mode 6) exported velocities with the inverted sign
// of the LQR-era EMA while mode 7 used the corrected sim convention, so the SAME
// trained policy saw opposite-signed velocities on HTTP vs on-device.
//   theta: as-is.  alpha: FLIPPED (encoder mirrored vs sim) and wrapped to [-pi,pi].
//   velocities: positive finite-difference of the sim-convention angles.
// NOTE: qube_rl/envs/qube_real.py reads these as PASS-THROUGH — it must NOT
// re-flip alpha or negate velocities. Firmware and qube_real.py must be deployed
// together.
volatile float rl_obs_th = 0.0f, rl_obs_al = 0.0f;    // rad
volatile float rl_obs_thd = 0.0f, rl_obs_ald = 0.0f;  // rad/s

// /rl_state protocol version. BUMP THIS whenever the sim-convention contract of
// updateRlObservation() / handleRlState changes (sign, units, wrapping, filter).
// qube_rl/envs/qube_real.py asserts it on connect so a firmware/Python mismatch
// fails LOUDLY instead of silently feeding the policy wrong-signed observations.
//   v2 = sim convention: theta as-is; alpha flipped+wrapped; +finite-diff vels @50Hz.
//   v3 = adds GET /rl_step?a=X (set action + return the compact state in ONE round-trip)
//        to halve per-step WiFi latency. Observation convention UNCHANGED from v2.
//        qube_real.py's step() requires /rl_step, so the bump makes an old firmware
//        (no /rl_step) fail loudly at reset() instead of 404'ing mid-episode.
#define RL_PROTO_VERSION 3

// Update the sim-convention RL observation (rl_obs_*) from the raw encoders.
// MUST be called at the 50 Hz training rate (the filter coefficients assume
// dt=0.02; ticking at the 500 Hz loop rate distorts the velocities).
void updateRlObservation(float pos_deg, float pendPosRaw_deg) {
  const float theta_rad = pos_deg * DEG_TO_RAD;          // theta_sim
  const float xth = theta_rad;                            // vel-filter input (unwrapped)
  const float xal = -pendPosRaw_deg * DEG_TO_RAD;         // alpha_sim, UNWRAPPED (clean derivative)
  if (!rl_vf_init) {
    rl_vf_thPrev = xth; rl_vf_alPrev = xal;
    rl_vf_thVel = 0.0f; rl_vf_alVel = 0.0f;
    rl_vf_init = true;
  }
  // v[n] = 50*(x[n]-x[n-1]) + exp(-1)*v[n-1]  (positive finite difference).
  rl_vf_thVel = 50.0f * (xth - rl_vf_thPrev) + 0.36787944f * rl_vf_thVel;
  rl_vf_alVel = 50.0f * (xal - rl_vf_alPrev) + 0.36787944f * rl_vf_alVel;
  rl_vf_thPrev = xth;
  rl_vf_alPrev = xal;
  float alpha_rad = xal;                                  // wrapped only for the obs features
  while (alpha_rad >  PI) alpha_rad -= TWO_PI;
  while (alpha_rad < -PI) alpha_rad += TWO_PI;
  rl_obs_th  = theta_rad;
  rl_obs_al  = alpha_rad;
  rl_obs_thd = rl_vf_thVel;
  rl_obs_ald = rl_vf_alVel;
}

// ── Instrumentacion de P21 ───────────────────────────────────────────────────
// La campana del 2026-08-04 midio corr(segundos en rama politica, loop_overruns)
// = +0,996 con n=10: la inferencia rompe el lazo de 500 Hz, ~21% de los ticks
// atrasan mas de 10 ms. Para 6.464 MACs en un ESP32 a 240 MHz eso es del orden de
// 100x de mas, asi que hay algo patologico y NO se puede optimizar a ciegas.
//
// Se cronometran las dos mitades por separado porque son sospechosos distintos:
//   fwd  = solo las multiplicaciones (pesos `constexpr` leidos desde flash)
//   step = fwd + armado de la observacion (4 transcendentales por llamada)
// Si el grueso esta en `step - fwd`, el problema son los cosf/sinf y no la red.
// Se reinician con /cmd?rj=1, igual que las metricas del lazo.
// Se acumulan las dos SUMAS, no solo los maximos: separar red de armado exige comparar
// media contra media. Restarle un maximo a una media no significa nada.
volatile uint32_t rl_fwd_us_last  = 0, rl_fwd_us_max  = 0;
volatile uint32_t rl_step_us_last = 0, rl_step_us_max = 0;
volatile uint64_t rl_step_us_sum  = 0, rl_fwd_us_sum  = 0;
volatile uint32_t rl_infer_count  = 0;

// ── P21: los pesos viven en RAM, no en flash ─────────────────────────────────
// Medido el 2026-08-04: con los pesos leidos desde `.rodata` una inferencia costaba
// 1.855 us de media y hasta 15.469 us, con max/media = 8,3x. Ese perfil a picos es
// caracteristico de fallos de cache de flash, no del costo de la aritmetica: 6.464
// MACs en un ESP32 a 240 MHz deberian ser decenas de microsegundos.
//
// 6.593 floats son ~26 KB de RAM, contra 320 KB disponibles y 27,7% en uso. Se copian
// una vez en setup() y el bucle caliente no vuelve a tocar flash.
static float RL_W0[RL_HIDDEN * RL_INPUT_DIM];
static float RL_B0[RL_HIDDEN];
static float RL_W1[RL_HIDDEN * RL_HIDDEN];
static float RL_B1[RL_HIDDEN];
static float RL_W2[RL_HIDDEN];
static float RL_B2;

// Sumas de control, calculadas una sola vez al copiar. Se contrastan desde el PC contra
// la misma suma sobre policy_weights.h: es lo que separa "la copia corrompio la
// politica" de "la politica es la misma y lo que cambio es el banco".
float rl_w0_sum = 0.0f, rl_w1_sum = 0.0f;

void rl_weights_to_ram() {
    memcpy(RL_W0, policy_weights::LAYER_0_WEIGHT, sizeof(RL_W0));
    memcpy(RL_B0, policy_weights::LAYER_0_BIAS,   sizeof(RL_B0));
    memcpy(RL_W1, policy_weights::LAYER_1_WEIGHT, sizeof(RL_W1));
    memcpy(RL_B1, policy_weights::LAYER_1_BIAS,   sizeof(RL_B1));
    memcpy(RL_W2, policy_weights::LAYER_2_WEIGHT, sizeof(RL_W2));
    RL_B2 = policy_weights::LAYER_2_BIAS[0];
    double s0 = 0.0, s1 = 0.0;
    for (int i = 0; i < RL_HIDDEN * RL_INPUT_DIM; i++) s0 += RL_W0[i];
    for (int i = 0; i < RL_HIDDEN * RL_HIDDEN; i++)    s1 += RL_W1[i];
    rl_w0_sum = (float)s0;
    rl_w1_sum = (float)s1;
}

// Forward pass: input[36] → action in [-1, 1] via tanh (matches SB3 SAC
// deterministic output; verified numerically vs model.predict, err < 2e-7).
float rl_forward(const float* input) {
    const uint32_t t_fwd0 = micros();
    float h1[RL_HIDDEN];
    for (int j = 0; j < RL_HIDDEN; j++) {
        float sum = RL_B0[j];
        for (int k = 0; k < RL_INPUT_DIM; k++) {
            sum += RL_W0[j * RL_INPUT_DIM + k] * input[k];
        }
        h1[j] = sum > 0.0f ? sum : 0.0f;  // ReLU
    }
    float h2[RL_HIDDEN];
    for (int j = 0; j < RL_HIDDEN; j++) {
        float sum = RL_B1[j];
        for (int k = 0; k < RL_HIDDEN; k++) {
            sum += RL_W1[j * RL_HIDDEN + k] * h1[k];
        }
        h2[j] = sum > 0.0f ? sum : 0.0f;  // ReLU
    }
    float raw_out = RL_B2;
    for (int k = 0; k < RL_HIDDEN; k++) {
        raw_out += RL_W2[k] * h2[k];
    }
    // SB3 SAC squashes the actor mean with tanh for the deterministic action.
    // (Previously Hardtanh(-2,2)*0.5 downstream — wrong fn, err up to 0.27.)
    const float out = tanhf(raw_out);
    rl_fwd_us_last = micros() - t_fwd0;
    if (rl_fwd_us_last > rl_fwd_us_max) rl_fwd_us_max = rl_fwd_us_last;
    rl_fwd_us_sum += rl_fwd_us_last;
    return out;
}

// Build observation from current state and append to history
float rl_infer_step(float theta_rad, float alpha_rad, float theta_dot, float alpha_dot) {
    const uint32_t t_step0 = micros();
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
    rl_step_us_last = micros() - t_step0;
    if (rl_step_us_last > rl_step_us_max) rl_step_us_max = rl_step_us_last;
    rl_step_us_sum += rl_step_us_last;
    rl_infer_count++;
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

// GPIO25 (PIN_ENA) no está conectado en el hardware actual (L298N con jumper ENA
// puesto). setup() lo deja en HIGH de todos modos por herencia del wiring BTS7960
// (R_EN/L_EN); es una salida sin efecto físico, no un requisito del L298N.
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
// Kd 0.15 -> 0.45 (2026-08-03, P6 etapa 4). Barrido en banco sobre el escalon +17 -> -20
// medido con la traza a 500 Hz y ventana de 14 s, n=5 por punto:
//   kd=0.15 -> sobrepaso 39.3% (37.6-39.4)   kd=0.45 -> 8.4% (7.9-8.8)
// Las distribuciones NO se solapan y el error de regimen no se degrada (2.66 vs 2.70).
// Cero hunting en las diez corridas. La tendencia es monotona sobre 0.15/0.30/0.45/0.60.
// Detalle en experiments/2026-08-03_p6_pid/README.md.
float Kd = 0.45f;
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
const float VEL_ALPHA_PEND = 0.60f;  // Filtro velocidad péndulo (usado en LQR)
// ── Velocidad del pendulo para el swing-up (modo 5) ──────────────────────────
// El modo 5 consume rl_vf_alVel (rad/s), el filtro de convencion sim que ya
// alimenta a los modos 6 y 7. Antes tenia su propio estimador EMA
// (swing_filteredVelAlpha / prevPosPend) que NUNCA se calculo: sus unicas
// asignaciones eran a cero, asi que alpha_dot valia 0 en todo momento, la rama
// de bombeo resonante era inalcanzable y ke_gain no tenia efecto alguno
// (auditoria F1). Se elimino en vez de repararse para no dejar un tercer
// estimador de velocidad conviviendo en el archivo.
//
// SIGNO — PENDIENTE DE VALIDACION EN BANCO. rl_vf_alVel es la derivada NEGATIVA
// de pendPosRaw, la misma convencion del LQR del modo 4, que es la unica ley de
// control de este firmware validada contra este hardware; de ahi el default +1.
// Pero el sentido correcto del bombeo depende del cableado del motor y del
// encoder y NO se puede determinar estaticamente. Si el pumping frena en vez de
// excitar (el pendulo se queda en el fondo con PWM alto), invertir en caliente
// con el comando serie `L12 -1` y anotar el valor que funciono.
float swing_vel_sign = 1.0f;
float pendulumOffsetDeg = 0.0f;
// LQR Péndulo Invertido (modo 4)
// Ganancias LQR base (lejos del equilibrio)
float lqr_K1 = 2.0f;    // Ganancia posición servo
float lqr_K2 = 22.0f;   // Ganancia ángulo péndulo (valor original calibrado)
float lqr_K3 = 1.5f;
float lqr_K4 = 9.0f;    // Ganancia velocidad péndulo (valor original calibrado)

// Gain scheduling: gains moderados cerca del equilibrio
float lqr_K2_near = 30.0f;       // K2 cerca de vertical
float lqr_K4_near = 15.0f;       // K4 cerca de vertical
float lqr_near_deg = 25.0f;      // Umbral para gains near
float lqr_K2_very_near = 55.0f;  // K2 muy cerca de vertical
float lqr_K4_very_near = 20.0f;  // K4 muy cerca de vertical
float lqr_very_near_deg = 5.0f;  // Umbral para gains very near
float lqr_damping_gain = 0.3f;   // Ganancia de disipación de energía
// Mode-7 hybrid RL→LQR handoff — runtime-tunable via serial (b/j/y) for bench tuning.
float hybrid_enter_deg = 165.0f; // |alpha|>=this (deg from hanging) → enter LQR catch
float hybrid_exit_deg  = 130.0f; // |alpha|<this → drop back to RL swing-up
int   hybrid_lqr_pwm   = 70;     // PWM clamp for the LQR catch branch
// Velocity-bleed catch-brake (ported from mode 4): on LQR entry, brake against the
// crossing velocity for a few ms to dissipate excess energy BEFORE the LQR hold.
// Tunable via serial L8/L9/L10.
float hybrid_catch_ms    = 250.0f; // brake duration after entering apex zone (ms)
float hybrid_catch_gain  = 0.10f;  // brake PWM per deg/s of pendulum velocity (sign-flippable)
int   hybrid_catch_pwm   = 40;     // brake PWM clamp
float hybrid_catch_angle = 15.0f;  // apex zone half-width (deg from vertical) that arms the brake
float lqr_prevTheta = 0.0f;
float lqr_prevAlpha = 0.0f;
float lqr_filteredVelTheta = 0.0f;
float lqr_filteredVelAlpha = 0.0f;
bool lqr_inFallback = false;  // true mientras se está en swing-up por fallback LQR (evita rebote)
unsigned long lqr_catchMs = 0;  // Timestamp para catch mode (frenado inicial al entrar a LQR)
// H6 (2026-08-04): instante en que TERMINO el catch. Existe porque `lqr_catchMs` se
// pone a cero justo al salir del catch y despues se lo seguia usando como referencia
// temporal: `millis() - 0` es el uptime, no el tiempo desde el catch. Ver el bloque
// del centering en el modo 4.
unsigned long lqr_catchEndMs = 0;
// Supervivencia del ultimo intento de balanceo: ms desde que termino el catch hasta
// que se salio del modo 4. Se latchea en setMode() y no por muestreo desde el cliente,
// por lo mismo que swing_trans_*: a 25 Hz de HTTP, "sobrevivio 0,3 s" son 7 muestras.
unsigned long lqr_aliveMs = 0;
// ── Estado transitorio de los modos, agrupado ────────────────────────────────
// Estas seis variables eran `static` locales dentro de loop(). Como setMode() no
// puede alcanzar un static local, sobrevivian a los cambios de modo: al re-entrar
// al modo 7 tras una caida, hybrid_lqr seguia en true (el lazo creia estar en fase
// de balance con el pendulo colgando) y la ventana de catch ya estaba consumida
// (auditoria F5). Ahora son globales y setMode() las limpia.
float         lqr_lockedBrakeDir = 0.0f;  // modo 4: sentido de frenado fijado al entrar al catch
unsigned long rl_lastTickUs6     = 0;     // modo 6: ultimo tick de observacion a 50 Hz
unsigned long rl_lastTickUs7     = 0;     // modo 7: ultimo tick de inferencia a 50 Hz
bool          hybrid_lqr         = false; // modo 7: true = rama LQR, false = rama politica RL
unsigned long hybrid_apexCatchMs = 0;     // modo 7: inicio de la ventana de freno en el apex (0 = desarmada)
float         hybrid_lockedBrakeDir = 0.0f; // modo 7: sentido de frenado fijado al entrar al apex

void resetModeState() {
  lqr_lockedBrakeDir = 0.0f;
  rl_lastTickUs6 = 0;
  rl_lastTickUs7 = 0;
  hybrid_lqr = false;
  hybrid_apexCatchMs = 0;
  hybrid_lockedBrakeDir = 0.0f;
}
const unsigned long LQR_CATCH_MS = 400;  // Duración del catch mode en ms (era 150, insuficiente para disipar inercia)
const float LQR_CATCH_GAIN = 0.10f;      // PWM de freno por deg/s de velocidad del péndulo
const int   LQR_CATCH_PWM  = 25;         // Tope del PWM de freno en el catch
const int   LQR_PWM_MAX    = 70;         // Tope del PWM del LQR en el modo 4

// ── H2 / H6: las dos variables de la ventana del catch, configurables por HTTP ──
// Los defaults reproducen EXACTAMENTE el comportamiento previo a v1.58.5, para que
// flashear no cambie nada por si solo y el A/B se haga por HTTP sin reflashear.
//
// H2: durante el catch la rama termina en `return`, asi que el LQR no corre. Con
// w_n = 14,34 rad/s (medida, P5) una desviacion de la vertical crece como
// cosh(w_n*t): x155 en 400 ms. `?lc=0` desactiva el catch por completo.
unsigned long lqr_catchDurMs = LQR_CATCH_MS;
// H6: el periodo de gracia del centering nunca existio (ver el bloque del centering).
// false = comportamiento historico (rampa llena desde el primer tick).
// true  = lo que el comentario decia: 2 s sin centering + 2 s de rampa.
bool lqr_centeringGrace = false;
float pendPosRawPrev = 0.0f;  // Para detectar spinning
// Cuantas veces se acoto la lectura del pendulo restando vueltas. Se expone en
// /state para que el analisis pueda distinguir una corrida donde el pendulo giro de
// una donde no, en vez de descubrirlo por accidente (P13).
//
// MONOTONICO a proposito (solo se reinicia al arrancar la placa): el cliente lo lee
// antes y despues y saca la diferencia. Reiniciarlo en setMode(5) parecia mas comodo
// pero perdia eventos — el fallback del LQR acota y JUSTO DESPUES llama a setMode(5),
// con lo que el contador borraba el wrap que acababa de registrar.
uint16_t pend_wrapCount = 0;
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
// PWM_MIN (12) se elimino el 2026-07-31: su unico uso era el kick anti-friccion del
// modo 2, y el nombre prometia un piso global que nunca fue. Ahora ese piso es
// `stiction_kick_pwm`, configurable y con un valor que si arranca el mecanismo.
const int PWM_MAX = 200;
// Escala angular de la soft saturation de setMotor(). Mas grande = mas suave.
const float SOFT_SAT_K_DEG = 200.0f;

// Parametros del pendulo para calculo de energia (Quanser swing-up)
// ⚠ PEND_MASS y PEND_LENGTH siguen SIN identificar (heredan el "- ajustar"
// original). No importa para lo unico que usan estas constantes hoy — `E/E*` en la
// transicion del swing-up — porque el cociente se reduce a:
//
//     E/E* = alpha_dot^2 / (4 * wn^2) + (1 - cos alpha) / 2 ,   wn^2 = mgl/I
//
// o sea que depende SOLO de wn, no de m, L e I por separado. Si alguna vez se usan
// para torque o para el gemelo, hay que identificarlas de verdad.
const float PEND_MASS = 0.025f;      // Masa del pendulo (kg) - SIN identificar
const float PEND_LENGTH = 0.065f;    // Distancia pivot-centro de masa (m) - SIN identificar
// I ajustado el 2026-07-30 para que mgl/I reproduzca la frecuencia natural MEDIDA en
// banco por oscilacion libre: T = 0.46 s a ~47 deg de amplitud -> wn = 14.34 rad/s
// (2.28 Hz) corrigiendo el ~5% de amplitud finita. Antes valia 2e-5, que implicaba
// wn = 28.2 rad/s (4.49 Hz): el doble, equivalente a una barra de 1.8 cm. Con ese
// valor el termino cinetico de E/E* se subestimaba ~3.9x y el criterio de energia
// nunca podia cumplirse. Ver experiments/2026-07-30_pendulum_id/.
const float PEND_INERTIA = 7.75e-5f; // Momento de inercia (kg*m^2) - de wn medido
const float GRAVITY = 9.81f;         // Gravedad (m/s^2)
// ⚠ ke_gain NO ESTA CALIBRADO. Hasta la auditoria de 2026-07-28 vivia dentro de
// una rama inalcanzable (la velocidad del pendulo era identicamente cero, ver
// swing_vel_sign arriba), asi que NUNCA afecto el comportamiento del equipo. El
// comentario anterior le atribuia "25% catch rate, hold 86s" medidos en BTS7960:
// esos numeros pueden ser reales, pero no son atribuibles a este parametro. Toda
// campaña previa de barrido de ke (y de bt) midio ruido.
// PENDIENTE: re-caracterizar desde cero en banco una vez validado el signo.
float ke_gain = 0.65f;
// Adaptive ke_gain: increase energy gain when pendulum stalls
float swing_maxAngleAchieved = 0.0f;    // Max absolute angle achieved since last reset
unsigned long swing_lastImprovementMs = 0;  // Timestamp of last angle improvement
const float KE_GAIN_BASE = 0.75f;       // Base energy gain (era 0.65)
const float KE_GAIN_BOOST = 1.5f;       // Boosted gain when stalled (era 1.2)
const unsigned long STALL_TIMEOUT_MS = 6000;  // 6s without improvement → boost (era 4s)
bool swing_recovering = false;       // Estado de recovery: motor apagado esperando que el péndulo caiga
const float SWING_RECOVERY_THRESHOLD = 30.0f;  // |pendPos| < esto para salir de recovery (cerca del fondo)
const unsigned long CONTROL_PERIOD_US = 2000;             // 500 Hz (era 5000 = 200 Hz)
// Subido de 50 a 60 el 2026-07-30 tras un barrido fino con condicion inicial
// controlada (reposo verificado + re-cero del pendulo, imprescindible por P13):
//   sp   50     55     57     59     60     70
//   a    145.4  154.7  156.8  157.0  158.7  150.2   (deg, mediana)
// Mejora monotona hasta 60 y despues empeora: por encima el brazo cruza los 95 deg
// y safeStop mata la corrida antes de acumular energia (a sp=70 dura 3.3 s).
// E/E* en el apice pasa de 0.911 a 0.966.
int swingupPwmMax = 60;  // PWM limit para swing-up (configurable por HTTP: sp<val>)
unsigned long telemetryPeriodMs = 100;          // Ajustable por HTTP: tp<ms>
// Linea de telemetria por Serial (~120 caracteres cada telemetryPeriodMs). A 115200
// baudios son ~10 ms de UART contra un periodo de control de 2 ms, y el consumidor
// habitual no existe: abrir el monitor serial REINICIA la placa. Se deja activa por
// defecto para no romper qube_serial_tool.py, pero es apagable (/cmd?sv=0) durante
// una adquisicion, donde cada milisegundo robado al lazo se ve en loop_dt_max_us.
bool serialTelemetry = true;
// Periodo del broadcast WS en modo 6 (RL por HTTP). El lazo es latencia-critico y
// comparte la unica radio, asi que la GUI se refresca decimada (~2 Hz) en vez de a
// telemetryPeriodMs. Suficiente para vigilar angulos, modo y watchdog de comandos.
const unsigned long RL_MODE_TELEMETRY_MS = 500;
float prev_alpha_dot_peak = 0.0f;  // Peak detection para transicion LQR

// ── Traspaso swing-up -> LQR (modo 5 -> 4): telemetria latcheada ─────────────
// El criterio ganador se imprimia SOLO por Serial, y el monitor serial reinicia la
// placa — asi que en la practica el traspaso no era atribuible. Los intentos del
// 2026-07-30 mostraron que el angulo de traspaso parecia variar entre 76 y 128 deg,
// pero eso era retraso de muestreo (los 4 criterios exigen |pendPos| > 120): sin
// latchear el valor EN el instante de la transicion no hay forma de distinguirlos.
// Se latchea aca y se expone en /state; setMode(5) lo limpia, asi que lo que se lee
// siempre corresponde al intento en curso.
const uint8_t SWING_TRANS_NEAR   = 0x01;  // cerca de vertical Y lento
const uint8_t SWING_TRANS_PEAK   = 0x02;  // pico de alpha dentro de la ventana
const uint8_t SWING_TRANS_FORCED = 0x04;  // |pendPos| > umbral forzado
const uint8_t SWING_TRANS_ENERGY = 0x08;  // energia dentro de tolerancia
uint8_t  swing_transReason   = 0;      // bitmask; 0 = no hubo transicion
float    swing_transAlphaDeg = 0.0f;   // pendPos EN el instante del traspaso
float    swing_transVelDps   = 0.0f;
float    swing_transEnergyRatio = 0.0f;  // E_current / E_target
unsigned long swing_transMs  = 0;      // millis() del traspaso (0 = nunca)
const unsigned long COMMAND_TIMEOUT_MS = 10000;
// Mode 1 has no reset-settle constraint, so it gets a much tighter deadman: a lost
// HTTP request there leaves the motor driving with nobody to stop it. 2.5 s clears
// capture.py's 2.0 s default --settle per PWM step.
const unsigned long MANUAL_COMMAND_TIMEOUT_MS = 2500;
// Failsafe enabled for unattended operation. It ONLY guards command-driven modes
// (1 manual PWM, 6 RL-over-HTTP): if their command stream dies, the motor stops.
// Autonomous modes (2 PID, 4 LQR, 5 swing-up, 7 on-device RL) run without external
// commands and are NEVER stopped by this timeout. 10 s is safely above the RL
// env's ~3 s reset settle, so it won't trip mid-episode; a true client disconnect
// is also bounded meanwhile by the mode-6 centering clamp.
const bool ENABLE_COMMAND_TIMEOUT = true;
// ── Escalera de seguridad del brazo (|theta| en grados) ──────────────────────
// UNA sola tabla, en orden creciente. Cada modo se limita a si mismo primero y
// SERVO_HARD_LIMIT_DEG es el respaldo comun; por eso todo umbral por modo tiene
// que quedar POR DEBAJO de el, o su rama es codigo inalcanzable.
//
//   70  SERVO_TAPER_DEG   modo 4: atenua linealmente el PWM que empuja al tope
//   80  SERVO_CLAMP_DEG   modo 6: la accion RL solo puede empujar hacia el centro
//   85  SERVO_BLOCK_DEG   modo 4: corta el PWM que empuja al tope
//   90  SERVO_BRAKE_DEG   modos 5 y 7: freno activo hacia el centro
//   95  SERVO_HARD_LIMIT  TODOS salvo 0 y 3: setMode(0) y coast  <-- respaldo
//  100                    tope mecanico del brazo
//
// El respaldo deja coastear en vez de frenar: garantiza par nulo hacia el fin de
// carrera, que es lo unico que importa ahi. El modo 3 (homing) esta exento por
// definicion — necesita llegar a los topes — y el modo 2 (PID) no tiene umbral
// propio: solo la soft saturation de setMotor(), que atenua pero nunca corta.
//
// HISTORICO: hasta v1.52 el modo 4 tenia una rama a 100 deg y el modo 6 otra a
// 110 deg. Ambas quedaron inalcanzables cuando se agrego el respaldo a 95 y se
// eliminaron; la escalera efectiva siempre fue 70/80/85/90/95.
const float SERVO_TAPER_DEG      = 70.0f;
const float SERVO_CLAMP_DEG      = 80.0f;
const float SERVO_BLOCK_DEG      = 85.0f;
const float SERVO_BRAKE_DEG      = 90.0f;
// PROBADO en 105 el 2026-07-31 y REVERTIDO a 95: no aporto nada. El pendulo siguio
// topando en 159-160 deg y el brazo se limito a usar el espacio extra (llego a 123,
// a 12 deg del tope mecanico). Mas riesgo sin beneficio.
// Referencia por si se retoma: topes mecanicos en +-134.8 (medidos con >30 homings),
// arrastre tras el corte 27 deg a PWM 50.
const float SERVO_HARD_LIMIT_DEG = 95.0f;
// PWM del freno activo de los modos 5 y 7 en la banda SERVO_BRAKE..HARD_LIMIT.
const int   SERVO_BRAKE_PWM      = 70;
// Ganancia del centrado asistido del modo 6 por encima de SERVO_CLAMP_DEG (PWM/deg).
const float RL_CENTERING_KP      = 2.0f;

// ── Homing por topes mecanicos (modo 3) ──────────────────────────────────────
// Recupera el cero del encoder incremental del brazo: toca ambos topes, valida
// el recorrido y toma el punto medio como origen. En el Furuta theta no tiene un
// cero fisico privilegiado, asi que el centro util es el que maximiza el rango
// disponible a ambos lados — exactamente el punto medio del recorrido.
//
// TODO el modo trabaja en grados CRUDOS (getRawPositionDeg()). El offset es lo
// que se esta tratando de establecer, asi que cualquier logica apoyada en
// getPositionDeg() seria circular: con el cero perdido esa lectura es basura.
// Busqueda al mismo PWM que el toque: a 70 el brazo llegaba al tope a ~80 deg/s
// (medido, 93 deg en 1.16 s) y esa es la unica parte de la rutina que golpea
// fuerte — los toques arrancan a 5 deg del tope y apenas aceleran. La energia de
// impacto va con v^2, asi que 55 la deja cerca de la mitad. No conviene bajar
// mas: a 40 la friccion sola frena el brazo y el detector lo lee como tope.
// DEVUELTO a 70 el 2026-07-30. Bajarlo a 55 (para suavizar el impacto) introdujo un
// fallo intermitente: hay un PUNTO DURO MECANICO en el lado positivo, unos 16 deg
// antes del tope real, y a PWM 55 el brazo no siempre lo vence. El detector de calado
// lo lee como tope y el recorrido sale ~254 en vez de 270. Medido: 3 de 8 corridas,
// con el falso tope agrupado en -85.3 +-0.3 (reproducible, no ruido) contra el tope
// real en -101.4.
//
// Se sube SOLO la busqueda. El toque sigue en 55: arranca a 5 deg del tope real, o
// sea ya pasado el punto duro, y es el que fija la medicion — asi que la suavidad
// donde importa se conserva.
const int   HOMING_PWM_SEEK        = 70;      // Primer acercamiento al tope
// El toque estuvo en 40 y se calaba ~10 deg ANTES del tope: en la corrida del
// 2026-07-30 el brazo ya habia llegado a raw=-107.9 durante SEEK y el toque
// lento se detuvo en -97.6. A esa velocidad la friccion sola frena el brazo y
// el detector lo lee como tope. 55 mantiene el toque suave y llega al final.
const int   HOMING_PWM_TOUCH       = 55;      // Segundo toque, lento (el que vale)
// Frenado de aproximacion (2026-08-03). El impacto contra el tope lo fija la
// velocidad de llegada, y esa la fija HOMING_PWM_SEEK. Bajar el seek entero es
// exactamente lo que se probo en v1.53.2 y causo P3: a 55 el brazo no siempre vence
// el punto duro que hay a ~119 deg del centro, se cala ahi y acepta un cero corrido
// de 16 deg. Por eso el seek sigue en 70 y solo se baja a HOMING_PWM_TOUCH en los
// ultimos grados. El umbral tiene que ser MENOR que los ~16 deg que separan el punto
// duro del tope (119 vs 135), o se estaria bajando la potencia justo donde P3 muerde.
const float HOMING_SEEK_SLOW_DEG   = 8.0f;    // Ultimos grados del seek, ya frenado
const float HOMING_RANGE_NOM_DEG   = 270.0f;  // Recorrido nominal si no hay medicion previa
const int   HOMING_PWM_MIN         = 45;      // Piso para vencer friccion estatica
const float HOMING_BACKOFF_DEG     = 5.0f;    // Retroceso entre toques
const float HOMING_TOUCH_MIN_DEG   = 2.0f;    // Avance minimo antes de creerle al calado
const float HOMING_STALL_DEG       = 0.5f;    // Umbral de "no se movio"
// 200 ms dejaban al motor empujando contra el tope 200 ms despues del contacto.
// Esto no baja la velocidad de impacto (el golpe ya ocurrio) pero si el esfuerzo
// sostenido sobre el tope. 120 ms sigue siendo holgadisimo para no confundirse:
// a 55 de PWM el brazo recorre ~7 deg en ese tiempo, contra un umbral de 0.5.
const unsigned long HOMING_STALL_MS = 120;    // Sin movimiento => tope alcanzado
// Subido de 8000: a PWM 55 cruzar los 270 deg de recorrido toma ~5 s, y 8 s
// dejaban un margen demasiado fino contra un timeout espurio.
const unsigned long HOMING_SIDE_TIMEOUT_MS = 12000;  // Falla, NO criterio de exito
const unsigned long HOMING_CENTER_TIMEOUT_MS = 10000;
// Subido de 4000: medido en oscilacion libre, el pendulo tarda ~5 s en bajar de 5 deg
// tras un intento energetico, asi que 4 s garantizaba agotar el timeout justo cuando
// mas importa. Ahora agotar el timeout es falla (codigo 5), no arranque a ciegas.
const unsigned long HOMING_QUIET_TIMEOUT_MS = 20000;
// APRETADA de 250-290 a 262-278 el 2026-07-30 tras la campania de validacion: de 24
// corridas, 3 midieron ~250.3-251.7 (tope + detectado 19 deg antes del real, calado
// falso) y la ventana ancha las ACEPTO — o sea que se fijo un cero corrido ~10 deg.
// El recorrido real es 268-270, asi que 250 de piso no filtraba nada util.
// Medido en banco el 2026-07-30, 4 corridas limpias: 270.352, 270.000, 270.000,
// 270.352 deg (la dispersion es 1 conteo de encoder = 0.176 deg). Los 150-230
// que habia antes eran una suposicion y hacian abortar con fail=1 un homing
// perfectamente bueno. La ventana +-20 deg alrededor de 270 tolera desgaste y
// dilatacion pero sigue atrapando el caso que importa: acople suelto o encoder
// que no cuenta, donde el calado dispara al toque y el rango da casi cero.
const float HOMING_RANGE_MIN_DEG   = 262.0f;
const float HOMING_RANGE_MAX_DEG   = 278.0f;
const float HOMING_QUIET_DEG       = 0.5f;    // Movimiento del pendulo que rearma la espera
const unsigned long HOMING_QUIET_HOLD_MS = 1000; // Quieto este tiempo => se puede arrancar (era 500)
// Tolerancia de ESTACIONAMIENTO, no de calibracion: el offset se fija en
// homing_centerRaw (el centro geometrico medido) pase lo que pase, asi que
// aflojar esto no degrada el cero, solo deja al brazo un poco menos centrado.
const float HOMING_CENTER_TOL_DEG  = 5.0f;
const float HOMING_CENTER_SLOW_DEG = 30.0f;   // Distancia de frenado al centro
const float HOMING_CENTER_KP       = 3.0f;

enum HomingPhase : uint8_t {
  H_IDLE = 0, H_WAIT_QUIET, H_SEEK_POS, H_BACKOFF_POS, H_TOUCH_POS,
  H_SEEK_NEG, H_BACKOFF_NEG, H_TOUCH_NEG, H_GOTO_CENTER, H_DONE, H_FAIL
};
// Codigos de falla: 1 = rango fuera de tolerancia, 2 = timeout lado +,
// 3 = timeout lado -, 4 = timeout al centrar, 5 = el mecanismo no se aquieto.
uint8_t homing_phase = H_IDLE;
uint8_t homing_failCode = 0;
bool    homing_ok = false;
unsigned long homing_phaseMs = 0;
unsigned long homing_lastMoveMs = 0;
float homing_lastMoveRaw = 0.0f;
float homing_refRaw = 0.0f;       // Posicion cruda al entrar a la fase actual
float homing_stopPosRaw = 0.0f;
float homing_stopNegRaw = 0.0f;
// Memoria entre corridas para el frenado de aproximacion. Se guarda la lectura CRUDA
// del encoder, que es comparable entre homings (el offset cambia, el crudo no) mientras
// no se reinicie la placa ni se pierdan pulsos. No se toca en homingReset(): el punto
// es justamente que sobreviva a la corrida.
float homing_prevStopPosRaw = 0.0f;
float homing_prevRangeDeg   = 0.0f;
bool  homing_prevValid      = false;
float homing_rangeDeg = 0.0f;
float homing_centerRaw = 0.0f;
float homing_prevPendRaw = 0.0f;
float homing_prevArmRaw = 0.0f;   // idem para el brazo: tambien queda con inercia
unsigned long homing_quietMs = 0;
// Sentido aprendido en el propio homing: +1 si un PWM positivo hace crecer la
// lectura cruda del encoder, -1 si la hace decrecer. Evita depender de la
// convencion de MOTOR_DIR / encoderDir, que cambia con el recableado.
float homing_pwmSign = 1.0f;
void homingEnterPhase(uint8_t phase, float rawPos);

// ── Umbrales LQR ─────────────────────────────────────────────────────────────
const float LQR_SERVO_LIMIT_DEG = 90.0f;                 // Saturación del ángulo del servo en el lazo
// El fallback y la proteccion del LQR se decidieron sobre pendPosRaw con
// umbrales fijos (250 y 360 deg) dentro del propio modo 4. Las constantes
// LQR_FALLBACK_*, LQR_REARM_*, LQR_HARDSTOP_* y LQR_PROTECT_* quedaron sin un
// solo uso desde esa reescritura y se eliminaron en la auditoria de 2026-07-28.
const float LQR_PROTECT_RAW_DEG  = 250.0f;               // |pendPosRaw| que apaga el motor (rotacion acumulada)
const float LQR_FALLBACK_RAW_DEG = 360.0f;               // |pendPosRaw| = 1 vuelta -> el LQR fallo, vuelve a swing-up
const float LQR_REARM_RAW_DEG    = 45.0f;                // |pendPosRaw| por debajo del cual se re-arma el fallback

// ── Umbrales PID Servo (modo 2) ──────────────────────────────────────────────
const float PID_ANTIWIND_ERR_DEG = 45.0f;               // |err| máx. para integrar (anti-windup)
const float PID_ANTIWIND_VEL_DPS = 60.0f;               // |vel| máx. para integrar (anti-windup)
const float DEADBAND_FINE_DEG = 0.5f;                   // Dead band modo fino
const float DEADBAND_COARSE_DEG = 1.0f;                 // Dead band modo grueso
const float DEADBAND_CLASSIC_DEG = 0.8f;                // Dead band PID clásico
// ── Kick anti-friccion del modo 2 ────────────────────────────────────────────
// Piso de PWM que se aplica cuando el brazo esta detenido y el PID pide menos de
// lo que hace falta para arrancarlo. Configurables por HTTP (`se`, `sk`) porque
// el valor correcto sale de un barrido en banco, no del modelo.
//
// P6 (2026-07-31): estaban en 8 deg / 12 PWM y entre los dos dejaban un hueco
// donde el brazo se queda pegado y NADA lo saca salvo el integrador, a ~2.4 PWM/s.
// Medido en `m2_rep1.csv`: brazo inmovil en -15.2 deg con el PID pidiendo 14-15 PWM
// durante mas de 1 s, error de regimen 4.8 deg. Dos fallas sumadas:
//   - el umbral de 8 deg deja fuera justo la banda donde queda el error (0.8-8);
//   - el piso de 12 PWM no mueve el mecanismo. El homing usa 45 (HOMING_PWM_MIN)
//     para vencer la misma friccion estatica, y la traza muestra que 15 no basta.
// Un kick por debajo del arranque real es un kick que por construccion no arranca.
float stiction_err_thresh_deg = 2.0f;   // |err| min. para aplicar el kick (era 8)
float stiction_kick_pwm       = 30.0f;  // piso de PWM del kick (era PWM_MIN = 12)
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
// |pendPos| se mide desde el reposo (colgando): 0 = abajo, 180 = vertical arriba.
const float SWINGUP_TRANSITION_VEL_DPS = 30.0f;   // |α̇| máx. para transicionar a LQR
const float SWINGUP_QUIET_THRESHOLD_RADPS = 0.15f;// |α̇| por debajo del cual se arranca con kick sinusoidal
// P2 (2026-07-30): estos umbrales estaban en 120/125/60, o sea traspasando a 55-60
// deg de la vertical. Medido en banco, el bombeo crece de forma MONOTONA ~9 deg por
// ciclo (26->35->46->...->120 en 12 ciclos) y el brazo se mantiene en +-50 deg, lejos
// de su limite: el pendulo no se quedaba sin energia, el traspaso lo cortaba mientras
// todavia subia. Subidos para dejarlo bombear hasta cerca de la vertical, en linea
// con el modo 7 hibrido, que ya usaba hybrid_enter_deg = 165.
const float SWINGUP_TRANS_NEAR_DEG   = 155.0f;    // |pendPos| min. para transicion normal (25 deg de la vertical)
const float SWINGUP_TRANS_PEAK_DEG   = 25.0f;     // Semiancho desde vertical para transicion en el pico (era 60, ver P2)
const float SWINGUP_TRANS_FORCED_DEG = 165.0f;    // |pendPos| para la transicion forzada (era 125, ver P2)
// Compuerta de velocidad de la transicion forzada (P1). Holgada a proposito respecto
// de SWINGUP_TRANSITION_VEL_DPS (30): la forzada sigue siendo la via permisiva, pero
// deja de aceptar un pendulo que pasa VOLANDO por los 125 deg. Medido en banco: los
// traspasos malos ocurrian a 506-871 deg/s, asi que 150 los descarta a todos con
// margen amplio. Si con esto el swing-up deja de traspasar por completo, el problema
// no es el umbral sino la energia (P2) — y eso es informacion, no una regresion.
const float SWINGUP_TRANS_FORCED_VEL_DPS = 150.0f;

// P9 (2026-07-31). El estimador de velocidad (rl_vf_alVel) NO tiene ganancia unitaria:
//     v[n] = 50*(x[n]-x[n-1]) + exp(-1)*v[n-1]
// le falta el factor (1-a) en el termino de diferencia, asi que su ganancia es
// 1/(1-exp(-1)) = 1.582 en continua y 1.520 a la frecuencia natural del pendulo
// (2.28 Hz medida). O sea que sobre-lee ~52%.
//
// NO se corrige el estimador: el simulador usa EXACTAMENTE el mismo filtro
// (qube_rl/utils.py, VelocityFilter, portado de Quanser), con la misma ganancia.
// Cambiarlo aqui romperia el emparejamiento sim2real, que es lo unico que importa
// para las observaciones del RL — ahi lo relevante es que ambos concuerden, no que
// el valor sea fisicamente exacto.
//
// PERO donde alpha_dot entra como magnitud FISICA —la energia— el sesgo si importa:
// va al cuadrado, o sea 2.3x en el termino cinetico. Se corrige solo ahi.
// Los umbrales de velocidad (SWINGUP_TRANSITION_VEL_DPS, el FORCED de arriba) se
// dejan en la escala del estimador: se calibraron contra valores REPORTADOS, y
// convertirlos ahora los desplazaria sin ganar nada.
const float ALPHA_DOT_FILTER_GAIN = 1.52f;

// Habilita el traspaso m5 -> m4 (`?tr=`). Sirve para MEDIR: con el traspaso activo la
// corrida termina al cruzar el umbral, asi que nunca se ve donde plafona realmente el
// bombeo — es la misma trampa de P10 un nivel mas arriba. Con tr=0 el modo 5 bombea
// indefinidamente y se puede observar el techo de energia.
// Por defecto 1: apagarlo deja el pendulo girando sin que nadie lo capture.
uint8_t swingupTransEnable = 1;

// Tope del freno anti-giro del swing-up. Estaba en PWM_MAX (200) y ese escalon de
// corriente tiro la tension de la placa dos veces el 2026-07-31 (mismo mecanismo del
// brownout ya documentado): la placa se reinicia y se pierde el control entero, que
// es peor que frenar algo mas lento. El freno actua sostenido durante el cooldown,
// asi que la autoridad no depende solo del pico.
const int SWINGUP_SPIN_BRAKE_PWM = 120;

// Angulo de captura (`?tn=`), en |alpha| con vertical = 180. Un unico mando del que
// se derivan los tres umbrales, que antes eran constantes sueltas y era facil
// dejarlas incoherentes entre si:
//   near   = tn        · forced = tn + 10 · ventana de pico = 180 - tn
// tn = 155 reproduce exactamente el comportamiento anterior (155 / 165 / 25).
// Variable para poder barrerlo sin reflashear: medido el 2026-07-31, el bombeo llega
// a 179.8 deg, asi que traspasar en 155 entregaba el pendulo a 25 deg de la vertical
// pudiendo hacerlo mucho mas cerca.
float swingupCatchDeg = 155.0f;
const float SWINGUP_TRANS_ENERGY_VEL_DPS = 60.0f; // |α̇| máx. para la transicion por energia
const float SWINGUP_TRANS_ENERGY_TOL = 0.10f;     // Tolerancia relativa |E-E*|/E* para la transicion por energia
const float SWINGUP_DAMP_START_DEG   = 165.0f;    // |pendPos| desde donde se disipa energia hacia la vertical
const float SWINGUP_DAMP_SPAN_DEG    = 15.0f;     // Ancho de la rampa de disipacion (165 -> 180)
const float SWINGUP_CROSS_DEG        = 180.0f;    // |pendPos| que indica cruce de la vertical sin transicionar
// Arranque en frio: referencia sinusoidal del servo cuando el pendulo esta quieto.
const float SWINGUP_KICK_AMP_DEG     = 40.0f;     // Amplitud de la referencia (deg)
const float SWINGUP_KICK_HZ          = 2.0f;      // Frecuencia del kick (Hz)
const float SWINGUP_KICK_KP          = 3.0f;      // PWM por grado de error de seguimiento
// Bombeo resonante: referencia del servo proporcional a la velocidad del pendulo.
const float SWINGUP_PUMP_GAIN_DEG_PER_RADPS = 120.0f; // deg de referencia por rad/s
// Tope de la referencia de bombeo. Variable (no const) para poder barrerlo por HTTP
// (`?pr=`): es el parametro que fija la amplitud del brazo durante el bombeo, y por
// lo tanto la energia inyectada por ciclo. Medido a 70: el brazo llega a ~73 deg y
// la meseta del pendulo se estanca en 144 deg (E/E* = 0.904), con el limite blando
// en 95 — o sea ~22 deg de recorrido sin aprovechar.
// Subir `swingupPwmMax` NO sirve para esto: el brazo se pasa de 95, salta safeStop y
// la corrida muere antes de acumular energia (los ciclos caen de 50 a 3).
float swingupPumpRefMaxDeg = 70.0f;

// Recentrado del bombeo (`?pc=`). Medido en banco: el centro de oscilacion del brazo
// durante el bombeo se sienta en -18 a -36 deg en vez de 0, asi que el brazo toca su
// limite de 95 por un lado mientras por el otro apenas llega a ~40 — desperdicia la
// mitad del recorrido util, que es justo lo que limita la energia inyectable.
// Se resta una media LENTA de la posicion a la referencia de bombeo. Lenta a
// proposito: la referencia oscila a la frecuencia del pendulo (~2.3 Hz) y restarle
// algo rapido cancelaria el bombeo en vez de recentrarlo.
float swingupCenterGain = 0.0f;    // 0 = desactivado (comportamiento previo)

// ── Ley de bombeo (`?pl=`) ──────────────────────────────────────────────────
// 0 = resonante (la historica): sigue una referencia de POSICION proporcional a
//     alpha_dot. Medida en banco, se estanca en alpha ~143 deg (E/E* = 0.904) y
//     satura el PWM el 100% del tiempo, con lo que ke_gain no puede influir.
// 1 = energia (Astrom-Furuta): acelera el brazo segun
//         u = k (E* - E) sign(alpha_dot * cos alpha)
//     Maximiza la inyeccion de energia por ciclo con el mismo esfuerzo maximo, y
//     se anula sola al llegar a E* — o sea que no hay que frenarla con un umbral.
//
// OJO con la convencion: aca alpha se mide desde COLGANDO (vertical = 180 deg).
// Con beta = alpha - 180 (desde la vertical) vale cos(beta) = -cos(alpha), y la ley
// clasica u = k(E - E_top) sign(beta_dot cos beta) se reduce a la forma de arriba.
uint8_t swingupPumpLaw = 0;
float   swingupEnergyGain = 8000.0f;  // PWM por joule de deficit; con E*~0.032 J y
                                      // PWM tope 50, satura mientras falte >0.6% de
                                      // energia y dessatura solo muy cerca del final
float   swingupPumpSign = 1.0f;       // `?pn=`: signo global, por si el cableado invierte
float swing_posMean = 0.0f;        // EMA de la posicion del brazo
const float SWING_POSMEAN_ALPHA = 0.001f;  // ~2 s de constante de tiempo a 500 Hz

// ── Techo de energia del bombeo (2026-08-04) ─────────────────────────────────
// La ley resonante (pl=0, la que corre por defecto) hace `pump_ref = alpha_dot * K`:
// cuanto mas rapido va el pendulo, mas grande la referencia y mas se bombea. Es
// autorreforzante y NO tiene ningun termino que la apague sola — a diferencia de la
// ley de Astrom-Furuta (pl=1), donde el factor (E* - E) se encarga.
//
// Consecuencia: lo unico que detenia el bombeo era el traspaso al LQR. Con `tr=0`, o
// si el traspaso simplemente no dispara, el pendulo se embala sin techo. Medido el
// 2026-08-04: 18 vueltas en 12 s, suficiente para saturar el contador del encoder
// (P17) y dejar alpha sin sentido fisico.
//
// El anti-spin que ya existia no alcanza: frena el BRAZO, y un pendulo girando sobre
// un brazo quieto solo pierde energia por friccion. El cooldown expira y el bombeo
// vuelve a inyectar.
//
// 1.0 = energia justa para llegar a la vertical. El traspaso normal dispara con
// E/E* ~ 0.96-1.00, muy por debajo del techo, asi que esto NO cambia la sintonia:
// solo corta el caso patologico.
// Configurable por HTTP (`?ec=`) como el resto de los parametros del swing-up, y por una
// razon concreta: un guardian que nunca se ejecuto no es un guardian. Bajando el techo se
// puede forzar el camino de codigo y verlo actuar, sin tener que esperar a que se de la
// condicion patologica — que es rara y ademas depende de que el brazo no toque el tope
// antes (P12). Este proyecto ya pago tres veces el creer en codigo que nunca corrio.
float swingupEnergyCeiling = 1.15f;
// Respaldo, por si el techo de energia no alcanzara: vueltas completas toleradas en un
// mismo intento antes de abortar a modo 0. El bombeo sano no completa ninguna; P2
// necesita al menos una para medir la meseta con `tr=0`, asi que 3 deja margen.
const int SWINGUP_MAX_TURNS = 3;
int swing_wrapsAtStart = 0;   // `pend_wrapCount` al entrar al modo 5
// Ticks en los que el techo corto la inyeccion durante el intento en curso. Se expone en
// /state: sin esto, que el guardian actue o no es indistinguible desde afuera.
uint32_t swing_ceilingHits = 0;
const float SWINGUP_PUMP_KP_SCALE    = 4.0f;      // Kp_pump = ke_gain * esto
const float SWINGUP_IMPROVE_DEG      = 5.0f;      // Mejora minima de angulo que rearma el detector de calado
// Frenado proporcional durante el recovery (fraccion de swingupPwmMax por rad/s).
const float SWINGUP_RECOVER_GAIN     = 0.4f;
// El umbral de transicion NO es configurable por HTTP. El antiguo `?bt=`
// (balance_threshold) apuntaba a una variable que ningun lazo leia; si hace
// falta barrer el umbral, exponer SWINGUP_TRANS_NEAR_DEG, que si se usa.

unsigned long lastControlUs = 0;
unsigned long lastTelemetryMs = 0;
unsigned long lastCommandMs = 0;
// ── Instrumentacion del lazo de control ──────────────────────────────────────
// loopMaxPeriodUs: peor periodo real entre ticks desde el ultimo reset. A 500 Hz
// el nominal es 2000 us; lo que interesa es cuanto se aparta bajo carga de WiFi.
// loopOverruns: cuantas veces el atraso supero LOOP_RESYNC_PERIODS y hubo que
// re-sincronizar. Ambos se exportan en /state y se reinician con /cmd?rj=1.
unsigned long loopMaxPeriodUs = 0;
unsigned long loopOverruns = 0;
const unsigned long LOOP_RESYNC_PERIODS = 5;  // >10 ms de atraso => re-sincronizar

// ── WiFi Configuration (stored in NVS/Preferences) ──────────────────────────
Preferences preferences;
const char* AP_SSID = "QUBE-ESP32";
const char* AP_PASS = "qube1234";
// Canal del SoftAP cuando NO hay STA. 1, 6 y 11 son los tres canales que no se
// solapan en 2,4 GHz; 6 es el histórico de este firmware. En AP+STA el canal no se
// elige: se copia del router por escaneo (ver setup()), porque la radio es una sola.
const uint8_t AP_CHANNEL = 6;
// Rol de radio. Por defecto SoftAP PURO: el PC se asocia a QUBE-ESP32 y llega a
// 192.168.4.1. La coexistencia AP+STA sobre una radio única fue la causa MEDIDA de
// los picos de latencia de ~100 ms (CHANGELOG v1.50.0, verificada en tres flasheos
// OTA: ni setSleep(false) ni WIFI_PS_NONE los quitaron, el beacon sí); apagar el STA
// la elimina de raíz en vez de paliarla. Evaluación completa, ventajas/desventajas y
// protocolo de medición A/B en docs/research/softap_app_escritorio.md.
// Para volver a AP+STA sin editar este archivo:  pio run -e esp32dev_apsta
#ifndef QUBE_ENABLE_STA
#define QUBE_ENABLE_STA 0
#endif
const bool ENABLE_STA = (QUBE_ENABLE_STA != 0);  // true: conecta tambien a tu router LAN
char staSsid[33] = "";         // Max 32 chars + null
char staPass[65] = "";         // Max 64 chars + null
// Guardián de reconexión STA no bloqueante (loop()). El ESP32 tiene UNA radio y
// en AP+STA el enlace STA se cae con más facilidad; si el router nos suelta,
// reintentamos periódicamente sin frenar el lazo de control de 500 Hz.
unsigned long lastStaReconnectMs = 0;
const unsigned long STA_RECONNECT_PERIOD_MS = 5000;
AsyncWebServer server(80);
AsyncWebSocket ws("/ws");
INA219_WE ina219(&Wire, 0x40);
bool inaOk = false;
uint8_t inaAddr = 0x40;
float busVoltageV = 0.0f;
float shuntVoltagemV = 0.0f;
float currentmA = 0.0f;
float powermW = 0.0f;

// Recuperación del bus I2C: si un esclavo (p.ej. un INA219 marginal/browned-out)
// quedó sosteniendo SDA en bajo, el maestro no puede generar un START válido y las
// transacciones se cuelgan (incluso con setTimeOut). Se pulsa SCL hasta 9 veces por
// bit-bang para que el esclavo suelte la línea y luego se emite un STOP. Debe llamarse
// ANTES de Wire.begin().
void i2cBusRecover(int sdaPin, int sclPin) {
  pinMode(sclPin, OUTPUT);
  pinMode(sdaPin, INPUT_PULLUP);
  for (int i = 0; i < 9 && digitalRead(sdaPin) == LOW; i++) {
    digitalWrite(sclPin, LOW);  delayMicroseconds(5);
    digitalWrite(sclPin, HIGH); delayMicroseconds(5);
  }
  // Condición de STOP: SDA de bajo a alto con SCL alto.
  pinMode(sdaPin, OUTPUT);
  digitalWrite(sdaPin, LOW);  delayMicroseconds(5);
  digitalWrite(sclPin, HIGH); delayMicroseconds(5);
  digitalWrite(sdaPin, HIGH); delayMicroseconds(5);
}

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

void resetPendulumOffsetHere();   // definida mas abajo

// Cero manual del pendulo (`zp=1`). Correcto SOLO con el mecanismo colgando en
// reposo — ahi colgando es el cero fisico por definicion. Delega en
// resetPendulumOffsetHere() para heredar la re-siembra del filtro de velocidad: el
// salto del offset es una discontinuidad y sin re-sembrar entra como un pico.
void zeroPendulumHere() {
  resetPendulumOffsetHere();
}

// Re-centra el cero del pendulo en la posicion actual y re-siembra el filtro de
// velocidad. Los modos 4 y 5 hacen esto cada vez que el pendulo acumulo vueltas
// y hay que devolver la lectura a [-180,180]; estaban las mismas lineas copiadas
// en cuatro lugares (F11) y una de ellas se olvidaba de re-sembrar el filtro, con
// lo que el salto del offset entraba como un pico de velocidad enorme.
// ⚠ Esta funcion define el cero DONDE ESTE el pendulo al llamarla. Eso es correcto
// solo cuando se sabe que esta colgando (comando `zp=1` con el mecanismo en reposo).
// NO sirve para acotar la lectura tras acumular vueltas, que era para lo que se usaba
// en los lazos: ver wrapPendulumTurns() abajo y P13 en docs/REGISTRO_PROBLEMAS.md.
void resetPendulumOffsetHere() {
  pendulumOffsetDeg = pendulumDir * getPendulumCountAtomic() * getPendulumDegPerCount();
  pendPosRawPrev = 0.0f;
  rl_vf_init = false;  // el salto del offset invalida el estado del filtro
}

// Acota la lectura del pendulo a [-180, 180] restando VUELTAS ENTERAS.
//
// P13 (2026-07-30): los lazos llamaban a resetPendulumOffsetHere() para esto, pero
// esa funcion pone el cero donde este el pendulo en ese instante, con lo que
// "colgando" dejaba de ser 0 deg y no volvia. Medido con el pendulo colgando e
// inmovil: raw=41.8, offset=-56.3, y `pend_position_deg` reportando 98 deg.
//
// El dano no era solo de telemetria. Los umbrales de traspaso del swing-up comparan
// contra |pendPos|, asi que con el cero corrido un pendulo COLGANDO ya superaba los
// 155 deg y el modo 5 traspasaba al LQR en ~1 s sin haber bombeado. Varios ensayos de
// esa jornada midieron el sesgo creyendo medir el angulo (uno reporto 241 deg, que
// para un angulo medido desde colgando es imposible sin envolver).
//
// Restar multiplos de 360 preserva la congruencia con el angulo fisico: el valor
// sigue significando lo mismo, solo que acotado.
void wrapPendulumTurns() {
  const float pos = getPendulumPositionDeg();
  const float turns = roundf(pos / 360.0f);
  if (fabsf(turns) < 0.5f) {
    return;                       // dentro de [-180,180]: nada que hacer
  }
  pendulumOffsetDeg += turns * 360.0f;
  pend_wrapCount++;
  // El valor reportado salta 360 deg de golpe aunque el angulo fisico no cambie.
  //
  // NO se reinicia el filtro de velocidad: se DESPLAZA su estado por el mismo salto.
  // Reiniciarlo (rl_vf_init = false) hacia que la velocidad reportada fuera 0 en el
  // tick siguiente — y el acotado se dispara justo al cruzar la vertical, que es
  // exactamente donde las compuertas de velocidad deciden el traspaso a LQR. El
  // efecto medido el 2026-07-31: un traspaso registrado como "alpha=178.4, vel=0.0,
  // E/E*=1.000" cuando la traza muestra al pendulo pasando a ~470 deg/s. La compuerta
  // `verySlow` se cumplia SIEMPRE al cruzar arriba, sin importar la velocidad real.
  //
  // updateRlObservation usa xal = -pendPosRaw * DEG_TO_RAD, y pendPosRaw baja en
  // turns*360, asi que xal sube en turns*360*DEG_TO_RAD: el estado previo tiene que
  // subir lo mismo para que la diferencia (xal - prev) quede continua.
  rl_vf_alPrev += turns * 360.0f * DEG_TO_RAD;
  pendPosRawPrev -= turns * 360.0f;   // el detector de giro guarda pendPosRaw
}


void resetLqr() {
  lqr_prevTheta = getPositionDeg();
  lqr_prevAlpha = getPendulumPositionDeg();
  lqr_filteredVelTheta = 0.0f;
  lqr_filteredVelAlpha = 0.0f;
  kalmanReset();
  // Invalida el cronometro de supervivencia: el modo 4 lo re-siembra al terminar el
  // catch. `lqr_aliveMs` NO se toca a proposito — es el resultado del intento previo
  // y tiene que sobrevivir a la caida para poder leerse por /state despues.
  lqr_catchEndMs = 0;
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
// setMotorDirect: aplica el PWM tal cual, SIN soft saturation. Es el unico punto
// que toca el puente H; setMotor() es esta misma funcion con la atenuacion por
// posicion aplicada antes. (Antes cada una repetia el arbol completo, ENA
// incluida — tres copias del mismo despacho.)
void setMotorDirect(int pwmValue) {
  pwmValue = constrain(pwmValue, -255, 255);
  lastPwmCmd = pwmValue;

  if (USE_ENA_PWM) {
    // Rama para wiring tipo ENA/dir (BTS7960 R_EN/L_EN). Inactiva en el hardware
    // L298N actual (jumper ENA puesto, GPIO25 sin conectar), se conserva porque el
    // proyecto ya cambio de driver en ambos sentidos.
    digitalWrite(PIN_IN1, pwmValue > 0 ? HIGH : LOW);
    digitalWrite(PIN_IN2, pwmValue < 0 ? HIGH : LOW);
    pwmWriteCompat(PIN_ENA, PWM_CH_ENA, abs(pwmValue));
    return;
  }

  // L298N con PWM dual sobre IN1/IN2: el lado inactivo va a 0.
  pwmWriteCompat(PIN_IN1, PWM_CH_IN1, pwmValue > 0 ?  pwmValue : 0);
  pwmWriteCompat(PIN_IN2, PWM_CH_IN2, pwmValue < 0 ? -pwmValue : 0);
}

// setMotor: salida normal del lazo, con soft saturation cerca de los limites
// mecanicos del servo. Factor = 1 / (1 + (|pos|/k)^2) con k = SOFT_SAT_K_DEG.
// En pos=0: 1.00 · en 60°: 0.92 · en 90°: 0.83 · en 95°: 0.82.
// (El comentario anterior decia k=120 y factores 0.80/0.64: describia una version
// del codigo que ya no existia — auditoria F19.)
void setMotor(int pwmValue) {
  const float k = fabsf(lastServoPos) / SOFT_SAT_K_DEG;
  const float pos_factor = 1.0f / (1.0f + k * k);   // era powf(x, 2.0f) en cada llamada
  setMotorDirect((int)(pwmValue * pos_factor));
}


void setMode(int newMode) {
  // Punto único de cambio de modo. Usado por HTTP y Serial para garantizar
  // que las mismas rutinas de reset y flags se ejecuten siempre.
  if (newMode < 0 || newMode > 7) return;
  // Stop the motor on ANY mode transition. Previously only mode 0 did this, so
  // switching e.g. 1->4 or 5->4 left the previous mode's last PWM applied until
  // the new mode's loop recomputed it. The new mode recomputes PWM within one
  // 2 ms tick, so a brief stop here is safe and avoids torque carry-over.
  setMotor(0);
  mode = newMode;
  swing_recovering = false;  // Reset recovery state al cambiar de modo
  resetPid();
  // Limpiar el estado transitorio de TODOS los modos en CADA transicion. Antes
  // estas variables eran static locales de loop() y sobrevivian al cambio de
  // modo, arrastrando la fase del hibrido y las ventanas de catch (F5).
  resetModeState();
  if (mode == 4) {
    resetLqr();
    lqr_inFallback = false;
    spinCooldownMs = 0;  // Reset cooldown anti-spin para no interferir con LQR
  }
  if (mode == 0) {
    setMotor(0);
    lqr_inFallback = false;
  }
  if (mode == 3) {
    // Homing: se limpian los resultados previos para que /state no reporte una
    // calibracion vieja como si fuera de esta corrida.
    homing_ok = false;
    homing_failCode = 0;
    homing_stopPosRaw = 0.0f;
    homing_stopNegRaw = 0.0f;
    homing_rangeDeg = 0.0f;
    homing_centerRaw = 0.0f;
    homing_pwmSign = 1.0f;
    homing_prevPendRaw = getPendulumPositionDeg();
    homing_prevArmRaw = getRawPositionDeg();
    homing_quietMs = millis();
    homingEnterPhase(H_WAIT_QUIET, getRawPositionDeg());
  }
  if (mode == 5) {
    prev_alpha_dot_peak = 0.0f;  // Reset peak detection
    swing_maxAngleAchieved = 0.0f;  // Reset adaptive ke_gain
    swing_lastImprovementMs = millis();
    swing_posMean = 0.0f;   // el recentrado no debe arrastrar la media del intento previo
    // Limpiar el latch del traspaso: lo que se lea en /state debe corresponder al
    // intento en curso, no arrastrar el anterior y hacerlo pasar por nuevo.
    swing_transReason = 0;
    swing_transAlphaDeg = 0.0f;
    swing_transVelDps = 0.0f;
    swing_transEnergyRatio = 0.0f;
    swing_wrapsAtStart = pend_wrapCount;  // el corte por vueltas cuenta desde ACA
    swing_ceilingHits = 0;
    swing_transMs = 0;
    // El swing-up consume el filtro de velocidad de convencion sim (compartido
    // con los modos 6 y 7): hay que re-sembrarlo o el primer tick ve un salto.
    rl_vf_init = false;
    rl_obs_th = rl_obs_al = rl_obs_thd = rl_obs_ald = 0.0f;
    // Solo reset ke_gain si no fue configurado por HTTP
    // (ke_gain fue seteado por cmd?ke= antes de cmd?m=5)
  }
  if (mode == 6) {
    rlAction = 0.0f;
    lqr_prevTheta = getPositionDeg();
    lqr_prevAlpha = getPendulumPositionDeg();
    lqr_filteredVelTheta = 0.0f;
    lqr_filteredVelAlpha = 0.0f;
    rl_vf_init = false;  // re-init the sim-convention velocity filter (shared with mode 7)
    rl_obs_th = rl_obs_al = rl_obs_thd = rl_obs_ald = 0.0f;
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

// ── Homing (modo 3) ──────────────────────────────────────────────────────────
const char *homingPhaseName(uint8_t p) {
  switch (p) {
    case H_WAIT_QUIET:  return "WAIT_QUIET";
    case H_SEEK_POS:    return "SEEK_POS";
    case H_BACKOFF_POS: return "BACKOFF_POS";
    case H_TOUCH_POS:   return "TOUCH_POS";
    case H_SEEK_NEG:    return "SEEK_NEG";
    case H_BACKOFF_NEG: return "BACKOFF_NEG";
    case H_TOUCH_NEG:   return "TOUCH_NEG";
    case H_GOTO_CENTER: return "GOTO_CENTER";
    case H_DONE:        return "DONE";
    case H_FAIL:        return "FAIL";
    default:            return "IDLE";
  }
}

void homingEnterPhase(uint8_t phase, float rawPos) {
  homing_phase = phase;
  homing_phaseMs = millis();
  homing_refRaw = rawPos;
  // El detector de calado se rearma en CADA fase: sin esto se arrastra la
  // quietud de la fase anterior y el primer tick de la nueva reporta un tope
  // falso en la posicion de partida.
  homing_lastMoveRaw = rawPos;
  homing_lastMoveMs = millis();
}

void homingFail(uint8_t code) {
  setMotorDirect(0);
  homing_ok = false;
  homing_failCode = code;
  homing_phase = H_FAIL;
  Serial.printf("[HOMING] FAIL code=%u range=%.2f\n", code, homing_rangeDeg);
  setMode(0);
}

// Se llama desde el lazo de 500 Hz con la posicion CRUDA del brazo. Usa
// setMotorDirect() en todo momento: la soft saturation de setMotor() escala el
// PWM por 1/(1+(|lastServoPos|/200)^2), y lastServoPos deriva del offset que
// aqui todavia es invalido.
void runHoming(float rawPos, float pendPos) {
  const unsigned long nowMs = millis();
  const unsigned long phaseAge = nowMs - homing_phaseMs;

  // Deteccion de calado por encoder: si el brazo no avanza HOMING_STALL_DEG en
  // HOMING_STALL_MS con par aplicado, esta contra el tope. No depende del
  // INA219 (cuya ausencia deja sin corte por corriente) ni de un temporizador
  // fijo, que obligaria a empujar contra el tope durante segundos.
  if (fabsf(rawPos - homing_lastMoveRaw) > HOMING_STALL_DEG) {
    homing_lastMoveRaw = rawPos;
    homing_lastMoveMs = nowMs;
  }
  const bool stalled = (nowMs - homing_lastMoveMs) > HOMING_STALL_MS;

  switch (homing_phase) {
    case H_WAIT_QUIET: {
      setMotorDirect(0);
      // Un pendulo oscilando ejerce reaccion sobre el brazo y puede simular o
      // enmascarar un calado. Se exige quietud SOSTENIDA por ventana, no una
      // velocidad instantanea: a 500 Hz la diferencia entre dos muestras del
      // encoder es o cero o un salto de un conteo entero, asi que cualquier
      // umbral sobre esa "velocidad" mide cuantizacion, no movimiento.
      //
      // Antes, al agotarse el timeout se arrancaba IGUAL, con el comentario de que
      // "el riesgo es de repetibilidad y no de dano". Eso estaba mal: el riesgo real
      // es un CERO EQUIVOCADO aceptado en silencio. Medido el 2026-07-30, lanzando
      // el homing enseguida despues de un swing-up, 3 de 24 corridas detectaron el
      // tope + unos 19 deg antes del real y fijaron un offset corrido ~10 deg. Ahora
      // no aquietarse es una FALLA (codigo 5), no una advertencia.
      //
      // Se vigila el brazo ADEMAS del pendulo: tras un intento energetico los dos
      // quedan con inercia, y un brazo que todavia se mueve falsea igual el calado.
      if (fabsf(pendPos - homing_prevPendRaw) > HOMING_QUIET_DEG ||
          fabsf(rawPos - homing_prevArmRaw) > HOMING_QUIET_DEG) {
        homing_prevPendRaw = pendPos;
        homing_prevArmRaw = rawPos;
        homing_quietMs = nowMs;
      }
      if ((nowMs - homing_quietMs) > HOMING_QUIET_HOLD_MS) {
        Serial.println("[HOMING] start");
        homingEnterPhase(H_SEEK_POS, rawPos);
      } else if (phaseAge > HOMING_QUIET_TIMEOUT_MS) {
        homingFail(5);
      }
      break;
    }

    case H_SEEK_POS:
    case H_TOUCH_POS:
    case H_SEEK_NEG:
    case H_TOUCH_NEG: {
      const bool positive = (homing_phase == H_SEEK_POS || homing_phase == H_TOUCH_POS);
      const bool fast = (homing_phase == H_SEEK_POS || homing_phase == H_SEEK_NEG);
      // Frenado de aproximacion: el seek arranca a HOMING_PWM_SEEK y baja a la
      // velocidad de toque en los ultimos HOMING_SEEK_SLOW_DEG, para no llegar al
      // tope a plena marcha. Si no hay forma de predecir donde esta el tope, se
      // mantiene el comportamiento anterior — nunca frena "por las dudas".
      int homingPwm = fast ? HOMING_PWM_SEEK : HOMING_PWM_TOUCH;
      if (fast) {
        if (homing_phase == H_SEEK_NEG) {
          // El tope opuesto ya se midio EN ESTA corrida. La prediccion sale de cuanto
          // se lleva recorrido desde el, asi que no depende del signo del cableado
          // (que en este punto todavia no se aprendio: homing_pwmSign se fija recien
          // al terminar el toque negativo).
          const float travelled = fabsf(rawPos - homing_stopPosRaw);
          const float expected = homing_prevValid ? homing_prevRangeDeg : HOMING_RANGE_NOM_DEG;
          if (travelled > expected - HOMING_SEEK_SLOW_DEG) homingPwm = HOMING_PWM_TOUCH;
        } else if (homing_prevValid) {
          // Primer tope: se usa la medicion de la corrida anterior.
          if (fabsf(rawPos - homing_prevStopPosRaw) < HOMING_SEEK_SLOW_DEG) homingPwm = HOMING_PWM_TOUCH;
        }
      }
      setMotorDirect((positive ? 1 : -1) * homingPwm);

      // En el toque lento se exige haber recorrido el backoff antes de creerle
      // al detector: a PWM bajo la friccion estatica puede retrasar el arranque
      // y eso se veria como un tope 5 deg adelantado.
      const bool moved = fabsf(rawPos - homing_refRaw) > HOMING_TOUCH_MIN_DEG;
      if (stalled && (fast || moved)) {
        setMotorDirect(0);
        if (fast) {
          homingEnterPhase(positive ? H_BACKOFF_POS : H_BACKOFF_NEG, rawPos);
        } else if (positive) {
          homing_stopPosRaw = rawPos;
          Serial.printf("[HOMING] stop+ = %.2f\n", rawPos);
          homingEnterPhase(H_SEEK_NEG, rawPos);
        } else {
          homing_stopNegRaw = rawPos;
          Serial.printf("[HOMING] stop- = %.2f\n", rawPos);
          // Aprender el sentido: en esta fase se aplico PWM negativo y el brazo
          // recorrio al menos HOMING_TOUCH_MIN_DEG, asi que el signo del
          // desplazamiento revela como mapea el PWM sobre el encoder.
          homing_pwmSign = (rawPos < homing_refRaw) ? 1.0f : -1.0f;
          // En valor absoluto: cual de los dos topes cae en el lado positivo del
          // encoder depende del cableado, y con el orden invertido un recorrido
          // perfectamente valido daria negativo y seria rechazado.
          homing_rangeDeg = fabsf(homing_stopPosRaw - homing_stopNegRaw);
          homing_centerRaw = 0.5f * (homing_stopPosRaw + homing_stopNegRaw);
          // Validar ANTES de fijar el cero. Un recorrido fuera de tolerancia
          // significa acople suelto o encoder que no cuenta (en ese caso el
          // calado dispara de inmediato en ambos lados y el rango da ~0).
          // Calibrar sobre esa medicion es peor que no calibrar.
          if (homing_rangeDeg < HOMING_RANGE_MIN_DEG || homing_rangeDeg > HOMING_RANGE_MAX_DEG) {
            homingFail(1);
          } else {
            // Semilla del frenado de aproximacion para la proxima corrida. Solo se
            // guarda una medicion que paso la validacion de recorrido: sembrar con un
            // homing malo haria frenar en el lugar equivocado.
            homing_prevStopPosRaw = homing_stopPosRaw;
            homing_prevRangeDeg   = homing_rangeDeg;
            homing_prevValid      = true;
            homingEnterPhase(H_GOTO_CENTER, rawPos);
          }
        }
      } else if (phaseAge > HOMING_SIDE_TIMEOUT_MS) {
        homingFail(positive ? 2 : 3);
      }
      break;
    }

    case H_BACKOFF_POS:
    case H_BACKOFF_NEG: {
      // Retroceso corto para volver a entrar lento: los topes tienen algo de
      // compliance y el tren tiene backlash, y es el segundo toque el que da
      // repetibilidad entre calibraciones.
      const bool positive = (homing_phase == H_BACKOFF_POS);
      setMotorDirect((positive ? -1 : 1) * HOMING_PWM_TOUCH);
      if (fabsf(rawPos - homing_refRaw) >= HOMING_BACKOFF_DEG) {
        setMotorDirect(0);
        homingEnterPhase(positive ? H_TOUCH_POS : H_TOUCH_NEG, rawPos);
      } else if (phaseAge > HOMING_SIDE_TIMEOUT_MS) {
        homingFail(positive ? 2 : 3);
      }
      break;
    }

    case H_GOTO_CENTER: {
      const float errDeg = homing_centerRaw - rawPos;
      const bool inTol = fabsf(errDeg) < HOMING_CENTER_TOL_DEG;
      // Estar dentro de tolerancia NO basta: setMotorDirect(0) deja el puente en
      // corte, no en freno, asi que el brazo sigue por inercia. En la corrida del
      // 2026-07-30 cruzo el centro a PWM 70, declaro DONE, y siguio de largo 126
      // deg hasta el tope opuesto — con homing_ok=true y el brazo fuera del
      // limite blando. Se exige ademas que este detenido.
      if (inTol && stalled) {
        setMotorDirect(0);
        // El cero es el centro geometrico MEDIDO, no donde quedo estacionado el
        // brazo: asi el offset no arrastra el error de posicionamiento final.
        positionOffsetDeg = homing_centerRaw;
        setpoint_deg = 0.0f;
        homing_ok = true;
        homing_failCode = 0;
        homing_phase = H_DONE;
        Serial.printf("[HOMING] OK stop+=%.2f stop-=%.2f range=%.2f center=%.2f\n",
                      homing_stopPosRaw, homing_stopNegRaw, homing_rangeDeg, homing_centerRaw);
        setMode(0);
      } else if (inTol) {
        // Dentro de tolerancia pero todavia rodando: soltar y dejar que frene
        // sola. Si la inercia la saca de la ventana, el lazo la vuelve a traer.
        setMotorDirect(0);
      } else if (fabsf(errDeg) > 0.5f * homing_rangeDeg + 10.0f) {
        // Alejarse del centro mas que el propio recorrido solo puede significar
        // que homing_pwmSign quedo mal y el lazo esta realimentando en positivo.
        // Cortar aca en vez de empujar contra el tope hasta agotar el timeout.
        homingFail(4);
      } else if (phaseAge > HOMING_CENTER_TIMEOUT_MS) {
        homingFail(4);
      } else {
        // homing_pwmSign cierra el lazo con el sentido correcto: sin el, una
        // convencion de cableado invertida convierte esto en realimentacion
        // positiva y el brazo se va contra el tope hasta el timeout.
        int pwm = (int)(HOMING_CENTER_KP * errDeg * homing_pwmSign);
        // Techo dependiente de la distancia: cerca del centro hay que llegar
        // despacio, porque lo que para al brazo es la friccion y no un freno.
        const int cap = (fabsf(errDeg) < HOMING_CENTER_SLOW_DEG)
                        ? HOMING_PWM_MIN : HOMING_PWM_SEEK;
        pwm = constrain(pwm, -cap, cap);
        if (pwm > 0 && pwm < HOMING_PWM_MIN) pwm = HOMING_PWM_MIN;
        if (pwm < 0 && pwm > -HOMING_PWM_MIN) pwm = -HOMING_PWM_MIN;
        setMotorDirect(pwm);
      }
      break;
    }

    default:
      setMotorDirect(0);
      break;
  }
}

// Watchdog del INA219: cada WATCHDOG_PERIOD_MS verificamos que el sensor
// sigue respondiendo en I2C. Si falla, marcamos inaOk=false y reintentamos
// la inicialización con la lista de direcciones candidatas.
static unsigned long lastInaWatchdogMs = 0;
static unsigned long lastInaRetryMs = 0;
void updateIna219() {
  const unsigned long nowMs = millis();
  if (inaOk && (nowMs - lastInaWatchdogMs) >= INA_WATCHDOG_PERIOD_MS) {
    lastInaWatchdogMs = nowMs;
    // ACK-poll: si el dispositivo no responde, endTransmission() != 0.
    Wire.beginTransmission(inaAddr);
    if (Wire.endTransmission() != 0) {
      inaOk = false;
      lastInaRetryMs = nowMs;  // arrancar el temporizador de reintento
      Serial.println("[INA219] Watchdog: sensor no responde, reintentando…");
    }
  }
  if (!inaOk) {
    // Reintentar init con throttle a INA_INIT_RETRY_MS. Antes se re-escaneaba el bus
    // I2C (bloqueante, 4 direcciones) en CADA tick de telemetria cuando el sensor
    // estaba ausente —lastInaWatchdogMs no se actualizaba en esta rama, así que la
    // condición siempre daba true—, metiendo jitter en el lazo. Ahora usa su propio
    // temporizador y respeta INA_INIT_RETRY_MS (5 s).
    if ((nowMs - lastInaRetryMs) >= INA_INIT_RETRY_MS) {
      lastInaRetryMs = nowMs;
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

// ══════════════════════════════════════════════════════════════════════════════
//  DAQ — adquisición por bloques
// ══════════════════════════════════════════════════════════════════════════════
// El ESP32 muestrea a la tasa del lazo (500 Hz / decim) en un buffer circular y el
// PC se lleva BLOQUES. Es lo contrario del lazo PC-en-el-lazo: la adquisición está
// limitada por CAUDAL, no por latencia, así que un bloque que tarde 30 ms en llegar
// no degrada nada — la serie se reconstruye con el `t_us` de cada muestra, tomado en
// el instante del tick. Un round-trip por muestra a 500 Hz, en cambio, pide 16x más
// de lo que el enlace sostiene (31 Hz medidos, CHANGELOG v1.50.0).
//
// Se transmiten ángulos CRUDOS y el PWM: derivar, filtrar y envolver es trabajo del
// PC, que es justamente el punto de una arquitectura de adquisición. `al_deg` va SIN
// envolver a propósito — el salto de ±180° arruina cualquier derivada numérica.
//
// Productor: el lazo de control (core 1). Consumidor: el handler HTTP (core 0).
// Buffer SPSC: sólo el productor mueve `daqHead` y sólo el consumidor mueve
// `daqTail`, así que la ruta de 500 Hz no necesita sección crítica.
#define DAQ_PROTO_VERSION 1
#define DAQ_MAGIC 0x51414451UL          // 'Q','D','A','Q' little-endian
#define DAQ_CAPACITY 2048               // muestras (32 KB); 4,1 s a 500 Hz
#define DAQ_MAX_BLOCK 512               // muestras por respuesta (8 KB)
#define DAQ_HEADER_BYTES 16

struct __attribute__((packed)) DaqSample {
  uint32_t t_us;      // micros() del tick que la produjo
  float    th_deg;    // posición del servo, con offset aplicado
  float    al_deg;    // péndulo CRUDO, sin envolver a [-180,180]
  int16_t  pwm;       // comando aplicado al motor en ese tick
  uint8_t  mode;      // modo activo
  uint8_t  flags;     // bit0: ina_ok
};
static_assert(sizeof(DaqSample) == 16, "DaqSample debe medir 16 bytes exactos");

DaqSample daqBuf[DAQ_CAPACITY];
volatile uint32_t daqHead = 0;      // muestras producidas (monotónico)
volatile uint32_t daqTail = 0;      // muestras consumidas (monotónico)
volatile uint32_t daqDropped = 0;   // perdidas por buffer lleno
volatile bool     daqRunning = false;
uint16_t daqDecim = 1;              // 1 = 500 Hz, 10 = 50 Hz, ...
uint16_t daqDecimCount = 0;

// Staging de transmisión + candado. `beginResponse_P` NO copia: lee del puntero a
// medida que transmite, así que el buffer debe sobrevivir a la respuesta. Con un
// único consumidor (el contrato de este DAQ) alcanza con rechazar la segunda
// petición concurrente en vez de arriesgar una lectura sobre datos ya pisados.
uint8_t daqTxBuf[DAQ_HEADER_BYTES + DAQ_MAX_BLOCK * sizeof(DaqSample)];
volatile bool daqTxBusy = false;

// Captura la muestra de este tick. Con la adquisición detenida (por defecto) cuesta
// una lectura de bool: la ruta de 500 Hz no paga por algo que nadie encendió.
inline void daqPush(uint32_t t_us, float th_deg, float al_raw_deg) {
  if (!daqRunning) return;
  if (++daqDecimCount < daqDecim) return;
  daqDecimCount = 0;
  // Buffer lleno: se descarta la muestra NUEVA y se cuenta. Sobrescribir la vieja
  // perdería historia en silencio; así el PC siempre sabe cuánto le faltó.
  if ((daqHead - daqTail) >= DAQ_CAPACITY) {
    daqDropped++;
    return;
  }
  DaqSample &s = daqBuf[daqHead % DAQ_CAPACITY];
  s.t_us = t_us;
  s.th_deg = th_deg;
  s.al_deg = al_raw_deg;
  s.pwm = (int16_t)lastPwmCmd;
  s.mode = (uint8_t)mode;
  s.flags = inaOk ? 0x01 : 0x00;
  daqHead++;  // publicar DESPUÉS de escribir: el consumidor no ve muestras a medias
}

String getDaqStatusJson() {
  const uint32_t avail = daqHead - daqTail;
  String json = "{";
  json += "\"pv\":" + String(DAQ_PROTO_VERSION) + ",";
  json += "\"running\":" + String(daqRunning ? "true" : "false") + ",";
  json += "\"decim\":" + String(daqDecim) + ",";
  json += "\"rate_hz\":" + String(1000000.0f / (CONTROL_PERIOD_US * (float)daqDecim), 1) + ",";
  json += "\"capacity\":" + String(DAQ_CAPACITY) + ",";
  json += "\"max_block\":" + String(DAQ_MAX_BLOCK) + ",";
  json += "\"sample_bytes\":" + String((int)sizeof(DaqSample)) + ",";
  json += "\"available\":" + String(avail) + ",";
  json += "\"produced\":" + String(daqHead) + ",";
  json += "\"dropped\":" + String(daqDropped);
  json += "}";
  return json;
}

// GET /daq?start=1[&decim=N] | ?stop=1 | (sin parámetros) -> estado en JSON
void handleDaq(AsyncWebServerRequest *request) {
  if (request->hasParam("decim")) {
    daqDecim = (uint16_t)constrain(request->getParam("decim")->value().toInt(), 1, 500);
  }
  if (request->hasParam("start")) {
    // Arrancar SIEMPRE vacía el buffer: mezclar muestras de dos sesiones daría una
    // serie con un salto temporal que nadie podría distinguir de un dato real.
    daqRunning = false;
    daqTail = daqHead;
    daqDropped = 0;
    daqDecimCount = 0;
    daqRunning = true;
  }
  if (request->hasParam("stop")) {
    daqRunning = false;
  }
  AsyncWebServerResponse *response =
      request->beginResponse(200, "application/json", getDaqStatusJson());
  response->addHeader("Access-Control-Allow-Origin", "*");
  request->send(response);
}

// GET /daq/read -> bloque binario little-endian:
//   cabecera 16 B: magic u32 | pv u8 | sample_bytes u8 | n u16 | dropped u32 | t_now u32
//   luego n x DaqSample (16 B c/u)
// `dropped` es acumulado desde el último start: el PC compara contra el bloque
// anterior y sabe exactamente cuántas muestras faltan y entre qué marcas de tiempo.
void handleDaqRead(AsyncWebServerRequest *request) {
  if (daqTxBusy) {
    // Un solo consumidor por diseño. Antes que servir datos posiblemente pisados,
    // se rechaza y el cliente reintenta.
    AsyncWebServerResponse *busy =
        request->beginResponse(503, "application/json", "{\"ok\":false,\"busy\":true}");
    busy->addHeader("Retry-After", "1");
    request->send(busy);
    return;
  }

  uint32_t avail = daqHead - daqTail;
  if (avail > DAQ_CAPACITY) avail = DAQ_CAPACITY;  // defensivo
  const uint16_t n = (uint16_t)((avail > DAQ_MAX_BLOCK) ? DAQ_MAX_BLOCK : avail);

  daqTxBusy = true;
  const uint32_t magic = DAQ_MAGIC;
  const uint32_t dropped = daqDropped;
  const uint32_t tNow = micros();
  memcpy(daqTxBuf + 0, &magic, 4);
  daqTxBuf[4] = DAQ_PROTO_VERSION;
  daqTxBuf[5] = (uint8_t)sizeof(DaqSample);
  memcpy(daqTxBuf + 6, &n, 2);
  memcpy(daqTxBuf + 8, &dropped, 4);
  memcpy(daqTxBuf + 12, &tNow, 4);
  for (uint16_t i = 0; i < n; i++) {
    memcpy(daqTxBuf + DAQ_HEADER_BYTES + i * sizeof(DaqSample),
           &daqBuf[(daqTail + i) % DAQ_CAPACITY], sizeof(DaqSample));
  }
  // Consumir sólo lo que efectivamente se copió al staging.
  daqTail += n;

  AsyncWebServerResponse *response = request->beginResponse_P(
      200, "application/octet-stream", daqTxBuf, DAQ_HEADER_BYTES + n * sizeof(DaqSample));
  response->addHeader("Access-Control-Allow-Origin", "*");
  request->onDisconnect([]() { daqTxBusy = false; });
  request->send(response);
}

String getStateJson() {
  // NOTE: do NOT call updateIna219() here. getStateJson() runs in the async web
  // server context (handleState / broadcastTelemetry); the I2C Wire library is
  // not reentrant, so touching it here races the 500 Hz control loop that also
  // reads the INA219. The loop refreshes the cached bus/current values every
  // telemetryPeriodMs — we just read those cached globals below.
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
  // Estado crudo de los canales A/B del encoder péndulo (diagnóstico de cuadratura:
  // un canal que queda fijo mientras el péndulo se mueve = canal muerto/suelto).
  json += "\"pend_a\":" + String(digitalRead(PIN_PEND_A)) + ",";
  json += "\"pend_b\":" + String(digitalRead(PIN_PEND_B)) + ",";
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
  json += "\"stiction_err_deg\":" + String(stiction_err_thresh_deg, 2) + ",";
  json += "\"stiction_kick_pwm\":" + String(stiction_kick_pwm, 1) + ",";
  json += "\"vel_alpha\":" + String(velAlpha, 3) + ",";
  json += "\"kf_enabled\":" + String(kf_enabled ? "true" : "false") + ",";
  json += "\"kf_theta\":" + String(kf_x[0], 3) + ",";
  json += "\"kf_alpha\":" + String(kf_x[1], 3) + ",";
  json += "\"kf_dtheta\":" + String(kf_x[2], 2) + ",";
  json += "\"kf_dalpha\":" + String(kf_x[3], 2) + ",";
  // RL action applied to the motor (mode 6/7) and command-timeout watchdog age.
  json += "\"rl_action\":" + String(rlAction, 3) + ",";
  // Homing (modo 3). El cliente hace polling de homing_phase hasta DONE/FAIL:
  // el callback HTTP no puede bloquear esperando (dispararia el watchdog y
  // congelaria el lazo de 500 Hz).
  json += "\"homing_phase\":\"" + String(homingPhaseName(homing_phase)) + "\",";
  json += "\"homing_ok\":" + String(homing_ok ? "true" : "false") + ",";
  json += "\"homing_fail\":" + String(homing_failCode) + ",";
  json += "\"homing_stop_pos\":" + String(homing_stopPosRaw, 3) + ",";
  json += "\"homing_stop_neg\":" + String(homing_stopNegRaw, 3) + ",";
  json += "\"homing_range\":" + String(homing_rangeDeg, 3) + ",";
  json += "\"homing_center\":" + String(homing_centerRaw, 3) + ",";
  // Traspaso swing-up -> LQR. `reason` es un bitmask (1=near+slow, 2=peak,
  // 4=forced, 8=energy) latcheado en el instante de la transicion: leerlo por
  // muestreo del modo llega tarde y da un angulo que no es el del traspaso.
  // `ms_ago` = 0 significa que no hubo transicion en el intento en curso.
  json += "\"pend_wraps\":" + String(pend_wrapCount) + ",";
  json += "\"swing_trans_reason\":" + String(swing_transReason) + ",";
  json += "\"swing_trans_alpha\":" + String(swing_transAlphaDeg, 2) + ",";
  json += "\"swing_trans_vel\":" + String(swing_transVelDps, 2) + ",";
  json += "\"swing_trans_energy\":" + String(swing_transEnergyRatio, 4) + ",";
  json += "\"swing_energy_ceiling\":" + String(swingupEnergyCeiling, 2) + ",";
  json += "\"swing_ceiling_hits\":" + String(swing_ceilingHits) + ",";
  json += "\"swing_trans_ms_ago\":" + String(swing_transMs ? (millis() - swing_transMs) : 0) + ",";
  // Ventana del catch del LQR (P4/H2, H6) + supervivencia latcheada por el firmware.
  // `lqr_alive_ms` cuenta desde el FIN del catch hasta que se salio del modo 4; deja
  // de actualizarse solo, asi que leerlo despues de la caida da el valor final. Se
  // mide aca y no por muestreo del modo desde el cliente porque a 25 Hz de HTTP
  // "sobrevivio 0,3 s" son 7 muestras.
  json += "\"lqr_catch_ms\":" + String(lqr_catchDurMs) + ",";
  json += "\"lqr_centering_grace\":" + String(lqr_centeringGrace ? 1 : 0) + ",";
  json += "\"lqr_alive_ms\":" + String(lqr_aliveMs) + ",";
  // Hibrido del modo 7: umbrales vigentes y en que rama esta corriendo. Sin `hybrid_lqr`
  // no se puede saber si un intento de m7 lo balanceo la politica o el LQR — que es la
  // diferencia entre medir la politica y volver a medir P4.
  json += "\"hybrid_enter_deg\":" + String(hybrid_enter_deg, 1) + ",";
  json += "\"hybrid_exit_deg\":" + String(hybrid_exit_deg, 1) + ",";
  json += "\"hybrid_lqr\":" + String(hybrid_lqr ? 1 : 0) + ",";
  // P21: cuanto cuesta UNA inferencia. `fwd` es solo la red; `step` la incluye mas el
  // armado de la observacion. La diferencia entre ambas separa "la red es lenta" de
  // "los transcendentales del armado son lentos", que exigen arreglos distintos.
  json += "\"rl_fwd_us_last\":" + String(rl_fwd_us_last) + ",";
  json += "\"rl_fwd_us_max\":" + String(rl_fwd_us_max) + ",";
  json += "\"rl_fwd_us_mean\":" + String(rl_infer_count ? (uint32_t)(rl_fwd_us_sum / rl_infer_count) : 0) + ",";
  json += "\"rl_step_us_last\":" + String(rl_step_us_last) + ",";
  json += "\"rl_step_us_max\":" + String(rl_step_us_max) + ",";
  json += "\"rl_step_us_mean\":" + String(rl_infer_count ? (uint32_t)(rl_step_us_sum / rl_infer_count) : 0) + ",";
  json += "\"rl_infer_count\":" + String(rl_infer_count) + ",";
  // Sumas de los pesos en RAM, calculadas UNA VEZ en el arranque. La primera version
  // las recorria en cada llamada a /state — 6.400 flotantes a 25 Hz durante una
  // campana. Instrumentacion que perturba lo que mide: exactamente el defecto que este
  // mismo dia costo dos diagnosticos (P19 y los picos de P21).
  json += "\"rl_w0_sum\":" + String(rl_w0_sum, 6) + ",";
  json += "\"rl_w1_sum\":" + String(rl_w1_sum, 6) + ",";
  json += "\"rl_last_action\":" + String(rl_last_action, 6) + ",";
  // `rl_pwm_scale` es un global que persiste hasta reiniciar y multiplica el torque de
  // la politica. diagnose_real_vs_sim.py lo pone en 0,85 y no se veia por ningun lado:
  // exactamente la clase de variable oculta que ya costo cara con MOTOR_DIR.
  json += "\"rl_pwm_scale\":" + String(rl_pwm_scale, 3) + ",";
  // Salud del lazo de control: periodo real peor caso y re-sincronizaciones desde
  // el ultimo reset (/cmd?rj=1). Con esto los "500 Hz" son un dato medido y no una
  // constante del codigo — y cada traza capturada lleva su propia evidencia de
  // temporizacion.
  json += "\"loop_dt_max_us\":" + String(loopMaxPeriodUs) + ",";
  json += "\"loop_overruns\":" + String(loopOverruns) + ",";
  json += "\"loop_dt_nom_us\":" + String(CONTROL_PERIOD_US) + ",";
  // Estado de la adquisicion: que aparezca en /state permite ver desde la GUI que hay
  // una captura corriendo sin tener que consultar /daq aparte.
  json += "\"daq_running\":" + String(daqRunning ? "true" : "false") + ",";
  json += "\"daq_available\":" + String(daqHead - daqTail) + ",";
  json += "\"daq_dropped\":" + String(daqDropped) + ",";
  json += "\"serial_telemetry\":" + String(serialTelemetry ? "true" : "false") + ",";
  json += "\"ms_since_cmd\":" + String(millis() - lastCommandMs);
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
// JSON compacto de baja latencia para el agente RL (modo 6). Reporta la observación
// en convención SIM calculada por el lazo de control (updateRlObservation). Misma
// convención que alimenta la red on-device (modo 7), así una política servida por
// HTTP ve entradas idénticas. qube_real.py lo lee PASS-THROUGH (sin re-flip de alpha
// ni negación de velocidad). Leer globales cacheados aquí (sin acceso a encoder/I2C
// desde el contexto async) evita además carreras con el lazo de 500 Hz.
String getRlStateJson() {
  String json = "{";
  json += "\"th\":" + String(rl_obs_th, 4) + ",";
  json += "\"al\":" + String(rl_obs_al, 4) + ",";
  json += "\"thd\":" + String(rl_obs_thd, 4) + ",";
  json += "\"ald\":" + String(rl_obs_ald, 4) + ",";
  json += "\"pv\":" + String(RL_PROTO_VERSION);  // protocol version handshake
  json += "}";
  return json;
}

void handleRlState(AsyncWebServerRequest *request) {
  request->send(200, "application/json", getRlStateJson());
}

// Endpoint combinado (proto v3): fija la acción RL Y devuelve el estado compacto en
// UN solo round-trip, en vez de /rl_cmd?a= seguido de /rl_state (2 RTT ≈ 71 ms). Con
// esto el lazo PC-en-el-lazo por WiFi baja a ~1 RTT/paso. Sin 'a', se comporta como
// /rl_state (solo lectura).
void handleRlStep(AsyncWebServerRequest *request) {
  if (request->hasParam("a")) {
    rlAction = constrain(request->getParam("a")->value().toFloat(), -1.0f, 1.0f);
    lastCommandMs = millis();
  }
  request->send(200, "application/json", getRlStateJson());
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
    rl_vf_init = false;  // re-init the sim-convention velocity filter
    rl_obs_th = rl_obs_al = rl_obs_thd = rl_obs_ald = 0.0f;
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
  if (request->hasParam("lqr2n")) { lqr_K2_near = request->getParam("lqr2n")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqr4n")) { lqr_K4_near = request->getParam("lqr4n")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqrnd")) { lqr_near_deg = request->getParam("lqrnd")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqr2vn")) { lqr_K2_very_near = request->getParam("lqr2vn")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqr4vn")) { lqr_K4_very_near = request->getParam("lqr4vn")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqrvnd")) { lqr_very_near_deg = request->getParam("lqrvnd")->value().toFloat(); resetLqr(); }
  if (request->hasParam("lqrdamp")) { lqr_damping_gain = request->getParam("lqrdamp")->value().toFloat(); resetLqr(); }
  // H2/H6: las dos variables de la ventana del catch. NO llaman a resetLqr() — no son
  // ganancias y no hay estado de filtro que invalidar; ademas resetLqr() reinicia el
  // cronometro de supervivencia, que es justo lo que se esta midiendo.
  // `lc=0` desactiva el catch por completo: el LQR corre desde el primer tick.
  if (request->hasParam("lc")) {
    lqr_catchDurMs = (unsigned long)constrain(request->getParam("lc")->value().toInt(), 0, 2000);
  }
  if (request->hasParam("cg")) {
    lqr_centeringGrace = (request->getParam("cg")->value().toInt() != 0);
  }
  // Umbrales del hibrido del modo 7. Existian desde hace tiempo pero SOLO por Serial
  // (`H`/`X`), y abrir el serial reinicia la placa y tira al PC del SoftAP: en la
  // practica eran inalcanzables. Mismo caso que `lc`/`cg`.
  //
  // Para que sirven: el modo 7 corre la politica RL hasta |alpha| >= he y ahi traspasa
  // a la MISMA ley LQR del modo 4. O sea que el balanceo del m7 es el del m4, que hoy
  // sostiene ~0,5 s (P4): medir el m7 tal cual mide el LQR, no la politica.
  //
  // Con `he=179` el traspaso practicamente no dispara y la politica balancea sola. Esa
  // es la unica prueba honesta de una politica de 50 Hz sobre el hardware, porque el
  // modo 7 corre en el chip y no arrastra los 14,3 Hz del enlace HTTP (P20).
  if (request->hasParam("he")) {
    hybrid_enter_deg = constrain(request->getParam("he")->value().toFloat(), 90.0f, 179.0f);
  }
  if (request->hasParam("hx")) {
    hybrid_exit_deg = constrain(request->getParam("hx")->value().toFloat(), 60.0f, 175.0f);
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
  // Tope de la referencia de bombeo. Se limita a 88 deg: el fin de carrera blando
  // esta en SERVO_HARD_LIMIT_DEG (95) y el brazo sigue la referencia con unos pocos
  // grados de sobrepaso, asi que pedir mas la llevaria a auto-matarse a mitad del
  // bombeo — que es exactamente lo que pasa al subir `sp`.
  if (request->hasParam("tn")) {
    swingupCatchDeg = constrain(request->getParam("tn")->value().toFloat(), 120.0f, 178.0f);
  }
  if (request->hasParam("tr")) {
    swingupTransEnable = (uint8_t)constrain(request->getParam("tr")->value().toInt(), 0, 1);
  }
  if (request->hasParam("ec")) {
    swingupEnergyCeiling = constrain(request->getParam("ec")->value().toFloat(), 0.2f, 3.0f);
  }
  if (request->hasParam("pl")) {
    swingupPumpLaw = (uint8_t)constrain(request->getParam("pl")->value().toInt(), 0, 1);
  }
  if (request->hasParam("pg")) {
    swingupEnergyGain = request->getParam("pg")->value().toFloat();
  }
  if (request->hasParam("pn")) {
    swingupPumpSign = (request->getParam("pn")->value().toFloat() < 0.0f) ? -1.0f : 1.0f;
  }
  if (request->hasParam("pc")) {
    swingupCenterGain = constrain(request->getParam("pc")->value().toFloat(), 0.0f, 3.0f);
  }
  if (request->hasParam("pr")) {
    swingupPumpRefMaxDeg = constrain(request->getParam("pr")->value().toFloat(), 30.0f, 88.0f);
  }
  // NOTA: el parametro `bt` (balance_threshold) se elimino en la auditoria de
  // 2026-07-28. Existia desde v1.20 y era configurable, pero ningun lazo lo leia
  // desde que la transicion del modo 5 se reescribio con umbrales fijos: era API
  // publicada que no hacia nada. El umbral real de transicion vive ahora en
  // SWINGUP_TRANS_*_DEG. Si hace falta barrerlo, exponer ESAS constantes.

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
  // Kick anti-friccion del modo 2 (P6). Se barren por HTTP en banco; el umbral de
  // error va hasta 15 y el piso hasta 60 = HOMING_PWM_SEEK, que es lo maximo que
  // tiene sentido pedirle a un arranque en libre.
  if (request->hasParam("se")) {
    stiction_err_thresh_deg = constrain(request->getParam("se")->value().toFloat(), 0.0f, 15.0f);
  }
  if (request->hasParam("sk")) {
    stiction_kick_pwm = constrain(request->getParam("sk")->value().toFloat(), 0.0f, 60.0f);
  }
  if (request->hasParam("tp")) {
    const unsigned long v = request->getParam("tp")->value().toInt();
    if (v >= 50 && v <= 5000) {
      telemetryPeriodMs = v;
    }
  }
  if (request->hasParam("sv")) {
    serialTelemetry = (request->getParam("sv")->value().toInt() != 0);
  }
  // Reset de las metricas de salud del lazo. Se llama al ARRANCAR una captura
  // para que loop_dt_max_us / loop_overruns describan esa corrida y no arrastren
  // el peor caso del arranque (donde el escaneo WiFi bloquea cientos de ms).
  if (request->hasParam("rj")) {
    loopMaxPeriodUs = 0;
    loopOverruns = 0;
    // Los contadores de P21 se reinician junto con los del lazo: se comparan entre si
    // dentro de la MISMA ventana, si no la correlacion no significa nada.
    rl_fwd_us_last = rl_fwd_us_max = 0;
    rl_step_us_last = rl_step_us_max = 0;
    rl_step_us_sum = 0;
    rl_fwd_us_sum = 0;
    rl_infer_count = 0;
  }
  request->send(200, "application/json", getStateJson());
}

void connectStaIfConfigured() {
  if (!ENABLE_STA) {
    // No callar: guardar credenciales por /cmd?wifi_ssid= o por serial sigue
    // funcionando (quedan en NVS), pero en SoftAP puro NO se conecta a nada. Sin
    // este aviso, el comando parece haber funcionado y la placa nunca aparece en
    // la LAN. Para usarlas: pio run -e esp32dev_apsta --target upload
    Serial.println("STA: deshabilitado en compilacion (SoftAP puro, ver esp32dev_apsta)");
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

// Eventos de red WiFi. Solo registran/informan: la reconexión activa la maneja
// setAutoReconnect(true) + el guardián no bloqueante de loop(). Llamar WiFi.begin()
// desde el contexto del evento es propenso a carreras, por eso aquí solo se loguea.
void onWifiEvent(WiFiEvent_t event) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      Serial.println("[WiFi] STA desconectado; el guardian reintentara");
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      // Re-afirmar sin power-save en cada (re)conexión: el stack puede reactivar el
      // modem-sleep al asociarse, devolviendo los picos de latencia de ~100 ms.
      esp_wifi_set_ps(WIFI_PS_NONE);
      Serial.print("[WiFi] STA (re)conectado, IP: ");
      Serial.println(WiFi.localIP());
      break;
    default:
      break;
  }
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
  Serial.println("WiFi: Reiniciar para conectar (envia 'reboot' por serial o pulsa RST)");
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
  Serial.println("Modos: m0(stop) m1(PWM) m2(PID servo) m3(homing) m4(LQR)");
  Serial.println("       m5(swing-up) m6(RL por HTTP) m7(RL on-device)");
  Serial.println("Servo: s<deg>, kp<val>, ki<val>, kd<val>, o<deg>, z, ed<1|-1>, cpr<val>");
  Serial.println("Pendulo: op<deg>, zp, edp<1|-1>, cprp<val>");
  Serial.println("LQR: lqr1<val>..lqr4<val>");
  Serial.println("     L<n> <val>: 1=K2near 2=K4near 3=damping 4=K2vnear 5=K4vnear");
  Serial.println("                 6=K2 7=K4 8=catch_ms 9=catch_gain 10=catch_pwm");
  Serial.println("                 11=catch_angle 12=signo velocidad swing-up (+1|-1)");
  Serial.println("Hibrido m7: b<deg>(entrar LQR) j<deg>(salir) y<pwm>(clamp) q<0..1>(escala par)");
  Serial.println("GainSched: g1(on) g0(off) gf<val> gi<val> gd<val> (fino) GC<val> GI<val> GD<val> (grueso)");
  Serial.println("Motor: p-255..255 (modo 1), x(stop), r(reset)");
  Serial.println("Info: ?(estado), i(IP), n(ina scan), h(esta ayuda)");
  Serial.println("WiFi: wifi_ssid<TuRed>, wifi_pass<TuClave>, wifi_info");
  Serial.println("Sistema: reboot (reinicia el ESP32)");
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
  // Reinicio por serial (palabra completa: no cabe en el switch por primer
  // carácter porque 'r' ya es reset de encoders). Gemelo serial de /restart.
  if (cmd == "reboot") {
    Serial.println("[REBOOT] Reiniciando...");
    Serial.flush();
    delay(100);
    ESP.restart();
  }
  const char c = cmd.charAt(0);
  switch (c) {
    case 'm':
      {
        const int m = cmd.substring(1).toInt();
        // Modes 0..7. Mode 3 was the pendulum PID (removed in v1.34) and now
        // holds the homing routine — sending m3 moves the arm to both stops.
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

    case 'q':
      {
        // q<val> — mode-7 on-device RL torque scale (0..1). Serial twin of the
        // HTTP /rl_cmd?scale path, so the whole mode-7 test can run WiFi-free.
        rl_pwm_scale = constrain(cmd.substring(1).toFloat(), 0.0f, 1.0f);
        lastCommandMs = millis();
        break;
      }

    case 'b':  // b<deg> — mode-7 hybrid LQR ENTER threshold (|alpha| deg from hanging)
      {
        hybrid_enter_deg = constrain(cmd.substring(1).toFloat(), 90.0f, 179.0f);
        Serial.printf("[HYBRID] enter=%.1fdeg\n", hybrid_enter_deg);
        lastCommandMs = millis();
        break;
      }
    case 'j':  // j<deg> — mode-7 hybrid LQR EXIT threshold
      {
        hybrid_exit_deg = constrain(cmd.substring(1).toFloat(), 60.0f, 175.0f);
        Serial.printf("[HYBRID] exit=%.1fdeg\n", hybrid_exit_deg);
        lastCommandMs = millis();
        break;
      }
    case 'y':  // y<pwm> — mode-7 hybrid LQR PWM clamp
      {
        hybrid_lqr_pwm = constrain(cmd.substring(1).toInt(), 30, PWM_MAX);
        Serial.printf("[HYBRID] lqr_pwm=%d\n", hybrid_lqr_pwm);
        lastCommandMs = millis();
        break;
      }
    case 'L':  // L<n> <val> — tune LQR catch gains live (shared mode4/mode7):
      {        // 1=K2_near 2=K4_near 3=damping 4=K2_very_near 5=K4_very_near 6=K2 7=K4
        const int sp = cmd.indexOf(' ');
        if (sp > 1) {
          const int n = cmd.substring(1, sp).toInt();
          const float val = cmd.substring(sp + 1).toFloat();
          switch (n) {
            case 1: lqr_K2_near = val; break;
            case 2: lqr_K4_near = val; break;
            case 3: lqr_damping_gain = val; break;
            case 4: lqr_K2_very_near = val; break;
            case 5: lqr_K4_very_near = val; break;
            case 6: lqr_K2 = val; break;
            case 7: lqr_K4 = val; break;
            case 8: hybrid_catch_ms = val; break;
            case 9: hybrid_catch_gain = val; break;
            case 10: hybrid_catch_pwm = (int)val; break;
            case 11: hybrid_catch_angle = val; break;
            // L12 <+1|-1> — signo de la velocidad del pendulo en el swing-up.
            // Si el bombeo del modo 5 frena en vez de excitar, invertir aca.
            case 12: swing_vel_sign = (val >= 0.0f) ? 1.0f : -1.0f; break;
            default: break;
          }
          Serial.printf("[LQR] g%d=%.3f\n", n, val);
        }
        lastCommandMs = millis();
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

static unsigned long lastRlBroadcastMs = 0;
void broadcastTelemetry() {
  if (ws.count() == 0) return;
  // Durante RL por HTTP (modo 6) el tráfico /rl_step es latencia-crítico y comparte la
  // única radio del ESP32; un broadcast de /state cada telemetryPeriodMs le roba tiempo
  // de aire. Se decima a RL_MODE_TELEMETRY_MS en vez de omitirlo: el modo 6 es
  // justamente donde el operador necesita ver el watchdog de comandos (auto-STOP a los
  // 10 s) y el ángulo del péndulo. Omitirlo dejaba la GUI congelada sin aviso, y como
  // el campo "mode" viaja en esta misma telemetría, tampoco podía saber por qué.
  // (El modo 7 corre on-device y no usa HTTP para el control, así que va a full rate.)
  if (mode == 6) {
    const unsigned long nowMs = millis();
    if (nowMs - lastRlBroadcastMs < RL_MODE_TELEMETRY_MS) return;
    lastRlBroadcastMs = nowMs;
  }
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
    // GPIO25 sin conexión física en el hardware L298N actual (jumper ENA puesto).
    // Se deja en HIGH por herencia del wiring BTS7960 (R_EN/L_EN); no-op eléctrico.
    pinMode(PIN_ENA, OUTPUT);
    digitalWrite(PIN_ENA, HIGH);
  }

  setMotor(0);

  // Encoder servo: PCNT en hardware (X4 cuadratura)
  initPcntUnit(pcnt_servo_unit, PIN_ENC_A, PIN_ENC_B);

  // Encoder péndulo: PCNT en hardware (X4 cuadratura)
  initPcntUnit(pcnt_pendulum_unit, PIN_PEND_A, PIN_PEND_B);
  // Los pull-ups INTERNOS de GPIO32/33 quedaron obsoletos con la placa de la v1.51: el
  // péndulo ya no va directo al GPIO, llega acondicionado desde U2 (CD40106, salida
  // push-pull) y el pull-up de 2,2 kΩ a 3V3 vive en la línea open-drain del encoder,
  // antes del Schmitt. El pull-up interno (~30-80 kΩ) queda del lado del GPIO, después
  // del RC serie de 10 kΩ, formando un divisor: con el Schmitt en bajo el pin no llega
  // a 0 V sino a 3,3·10k/(10k+Rpu) ≈ 0,6 V típico y ~0,83 V en el peor caso, contra un
  // V_IL de 0,825 V. Se desactiva: el nivel lo fija el driver push-pull de U2.
  gpio_pullup_dis((gpio_num_t)PIN_PEND_A);
  gpio_pullup_dis((gpio_num_t)PIN_PEND_B);
  gpio_pulldown_dis((gpio_num_t)PIN_PEND_A);
  gpio_pulldown_dis((gpio_num_t)PIN_PEND_B);

  // NOTA: la inicialización I2C (INA219) se movió a DESPUÉS de server.begin() —
  // ver más abajo. Un bus I2C trabado colgaba setup() ANTES de arrancar WiFi/servidor
  // y mataba toda la comunicación; arrancando el servidor primero, un fallo del sensor
  // ya no puede tumbar el HTTP (el AsyncWebServer corre en su propia task).

  // Initialize SPIFFS for web GUI
  if (!SPIFFS.begin(true)) {
    Serial.println("[SPIFFS] Error al montar");
  } else {
    Serial.println("[SPIFFS] OK");
  }


  // Load WiFi credentials from NVS
  loadWifiCredentials();

  WiFi.mode(ENABLE_STA ? WIFI_AP_STA : WIFI_AP);
  WiFi.onEvent(onWifiEvent);
  // Coexistencia AP+STA: el ESP32 tiene UNA sola radio, por lo que el SoftAP
  // debe operar en el MISMO canal que el router STA. Si se fuerza un canal
  // distinto al del router, el STA no logra autenticar (Reason 2 AUTH_EXPIRE).
  // Detectamos el canal del SSID objetivo por escaneo; fallback a AP_CHANNEL.
  // En SoftAP puro no hay router al que seguir: se usa AP_CHANNEL y se evita el
  // escaneo, que es BLOQUEANTE y es el peor caso que domina loop_dt_max_us al
  // arrancar si no se resetean las métricas con /cmd?rj=1 (ver docs/http_api.md).
  uint8_t apChannel = AP_CHANNEL;
  if (ENABLE_STA && staSsid[0] != '\0') {
    int n = WiFi.scanNetworks();
    for (int i = 0; i < n; i++) {
      if (WiFi.SSID(i) == staSsid) { apChannel = WiFi.channel(i); break; }
    }
    WiFi.scanDelete();
  }
  WiFi.softAP(AP_SSID, AP_PASS, apChannel, false, 4);  // canal = STA, SSID visible, max 4
  // Beacon del AP. Rango válido 100–60000 ms.
  //  · AP+STA (radio única): el beacon cada ~100 ms competía con el tráfico STA y era
  //    la causa medida de los picos de ~100 ms; subirlo a 300 ms le da más tiempo de
  //    aire contiguo al STA sin apagar el AP.
  //  · SoftAP puro: NO hay tráfico STA con el que competir, y un beacon largo pasa a
  //    ser contraproducente — el AP retiene las tramas de una estación en power-save
  //    hasta el DTIM siguiente, así que alargar el beacon alarga esa retención. Con el
  //    PC como estación (y su adaptador, no el ESP32, siendo quien puede dormir) se
  //    vuelve a 100 ms. Ver docs/research/softap_app_escritorio.md §3.2.
  {
    wifi_config_t apcfg;
    if (esp_wifi_get_config(WIFI_IF_AP, &apcfg) == ESP_OK) {
      apcfg.ap.beacon_interval = ENABLE_STA ? 300 : 100;
      esp_wifi_set_config(WIFI_IF_AP, &apcfg);
    }
  }
  connectStaIfConfigured();
  // Estabilidad WiFi: desactivar el modem-sleep (activo por defecto) que introduce
  // picos de latencia de ~100 ms y pérdida de paquetes en tráfico latencia-crítico
  // como el lazo RL por HTTP; y habilitar la reconexión STA a nivel de stack.
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  // Forzar explícitamente WIFI_PS_NONE a nivel de driver: WiFi.setSleep(false) no
  // siempre desactiva el modem-sleep en modo AP+STA, dejando picos periódicos de
  // ~100 ms (medidos). esp_wifi_set_ps lo garantiza; se re-afirma en cada GOT_IP.
  esp_wifi_set_ps(WIFI_PS_NONE);

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
  server.on("/rl_step", HTTP_GET, handleRlStep);
  server.on("/rl_state", HTTP_OPTIONS, handleOptions);
  server.on("/rl_cmd", HTTP_OPTIONS, handleOptions);
  server.on("/rl_step", HTTP_OPTIONS, handleOptions);
  // ORDEN CRITICO: la ruta especifica va PRIMERO. ESPAsyncWebServer acepta subrutas
  // (WebHandlerImpl.h:121 -> `url.startsWith(_uri + "/")`), asi que un "/daq"
  // registrado antes tambien captura "/daq/read" y devuelve el JSON de estado en vez
  // del bloque binario. Medido en banco el 2026-08-03: el cliente recibia
  // magic=0x7670227b, que son los bytes ASCII de {"pv. Si se reordena esto, la
  // adquisicion por bloques deja de funcionar entera.
  server.on("/daq/read", HTTP_GET, handleDaqRead);
  server.on("/daq", HTTP_GET, handleDaq);
  server.on("/daq/read", HTTP_OPTIONS, handleOptions);
  server.on("/daq", HTTP_OPTIONS, handleOptions);
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

  // ── Init I2C (INA219) DESPUÉS del servidor ────────────────────────────────
  // Con WiFi + web server ya corriendo, un bus I2C trabado no puede matar la
  // comunicación. Aun así lo hacemos robusto: recuperar el bus (soltar SDA) antes de
  // Wire.begin y acotar cada transacción con setTimeOut para que un INA219 marginal
  // (que a veces sostiene SDA en bajo) no cuelgue scanI2CBus()/initIna219().
  i2cBusRecover(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.begin(PIN_I2C_SDA, PIN_I2C_SCL);
  Wire.setTimeOut(50);
  delay(50);
  scanI2CBus();
  inaOk = initIna219();

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

  // P21: los pesos de la politica pasan de flash a RAM antes del primer tick del
  // modo 7. Ver rl_weights_to_ram(): leerlos desde .rodata costaba hasta 15,5 ms por
  // inferencia contra los 2 ms de periodo del lazo.
  rl_weights_to_ram();

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

// ── Mantenimiento por tick: failsafe de comandos + telemetria + INA219 ───────
// CRITICO que esto corra ANTES del despacho de modos, no despues.
//
// Vivia al final de loop(), pero las ramas de modo tienen ~10 `return;` (freno de
// seguridad, brownout, zero-order-hold del modo 7, catch del hibrido…) y todos
// salen de loop() sin llegar al final. El caso peor era el corte por tension:
//   pwm=0; setMotor(0); return;  ->  nunca se llamaba updateIna219()
// y como busVoltageV quedaba congelada por debajo del umbral, la condicion no se
// podia volver a evaluar: motor cortado y telemetria muerta hasta cambiar de modo
// o rebootear. Corriendo primero, cada tick refresca el INA219 y evalua el
// watchdog de comandos sin importar por donde salga la rama de modo (F2, F3).
//
// Efecto lateral deseado: si el failsafe dispara safeStop() (mode=0), el despacho
// de este mismo tick ya ve mode 0 y no aplica par — antes tardaba un tick mas.
void serviceFailsafeAndTelemetry() {
  const unsigned long nowMs = millis();

  // Failsafe: si no hay comandos recientes en modos activos, detener.
  // Only guard the command-driven modes (1 manual PWM, 6 RL-over-HTTP); autonomous
  // modes must keep running without external commands (see ENABLE_COMMAND_TIMEOUT).
  if (ENABLE_COMMAND_TIMEOUT && (mode == 1 || mode == 6)) {
    const unsigned long cmdLimitMs = (mode == 1) ? MANUAL_COMMAND_TIMEOUT_MS : COMMAND_TIMEOUT_MS;
    if (nowMs - lastCommandMs > cmdLimitMs) {
      safeStop();
    }
  }

  if (nowMs - lastTelemetryMs < telemetryPeriodMs) return;
  lastTelemetryMs = nowMs;

  const long c = getEncoderCountAtomic();
  const float pos = encoderDir * c * getDegPerCount() - positionOffsetDeg;
  const long pc = getPendulumCountAtomic();
  const float pendPos = pendulumDir * pc * getPendulumDegPerCount() - pendulumOffsetDeg;

  updateIna219();

  if (!serialTelemetry) {
    broadcastTelemetry();
    return;
  }

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
  Serial.print(" DTMAX:");
  Serial.print(loopMaxPeriodUs);
  Serial.println();
  // Broadcast via WebSocket to connected clients
  broadcastTelemetry();
}

void loop() {
  ArduinoOTA.handle();
  ws.cleanupClients();
  yield();  // Alimentar watchdog timer para evitar crash por loop largo

  // Guardián STA no bloqueante: si el router nos soltó, reintentar cada
  // STA_RECONNECT_PERIOD_MS. connectStaIfConfigured() es no bloqueante (solo
  // config + begin), así que no frena el lazo de control de 500 Hz.
  if (ENABLE_STA && staSsid[0] != '\0' && WiFi.status() != WL_CONNECTED) {
    const unsigned long nowWifiMs = millis();
    if (nowWifiMs - lastStaReconnectMs >= STA_RECONNECT_PERIOD_MS) {
      lastStaReconnectMs = nowWifiMs;
      connectStaIfConfigured();
    }
  }

  if (Serial.available()) {
    processSerialCommand();
  }

  // Failsafe + telemetria + INA219 ANTES del despacho: las ramas de modo salen
  // con `return` y se lo saltaban (ver comentario de la funcion).
  serviceFailsafeAndTelemetry();

  const unsigned long nowUs = micros();
  if ((nowUs - lastControlUs) >= CONTROL_PERIOD_US) {
    // ── Instrumentacion del lazo ────────────────────────────────────────────
    // El periodo REAL entre ticks, no el nominal. Un bloqueo largo (escaneo WiFi,
    // SPIFFS, una linea serie sin terminador, una transaccion I2C lenta) se ve
    // aca y en ningun otro lado: los "500 Hz" del proyecto eran una constante del
    // codigo sin una sola medicion detras (F9).
    const unsigned long periodUs = nowUs - lastControlUs + CONTROL_PERIOD_US;
    if (periodUs > loopMaxPeriodUs) loopMaxPeriodUs = periodUs;

    // Recuperacion de atraso: `lastControlUs += CONTROL_PERIOD_US` solo avanza un
    // periodo por vuelta, asi que tras un bloqueo el acumulador queda atras y el
    // lazo dispara ticks consecutivos separados por microsegundos mientras asume
    // dt = 2 ms. Las derivadas y el integral se corrompen justo despues de cada
    // hipo. Si el atraso supera LOOP_RESYNC_PERIODS se re-sincroniza y se cuenta
    // el evento en vez de intentar "recuperar" ticks que ya no sirven.
    if ((nowUs - lastControlUs) > LOOP_RESYNC_PERIODS * CONTROL_PERIOD_US) {
      lastControlUs = nowUs;
      loopOverruns++;
    } else {
      lastControlUs += CONTROL_PERIOD_US;
    }

    const float pos = getPositionDeg();
    lastServoPos = pos;  // Para soft saturation en setMotor()
    const float pendPosRaw = getPendulumPositionDeg();  // Sin wrap (para velocidad)
    const float pendPos = fmodf(pendPosRaw + 180.0f, 360.0f) - 180.0f;  // Wrap a [-180, 180]
    const float dt = CONTROL_PERIOD_US / 1000000.0f;

    // ── Fin de carrera duro, comun a todos los modos ──────────────────────────
    // Corre ANTES del despacho de modo: safeStop() pone mode=0, con lo que ninguno
    // de los if (mode == N) de abajo se ejecuta en este tick y no se aplica par.
    // El modo 3 (homing) queda exento: corre con el cero invalido — asi que
    // este `pos` no significa nada — y por definicion necesita llegar a los
    // topes. Sin la exencion se auto-mata en el primer tick y el brazo queda
    // trabado sin forma de recuperarse por software.
    if (mode != 0 && mode != 3 && fabsf(pos) > SERVO_HARD_LIMIT_DEG) {
      safeStop();
    }

    // ── DAQ: capturar la muestra de ESTE tick ────────────────────────────────
    // Va aquí, con el lazo ya sincronizado y los ángulos recién leídos, para que
    // t_us corresponda al instante del muestreo y no al de la transmisión. Con la
    // adquisición detenida (por defecto) es un único `if` sobre un bool.
    daqPush(nowUs, pos, pendPosRaw);

    // ══════════════════════════════════════════════════════════════════════════
    // MODO 2: PID Posición Servo
    // ══════════════════════════════════════════════════════════════════════════
    if (mode == 2) {
      const float err = setpoint_deg - pos;
      const float absErr = fabsf(err);

      // ── Gain Scheduling: elegir gains según magnitud del error ──────────
      // kp_eff/ki_eff/kd_eff: antes se llamaban Kp/Ki/Kd y TAPABAN a las globales
      // homonimas, lo que obligaba al `::Kp` de mas abajo para recuperarlas (F15).
      float kp_eff, ki_eff, kd_eff;
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
          kp_eff = Kp_fine;   ki_eff = Ki_fine;   kd_eff = Kd_fine;
        } else {
          kp_eff = Kp_coarse; ki_eff = Ki_coarse; kd_eff = Kd_coarse;
        }
      } else {
        // PID clásico: usa los gains globales Kp/Ki/Kd
        kp_eff = Kp;  ki_eff = Ki;  kd_eff = Kd;
      }

      // ── Integral anti-windup ────────────────────────────────────────────
      if (absErr < PID_ANTIWIND_ERR_DEG && fabsf(filteredVel) < PID_ANTIWIND_VEL_DPS) {
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
      float u = kp_eff * err + ki_eff * integralTerm + kd_eff * filteredVel;
      int pwm = (int)(MOTOR_DIR * u);

      // ── Feedforward gravitacional: compensa torque proporcional a sin(pos) ──
      // Modelo: τ_gravedad ∝ sin(ángulo). Compensa la soft saturation que
      // reduce PWM a medida que el brazo se aleja del centro.
      // ff=15 → ~7.5 PWM a 30°, ~13 PWM a 60°, ~15 PWM a 90°.
      // Calibrar: subir ff hasta que el SS error se minimice.
      //
      // Va ANTES de la zona muerta a proposito. Al reves —como estaba hasta
      // 2026-07-31— el `pwm = 0` de la zona muerta quedaba pisado por el termino
      // de feedforward que se sumaba justo despues, o sea que dentro de la zona
      // muerta el motor seguia recibiendo PWM. Era inocuo solo porque
      // `servo_ff_pwm` vale 0 por defecto: con `ff` en uso, la zona muerta no
      // existia.
      const float ff = servo_ff_pwm * sinf(pos * DEG_TO_RAD);
      pwm += (int)(MOTOR_DIR * ff);

      // ── Dead band ──────────────────────────────────────────────────────
      const float deadBand = useGainScheduling ? (gainMode == 0 ? DEADBAND_FINE_DEG : DEADBAND_COARSE_DEG) : DEADBAND_CLASSIC_DEG;
      if (absErr <= deadBand) {
        pwm = 0;
      }
      // ── Kick mínimo para vencer fricción ───────────────────────────────
      const int kick = (int)stiction_kick_pwm;
      if (abs(pwm) < kick && absErr > stiction_err_thresh_deg && fabsf(filteredVel) < STICTION_VEL_THRESH_DPS) {
        pwm = (pwm >= 0) ? kick : -kick;
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
    } else if (mode == 3) {
    // ══════════════════════════════════════════════════════════════════════════
    // MODO 3: Homing por topes mecanicos — recupera el cero del encoder
    // incremental del brazo. Termina solo (setMode(0)); el resultado se lee por
    // /state en homing_phase / homing_ok / homing_range / homing_center.
    // ══════════════════════════════════════════════════════════════════════════
      runHoming(getRawPositionDeg(), pendPosRaw);
    } else if (mode == 4) {
      // ── Catch mode: frenar péndulo al entrar a LQR ────────────────────
      // Direction-locked proportional braking: locks brake direction on entry
      // to prevent overshoot when pendulum crosses zero velocity.
      int pwm = 0;
      if (lqr_catchMs > 0 && (millis() - lqr_catchMs) < lqr_catchDurMs) {
        // H1 (2026-08-03): esta rama termina en `return`, asi que se saltaba el
        // `lqr_prevAlpha = alpha_raw` de mas abajo. Durante los 400 ms del catch la
        // referencia quedaba CONGELADA en el valor de entrada, y esto no era una
        // velocidad sino el desplazamiento ACUMULADO dividido por un tick de 2 ms:
        // 30 deg acumulados daban 15.000 deg/s y el freno saturaba contra
        // LQR_CATCH_PWM casi de inmediato. Peor, la direccion se fijaba en los
        // primeros 10 ms desde esa misma lectura, que con una entrega buena
        // (vel ~ 0) es ruido de una cuenta de encoder: 400 ms de empuje constante
        // de +-25 PWM en un sentido esencialmente aleatorio.
        const float rawVelForCatch = -(pendPosRaw - lqr_prevAlpha) / dt;
        lqr_prevAlpha = pendPosRaw;  // la derivada vuelve a ser por tick
        // Sentido de frenado fijado en la entrada (global, la limpia setMode).
        if ((millis() - lqr_catchMs) < 10) {  // First ~10ms: lock direction
          lqr_lockedBrakeDir = (rawVelForCatch > 0) ? 1.0f : -1.0f;
        }
        // Proportional braking with locked direction: ±25 PWM max, gain suave
        float brake_pwm = lqr_lockedBrakeDir * fabsf(rawVelForCatch) * LQR_CATCH_GAIN;
        pwm = constrain((int)brake_pwm, -LQR_CATCH_PWM, LQR_CATCH_PWM);
        setMotor(pwm);
        return;
      }
      // Fin del catch. Se registra el instante UNA sola vez: `lqr_catchMs` se pisa a
      // cero aca mismo y por eso no puede seguir usandose como referencia temporal
      // mas abajo (H6). El guardia por `== 0` cubre tambien la entrada manual (`m=4`
      // sin swing-up previo), donde el catch nunca corre; resetLqr() lo invalida al
      // entrar al modo, asi que aca siempre vale 0 en el primer tick.
      if (lqr_catchEndMs == 0) lqr_catchEndMs = millis();
      lqr_catchMs = 0;
      // Cronometro de supervivencia. Se actualiza cada tick mientras el LQR corra: al
      // salir del modo 4 deja de actualizarse y el ultimo valor ES lo que aguanto, sin
      // necesidad de cerrarlo desde setMode(). Cuenta desde el FIN del catch, no desde
      // la entrada al modo: durante el catch el LQR no corre (H2), y contarlo le
      // regalaria esos ms por igual a todas las condiciones del A/B.
      lqr_aliveMs = millis() - lqr_catchEndMs;
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
      if (fabsf(alpha) < lqr_very_near_deg) {
        k2_eff = lqr_K2_very_near;
        k4_eff = lqr_K4_very_near;
      } else if (fabsf(alpha) < lqr_near_deg) {
        k2_eff = lqr_K2_near;
        k4_eff = lqr_K4_near;
      }
      // Usar velocidades: KF si habilitado, EMA como fallback
      float velTheta_ctrl = kf_enabled ? kf_x[2] : lqr_filteredVelTheta;
      float velAlpha_ctrl = kf_enabled ? kf_x[3] : lqr_filteredVelAlpha;
      // Velocity-dependent gain scaling: boost damping for high-velocity entries
      // H4 (2026-08-03): aca sobraba un `* RAD_TO_DEG`. velAlpha_ctrl YA esta en
      // deg/s — sale de lqr_filteredVelAlpha, que deriva pendPosRaw (grados), o de
      // kf_x[3], que kalmanUpdate alimenta tambien con grados. Multiplicar por 57,3
      // hacia que el umbral de 200 se cruzara con 3,5 deg/s reales y que vel_scale
      // topara en 2,0 con 8,7 deg/s: k4_eff era el DOBLE del declarado casi siempre.
      // No era gain scheduling, era una constante escondida. El gemelo del modo 7
      // (`:3828`) ya lo hacia bien y su comentario lo dice: "velAlpha_ctrl is deg/s".
      // OJO: al corregirlo, el k4 efectivo se reduce a la mitad. Cualquier sintonia
      // previa de lqr_K4 hay que rehacerla (se puede A/B por HTTP con `lqr4=`).
      float vel_alpha_dps = fabsf(velAlpha_ctrl);
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
      if (fabsf(alpha) < lqr_near_deg) {
        u -= lqr_damping_gain * velAlpha_ctrl;
      }

      pwm = constrain((int)(MOTOR_DIR * u), -LQR_PWM_MAX, LQR_PWM_MAX);

      // Servo centering en LQR: mantener el servo cerca del centro para
      // maximizar el rango de actuación y reducir oscilación del servo.
      // Centering agresivo: si el servo se aleja del centro, la fuerza de
      // retorno crece linealmente. Esto previene que el servo pegue contra
      // el stop mecánico y cause brownout.
      {
        // Centering: solo activo 2+ segundos después del catch.
        // Durante los primeros 2s, el LQR necesita control total del servo
        // para estabilizar el péndulo sin interferencia del centering.
        // H6 (2026-08-04): esto leia `lqr_catchMs`, que ya se habia puesto a cero al
        // salir del catch, unas lineas mas arriba. `millis() - 0` es el uptime de la
        // placa, siempre >> 2 s, asi que `ramp` valia 1 desde el PRIMER tick y el
        // periodo de gracia que describe el comentario de aca arriba NUNCA existio: el
        // centering entraba a ganancia plena justo cuando el swing-up entrega con el
        // brazo lejos del centro, con hasta +-25 PWM sobre un LQR_PWM_MAX de 70.
        // `?cg=` elige entre el comportamiento historico (false, el default, para que
        // flashear no cambie nada) y el documentado (true), para medir la diferencia
        // en vez de suponerla.
        float centering_sec = lqr_centeringGrace
                                ? (millis() - lqr_catchEndMs) / 1000.0f
                                : 1.0e6f;  // historico: sin gracia, rampa llena ya
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
      if (fabsf(pendPosRaw) > LQR_PROTECT_RAW_DEG) {
        pwm = 0;
      }

      // Fallback: si raw>360°, el péndulo hizo una vuelta → LQR falló.
      // Se ACOTA la lectura (resta de vueltas enteras); antes se ponia el cero aqui
      // mismo, con lo que el swing-up arrancaba con una referencia falsa (P13).
      if (fabsf(pendPosRaw) > LQR_FALLBACK_RAW_DEG) {
        if (!lqr_inFallback) {
          wrapPendulumTurns();
          setMode(5);
          lqr_inFallback = true;
          Serial.printf("LQR: FALLBACK (raw=%.1f, offset reset)\n", pendPosRaw);
        }
      } else if (fabsf(pendPosRaw) < LQR_REARM_RAW_DEG) {
        // Rearm: péndulo cerca del fondo, listo para nuevo intento
        lqr_inFallback = false;
      }

      // ── Escalera de fin de carrera del modo 4 (ver tabla SERVO_*_DEG) ──────
      // El respaldo comun corta a SERVO_HARD_LIMIT_DEG (95) ANTES de llegar aca,
      // asi que estas ramas solo viven por debajo de ese valor. Habia una tercera
      // rama a 100 deg que por esa misma razon era inalcanzable: se elimino.
      if (fabsf(pos) > SERVO_BLOCK_DEG) {
        // Direction-aware: solo cortar PWM que empuja contra el stop.
        // PWM que va AL centro se permite SIN reducción.
        float stop_dir = (pos > 0) ? 1.0f : -1.0f;
        float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
        if (pwm_dir == stop_dir) {
          pwm = 0;  // Empuja contra stop → cortar
        }
        // Si va al centro → permitir sin restricción (para recuperar)
      } else if (fabsf(pos) > SERVO_TAPER_DEG) {
        // Cortar solo el PWM que empuja hacia el stop (direction-aware)
        float stop_dir = (pos > 0) ? 1.0f : -1.0f;
        float pwm_dir = (pwm > 0) ? 1.0f : ((pwm < 0) ? -1.0f : 0.0f);
        if (pwm_dir == stop_dir) {
          float factor = 1.0f - (fabsf(pos) - SERVO_TAPER_DEG) / (SERVO_BLOCK_DEG - SERVO_TAPER_DEG);
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
      // ── Fin de carrera del modo 5: freno activo hacia el centro ────────────
      {
        if (fabsf(pos) > SERVO_BRAKE_DEG) {
          float brake_dir = (pos > 0) ? -1.0f : 1.0f;
          setMotor((int)(brake_dir * SERVO_BRAKE_PWM));
          return;
        }
      }

      // ── Velocidad angular del péndulo ─────────────────────────────────────
      // Se tickea el filtro de convención sim a 50 Hz (sus coeficientes asumen
      // dt=0.02; tickearlo a los 500 Hz del lazo distorsiona la velocidad) y se
      // lee rl_vf_alVel, en rad/s. Es el MISMO estimador que usan los modos 6 y 7.
      //
      // Hasta 2026-07-28 aca habia un EMA propio (swing_filteredVelAlpha) que
      // nunca se calculaba: alpha_dot valia 0 en todo momento, con lo que el
      // bombeo resonante de mas abajo era inalcanzable, el freno anti-spin no
      // distinguia el sentido del giro y el damping no hacia nada (auditoria F1).
      if (rl_lastTickUs6 == 0 || (nowUs - rl_lastTickUs6) >= 20000UL) {
        rl_lastTickUs6 = nowUs;
        updateRlObservation(pos, pendPosRaw);
      }
      const float alpha_dot = swing_vel_sign * rl_vf_alVel;  // rad/s

      // ── Detección de spinning ──────────────────────────────────────────
      // Si el péndulo acumula >360° en crudo entre samples, está girando.
      float rawDelta = fabsf(pendPosRaw - pendPosRawPrev);
      bool spinning = (rawDelta > 200.0f);  // >200° entre samples = spinning rápido
      pendPosRawPrev = pendPosRaw;

      // Contador de vueltas: si |pendPosRaw| > 360° (1 vuelta), forzar frenado
      if (fabsf(pendPosRaw) > LQR_FALLBACK_RAW_DEG) spinning = true;

      // ── Corte por vueltas acumuladas ──────────────────────────────────
      // Respaldo del techo de energia. El anti-spin de mas abajo frena el BRAZO, que
      // no le saca energia a un pendulo que ya gira, asi que por si solo no puede
      // terminar un embalamiento: hace falta un corte que apague el modo.
      if ((pend_wrapCount - swing_wrapsAtStart) >= SWINGUP_MAX_TURNS) {
        Serial.printf("Swing-up: ABORT por %d vueltas acumuladas\n", pend_wrapCount - swing_wrapsAtStart);
        setMode(0);
        setMotor(0);
        return;
      }

      // Cooldown post-spin: aplicar freno durante SPIN_COOLDOWN_MS después de detectar spinning
      bool inCooldown = (spinCooldownMs > 0) && ((millis() - spinCooldownMs) < SPIN_COOLDOWN_MS);

      if (spinning || inCooldown) {
        // ── Anti-spin: freno máximo + reset offset ──────────────────────
        if (spinning) {
          // Acotar INMEDIATAMENTE para que pendPos vuelva a [-180,180] sin perder
          // la referencia fisica (P13: antes esto ponia el cero donde estuviera).
          wrapPendulumTurns();
          spinCooldownMs = millis();  // Iniciar cooldown
          Serial.printf("Swing-up: SPIN detected, raw=%.1f, braking + cooldown\n", pendPosRaw);
        }

        // Freno máximo, OPUESTO al sentido de giro. Con alpha_dot identicamente
        // cero (F1) esto colapsaba a +PWM_MAX fijo: el "freno" empujaba siempre
        // en el mismo sentido y en la mitad de los casos aceleraba el spin.
        pwm = (alpha_dot > 0.0f) ? -SWINGUP_SPIN_BRAKE_PWM : SWINGUP_SPIN_BRAKE_PWM;
      } else {
        // ══════════════════════════════════════════════════════════════════
        // TRANSICION A LQR: solo cuando el péndulo está cerca de la vertical.
        // Transicion a LQR cuando el pendulo esta dentro de ±60° de vertical.
        // Vertical = |pendPos| ≈ 180°. ±60° = |pendPos| > 120°.
        // ══════════════════════════════════════════════════════════════════
        float vel_raw_dps = fabsf(alpha_dot) * RAD_TO_DEG;
        // P14 (2026-08-03): las cuatro compuertas comparaban fabsf(pendPos) contra
        // sus umbrales SIN acotar. Si el pendulo acumula vuelta, pendPos se va fuera
        // de [-180,180] y |pendPos| supera cualquier umbral hasta 178 con el pendulo
        // lejos de la vertical. Medido en banco: un traspaso con pendPos = -223.42
        // (angulo real 136.6, a 43 de la vertical, E/E* = 0.86) que no debio ocurrir.
        // wrapPendulumTurns() acota, pero solo se llama en spin/recovery: entre medio
        // pendPos puede pasarse. Se acota aqui, para la evaluacion, sin tocar el
        // estado: el offset lo sigue manejando wrapPendulumTurns (P13).
        float pendPosWrapped = fmodf(pendPos + 180.0f, 360.0f);
        if (pendPosWrapped < 0.0f) pendPosWrapped += 360.0f;
        pendPosWrapped -= 180.0f;
        bool nearVertical = fabsf(pendPosWrapped) > swingupCatchDeg;
        bool verySlow = vel_raw_dps < SWINGUP_TRANSITION_VEL_DPS;
        bool canTransition = nearVertical && verySlow;

        // Peak detection: detect position peak (alpha_dot crosses zero)
        bool atPeak = (prev_alpha_dot_peak > 0.0f && alpha_dot <= 0.0f) ||
                       (prev_alpha_dot_peak < 0.0f && alpha_dot >= 0.0f);
        prev_alpha_dot_peak = alpha_dot;

        // At position peak AND near vertical
        bool atPeakTransition = atPeak && (180.0f - fabsf(pendPosWrapped) < (180.0f - swingupCatchDeg));

        // FORCED transition.
        //
        // P1 (2026-07-30): hasta v1.55.1 esto era SOLO `|pendPos| > 125`, sin
        // compuerta de velocidad ni de energia. Como su umbral (125) esta apenas
        // sobre el de cercania (120), se cruzaba antes de que las tres condiciones
        // CON compuerta llegaran a cumplirse — o sea que las anulaba. Medido: en 7
        // de 7 traspasos gano `forced`, entregando al LQR un pendulo a ~55 deg de
        // la vertical, girando a 500-870 deg/s y con solo 75-87% de la energia.
        //
        // La compuerta es de velocidad y no de energia a proposito: `E/E*` depende
        // de PEND_INERTIA/MASS/LENGTH, cuya escala esta en duda (P5). La velocidad
        // sale del mismo estimador que usan los modos 6 y 7, asi que aunque su
        // escala tambien se revise, el umbral se puede recalibrar con una sola
        // medicion en vez de arrastrar tres constantes sin verificar.
        bool forcedTransition = fabsf(pendPosWrapped) > fminf(swingupCatchDeg + 10.0f, 178.0f) &&
                                vel_raw_dps < SWINGUP_TRANS_FORCED_VEL_DPS;

        // Energy-based
        const float mgl_eb = PEND_MASS * GRAVITY * PEND_LENGTH;
        const float alpha_eb_rad = pendPosRaw * DEG_TO_RAD;
        // Velocidad FISICA: se descuenta la ganancia del estimador (P9).
        const float alpha_dot_phys = alpha_dot / ALPHA_DOT_FILTER_GAIN;
        float E_current = 0.5f * PEND_INERTIA * alpha_dot_phys * alpha_dot_phys +
                          mgl_eb * (1.0f - cosf(alpha_eb_rad));
        float E_target_eb = 2.0f * mgl_eb;
        bool energyReady = (E_target_eb > 0.0f) &&
                           (fabsf(E_current - E_target_eb) / E_target_eb < SWINGUP_TRANS_ENERGY_TOL) &&
                           fabsf(pendPosWrapped) > swingupCatchDeg &&
                           (vel_raw_dps < SWINGUP_TRANS_ENERGY_VEL_DPS);


        if (swingupTransEnable &&
            (canTransition || atPeakTransition || forcedTransition || energyReady)) {
          // Latchear ANTES de setMode(4): setMode limpia estado del modo saliente,
          // y estos valores solo tienen sentido medidos en el instante exacto.
          // Es un bitmask, no un enum: varios criterios pueden cumplirse a la vez y
          // saber cuales coincidieron dice mas que saber cual gano el cortocircuito.
          swing_transReason = (canTransition    ? SWING_TRANS_NEAR   : 0) |
                              (atPeakTransition ? SWING_TRANS_PEAK   : 0) |
                              (forcedTransition ? SWING_TRANS_FORCED : 0) |
                              (energyReady      ? SWING_TRANS_ENERGY : 0);
          // Se latchea el ACOTADO: es el que evaluaron las compuertas, y el que se
          // puede comparar entre corridas. El crudo queda en el log de Serial.
          swing_transAlphaDeg = pendPosWrapped;
          swing_transVelDps   = vel_raw_dps;
          swing_transEnergyRatio = (E_target_eb > 0.0f) ? (E_current / E_target_eb) : 0.0f;
          swing_transMs = millis();

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
          float recover_brake = -SWINGUP_RECOVER_GAIN * alpha_dot;  // Frenado proporcional
          pwm = constrain((int)(MOTOR_DIR * recover_brake * swingupPwmMax), -swingupPwmMax, swingupPwmMax);
          if (fabsf(pendPos) < SWING_RECOVERY_THRESHOLD) {
            swing_recovering = false;
            // Acotar a [-180,180] al salir de recovery, sin redefinir el cero (P13)
            wrapPendulumTurns();
            Serial.printf("Swing-up: recovery COMPLETE (pend=%.1f)\n", pendPos);
          }
        } else if (fabsf(pendPosRaw) > SWINGUP_CROSS_DEG) {
          // El péndulo cruzó la vertical sin transicionar → recovery.
          // Reset offset para que raw se mantenga acotado.
          swing_recovering = true;
          wrapPendulumTurns();
          Serial.printf("Swing-up: RECOVERY START (raw=%.1f, pend=%.1f, vel=%.1f)\n", pendPosRaw, pendPos, vel_raw_dps);
        } else if (fabsf(pendPosRaw) > SWINGUP_DAMP_START_DEG) {
          // ── Damping: disipar energía desde 165° hasta la vertical ──
          float dampStrength = (fabsf(pendPosRaw) - SWINGUP_DAMP_START_DEG) / SWINGUP_DAMP_SPAN_DEG;
          dampStrength = constrain(dampStrength, 0.0f, 1.0f);
          float damping = -(0.3f + 0.7f * dampStrength) * alpha_dot;
          pwm = constrain((int)(MOTOR_DIR * damping * swingupPwmMax), -swingupPwmMax, swingupPwmMax);
        } else if ((E_target_eb > 0.0f) && (E_current / E_target_eb) > swingupEnergyCeiling) {
          // ── Techo de energia: ya sobra, NO se inyecta mas ────────────────
          // Sin esto la ley resonante se realimenta a si misma y el pendulo se
          // embala (ver SWINGUP_ENERGY_CEILING). Se deja en coast en vez de frenar:
          // el freno actua sobre el brazo y no le saca energia al pendulo, mientras
          // que dejar de bombear si la deja caer sola por friccion y damping.
          pwm = 0;
          swing_ceilingHits++;
        } else {
          // ── Resonant pumping: servo oscila a frecuencia del péndulo ────
          // ⚠ ESTA RAMA NUNCA SE HABIA EJECUTADO. Con alpha_dot identicamente
          // cero (F1) la condicion de abajo era siempre verdadera y el modo 5 se
          // reducia al kick sinusoidal de lazo abierto. Todo lo que sigue —
          // bombeo resonante, ke_gain, ganancia adaptativa por calado — se
          // ejecuta por primera vez con este cambio y NO esta validado en banco.
          if (fabsf(alpha_dot) < SWINGUP_QUIET_THRESHOLD_RADPS) {
            // Péndulo quieto: kick sinusoidal para iniciar oscilación
            float t_sec = millis() / 1000.0f;
            float kick_ref = SWINGUP_KICK_AMP_DEG * sinf(2.0f * PI * SWINGUP_KICK_HZ * t_sec);
            float error = kick_ref - pos;
            pwm = (int)(MOTOR_DIR * error * SWINGUP_KICK_KP);
            pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
          } else if (swingupPumpLaw == 1) {
            // ── Bombeo por energia (Astrom-Furuta) ───────────────────────────
            // u = k (E* - E) sign(alpha_dot * cos alpha)
            //
            // A diferencia de la ley resonante, esto NO sigue una referencia de
            // posicion: comanda directamente el sentido de aceleracion del brazo,
            // que es lo que inyecta energia. El termino (E* - E) hace que se apague
            // sola al llegar arriba, sin necesitar un umbral que la corte.
            const float mgl_p = PEND_MASS * GRAVITY * PEND_LENGTH;
            const float a_rad = pendPosRaw * DEG_TO_RAD;
            const float alpha_dot_phys = alpha_dot / ALPHA_DOT_FILTER_GAIN;   // P9
            const float E_now = 0.5f * PEND_INERTIA * alpha_dot_phys * alpha_dot_phys +
                                mgl_p * (1.0f - cosf(a_rad));
            const float E_def = (2.0f * mgl_p) - E_now;   // deficit; >0 mientras falte
            const float s = alpha_dot * cosf(a_rad);
            const float dir = (s >= 0.0f) ? 1.0f : -1.0f;

            // Recentrado: se suma como sesgo de PWM, no de referencia — esta ley no
            // tiene referencia de posicion que sesgar. Sin esto el brazo deriva
            // (medido: el centro de oscilacion se sienta en -18 a -36 deg).
            swing_posMean += (pos - swing_posMean) * SWING_POSMEAN_ALPHA;
            const float centerBias = -swingupCenterGain * swing_posMean;

            pwm = (int)(MOTOR_DIR * swingupPumpSign * swingupEnergyGain * E_def * dir + centerBias);
            pwm = constrain(pwm, -swingupPwmMax, swingupPwmMax);
          } else {
            // Péndulo oscilando: resonant pumping
            float pump_ref = alpha_dot * SWINGUP_PUMP_GAIN_DEG_PER_RADPS;
            // Recentrado: se sesga la referencia en contra de la media lenta de la
            // posicion. Se aplica ANTES del clamp para que el tope siga acotando la
            // excursion total del brazo y no se pueda pedir mas de lo seguro.
            swing_posMean += (pos - swing_posMean) * SWING_POSMEAN_ALPHA;
            pump_ref -= swingupCenterGain * swing_posMean;
            pump_ref = constrain(pump_ref, -swingupPumpRefMaxDeg, swingupPumpRefMaxDeg);
            // Adaptive gain: boost when pendulum stalls
            float currentAbsAngle = fabsf(pendPos);
            if (currentAbsAngle > swing_maxAngleAchieved + SWINGUP_IMPROVE_DEG) {
              swing_maxAngleAchieved = currentAbsAngle;
              swing_lastImprovementMs = millis();
              ke_gain = KE_GAIN_BASE;
            } else if ((millis() - swing_lastImprovementMs) > STALL_TIMEOUT_MS) {
              ke_gain = KE_GAIN_BOOST;
            }

            float error = pump_ref - pos;
            float Kp_pump = ke_gain * SWINGUP_PUMP_KP_SCALE;
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
    // MODO 6: Deep RL (HTTP) — Python envía la acción por /rl_cmd?a=, este lazo
    // la aplica como PWM. La observación de /rl_state se calcula aquí en
    // convención SIM (updateRlObservation, compartida con el modo 7), de modo que
    // una política servida por HTTP ve las MISMAS entradas que en on-device.
    // Endpoints: GET /rl_state (obs), GET /rl_cmd?a=X (action)
    // ══════════════════════════════════════════════════════════════════════════
      // Update the sim-convention observation at the 50 Hz training rate (the
      // velocity filter assumes dt=0.02; ticking it at the 500 Hz loop rate would
      // distort velocities). The motor command itself is applied every loop.
      if (rl_lastTickUs6 == 0 || (nowUs - rl_lastTickUs6) >= 20000UL) {
        rl_lastTickUs6 = nowUs;
        updateRlObservation(pos, pendPosRaw);
      }

      // ── Action clamping: restrict RL to push TOWARD center when far ──
      // Por encima de SERVO_CLAMP_DEG la accion RL solo puede empujar hacia el
      // centro, y se suma un termino de centrado. Mas alla, el respaldo comun
      // (SERVO_HARD_LIMIT_DEG) ya corto el modo antes de llegar aca.
      //
      // Habia ademas una rama "pure centering" a HARD_LIMIT = 110 deg que era
      // INALCANZABLE: el respaldo comun dispara a 95 (auditoria F4). Se elimino;
      // si alguna vez se quiere ese comportamiento, hay que subir el respaldo.
      int rl_pwm = (int)(rlAction * PWM_MAX);
      rl_pwm = constrain(rl_pwm, -PWM_MAX, PWM_MAX);

      if (fabsf(pos) > SERVO_CLAMP_DEG) {
        // Clamp: only allow action that pushes TOWARD center
        if (pos > 0 && rl_pwm > 0) rl_pwm = 0;  // positive pos, block positive action
        if (pos < 0 && rl_pwm < 0) rl_pwm = 0;  // negative pos, block negative action
        // Add centering assist
        int center_pwm = (int)(-pos * RL_CENTERING_KP);
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
      if (rl_lastTickUs7 != 0 && (nowUs - rl_lastTickUs7) < 20000UL) {
        return;  // zero-order hold — keep last motor command
      }
      rl_lastTickUs7 = nowUs;

      // ── Fin de carrera del modo 7: freno activo hacia el centro ────────────
      if (fabsf(pos) > SERVO_BRAKE_DEG) {
        float brake_dir = (pos > 0) ? -1.0f : 1.0f;
        setMotor((int)(brake_dir * SERVO_BRAKE_PWM));
        rl_vf_init = false;  // re-init velocity filter when control resumes
        return;
      }

      // Build the sim-convention observation (theta as-is; alpha FLIPPED + wrapped;
      // positive-finite-difference velocities @ 50 Hz). Shared with mode 6 so the
      // HTTP path (/rl_state) and on-device inference feed the policy identically.
      updateRlObservation(pos, pendPosRaw);

      // Run on-device inference (returns policy action = tanh(mu) in [-1,1]).
      // rl_last_action stored inside is the un-negated policy action (sim convention).
      // ── Hybrid RL swing-up + LQR balance ────────────────────────────────
      // When the RL policy brings the pendulum near the inverted position,
      // smoothly hand off to LQR for balance.  Same velocity estimates,
      // no HTTP mode switch needed.
      // rl_obs_al is in sim convention [-π,π]: inverted = |α| ≈ π.
      // hybrid_lqr es GLOBAL y la limpia setMode(): como static local sobrevivia al
      // cambio de modo, y al re-entrar al modo 7 tras una caida el lazo arrancaba
      // creyendose en fase de balance con el pendulo colgando (auditoria F5).
      float action = rl_infer_step(rl_obs_th, rl_obs_al, rl_obs_thd, rl_obs_ald);

      // LQR transition thresholds — runtime-tunable (serial b/j). rl_obs_al is the
      // wrapped sim-convention alpha in rad, inverted=±π. Compare against the
      // tunable degree thresholds converted to rad.
      const float HYBRID_ENTER = hybrid_enter_deg * DEG_TO_RAD;
      const float HYBRID_EXIT  = hybrid_exit_deg  * DEG_TO_RAD;

      if (!hybrid_lqr && fabsf(rl_obs_al) >= HYBRID_ENTER) {
        hybrid_lqr = true;
      } else if (hybrid_lqr && fabsf(rl_obs_al) < HYBRID_EXIT) {
        hybrid_lqr = false;
      }

      int rl_pwm;
      if (hybrid_lqr) {
        // ── LQR balance (using raw encoder angles, same as mode 4) ──────
        float theta = constrain(pos, -LQR_SERVO_LIMIT_DEG, LQR_SERVO_LIMIT_DEG);
        float alpha_raw = pendPosRaw;
        // alpha to vertical — EXACT mode-4 convention: 0=vertical, negative=below,
        // positive=above/crossed. (The previous (alpha_raw+180) form gave the
        // OPPOSITE sign of mode 4, so the tuned gains pushed the pendulum the wrong
        // way and the catch never held.)
        float alpha = fmodf(alpha_raw - 180.0f, 360.0f);
        if (alpha < -180.0f) alpha += 360.0f;
        else if (alpha > 180.0f) alpha -= 360.0f;
        alpha = -alpha;

        // Velocities in mode-4 convention (deg/s): velTheta ∝ -dθ/dt,
        // velAlpha ∝ -d(alpha_raw)/dt. The rl_vf filter stores sim convention
        // (thVel=+dθ/dt; alVel=-d(alpha_raw)/dt), so: velTheta = -rl_vf_thVel,
        // velAlpha = +rl_vf_alVel (already -d(alpha_raw)/dt). This makes the
        // whole LQR law identical to the proven mode-4 controller.
        float velTheta_ctrl = -rl_vf_thVel * RAD_TO_DEG;
        float velAlpha_ctrl = rl_vf_alVel * RAD_TO_DEG;

        // ── Apex velocity-bleed catch-brake (ported & adapted from mode 4) ──
        // We enter LQR LOW (~112°) so the LQR helps pump to the apex; braking at
        // entry would kill the climb. So the brake is APEX-TRIGGERED: when the
        // pendulum first reaches within hybrid_catch_angle of vertical, brake
        // against the crossing velocity (direction locked on zone entry) for
        // hybrid_catch_ms to dissipate excess energy, THEN let the LQR hold.
        // Re-arms only after leaving the apex zone. gain is sign-flippable (L9<0)
        // if the brake assists instead of opposes.
        // (hybrid_apexCatchMs y hybrid_lockedBrakeDir son globales: setMode() las
        // limpia, para que una entrada nueva al modo 7 llegue con el catch armado.)
        if (fabsf(alpha) < hybrid_catch_angle && hybrid_apexCatchMs == 0) {
          hybrid_apexCatchMs = millis();
          hybrid_lockedBrakeDir = (velAlpha_ctrl > 0.0f) ? 1.0f : -1.0f;
        }
        if (hybrid_apexCatchMs != 0) {
          if ((millis() - hybrid_apexCatchMs) < (unsigned long)hybrid_catch_ms) {
            const float brake = hybrid_lockedBrakeDir * fabsf(velAlpha_ctrl) * hybrid_catch_gain;
            setMotor(constrain((int)brake, -hybrid_catch_pwm, hybrid_catch_pwm));
            return;  // bleed crossing velocity, then the LQR holds
          } else if (fabsf(alpha) >= hybrid_catch_angle) {
            hybrid_apexCatchMs = 0;  // window done and left apex zone → re-arm
          }
        }

        // Gain scheduling (same 3-tier as mode 4)
        float k2_eff = lqr_K2;
        float k4_eff = lqr_K4;
        if (fabsf(alpha) < lqr_very_near_deg) {
          k2_eff = lqr_K2_very_near;
          k4_eff = lqr_K4_very_near;
        } else if (fabsf(alpha) < lqr_near_deg) {
          k2_eff = lqr_K2_near;
          k4_eff = lqr_K4_near;
        }

        // High-velocity catch: BOOST damping for a fast entry (mode-4 behaviour).
        // The old code did the opposite (halved gains for 500ms), which left the
        // catch too weak to arrest the swing and it fell. velAlpha_ctrl is deg/s.
        float vel_alpha_dps = fabsf(velAlpha_ctrl);
        if (vel_alpha_dps > 200.0f) {
          float vel_scale = 1.0f + (vel_alpha_dps - 200.0f) / 300.0f;
          vel_scale = (vel_scale > 2.0f) ? 2.0f : vel_scale;
          k4_eff *= vel_scale;
        }

        float u = -(lqr_K1 * theta + k2_eff * alpha + lqr_K3 * velTheta_ctrl + k4_eff * velAlpha_ctrl);

        // Damping near inverted
        if (fabsf(alpha) < lqr_near_deg) {
          u -= lqr_damping_gain * velAlpha_ctrl;
        }

        rl_pwm = constrain((int)(MOTOR_DIR * u), -hybrid_lqr_pwm, hybrid_lqr_pwm);
      } else {
        // ── RL policy action ────────────────────────────────────────────
        // La politica se ENTRENA detras del wrapper DeadZone (qube_rl/wrappers,
        // WrapperConfig: deadzone=0.2, center=0.01, max_act=0.75), asi que su salida es
        // la accion PREVIA a esa transformacion:
        //
        //     a_efectiva = signo(a) * (|a| * (max_act - deadzone) + deadzone)   si |a| > center
        //                = 0                                                    si no
        //
        // Hasta el 2026-08-04 este camino hacia un mapeo LINEAL y el firmware no tenia
        // deadzone en ninguna parte. La diferencia es sistematica y peor justo donde el
        // bombeo del swing-up vive (acciones moderadas):
        //     |a|=0.10 -> esperado 0.255, entregado 0.100  (39%)
        //     |a|=0.30 -> esperado 0.365, entregado 0.300  (82%)
        //     |a|=1.00 -> esperado 0.750, entregado 1.000  (133%)
        // Medido: el pendulo se quedaba en 60-117 deg donde necesita 180, con el lazo
        // sano y la politica verificada identica a la del .zip.
        //
        // El modo 6 NO lleva esto: ahi la accion llega por /rl_cmd desde el env de
        // Python, que ya aplico el wrapper. Aplicarlo aca lo duplicaria.
        float a = constrain(-action, -1.0f, 1.0f);
        float action_norm = 0.0f;
        if (fabsf(a) > RL_DEADZONE_CENTER) {
          action_norm = (a > 0 ? 1.0f : -1.0f) *
                        (fabsf(a) * (RL_DEADZONE_MAX_ACT - RL_DEADZONE) + RL_DEADZONE);
        }
        rl_pwm = (int)(action_norm * PWM_MAX * rl_pwm_scale);
        rl_pwm = constrain(rl_pwm, -PWM_MAX, PWM_MAX);
      }
      setMotor(rl_pwm);
    }
  }
}
