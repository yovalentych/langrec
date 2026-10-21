"""GUI checks without a screen (QT_QPA_PLATFORM=offscreen)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from test_core import SESSION, need_archive


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_window_opens_without_data(app):
    from langrec.gui.main_window import MainWindow
    w = MainWindow()
    w._set_theme("dark")
    w._rebuild_all()
    w.set_ui_language("en")
    w._rebuild_all()
    assert w.status_lamp.text() == "NO DATA"
    w.set_ui_language("uk")
    w._rebuild_all()
    assert w.status_lamp.text() == "НЕМАЄ ДАНИХ"
    w.close()


@need_archive
def test_replay_record_markers(app, tmp_path):
    from langrec.gui.main_window import MainWindow
    from langrec.sources.replay import ReplaySource

    w = MainWindow()
    t = [0.0]
    from langrec.io.ischemia_dat import find_recordings
    f = [p for p in find_recordings(SESSION) if p.stat().st_size > 700_000][0]
    w.load_files([f])
    # fake clock: advance time without waiting
    w.source = ReplaySource([f], speed=1, clock=lambda: t[0])
    w.rec_dir_edit.setText(str(tmp_path))
    w._start()
    w.b_rec.setChecked(True)
    for _ in range(40):          # 40 s of signal
        t[0] += 1.0
        w._tick()
    assert w.last_params is not None
    if w.last_params.lvdp is None:          # this file starts without beats: set one by hand
        from langrec.analysis.hemodynamics import HemoParams
        w.last_params = HemoParams(hr=150, lvdp=2.0, edp=0.1, sys=2.1)
    w.add_preset("isch")         # must set the baseline automatically
    assert w.baseline is not None
    t[0] += 1.0
    w._tick()
    w.b_rec.setChecked(False)
    session = next(tmp_path.iterdir())
    markers = (session / "markers.csv").read_text(encoding="utf-8")
    assert "Ішемія" in markers and "Базова лінія" in markers   # default UI language: uk
    assert len((session / "signals.csv").read_text().splitlines()) > 3900
    w.close()


def test_simulator_session_with_filters(app, tmp_path):
    from langrec.analysis.filters import FilterBank, FilterConfig
    from langrec.gui.main_window import MainWindow
    from langrec.sources.simulator import SimulatorSource

    w = MainWindow()
    w.seed_edit.setText("7")
    w._start_simulator()
    t = [0.0]
    w.source = SimulatorSource("lab", rate=500, seed=7, speed=1, clock=lambda: t[0])
    w.source.start()
    w._sync_widgets()
    assert w.rig_dock.isVisibleTo(w)
    w.rec_dir_edit.setText(str(tmp_path))
    w.b_rec.setChecked(True)
    w.filter_cfgs = [FilterConfig(lowpass_hz=30), FilterConfig(), FilterConfig(), FilterConfig(notch_hz=50)]
    w.bank = FilterBank(w.filter_cfgs, w.rate)
    w.sim.model.hum = True
    for _ in range(30):
        t[0] += 1.0
        w._tick()
    assert w.last_params.hr > 100 and w.last_params.lvdp > 40
    w._drug_toggled("iso", True)
    w._toggle_perfusion()                       # ischemia
    assert not w.sim.model.perfused and w.baseline is not None
    for _ in range(10):
        t[0] += 1.0
        w._tick()
    w._toggle_perfusion()                       # reperfusion
    w.b_rec.setChecked(False)
    session = next(tmp_path.iterdir())
    markers = (session / "markers.csv").read_text(encoding="utf-8")
    assert "Ішемія" in markers and "Реперфузія" in markers and "Ізопротеренол" in markers
    assert "display_filters" in (session / "session.json").read_text(encoding="utf-8")
    w._show_summary = lambda: None
    w.close()


def test_arduino_source_in_gui(app, tmp_path):
    from test_arduino import FakeSerial
    from langrec.gui.main_window import MainWindow
    from langrec.sources.arduino import ArduinoSource
    import time

    w = MainWindow()
    w._set_src_mode("arduino")
    assert w.src_stack.currentIndex() == 2
    fake = FakeSerial()
    src = ArduinoSource("fake", serial_factory=lambda: fake)
    src.start()
    from langrec.channels import arduino_channels
    w.channels = arduino_channels()
    w._set_source(src)
    w._start()
    for _ in range(20):
        time.sleep(0.05)
        w._tick()
    assert w.n > 300 and w.status_lamp.text() in ("НАЖИВО", "LIVE")
    w.close()
    assert fake.closed
