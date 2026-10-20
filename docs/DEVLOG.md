# Development log

What was done, in what order, and why. Newest entries first.

---

## 2026-10-21 — 0.2.0: training simulator, bilingual UI, desktop redesign, filters, autoscale

### Training simulator (`langrec/sim/model.py`, `langrec/sources/simulator.py`)
- Request: a simulator "to learn how to work" with the rig. The existing replay mode plays
  recordings back verbatim and cannot react to the operator, so a **generative model** was written.
- To avoid a textbook-only model, time constants were **measured from the lab's own legacy
  ischemia–reperfusion recordings** (per-minute HR / LVDP / EDP and beat shape; see docs/SIMULATOR.md).
  Rat and mouse profiles use literature values.
- Model: beat-by-beat waveform generation (vectorised per beat — one hour of experiment is
  generated in ~1 s), slow state updated per beat: function, contracture, drug concentrations,
  perfusion pressure, flow, reperfusion arrhythmia risk, preconditioning, transducer artefacts.
- Validation runs (seed 1, lab profile), LVDP recovery after 40 min reperfusion:
  5 min ischemia 94 %, 10 min 82 %, 20 min 26 %, 30 min 15 %; 20 min with cardioprotector 92 %;
  contracture onset ≈ 10 min. Consistent with the recordings (≈100 % / 25 % / 35 % at 9 / 17 / 30 min).
- **Bugs found while validating**:
  - VT never ended: the remaining-duration counter was decremented only for VF. Fixed; HR after
    reperfusion went from a stuck ~390 bpm back to baseline.
  - The cardioprotector "did nothing" when switched on together with ischemia — correct
    physiology (no flow, no delivery), so the test and docs now give it 10 min before ischemia.
- The analyser's refractory period was lowered from 0.15 s to 0.09 s: mouse hearts (400–600 bpm)
  were counted at half rate.
- Teaching aids: on-screen explanations of the current physiology, simulator events as
  markers (◆), an end-of-experiment summary revealing the heart's hidden properties,
  calibration pressures 0/100 mmHg and an *uncalibrated* start to practise two-point calibration.

### Bilingual interface (`langrec/i18n.py`)
- Request: English in addition to Ukrainian; documentation in English only.
- All visible text goes through `tr(key)`; Ukrainian and English dictionaries have identical keys
  (checked). The language switches **without restart**: the window rebuilds its widgets from
  state kept on the window object. Rebuilding is deferred with `QTimer.singleShot(0)` because it
  is triggered from a menu action that the rebuild deletes.
- Markers store translation keys, so existing markers are re-labelled on a language switch.
- Code comments and docs were translated to English; the Ukrainian docs were replaced.
- Fix: `&` in English labels ("Protocol & markers") is a Qt mnemonic and disappeared — rephrased.

### Desktop redesign
- Feedback: the interface looked "too HTML-like". Rebuilt as a desktop instrument: menu bar,
  toolbar, **dockable panels** (movable / closable / floatable), flat readouts with tabular digits,
  4 px radii, the system UI font, an explicit **QPalette** per theme (the style sheet alone left
  scroll-area viewports light in the dark theme — text was unreadable).
- Layout iterations from screenshots: four stacked docks were cramped and clipped controls →
  set-up panels are now tabbed (Source / Recording / Channels) above *Protocol*, and the *Virtual
  rig* sits on the right and only appears in simulator mode. A stacked widget reserved the height
  of its tallest page → hidden pages now get an `Ignored` size policy. Long labels were shortened
  and given tooltips.

### Autoscale and typography (`langrec/gui/plots.py`)
- Per-channel autoscale expands at once and shrinks slowly, so the axis does not jump each beat.
  Dragging/zooming a Y axis switches that plot to manual (shown in its title); double-click returns to auto.
- Marker labels: first they were crossed by other markers' lines and overlapped each other.
  Now labels are separate text items above all lines, with an opaque background, laid out in
  **pixel space**: each label goes to the highest free row, hidden if none is free (the full
  text remains in the marker list and tooltip). A first version used 20 px rows for 23 px
  labels — measured, fixed by taking the row height from the label itself.
