# Architecture

```
langrec/
  __main__.py              entry point and command-line options
  i18n.py                  interface strings (uk, en) and tr()
  paths.py                 normal vs portable mode: where settings and sessions live
  channels.py              ChannelConfig: name, role, units, linear calibration
  recorder.py              SessionRecorder: CSV + session.json
  io/ischemia_dat.py       reader for legacy ISCH*.DAT / .MRK
  sources/base.py          DataSource — the interface every signal source implements
  sources/replay.py        ReplaySource — legacy recordings played back in real time
  sources/simulator.py     SimulatorSource — the training heart as a source
  sim/model.py             HeartModel — the virtual heart
  analysis/hemodynamics.py HR, LVDP, EDP, ±dP/dt from LV pressure
  analysis/filters.py      streaming digital filters (scipy.signal, stateful sosfilt)
  gui/main_window.py       main window: menus, toolbar, docks, the acquisition loop
  gui/plots.py             SignalView: channel plots, autoscale, markers, trends
  gui/channels_dialog.py   channel settings and two-point calibration
  gui/filters_dialog.py    filter settings
  gui/theme.py             light / dark themes (palette + style sheet)
  gui/icon.py              application icon drawn in code
tests/                     pytest; GUI tests run off-screen
build_app.py               PyInstaller portable build
.github/workflows/build.yml  tests + builds for Windows, macOS, Linux
```

## Data flow
```
DataSource.read()  ─►  raw buffer (volts, last 120 s) ──────────────► recorder (calibrated, raw)
  (~30×/s)             │
                       └► FilterBank (stateful) ─► filtered buffer ─► plots
                                                         │
                                                         └► every 1 s: hemodynamics.compute(last 5 s of LVP)
                                                              ─► readouts, trends, parameters.csv
```
- Signals are kept in **volts**; calibration (`ChannelConfig.to_units`) is applied when
  displaying, analysing and recording, so changing calibration never corrupts the buffer.
- Filters affect display and analysis only. The recorder always writes unfiltered data and
  stores the filter settings in `session.json` (`display_filters`).
- Markers are kept as dictionaries with a translation key where possible, so switching the
  interface language re-labels existing markers.

## Adding a real ADC board
1. Create `langrec/sources/<board>.py` with a `DataSource` subclass:
   - `rate`, `channel_names`;
   - `start()` starts streaming (in the driver's callback or a thread) into a thread-safe buffer;
   - `read()` returns `(ndarray (n, n_channels) in volts, [SourceEvent ...])` with everything
     accumulated so far and never blocks;
   - `stop()`.
2. Offer it in the *Signal source* panel (`MainWindow._build_source_panel`).
3. Nothing else changes: plots, analysis, filters, markers and recording are source-agnostic.

Why pull rather than Qt signals from a thread: it is trivial to test with a fake clock
(see `tests/test_core.py::test_replay_clock_pause_and_events`), and the GUI decides how often to redraw.

## Design decisions
- **PySide6 + pyqtgraph**: Qt looks and behaves the same on all three systems (Fusion style plus
  an explicit palette); pyqtgraph draws tens of thousands of points per frame — matplotlib cannot.
- **CSV**: universally readable. At 500 Hz–1 kHz it is more than adequate; HDF5 can be added
  for long multi-kHz recordings.
- **scipy.signal** for filters: standard Butterworth / notch designs with state carried across
  blocks, so block-wise filtering equals filtering the whole signal (tested).
- **Simple peak detector** (numpy only) — predictable and fast.
- **Desktop-instrument UI**: menus, a toolbar, dockable panels, flat readouts with tabular
  digits; marker labels are laid out in pixel space so they never overlap.
- **Language switch without restart**: the UI is rebuilt from state kept on the window object.
