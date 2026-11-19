"""Per-motor current / voltage sensor feed (planned hardware: MCU + INA226/INA228 or Hall sensor).

Wire protocol (ASCII, one sample per line, UDP datagram or serial line):

    S,<t_ms>,<ch>,<mA>,<mV>\\n          ch 0 = base motor, 1 = shoulder motor; t_ms = MCU millis()

The source keeps the latest sample per channel, a short window for averaging, and the clock offset between
the MCU and the PC (first sample defines it; use a shared sync pulse for tighter alignment).
"""
from __future__ import annotations

import socket
import threading
import time
from collections import deque

CHANNELS = ("base", "shoulder")


def parse_line(line: str):
    """-> (t_ms, channel_name, mA, mV) or None for anything that is not a valid sample."""
    parts = line.strip().split(",")
    if len(parts) != 5 or parts[0] != "S":
        return None
    try:
        t_ms, ch, ma, mv = int(parts[1]), int(parts[2]), float(parts[3]), float(parts[4])
    except ValueError:
        return None
    if ch not in (0, 1):
        return None
    return t_ms, CHANNELS[ch], ma, mv


class SensorSource:
    name = "sensors"

    def __init__(self, reader, window_s: float = 0.25, label: str = "") -> None:
        """reader: callable returning an iterable of text lines (blocking) -- see udp_reader / serial_reader."""
        self.reader = reader
        self.window_s = window_s
        self.label = label
        self.samples = {c: deque(maxlen=5000) for c in CHANNELS}   # (pc_time, mA, mV)
        self.count = 0
        self.bad = 0
        self.last_rx = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- constructors ------------------------------------------------------
    @classmethod
    def from_spec(cls, spec: str, twin=None) -> "SensorSource":
        kind, _, arg = spec.partition(":")
        if kind == "udp":
            return cls(udp_reader(int(arg or 9100)), label=spec)
        if kind == "serial":
            port, _, baud = arg.partition("@")
            return cls(serial_reader(port, int(baud or 115200)), label=spec)
        raise ValueError("sensor spec must be udp:PORT or serial:COMx[@baud]")

    # ---- ingest ------------------------------------------------------------
    def feed_line(self, line: str, now: float | None = None) -> bool:
        p = parse_line(line)
        if p is None:
            self.bad += 1
            return False
        _, ch, ma, mv = p
        now = time.time() if now is None else now
        self.samples[ch].append((now, ma, mv))
        self.count += 1
        self.last_rx = now
        return True

    def start(self) -> "SensorSource":
        def run():
            for line in self.reader(self._stop):
                self.feed_line(line)
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    # ---- outputs -----------------------------------------------------------
    def latest(self, now: float | None = None) -> dict:
        """Averages over the last window per channel: {"base": {"mA","mV","W","n","age_s"}, ...}"""
        now = time.time() if now is None else now
        out = {}
        for c, buf in self.samples.items():
            win = [s for s in buf if now - s[0] <= self.window_s]
            if win:
                ma = sum(s[1] for s in win) / len(win)
                mv = sum(s[2] for s in win) / len(win)
                out[c] = {"mA": ma, "mV": mv, "W": ma * mv / 1e6, "n": len(win), "age_s": now - buf[-1][0]}
        return out

    def snapshot(self) -> dict | None:
        if not self.count:
            return None
        return {"schema": 1, "source": "sensors", "t": time.time(), "wall": time.time(), "sensors": self.latest()}

    def status(self) -> dict:
        age = time.time() - self.last_rx if self.last_rx else None
        ok = age is not None and age < 2
        return {"connected": ok, "info": f"{self.label} samples={self.count} bad={self.bad}"}

    def control(self, action: str, params: dict) -> dict:
        return {}


def udp_reader(port: int, host: str = "0.0.0.0"):
    def gen(stop: threading.Event):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.settimeout(0.5)
        while not stop.is_set():
            try:
                data, _ = sock.recvfrom(2048)
            except socket.timeout:
                continue
            for line in data.decode("ascii", "ignore").splitlines():
                yield line
        sock.close()
    return gen


def serial_reader(port: str, baud: int = 115200):
    def gen(stop: threading.Event):
        import serial        # pyserial, optional
        with serial.Serial(port, baud, timeout=0.5) as ser:
            while not stop.is_set():
                line = ser.readline().decode("ascii", "ignore")
                if line:
                    yield line
    return gen
