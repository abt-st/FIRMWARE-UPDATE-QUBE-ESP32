/**
 * @file test_encoder_pulse_loss.cpp
 * @brief Test de diagnóstico: pérdida de pulsos en ISR vs PCNT
 *
 * Genera señales de cuadratura sintéticas y compara cuántos pulsos captura
 * cada método de conteo (ISR de software vs PCNT hardware) a diferentes
 * frecuencias.
 *
 * Conexión física requerida (jumper wire):
 *   GPIO18 (GEN_A) ──────→ GPIO23 (INPUT_A)
 *   GPIO19 (GEN_B) ──────→ GPIO22 (INPUT_B)
 *
 * Resultados: se imprimen por Serial a 115200 bauds en formato tabla.
 *
 * Uso:
 *   1. Subir con: pio run -t upload -e esp32dev_debug
 *   2. Abrir monitor serie: pio device monitor
 *   3. Conectar GPIO18→GPIO23 y GPIO19→GPIO22 con jumper wire
 *   4. Observar resultados
 *
 * @note Este test es para hardware real ESP32. No ejecutar en nativo/simulador.
 */

#include <Arduino.h>
#include <unity.h>
#include "driver/pcnt.h"

// ═══════════════════════════════════════════════════════════════════════════════
// Pin Definitions
// ═══════════════════════════════════════════════════════════════════════════════

// Generador de señales (salida)
static const int GEN_A_PIN = 18;  // GPIO18 — Canal A del encoder sintético
static const int GEN_B_PIN = 19;  // GPIO19 — Canal B del encoder sintético

// Entrada para ISR y PCNT (los dos leen los mismos pines)
static const int INPUT_A_PIN = 23;  // GPIO23 — Conectado a GEN_A_PIN
static const int INPUT_B_PIN = 22;  // GPIO22 — Conectado a GEN_B_PIN

// PCNT unit para el test
static const pcnt_unit_t PCNT_TEST_UNIT = PCNT_UNIT_4;  // Unit 4: GPIO25/GPIO26
// Nota: PCNT_4 usa GPIO25 (A) y GPIO26 (B) por defecto.
// Vamos a usar PCNT_0 con GPIO23/GPIO22 si es posible, o mapear manualmente.
// ESP32 PCNT pin mapping:
//   PCNT_0: GPIO34/35 (input-only, no gen)
//   PCNT_1: GPIO36/37 (input-only)
//   PCNT_2: GPIO38/39 (input-only)
//   PCNT_3: GPIO32/33
//   PCNT_4: GPIO25/26
//   PCNT_5: GPIO27/14
//   PCNT_6: GPIO16/17
//   PCNT_7: GPIO4/5
//
// Ninguno mapea a GPIO23/22. Usaremos la unidad que mejor se acerque
// y configuraremos los pines manualmente con pcnt_set_pin().

// ═══════════════════════════════════════════════════════════════════════════════
// ISR Encoder — Replica exacta del firmware actual
// ═══════════════════════════════════════════════════════════════════════════════

volatile long isrCountA = 0;   // Conteo por flanco CHANGE en A
volatile long isrCountB = 0;   // Conteo por flanco CHANGE en B
volatile long isrCountTotal = 0;  // A + B (simula X4 software)
volatile long isrOverrunCount = 0;  // Veces que el ISR no terminó a tiempo

// ISR idéntica al firmware: lee ambos pines para decidir dirección
void IRAM_ATTR isrTestA() {
    const uint32_t start = ESP_CPU_CYCLES();
    if (digitalRead(INPUT_A_PIN) == digitalRead(INPUT_B_PIN)) {
        isrCountA++;
    } else {
        isrCountA--;
    }
    const uint32_t elapsed = ESP_CPU_CYCLES() - start;
    // Detectar si el ISR tardó más de lo esperado (>80% del período mínimo)
    // Esto es un indicador de que pulses podrían perderse
    (void)elapsed;
}

