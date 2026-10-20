# Legacy ISCHEMIA file format (ISCHnnnn.DAT / .MRK)

Reverse-engineered from 121 recordings made in 2010–2019; there is no official documentation.
Implementation: `langrec/io/ischemia_dat.py`.

## Background
- ISCHEMIA: a DOS program (Borland C++, 1991 runtime) built on the **STEMMER SWG "TL 4.0"**
  library for a **Data Translation DT2801** board (12 bit, ±10.24 V).
- Recordings are written to `C:\FILES\ISCHnnnn.DAT`; markers to `ISCHnnnn.MRK`.

## Header
| Offset | Content |
|---|---|
| 0x00 | `SWGBSMBWS\0` — signature |
| 0x34 | `TL 4.0` |
| 0x4C | `Sampled Data File` |
| 0x66 | date: uint16 year, uint8 day, uint8 month (Borland `struct date`) |
| 0x6A | time: minutes, hours, hundredths, seconds (Borland `struct time`) |
| 0x6E… | tagged 16-byte records (below) |

Record: `uint16 tag, uint16 idx, uint16 type, uint16 len` + 8 value bytes.
If `len > 8` (e.g. a long comment) the value follows **after** the 16 bytes (padded to even).
A record with `tag = 0xFFFF` closes a section and is always 16 bytes.

Types: `2` — string (CP866), `8` — integer (uint16/uint32), `14` — 6-byte number:
`int32 mantissa / 2^31 × 2^(int16 exponent)`.

| tag | Meaning |
|---|---|
| 0x0002 | comment typed by the operator |
| 0x8005 idx=0 | global section: 0x8A — **sampling rate per channel, Hz** (100); 0x89 — 5.184 (unknown) |
| 0x8005 idx=k | channel k: 0x0001 — name (`CH00`…); idx=1: 0x82 scale (0.005), 0x83 offset (−10.24); idx=2: user calibration (1.0 / 0.0, `Volt`); 0x85/0x86 — display limits ±10.24 |
| 0x8003 | ADC section: 0x98 = 6; 0xA0 — ADC input number (0, 2, 4) |
| 0x7FED | opaque block (306–312 bytes) |
| 0x8004 | start of data — samples follow this record (at 0x600 in every known file) |
| 0xC0 | (in MRK) a marker: uint32 sample index |

## Data
- int16 little-endian, values 0…4095 (12 bit), **channels interleaved** (CH00, CH01, CH02, CH00 …).
- Volts = raw × 0.005 − 10.24.
- Every known file: **3 channels at 100 Hz per channel**. A full file holds 120 000 samples (20 min);
  later recordings used 10-minute files.
- 100 Hz was confirmed twice: from the start times of consecutive files of one experiment
  (~20 min apart) and from a physiological heart rate in the signal.

## Channel meaning (inferred, not stored in the files)
From the waveforms:
- **CH00** (input 0) — left-ventricular pressure (systole/diastole; diastolic pressure rises during ischemia — contracture);
- **CH01** (input 2) — a nearly constant level with small pulsation, most likely perfusion pressure;
- **CH02** (input 4) — a biphasic curve matching the derivative of CH00, i.e. a hardware dP/dt.

The transducer calibration (mmHg per volt) is **not** stored.
