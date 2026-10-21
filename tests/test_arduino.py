"""Arduino source: frame parsing, resynchronisation, checksum, threaded reading."""
import time

import numpy as np

from langrec.sources.arduino import FRAME, ArduinoSource, FrameParser


def frame(vals):
    payload = b"".join(int(v).to_bytes(2, "little") for v in vals)
    return b"\xAA\x55" + payload + bytes([sum(payload) & 0xFF])


def test_parses_frames_split_anywhere():
    stream = b"".join(frame([i, 2 * i, 3 * i, 1023]) for i in range(100))
    p = FrameParser()
    out = np.vstack([p.feed(stream[k:k + 7]) for k in range(0, len(stream), 7)])
    assert out.shape == (100, 4)
    assert list(out[42]) == [42, 84, 126, 1023]


def test_resync_after_garbage_and_bad_checksum():
    good = frame([1, 2, 3, 4])
    bad = bytearray(frame([5, 6, 7, 8]))
    bad[-1] ^= 0xFF
    p = FrameParser()
    out = p.feed(b"\x00\x13garbage" + good + bytes(bad) + good)
    assert out.shape == (2, 4) and p.bad == 1


class FakeSerial:
    """Behaves like serial.Serial.read: streams frames of a sine wave."""

    def __init__(self):
        self.t = 0
        self.closed = False

    def read(self, n):
        time.sleep(0.002)
        chunk = b""
        for _ in range(n // FRAME):
            v = 512 + 400 * np.sin(2 * np.pi * 2 * self.t / 500)
            chunk += frame([v, 300, 200, 0])
            self.t += 1
        return chunk

    def write(self, data):
        pass

    def close(self):
        self.closed = True


def test_source_delivers_volts():
    fake = FakeSerial()
    src = ArduinoSource("fake", serial_factory=lambda: fake)
    src.start()
    time.sleep(0.2)
    block, _ = src.read()
    src.close()
    assert block.shape[1] == 4 and len(block) > 100
    assert np.allclose(block[:, 1], 300 * 5 / 1023, atol=1e-3)
    assert fake.closed
