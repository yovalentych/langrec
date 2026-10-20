# LangRec

**Recording, analysis and a training simulator for isolated-heart (Langendorff) experiments.**
Cross-platform (Windows · macOS · Linux), portable, bilingual interface (Українська / English).

![LangRec — training simulator, reperfusion after global ischemia](docs/img/simulator-light-uk.png)

LangRec started as a modern successor to **ISCHEMIA**, a DOS acquisition program written in a
physiology lab in the 1990s for a Data Translation DT2801 ISA board. It reads that program's
files, replays them as if they were live, and adds what the old program never had: on-line
haemodynamics, baseline-relative readouts, digital filters, and a virtual heart to practise on.

## Features
- **Replay of legacy ISCHEMIA recordings** (`ISCH*.DAT` + `.MRK`, format reverse-engineered —
  see [docs/DAT_FORMAT.md](docs/DAT_FORMAT.md)): files of one experiment are joined,
  1×–60× speed, seeking, original markers.
- **Training simulator** — a virtual Langendorff heart that reacts to the operator:
  global ischemia and reperfusion (contractile failure, arrest, ischemic contracture,
  reperfusion arrhythmias incl. VF, stunning, duration-dependent recovery), drugs
  (isoproterenol, propranolol, verapamil, adenosine, KCl cardioplegia, a generic
  cardioprotector), balloon volume, calibration pressures, artefacts, zero drift, 50 Hz hum,
  on-screen physiological explanations and an end-of-experiment summary.
  The default model is tuned on real ischemia–reperfusion recordings — see [docs/SIMULATOR.md](docs/SIMULATOR.md).
- **On-line haemodynamics** from LV pressure every second over the last 5 s: HR, systolic
  pressure, EDP, LVDP, ±dP/dt, rate–pressure product — and **% of baseline** for each.
- **Protocol markers** (stabilisation / ischemia / reperfusion / drug / washout, Ctrl+1…5, or
  free text), current phase and its duration in the toolbar, session trends of LVDP and HR.
- **Digital filters** per channel (Butterworth low-/high-pass, 50/60 Hz notch, median spike
  removal) for display and analysis; the **raw** signal is what gets recorded.
- **Autoscale** that does not jump with every beat; drag a Y axis for manual scale, double-click to return.
- **Recording** to plain CSV (+ JSON session description) that opens in anything.
- **Calibration**: linear V → units per channel, two-point calibration helper.
- Light and dark themes; Ukrainian and English interface, switchable on the fly.

Not yet: acquisition from a real ADC board. The interface is ready for it — see
[docs/HARDWARE.md](docs/HARDWARE.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Download and run
Portable builds for Windows, macOS and Linux are produced by GitHub Actions
(*Actions → Build → artifacts*, or the *Releases* page).

| System | Run |
|---|---|
| Windows | `LangRec.exe` in the unpacked folder |
| macOS | `LangRec.app` (first time: right-click → Open — the app is not notarised) |
| Linux | `./LangRec` in the unpacked folder |

A `portable.txt` next to the program keeps settings and sessions in `LangRec_data/` beside it.

Keyboard: **Space** start/pause · **Ctrl+1…5** protocol markers · **Ctrl+B** set baseline ·
**Ctrl+R** record · **Ctrl+Shift+F** filters.

## From source
```bash
pip install -r requirements.txt          # or: conda env with numpy scipy pyside6 pyqtgraph
python -m langrec                         # start
python -m langrec --simulator --speed 10  # straight into the simulator
python -m langrec --replay path/to/folder --autostart
python -m pytest -q                       # tests (legacy-file tests need LANGREC_ARCHIVE)
python build_app.py                       # portable build for this OS → dist/
```

## Documentation
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — how the program is organised, how to add a board
- [docs/SIMULATOR.md](docs/SIMULATOR.md) — the heart model, its data basis and limits
- [docs/DAT_FORMAT.md](docs/DAT_FORMAT.md) — the legacy ISCHEMIA file format
- [docs/HARDWARE.md](docs/HARDWARE.md) — choosing a modern ADC board
- [docs/DEVLOG.md](docs/DEVLOG.md) — development log: what was done, when and why

## Licence
MIT — see [LICENSE](LICENSE). The simulator is a teaching tool, not a validated physiological model.
