"""DataSource around the training heart model (langrec.sim.model.HeartModel).

Generates samples at the model's rate, in step with the wall clock times the speed factor,
exactly like a real ADC would deliver them. Model events (arrest, VF, contracture...) are
passed on as SourceEvent(kind="sim") so the GUI can show them as hints.
"""
from __future__ import annotations

import time

import numpy as np

from ..sim.model import CHANNELS, HeartModel
from .base import DataSource, SourceEvent

MAX_CATCH_UP_S = 5.0   # never generate more than this much signal in one read (e.g. after sleep)


class SimulatorSource(DataSource):
    def __init__(self, profile: str = "lab", rate: float = 500.0, seed: int | None = None,
                 speed: float = 1.0, clock=time.monotonic):
        self.model = HeartModel(profile, rate=rate, seed=seed)
        self.rate = rate
        self.channel_names = list(CHANNELS)
        self.profile = profile
        self.speed = speed
        self._clock = clock
        self._t0: float | None = None
        self._pending = 0.0       # samples owed but not yet generated (fractional)

    def start(self):
        if self._t0 is None:
            self._t0 = self._clock()

    def stop(self):
        self._accrue()
        self._t0 = None

    def set_speed(self, speed: float):
        self._accrue()
        self.speed = speed

    def _accrue(self):
        if self._t0 is not None:
            now = self._clock()
            self._pending += (now - self._t0) * self.rate * self.speed
            self._t0 = now

    def read(self):
        self._accrue()
        n = int(min(self._pending, MAX_CATCH_UP_S * self.rate * max(1.0, self.speed)))
        self._pending -= n
        if self._pending > self.rate * MAX_CATCH_UP_S * max(1.0, self.speed):
            self._pending = 0.0          # drop the backlog instead of freezing the GUI
        if n <= 0:
            return np.zeros((0, len(self.channel_names)), dtype=np.float32), []
        block = self.model.generate(n).astype(np.float32)
        events = [SourceEvent(s, key, "sim", params) for s, key, params in self.model.pop_events()]
        return block, events

    @property
    def position(self) -> int:
        return self.model.sample

    def describe(self) -> str:
        return f"simulator:{self.profile}:seed={self.model.seed}:{self.rate:.0f}Hz"
