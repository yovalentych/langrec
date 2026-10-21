# Arduino prototype: a heart on a breadboard

A cheap way to exercise the whole live chain — analogue signal → ADC → USB → LangRec — before a
real DAQ is bought. An Arduino Uno generates a left-ventricular-pressure-like waveform, reads it
back through its own ADC together with a knob and a light sensor, and streams four channels at
500 Hz to LangRec (source **Arduino**). Works on macOS, Windows and Linux.

A step-by-step illustrated guide (in Ukrainian, for complete beginners) was published as a
separate page; the wiring below is the same.

## Parts
Arduino Uno + USB cable, solderless breadboard, jumper wires, blue trimmer potentiometer,
3 × 10 kΩ, 1 × 220 Ω, 2 × 10 nF ceramic capacitors ("103"), tactile push button,
buzzer, photoresistor (LDR), red LED.

## Wiring
| Signal | Arduino | Breadboard |
|---|---|---|
| Power | 5V, GND | top rails (+, −); jumpers to the bottom rails at column 28–29 |
| Heart-rate knob | A1 | trimmer in e4–e6; a4 → +, a6 → −, wiper b5 → A1 |
| Heart waveform (PWM) | pin 9 | pin 9 → a10; 10 kΩ b10–b14; 10 nF a14 → −; 10 kΩ c14–c18; 10 nF a18 → −; d18 → **A0** |
| "Ischemia" button | pin 2 | button across the channel at e22/e24/f22/f24; a22 → pin 2; j24 → − (diagonal legs) |
| Buzzer (optional) | pin 8 | h27 (+) / h29; g27 → pin 8; j29 → − |
| Finger pulse (optional) | A2 | 220 Ω + rail → j5, LED i5 (+) / i6, j6 → −; LDR + rail → j10; 10 kΩ i10–i14; j14 → −; g10 → **A2** |

The two-stage RC filter (2 × 10 kΩ / 10 nF, corner ≈ 1.6 kHz each) removes the 62.5 kHz PWM
carrier (≈ 50 dB) while keeping the beat shape. The onboard LED (pin 13) lights during systole.

**Never** feed signals outside 0–5 V into the Uno's analogue inputs. Real ±10 V amplifier
outputs need a divider and a 2.5 V offset (or a proper DAQ, see [HARDWARE.md](HARDWARE.md)).

## Firmware
`firmware/langrec_arduino/langrec_arduino.ino`
- Timer1: 8-bit fast PWM on pin 9 at 62.5 kHz — the "heart" (60–300 bpm from A1; while the button
  is held contractility fades with τ ≈ 3 s and diastolic level rises; recovery τ ≈ 8 s).
- Timer2: 500 Hz sampling of A0–A3.
- Serial 115200 baud, one 11-byte frame per sample:
  `0xAA 0x55 | A0 A1 A2 A3 as uint16 LE (0..1023) | checksum = sum of the 8 data bytes mod 256`.
- Command `b` toggles a buzzer click on every beat (plain pulse: `tone()` would clash with Timer2).

Build and upload:
```bash
arduino-cli core install arduino:avr
arduino-cli compile --fqbn arduino:avr:uno firmware/langrec_arduino
arduino-cli upload  --fqbn arduino:avr:uno -p /dev/cu.usbmodem… firmware/langrec_arduino
```

## In LangRec
*Signal source → Arduino* → choose the port → **Connect Arduino**. Channels: `A0 heart`
(role LV pressure, volts), `A1 knob`, `A2 light`, `A3` (hidden). For the finger pulse give A2 the
role *LV pressure* and filters HP 0.5 Hz + LP 5 Hz.

Implementation: `langrec/sources/arduino.py` — a reader thread parses the byte stream,
resynchronises on the header after garbage and drops frames with a bad checksum (tests:
`tests/test_arduino.py`).