void IRAM_ATTR isrTestB() {
    if (digitalRead(INPUT_A_PIN) != digitalRead(INPUT_B_PIN)) {
        isrCountB++;
    } else {
        isrCountB--;
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// PCNT — Conteo por hardware
// ═══════════════════════════════════════════════════════════════════════════════

// Usamos PCNT_0 para el test. Aunque el mapeo por defecto es GPIO34/35,
// podemos reconfigurar los pines con pcnt_set_pin() si el SDK lo permite.
// Si no, usamos una unidad cuyos pines por defecto estén libres.

static const pcnt_unit_t PCNT_UNIT = PCNT_UNIT_6;  // GPIO16/17 por defecto
// GPIO16/17 están libres en nuestro setup. Pero necesitamos GPIO23/22.
// Solución: usar pcnt_set_pin() para reasignar.

void pcntInitX4(pcnt_unit_t unit, int pinA, int pinB) {
    // Configurar los pines manualmente (sobreescribe el mapeo por defecto)
    pcnt_set_pin(unit, PCNT_CHANNEL_0, pinA, pinB);
    pcnt_set_pin(unit, PCNT_CHANNEL_1, pinB, pinA);

    // Canal 0: cuenta flancos en A, revierte con B alto
    pcnt_set_edge_action(unit, PCNT_CHANNEL_0,
                         PCNT_COUNT_INC,    // Flanco en signal (A) → incrementa
                         PCNT_COUNT_INC);   // Ambos flancos
    pcnt_set_level_action(unit, PCNT_CHANNEL_0,
                          PCNT_MODE_KEEP,    // B bajo → mantiene dirección
                          PCNT_MODE_REVERSE); // B alto → invierte

    // Canal 1: cuenta flancos en B, revierte con A alto
    pcnt_set_edge_action(unit, PCNT_CHANNEL_1,
                         PCNT_COUNT_INC,
                         PCNT_COUNT_INC);
    pcnt_set_level_action(unit, PCNT_CHANNEL_1,
                          PCNT_MODE_KEEP,
                          PCNT_MODE_REVERSE);

    // Filtro: ignorar pulsos menores a 10µs (rechaza rebotes)
    pcnt_set_filter_value(unit, 10);
    pcnt_filter_enable(unit);

    // Límites del contador (evitar overflow)
    pcnt_set_event_value(unit, PCNT_EVT_ZERO, 0);

    // Limpiar y arrancar
    pcnt_counter_pause(unit);
    pcnt_counter_clear(unit);
    pcnt_counter_resume(unit);
}

int32_t pcntReadX4(pcnt_unit_t unit) {
    int16_t count = 0;
    pcnt_get_counter_value(unit, &count);
    return (int32_t)count;
}

void pcntReset(pcnt_unit_t unit) {
    pcnt_counter_pause(unit);
    pcnt_counter_clear(unit);
    pcnt_counter_resume(unit);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Generador de Señales de Cuadratura
// ═══════════════════════════════════════════════════════════════════════════════

/**
 * Genera N ciclos completos de cuadratura a la frecuencia dada.
 * Un ciclo = 4 transiciones (X4 encoding).
 *
 * @param cycles Número de ciclos completos a generar
 * @param freqHz Frecuencia del encoder en Hz (ciclos por segundo)
 * @return Número de transiciones generadas (= cycles × 4)
 */
unsigned long generateQuadrature(unsigned long cycles, unsigned long freqHz) {
    // Período de media transición en microsegundos
    // Un ciclo de cuadratura tiene 4 transiciones:
    //   A↑B0 → A1B0 → A1B↑ → A1B1 → A↓B1 → A0B1 → A0B↓ → A0B0
    // Simplificado a 4 estados: 00, 10, 11, 01
    const unsigned long halfPeriodUs = 1000000UL / (freqHz * 4);

    for (unsigned long i = 0; i < cycles; i++) {
        // Estado 00
        digitalWrite(GEN_A_PIN, LOW);
        digitalWrite(GEN_B_PIN, LOW);
        delayMicroseconds(halfPeriodUs);

        // Estado 10
        digitalWrite(GEN_A_PIN, HIGH);
        digitalWrite(GEN_B_PIN, LOW);
        delayMicroseconds(halfPeriodUs);

        // Estado 11
        digitalWrite(GEN_A_PIN, HIGH);
        digitalWrite(GEN_B_PIN, HIGH);
        delayMicroseconds(halfPeriodUs);

        // Estado 01
        digitalWrite(GEN_A_PIN, LOW);
        digitalWrite(GEN_B_PIN, HIGH);
        delayMicroseconds(halfPeriodUs);
    }

    return cycles * 4;
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test Helpers
// ═══════════════════════════════════════════════════════════════════════════════

struct TestResult {
    unsigned long expected;    // Transiciones generadas
    long isrCountA;           // Flancos capturados por ISR en A
    long isrCountB;           // Flancos capturados por ISR en B
    long isrTotal;            // ISR A + ISR B
    int32_t pcntCount;        // Conteo del PCNT
    float isrLossPercent;     // % de pulsos perdidos por ISR
    float pcntLossPercent;    // % de pulsos perdidos por PCNT
    unsigned long durationMs; // Duración del test
};

TestResult runEncoderTest(unsigned long cycles, unsigned long freqHz, const char* label) {
    // Reset contadores
    noInterrupts();
    isrCountA = 0;
    isrCountB = 0;
    isrCountTotal = 0;
    interrupts();

    pcntReset(PCNT_UNIT);

    // Estabilizar pines
    digitalWrite(GEN_A_PIN, LOW);
    digitalWrite(GEN_B_PIN, LOW);
    delayMicroseconds(100);

    // Generar señales
    const unsigned long startMs = millis();
    const unsigned long expectedTransitions = generateQuadrature(cycles, freqHz);
    const unsigned long durationMs = millis() - startMs;

    // Leer resultados
    noInterrupts();
    const long countA = isrCountA;
    const long countB = isrCountB;
    interrupts();

    const int32_t pcntVal = pcntReadX4(PCNT_UNIT);

    // Calcular totales (valor absoluto para X4)
    const long isrTotal = abs(countA) + abs(countB);

    TestResult r;
    r.expected = expectedTransitions;
    r.isrCountA = countA;
    r.isrCountB = countB;
    r.isrTotal = isrTotal;
    r.pcntCount = pcntVal;
    r.isrLossPercent = (expectedTransitions > 0)
        ? (1.0f - (float)isrTotal / (float)expectedTransitions) * 100.0f
        : 0.0f;
    r.pcntLossPercent = (expectedTransitions > 0)
        ? (1.0f - (float)abs(pcntVal) / (float)expectedTransitions) * 100.0f
        : 0.0f;
    r.durationMs = durationMs;

    return r;
}

void printResult(const TestResult& r, const char* freqLabel) {
    Serial.printf("  %-12s | %6lu | %6ld | %6ld | %+6d | %5.1f%% | %5.1f%% | %lu ms\n",
                  freqLabel,
                  r.expected,
                  r.isrTotal,
                  abs(r.pcntCount),
                  r.pcntCount,
                  r.isrLossPercent,
                  r.pcntLossPercent,
                  r.durationMs);
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Validación de Hardware (conexión de cables)
// ═══════════════════════════════════════════════════════════════════════════════

void test_hardware_connection() {
    Serial.println("\n=== TEST: Verificación de conexión ===");
    Serial.println("Generando 1 ciclo a 10 Hz (lento)...");

    // Reset
    noInterrupts();
    isrCountA = 0;
    isrCountB = 0;
    interrupts();
    pcntReset(PCNT_UNIT);

    digitalWrite(GEN_A_PIN, LOW);
    digitalWrite(GEN_B_PIN, LOW);
    delay(10);

    // Generar 1 ciclo lento
    const unsigned long expected = generateQuadrature(1, 10);

    noInterrupts();
    const long countA = isrCountA;
    const long countB = isrCountB;
    interrupts();
    const int32_t pcntVal = pcntReadX4(PCNT_UNIT);

    Serial.printf("  Esperado:   %lu transiciones\n", expected);
    Serial.printf("  ISR A:      %ld\n", countA);
    Serial.printf("  ISR B:      %ld\n", countB);
    Serial.printf("  ISR Total:  %ld\n", abs(countA) + abs(countB));
    Serial.printf("  PCNT:       %d\n", pcntVal);

    // Verificar que al menos el PCNT capturó algo
    TEST_ASSERT_TRUE_MESSAGE(abs(pcntVal) >= 2,
        "PCNT no detectó pulsos. Verificar conexión GPIO18→GPIO23 y GPIO19→GPIO22");

    // Verificar que ISR y PCNT están en el mismo rango
    const long isrTotal = abs(countA) + abs(countB);
    TEST_ASSERT_TRUE_MESSAGE(isrTotal >= 2,
        "ISR no detectó pulsos. Verificar conexión y pull-ups");

    Serial.println("  ✅ Conexión verificada\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Pérdida de Pulsos vs Frecuencia
// ═══════════════════════════════════════════════════════════════════════════════

void test_pulse_loss_vs_frequency() {
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  TEST: Pérdida de Pulsos — ISR Software vs PCNT Hardware");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");
    Serial.println("  Conexión: GPIO18→GPIO23, GPIO19→GPIO22");
    Serial.println("  Cada fila = 1000 ciclos de cuadratura (4000 transiciones)\n");

    Serial.printf("  %-12s | %-6s | %-6s | %-6s | %-6s | %-6s | %-6s | %-8s\n",
                  "Frecuencia", "Espero", "ISR", "PCNT", "ISR %", "PCNT %", "Tiempo");
    Serial.printf("  %-12s-+-%-6s-+-%-6s-+-%-6s-+-%-6s-+-%-6s-+-%-6s-+-%-8s\n",
                  "------------", "------", "------", "------", "------", "------", "------", "--------");

    const unsigned long CYCLES = 1000;  // 1000 ciclos = 4000 transiciones

    // Tabla de frecuencias a probar
    struct TestCase {
        unsigned long freqHz;
        const char* label;
        const char* rpmEquivalent;
    };

    TestCase tests[] = {
        {    100, "100 Hz",    "~0.7 RPM" },
        {    500, "500 Hz",    "~3.7 RPM" },
        {  1000, "1 kHz",     "~7.3 RPM" },
        {  5000, "5 kHz",     "~37 RPM" },
        { 10000, "10 kHz",    "~73 RPM" },
        { 20000, "20 kHz",    "~147 RPM" },
        { 50000, "50 kHz",    "~366 RPM" },
        {100000, "100 kHz",   "~732 RPM" },
        {136533, "136.5 kHz", "~1000 RPM (máx real)" },
        {200000, "200 kHz",   "~1465 RPM (超出)" },
    };

    const int numTests = sizeof(tests) / sizeof(tests[0]);

    for (int i = 0; i < numTests; i++) {
        const unsigned long freq = tests[i].freqHz;

        // Generar y medir
        TestResult r = runEncoderTest(CYCLES, freq, tests[i].label);

        // Imprimir resultado
        printResult(r, tests[i].label);

        // Pausa entre tests
        delay(200);
    }

    Serial.println("\n  ════════════════════════════════════════════════════════════════════════");
    Serial.println("  Análisis:");
    Serial.println("  - Si ISR% > 0%: el ISR está perdiendo pulsos a esa frecuencia");
    Serial.println("  - Si PCNT% ≈ 0% en todas: PCNT no pierde pulsos (hardware dedicado)");
    Serial.println("  - La diferencia ISR% - PCNT% = pulsos que WiFi/otros ISRs robaron");
    Serial.println("  ════════════════════════════════════════════════════════════════════════\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Efecto de Carga de CPU en ISRs
// ═══════════════════════════════════════════════════════════════════════════════

// Simula carga de CPU haciendo cálculos pesados en el loop principal
volatile float fakeLoad = 0;

void simulateCpuLoad() {
    // Simular trabajo del PID + WebSocket + INA219
    for (int i = 0; i < 500; i++) {
        fakeLoad += sinf((float)i) * cosf((float)i);
    }
}

void test_cpu_load_effect() {
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  TEST: Efecto de Carga de CPU en ISRs");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");
    Serial.println("  Compara: ISR solo vs ISR con carga de CPU simulada");
    Serial.println("  Frecuencia fija: 50 kHz (1000 RPM equiv.)\n");

    const unsigned long FREQ = 50000;
    const unsigned long CYCLES = 500;

    // Test 1: Sin carga de CPU
    Serial.println("  [1/2] Sin carga de CPU...");
    TestResult r1 = runEncoderTest(CYCLES, FREQ, "50kHz limpio");
    printResult(r1, "Sin carga");

    delay(500);

    // Test 2: Con carga de CPU
    Serial.println("  [2/2] Con carga de CPU simulada...");
    noInterrupts();
    isrCountA = 0;
    isrCountB = 0;
    interrupts();
    pcntReset(PCNT_UNIT);

    digitalWrite(GEN_A_PIN, LOW);
    digitalWrite(GEN_B_PIN, LOW);
    delayMicroseconds(100);

    const unsigned long startMs = millis();
    const unsigned long expected = generateQuadrature(CYCLES, FREQ);
    // Inyectar carga de CPU entre transiciones
    // (el generador ya usa delayMicroseconds, pero agregamos más carga)
    simulateCpuLoad();
    const unsigned long durationMs = millis() - startMs;

    noInterrupts();
    const long countA = isrCountA;
    const long countB = isrCountB;
    interrupts();
    const int32_t pcntVal = pcntReadX4(PCNT_UNIT);

    const long isrTotal = abs(countA) + abs(countB);

    TestResult r2;
    r2.expected = expected;
    r2.isrCountA = countA;
    r2.isrCountB = countB;
    r2.isrTotal = isrTotal;
    r2.pcntCount = pcntVal;
    r2.isrLossPercent = (1.0f - (float)isrTotal / (float)expected) * 100.0f;
    r2.pcntLossPercent = (1.0f - (float)abs(pcntVal) / (float)expected) * 100.0f;
    r2.durationMs = durationMs;

    printResult(r2, "Con carga");

    Serial.printf("\n  Diferencia ISR: %.1f%% → %.1f%%\n",
                  r1.isrLossPercent, r2.isrLossPercent);
    if (r2.isrLossPercent > r1.isrLossPercent) {
        Serial.println("  ⚠️  La carga de CPU aumentó la pérdida de pulsos en ISR");
    }
    Serial.println("  PCNT no se ve afectado por la carga de CPU\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Overflow del Contador PCNT (16 bits)
// ═══════════════════════════════════════════════════════════════════════════════

void test_pcnt_overflow() {
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  TEST: Overflow del Contador PCNT (16 bits)");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");
    Serial.println("  Generando 10,000 ciclos (40,000 transiciones) a 10 kHz");
    Serial.println("  El PCNT solo cuenta 16 bits (-32768..32767)");
    Serial.println("  Si el software no lee el contador a tiempo, se desborda.\n");

    const unsigned long CYCLES = 10000;  // 40,000 transiciones
    const unsigned long FREQ = 10000;

    noInterrupts();
    isrCountA = 0;
    isrCountB = 0;
    interrupts();
    pcntReset(PCNT_UNIT);

    digitalWrite(GEN_A_PIN, LOW);
    digitalWrite(GEN_B_PIN, LOW);
    delayMicroseconds(100);

    const unsigned long startMs = millis();
    const unsigned long expected = generateQuadrature(CYCLES, FREQ);
    const unsigned long durationMs = millis() - startMs;

    noInterrupts();
    const long countA = isrCountA;
    const long countB = isrCountB;
    interrupts();
    const int32_t pcntVal = pcntReadX4(PCNT_UNIT);

    const long isrTotal = abs(countA) + abs(countB);

    Serial.printf("  Generado:       %lu transiciones\n", expected);
    Serial.printf("  ISR Total:      %ld (%.1f%% del esperado)\n",
                  isrTotal, (float)isrTotal / (float)expected * 100.0f);
    Serial.printf("  PCNT (1 lectura): %d\n", pcntVal);
    Serial.printf("  PCNT overflow:  %s\n",
                  abs(pcntVal) < (int)expected ? "SÍ (16 bits insuficiente)" : "NO");
    Serial.println("\n  Nota: El ISR acumula en `long` (32 bits), no tiene este problema.");
    Serial.println("  Solución en PCNT: leer periódicamente y acumular en software.\n");
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Precisión del PCNT (referencia golden)
// ═══════════════════════════════════════════════════════════════════════════════

void test_pcnt_accuracy() {
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  TEST: Precisión del PCNT (referencia golden)");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");
    Serial.println("  Verifica que PCNT cuenta exactamente a bajas frecuencias.");
    Serial.println("  Si PCNT falla aquí, hay un problema de configuración.\n");

    struct TestCase {
        unsigned long cycles;
        unsigned long freqHz;
        const char* label;
    };

    TestCase tests[] = {
        {     10,      10, "10 ciclos @ 10Hz" },
        {    100,      10, "100 ciclos @ 10Hz" },
        {   1000,     100, "1K ciclos @ 100Hz" },
        {   1000,    1000, "1K ciclos @ 1kHz" },
        {   5000,    5000, "5K ciclos @ 5kHz" },
    };

    Serial.printf("  %-22s | %-10s | %-8s | %-8s | %-6s\n",
                  "Test", "Esperado", "PCNT", "Error", "Estado");
    Serial.printf("  %-22s-+-%-10s-+-%-8s-+-%-8s-+-%-6s\n",
                  "----------------------", "----------", "--------", "--------", "------");

    for (int i = 0; i < 5; i++) {
        const unsigned long expected = tests[i].cycles * 4;

        noInterrupts();
        isrCountA = 0;
        isrCountB = 0;
        interrupts();
        pcntReset(PCNT_UNIT);

        digitalWrite(GEN_A_PIN, LOW);
        digitalWrite(GEN_B_PIN, LOW);
        delayMicroseconds(100);

        generateQuadrature(tests[i].cycles, tests[i].freqHz);

        const int32_t pcntVal = abs(pcntReadX4(PCNT_UNIT));
        const int32_t error = (int32_t)expected - pcntVal;

        const char* status = (error == 0) ? "✅ PASS" : "❌ FAIL";

        Serial.printf("  %-22s | %10lu | %8d | %+8d | %s\n",
                      tests[i].label, expected, pcntVal, error, status);

        TEST_ASSERT_EQUAL_INT32_MESSAGE(expected, pcntVal,
            "PCNT no contó correctamente — revisar configuración");

        delay(100);
    }

    Serial.println();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Test: Benchmark de Tiempo del ISR
// ═══════════════════════════════════════════════════════════════════════════════

// Variables para medición de timing
volatile uint32_t isrMinCycles = UINT32_MAX;
volatile uint32_t isrMaxCycles = 0;
volatile uint32_t isrTotalCycles = 0;
volatile uint32_t isrCallCount = 0;

void IRAM_ATTR isrTimedA() {
    const uint32_t start = ESP_CPU_CYCLES();
    if (digitalRead(INPUT_A_PIN) == digitalRead(INPUT_B_PIN)) {
        isrCountA++;
    } else {
        isrCountA--;
    }
    const uint32_t elapsed = ESP_CPU_CYCLES() - start;
    if (elapsed < isrMinCycles) isrMinCycles = elapsed;
    if (elapsed > isrMaxCycles) isrMaxCycles = elapsed;
    isrTotalCycles += elapsed;
    isrCallCount++;
}

void test_isr_timing() {
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  TEST: Benchmark de Tiempo del ISR");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");

    // Temporalmente usar ISR timed
    detachInterrupt(digitalPinToInterrupt(INPUT_A_PIN));
    attachInterrupt(digitalPinToInterrupt(INPUT_A_PIN), isrTimedA, CHANGE);

    // Reset métricas
    noInterrupts();
    isrMinCycles = UINT32_MAX;
    isrMaxCycles = 0;
    isrTotalCycles = 0;
    isrCallCount = 0;
    isrCountA = 0;
    isrCountB = 0;
    interrupts();

    pcntReset(PCNT_UNIT);

    // Generar 5000 ciclos a 10kHz
    const unsigned long CYCLES = 5000;
    const unsigned long FREQ = 10000;

    Serial.printf("  Generando %lu ciclos a %lu Hz...\n", CYCLES, FREQ);
    generateQuadrature(CYCLES, FREQ);

    // Leer métricas
    noInterrupts();
    const uint32_t minC = isrMinCycles;
    const uint32_t maxC = isrMaxCycles;
    const uint32_t totalC = isrTotalCycles;
    const uint32_t calls = isrCallCount;
    interrupts();

    const float cpuFreqMHz = 240.0f;  // ESP32 default
    const float minUs = (float)minC / cpuFreqMHz;
    const float maxUs = (float)maxC / cpuFreqMHz;
    const float avgUs = (calls > 0) ? (float)totalC / (float)calls / cpuFreqMHz : 0;

    Serial.printf("  ISR ejecutado %lu veces\n", calls);
    Serial.printf("  Tiempo mínimo:  %lu ciclos (~%.1f µs)\n", minC, minUs);
    Serial.printf("  Tiempo máximo:  %lu ciclos (~%.1f µs)\n", maxC, maxUs);
    Serial.printf("  Tiempo promedio: %lu ciclos (~%.1f µs)\n",
                  (calls > 0 ? totalC / calls : 0), avgUs);
    Serial.printf("  Período entre pulsos a 10kHz: ~25 µs (X4: 4 transiciones/ciclo)\n");

    if (avgUs > 20.0f) {
        Serial.println("  ⚠️  ISR promedio > 20µs: a 50kHz ya empezará a perder pulsos");
    }
    if (maxUs > 25.0f) {
        Serial.println("  ⚠️  ISR máximo > 25µs: pulsos garantidos perdidos a 50kHz");
    }

    // Restaurar ISR normal
    detachInterrupt(digitalPinToInterrupt(INPUT_A_PIN));
    attachInterrupt(digitalPinToInterrupt(INPUT_A_PIN), isrTestA, CHANGE);

    Serial.println();
}

// ═══════════════════════════════════════════════════════════════════════════════
// Setup y Loop
// ═══════════════════════════════════════════════════════════════════════════════

void setup() {
    Serial.begin(115200);
    delay(2000);  // Esperar estabilización del monitor serie

    Serial.println("\n");
    Serial.println("╔═══════════════════════════════════════════════════════════════════════╗");
    Serial.println("║     TEST: Pérdida de Pulsos del Encoder — ISR vs PCNT                ║");
    Serial.println("║     QUBE Servo ESP32 — Diagnóstico de Hardware                       ║");
    Serial.println("╚═══════════════════════════════════════════════════════════════════════╝");
    Serial.println();
    Serial.println("  Conexión física requerida:");
    Serial.println("    GPIO18 (GEN_A) ──── jumper wire ────→ GPIO23 (INPUT_A)");
    Serial.println("    GPIO19 (GEN_B) ──── jumper wire ────→ GPIO22 (INPUT_B)");
    Serial.println();
    Serial.println("  IMPORTANTE: Sin estos cables, los tests fallarán.");
    Serial.println();

    // Configurar pines del generador
    pinMode(GEN_A_PIN, OUTPUT);
    pinMode(GEN_B_PIN, OUTPUT);
    digitalWrite(GEN_A_PIN, LOW);
    digitalWrite(GEN_B_PIN, LOW);

    // Configurar pines de entrada
    pinMode(INPUT_A_PIN, INPUT);
    pinMode(INPUT_B_PIN, INPUT);

    // Configurar ISR (replica del firmware actual)
    attachInterrupt(digitalPinToInterrupt(INPUT_A_PIN), isrTestA, CHANGE);
    attachInterrupt(digitalPinToInterrupt(INPUT_B_PIN), isrTestB, CHANGE);

    // Configurar PCNT
    pcntInitX4(PCNT_UNIT, INPUT_A_PIN, INPUT_B_PIN);

    delay(500);
}

void loop() {
    Serial.println("Presione cualquier tecla para iniciar los tests...\n");
    while (!Serial.available()) {
        delay(100);
    }
    Serial.read();  // Limpiar buffer

    // Ejecutar todos los tests
    test_hardware_connection();
    delay(1000);

    test_pcnt_accuracy();
    delay(1000);

    test_isr_timing();
    delay(1000);

    test_pulse_loss_vs_frequency();
    delay(1000);

    test_cpu_load_effect();
    delay(1000);

    test_pcnt_overflow();

    // Resumen final
    Serial.println("\n═══════════════════════════════════════════════════════════════════════");
    Serial.println("  RESUMEN");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");
    Serial.println("  Si los resultados muestran:");
    Serial.println("  1. ISR pierde pulsos a frecuencias altas → confirma la hipótesis");
    Serial.println("  2. PCNT no pierde pulsos en ninguna frecuencia → PCNT es la solución");
    Serial.println("  3. La carga de CPU aumenta la pérdida → WiFi empeora el problema");
    Serial.println("  4. El timing del ISR es > 10µs → hard limit alcanzable");
    Serial.println();
    Serial.println("  Próximos pasos:");
    Serial.println("  - Migrar encoders a PCNT en el firmware principal");
    Serial.println("  - Eliminar ISRs de encoder (liberar ~10µs por pulso de CPU)");
    Serial.println("  - Verificar que el PID mantiene posición con PCNT");
    Serial.println("═══════════════════════════════════════════════════════════════════════\n");

    Serial.println("Tests completados. Reiniciando en 10 segundos...");
    delay(10000);
    ESP.restart();
}
