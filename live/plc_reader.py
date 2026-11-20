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
from collections import deque

from twin.config import TwinCfg
from twin.il import Memory
from twin.sources import pose_snapshot

from .diag import PollStats
from .modbus_map import MAX_BITS_PER_READ, MAX_WORDS_PER_READ, ModbusMap
from .raw import pack_bits

# One block = (kind, area, first byte, number of bytes); kind = discrete | coil | word (holding registers, V area) | wordbits
# (word data of a bit-only area). A plan is a dict of named groups, each polled at its own rate, so the fast signals
# (encoders, status bits) are not slowed down by the bulky slow ones (taught data, counters).
FAST = [
    ("discrete", "I", 0, 2),
    ("coil", "Q", 0, 2),
    ("coil", "M", 10, 44),
    ("wordbits", "M", 600, 8),          # %MD600 (base position): the M area is bit-only on the PLC, read as 64 coils
    ("word", "V", 1044, 4),             # %VD1044 (shoulder position)
]
SLOW = [
    ("word", "V", 1000, 64),
    ("word", "V", 2000, 42),
    ("word", "V", 2300, 128),
    ("word", "V", 2490, 40),
]
DEFAULT_PLAN = FAST + SLOW                          # flat form, still accepted (one group named "all")


def make_groups(fast_hz: float = 10.0, slow_hz: float = 1.0) -> dict:
    return {"fast": {"hz": fast_hz, "blocks": FAST}, "slow": {"hz": slow_hz, "blocks": SLOW}}


# 32-bit values the program uses: (area, first byte). A torn read happens if the two halves arrive in different requests.
KNOWN_DWORDS = [("M", 600), ("V", 1044), ("V", 2020), ("V", 2030)] + [("V", 2300 + 4 * i) for i in range(5)] + [("V", 2400 + 4 * i) for i in range(5)]


