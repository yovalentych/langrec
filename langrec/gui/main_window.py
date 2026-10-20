"""LangRec main window — a desktop instrument layout.

  menu bar   File · Signal · View · Help
  tool bar   ▶ ⏮ · speed · ● Record · ⇕ Auto · ƒ Filters ·········· status · phase · clock
  left docks Signal source · Virtual rig (simulator only) · Protocol & markers ·
             Recording / Channels (tabbed)            — movable, closable, floatable
  centre     parameter readouts · channel plots / trends (splitter) · timeline

Loop: a QTimer calls _tick() ~30 times per second, which
  1) takes new samples from the source (DataSource.read),
  2) stores raw volts (recorded) and filtered volts (displayed, analysed),
  3) every second of signal computes parameters over the last 5 s,
  4) refreshes plots, readouts and trends.

All visible text goes through i18n.tr(). Changing the language rebuilds menus, toolbar,
docks and the centre (_build_ui); everything that must survive lives on `self`.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, replace
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QCheckBox,
                               QComboBox, QDockWidget, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QStackedWidget, QToolBar, QToolButton, QVBoxLayout,
                               QWidget)

from .. import __version__
from ..analysis.filters import FilterBank, FilterConfig
from ..analysis.hemodynamics import HemoParams, compute
from ..channels import LEGACY_DEFAULT, ChannelConfig, simulator_channels
from ..i18n import LANGUAGES, language, set_language, tr
from ..io.ischemia_dat import find_recordings, parse_header
from ..paths import default_sessions_dir, is_portable, make_settings
from ..recorder import SessionRecorder
from ..sim.model import DRUGS, PROFILES
from ..sources.base import DataSource
from ..sources.replay import ReplaySource
from ..sources.simulator import SimulatorSource
from .channels_dialog import ChannelsDialog
from .filters_dialog import FiltersDialog
from .icon import make_icon
from .plots import SignalView
from .theme import THEMES, Theme, apply_palette, stylesheet

BUFFER_S = 120          # seconds of signal kept for display
ANALYSIS_STEP_S = 1.0   # how often parameters are computed (seconds of signal)
ANALYSIS_WIN_S = 5.0    # analysis window
SIM_RATE = 500.0        # simulator sampling rate, Hz (what a modern board would use)
DOCK_WIDTH = 320

PRESETS = [("stab", "success"), ("isch", "danger"), ("reperf", "accent"),
           ("drug", "violet"), ("wash", "warn")]
TILES = [("hr", "pct", 0), ("sys", "pct", 1), ("edp", "abs", 1), ("lvdp", "pct", 1),
         ("dpdt_max", "pct", 0), ("dpdt_min", "pct", 0), ("rpp", "pct", 0)]
SPEEDS = (1, 2, 5, 10, 30, 60)
WINDOWS = (5, 10, 30, 60, 120)


def fmt_time(s: float) -> str:
    s = max(0, int(s))
    h, m, sec = s // 3600, s // 60 % 60, s % 60
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}"


def fmt_num(v, digits=1):
    if v is None:
        return "—"
    if abs(v) >= 1000:
        return f"{v:,.0f}".replace(",", " ")
    return f"{v:.{digits}f}"


def section(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


def hint_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("hint")
    lab.setWordWrap(True)
    return lab


class Tile(QFrame):
    """Readout of one parameter: short title, value, units, change vs baseline."""

    def __init__(self, key: str):
        super().__init__()
        self.setObjectName("tile")
        self.setToolTip(tr(f"tiletip.{key}"))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(104)
        g = QGridLayout(self)
        g.setContentsMargins(10, 6, 10, 6)
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(0)
        self.title = QLabel(tr(f"tile.{key}"))
        self.title.setObjectName("tileTitle")
        self.delta = QLabel("")
        self.delta.setObjectName("tileDelta")
        self.delta.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.delta.setToolTip(tr("tiletip.delta"))
        self.value = QLabel("—")
        self.value.setObjectName("tileValue")
        self.unit = QLabel("")
        self.unit.setObjectName("tileUnit")
        g.addWidget(self.title, 0, 0)
        g.addWidget(self.delta, 0, 1)
        g.addWidget(self.value, 1, 0, 1, 2)
        g.addWidget(self.unit, 2, 0, 1, 2)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowIcon(make_icon())
        self.resize(1500, 960)
        self.setDockOptions(QMainWindow.AnimatedDocks | QMainWindow.AllowTabbedDocks)
        self.settings = make_settings()
        set_language(self.settings.value("language", "uk"))
        self.theme: Theme = THEMES.get(self.settings.value("theme", "light"), THEMES["light"])

        # --- state that survives a UI rebuild
        self.source: DataSource | None = None
        self.channels: list[ChannelConfig] = self._load_channel_settings()
        self.filter_cfgs: list[FilterConfig] = [FilterConfig() for _ in self.channels]
        self.filters_on = True
        self.autoscale = True
        self.recorder: SessionRecorder | None = None
        self.running = False
        self.speed = 1
        self.baseline: HemoParams | None = None
        self.base_info: tuple[str, dict] = ("base.none", {})
        self.last_params: HemoParams | None = None
        self.src_mode = self.settings.value("src_mode", "replay")
        self.files: list[tuple[str, str, bool]] = []      # (path, text, selected)
        self.sim_profile = "lab"
        self.sim_hints = True
        self.sim_uncal = False
        self.auto_markers = True
        self.rec_title = ""
        self.rec_dir = self.settings.value("rec_dir", str(default_sessions_dir()))
        self.rec_info: tuple[str, dict] = ("rec.info", {})
        self.window_idx = 1
        self._explain_tick = 0
        self._last_draw = 0.0
        self._draw_interval = 0.05   # adapted to how long drawing takes on this computer
        self._docks: list[QDockWidget] = []
        self._toolbar: QToolBar | None = None

        self._make_bank()
        self._reset_buffers(0)
        self._build_ui()
        self._make_shortcuts()

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._tick)

    # ================================================================ state
    def _make_bank(self):
        while len(self.filter_cfgs) < len(self.channels):
            self.filter_cfgs.append(FilterConfig())
        self.filter_cfgs = self.filter_cfgs[:len(self.channels)]
        self.bank = FilterBank(self.filter_cfgs, self.rate)

    def _reset_buffers(self, start_sample: int):
        nch = len(self.channels)
        self.buf = np.zeros((0, nch), dtype=np.float32)    # raw volts
        self.fbuf = np.zeros((0, nch), dtype=np.float32)   # filtered volts
        self.n = start_sample
        self.next_analysis = start_sample
        self.markers: list[dict] = []
        self.phase: dict | None = None
        self.trend_t: list[float] = []
        self.trend_lvdp: list[float] = []
        self.trend_hr: list[float] = []
        self._make_bank()

    @property
    def rate(self) -> float:
        return self.source.rate if self.source else 100.0

    @property
    def sim(self) -> SimulatorSource | None:
        return self.source if isinstance(self.source, SimulatorSource) else None

    @property
    def view_buf(self) -> np.ndarray:
        return self.fbuf if (self.filters_on and self.bank.active) else self.buf

    def _lvp_index(self) -> int | None:
        return next((i for i, c in enumerate(self.channels) if c.role == "lvp"), None)

    def _color(self, key: str) -> str:
        if key == "violet":
            return self.theme.channels[4]
        return getattr(self.theme, key, self.theme.accent)

    # ============================================================ building
    def _build_ui(self):
        """(Re)build every widget from the state on self."""
        app = QApplication.instance()
        apply_palette(app, self.theme)
        app.setStyleSheet(stylesheet(self.theme))
        self.setWindowTitle("LangRec — " + tr("app.subtitle"))
        for d in self._docks:
            self.removeDockWidget(d)
            d.deleteLater()
        self._docks = []
        if self._toolbar:
            self.removeToolBar(self._toolbar)
            self._toolbar.deleteLater()
        self.menuBar().clear()

        self._build_toolbar()
        self._build_central()
        self._build_docks()
        self._build_menus()
        mode = tr("status.portable") if is_portable() else ""
        self.statusBar().showMessage(mode + tr("status.start"))
        self._rebuild_plots()
        self._sync_widgets()
        self._update_tiles()

    def _build_menus(self):
        mb = self.menuBar()
        m = mb.addMenu(tr("menu.file"))
        a = m.addAction(tr("act.open"), self._open_folder)
        a.setShortcut(QKeySequence.Open)
        a = m.addAction(tr("act.sim"), self._start_simulator_default)
        a.setShortcut(QKeySequence("Ctrl+Shift+N"))
        m.addSeparator()
        self.act_record = m.addAction(tr("act.record"))
        self.act_record.setCheckable(True)
        self.act_record.setShortcut(QKeySequence("Ctrl+R"))
        self.act_record.toggled.connect(lambda on: self.b_rec.setChecked(on))
        m.addSeparator()
        a = m.addAction(tr("act.quit"), self.close)
        a.setShortcut(QKeySequence.Quit)

        m = mb.addMenu(tr("menu.signal"))
        m.addAction(tr("act.channels"), self._edit_channels)
        a = m.addAction(tr("act.filters"), self._edit_filters)
        a.setShortcut(QKeySequence("Ctrl+Shift+F"))
        self.act_filters_on = m.addAction(tr("act.filters_on"))
        self.act_filters_on.setCheckable(True)
        self.act_filters_on.setChecked(self.filters_on)
        self.act_filters_on.toggled.connect(self._set_filters_on)
        self.act_autoscale = m.addAction(tr("act.autoscale"))
        self.act_autoscale.setCheckable(True)
        self.act_autoscale.setChecked(self.autoscale)
        self.act_autoscale.toggled.connect(self._set_autoscale)
        m.addSeparator()
        a = m.addAction(tr("act.baseline"), lambda: self._set_baseline(manual=True))
        a.setShortcut(QKeySequence("Ctrl+B"))

        m = mb.addMenu(tr("menu.view"))
        lm = m.addMenu(tr("menu.lang"))
        grp = QActionGroup(self)
        for code, name in (("uk", "Українська"), ("en", "English")):
            a = lm.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == language())
            a.triggered.connect(lambda _=False, c=code: self.set_ui_language(c))
            grp.addAction(a)
        a = m.addAction(tr("act.dark"))
        a.setCheckable(True)
        a.setChecked(self.theme.name == "dark")
        a.toggled.connect(lambda on: self._set_theme("dark" if on else "light"))
        pm = m.addMenu(tr("menu.panels"))
        for d in self._docks:
            pm.addAction(d.toggleViewAction())

        m = mb.addMenu(tr("menu.help"))
        m.addAction(tr("act.about"), lambda: QMessageBox.about(
            self, "LangRec", tr("about.text", ver=__version__)))

    def _build_toolbar(self):
        tb = QToolBar()
        tb.setMovable(False)
        tb.setIconSize(QSize(16, 16))
        self.addToolBar(Qt.TopToolBarArea, tb)
        self._toolbar = tb

        self.b_play = QToolButton()
        self.b_play.setObjectName("play")
        self.b_play.setToolTip(tr("tip.play"))
        self.b_play.clicked.connect(self._toggle_play)
        tb.addWidget(self.b_play)
        self.b_rewind = QToolButton()
        self.b_rewind.setText("⏮")
        self.b_rewind.setToolTip(tr("tip.rewind"))
        self.b_rewind.clicked.connect(lambda: self._seek_to(0))
        tb.addWidget(self.b_rewind)
        tb.addSeparator()
        tb.addWidget(QLabel(tr("tool.speed")))
        self.speed_box = QComboBox()
        for s in SPEEDS:
            self.speed_box.addItem(f"{s}×", s)
        self.speed_box.setCurrentIndex(SPEEDS.index(self.speed))
        self.speed_box.currentIndexChanged.connect(lambda i: self.set_speed(SPEEDS[i]))
        tb.addWidget(self.speed_box)
        tb.addSeparator()
        self.b_rec = QToolButton()
        self.b_rec.setObjectName("record")
        self.b_rec.setCheckable(True)
        self.b_rec.setToolTip(tr("tip.rec"))
        self.b_rec.toggled.connect(self._toggle_record)
        tb.addWidget(self.b_rec)
        tb.addSeparator()
        self.b_auto = QToolButton()
        self.b_auto.setText(tr("tool.autoscale"))
        self.b_auto.setCheckable(True)
        self.b_auto.setChecked(self.autoscale)
        self.b_auto.setToolTip(tr("tip.autoscale"))
        self.b_auto.toggled.connect(self._set_autoscale)
        tb.addWidget(self.b_auto)
        self.b_filt = QToolButton()
        self.b_filt.setText(tr("tool.filters"))
        self.b_filt.setCheckable(True)
        self.b_filt.setChecked(self.filters_on)
        self.b_filt.setToolTip(tr("tip.filters"))
        self.b_filt.toggled.connect(self._set_filters_on)
        tb.addWidget(self.b_filt)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        tb.addWidget(spacer)

        self.status_lamp = QLabel()
        self.status_lamp.setObjectName("status")
        tb.addWidget(self.status_lamp)
        ph = QWidget()
        pl = QVBoxLayout(ph)
        pl.setContentsMargins(8, 0, 8, 0)
        pl.setSpacing(0)
        self.phase_label = QLabel()
        self.phase_label.setObjectName("phase")
        self.phase_time = QLabel()
        self.phase_time.setObjectName("phaseTime")
        pl.addWidget(self.phase_label)
        pl.addWidget(self.phase_time)
        ph.setMinimumWidth(170)
        tb.addWidget(ph)
        self.clock = QLabel("00:00")
        self.clock.setObjectName("clock")
        self.clock.setToolTip(tr("tip.clock"))
        tb.addWidget(self.clock)

    def _build_central(self):
        c = QWidget()
        lay = QVBoxLayout(c)
        lay.setContentsMargins(8, 8, 8, 6)
        lay.setSpacing(8)
        tiles = QHBoxLayout()
        tiles.setSpacing(6)
        self.tiles: dict[str, Tile] = {}
        for key, _, _ in TILES:
            t = Tile(key)
            self.tiles[key] = t
            tiles.addWidget(t)
        lay.addLayout(tiles)

        frame = QFrame()
        frame.setObjectName("plotFrame")
        fl = QVBoxLayout(frame)
        fl.setContentsMargins(2, 2, 2, 2)
        self.view = SignalView(self.theme)
        self.view.autoscale = self.autoscale
        fl.addWidget(self.view)
        lay.addWidget(frame, 1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.pos_label = QLabel("00:00")
        self.pos_label.setObjectName("mono")
        row.addWidget(self.pos_label)
        self.pos_slider = QSlider(Qt.Horizontal)
        self.pos_slider.sliderReleased.connect(lambda: self._seek_to(self.pos_slider.value()))
        row.addWidget(self.pos_slider, 1)
        self.total_label = QLabel("")
        self.total_label.setObjectName("mono")
        row.addWidget(self.total_label)
        row.addSpacing(10)
        row.addWidget(QLabel(tr("timeline.window")))
        self.window_s = QComboBox()
        for s in WINDOWS:
            self.window_s.addItem(tr("unit.s", s=s), s)
        self.window_s.setCurrentIndex(self.window_idx)
        self.window_s.currentIndexChanged.connect(self._window_changed)
        row.addWidget(self.window_s)
        lay.addLayout(row)
        self.setCentralWidget(c)

    def _dock(self, key: str, content: QWidget, area=Qt.LeftDockWidgetArea) -> QDockWidget:
        d = QDockWidget(tr(key), self)
        d.setObjectName(key)
        d.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetClosable |
                      QDockWidget.DockWidgetFloatable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content.setMinimumWidth(DOCK_WIDTH - 24)
        scroll.setWidget(content)
        d.setWidget(scroll)
        d.setMinimumWidth(DOCK_WIDTH)
        self.addDockWidget(area, d)
        self._docks.append(d)
        return d

    @staticmethod
    def _panel() -> tuple[QWidget, QVBoxLayout]:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(10, 10, 10, 10)
        lay.setSpacing(7)
        return w, lay

    def _build_docks(self):
        # left: set-up (source / recording / channels, tabbed) above the protocol;
        # right: the virtual rig, only while the simulator runs
        src = self._dock("dock.source", self._build_source_panel())
        rec = self._dock("dock.record", self._build_record_panel())
        ch = self._dock("dock.channels", self._build_channels_panel())
        self.tabifyDockWidget(src, rec)
        self.tabifyDockWidget(rec, ch)
        src.raise_()
        prot = self._dock("dock.protocol", self._build_protocol_panel())
        self.rig_dock = self._dock("dock.rig", self._build_rig_panel(), Qt.RightDockWidgetArea)
        self.resizeDocks([src, prot], [340, 560], Qt.Vertical)

    # ---------------------------------------------------------------- panels
    def _build_source_panel(self) -> QWidget:
        w, lay = self._panel()
        tabs = QHBoxLayout()
        tabs.setSpacing(0)
        self.mode_group = QButtonGroup(self)
        for mode, key in (("replay", "src.tab_replay"), ("sim", "src.tab_sim")):
            b = QPushButton(tr(key))
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setProperty("mode", mode)
            b.setChecked(mode == self.src_mode)
            self.mode_group.addButton(b)
            tabs.addWidget(b)
        self.mode_group.buttonClicked.connect(lambda b: self._set_src_mode(b.property("mode")))
        lay.addLayout(tabs)

        self.src_label = QLabel()
        self.src_label.setWordWrap(True)
        lay.addWidget(self.src_label)

        self.src_stack = QStackedWidget()
        p0 = QWidget()
        l0 = QVBoxLayout(p0)
        l0.setContentsMargins(0, 0, 0, 0)
        l0.setSpacing(7)
        l0.addWidget(hint_label(tr("src.replay_info")))
        b = QPushButton(tr("btn.open_folder"))
        b.setObjectName("primary")
        b.clicked.connect(self._open_folder)
        l0.addWidget(b)
        self.file_list = QListWidget()
        self.file_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.file_list.setFixedHeight(140)
        self.file_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.file_list.setTextElideMode(Qt.ElideRight)
        self.file_list.setUniformItemSizes(True)
        for path, text, sel in self.files:
            it = QListWidgetItem(text)
            it.setToolTip(text)
            it.setData(Qt.UserRole, path)
            self.file_list.addItem(it)
            it.setSelected(sel)
        l0.addWidget(self.file_list)
        l0.addWidget(hint_label(tr("hint.select_files")))
        b2 = QPushButton(tr("btn.load_selected"))
        b2.clicked.connect(self._load_selected)
        l0.addWidget(b2)
        l0.addStretch()
        self.src_stack.addWidget(p0)

        p1 = QWidget()
        l1 = QGridLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setVerticalSpacing(7)
        l1.addWidget(hint_label(tr("sim.info")), 0, 0, 1, 2)
        l1.addWidget(QLabel(tr("sim.profile")), 1, 0)
        self.profile_box = QComboBox()
        for key in PROFILES:
            self.profile_box.addItem(tr(f"profile.{key}"), key)
        self.profile_box.setCurrentIndex(max(0, self.profile_box.findData(self.sim_profile)))
        self.profile_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.profile_box.setMinimumContentsLength(12)
        self.profile_box.setToolTip(tr("tip.profile"))
        l1.addWidget(self.profile_box, 1, 1)
        l1.addWidget(QLabel(tr("sim.seed")), 2, 0)
        self.seed_edit = QLineEdit()
        self.seed_edit.setPlaceholderText(tr("sim.seed_ph"))
        l1.addWidget(self.seed_edit, 2, 1)
        self.cb_hints = QCheckBox(tr("sim.hints"))
        self.cb_hints.setChecked(self.sim_hints)
        self.cb_hints.toggled.connect(self._hints_toggled)
        l1.addWidget(self.cb_hints, 3, 0, 1, 2)
        self.cb_uncal = QCheckBox(tr("sim.uncal"))
        self.cb_uncal.setChecked(self.sim_uncal)
        self.cb_uncal.setToolTip(tr("tip.uncal"))
        l1.addWidget(self.cb_uncal, 4, 0, 1, 2)
        b3 = QPushButton(tr("btn.sim_start"))
        b3.setObjectName("primary")
        b3.clicked.connect(self._start_simulator)
        l1.addWidget(b3, 5, 0, 1, 2)
        l1.setColumnStretch(1, 1)
        l1.setRowStretch(6, 1)
        self.src_stack.addWidget(p1)
        lay.addWidget(self.src_stack)
        lay.addStretch()
        QTimer.singleShot(0, lambda: self._set_src_mode(self.src_mode))
        return w

    def _build_rig_panel(self) -> QWidget:
        w, lay = self._panel()
        self.b_perf = QPushButton()
        self.b_perf.setMinimumHeight(34)
        self.b_perf.clicked.connect(self._toggle_perfusion)
        lay.addWidget(self.b_perf)

        lay.addWidget(section(tr("rig.drugs")))
        grid = QGridLayout()
        grid.setSpacing(5)
        self.drug_buttons: dict[str, QPushButton] = {}
        for i, k in enumerate(DRUGS):
            b = QPushButton(tr(f"drug.{k}"))
            b.setCheckable(True)
            b.setToolTip(tr(f"drugtip.{k}"))
            b.toggled.connect(lambda on, key=k: self._drug_toggled(key, on))
            grid.addWidget(b, i // 2, i % 2)
            self.drug_buttons[k] = b
        lay.addLayout(grid)
        b = QPushButton(tr("btn.washout"))
        b.clicked.connect(self._washout)
        lay.addWidget(b)

        self.balloon_label = section("")
        lay.addWidget(self.balloon_label)
        self.balloon = QSlider(Qt.Horizontal)
        self.balloon.setRange(0, 25)
        self.balloon.valueChanged.connect(self._balloon_changed)
        lay.addWidget(self.balloon)

        lay.addWidget(section(tr("rig.cal")))
        row = QHBoxLayout()
        row.setSpacing(0)
        self.cal_group = QButtonGroup(self)
        for i, (label, val) in enumerate((("0", 0.0), ("100", 100.0), (tr("btn.cal_off"), None))):
            b = QPushButton(label)
            b.setObjectName("seg")
            b.setCheckable(True)
            b.setProperty("cal", val)
            self.cal_group.addButton(b, i)
            row.addWidget(b)
        self.cal_group.buttonClicked.connect(lambda b: self._set_cal(b.property("cal")))
        lay.addLayout(row)

        lay.addWidget(section(tr("rig.trouble")))
        row = QGridLayout()
        row.setSpacing(5)
        b = QPushButton(tr("btn.artefact"))
        b.clicked.connect(lambda: self.sim and self.sim.model.artefact())
        row.addWidget(b, 0, 0)
        self.b_drift = QPushButton(tr("btn.drift"))
        self.b_drift.setCheckable(True)
        self.b_drift.toggled.connect(lambda on: self.sim and self.sim.model.new_baseline_drift(on))
        row.addWidget(self.b_drift, 0, 1)
        self.b_hum = QPushButton(tr("btn.hum"))
        self.b_hum.setCheckable(True)
        self.b_hum.toggled.connect(lambda on: self.sim and setattr(self.sim.model, "hum", on))
        row.addWidget(self.b_hum, 1, 0)
        lay.addLayout(row)

        self.cb_auto = QCheckBox(tr("rig.auto_markers"))
        self.cb_auto.setChecked(self.auto_markers)
        self.cb_auto.toggled.connect(lambda on: setattr(self, "auto_markers", on))
        lay.addWidget(self.cb_auto)

        self.explain_box = QFrame()
        self.explain_box.setObjectName("explain")
        el = QVBoxLayout(self.explain_box)
        el.setContentsMargins(8, 6, 8, 8)
        el.addWidget(section(tr("rig.explain_title")))
        self.explain = QLabel()
        self.explain.setWordWrap(True)
        self.explain.setTextFormat(Qt.RichText)
        el.addWidget(self.explain)
        lay.addWidget(self.explain_box)

        b = QPushButton(tr("btn.summary"))
        b.clicked.connect(self._show_summary)
        lay.addWidget(b)
        lay.addStretch()
        return w

    def _build_protocol_panel(self) -> QWidget:
        w, lay = self._panel()
        grid = QGridLayout()
        grid.setSpacing(5)
        self.preset_buttons = []
        for i, (pid, ckey) in enumerate(PRESETS):
            b = QPushButton(tr("preset." + pid))
            b.setToolTip(f"Ctrl+{i + 1}")
            b.clicked.connect(lambda _=False, p=pid: self.add_preset(p))
            grid.addWidget(b, i // 2, i % 2)
            self.preset_buttons.append((b, ckey))
        lay.addLayout(grid)
        self.marker_edit = QLineEdit()
        self.marker_edit.setPlaceholderText(tr("marker.custom_ph"))
        self.marker_edit.returnPressed.connect(self._custom_marker)
        lay.addWidget(self.marker_edit)
        self.b_base = QPushButton(tr("btn.baseline"))
        self.b_base.setToolTip(tr("tip.baseline"))
        self.b_base.clicked.connect(lambda: self._set_baseline(manual=True))
        lay.addWidget(self.b_base)
        self.base_label = hint_label("")
        lay.addWidget(self.base_label)
        self.marker_list = QListWidget()
        self.marker_list.setMinimumHeight(150)
        self.marker_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.marker_list.setTextElideMode(Qt.ElideRight)
        self.marker_list.itemDoubleClicked.connect(self._jump_to_marker)
        self.marker_list.setToolTip(tr("tip.markers"))
        lay.addWidget(self.marker_list, 1)
        return w

    def _build_record_panel(self) -> QWidget:
        w, lay = self._panel()
        self.rec_title_edit = QLineEdit(self.rec_title)
        self.rec_title_edit.setPlaceholderText(tr("rec.title_ph"))
        self.rec_title_edit.textChanged.connect(lambda s: setattr(self, "rec_title", s))
        lay.addWidget(self.rec_title_edit)
        row = QHBoxLayout()
        self.rec_dir_edit = QLineEdit(self.rec_dir)
        self.rec_dir_edit.setToolTip(tr("tip.rec_dir"))
        self.rec_dir_edit.textChanged.connect(lambda s: setattr(self, "rec_dir", s))
        b = QPushButton("…")
        b.setFixedWidth(32)
        b.clicked.connect(self._choose_rec_dir)
        row.addWidget(self.rec_dir_edit)
        row.addWidget(b)
        lay.addLayout(row)
        self.rec_info_label = hint_label("")
        lay.addWidget(self.rec_info_label)
        lay.addStretch()
        return w

    def _build_channels_panel(self) -> QWidget:
        w, lay = self._panel()
        self.ch_summary = QLabel()
        self.ch_summary.setWordWrap(True)
        self.ch_summary.setTextFormat(Qt.RichText)
        lay.addWidget(self.ch_summary)
        b = QPushButton(tr("act.channels"))
        b.clicked.connect(self._edit_channels)
        lay.addWidget(b)
        b = QPushButton(tr("act.filters"))
        b.clicked.connect(self._edit_filters)
        lay.addWidget(b)
        lay.addStretch()
        return w

    def _make_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key_Space), self, activated=self._toggle_play)
        for i, (pid, _) in enumerate(PRESETS):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda p=pid: self.add_preset(p))

    # ---------------------------------------------- widgets <- state (sync)
    def _sync_widgets(self):
        """Bring every widget in line with the state on `self`."""
        self.b_rec.blockSignals(True)
        self.b_rec.setChecked(self.recorder is not None)
        self.b_rec.blockSignals(False)
        self.b_rec.setText(tr("btn.rec_stop") if self.recorder else tr("btn.rec"))
        self.act_record.blockSignals(True)
        self.act_record.setChecked(self.recorder is not None)
        self.act_record.blockSignals(False)
        self.rec_info_label.setText(tr(self.rec_info[0], **self.rec_info[1]))
        self.base_label.setText(tr(self.base_info[0], **self.base_info[1]))
        self._update_src_label()
        self.marker_list.clear()
        for m in self.markers:
            self._add_marker_item(m)
        self._sync_rig()
        is_replay = isinstance(self.source, ReplaySource)
        self.b_play.setEnabled(self.source is not None)
        self.b_play.setText(("❚❚  " + tr("tool.pause")) if self.running else ("▶  " + tr("tool.play")))
        self.b_rewind.setEnabled(is_replay)
        self.pos_slider.setEnabled(is_replay)
        if is_replay:
            self.pos_slider.setRange(0, self.source.total_samples)
        for b, ckey in self.preset_buttons:
            col = self._color(ckey)
            b.setStyleSheet(f"QPushButton {{ border-left: 4px solid {col}; text-align: left; padding-left: 8px; }}")
        self._update_channel_summary()
        self._update_status()
        self._update_pos()
        self._update_clock()

    def _sync_rig(self):
        m = self.sim.model if self.sim else None
        self.rig_dock.setVisible(m is not None)
        if not m:
            return
        for k, b in self.drug_buttons.items():
            b.blockSignals(True)
            b.setChecked(m.drug_on[k])
            b.blockSignals(False)
        self.balloon.blockSignals(True)
        self.balloon.setValue(int(round(m.edp_set)))
        self.balloon.blockSignals(False)
        self.balloon_label.setText(tr("rig.balloon", v=m.edp_set))
        for b in self.cal_group.buttons():
            b.setChecked(m.cal_pressure is not None and b.property("cal") == m.cal_pressure)
        for b, on in ((self.b_drift, m.drift_on), (self.b_hum, m.hum)):
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
        self.explain_box.setVisible(self.sim_hints)
        self._update_perf_button()
        self._update_explain()

    def _update_src_label(self):
        s = self.source
        if isinstance(s, ReplaySource):
            self.src_label.setText(tr("src.loaded_replay", files=len(s.files),
                                      min=s.total_samples / s.rate / 60, rate=s.rate,
                                      ch=len(s.channel_names)))
        elif isinstance(s, SimulatorSource):
            self.src_label.setText(tr("src.loaded_sim", profile=tr(f"profile.{s.profile}"),
                                      seed=s.model.seed, rate=s.rate))
        self.src_label.setVisible(s is not None)

    def _update_channel_summary(self):
        lines = []
        for i, c in enumerate(self.channels):
            col = self.theme.channels[i % len(self.theme.channels)]
            off = "" if c.enabled else f" <i>{tr('ch.hidden')}</i>"
            f = self._filter_desc(self.filter_cfgs[i]) if i < len(self.filter_cfgs) else []
            fl = f"<br>&nbsp;&nbsp;&nbsp;<span style='color:{self.theme.accent}'>ƒ {', '.join(f)}</span>" if f else ""
            lines.append(f"<span style='color:{col}'>■</span> <b>{c.name}</b> — "
                         f"{tr('role.' + c.role)}, {c.unit}{off}{fl}")
        self.ch_summary.setText("<br>".join(lines))

    def set_ui_language(self, lang: str):
        if lang == language():
            return
        set_language(lang)
        self.settings.setValue("language", lang)
        # rebuild after the menu action that triggered this has finished
        QTimer.singleShot(0, self._rebuild_all)

    def _rebuild_all(self):
        self._build_ui()
        self._refresh_plots()

    # ------------------------------------------------------------- plots
    @staticmethod
    def _filter_desc(c: FilterConfig) -> list[str]:
        out = []
        for key, v in (("med", c.median_ms), ("notch", c.notch_hz), ("hp", c.highpass_hz),
                       ("lp", c.lowpass_hz)):
            if v:
                out.append(tr(f"flt.short_{key}", v=v))
        return out

    def _rebuild_plots(self):
        self.view.theme = self.theme
        desc = [self._filter_desc(c) if (self.filters_on and c.active) else [] for c in self.filter_cfgs]
        self.view.build(self.channels, desc, [c.units_per_volt for c in self.channels])
        self.view.update_trends(self.trend_t, self.trend_lvdp, self.trend_hr)
        for m in self.markers:
            self._add_marker_line(m)
        self._update_units()

    def _update_units(self):
        i = self._lvp_index()
        u = self.channels[i].unit if i is not None else "?"
        units = {"hr": tr("unit.bpm"), "sys": u, "edp": u, "lvdp": u,
                 "dpdt_max": tr("unit.per_s", u=u), "dpdt_min": tr("unit.per_s", u=u),
                 "rpp": tr("unit.rpp", u=u)}
        for k, t in self.tiles.items():
            t.unit.setText(units[k])

    # --------------------------------------------------------------- theme
    def _set_theme(self, name: str):
        if name == self.theme.name:
            return
        self.theme = THEMES[name]
        self.settings.setValue("theme", name)
        QTimer.singleShot(0, self._rebuild_all)

    def _update_status(self):
        th = self.theme
        if self.recorder:
            key, bg = "pill.rec", th.danger
        elif not self.source:
            key, bg = "pill.nodata", th.muted
        elif self.running:
            key, bg = ("pill.sim", th.success) if self.sim else ("pill.replay", th.warn)
        else:
            key, bg = "pill.paused", th.muted
        self.status_lamp.setText(tr(key))
        self.status_lamp.setStyleSheet(f"background:{bg};")

    # ============================================================= sources
    def _set_src_mode(self, mode: str):
        self.src_mode = mode
        self.settings.setValue("src_mode", mode)
        for b in self.mode_group.buttons():
            b.setChecked(b.property("mode") == mode)
        idx = 0 if mode == "replay" else 1
        self.src_stack.setCurrentIndex(idx)
        # a stacked widget is as tall as its tallest page; let hidden pages take no space
        for i in range(self.src_stack.count()):
            self.src_stack.widget(i).setSizePolicy(
                QSizePolicy.Preferred, QSizePolicy.Preferred if i == idx else QSizePolicy.Ignored)
        self.src_stack.adjustSize()

    def _open_folder(self):
        start = self.settings.value("last_folder", str(Path.home() / "Documents"))
        folder = QFileDialog.getExistingDirectory(self, tr("dlg.folder"), start)
        if folder:
            self.open_folder(folder)

    def open_folder(self, folder: str | Path):
        self.settings.setValue("last_folder", str(folder))
        self._set_src_mode("replay")
        self.files = []
        for f in find_recordings(folder):
            try:
                h = parse_header(f.read_bytes()[:0x600])
                text = f"{f.stem}   {h.start:%d.%m.%y %H:%M}   {h.comment}"
            except Exception as e:      # a damaged file must not break the list
                text = f"{f.name} ({e})"
            self.files.append((str(f), text, True))
        self.file_list.clear()
        for path, text, sel in self.files:
            it = QListWidgetItem(text)
            it.setToolTip(text)
            it.setData(Qt.UserRole, path)
            self.file_list.addItem(it)
            it.setSelected(sel)
        self.statusBar().showMessage(tr("status.found", n=len(self.files), folder=folder))

    def _load_selected(self):
        sel = [self.file_list.item(i).isSelected() for i in range(self.file_list.count())]
        self.files = [(p, t, s) for (p, t, _), s in zip(self.files, sel)]
        files = [p for p, _, s in self.files if s]     # in list order = recording time
        if files:
            self.load_files(files)

    def load_files(self, files):
        try:
            src = ReplaySource(files, speed=self.speed)
        except Exception as e:
            QMessageBox.warning(self, tr("dlg.open_fail"), str(e))
            return
        if len(self.channels) != len(src.channel_names) or self.sim:
            self.channels = [ChannelConfig(**asdict(c)) for c in LEGACY_DEFAULT] \
                if len(src.channel_names) == 3 else [ChannelConfig(n) for n in src.channel_names]
            self.filter_cfgs = [FilterConfig() for _ in self.channels]
        self._set_source(src)

    def _start_simulator_default(self):
        self._set_src_mode("sim")
        self._start_simulator()

    def _start_simulator(self):
        txt = self.seed_edit.text().strip()
        seed = int(txt) if txt.isdigit() else None
        self.sim_profile = self.profile_box.currentData()
        self.sim_uncal = self.cb_uncal.isChecked()
        src = SimulatorSource(self.sim_profile, rate=SIM_RATE, seed=seed, speed=self.speed)
        self.channels = simulator_channels(calibrated=not self.sim_uncal)
        self.filter_cfgs = [FilterConfig() for _ in self.channels]
        self._set_source(src)
        self._start()

    def _set_source(self, src: DataSource):
        self._stop()
        if self.recorder:
            self.b_rec.setChecked(False)
        self.source = src
        self.baseline = None
        self.base_info = ("base.none", {})
        self.last_params = None
        self._reset_buffers(0)
        self._rebuild_plots()
        self._update_tiles()
        self._sync_widgets()
        self.statusBar().showMessage(tr("status.loaded"))

    # ========================================================= playback
    def _toggle_play(self):
        if not self.source:
            return
        if self.running:
            self._stop()
        else:
            self._start()

    def _start(self):
        if not self.source:
            return
        if self.source.finished:
            self._seek_to(0)
        self.source.start()
        self.running = True
        self.timer.start()
        self.b_play.setText("❚❚  " + tr("tool.pause"))
        self._update_status()
        self.statusBar().showMessage(self.source.describe())

    def _stop(self):
        if self.source:
            self.source.stop()
        self.running = False
        if hasattr(self, "timer"):
            self.timer.stop()
        self.b_play.setText("▶  " + tr("tool.play"))
        self._update_status()

    def set_speed(self, speed: int):
        self.speed = speed
        if self.speed_box.currentData() != speed:
            self.speed_box.setCurrentIndex(SPEEDS.index(speed))
        if hasattr(self.source, "set_speed"):
            self.source.set_speed(speed)

    def _seek_to(self, sample: int):
        if not isinstance(self.source, ReplaySource):
            return
        self.source.seek(sample)
        self._reset_buffers(self.source.position)
        self.marker_list.clear()
        self._rebuild_plots()
        self._update_pos()

    def _window_changed(self, idx: int):
        self.window_idx = idx
        self.view.set_autoscale(self.autoscale)
        self._refresh_plots()

    def _set_autoscale(self, on: bool):
        self.autoscale = on
        for w in (self.b_auto, self.act_autoscale):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        self.view.set_autoscale(on)
        self._refresh_plots()

    def _set_filters_on(self, on: bool):
        self.filters_on = on
        for w in (self.b_filt, self.act_filters_on):
            w.blockSignals(True)
            w.setChecked(on)
            w.blockSignals(False)
        self._rebuild_plots()
        self._refresh_plots()

    def _update_pos(self):
        s = self.source
        if isinstance(s, ReplaySource):
            self.pos_label.setText(fmt_time(s.position / s.rate))
            self.total_label.setText(fmt_time(s.total_samples / s.rate))
            if not self.pos_slider.isSliderDown():
                self.pos_slider.setValue(s.position)
        else:
            self.pos_label.setText(fmt_time(self.n / self.rate) if s else "00:00")
            self.total_label.setText("")

    # ============================================================== loop
    def _tick(self):
        if not self.source:
            return
        block, events = self.source.read()
        if len(block):
            keep = int(BUFFER_S * self.rate)
            self.buf = np.concatenate([self.buf, block])[-keep:]
            self.fbuf = np.concatenate([self.fbuf, self.bank.process(block)])[-keep:]
            self.n += len(block)
            if self.recorder:
                self.recorder.write_block(self._to_units(block))
            for ev in events:
                if ev.kind == "sim" and not self.sim_hints:
                    continue
                key = ev.text if ev.kind in ("sim", "marker") else None
                self._register_marker({"sample": ev.sample, "kind": ev.kind, "key": key,
                                       "params": ev.params, "text": ev.text})
            self._run_analysis()
            self._draw()
        self._update_pos()
        self._update_clock()
        self._explain_tick += 1
        if self._explain_tick % 15 == 0:
            self._update_explain()
        if self.source.finished:
            self._stop()
            self.statusBar().showMessage(tr("status.finished"))

    def _update_clock(self):
        self.clock.setText(fmt_time(self.n / self.rate))
        if self.phase:
            self.phase_label.setText(self._marker_text(self.phase))
            self.phase_time.setText(tr("phase.lasts", t=fmt_time((self.n - self.phase["sample"]) / self.rate)))
        else:
            self.phase_label.setText(tr("phase.none"))
            self.phase_time.setText(tr("phase.hint"))

    def _to_units(self, volts: np.ndarray) -> np.ndarray:
        out = np.empty(volts.shape, dtype=np.float64)
        for i, c in enumerate(self.channels):
            out[:, i] = c.to_units(volts[:, i])
        return out

    def _current_volts(self, i: int) -> float | None:
        if len(self.buf) == 0 or i >= self.buf.shape[1]:
            return None
        return float(np.mean(self.buf[-int(0.5 * self.rate):, i]))

    def _run_analysis(self):
        li = self._lvp_index()
        if li is None:
            return
        step = int(ANALYSIS_STEP_S * self.rate)
        win = int(ANALYSIS_WIN_S * self.rate)
        c = self.channels[li]
        data = self.view_buf
        params = None
        while self.next_analysis + step <= self.n:
            self.next_analysis += step
            end = len(data) - (self.n - self.next_analysis)
            if end < win:
                continue
            x = c.to_units(data[end - win:end, li].astype(np.float64))
            params = compute(x, self.rate, min_amplitude=0.1 * abs(c.units_per_volt))
            self.trend_t.append(self.next_analysis / self.rate / 60)
            self.trend_lvdp.append(np.nan if params.lvdp is None else params.lvdp)
            self.trend_hr.append(np.nan if params.hr is None else params.hr)
            if self.recorder:
                self.recorder.add_params(self.recorder.n - (self.n - self.next_analysis),
                                         params.as_row())
        if params is not None:
            self.last_params = params
            self._update_tiles()
            self.view.update_trends(self.trend_t, self.trend_lvdp, self.trend_hr)

    def _update_tiles(self):
        p, b, th = self.last_params, self.baseline, self.theme
        for key, mode, digits in TILES:
            tile = self.tiles[key]
            v = getattr(p, key) if p else None
            tile.value.setText(fmt_num(v, digits))
            ref = getattr(b, key) if b else None
            if v is None or ref is None:
                tile.delta.setText("")
                continue
            if mode == "pct" and ref:
                pct = 100 * v / ref
                col = th.success if pct >= 80 else (th.warn if pct >= 50 else th.danger)
                tile.delta.setText(tr("tile.pct", pct=pct))
            else:
                # EDP: a rise above 10 % of baseline LVDP is flagged (contracture)
                d = v - ref
                col = th.danger if d > 0.1 * abs(b.lvdp or 1) else th.muted
                tile.delta.setText(tr("tile.abs", d=d))
            tile.delta.setStyleSheet(f"color:{col};")

    def _draw(self):
        """Redraw the plots, but never let drawing take more than ~1/3 of the time:
        on a slow computer (or a large Retina screen) the plots refresh less often,
        while data, analysis, recording and the controls stay responsive."""
        now = time.perf_counter()
        if now - self._last_draw < self._draw_interval:
            return
        self._refresh_plots()
        self.view.repaint_now()
        cost = time.perf_counter() - now
        self._draw_interval = min(0.5, max(0.04, 3 * cost))
        self._last_draw = time.perf_counter()

    def _refresh_plots(self):
        if not getattr(self.view, "plots", None):
            return
        w = WINDOWS[self.window_idx]
        data = self.view_buf
        nshow = min(len(data), int(w * self.rate))
        t = (self.n - nshow + np.arange(nshow)) / self.rate
        ys = [self.channels[i].to_units(data[-nshow:, i]) for i in self.view.rows]
        self.view.update_signals(t, ys, w, self.n / self.rate)

    # =========================================================== markers
    def add_preset(self, pid: str):
        if not self.source:
            return
        if pid == "isch" and self.baseline is None and self.last_params:
            self._set_baseline(manual=False)
        self._register_marker({"sample": self.n, "kind": "user", "key": f"preset.{pid}",
                               "params": {}, "text": "", "preset": pid})

    def add_marker(self, text: str, key: str | None = None, **params):
        if not self.source:
            return
        self._register_marker({"sample": self.n, "kind": "user", "key": key,
                               "params": params, "text": text})

    def _custom_marker(self):
        t = self.marker_edit.text().strip()
        if t:
            self.add_marker(t)
            self.marker_edit.clear()

    def _marker_text(self, m: dict) -> str:
        if not m.get("key"):
            return m["text"]
        params = dict(m.get("params") or {})
        if "drug_key" in params:
            params["drug"] = tr(params["drug_key"])
        return tr(m["key"], **params)

    def _marker_color(self, m: dict) -> str:
        if m["kind"] == "file":
            return self.theme.muted
        if m["kind"] in ("marker", "sim"):
            return self.theme.warn
        for pid, ckey in PRESETS:
            if m.get("preset") == pid:
                return self._color(ckey)
        return self.theme.accent

    def _register_marker(self, m: dict):
        self.markers.append(m)
        self._add_marker_item(m)
        if m["kind"] == "user":
            self.phase = m
            self._update_clock()
        if self.recorder:
            self.recorder.add_marker(self.recorder.n - (self.n - m["sample"]),
                                     self._marker_text(m), m["kind"])
        self._add_marker_line(m)

    def _add_marker_item(self, m: dict):
        text = self._marker_text(m)
        prefix = "◆ " if m["kind"] == "sim" else ""
        it = QListWidgetItem(f"{fmt_time(m['sample'] / self.rate)}  {prefix}{text}")
        it.setForeground(pg.mkColor(self._marker_color(m)))
        it.setToolTip(text)
        it.setData(Qt.UserRole, m["sample"])
        self.marker_list.addItem(it)
        self.marker_list.scrollToBottom()

    def _add_marker_line(self, m: dict):
        self.view.add_marker(m["sample"] / self.rate, self._marker_text(m), self._marker_color(m),
                             dashed=m["kind"] in ("file", "sim"), label=m["kind"] != "file",
                             on_trends=m["kind"] in ("user", "info"),
                             window_s=WINDOWS[self.window_idx])

    def _jump_to_marker(self, item: QListWidgetItem):
        sample = item.data(Qt.UserRole)
        if isinstance(self.source, ReplaySource) and sample is not None:
            self._seek_to(max(0, int(sample - 5 * self.rate)))

    def _set_baseline(self, manual: bool):
        if not self.last_params or self.last_params.lvdp is None:
            if manual:
                self.statusBar().showMessage(tr("base.no_beats"))
            return
        self.baseline = replace(self.last_params)
        b = self.baseline
        self.base_info = ("base.set", {"how": tr("base.manual" if manual else "base.auto"),
                                       "t": fmt_time(self.n / self.rate),
                                       "lvdp": fmt_num(b.lvdp, 1), "hr": fmt_num(b.hr, 0)})
        self.base_label.setText(tr(self.base_info[0], **self.base_info[1]))
        self._register_marker({"sample": self.n, "kind": "info", "key": "marker.baseline",
                               "params": {}, "text": ""})
        self._update_tiles()

    # ========================================================= virtual rig
    def _update_perf_button(self):
        m = self.sim.model if self.sim else None
        on = m.perfused if m else True
        self.b_perf.setText(tr("rig.perf_on") if on else tr("rig.perf_off"))
        th = self.theme
        if on:
            self.b_perf.setStyleSheet(f"QPushButton {{ border: 1px solid {th.success}; color: {th.success}; font-weight: 600; }}")
        else:
            self.b_perf.setStyleSheet(f"QPushButton {{ background: {th.danger}; color: white; border-color: {th.danger}; font-weight: 600; }}")

    def _toggle_perfusion(self):
        if not self.sim:
            return
        m = self.sim.model
        if m.perfused:
            m.stop_perfusion()
            if self.auto_markers:
                self.add_preset("isch")
        else:
            m.restore_perfusion()
            if self.auto_markers:
                self.add_preset("reperf")
        self._update_perf_button()
        self._update_explain()

    def _drug_toggled(self, key: str, on: bool):
        if not self.sim:
            return
        self.sim.model.set_drug(key, on)
        if self.auto_markers:
            self.add_marker("", key="marker.drug_on" if on else "marker.drug_off",
                            drug_key=f"drug.{key}")

    def _washout(self):
        if not self.sim:
            return
        self.sim.model.washout()
        self._sync_rig()
        if self.auto_markers:
            self.add_preset("wash")

    def _balloon_changed(self, v: int):
        if self.sim:
            self.sim.model.set_balloon(v)
            self.balloon_label.setText(tr("rig.balloon", v=v))

    def _set_cal(self, value):
        if not self.sim:
            return
        self.sim.model.cal_pressure = value
        if value is not None and self.auto_markers:
            self.add_marker("", key="marker.cal", p=value)
        self._sync_rig()

    def _hints_toggled(self, on: bool):
        self.sim_hints = on
        self.explain_box.setVisible(on)

    def _update_explain(self):
        if not self.sim or not self.sim_hints:
            return
        items = [tr(k, **p) for k, p in self.sim.model.explain()]
        self.explain.setText("<br>".join(f"• {s}" for s in items))

    def _show_summary(self):
        if not self.sim:
            return
        s = self.sim.model.summary()
        isch = ", ".join(tr("sum.isch_item", m=e["duration_s"] / 60, loss=100 * e["loss"])
                         for e in s["ischemias"]) or tr("sum.none")
        contr = f"{s['contracture_onset_s'] / 60:.1f}" if s["contracture_onset_s"] else tr("sum.none")
        if self.baseline and self.baseline.lvdp and self.last_params and self.last_params.lvdp is not None:
            rec = tr("sum.rec", pct=100 * self.last_params.lvdp / self.baseline.lvdp)
        else:
            rec = tr("sum.no_baseline")
        body = tr("sum.body", profile=tr(f"profile.{s['profile']}"), seed=s["seed"], isch=isch,
                  contr=contr, vf=s["vf_episodes"], vf_time=s["vf_time"], vt=s["vt_episodes"],
                  ect=s["ectopics"], rec=rec, t50=s["true_t50_min"], tc=s["true_contracture_min"],
                  ach=s["achievable_recovery_pct"])
        QMessageBox.information(self, tr("sum.title"), body)

    # ============================================================ recording
    def _choose_rec_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("dlg.rec_dir"), self.rec_dir)
        if d:
            self.rec_dir_edit.setText(d)

    def _toggle_record(self, on: bool):
        if on:
            if not self.source:
                self.b_rec.setChecked(False)
                self.statusBar().showMessage(tr("rec.need_source"))
                return
            self.settings.setValue("rec_dir", self.rec_dir)
            try:
                self.recorder = SessionRecorder(self.rec_dir, self.channels, self.rate,
                                                self.source.describe(), self.rec_title)
                self.recorder.meta["display_filters"] = [asdict(c) for c in self.filter_cfgs] \
                    if self.filters_on else []
                self.recorder._write_meta()
            except Exception as e:
                QMessageBox.warning(self, tr("dock.record"), tr("rec.error", e=e))
                self.b_rec.setChecked(False)
                return
            self.rec_info = ("rec.writing", {"dir": str(self.recorder.dir)})
        else:
            if self.recorder:
                self.recorder.close()
                self.rec_info = ("rec.saved", {"dir": str(self.recorder.dir)})
                self.statusBar().showMessage(tr("status.saved", dir=self.recorder.dir))
            self.recorder = None
        self.b_rec.setText(tr("btn.rec_stop") if self.recorder else tr("btn.rec"))
        self.act_record.blockSignals(True)
        self.act_record.setChecked(self.recorder is not None)
        self.act_record.blockSignals(False)
        self.rec_info_label.setText(tr(self.rec_info[0], **self.rec_info[1]))
        self._update_status()

    # ============================================================= channels
    def _edit_channels(self):
        if self.recorder:
            QMessageBox.information(self, tr("dock.channels"), tr("rec.stop_first"))
            return
        dlg = ChannelsDialog(self.channels, self, current_volts=self._current_volts)
        if dlg.exec():
            self.channels = dlg.channels()
            if not self.sim:
                self.settings.setValue("channels", json.dumps([asdict(c) for c in self.channels]))
            self.baseline = None
            self.base_info = ("base.none_channels", {})
            self.base_label.setText(tr(self.base_info[0]))
            self._rebuild_plots()
            self._update_channel_summary()
            self._refresh_plots()

    def _edit_filters(self):
        dlg = FiltersDialog(self.channels, self.filter_cfgs, self.rate, self)
        if dlg.exec():
            self.filter_cfgs = dlg.configs()
            self.bank = FilterBank(self.filter_cfgs, self.rate)
            # re-filter what is already in the buffer, so the change is visible at once
            self.fbuf = self.bank.process(self.buf) if len(self.buf) else self.fbuf[:0]
            if self.bank.active and not self.filters_on:
                self._set_filters_on(True)
            self._rebuild_plots()
            self._update_channel_summary()
            self._refresh_plots()

    def _load_channel_settings(self) -> list[ChannelConfig]:
        raw = self.settings.value("channels")
        if raw:
            try:
                return [ChannelConfig(**d) for d in json.loads(raw)]
            except Exception:
                pass
        return [ChannelConfig(**asdict(c)) for c in LEGACY_DEFAULT]

    def closeEvent(self, ev):
        if self.recorder:
            self.recorder.close()
        super().closeEvent(ev)
