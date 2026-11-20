"""Read-only live feed from the real PLC over Modbus TCP (pymodbus).

* The client wrapper exposes read functions ONLY. There is no code path that writes to the PLC.
* Polls a fixed plan of memory blocks, mirrors them into a ``twin.il.Memory`` and publishes a pose snapshot
  (source name ``plc``) from the mirrored encoder counts (%MD600 base, %VD1044 shoulder).
* The Kinco address mapping lives in ``live/modbus_map.py`` (from the Kinco K-series manual, not yet verified on hardware).
"""
from __future__ import annotations

import inspect
import threading
import time

from twin.config import TwinCfg
from twin.il import Memory
from twin.sources import pose_snapshot

from .modbus_map import MAX_BITS_PER_READ, MAX_WORDS_PER_READ, ModbusMap

# (kind, area, first byte, number of bytes); kind = discrete | coil | word (holding registers, V area) | wordbits (word data of a bit-only area)
DEFAULT_PLAN = [
    ("discrete", "I", 0, 2),
    ("coil", "Q", 0, 2),
    ("coil", "M", 10, 44),
    ("word", "V", 1000, 64),
    ("word", "V", 2000, 42),
    ("word", "V", 2300, 128),
    ("word", "V", 2490, 40),
    ("wordbits", "M", 600, 8),          # %MD600 (base position): the M area is bit-only on the PLC, read as 64 coils
]


class ReadOnlyClient:
    """Thin wrapper over pymodbus' ModbusTcpClient that can only read."""

    def __init__(self, host: str, port: int = 502, unit: int = 1, timeout: float = 1.0) -> None:
        from pymodbus.client import ModbusTcpClient
        self._c = ModbusTcpClient(host, port=port, timeout=timeout)
        params = inspect.signature(self._c.read_holding_registers).parameters
        self._unit_kw = "device_id" if "device_id" in params else ("slave" if "slave" in params else None)
        self.unit = unit

    def connect(self) -> bool:
        return bool(self._c.connect())

    def close(self) -> None:
        self._c.close()

    def _kw(self) -> dict:
        return {self._unit_kw: self.unit} if self._unit_kw else {}

    def read_bits(self, kind: str, addr: int, count: int) -> list[int]:
        fn = self._c.read_coils if kind == "coil" else self._c.read_discrete_inputs
        rr = fn(addr, count=count, **self._kw())
        if rr.isError():
            raise IOError(f"modbus {kind} read @{addr} x{count}: {rr}")
        return [1 if b else 0 for b in rr.bits[:count]]

    def read_words(self, addr: int, count: int) -> list[int]:
        rr = self._c.read_holding_registers(addr, count=count, **self._kw())
        if rr.isError():
            raise IOError(f"modbus holding read @{addr} x{count}: {rr}")
        return list(rr.registers)


