"""Common interface of a signal source.

The same interface is used for replaying old recordings, for the training simulator and,
later, for a real ADC board (LabJack, MCC, NI, ...). The GUI only talks to this interface,
so supporting a new board means writing one more source class.

Pull model: about 30 times per second the GUI calls read() and receives every sample that
has accumulated since the previous call. A real board will read in its own thread into a
buffer; read() will just take what is there.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import numpy as np


@dataclass
class SourceEvent:
    """Something that happened at a given sample: a marker from an old MRK file,
    the start of a file, a simulator event (arrest, VF, ...)."""
    sample: int                    # sample index from the start of the session
    text: str                      # plain text, or a translation key for kind="sim"
    kind: str = "info"             # "marker" | "file" | "sim" | "info"
    params: dict = field(default_factory=dict)   # parameters for translated texts


class DataSource(ABC):
    #: sampling rate per channel, Hz
    rate: float
    #: channel names, in column order
    channel_names: list[str]

    @abstractmethod
    def start(self) -> None: ...

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def read(self) -> tuple[np.ndarray, list[SourceEvent]]:
        """New samples (n, n_channels) in volts, and events that happened."""

    @property
    def finished(self) -> bool:
        return False

    def describe(self) -> str:
        return type(self).__name__
