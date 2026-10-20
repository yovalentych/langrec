"""Real-time digital filters for display and analysis.

Raw data is always what gets recorded; filters only change what is shown and what the
parameters are computed from (the filter settings are saved in session.json).

Per channel, in this order:
  1. spike removal — running median over `median_ms` (removes short artefacts, keeps edges);
  2. notch — IIR notch at 50 or 60 Hz (mains hum), Q = 30;
  3. high-pass — Butterworth, 2nd order (baseline drift; mostly for ECG);
  4. low-pass — Butterworth, 4th order (noise).

IIR filters run with scipy.signal.sosfilt and keep their state between blocks, so the
output is identical whether the signal arrives in one piece or in many small blocks.
They are causal (like an analogue filter): a small phase lag, no look-ahead.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
from scipy import signal


@dataclass
class FilterConfig:
    lowpass_hz: float | None = None
    highpass_hz: float | None = None
    notch_hz: float | None = None      # 50 or 60
    median_ms: float | None = None     # spike removal window

    @property
    def active(self) -> bool:
        return any(v for v in asdict(self).values())

    def describe(self) -> list[str]:
        out = []
        if self.median_ms:
            out.append(f"med {self.median_ms:.0f} ms")
        if self.notch_hz:
            out.append(f"notch {self.notch_hz:.0f} Hz")
        if self.highpass_hz:
            out.append(f"HP {self.highpass_hz:g} Hz")
        if self.lowpass_hz:
            out.append(f"LP {self.lowpass_hz:g} Hz")
        return out


class ChannelFilter:
    """Streaming filter chain for one channel."""

    def __init__(self, cfg: FilterConfig, rate: float):
        self.cfg = cfg
        self.rate = rate
        nyq = rate / 2
        sos = []
        if cfg.notch_hz and cfg.notch_hz < nyq * 0.95:
            b, a = signal.iirnotch(cfg.notch_hz, 30.0, fs=rate)
            sos.append(signal.tf2sos(b, a))
        if cfg.highpass_hz and cfg.highpass_hz < nyq * 0.9:
            sos.append(signal.butter(2, cfg.highpass_hz, "highpass", fs=rate, output="sos"))
        if cfg.lowpass_hz and cfg.lowpass_hz < nyq * 0.95:
            sos.append(signal.butter(4, cfg.lowpass_hz, "lowpass", fs=rate, output="sos"))
        self.sos = np.vstack(sos) if sos else None
        self.zi = None
        self.med_w = 0
        if cfg.median_ms:
            w = int(round(cfg.median_ms / 1000 * rate)) | 1
            self.med_w = max(3, w)
        self._med_hist = np.zeros(0)

    def _median(self, x: np.ndarray) -> np.ndarray:
        w = self.med_w
        if not len(self._med_hist):
            self._med_hist = np.full(w - 1, x[0])
        xx = np.concatenate([self._med_hist, x])
        self._med_hist = xx[-(w - 1):]
        return np.median(np.lib.stride_tricks.sliding_window_view(xx, w), axis=1)

    def process(self, x: np.ndarray) -> np.ndarray:
        x = np.asarray(x, dtype=np.float64)
        if len(x) == 0:
            return x
        if self.med_w:
            x = self._median(x)
        if self.sos is not None:
            if self.zi is None:
                # start in steady state for the first value: no big transient at switch-on
                self.zi = signal.sosfilt_zi(self.sos) * x[0]
            x, self.zi = signal.sosfilt(self.sos, x, zi=self.zi)
        return x


class FilterBank:
    """Filters for all channels of a source."""

    def __init__(self, configs: list[FilterConfig], rate: float):
        self.configs = configs
        self.rate = rate
        self.filters = [ChannelFilter(c, rate) for c in configs]

    def process(self, block: np.ndarray) -> np.ndarray:
        if len(block) == 0:
            return block
        out = np.array(block, dtype=np.float32, copy=True)
        for i, f in enumerate(self.filters[:block.shape[1]]):
            out[:, i] = f.process(block[:, i])
        return out

    @property
    def active(self) -> bool:
        return any(c.active for c in self.configs)


def suggested(role: str, rate: float) -> FilterConfig:
    """Sensible starting filters by channel role."""
    if role == "ecg":
        return FilterConfig(lowpass_hz=min(100, rate * 0.4), highpass_hz=0.5, notch_hz=50)
    if role in ("lvp", "perf"):
        return FilterConfig(lowpass_hz=min(30, rate * 0.4), median_ms=None)
    if role == "flow":
        return FilterConfig(lowpass_hz=min(10, rate * 0.4))
    return FilterConfig()
