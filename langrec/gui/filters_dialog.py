"""Digital filter settings per channel (display and analysis only; raw data is recorded)."""
from __future__ import annotations

from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTableWidget, QVBoxLayout)

from ..analysis.filters import FilterConfig, suggested
from ..i18n import tr

LP = [None, 5, 10, 20, 30, 50, 100, 200]
HP = [None, 0.05, 0.1, 0.5, 1, 5]
NOTCH = [None, 50, 60]
MEDIAN = [None, 10, 20, 50]


def _combo(values, current, unit, rate_limit=None):
    c = QComboBox()
    for v in values:
        if v is not None and rate_limit is not None and v >= rate_limit:
            continue
        c.addItem(tr("flt.off") if v is None else f"{v:g} {unit}", v)
    i = c.findData(current)
    c.setCurrentIndex(i if i >= 0 else 0)
    return c


class FiltersDialog(QDialog):
    def __init__(self, channels, configs: list[FilterConfig], rate: float, parent=None):
        super().__init__(parent)
        self.channels = channels
        self.rate = rate
        self.setWindowTitle(tr("flt.title"))
        self.resize(720, 320)
        lay = QVBoxLayout(self)
        help_ = QLabel(tr("flt.help", rate=rate))
        help_.setWordWrap(True)
        lay.addWidget(help_)
        cols = tr("flt.cols").split("|")
        self.table = QTableWidget(len(channels), len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        b1 = QPushButton(tr("flt.suggest"))
        b1.clicked.connect(self._suggest)
        b2 = QPushButton(tr("flt.reset"))
        b2.clicked.connect(lambda: self._fill([FilterConfig() for _ in channels]))
        row.addWidget(b1)
        row.addWidget(b2)
        row.addStretch()
        lay.addLayout(row)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill(configs)

    def _fill(self, configs):
        nyq = self.rate / 2
        first = self.table.cellWidget(0, 1) is None
        for r, (ch, cfg) in enumerate(zip(self.channels, configs)):
            values = (cfg.lowpass_hz, cfg.highpass_hz, cfg.notch_hz, cfg.median_ms)
            if first:      # widgets are created once; later calls only change values
                self.table.setCellWidget(r, 0, QLabel(f"  {ch.name} — {tr('role.' + ch.role)}  "))
                self.table.setCellWidget(r, 1, _combo(LP, None, tr("unit.hz"), nyq * 0.95))
                self.table.setCellWidget(r, 2, _combo(HP, None, tr("unit.hz"), nyq * 0.9))
                self.table.setCellWidget(r, 3, _combo(NOTCH, None, tr("unit.hz"), nyq * 0.95))
                self.table.setCellWidget(r, 4, _combo(MEDIAN, None, tr("unit.ms")))
            for col, v in enumerate(values, start=1):
                box = self.table.cellWidget(r, col)
                i = box.findData(v)
                box.setCurrentIndex(i if i >= 0 else 0)
        if first:
            self.table.resizeColumnsToContents()

    def _suggest(self):
        self._fill([suggested(c.role, self.rate) for c in self.channels])

    def configs(self) -> list[FilterConfig]:
        w = self.table.cellWidget
        return [FilterConfig(lowpass_hz=w(r, 1).currentData(), highpass_hz=w(r, 2).currentData(),
                             notch_hz=w(r, 3).currentData(), median_ms=w(r, 4).currentData())
                for r in range(self.table.rowCount())]
