"""Reader for files of the legacy DOS program ISCHEMIA (ISCHnnnn.DAT + ISCHnnnn.MRK).

The format was reverse-engineered from real files (see docs/DAT_FORMAT.md):

* the STEMMER SWG "TL 4.0 / Sampled Data File" header is a sequence of 16-byte records:
  tag, idx, type, len (uint16 LE) and an 8-byte value. If len > 8 the value follows
  right after the 16-byte record;
* numbers (type 14) are 6 bytes: int32 mantissa / 2^31 * 2^(int16 exponent);
* date and time are at offset 0x66 (Borland struct date + struct time);
* data starts after record 0x8004: int16 LE, 12 bit (0..4095), channels interleaved;
* volts = raw * scale + offset (0.005 and -10.24 in every known file, i.e. ±10.24 V);
* an MRK file has the same header plus 0xC0 records holding a sample index (uint32).
"""
from __future__ import annotations

import datetime as dt
import struct
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

MAGIC = b"SWGBSMBWS"


@dataclass
class DatChannel:
    name: str
    adc: int | None = None
    scale: float = 1.0      # raw -> V
    offset: float = 0.0
    uscale: float = 1.0     # user calibration (V -> units)
    uoffset: float = 0.0
    unit: str = "Volt"


@dataclass
class DatHeader:
    start: dt.datetime | None = None
    comment: str = ""
    rate: float = 100.0
    channels: list[DatChannel] = field(default_factory=list)
    markers: list[int] = field(default_factory=list)   # sample indices
    data_offset: int | None = None


@dataclass
class DatRecording:
    path: Path
    header: DatHeader
    volts: np.ndarray            # (n_samples, n_channels), float32, volts
    markers: list[int]           # sample indices from the MRK file

    @property
    def rate(self) -> float:
        return self.header.rate

    @property
    def duration(self) -> float:
        return len(self.volts) / self.rate


def _num(v: bytes) -> float:
    m, e = struct.unpack("<ih", v[:6])
    return m / 2**31 * 2.0**e


def _text(v: bytes) -> str:
    return v.split(b"\0")[0].decode("cp866", "replace").strip()


def _records(b: bytes, start: int):
    off = start
    while off + 16 <= len(b):
        tag, idx, typ, ln = struct.unpack_from("<4H", b, off)
        if ln > 8 and tag != 0xFFFF:
            val, nxt = b[off + 16:off + 16 + ln], off + 16 + ln + (ln & 1)
        else:
            val, nxt = b[off + 8:off + 8 + ln], off + 16
        yield tag, idx, typ, val, nxt
        if tag == 0x8004:
            return
        off = nxt


def _find_start(b: bytes) -> int:
    # the comment record (tag 2, type 2) follows the date and time
    for s in (0x6E, 0x6C, 0x70):
        tag, _, typ = struct.unpack_from("<3H", b, s)
        if tag == 2 and typ == 2:
            return s
    raise ValueError("header start not found")


def parse_header(b: bytes) -> DatHeader:
    if not b.startswith(MAGIC):
        raise ValueError("not an ISCHEMIA / STEMMER file")
    h = DatHeader()
    y, day, mon = struct.unpack_from("<HBB", b, 0x66)
    mi, hr, hu, se = b[0x6A:0x6E]
    try:
        h.start = dt.datetime(y, mon, day, hr, mi, se, hu * 10000)
    except ValueError:
        pass

    cur: DatChannel | None = None
    sect = None
    adc_i = 0
    for tag, idx, typ, val, nxt in _records(b, _find_start(b)):
        if tag == 2 and typ == 2 and not h.comment:
            h.comment = _text(val)
        elif tag in (0x8005, 0x8003):
            sect = tag
            if tag == 0x8005 and idx > 0:
                cur = DatChannel(name=f"CH{idx - 1:02d}")
                h.channels.append(cur)
        elif tag == 0x8A and typ == 14:
            h.rate = _num(val)
        elif sect == 0x8005 and cur is not None:
            if tag == 1 and typ == 2:
                cur.name = _text(val) or cur.name
            elif tag == 0x82 and typ == 14:
                if idx == 1:
                    cur.scale = _num(val)
                else:
                    cur.uscale = _num(val)
            elif tag == 0x83 and typ == 14:
                if idx == 1:
                    cur.offset = _num(val)
                else:
                    cur.uoffset = _num(val)
            elif tag == 0x84 and typ == 2 and idx == 2:
                cur.unit = _text(val) or cur.unit
        elif sect == 0x8003 and tag == 0xA0 and typ == 8:
            if adc_i < len(h.channels):
                h.channels[adc_i].adc = struct.unpack("<H", val[:2])[0]
            adc_i += 1
        elif tag == 0xC0 and typ == 8:
            h.markers.append(struct.unpack("<I", val[:4])[0])
        if tag == 0x8004:
            h.data_offset = nxt
    return h


def read_markers(path: Path) -> list[int]:
    return sorted(parse_header(Path(path).read_bytes()).markers)


def _mrk_for(path: Path) -> Path | None:
    for suf in (".MRK", ".mrk"):
        p = path.with_suffix(suf)
        if p.exists():
            return p
    return None


def read_dat(path: str | Path) -> DatRecording:
    path = Path(path)
    b = path.read_bytes()
    h = parse_header(b)
    if h.data_offset is None or not h.channels:
        raise ValueError(f"{path.name}: no data block")
    n = len(h.channels)
    body = b[h.data_offset:]
    body = body[: len(body) // (2 * n) * (2 * n)]
    raw = np.frombuffer(body, dtype="<i2").reshape(-1, n)
    scale = np.array([c.scale * c.uscale for c in h.channels])
    off = np.array([c.offset * c.uscale + c.uoffset for c in h.channels])
    volts = (raw * scale + off).astype(np.float32)
    mrk = _mrk_for(path)
    markers = read_markers(mrk) if mrk else []
    return DatRecording(path, h, volts, markers)


def find_recordings(folder: str | Path) -> list[Path]:
    """All ISCH*.DAT files in a folder, sorted by recording start time."""
    files = [p for p in Path(folder).iterdir()
             if p.suffix.upper() == ".DAT" and p.name.upper().startswith("ISCH")]

    def key(p: Path):
        try:
            s = parse_header(p.read_bytes()[:0x600]).start
        except Exception:
            s = None
        return (s or dt.datetime.max, p.name)

    return sorted(files, key=key)
