"""Replay of old ISCHEMIA recordings as if the signal came from a board.

Several files of one experiment are joined into one continuous session in the order of
their recording time. Gaps between files are not reproduced, but an event with the file
name, time and comment is emitted at the start of each file.

Speed can be changed (1x = real time, 10x = ten times faster) so that an hour-long
experiment does not have to be watched in real time.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from ..io.ischemia_dat import read_dat
from .base import DataSource, SourceEvent


class ReplaySource(DataSource):
    def __init__(self, files: list[str | Path], speed: float = 1.0, clock=time.monotonic):
        if not files:
            raise ValueError("no files selected")
        recs = [read_dat(f) for f in files]
        rates = {r.rate for r in recs}
        nch = {r.volts.shape[1] for r in recs}
        if len(rates) != 1 or len(nch) != 1:
            raise ValueError("files differ in sampling rate or number of channels")
        self.rate = rates.pop()
        self.channel_names = [c.name for c in recs[0].header.channels]
        self.files = [r.path for r in recs]

        self._data = np.concatenate([r.volts for r in recs])
        self._events: list[SourceEvent] = []
        pos = 0
        for r in recs:
            st = r.header.start.strftime("%d.%m.%Y %H:%M:%S") if r.header.start else "?"
            self._events.append(SourceEvent(pos, f"{r.path.name} · {st} · {r.header.comment}", "file"))
            for m in r.markers:
                self._events.append(SourceEvent(pos + m, "marker.ischemia_file", "marker",
                                                {"file": r.path.name}))
            pos += len(r.volts)
        self._events.sort(key=lambda e: e.sample)

        self._clock = clock
        self.speed = speed
        self._pos = 0              # samples already handed out by read()
        self._ev_i = 0
        self._t0: float | None = None   # start of the current running stretch (None = paused)
        self._pos0 = 0             # samples "available" when the stretch started

    # --- control ----------------------------------------------------------
    def start(self) -> None:
        if self._t0 is None:
            self._t0 = self._clock()

    def stop(self) -> None:
        self._pos0 = self._advance()   # samples accrued but not yet read are kept
        self._t0 = None

    def set_speed(self, speed: float) -> None:
        running = self._t0 is not None
        if running:
            self.stop()
        self.speed = speed
        if running:
            self.start()

    def seek(self, sample: int) -> None:
        """Jump to a sample. Events before that point are skipped."""
        running = self._t0 is not None
        self._t0 = None
        self._pos = self._pos0 = int(np.clip(sample, 0, len(self._data)))
        self._ev_i = 0
        while self._ev_i < len(self._events) and self._events[self._ev_i].sample < self._pos:
            self._ev_i += 1
        if running:
            self.start()

    # --- data ---------------------------------------------------------------
    def _advance(self) -> int:
        if self._t0 is None:
            return self._pos0
        target = self._pos0 + int((self._clock() - self._t0) * self.rate * self.speed)
        return min(target, len(self._data))

    def read(self):
        end = self._advance()
        block = self._data[self._pos:end]
        ev = []
        while self._ev_i < len(self._events) and self._events[self._ev_i].sample < end:
            ev.append(self._events[self._ev_i])
            self._ev_i += 1
        self._pos = end
        return block, ev

    @property
    def position(self) -> int:
        return self._pos

    @property
    def total_samples(self) -> int:
        return len(self._data)

    @property
    def finished(self) -> bool:
        return self._pos >= len(self._data)

    def describe(self) -> str:
        return f"replay:{len(self.files)} file(s):{self.total_samples / self.rate / 60:.1f} min"
