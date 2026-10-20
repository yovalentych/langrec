"""Recording a session to disk.

Each session gets a folder YYYY-MM-DD_HH-MM-SS[_title]/ with:
  signals.csv     — time_s and every channel (in calibrated units, raw = unfiltered);
  markers.csv     — markers: time_s, sample, kind, text;
  parameters.csv  — computed parameters (HR, LVDP, dP/dt ...) once per analysis step;
  session.json    — description: source, rate, channel settings, display filters, start/stop.

CSV opens anywhere (Excel, Origin, Python, R). Data is appended in blocks and flushed
every time, so nothing already written is lost if the program crashes.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import __version__
from .channels import ChannelConfig


class SessionRecorder:
    def __init__(self, root: str | Path, channels: list[ChannelConfig], rate: float,
                 source_desc: str, title: str = ""):
        now = dt.datetime.now()
        slug = re.sub(r"[^\w\-]+", "_", title.strip())[:40]
        name = now.strftime("%Y-%m-%d_%H-%M-%S") + (f"_{slug}" if slug else "")
        self.dir = Path(root) / name
        self.dir.mkdir(parents=True, exist_ok=False)
        self.channels = channels
        self.rate = rate
        self.n = 0
        self.meta = {
            "program": f"LangRec {__version__}",
            "title": title,
            "started": now.isoformat(timespec="seconds"),
            "source": source_desc,
            "rate_hz": rate,
            "channels": [asdict(c) for c in channels],
        }
        self._write_meta()
        self._sig = (self.dir / "signals.csv").open("w", newline="", encoding="utf-8")
        self._sw = csv.writer(self._sig)
        self._sw.writerow(["time_s"] + [f"{c.name}_{c.unit}" for c in channels])
        self._mrk = (self.dir / "markers.csv").open("w", newline="", encoding="utf-8")
        self._mw = csv.writer(self._mrk)
        self._mw.writerow(["time_s", "sample", "kind", "text"])
        self._par = None
        self._pw = None

    def _write_meta(self):
        (self.dir / "session.json").write_text(json.dumps(self.meta, ensure_ascii=False, indent=2),
                                               encoding="utf-8")

    def write_block(self, units: np.ndarray) -> None:
        """units: (n, n_channels), already in calibrated units."""
        if len(units) == 0:
            return
        t = (self.n + np.arange(len(units))) / self.rate
        rows = np.column_stack([t, units])
        # numpy formats in C: fast enough for 1 kHz x many channels at 60x replay speed
        np.savetxt(self._sig, rows, fmt=["%.4f"] + ["%.6g"] * units.shape[1], delimiter=",")
        self.n += len(units)
        self._sig.flush()

    def add_marker(self, sample: int, text: str, kind: str = "user") -> None:
        self._mw.writerow([f"{sample / self.rate:.3f}", sample, kind, text])
        self._mrk.flush()

    def add_params(self, sample: int, params: dict) -> None:
        if self._pw is None:
            self._par = (self.dir / "parameters.csv").open("w", newline="", encoding="utf-8")
            self._pw = csv.DictWriter(self._par, fieldnames=["time_s", *params.keys()])
            self._pw.writeheader()
        self._pw.writerow({"time_s": f"{sample / self.rate:.2f}", **params})
        self._par.flush()

    def close(self) -> None:
        self.meta["stopped"] = dt.datetime.now().isoformat(timespec="seconds")
        self.meta["samples"] = self.n
        self.meta["duration_s"] = round(self.n / self.rate, 3)
        self._write_meta()
        for f in (self._sig, self._mrk, self._par):
            if f:
                f.close()
