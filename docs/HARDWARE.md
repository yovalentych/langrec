# Choosing a modern ADC board

No decision yet (as of October 2026, not urgent). This page collects requirements and options
so that nothing is forgotten when the time comes.

## What an ADC / DAQ does
A Langendorff rig produces **analogue voltages**: a pressure transducer connected to the LV
balloon (or to the perfusion line) gives a few millivolts, a bridge amplifier scales that to a
few volts, and so on for flow meters and ECG amplifiers. A computer cannot read a voltage
directly — an **analogue-to-digital converter (ADC)** measures it at fixed intervals
(the *sampling rate*) with a given precision (the *resolution*, in bits) and hands the numbers
to the software. A **data-acquisition device (DAQ)** is an ADC with several inputs, a clock and
a USB (or Ethernet) interface in one box.

The old setup used a DT2801-compatible ISA card inside the PC: 12 bit, ±10.24 V, 3 channels at
100 Hz — see [LEGACY_BOARD.md](LEGACY_BOARD.md) for what it was and why its cable is worth keeping.
Today the equivalent is an external USB DAQ that works with any laptop.

```
transducer ─► amplifier (±10 V) ─► DAQ input ─┐
transducer ─► amplifier (±10 V) ─► DAQ input ─┼─► USB ─► LangRec
ECG / flow amplifier ─────────────► DAQ input ─┘
```

Terms worth knowing when comparing devices:
- **Input range** — the voltage span an input accepts (±10 V here). A smaller range on a larger
  signal clips it; a much larger range wastes resolution.
- **Resolution** — 12 bit splits ±10 V into 4096 steps (≈5 mV), 16 bit into 65 536 (≈0.3 mV).
- **Sampling rate** — per channel. Some devices quote the *total* rate shared by all channels.
- **Single-ended vs differential** — single-ended inputs measure against a common ground;
  differential inputs measure the difference between two wires and reject interference
  (e.g. 50 Hz mains hum) much better. Prefer differential for small or long-cabled signals.
- **Isolation** — not required for an isolated heart, but matters if the same device is ever
  used with live animals.
- **Drivers / API** — what operating systems and programming languages the vendor supports.

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

## Availability in Ukraine (checked October 2026)
Stock and prices change — confirm with the seller before ordering.

| Device | Where | Notes |
|---|---|---|
| Advantech USB-4704 / USB-4702 | Proxis (proxis.ua), Kyiv | ±10 V; 4704: 14 bit, 48 kS/s total; 4702: 12 bit, 10 kS/s, ~6 500 UAH. Drivers: Windows, Linux — **no macOS** |
| NI USB-6009 | MOMM (momm.com.ua) | ±10 V, 14 bit, 48 kS/s total. NI-DAQmx: Windows, Linux — **no macOS** |
| Digilent Analog Discovery 3 | RKS Components / Radiomag (rcscomponents.kiev.ua), to order 14–30 days | only **2** analogue inputs (±25 V, 14 bit); Windows, macOS, Linux SDK — enough for LVP + perfusion pressure |
| ICP DAS USB-2019 | Holit Data Systems (icpdas.com.ua), official ICP DAS distributor | universal slow input for temperature/thermocouples — **not suitable** for pressure waveforms |
| LabJack T7 / T4 | no Ukrainian dealer found | order from the EU, e.g. PIMZOS (Poland, ~€550 for T7), or from labjack.com; add shipping and import VAT |
| MCC USB-1608G | no Ukrainian dealer found | Digilent/MCC require an export form outside the US; some countries are excluded |
| ADC breakout boards (ADS1015/ADS1115…) | arduino.ua, Kosmodrom | DIY only: need level shifting to ±10 V and firmware |

Do **not** buy L-Card or other Russian-made devices (imports from Russia are prohibited, and
spare parts, drivers and support are unavailable).

Practical choice: **LabJack T7 from an EU seller** if macOS/Linux matter; a locally available
**Advantech USB-4704** or **NI USB-6009** if the rig computer will run Windows.

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
