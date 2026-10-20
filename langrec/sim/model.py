"""Training simulator: a virtual isolated (Langendorff-perfused) heart.

The model generates four channels in real time and reacts to the operator:
left-ventricular pressure (balloon), perfusion pressure, coronary flow and ECG.

It is a *phenomenological* model: it does not solve ion-channel equations, it reproduces
what an experimenter sees. Time constants and magnitudes for the default "lab" profile were
taken from the lab's own ISCHEMIA recordings of 2010-2011 (see docs/SIMULATOR.md):

  * stabilisation: LVDP rises by ~30-50 % during the first 15-20 min (tau ~6 min);
  * global ischemia: contractions fade within 1-3 min (tau ~35 s), heart rate falls, arrest;
  * a ~9 min ischemia recovered fully, ~17 min recovered ~25 %, ~30 min ~35 % with a large
    contracture  ->  50 % recovery at ~13 min of ischemia;
  * reperfusion: chaotic rhythm for several minutes, a rise of end-diastolic pressure
    (reperfusion contracture) that slowly decays, function recovering over 10-20 min (stunning);
  * beat shape: 10-100 % rise 50-70 ms, 100-10 % relaxation 90-100 ms, |dP/dt min| / dP/dt max ~0.6.

Rat and mouse profiles use typical literature values at 37 C instead.

Units: pressures in mmHg, flow in ml/min, ECG in mV, time in seconds. `generate()` returns
*volts*, as a real ADC would; the "virtual transducers" have the gains in CALIBRATION.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

CHANNELS = ["LVP", "Perf", "Flow", "ECG"]
UNITS = {"LVP": "mmHg", "Perf": "mmHg", "Flow": "ml/min", "ECG": "mV"}
CALIBRATION = {"LVP": 50.0, "Perf": 50.0, "Flow": 5.0, "ECG": 1.0}   # units per volt
ROLES = {"LVP": "lvp", "Perf": "perf", "Flow": "flow", "ECG": "ecg"}


@dataclass(frozen=True)
class Profile:
    key: str
    hr: float            # bpm at baseline
    lvdp: float          # mmHg
    edp: float           # mmHg (balloon volume)
    flow: float          # ml/min
    perf: float          # mmHg (constant-pressure perfusion)
    t50_min: float       # minutes of ischemia giving 50 % functional loss
    contracture_min: float  # onset of ischemic contracture, minutes
    rise_ms: float       # 10-100 % pressure rise
    relax_ms: float      # 100-10 % relaxation


PROFILES = {
    # tuned on the lab recordings (see module docstring)
    "lab": Profile("lab", hr=165, lvdp=100, edp=6, flow=11, perf=70, t50_min=13,
                   contracture_min=14, rise_ms=60, relax_ms=95),
    "rat": Profile("rat", hr=280, lvdp=110, edp=7, flow=12, perf=75, t50_min=22,
                   contracture_min=12, rise_ms=45, relax_ms=70),
    "mouse": Profile("mouse", hr=400, lvdp=85, edp=6, flow=2.5, perf=80, t50_min=18,
                     contracture_min=9, rise_ms=30, relax_ms=50),
}

DRUGS = ["iso", "prop", "verap", "aden", "prot", "kcl"]


def _gauss(t, mu, sd, amp):
    return amp * np.exp(-0.5 * ((t - mu) / sd) ** 2)


def _approach(x, target, dt, tau):
    return target + (x - target) * math.exp(-dt / tau)


class HeartModel:
    def __init__(self, profile: str = "lab", rate: float = 500.0, seed: int | None = None):
        self.p = PROFILES[profile]
        self.rate = float(rate)
        self.seed = seed if seed is not None else int(np.random.default_rng().integers(1, 10**6))
        self.rng = np.random.default_rng(self.seed)
        r, p = self.rng, self.p
        # individual heart: each "animal" is a little different
        self.hr0 = p.hr * r.uniform(0.9, 1.1)
        self.lvdp0 = p.lvdp * r.uniform(0.85, 1.15)
        self.flow0 = p.flow * r.uniform(0.85, 1.15)
        self.t50 = p.t50_min * 60 * r.uniform(0.85, 1.15)
        self.t_contr = p.contracture_min * 60 * r.uniform(0.85, 1.2)
        self.arrh = r.uniform(0.6, 1.4)

        self.edp_set = p.edp
        self.t = 0.0                  # model time, s
        self.sample = 0               # samples generated so far
        self.perfused = True
        self.isch_t = 0.0             # duration of the current ischemia, s
        self.isch_start: float | None = None
        self.reperf_t: float | None = None
        self.last_isch = 0.0
        self.recovery = 1.0           # achievable fraction of function (permanent damage)
        self.stun = 0.0               # extra transient depression after reperfusion
        self.func = 0.65              # current function (stabilisation starts at ~65 %)
        self.contr = 0.0              # contracture, mmHg added to EDP
        self.contr_resid = 0.0        # level the contracture relaxes to after reperfusion
        self.perf_level = p.perf
        self.flow_level = self.flow0
        self.prot_int = 0.0           # protective drug exposure during ischemia, s
        self.risk = 0.0               # reperfusion arrhythmia risk
        self.pc_times: list[float] = []   # ends of short "preconditioning" ischemias

        self.drug = {k: 0.0 for k in DRUGS}
        self.drug_on = {k: False for k in DRUGS}

        self.rhythm = "sinus"         # sinus | vt | vf | arrest
        self.rhythm_left = 0.0
        self.next_ectopic = False

        # artefacts / training complications
        self.noise = 1.0
        self.hum = False
        self.drift_on = False
        self.drift = 0.0
        self.spike = False
        self.cal_pressure: float | None = None

        self.events: list[tuple[int, str, dict]] = []    # (sample, key, params)
        self.stats = {"vf_episodes": 0, "vf_time": 0.0, "vt_episodes": 0, "ectopics": 0,
                      "contracture_onset_s": None, "ischemias": [], "arrest_at_s": None}
        self._buf = np.zeros((0, 4))

    # ------------------------------------------------------------------ actions
    def _event(self, key: str, **kw):
        self.events.append((self.sample, key, kw))

    def stop_perfusion(self):
        if self.perfused:
            self.perfused = False
            self.isch_t = 0.0
            self.isch_start = self.t
            self.prot_int = 0.0
            self.stats["contracture_onset_s"] = None
            self.stats["arrest_at_s"] = None
            self.reperf_t = None

    def restore_perfusion(self):
        if self.perfused:
            return
        d = self.isch_t
        prot = self.prot_int / max(d, 1.0)
        pc = self._preconditioning()
        t50 = self.t50 * (1 + 0.8 * prot + 0.5 * pc)
        slope = 0.2 * self.t50

        def logistic(x):
            return 1 / (1 + math.exp(-(x - t50) / slope))

        loss = max(0.0, (logistic(d) - logistic(0)) / (1 - logistic(0)))
        self.recovery *= 1 - 0.85 * loss
        self.stun = 0.5 * min(1.0, d / 600)
        # reperfusion contracture: EDP jumps, then slowly relaxes to a residual level
        self.contr = max(self.contr, 45 * loss)
        self.contr_resid = 25 * loss
        bell = math.exp(-((d / 60 - 15) / 10) ** 2)      # most arrhythmias after 10-25 min
        self.risk = self.arrh * bell * (1 - 0.6 * self.drug["prot"]) * (1 - 0.5 * pc)
        if 120 <= d <= 420:
            self.pc_times.append(self.t)
        self.stats["ischemias"].append({"duration_s": round(d, 1), "loss": round(loss, 3)})
        self.last_isch = d
        self.perfused = True
        self.reperf_t = 0.0
        self.isch_start = None

    def _preconditioning(self) -> float:
        recent = [t for t in self.pc_times if self.t - t < 90 * 60 and self.t - t > 5 * 60]
        return min(1.0, len(recent) / 2)

    def set_drug(self, key: str, on: bool):
        self.drug_on[key] = on

    def washout(self):
        for k in DRUGS:
            self.drug_on[k] = False

    def set_balloon(self, edp: float):
        self.edp_set = float(edp)

    def artefact(self):
        self.spike = True

    def new_baseline_drift(self, on: bool):
        self.drift_on = on
        if not on:
            self.drift = 0.0

    # ----------------------------------------------------------- slow dynamics
    def _update(self, dt: float):
        c = self.drug
        for k in DRUGS:
            target = 1.0 if self.drug_on[k] else 0.0
            tau = 40.0 if target > c[k] else 120.0
            if not self.perfused:          # no flow = no drug delivery or washout
                continue
            c[k] = _approach(c[k], target, dt, tau)

        if not self.perfused:
            self.isch_t += dt
            self.func = _approach(self.func, 0.0, dt, 35.0)
            self.prot_int += (c["prot"] + 0.8 * c["kcl"]) * dt
            onset = self.t_contr * (1 + 0.4 * c["prot"] + 0.6 * c["kcl"] + 0.3 * self._preconditioning())
            target_contr = 55 / (1 + math.exp(-(self.isch_t - onset) / 90))
            self.contr = max(self.contr, target_contr)
            if self.contr > 5 and self.stats["contracture_onset_s"] is None:
                self.stats["contracture_onset_s"] = round(self.isch_t, 1)
                self._event("ev.contracture", minutes=self.isch_t / 60)
        else:
            if self.reperf_t is not None:
                self.reperf_t += dt
                stun = self.stun * math.exp(-self.reperf_t / 600)
                tau = 300.0
            else:
                stun, tau = 0.0, 360.0         # stabilisation
            hours = self.t / 3600
            target = self.recovery * (1 - stun) * (1 - 0.06 * hours)
            self.func = _approach(self.func, target, dt, tau)
            self.contr = _approach(self.contr, self.contr_resid, dt, 600.0)

        # perfusion pressure and flow follow the tap within ~1-2 s
        self.perf_level = _approach(self.perf_level, self.p.perf if self.perfused else 2.0, dt, 1.5)
        if self.perfused:
            vaso = (1 + 0.3 * c["iso"]) * (1 + 0.25 * c["verap"]) * (1 + 0.8 * c["aden"])
            hyper = 1.0
            if self.reperf_t is not None:
                hyper += 0.9 * math.exp(-self.reperf_t / 60) * min(1.0, self.last_isch / 300)
            flow_t = self.flow0 * vaso * hyper * (0.75 + 0.25 * self.recovery)
        else:
            flow_t = 0.0
        self.flow_level = _approach(self.flow_level, flow_t, dt, 1.0)

        if self.drift_on:
            self.drift += dt * 0.08          # mmHg/s, slow transducer drift

    # ------------------------------------------------------------------ rhythm
    def _hr(self) -> float:
        c = self.drug
        iso = c["iso"] * (1 - 0.8 * c["prop"])
        hr = self.hr0 * (1 + 0.35 * iso) * (1 - 0.2 * c["prop"]) * (1 - 0.15 * c["verap"]) \
            * (1 - 0.25 * c["aden"])
        if not self.perfused:
            hr *= 0.45 + 0.55 * min(1.0, self.func / 0.6)
        return hr

    def _inotropy(self) -> float:
        c = self.drug
        iso = c["iso"] * (1 - 0.8 * c["prop"])
        fs = 1 + 0.025 * (self.edp_set - self.p.edp)      # Frank-Starling
        return (1 + 0.5 * iso) * (1 - 0.2 * c["prop"]) * (1 - 0.55 * c["verap"]) \
            * (1 - c["kcl"]) * max(0.3, min(1.3, fs))

    def _choose_rhythm(self):
        c = self.drug
        if c["kcl"] > 0.6:
            if self.rhythm != "arrest":
                self._event("ev.kcl_arrest")
            self.rhythm = "arrest"
            return
        if not self.perfused and self.func < 0.04:
            if self.rhythm != "arrest":
                self.stats["arrest_at_s"] = round(self.isch_t, 1)
                self._event("ev.arrest", minutes=self.isch_t / 60)
            self.rhythm = "arrest"
            return
        if self.rhythm == "arrest":
            if self.perfused and self.func > 0.08 and c["kcl"] < 0.3:
                self.rhythm = "sinus"
                self._event("ev.restart")
            return
        if self.rhythm in ("vt", "vf"):
            if self.rhythm_left > 0:
                return
            self._event("ev.sinus_back")
            self.rhythm = "sinus"
        # new arrhythmia?
        if self.perfused and self.reperf_t is not None and self.reperf_t < 900:
            iso = c["iso"] * (1 - 0.8 * c["prop"])
            h = self.risk * math.exp(-self.reperf_t / 180) * (1 + 2 * iso)
            u = self.rng.random()
            if u < 0.003 * h:
                self.rhythm = "vf"
                self.rhythm_left = float(min(240, self.rng.exponential(45)))
                self.stats["vf_episodes"] += 1
                self._event("ev.vf")
            elif u < 0.012 * h:
                self.rhythm = "vt"
                self.rhythm_left = float(self.rng.uniform(2, 15))
                self.stats["vt_episodes"] += 1
                self._event("ev.vt")
            elif u < 0.08 * h:
                self.next_ectopic = True
        base = 0.002 * (1 + 4 * c["iso"])
        if self.rng.random() < base:
            self.next_ectopic = True

    # --------------------------------------------------------------- waveforms
    def _segment(self) -> np.ndarray:
        """One heartbeat (or a short piece of arrest / VF) in physical units, shape (n, 4)."""
        self._choose_rhythm()
        rate = self.rate
        edp = self.edp_set + self.contr
        lvdp = self.lvdp0 * self.func * self._inotropy()
        isch_st = 0.0 if self.perfused else 0.5 * (1 - self.func)
        if self.reperf_t is not None:
            isch_st = 0.3 * math.exp(-self.reperf_t / 60) * min(1.0, self.last_isch / 600)

        if self.rhythm == "arrest":
            dur = 0.25
            n = int(dur * rate)
            t = np.arange(n) / rate
            lv = np.full(n, edp)
            ecg = np.zeros(n)
            comp = np.zeros(n)
        elif self.rhythm == "vf":
            dur = 0.5
            n = int(dur * rate)
            t = np.arange(n) / rate
            f1, f2 = self.rng.uniform(8, 14, 2)
            ph = self.rng.uniform(0, 2 * np.pi, 2)
            osc = np.sin(2 * np.pi * f1 * (t + self.t) + ph[0]) + 0.6 * np.sin(2 * np.pi * f2 * (t + self.t) + ph[1])
            lv = edp + 4 + 3 * osc
            ecg = 0.5 * osc * self.rng.uniform(0.6, 1.3)
            comp = 0.2 * (osc + 1.6) / 3.2
            self.rhythm_left -= dur
            self.stats["vf_time"] += dur
        else:
            hr = self._hr()
            vt = self.rhythm == "vt"
            period = 60 / (min(700.0, hr * 2.4) if vt else hr)
            period *= 1 + self.rng.normal(0, 0.012)
            amp = lvdp * (0.35 if vt else 1.0)
            ectopic = self.next_ectopic and not vt
            if ectopic:
                self.next_ectopic = False
                self.stats["ectopics"] += 1
                period *= 0.6
                amp *= 0.55
            # AV block under adenosine: a dropped beat (P wave without contraction)
            dropped = (not vt) and self.rng.random() < 0.35 * self.drug["aden"]
            n = max(4, int(round(period * rate)))
            t = np.arange(n) / rate
            iso = self.drug["iso"] * (1 - 0.8 * self.drug["prop"])
            rise = self.p.rise_ms / 1000 * (1 - 0.25 * iso) / 0.9      # 10-100 % -> 0-100 %
            relax = self.p.relax_ms / 1000 * (1 - 0.25 * iso) / 0.9
            scale = min(1.0, 0.85 * period / (rise + relax))       # very fast rates squeeze the beat
            rise, relax = rise * scale, relax * scale
            emd = 0.010                                            # QRS -> pressure rise
            u = t - emd
            shape = np.where((u >= 0) & (u < rise), 0.5 - 0.5 * np.cos(np.pi * u / rise), 0.0)
            shape = np.where((u >= rise) & (u < rise + relax),
                             0.5 + 0.5 * np.cos(np.pi * (u - rise) / relax), shape)
            if dropped:
                shape[:] = 0
            fill = 1.5 * np.clip((t - emd - rise - relax) / max(1e-3, period - emd - rise - relax), 0, 1)
            lv = edp + amp * shape + fill * self.func
            comp = shape
            # ECG
            if vt:
                ecg = _gauss(t, 0.02, 0.010, 1.6) - _gauss(t, 0.05, 0.012, 0.6) \
                    - _gauss(t, emd + rise + relax * 0.6, 0.025, 0.35)
            else:
                ecg = _gauss(t, period - 0.03, 0.008, 0.12)            # P wave
                if not dropped:
                    t_t = emd + rise + relax * 0.6
                    st = isch_st * np.clip((t - 0.02) / 0.01, 0, 1) * np.clip((t_t + 0.03 - t) / 0.02, 0, 1)
                    ecg = ecg - _gauss(t, 0.004, 0.002, 0.12) + _gauss(t, 0.010, 0.0035, 1.3) \
                        - _gauss(t, 0.017, 0.003, 0.3) + _gauss(t, t_t, 0.022, 0.32 * (1 - 1.5 * isch_st)) + st
                if ectopic:
                    ecg = _gauss(t, 0.015, 0.009, -1.4) + _gauss(t, 0.05, 0.02, 0.4)
            dur = n / rate
            if vt:
                self.rhythm_left -= dur

        n = len(t)
        perf = self.perf_level + 2.5 * comp * (self.perf_level / max(1.0, self.p.perf))
        flow = self.flow_level * (1 - 0.35 * comp)
        out = np.column_stack([lv, perf, flow, ecg])
        self._update(dur)
        self.t += dur
        return out

    # ---------------------------------------------------------------- output
    def _artefacts(self, x: np.ndarray, t0: float) -> np.ndarray:
        n = len(x)
        t = t0 + np.arange(n) / self.rate
        s = self.noise
        x[:, 0] += self.rng.normal(0, 0.35 * s, n) + self.drift
        x[:, 1] += self.rng.normal(0, 0.3 * s, n)
        x[:, 2] += self.rng.normal(0, 0.04 * s, n)
        x[:, 3] += self.rng.normal(0, 0.015 * s, n)
        if self.hum:
            hum = np.sin(2 * np.pi * 50 * t)
            x[:, 0] += 1.2 * hum
            x[:, 3] += 0.12 * hum
        if self.spike and n > 20:
            i = int(self.rng.integers(7, n - 7))
            w = np.arange(-6, 7)
            x[i + w, 0] += 45 * np.exp(-0.5 * (w / 2.0) ** 2) * self.rng.choice([-1, 1])
            x[i + w, 1] += 15 * np.exp(-0.5 * (w / 2.0) ** 2)
            self.spike = False
        if self.cal_pressure is not None:
            x[:, 0] = self.cal_pressure + self.drift + self.rng.normal(0, 0.2, n)
        return x

    def generate(self, n: int) -> np.ndarray:
        """Next n samples in volts, shape (n, 4)."""
        while len(self._buf) < n:
            t0 = self.t
            seg = self._artefacts(self._segment(), t0)
            self._buf = np.concatenate([self._buf, seg])
        out, self._buf = self._buf[:n], self._buf[n:]
        self.sample += n
        gains = np.array([CALIBRATION[c] for c in CHANNELS])
        return out / gains

    def pop_events(self):
        ev, self.events = self.events, []
        return ev

    # ---------------------------------------------------------- for teaching
    def explain(self) -> list[tuple[str, dict]]:
        """What is happening physiologically right now: (message key, params)."""
        out = []
        c = self.drug
        if not self.perfused:
            m = self.isch_t / 60
            if self.func > 0.3:
                out.append(("ex.isch_early", {}))
            elif self.rhythm != "arrest":
                out.append(("ex.isch_fading", {}))
            elif self.contr < 5:
                out.append(("ex.isch_arrest", {}))
            else:
                out.append(("ex.isch_contracture", {}))
            out.append(("ex.isch_time", {"m": m, "t50": self.t50 / 60}))
        elif self.reperf_t is not None and self.reperf_t < 1800:
            if self.rhythm == "vf":
                out.append(("ex.vf", {}))
            elif self.rhythm == "vt":
                out.append(("ex.vt", {}))
            elif self.reperf_t < 120:
                out.append(("ex.reperf_early", {}))
            else:
                out.append(("ex.stunning", {"rec": 100 * self.recovery}))
            if self.contr > 5:
                out.append(("ex.reperf_contracture", {}))
        elif self.t < 20 * 60 and self.func < 0.95 * self.recovery:
            out.append(("ex.stabilisation", {}))
        else:
            out.append(("ex.stable", {}))
        for k in DRUGS:
            if c[k] > 0.1:
                out.append((f"ex.drug.{k}", {"pct": 100 * c[k]}))
        if self.cal_pressure is not None:
            out.append(("ex.calibration", {"p": self.cal_pressure}))
        if self.drift_on:
            out.append(("ex.drift", {}))
        if self.hum:
            out.append(("ex.hum", {}))
        return out

    def summary(self) -> dict:
        s = dict(self.stats)
        s["seed"] = self.seed
        s["profile"] = self.p.key
        s["true_t50_min"] = round(self.t50 / 60, 1)
        s["true_contracture_min"] = round(self.t_contr / 60, 1)
        s["achievable_recovery_pct"] = round(100 * self.recovery, 1)
        s["vf_time"] = round(s["vf_time"], 1)
        return s
