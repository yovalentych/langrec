"""Core tests. Run: python -m pytest -q

Tests on real ISCHEMIA files are skipped unless a folder with such files exists.
Point LANGREC_ARCHIVE at any folder that contains ISCH*.DAT files (searched recursively).
"""
import os
from pathlib import Path

import numpy as np
import pytest

from langrec.analysis.hemodynamics import compute, find_peaks_simple
from langrec.channels import ChannelConfig
from langrec.io.ischemia_dat import find_recordings, read_dat
from langrec.recorder import SessionRecorder
from langrec.sources.replay import ReplaySource

ARCHIVE = Path(os.environ.get("LANGREC_ARCHIVE", Path(__file__).parent / "data" / "legacy"))


def _find_session() -> Path | None:
    """A folder with at least two full-length (20 min) recordings that have markers."""
    if not ARCHIVE.exists():
        return None
    for folder in sorted({p.parent for p in ARCHIVE.rglob("ISCH*.DAT")}):
        full = [p for p in folder.glob("ISCH*.DAT") if p.stat().st_size > 700_000]
        if len(full) >= 2 and any(folder.glob("ISCH*.MRK")):
            return folder
    return None


SESSION = _find_session()
need_archive = pytest.mark.skipif(SESSION is None, reason="no legacy ISCHEMIA recordings available")


def synthetic_lvp(hr=240, rate=1000, seconds=6, edp=8.0, lvdp=90.0):
    t = np.arange(int(seconds * rate)) / rate
    phase = (t * hr / 60) % 1
    # systole takes ~35 % of the cycle
    wave = np.where(phase < 0.35, np.sin(np.pi * phase / 0.35) ** 2, 0.0)
    return edp + lvdp * wave


def test_hemodynamics_synthetic():
    rate = 1000
    p = compute(synthetic_lvp(rate=rate), rate)
    assert p.hr == pytest.approx(240, rel=0.01)
    assert p.edp == pytest.approx(8.0, abs=0.5)
    assert p.lvdp == pytest.approx(90.0, rel=0.02)
    # analytic maximum of the derivative: lvdp * pi / 0.35 / period
    expected = 90 * np.pi / (0.35 * 0.25)
    assert p.dpdt_max == pytest.approx(expected, rel=0.03)
    assert p.dpdt_min == pytest.approx(-expected, rel=0.03)


def test_mouse_rate_is_detected():
    p = compute(synthetic_lvp(hr=550, rate=1000), 1000)
    assert p.hr == pytest.approx(550, rel=0.02)


def test_no_beats_when_flat():
    p = compute(np.full(1000, 30.0) + np.random.default_rng(0).normal(0, 0.01, 1000), 100)
    assert p.hr == 0 and p.lvdp is None and p.edp == pytest.approx(30, abs=0.1)


def test_refractory_merges_double_peaks():
    x = synthetic_lvp(rate=100)
    pk = find_peaks_simple(x, 100)
    assert np.all(np.diff(pk) >= 15)


@need_archive
def test_read_dat_structure():
    files = find_recordings(SESSION)
    rec = read_dat(files[0])
    assert rec.rate == 100
    assert rec.volts.shape[1] == 3
    assert rec.header.start is not None
    assert np.all(np.abs(rec.volts) <= 10.24 + 1e-3)


@need_archive
def test_find_recordings_sorted_by_time():
    files = find_recordings(SESSION)
    starts = [read_dat(f).header.start for f in files]
    assert starts == sorted(starts)
    assert all(f.name.upper().startswith("ISCH") for f in files)


@need_archive
def test_replay_clock_pause_and_events():
    files = [f for f in find_recordings(SESSION) if f.stat().st_size > 700_000][:2]
    marker_rec = next(read_dat(f) for f in find_recordings(SESSION) if f.with_suffix(".MRK").exists())
    t = [0.0]
    src = ReplaySource(files, speed=10, clock=lambda: t[0])
    src.start()
    t[0] = 1.0
    block, ev = src.read()
    assert len(block) == 1000            # 1 s x 100 Hz x 10
    assert ev[0].kind == "file"
    src.stop()                           # pause
    t[0] = 50.0
    assert len(src.read()[0]) == 0       # nothing accrues while paused
    src.start()
    t[0] = 51.0
    assert len(src.read()[0]) == 1000
    src.seek(src.total_samples - 10)
    t[0] = 100.0
    src.read()
    assert src.finished
    # markers from MRK files arrive as events at the right sample
    src2 = ReplaySource([marker_rec.path], speed=1000, clock=lambda: t[0])
    src2.start()
    t[0] += 1000.0
    _, ev = src2.read()
    assert [e.sample for e in ev if e.kind == "marker"] == marker_rec.markers


@need_archive
def test_real_heart_has_plausible_rate():
    best = 0.0
    for f in find_recordings(SESSION):
        rec = read_dat(f)
        for s in range(0, len(rec.volts) - 1000, 6000):
            p = compute(rec.volts[s:s + 1000, 0], rec.rate)
            if p.lvdp and p.lvdp > 0.5 and 60 < p.hr < 400:
                best = p.hr
                break
        if best:
            break
    assert 60 < best < 400


def test_recorder_roundtrip(tmp_path):
    chs = [ChannelConfig("LVP", role="lvp", unit="mmHg", units_per_volt=10)]
    r = SessionRecorder(tmp_path, chs, 100, "test", title="trial 1")
    r.write_block(np.arange(5, dtype=float).reshape(-1, 1))
    r.add_marker(3, "Ischemia")
    r.add_params(4, {"hr": 200.0})
    r.close()
    lines = (r.dir / "signals.csv").read_text().splitlines()
    assert lines[0] == "time_s,LVP_mmHg" and len(lines) == 6
    assert "Ischemia" in (r.dir / "markers.csv").read_text(encoding="utf-8")
    assert '"samples": 5' in (r.dir / "session.json").read_text(encoding="utf-8")