- Trend x-axis showed "min (x0.001)" — pyqtgraph's SI prefix was disabled on that axis too.

### Digital filters (`langrec/analysis/filters.py`)
- Per channel: median spike removal → 50/60 Hz notch → Butterworth high-pass (2nd order) →
  Butterworth low-pass (4th order); `scipy.signal.sosfilt` with carried state, so block-wise
  output equals whole-signal output (tested). Causal, like an analogue filter.
- Decision: filters apply to **display and analysis only**; the **raw** signal is recorded and the
  filter settings are stored in `session.json`. Filtered data can always be recomputed; raw cannot.
- SciPy added as a dependency (+ ~50 MB in the bundle) for standard, well-tested filter designs.

### Other
- Recorder switched from per-value Python formatting to `numpy.savetxt`: ~580 000 rows/s,
  enough for 1 kHz × many channels at 60× replay.
- Tests no longer touch the real user settings (`LANGREC_SETTINGS` → temporary file) and no
  longer depend on particular legacy files (any folder via `LANGREC_ARCHIVE`). 26 tests.
- Default sessions folder renamed to `LangRec_sessions` (ASCII path, safer on Windows).

---

## 2026-10-21 — 0.1.0: replay mode, first interface, portable builds

### Background
- 2026-10-20: an archive was made from the IDE disk of an old lab PC (Windows 98). It contained
  ISCHEMIA, a DOS acquisition program for isolated hearts written by a colleague in the lab for a
  DT2801 ISA board — unusable on current computers.
- The file format was reverse-engineered (docs/DAT_FORMAT.md) and all 121 recordings converted to CSV.
- Decision: rewrite the program for current Windows / macOS / Linux. With no board chosen yet,
  start with **replay of the legacy recordings** as if they were live, so that everything except
  the driver can be built and tested now.

### Stack
Python 3.12, PySide6 (Qt 6), pyqtgraph, numpy; PyInstaller for builds.

### Done
1. `io/ischemia_dat.py` — DAT/MRK reader (numpy, dataclasses, files sorted by header time).
2. `channels.py` — channel roles and linear calibration; legacy defaults CH00 = LV pressure,
   CH01 = perfusion pressure, CH02 = dP/dt (inferred from waveforms).
3. `sources/base.py` — the `DataSource` pull interface for replay and future boards.
4. `sources/replay.py` — joined files, real-time × speed, pause, seek, file and marker events.
   *Bug found in review:* samples accrued but not yet read were lost on pause; fixed and tested.
5. `analysis/hemodynamics.py` — HR, Psys, EDP, LVDP, ±dP/dt, RPP; validated on a synthetic
   curve with a known answer (1–3 %) and on real data (~150 bpm). 100 Hz clips dP/dt.
6. `recorder.py` — session folder with signals, markers, parameters and a JSON description.
7. GUI — live channels, protocol markers, phase timer, baseline with % readouts (auto at
   *Ischemia*), trends, light/dark themes. Fixes from screenshots: readouts did not fit the side
   panel (moved above the plots); "×0.001" axis prefixes (disabled).
8. Portable builds — `paths.py` (`portable.txt` → settings and sessions beside the program),
   `build_app.py`. *Bugs:* on Windows/Linux `portable.txt` landed one level above the exe (fixed);
   the macOS zip was 307 MB for a 176 MB folder because `shutil.make_archive` follows the symlinks
   inside `.app` — now packed with `ditto` (67 MB). GitHub Actions builds Windows and Linux.

---

## Open questions
- Confirm with the lab what the three legacy channels are, and the transducer calibration.
- ADC board choice → docs/HARDWARE.md.
- macOS builds are not notarised: first launch via right-click → Open.

## Ideas
- Source for a real board (LabJack / MCC) once chosen.
- Experiment report: parameters per protocol phase (mean of the last N min of each phase).
- Markers from a board's digital input (ischemia valve).
- Opening recorded LangRec sessions for review.
- Guided simulator scenarios with step-by-step tasks and scoring.