def check_plan(groups: dict, dwords=KNOWN_DWORDS) -> list[str]:
    """Messages for every known double word that is NOT read inside one single request (would be a torn read); [] if fine.
    Also reports double words the plan does not read at all."""
    reqs = []          # (area, first byte, last byte+1) of every request that will be sent
    for g, spec in groups.items():
        for kind, area, byte0, nbytes in spec["blocks"]:
            if kind == "word":
                for off in range(0, nbytes // 2, MAX_WORDS_PER_READ):
                    n = min(MAX_WORDS_PER_READ, nbytes // 2 - off)
                    reqs.append((area, byte0 + off * 2, byte0 + off * 2 + n * 2))
            else:
                for off in range(0, nbytes * 8, MAX_BITS_PER_READ):
                    n = min(MAX_BITS_PER_READ, nbytes * 8 - off)
                    reqs.append((area, byte0 + off // 8, byte0 + off // 8 + (n + 7) // 8))
    bad = []
    for area, b0 in dwords:
        if any(a == area and lo <= b0 and b0 + 4 <= hi for a, lo, hi in reqs):
            continue
        if any(a == area and lo < b0 + 4 and b0 < hi for a, lo, hi in reqs):
            bad.append(f"%{area}D{b0} is split across requests (torn read possible)")
        else:
            bad.append(f"%{area}D{b0} is not read by the plan")
    return bad


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
                 hz: float = 10.0, plan=None, client_factory=None, slow_hz: float = 1.0) -> None:
        self.host, self.port = host, port
        self.cfg = cfg or TwinCfg()
        self.map = mapping or ModbusMap.load()
        self.hz = hz
        if plan is None:
            self.groups = make_groups(hz, slow_hz)
        elif isinstance(plan, dict):
            self.groups = plan
        else:
            self.groups = {"all": {"hz": hz, "blocks": plan}}          # flat plan
        self.plan = [b for g in self.groups.values() for b in g["blocks"]]
        self.stats = PollStats()
        self._raw: deque = deque(maxlen=4000)        # raw poll records not yet drained by a recorder
        self._events: deque = deque(maxlen=200)      # connection events not yet drained
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

    def _event(self, text: str, kind: str = "info") -> None:
        self._events.append({"text": text, "kind": kind, "t_mono": time.monotonic(), "t_wall": time.time()})

    def _loop(self) -> None:
        due = {g: 0.0 for g in self.groups}                 # next due time per group (monotonic)
        while not self._stop.is_set():
            try:
                if self._client is None:
                    self._client = self._factory()
                    if not self._client.connect():
                        raise IOError(f"cannot connect to {self.host}:{self.port}")
                    if self.stats.errors or self.polls:
                        self.stats.reconnect()
                    self._event(f"PLC connected {self.host}:{self.port}")
                now = time.monotonic()
                for g, spec in self.groups.items():
                    if now >= due[g]:
                        self.poll_group(g)
                        per, nxt = 1.0 / spec["hz"], due[g] + 1.0 / spec["hz"]
                        t_now = time.monotonic()
                        while nxt <= t_now:                 # skip missed slots: keep the rate, never burst to catch up
                            nxt += per
                        due[g] = nxt
                self.connected, self.error = True, ""
            except Exception as exc:   # noqa: BLE001
                self.connected, self.error = False, str(exc)
                self.stats.error(str(exc))
                self._event(f"PLC error: {exc}", "error")
                if self._client:
                    try:
                        self._client.close()
                    except Exception:   # noqa: BLE001
                        pass
                self._client = None
                self._stop.wait(2.0)           # back off before reconnecting
                due = {g: 0.0 for g in self.groups}
                continue
            nxt = min(due.values()) - time.monotonic()
            self._stop.wait(min(0.05, max(0.001, nxt)))

    # ---- polling -------------------------------------------------------------
    def poll_once(self) -> None:
        """Poll every group once (used by tests and the scanner)."""
        for g in self.groups:
            self.poll_group(g)

    def poll_group(self, group: str) -> dict:
        """One poll of one group: reads every block, mirrors the values into ``self.mem``, times each request and
        appends a raw record (see live/raw.py) for the recorder. Returns the raw record."""
        c, m = self._client, self.map
        t_start = time.monotonic()
        rec = {"t_mono": t_start, "t_wall": time.time(), "group": group, "blocks": []}
        for kind, area, byte0, nbytes in self.groups[group]["blocks"]:
            if kind == "word":
                first = m.word(area, byte0)
                nwords = nbytes // 2
                for off in range(0, nwords, MAX_WORDS_PER_READ):
                    n = min(MAX_WORDS_PER_READ, nwords - off)
                    t0 = time.monotonic()
                    regs = c.read_words(first + off, n)
                    t1 = time.monotonic()
                    for i, r in enumerate(regs):
                        self.mem.set(area, 2, byte0 + (off + i) * 2, r)
                    self.stats.record_block(f"{kind}:{area}{byte0}", (t1 - t0) * 1000)
                    rec["blocks"].append({"kind": kind, "area": area, "byte0": byte0 + off * 2, "addr": first + off, "n": n,
                                          "t0": t0, "t1": t1, "data": list(regs)})
            else:
                nbits = nbytes * 8
                k, first = m.bit(area, byte0, 0) if kind != "wordbits" else m.word_via_bits(area, byte0)
                rk = "coil" if kind in ("wordbits", "coil") else k
                for off in range(0, nbits, MAX_BITS_PER_READ):
                    n = min(MAX_BITS_PER_READ, nbits - off)
                    t0 = time.monotonic()
                    bits = c.read_bits(rk, first + off, n)
                    t1 = time.monotonic()
                    for i, b in enumerate(bits):
                        idx = off + i
                        self.mem.set_bit(area, byte0 + idx // 8, idx % 8, b)
                    self.stats.record_block(f"{kind}:{area}{byte0}", (t1 - t0) * 1000)
                    rec["blocks"].append({"kind": kind, "area": area, "byte0": byte0 + off // 8, "addr": first + off, "n": n,
                                          "t0": t0, "t1": t1, "data": pack_bits(bits)})
        t_end = time.monotonic()
        self.last_ms = (t_end - t_start) * 1000
        self.stats.record_cycle(group, t_start, self.last_ms)
        self.polls += 1
        self._last_t = time.time()
        self._raw.append(rec)
        return rec

    # ---- recorder hooks (called by the Hub) ----------------------------------
    def drain_raw(self) -> list[dict]:
        out = []
        while self._raw:
            out.append(self._raw.popleft())
        return out

    def drain_events(self) -> list[dict]:
        out = []
        while self._events:
            out.append(self._events.popleft())
        return out

    def diag(self) -> dict:
        d = self.stats.summary()
        d.update({"source": "plc", "host": self.host, "port": self.port, "connected": self.connected})
        return d

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
            "taught": self._taught(),
            "live": {"age_s": time.time() - self._last_t, "poll_ms": self.last_ms, "polls": self.polls},
        }
        snap = pose_snapshot("plc", c, b, s, t=time.time(), magnet=bool(m.read("Q0.7")), extra=extra)
        snap["base"].update({"count": m.read("MD600")})
        snap["shoulder"].update({"count": m.read("VD1044")})
        return snap

    def _taught(self) -> list[dict]:
        """The taught points as stored in the real PLC (INIT, 1..4: base %VD2300+4i, shoulder %VD2400+4i) with their tip position."""
        c, m, out = self.cfg, self.mem, []
        for i, name in enumerate(("INI", "1", "2 PICK", "3", "4 DROP")):
            bc, sc = m.read(f"VD{2300 + 4 * i}"), m.read(f"VD{2400 + 4 * i}")
            if bc == 0 and sc == 0:                      # never taught (0/0 is not a pose): no angles, nothing to draw
                out.append({"name": name, "taught": False, "base_count": 0, "sh_count": 0})
                continue
            bd, sd = c.base.count_to_angle(bc) * 180 / 3.141592653589793, c.shoulder.count_to_angle(sc) * 180 / 3.141592653589793
            tip = pose_snapshot("plc", c, bd, sd)["geom"]["tip"]
            out.append({"name": name, "taught": True, "base_count": bc, "sh_count": sc, "base_deg": bd, "sh_deg": sd, "tip": tip})
        return out

    def status(self) -> dict:
        info = f"{self.host}:{self.port} polls={self.polls} {self.last_ms:.0f} ms" if self.connected else (self.error or "idle")
        return {"connected": self.connected, "info": info, "diag": self.diag()}

    def control(self, action: str, params: dict) -> dict:
        if action == "stop":
            self.stop()
        elif action == "start" and not (self._thread and self._thread.is_alive()):
            self.start()
        return {}
