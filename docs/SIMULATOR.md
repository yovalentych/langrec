# Training simulator

A virtual Langendorff-perfused heart for learning the workflow: stabilisation, setting a
baseline, ischemia, reperfusion, drugs, calibration, recognising artefacts. It generates four
channels at 500 Hz — **LVP** (balloon pressure), **Perf** (perfusion pressure), **Flow**
(coronary flow) and **ECG** — and reacts to the *Virtual rig* panel.

Implementation: `langrec/sim/model.py` (model), `langrec/sources/simulator.py` (source).

> This is a **phenomenological teaching model**. It reproduces what an experimenter sees, not
> the underlying ion currents or metabolism. Do not use it to predict experimental results.

## Data basis
The default **Lab** profile was tuned on real ischemia–reperfusion recordings made with the
legacy ISCHEMIA program (2010–2011). Only derived numbers were used:

| Observation in the recordings | Model |
|---|---|
| LVDP rises 30–50 % during the first 15–20 min | stabilisation from 65 % with τ ≈ 6 min |
| contractions fade within 1–3 min of global ischemia, HR falls, then arrest | function decays with τ ≈ 35 s; arrest below 4 % |
| ~9 min ischemia → full recovery; ~17 min → ~25 %; ~30 min → ~35 % with large contracture | logistic loss, 50 % at ≈ 13 min (±15 % per heart) |
| EDP rises at reperfusion and decays over tens of minutes | reperfusion contracture ∝ injury, τ ≈ 10 min |
| chaotic rhythm for minutes after reperfusion | VT/VF/ectopic hazard peaking after 10–25 min ischemia, decaying τ ≈ 3 min |
| function recovers over 10–20 min | stunning, τ ≈ 5–10 min |
| beat shape: rise 50–70 ms (10–100 %), relaxation 90–100 ms, \|dP/dt min\| ≈ 0.6 × dP/dt max | cosine rise/fall with those durations |
| HR 120–200 bpm | 165 bpm ±10 % |

Pressure calibration is not stored in the legacy files, so absolute pressures (baseline LVDP
≈ 100 mmHg, EDP ≈ 6 mmHg) are typical values, not measurements. The **Rat** and **Mouse**
profiles use typical literature values at 37 °C.

## What reacts to what
| Action | Effect |
|---|---|
| Stop perfusion | flow → 0, perfusion pressure → ~0 within seconds; no drug delivery or washout; contractions fail; ST elevation; arrest; ischemic contracture after ~10–15 min |
| Restore perfusion | hyperaemic flow overshoot; reperfusion contracture; arrhythmias; stunning; recovery set by ischemia duration and protection |
| Isoproterenol | ↑HR ~35 %, ↑LVDP ~50 %, faster relaxation, ↑flow, more arrhythmias |
| Propranolol | ↓HR, ↓contractility; blunts isoproterenol by 80 % |
| Verapamil | ↓contractility ~55 %, ↓HR, vasodilation |
| Adenosine | ↑flow ~80 %, ↓HR, dropped beats (AV block) |
| Cardioprotector | if present **before** ischemia: later contracture, higher tolerance, fewer arrhythmias |
| KCl cardioplegia | diastolic arrest; protects during ischemia; heart restarts after washout |
| Short ischemias (2–7 min) followed by ≥5 min reperfusion | ischemic preconditioning: higher tolerance in the next 90 min |
| Balloon volume | sets EDP; Frank–Starling effect on LVDP |
| Calibration pressure 0 / 100 | LVP channel shows exactly that pressure (for two-point calibration practice) |
| Artefact / zero drift / 50 Hz hum | spike on LVP and Perf / slow LVP offset / mains interference on LVP and ECG |

Drug concentrations approach their target with τ = 40 s (wash-in) and 120 s (washout).
Each heart (seed) differs: HR, LVDP, flow, ischemic tolerance, contracture onset, arrhythmia
propensity. The *Experiment summary* reveals these hidden properties at the end.

## Exercises
1. **Calibration** — start *Uncalibrated*, apply 0 and 100 mmHg, use *Take current voltage* in
   the two-point calibration, check that LVP reads in mmHg.
2. **Classic I/R** — 20 min stabilisation, baseline, 30 min global ischemia, 60 min reperfusion.
   Note contracture onset and LVDP recovery.
3. **Ischemic tolerance** — repeat with 10, 15, 20 min ischemia on new hearts; estimate the 50 % point.
4. **Protection** — give the cardioprotector or KCl before ischemia; compare recovery.
5. **Preconditioning** — 2 × 5 min ischemia / 5 min reperfusion, then 30 min ischemia.
6. **Pharmacology** — isoproterenol dose effect, then propranolol on top.
7. **Troubleshooting** — switch on hum and drift, fix them with the notch filter and recalibration.
