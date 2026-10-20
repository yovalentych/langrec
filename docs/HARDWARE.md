# Choosing a modern ADC board

No decision yet (as of October 2026, not urgent). This page collects requirements and options
so that nothing is forgotten when the time comes.

## Requirements
| What | Minimum | Why |
|---|---|---|
| Input range | **±10 V** | connect existing transducer amplifiers unchanged (the DT2801 had ±10.24 V) |
| Resolution | 12 bit (16 preferred) | 12 bit = 5 mV per step as before; 16 bit leaves headroom |
| Sampling rate | **≥ 500–1000 Hz per channel** | 100 Hz clips the dP/dt peak; ECG needs ≥ 500 Hz |
| Channels | 4–8 analogue | LVP, perfusion pressure, flow, ECG, temperature + spare |
| Input mode | differential or single-ended | differential picks up less interference |
| Connection | USB | works with any laptop |
| Drivers | Windows + macOS + Linux | keep the program cross-platform |
| Digital inputs | 1–2 (nice to have) | external marker button or ischemia valve state |

## Options
| Board | Win / Mac / Linux | Approx. price | Notes |
|---|---|---|---|
| **LabJack T4** | ✅ ✅ ✅ | ~$300 | ±10 V, 12 bit, LJM library with Python bindings. Recommended starting point |
| **LabJack T7** | ✅ ✅ ✅ | ~$500–700 | 16–24 bit, differential inputs, USB/Ethernet |
| **MCC USB-1608G / USB-1208FS-Plus** | ✅ ✅ ✅ | ~$300–800 | `uldaq` on Linux/macOS, `mcculw` on Windows (two libraries) |
| NI USB-6001/6002/6211 | ✅ ❌ ✅ | ~$300–1500 | NI-DAQmx has no macOS support |
| Arduino/Teensy + ADS1256 | ✅ ✅ ✅ | ~$50 | cheapest; needs level shifting to ±10 V and soldering |
| ADInstruments PowerLab | ✅ ✅ ❌ | $$$$ | complete commercial system with LabChart |

Prices are indicative; check current listings.

## When a board is chosen
1. Write a source class in `langrec/sources/` (see [ARCHITECTURE.md](ARCHITECTURE.md#adding-a-real-adc-board)).
2. Calibrate transducers: apply known pressures (e.g. 0 and 100 mmHg from a manometer), use the
   two-point calibration in *Channels and calibration*. The simulator has the same procedure for practice.
3. Save the channel settings as `config/<rig>.json`.
4. Verify HR and dP/dt against a signal generator or a known recording.

## Open questions for the lab
- What exactly was recorded on CH00/CH01/CH02? Is ECG, coronary flow (drop counter or flow
  meter) or temperature needed?
- Which transducers and amplifiers are in use, and what is their output voltage range?
- How is ischemia induced — a manual tap or a valve (which could set markers automatically)?
