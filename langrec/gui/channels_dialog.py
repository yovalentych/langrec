"""Channel settings dialog: name, role, units, calibration, and a two-point calibration helper."""
from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                               QFileDialog, QGridLayout, QGroupBox, QHBoxLayout, QLabel,
                               QLineEdit, QPushButton, QTableWidget, QVBoxLayout)

from ..channels import ROLE_KEYS, ChannelConfig, load_channels, save_channels
from ..i18n import tr


def _spin(lo, hi, dec, val):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setDecimals(dec)
    s.setValue(val)
    return s


class ChannelsDialog(QDialog):
    def __init__(self, channels: list[ChannelConfig], parent=None,
                 current_volts: Callable[[int], float | None] | None = None):
        super().__init__(parent)
        self.current_volts = current_volts
        self.setWindowTitle(tr("chd.title"))
        self.resize(820, 520)
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(tr("chd.help")))
        cols = tr("chd.cols").split("|")
        self.table = QTableWidget(0, len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.table)

        row = QHBoxLayout()
        b_load = QPushButton(tr("chd.load"))
        b_save = QPushButton(tr("chd.save"))
        b_load.clicked.connect(self._load)
        b_save.clicked.connect(self._save)
        row.addWidget(b_load)
        row.addWidget(b_save)
        row.addStretch()
        lay.addLayout(row)

        lay.addWidget(self._two_point_box())

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self._fill(channels)

    # ------------------------------------------------------------------ table
    def _fill(self, channels):
        self.table.setRowCount(len(channels))
        for r, c in enumerate(channels):
            self.table.setCellWidget(r, 0, QLineEdit(c.name))
            role = QComboBox()
            for key in ROLE_KEYS:
                role.addItem(tr(f"role.{key}"), key)
            role.setCurrentIndex(max(0, role.findData(c.role)))
            self.table.setCellWidget(r, 1, role)
            self.table.setCellWidget(r, 2, QLineEdit(c.unit))
            self.table.setCellWidget(r, 3, _spin(-1e6, 1e6, 4, c.units_per_volt))
            self.table.setCellWidget(r, 4, _spin(-20, 20, 4, c.zero_v))
            en = QCheckBox()
            en.setChecked(c.enabled)
            self.table.setCellWidget(r, 5, en)
        self.table.resizeColumnsToContents()
        self.tp_channel.clear()
        for c in channels:
            self.tp_channel.addItem(c.name)

    def channels(self) -> list[ChannelConfig]:
        out = []
        w = self.table.cellWidget
        for r in range(self.table.rowCount()):
            out.append(ChannelConfig(
                name=w(r, 0).text().strip() or f"CH{r:02d}",
                role=w(r, 1).currentData(),
                unit=w(r, 2).text().strip() or "V",
                units_per_volt=w(r, 3).value(),
                zero_v=w(r, 4).value(),
                enabled=w(r, 5).isChecked(),
            ))
        return out

    # ------------------------------------------------------- two-point helper
    def _two_point_box(self) -> QGroupBox:
        g = QGroupBox(tr("chd.twopoint"))
        gl = QGridLayout(g)
        help_ = QLabel(tr("chd.tp_help"))
        help_.setWordWrap(True)
        gl.addWidget(help_, 0, 0, 1, 5)
        gl.addWidget(QLabel(tr("chd.channel")), 1, 0)
        self.tp_channel = QComboBox()
        gl.addWidget(self.tp_channel, 1, 1)
        self.tp = []
        for i, (key, val) in enumerate([("chd.p1", 0.0), ("chd.p2", 100.0)]):
            gl.addWidget(QLabel(tr(key)), 2 + i, 0)
            v = _spin(-1e5, 1e5, 3, val)
            v.setPrefix(tr("chd.value") + " ")
            volts = _spin(-20, 20, 4, 0.0)
            volts.setSuffix(" " + tr("chd.volts"))
            take = QPushButton(tr("chd.take"))
            take.setEnabled(self.current_volts is not None)
            take.clicked.connect(lambda _=False, sp=volts: self._take(sp))
            gl.addWidget(v, 2 + i, 1)
            gl.addWidget(volts, 2 + i, 2)
            gl.addWidget(take, 2 + i, 3)
            self.tp.append((v, volts))
        b = QPushButton(tr("chd.apply"))
        b.clicked.connect(self._apply_two_point)
        gl.addWidget(b, 4, 3)
        return g

    def _take(self, spin):
        v = self.current_volts(self.tp_channel.currentIndex()) if self.current_volts else None
        if v is not None:
            spin.setValue(v)

    def _apply_two_point(self):
        (p1, v1), (p2, v2) = [(a.value(), b.value()) for a, b in self.tp]
        if abs(v2 - v1) < 1e-6:
            return
        k = (p2 - p1) / (v2 - v1)
        zero = v1 - p1 / k
        r = self.tp_channel.currentIndex()
        self.table.cellWidget(r, 3).setValue(k)
        self.table.cellWidget(r, 4).setValue(zero)

    # ------------------------------------------------------------------- files
    def _load(self):
        p, _ = QFileDialog.getOpenFileName(self, tr("chd.json"), "", "JSON (*.json)")
        if p:
            chs = load_channels(p)
            if len(chs) == self.table.rowCount():
                self._fill(chs)

    def _save(self):
        p, _ = QFileDialog.getSaveFileName(self, tr("chd.json"), "channels.json", "JSON (*.json)")
        if p:
            save_channels(self.channels(), p)