class PlcLiveSource:
    name = "plc"

    def __init__(self, host: str, port: int = 502, cfg: TwinCfg | None = None, mapping: ModbusMap | None = None,
                 hz: float = 10.0, plan=None, client_factory=None) -> None:
        self.host, self.port = host, port
        self.cfg = cfg or TwinCfg()
        self.map = mapping or ModbusMap.load()
        self.hz = hz
        self.plan = plan or DEFAULT_PLAN
        self.mem = Memory()                      # mirror of the PLC memory
        self.connected = False
        self.error = ""
        self.polls = 0
        self.last_ms = 0.0
        self._factory = client_factory or (lambda: ReadOnlyClient(host, port, self.map.unit))
        self._client = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_t = 0.0

    # ---- lifecycle ---------------------------------------------------------
    def start(self) -> "PlcLiveSource":
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._client:
            self._client.close()
        self.connected = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            t0 = time.perf_counter()
            try:
                if self._client is None:
                    self._client = self._factory()
                    if not self._client.connect():
                        raise IOError(f"cannot connect to {self.host}:{self.port}")
                self.poll_once()
                self.connected, self.error = True, ""
            except Exception as exc:   # noqa: BLE001
                self.connected, self.error = False, str(exc)
                if self._client:
                    self._client.close()
                self._client = None
                self._stop.wait(2.0)           # back off before reconnecting
                continue
            self.last_ms = (time.perf_counter() - t0) * 1000
            self._stop.wait(max(0.0, 1.0 / self.hz - (time.perf_counter() - t0)))

    # ---- one poll of the whole plan ----------------------------------------
    def poll_once(self) -> None:
        c, m = self._client, self.map
        for kind, area, byte0, nbytes in self.plan:
            if kind == "word":
                first = m.word(area, byte0)
                nwords = nbytes // 2
                for off in range(0, nwords, MAX_WORDS_PER_READ):
                    n = min(MAX_WORDS_PER_READ, nwords - off)
                    regs = c.read_words(first + off, n)
                    for i, r in enumerate(regs):
                        self.mem.set(area, 2, byte0 + (off + i) * 2, r)
            else:
                nbits = nbytes * 8
                k, first = m.bit(area, byte0, 0) if kind != "wordbits" else m.word_via_bits(area, byte0)
                rk = "coil" if kind in ("wordbits", "coil") else k
                for off in range(0, nbits, MAX_BITS_PER_READ):
                    n = min(MAX_BITS_PER_READ, nbits - off)
                    bits = c.read_bits(rk, first + off, n)
                    for i, b in enumerate(bits):
                        idx = off + i
                        self.mem.set_bit(area, byte0 + idx // 8, idx % 8, b)
        self.polls += 1
        self._last_t = time.time()

    # ---- bus interface -----------------------------------------------------
    def snapshot(self) -> dict | None:
        if not self.polls:
            return None
        c, m = self.cfg, self.mem
        b = c.base.count_to_angle(m.read("MD600")) * 180 / 3.141592653589793
        s = c.shoulder.count_to_angle(m.read("VD1044")) * 180 / 3.141592653589793
        keys = ("M20.1", "M20.2", "M20.3", "M20.4", "M20.5", "M30.0", "M30.1", "M30.2", "M30.6", "M40.0", "M50.0", "M50.1")
        reg_keys = (["MD600", "VD1044", "VD2020", "VD2030", "VW2036", "VW2400", "VW2500", "VW2510"]
                    + [f"VD{2300 + 4 * i}" for i in range(5)] + [f"VD{2400 + 4 * i}" for i in range(5)])
        extra = {
            "io": {"I0.0": m.read("I0.0"), "I0.1": m.read("I0.1"), "Q0.7": m.read("Q0.7")},
            "bits": {k: m.read(k) for k in keys},
            "regs": {k: m.read(k) for k in reg_keys},
            # what the HMI replica shows: C3/C4 are mirrored to VW2500 (min) / VW2510 (sec) by the PLC program
            "hmi": {"cyc_min": m.read("VW2500"), "cyc_sec": m.read("VW2510"), "magnet_sw": m.read("M20.5")},
            "cycle_reg": "VW2400",
            "live": {"age_s": time.time() - self._last_t, "poll_ms": self.last_ms, "polls": self.polls},
        }
        snap = pose_snapshot("plc", c, b, s, t=time.time(), magnet=bool(m.read("Q0.7")), extra=extra)
        snap["base"].update({"count": m.read("MD600")})
        snap["shoulder"].update({"count": m.read("VD1044")})
        return snap

    def status(self) -> dict:
        info = f"{self.host}:{self.port} polls={self.polls} {self.last_ms:.0f} ms" if self.connected else (self.error or "idle")
        return {"connected": self.connected, "info": info}

    def control(self, action: str, params: dict) -> dict:
        if action == "stop":
            self.stop()
        elif action == "start" and not (self._thread and self._thread.is_alive()):
            self.start()
        return {}
