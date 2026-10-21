/*
  LangRec Arduino prototype — "a heart on a breadboard" + a 4-channel 500 Hz ADC.

  Board: Arduino Uno (ATmega328P, 16 MHz). See docs/ARDUINO_PROTOTYPE.md for the wiring.

  What it does
    1. Generates a left-ventricular-pressure-like waveform as fast PWM on pin 9
       (62.5 kHz). A two-stage RC filter (2 x 10 kOhm + 2 x 10 nF) on the breadboard turns it
       into a smooth analogue curve, which is read back on A0 — so the whole chain
       "analogue signal -> ADC -> USB -> LangRec" is exercised, exactly as with a real rig.
       - potentiometer on A1 sets the heart rate (60-300 bpm);
       - button on pin 2 (to GND) = "ischemia": while held, contractions weaken and
         diastolic pressure creeps up; released -> the heart recovers;
       - LED on pin 13 lights during systole; a buzzer on pin 8 can click on every beat
         (send 'b' over serial to toggle).
    2. Samples A0..A3 at 500 Hz (Timer2) and streams binary frames over USB serial.

  Serial protocol (115200 baud, 8N1), one frame per sample period:
    0xAA 0x55  a0_lo a0_hi  a1_lo a1_hi  a2_lo a2_hi  a3_lo a3_hi  checksum
    values are raw 10-bit ADC counts (0..1023, 5 V reference);
    checksum = sum of the 8 data bytes, modulo 256.
  Commands from the computer: 'b' toggles the buzzer click.
*/

#include <avr/interrupt.h>

const uint8_t PIN_PWM = 9;      // OC1A
const uint8_t PIN_BUTTON = 2;
const uint8_t PIN_BUZZER = 8;
const uint8_t PIN_LED = 13;
const uint16_t RATE_HZ = 500;

volatile bool sampleDue = false;
bool buzzerOn = false;
unsigned long buzzerOffAt = 0;   // tone() would clash with Timer2, so the click is a plain pulse

// heart state
float phase = 0;             // 0..1 within the current beat
float strength = 1.0;        // contractility, 0..1
float edp = 0.08;            // diastolic level as a fraction of full scale
unsigned long lastMicros = 0;

ISR(TIMER2_COMPA_vect) { sampleDue = true; }

void setupTimers() {
  // Timer1: 8-bit fast PWM on OC1A (pin 9), no prescaler -> 16 MHz / 256 = 62.5 kHz
  pinMode(PIN_PWM, OUTPUT);
  TCCR1A = _BV(COM1A1) | _BV(WGM10);
  TCCR1B = _BV(WGM12) | _BV(CS10);
  OCR1A = 0;
  // Timer2: CTC interrupt at 500 Hz: 16 MHz / 256 / (124 + 1) = 500 Hz
  TCCR2A = _BV(WGM21);
  TCCR2B = _BV(CS22) | _BV(CS21);   // prescaler 256
  OCR2A = 124;
  TIMSK2 = _BV(OCIE2A);
}

// Pressure shape over one beat: quick rise, slower relaxation, flat diastole.
float beatShape(float p) {
  const float rise = 0.14, relax = 0.24;
  if (p < rise) return 0.5 - 0.5 * cos(PI * p / rise);
  if (p < rise + relax) return 0.5 + 0.5 * cos(PI * (p - rise) / relax);
  return 0;
}

void updateHeart() {
  unsigned long now = micros();
  float dt = (now - lastMicros) / 1e6;
  lastMicros = now;
  if (dt <= 0 || dt > 0.1) return;

  float bpm = 60 + analogRead(A1) * (240.0 / 1023.0);          // 60..300 bpm
  float prevPhase = phase;
  phase += dt * bpm / 60.0;
  if (phase >= 1.0) phase -= 1.0;
  bool newBeat = phase < prevPhase;

  bool ischemia = digitalRead(PIN_BUTTON) == LOW;
  if (ischemia) {
    strength += (0.08 - strength) * dt / 3.0;    // fades within a few seconds
    edp += (0.22 - edp) * dt / 8.0;              // contracture-like rise
  } else {
    strength += (1.0 - strength) * dt / 8.0;     // slower recovery
    edp += (0.08 - edp) * dt / 6.0;
  }

  float level = edp + 0.7 * strength * beatShape(phase);
  if (level > 1) level = 1;
  OCR1A = (uint8_t)(level * 255);
  digitalWrite(PIN_LED, beatShape(phase) > 0.2 ? HIGH : LOW);
  if (newBeat && buzzerOn && strength > 0.2) {
    digitalWrite(PIN_BUZZER, HIGH);          // active buzzer: a short beep; passive: a click
    buzzerOffAt = millis() + 15;
  }
  if (buzzerOffAt && millis() >= buzzerOffAt) {
    digitalWrite(PIN_BUZZER, LOW);
    buzzerOffAt = 0;
  }
}

void sendFrame() {
  uint16_t v[4] = {(uint16_t)analogRead(A0), (uint16_t)analogRead(A1),
                   (uint16_t)analogRead(A2), (uint16_t)analogRead(A3)};
  uint8_t buf[11];
  buf[0] = 0xAA;
  buf[1] = 0x55;
  uint8_t sum = 0;
  for (uint8_t i = 0; i < 4; i++) {
    buf[2 + 2 * i] = v[i] & 0xFF;
    buf[3 + 2 * i] = v[i] >> 8;
    sum += buf[2 + 2 * i] + buf[3 + 2 * i];
  }
  buf[10] = sum;
  Serial.write(buf, sizeof(buf));
}

void setup() {
  Serial.begin(115200);
  pinMode(PIN_BUTTON, INPUT_PULLUP);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_BUZZER, OUTPUT);
  setupTimers();
  lastMicros = micros();
}

void loop() {
  if (sampleDue) {
    sampleDue = false;
    sendFrame();          // 4 conversions ~0.45 ms, 11 bytes at 115200 baud ~1 ms
    updateHeart();
  }
  while (Serial.available()) {
    if (Serial.read() == 'b') buzzerOn = !buzzerOn;
  }
}
