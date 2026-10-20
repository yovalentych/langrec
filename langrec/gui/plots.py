"""Signal plots (one per channel, shared time axis) and session trends.

Autoscale (per channel):
  * expands at once when the signal leaves the current range, shrinks slowly when the
    signal has become much smaller — so the axis does not jump with every beat;
  * dragging / wheel-zooming the Y axis switches that plot to manual; a double-click
    on the plot (or the global Autoscale toggle) switches it back.

Marker labels are drawn only on the top plot, shortened, above every line, and laid out
in pixel space so that they never overlap (see _place_labels).
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from ..i18n import tr
from .theme import Theme

LABEL_ROW_PX = 20      # height of one row of marker labels
LABEL_MAX = 24


class AutoRange:
    def __init__(self, min_span: float):
        self.min_span = min_span
        self.cur: tuple[float, float] | None = None

    def update(self, y: np.ndarray) -> tuple[float, float] | None:
        if y.size == 0:
            return self.cur
        lo, hi = float(np.nanmin(y)), float(np.nanmax(y))
        if not np.isfinite(lo) or not np.isfinite(hi):
            return self.cur
        span = max(hi - lo, self.min_span)
        mid = (hi + lo) / 2
        lo, hi = mid - span / 2, mid + span / 2
        pad = 0.08 * span
        tlo, thi = lo - pad, hi + pad
        extra = 0.04 * (thi - tlo)
        if self.cur is None:
            self.cur = (tlo - extra, thi + extra)
        elif tlo < self.cur[0] or thi > self.cur[1]:
            # expand at once, with a little extra room
            self.cur = (min(self.cur[0], tlo - extra), max(self.cur[1], thi + extra))
        elif (thi - tlo) < 0.6 * (self.cur[1] - self.cur[0]):
            a = 0.15     # shrink slowly
            self.cur = (self.cur[0] * (1 - a) + tlo * a, self.cur[1] * (1 - a) + thi * a)
        return self.cur

    def reset(self):
        self.cur = None


class SignalView(QWidget):
    def __init__(self, theme: Theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.split = QSplitter(Qt.Vertical)
        self.glw = pg.GraphicsLayoutWidget()
        self.trend_w = pg.GraphicsLayoutWidget()
        self.split.addWidget(self.glw)
        self.split.addWidget(self.trend_w)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setChildrenCollapsible(False)
        lay.addWidget(self.split)
        self.glw.scene().sigMouseClicked.connect(self._scene_clicked)
        self.autoscale = True
        self.plots: list[pg.PlotItem] = []
        self.curves = []
        self.rows: list[int] = []
        self.ranges: list[AutoRange] = []
        self.auto: list[bool] = []
        self._labels: list[tuple[pg.TextItem, float, int]] = []   # (item, time, level)
        self._titles: list[str] = []

    # ------------------------------------------------------------- building
    def build(self, channels, filter_desc: list[list[str]], units_scale: list[float]):
        th = self.theme
        pg.setConfigOptions(antialias=True, background=th.plot_bg, foreground=th.plot_fg)
        for w in (self.glw, self.trend_w):
            w.setBackground(th.plot_bg)
        self.glw.clear()
        self.plots, self.curves, self.rows, self.ranges, self.auto, self._titles = [], [], [], [], [], []
        self._labels = []
        first = None
        for i, c in enumerate(channels):
            if not c.enabled:
                continue
            col = th.channels[i % len(th.channels)]
            p = self.glw.addPlot(row=len(self.plots), col=0)
            ax = p.getAxis("left")
            ax.setWidth(62)
            ax.enableAutoSIPrefix(False)        # no "x0.001" axis labels
            p.getAxis("bottom").enableAutoSIPrefix(False)
            p.showGrid(x=True, y=True, alpha=th.grid_alpha)
            p.setMouseEnabled(x=False, y=True)
            p.hideButtons()
            p.setMenuEnabled(False)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            if first is None:
                first = p
            else:
                p.setXLink(first)
            curve = p.plot(pen=pg.mkPen(col, width=1.5))
            idx = len(self.plots)
            p.getViewBox().sigRangeChangedManually.connect(lambda *_, k=idx: self._manual(k))
            self.plots.append(p)
            self.curves.append(curve)
            self.rows.append(i)
            self.ranges.append(AutoRange(min_span=0.02 * abs(units_scale[i] or 1)))
            self.auto.append(self.autoscale)
            badge = ""
            if filter_desc and i < len(filter_desc) and filter_desc[i]:
                badge = f"  <span style='color:{th.accent}'>ƒ {', '.join(filter_desc[i])}</span>"
            self._titles.append(f"<span style='color:{col}; font-weight:600'>{c.name}</span>"
                                f"<span style='color:{th.muted}'>  {tr('role.' + c.role)} [{c.unit}]</span>{badge}")
            self._set_title(idx)
        for p in self.plots[:-1]:
            p.getAxis("bottom").setStyle(showValues=False)
        if self.plots:
            self.plots[-1].setLabel("bottom", tr("plot.time"))

        self.trend_w.clear()
        self.tp_lvdp = self.trend_w.addPlot(row=0, col=0)
        self.tp_hr = self.trend_w.addPlot(row=0, col=1)
        for tp, key in ((self.tp_lvdp, "plot.trend_lvdp"), (self.tp_hr, "plot.trend_hr")):
            tp.setTitle(f"<span style='color:{th.plot_fg}'>{tr(key)}</span>", justify="left", size="9pt")
            tp.showGrid(x=True, y=True, alpha=th.grid_alpha)
            tp.setLabel("bottom", tr("plot.min"))
            tp.getAxis("left").enableAutoSIPrefix(False)
            tp.getAxis("bottom").enableAutoSIPrefix(False)
            tp.getAxis("left").setWidth(48)
            tp.hideButtons()
            tp.setMenuEnabled(False)
        self.tc_lvdp = self.tp_lvdp.plot(pen=pg.mkPen(th.channels[0], width=1.8))
        self.tc_hr = self.tp_hr.plot(pen=pg.mkPen(th.channels[1], width=1.8))

    def _set_title(self, k: int):
        manual = "" if self.auto[k] else f"  <span style='color:{self.theme.warn}'>{tr('plot.manual')}</span>"
        self.plots[k].setTitle(self._titles[k] + manual, justify="left", size="9pt")

    def _manual(self, k: int):
        if self.auto[k]:
            self.auto[k] = False
            self._set_title(k)

    def _scene_clicked(self, ev):
        if not ev.double():
            return
        for k, p in enumerate(self.plots):
            if p.sceneBoundingRect().contains(ev.scenePos()):
                self.auto[k] = True
                self.ranges[k].reset()
                self._set_title(k)

    def set_autoscale(self, on: bool):
        self.autoscale = on
        for k in range(len(self.plots)):
            self.auto[k] = on
            self.ranges[k].reset()
            self._set_title(k)

    # --------------------------------------------------------------- update
    def update_signals(self, t: np.ndarray, data_units: list[np.ndarray], window_s: float, t_end: float):
        for k, (curve, y) in enumerate(zip(self.curves, data_units)):
            curve.setData(t, y)
            if self.auto[k] and len(y):
                r = self.ranges[k].update(y)
                if r:
                    self.plots[k].setYRange(*r, padding=0)
        if self.plots:
            self.plots[0].setXRange(max(0.0, t_end - window_s), max(window_s, t_end), padding=0)

    def _place_labels(self):
        """Lay labels out in pixel space: each goes to the highest row where it does not
        overlap an earlier label; if no row is free it is hidden (the full text stays in
        the marker list and in the tooltip)."""
        if not self.plots or not self._labels:
            return
        vb = self.plots[0].getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        w_px, h_px = vb.width(), vb.height()
        if w_px <= 0 or h_px <= 0:
            return
        sx, sy = (x1 - x0) / w_px, (y1 - y0) / h_px
        row = max(LABEL_ROW_PX, self._labels[0][0].boundingRect().height() + 3)
        n_rows = max(1, int(h_px * 0.95 // row))
        right = [float("-inf")] * n_rows
        for item, ts, _ in sorted(self._labels, key=lambda lab: lab[1]):
            if ts < x0 or ts > x1:
                item.setVisible(False)
                continue
            x_px = (ts - x0) / sx + 4                       # 4 px gap after the line
            width = item.boundingRect().width()
            level = next((i for i in range(n_rows) if right[i] <= x_px), None)
            if level is None:
                item.setVisible(False)
                continue
            right[level] = x_px + width + 6
            item.setVisible(True)
            item.setPos(x0 + x_px * sx, y1 - (4 + level * row + row / 2) * sy)

    def update_trends(self, t, lvdp, hr):
        self.tc_lvdp.setData(t, lvdp, connect="finite")
        self.tc_hr.setData(t, hr, connect="finite")

    # -------------------------------------------------------------- markers
    def add_marker(self, ts: float, text: str, color: str, dashed: bool, label: bool,
                   on_trends: bool, window_s: float):
        style = Qt.DashLine if dashed else Qt.SolidLine
        short = text if len(text) <= LABEL_MAX else text[:LABEL_MAX - 1] + "…"
        for p in self.plots:
            p.addItem(pg.InfiniteLine(ts, angle=90, pen=pg.mkPen(color, width=1.3, style=style)))
        if label and self.plots:
            # a separate text item above every line, with a background, so that lines of
            # other markers never cross the text
            item = pg.TextItem(short, color=color, anchor=(0, 0.5),
                               fill=pg.mkBrush(self.theme.plot_bg), border=pg.mkPen(color, width=1))
            item.setToolTip(text)
            item.setZValue(1000)
            self.plots[0].addItem(item, ignoreBounds=True)
            self._labels.append((item, ts, 0))
            self._place_labels()
        if on_trends:
            for tp in (self.tp_lvdp, self.tp_hr):
                tp.addItem(pg.InfiniteLine(ts / 60, angle=90, pen=pg.mkPen(color, width=1)))
