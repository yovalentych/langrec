"""Channel settings: name, role and linear calibration from volts to physical units.

value = (volts - zero_v) * units_per_volt

The role tells the analysis which channel to use: HR, LVDP, dP/dt etc. are computed
from the channel with role "lvp" (left-ventricular pressure).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

ROLE_KEYS = ["lvp", "dpdt", "perf", "flow", "ecg", "other"]


@dataclass
class ChannelConfig:
    name: str
    role: str = "other"
    unit: str = "V"
    units_per_volt: float = 1.0
    zero_v: float = 0.0
    enabled: bool = True

    def to_units(self, volts):
        return (volts - self.zero_v) * self.units_per_volt


# Old ISCHEMIA recordings. The roles are a guess from the waveforms (see docs/DAT_FORMAT.md);
# the calibration was not stored in the files, so the units stay volts.
LEGACY_DEFAULT = [
    ChannelConfig("CH00", role="lvp"),
    ChannelConfig("CH01", role="perf"),
    ChannelConfig("CH02", role="dpdt"),
]


def simulator_channels(calibrated: bool = True) -> list[ChannelConfig]:
    """Channels of the training simulator, optionally with its 'virtual transducer' gains."""
    from .sim.model import CALIBRATION, CHANNELS, ROLES, UNITS
    out = []
    for name in CHANNELS:
        if calibrated:
            out.append(ChannelConfig(name, ROLES[name], UNITS[name], CALIBRATION[name]))
        else:
            out.append(ChannelConfig(name, ROLES[name], "V", 1.0))
    return out


def arduino_channels() -> list[ChannelConfig]:
    """Arduino prototype: A0 = generated 'heart' curve, A1 = knob, A2 = light sensor (pulse)."""
    return [
        ChannelConfig("A0 heart", role="lvp", unit="V"),
        ChannelConfig("A1 knob", role="other", unit="V"),
        ChannelConfig("A2 light", role="other", unit="V"),
        ChannelConfig("A3", role="other", unit="V", enabled=False),
    ]


def save_channels(chs: list[ChannelConfig], path: str | Path) -> None:
    Path(path).write_text(json.dumps([asdict(c) for c in chs], ensure_ascii=False, indent=2),
                          encoding="utf-8")


def load_channels(path: str | Path) -> list[ChannelConfig]:
    return [ChannelConfig(**d) for d in json.loads(Path(path).read_text(encoding="utf-8"))]
