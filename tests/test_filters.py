import numpy as np
import pytest

from langrec.analysis.filters import ChannelFilter, FilterBank, FilterConfig


def test_streaming_equals_one_block():
    rng = np.random.default_rng(0)
    x = rng.normal(size=5000)
    cfg = FilterConfig(lowpass_hz=30, highpass_hz=0.5, notch_hz=50, median_ms=10)
    one = ChannelFilter(cfg, 500).process(x)
    f = ChannelFilter(cfg, 500)
    parts = np.concatenate([f.process(c) for c in np.array_split(x, 37)])
    assert np.allclose(one, parts)


def test_notch_removes_hum_keeps_slow_signal():
    rate = 500
    t = np.arange(10 * rate) / rate
    slow = np.sin(2 * np.pi * 3 * t)
    y = ChannelFilter(FilterConfig(notch_hz=50), rate).process(slow + np.sin(2 * np.pi * 50 * t))
    tail = slice(5 * rate, None)
    assert np.std(y[tail] - slow[tail]) < 0.1


def test_median_removes_spike():
    x = np.zeros(1000)
    x[500] = 100
    y = ChannelFilter(FilterConfig(median_ms=10), 500).process(x)
    assert np.abs(y).max() == 0


def test_filters_above_nyquist_are_ignored():
    f = ChannelFilter(FilterConfig(notch_hz=50, lowpass_hz=80), 100)
    assert f.sos is None


def test_bank_passes_unfiltered_channels():
    b = FilterBank([FilterConfig(lowpass_hz=10)], 500)
    blk = np.ones((100, 2), dtype=np.float32)
    out = b.process(blk)
    assert out.shape == (100, 2) and np.allclose(out[:, 1], 1) and np.allclose(out[:, 0], 1, atol=1e-3)
