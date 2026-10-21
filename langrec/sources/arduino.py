"""DataSource for the Arduino prototype (firmware/langrec_arduino).

The board streams frames over USB serial at 115200 baud, 500 frames per second:
    0xAA 0x55, four little-endian uint16 ADC counts (A0..A3, 0..1023), checksum
(checksum = sum of the 8 data bytes modulo 256). A reader thread parses the byte stream,
resynchronises on the header after any garbage, drops frames with a bad checksum, and
hands complete samples to read() in volts (5 V reference).

Works on macOS, Windows and Linux (pyserial); the Uno needs no extra driver on macOS.
"""
from __future__ import annotations

import threading
from collections import deque

import numpy as np

from .base import DataSource, SourceEvent

HEADER = b"\xAA\x55"
FRAME = 11
N_CH = 4
VREF = 5.0
BAUD = 115200
RATE = 500.0
CHANNELS = ["A0 heart", "A1 knob", "A2 light", "A3"]


class FrameParser:
    """Turns an arbitrary byte stream into (n, 4) arrays of ADC counts."""

    def __init__(self):
        self.buf = bytearray()
        self.bad = 0          # frames dropped because of a checksum error
        self.skipped = 0      # bytes skipped while resynchronising

    def feed(self, data: bytes) -> np.ndarray:
        self.buf += data
        out = []
        i = 0
        b = self.buf
        while len(b) - i >= FRAME:
            if b[i] != 0xAA or b[i + 1] != 0x55:
                j = b.find(HEADER, i + 1)
                if j < 0:
                    self.skipped += len(b) - i - 1
                    i = len(b) - 1
                    break
                self.skipped += j - i
                i = j
                continue
            payload = b[i + 2:i + 10]
            if sum(payload) & 0xFF != b[i + 10]:
                self.bad += 1
                i += 1                       # resync from the next byte
                continue
            out.append(np.frombuffer(bytes(payload), dtype="<u2"))
            i += FRAME
        del b[:i]
        if not out:
            return np.zeros((0, N_CH), dtype=np.uint16)
        return np.vstack(out)


def list_ports() -> list[tuple[str, str]]:
    """(device, description) of serial ports, likely Arduinos first."""
    try:
        from serial.tools import list_ports as lp
    except ImportError:
        return []
    ports = []
    for p in lp.comports():
        desc = p.description or ""
        score = 0 if any(k in (desc + (p.manufacturer or "")).lower()
                         for k in ("arduino", "ch340", "usb serial", "usbmodem", "wch")) \
            or "usbmodem" in p.device or "usbserial" in p.device else 1
        ports.append((score, p.device, desc))
    return [(d, desc) for _, d, desc in sorted(ports)]


class ArduinoSource(DataSource):
    def __init__(self, port: str, serial_factory=None):
        self.port = port
        self.rate = RATE
        self.channel_names = list(CHANNELS)
        self._factory = serial_factory
        self._ser = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._queue: deque[np.ndarray] = deque()
        self._lock = threading.Lock()
        self.parser = FrameParser()
        self.error: str | None = None
        self._running = False

    # ---------------------------------------------------------------- serial
    def _open(self):
        if self._ser is not None:
            return
        if self._factory:
            self._ser = self._factory()
        else:
            import serial
            self._ser = serial.Serial(self.port, BAUD, timeout=0.05)
            # opening the port resets the Uno; its bootloader runs for ~1.5 s
        self._stop.clear()
        self._thread = threading.Thread(target=self._reader, daemon=True)
        self._thread.start()

    def _reader(self):
        while not self._stop.is_set():
            try:
                data = self._ser.read(512)
            except Exception as e:           # unplugged, permission, ...
                self.error = str(e)
                return
            if not data:
                continue
            frames = self.parser.feed(data)
            if len(frames) and self._running:
                with self._lock:
                    self._queue.append(frames)

    # ------------------------------------------------------------- interface
    def start(self):
        self._open()
        with self._lock:
            self._queue.clear()          # do not replay what arrived while paused
        self._running = True

    def stop(self):
        self._running = False

    def close(self):
        self._running = False
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:
                pass
        self._ser = None

    def send(self, data: bytes):
        if self._ser is not None:
            self._ser.write(data)

    def read(self):
        with self._lock:
            chunks = list(self._queue)
            self._queue.clear()
        events = []
        if self.error:
            events.append(SourceEvent(0, f"Arduino: {self.error}", "info"))
            self.error = None
        if not chunks:
            return np.zeros((0, N_CH), dtype=np.float32), events
        counts = np.vstack(chunks).astype(np.float32)
        return counts * (VREF / 1023.0), events

    def describe(self) -> str:
        return f"arduino:{self.port}:{self.rate:.0f}Hz"
