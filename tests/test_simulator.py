"""Training simulator: physiology behaves as intended, streaming is deterministic."""
import numpy as np
import pytest

from langrec.analysis.hemodynamics import compute
from langrec.sim.model import CALIBRATION, HeartModel
from langrec.sources.simulator import SimulatorSource

RATE = 500


def lvp(m, seconds):
    return m.generate(int(seconds * RATE))[:, 0] * CALIBRATION["LVP"]


def params(m, seconds=5):
    return compute(lvp(m, seconds), RATE, min_amplitude=5)


def run_ir(isch_min, seed=1, drug=None):
    m = HeartModel("lab", RATE, seed)
    lvp(m, 600)
    if drug:
        m.set_drug(drug, True)
    lvp(m, 600)
    base = params(m)
    m.stop_perfusion()
    lvp(m, isch_min * 60)
    m.restore_perfusion()
    lvp(m, 40 * 60)
    return m, base, params(m)


def test_output_shape_and_deterministic():
    a = HeartModel("lab", RATE, seed=5).generate(3000)
    b = HeartModel("lab", RATE, seed=5).generate(3000)
    assert a.shape == (3000, 4) and np.allclose(a, b)


def test_baseline_is_physiological():
    m = HeartModel("rat", RATE, seed=2)
    lvp(m, 1200)
    p = params(m)
    assert 230 < p.hr < 330 and 70 < p.lvdp < 160 and 0 < p.edp < 15


def test_ischemia_stops_the_heart_and_causes_contracture():
    m = HeartModel("lab", RATE, seed=1)
    lvp(m, 600)
    m.stop_perfusion()
    lvp(m, 4 * 60)
    p = params(m)
    assert p.lvdp is None or p.lvdp < 5
    lvp(m, 20 * 60)
    assert params(m).edp > 30                     # contracture
    assert m.stats["contracture_onset_s"] is not None


def test_recovery_depends_on_ischemia_duration():
    _, b10, r10 = run_ir(10)
    _, b30, r30 = run_ir(30)
    assert r10.lvdp / b10.lvdp > 0.6
    assert r30.lvdp / b30.lvdp < 0.35


def test_cardioprotector_before_ischemia_helps():
    _, b, r = run_ir(20)
    _, bp, rp = run_ir(20, drug="prot")
    assert rp.lvdp / bp.lvdp > r.lvdp / b.lvdp + 0.3


def test_isoproterenol_raises_rate_and_force():
    m = HeartModel("lab", RATE, seed=3)
    lvp(m, 1200)
    before = params(m)
    m.set_drug("iso", True)
    lvp(m, 300)
    after = params(m)
    assert after.hr > before.hr * 1.2 and after.lvdp > before.lvdp * 1.3


def test_kcl_arrests_and_washout_restarts():
    m = HeartModel("lab", RATE, seed=4)
    lvp(m, 600)
    m.set_drug("kcl", True)
    lvp(m, 300)
    assert params(m).hr == 0
    m.washout()
    lvp(m, 900)
    assert params(m).hr > 100


def test_calibration_pressure_is_exact():
    m = HeartModel("lab", RATE, seed=1)
    m.cal_pressure = 100.0
    assert abs(np.mean(lvp(m, 2)) - 100) < 0.5


def test_source_follows_clock_and_reports_events():
    t = [0.0]
    src = SimulatorSource("lab", rate=RATE, seed=1, speed=10, clock=lambda: t[0])
    src.start()
    t[0] = 1.0
    block, _ = src.read()
    assert block.shape == (5000, 4)
    src.model.stop_perfusion()
    events = []
    for _ in range(40):
        t[0] += 1.0
        events += src.read()[1]
    assert any(e.text == "ev.arrest" for e in events)
