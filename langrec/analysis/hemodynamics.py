"""Haemodynamic parameters from the left-ventricular pressure (LVP) curve.

For a window of signal (by default the last 5 s) the following are computed:
  * hr        — heart rate, bpm (from peak-to-peak intervals);
  * sys       — systolic pressure (median of the peaks);
  * edp       — end-diastolic pressure (median of the minima between peaks);
  * lvdp      — LV developed pressure = sys − edp;
  * dpdt_max / dpdt_min — maximal rates of pressure rise and fall (median per beat), units/s;
  * rpp       — rate-pressure product lvdp × hr.

The peak detector is deliberately simple and depends on numpy only: a threshold half-way
between the 5th and 95th percentiles of the window plus a refractory period of 0.09 s
(up to ~660 bpm, enough for a mouse heart). If the swing is smaller than `min_amplitude`
(the heart does not contract, e.g. during global ischemia), contraction parameters are
not computed: hr = 0, lvdp and dP/dt = None, but edp is still reported so that an
ischemic contracture is visible.

Caveat: the old recordings have only 100 Hz per channel, which clips the dP/dt peak.
A new board should sample at >= 500–1000 Hz (docs/HARDWARE.md).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class HemoParams:
    hr: float | None = None
    sys: float | None = None
    edp: float | None = None
    lvdp: float | None = None
    dpdt_max: float | None = None
    dpdt_min: float | None = None
    rpp: float | None = None
    n_beats: int = 0

    def as_row(self) -> dict:
        return {k: (None if v is None else round(float(v), 4)) for k, v in self.__dict__.items()}


def find_peaks_simple(x: np.ndarray, rate: float, refractory_s: float = 0.09,
                      min_amplitude: float = 0.0) -> np.ndarray:
    """Indices of systolic peaks."""
    if len(x) < 3:
        return np.array([], dtype=int)
    lo, hi = np.percentile(x, 5), np.percentile(x, 95)
    if hi - lo <= min_amplitude:
        return np.array([], dtype=int)
    thr = lo + 0.5 * (hi - lo)
    # local maxima above the threshold
    cand = np.flatnonzero((x[1:-1] >= x[:-2]) & (x[1:-1] > x[2:]) & (x[1:-1] > thr)) + 1
    refr = max(1, int(refractory_s * rate))
    peaks: list[int] = []
    for i in cand:
        if peaks and i - peaks[-1] < refr:
            if x[i] > x[peaks[-1]]:
                peaks[-1] = i
        else:
            peaks.append(int(i))
    return np.asarray(peaks, dtype=int)


def compute(lvp: np.ndarray, rate: float, min_amplitude: float = 0.1) -> HemoParams:
    """Parameters for a window of pressure signal (in channel units)."""
    p = HemoParams()
    x = np.asarray(lvp, dtype=float)
    if len(x) < rate:            # less than a second: nothing to compute
        return p
    peaks = find_peaks_simple(x, rate, min_amplitude=min_amplitude)
    # minima between neighbouring peaks = end-diastolic level
    mins = [int(a + np.argmin(x[a:b])) for a, b in zip(peaks[:-1], peaks[1:])]
    if len(peaks) < 3:
        p.edp = float(np.median(x))
        p.hr = 0.0
        return p

    p.n_beats = len(peaks)
    p.hr = 60.0 * rate / float(np.median(np.diff(peaks)))
    p.sys = float(np.median(x[peaks]))
    p.edp = float(np.median(x[mins]))
    p.lvdp = p.sys - p.edp
    p.rpp = p.lvdp * p.hr

    d = np.gradient(x) * rate
    # for every cycle "minimum -> next minimum" take the max and min of the derivative
    ups, downs = [], []
    for a, b in zip(mins[:-1], mins[1:]):
        seg = d[a:b + 1]
        if len(seg) > 2:
            ups.append(seg.max())
            downs.append(seg.min())
    if ups:
        p.dpdt_max = float(np.median(ups))
        p.dpdt_min = float(np.median(downs))
    return p
