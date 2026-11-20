"""Per-motor DC power meters as a live source: polls PZEM-017 meters over Modbus RTU (RS485) and feeds the same ``sensors`` slot as the
ESP32/INA226 sensor feed, so the GUI (measured current in the scope and axis panels), the calibration fit (tools/fit_motor_params.py),
the recorder and the shadow tools work unchanged.

* ``PowerMeterSource``  polls each meter (``base`` and ``shoulder``) at ``hz``; per request it records send/receive times, keeps
  diagnostics (rate, round trip, errors, reconnects, data age) and raw register records for the bag (topic ``sensors/raw``).
* ``SimTwinFeed``       drives simulated meters from the running twin (torque -> current -> power), so everything can be developed, tested
  and shown with no hardware: ``python run_twin.py --power sim``.
* Real hardware:        ``python run_twin.py --power COM5@9600 --power-slaves base=1,shoulder=2`` (USB-RS485 adapter). The master is
  read-only; meter setup (address, range, energy reset) is a separate explicit step, see docs/POWER_METER_PLAN.md.

A raw record: ``{"t_mono","t_wall","meter":"base","slave":1,"t0","t1","regs":[8 register values]}``; ``live.pzem.decode_regs`` turns it
back into volts, amps, watts and Wh.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from twin.diag import PollStats

from .pzem import Pzem017, SimBus, SimPzem017, decode_regs
from .rtu import RtuMaster, SerialTransport
from .sensors import CHANNELS, SensorSource


class PowerMeterSource(SensorSource):
    """Name ``sensors`` on purpose: it replaces the ESP32 source in the same slot (use one or the other)."""

    def __init__(self, slaves: dict[str, int], master_factory, hz: float = 2.0, window_s: float = 1.5, label: str = "", retry_s: float = 3.0) -> None:
        super().__init__(lambda stop: iter(()), window_s=window_s, label=label)
        bad = set(slaves) - set(CHANNELS)
        if bad:
            raise ValueError(f"meter names must be {CHANNELS}, got {sorted(bad)}")
        self.slaves, self.hz, self.retry_s = dict(slaves), hz, retry_s
        self._factory = master_factory
        self.master: RtuMaster | None = None
        self.drivers: dict[str, Pzem017] = {}
        self.extra = {c: {} for c in self.slaves}              # latest meter-side power (W) and energy (Wh) per channel
        # The meter's own energy counter counts whole Wh: one 30 s cycle at 20 W is 0.17 Wh and reads 0. Energy per cycle therefore has to be
        # integrated here from the 0.1 W power readings (trapezoid over the time between polls); gaps longer than max_gap_s are not bridged.
        self.energy_sw_wh = {c: 0.0 for c in self.slaves}
        self.max_gap_s = 5.0
        self._last_p: dict[str, tuple[float, float]] = {}
        self.stats = PollStats()
        self._raw: deque = deque(maxlen=4000)
        self._events: deque = deque(maxlen=200)
        self.connected = False
        self.error = ""

    # ---- constructors ------------------------------------------------------------------------------------------------
    @classmethod
    def from_spec(cls, spec: str, twin=None, slaves: dict[str, int] | None = None, hz: float = 2.0):
        """``sim`` (needs the twin) or ``COM5[@9600]``. Returns ``(source, feed)``; ``feed`` is the object that must be stepped
        by the Hub (``hub.tickers.append(feed)``) for ``sim``, else None."""
        slaves = slaves or {"base": 1, "shoulder": 2}
        if spec == "sim":
            if twin is None:
                raise ValueError("--power sim needs the twin")
            devs = {c: SimPzem017(address=a, range_a=50) for c, a in slaves.items()}
            bus = SimBus(list(devs.values()))
            src = cls(slaves, lambda: RtuMaster(bus), hz=hz, label="sim")
            return src, SimTwinFeed(twin, devs)
        port, _, baud = spec.partition("@")
        return cls(slaves, lambda: RtuMaster(SerialTransport(port, int(baud or 9600), 8, "N", 2, 0.3)), hz=hz, label=spec), None

    # ---- lifecycle ---------------------------------------------------------------------------------------------------
    def start(self) -> "PowerMeterSource":
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.master:
            try:
                self.master.close()
            except Exception:   # noqa: BLE001
                pass
        self.connected = False

    def _event(self, text: str, kind: str = "info") -> None:
        self._events.append({"text": text, "kind": kind, "t_mono": time.monotonic(), "t_wall": time.time()})

    def _connect(self) -> None:
        self.master = self._factory()
        self.drivers = {c: Pzem017(self.master, s) for c, s in self.slaves.items()}
        self._event(f"power meters connected ({self.label})")

    def _loop(self) -> None:
        period = 1.0 / self.hz
        nxt = time.monotonic()
        while not self._stop.is_set():
            try:
                if self.master is None:
                    self._connect()
                self.poll_once()
                self.connected, self.error = True, ""
            except Exception as exc:   # noqa: BLE001
                if self.connected or not self.error:
                    self._event(f"power meter error: {exc}", "error")
                self.connected, self.error = False, str(exc) or type(exc).__name__
                self.stats.error(self.error)
                if isinstance(exc, OSError) or self.master is None:      # port missing / unplugged: reopen later
                    if self.master:
                        try:
                            self.master.close()
                        except Exception:   # noqa: BLE001
                            pass
                    self.master = None
                    self._stop.wait(self.retry_s)
                    nxt = time.monotonic()
                    continue
            nxt += period
            if nxt < time.monotonic():
                nxt = time.monotonic()
            self._stop.wait(max(0.0, nxt - time.monotonic()))

    # ---- one poll of every meter ---------------------------------------------------------------------------------------
    def poll_once(self) -> None:
        """Read every meter once. A meter that fails is counted and skipped; if ALL fail the error propagates (link down)."""
        failures = 0
        last: Exception | None = None
        for ch, drv in self.drivers.items():
            t_start = time.monotonic()
            try:
                t0 = time.monotonic()
                r = drv.read()
                t1 = time.monotonic()
            except Exception as exc:   # noqa: BLE001
                failures += 1
                last = exc
                self.stats.error(f"{ch}: {exc}")
                continue
            now = time.time()
            self.samples[ch].append((now, r["current_a"] * 1000.0, r["voltage_v"] * 1000.0))
            tm = time.monotonic()
            prev = self._last_p.get(ch)
            if prev is not None and tm - prev[0] <= self.max_gap_s:
                self.energy_sw_wh[ch] += 0.5 * (prev[1] + r["power_w"]) * (tm - prev[0]) / 3600.0
            self._last_p[ch] = (tm, r["power_w"])
            self.extra[ch] = {"meter_W": r["power_w"], "Wh": r["energy_wh"], "Wh_sw": self.energy_sw_wh[ch],
                              "high_alarm": r["high_alarm"], "low_alarm": r["low_alarm"]}
            self.count += 1
            self.last_rx = now
            self.stats.record_block(f"read:{ch}", (t1 - t0) * 1000)
            self.stats.record_cycle(ch, t_start, (time.monotonic() - t_start) * 1000)
            self._raw.append({"t_mono": t_start, "t_wall": now, "meter": ch, "slave": self.slaves[ch], "t0": t0, "t1": t1, "regs": r["regs"]})
        if self.drivers and failures == len(self.drivers) and last is not None:
            raise last

    # ---- outputs ---------------------------------------------------------------------------------------------------------
    def latest(self, now: float | None = None) -> dict:
        out = super().latest(now)
        for ch, v in out.items():
            v.update(self.extra.get(ch, {}))
        return out

    def snapshot(self) -> dict | None:
        snap = super().snapshot()
        if snap is not None:
            snap["live"] = {"age_s": (time.time() - self.last_rx) if self.last_rx else None, "polls": self.stats.polls}
        return snap

    def status(self) -> dict:
        age = (time.time() - self.last_rx) if self.last_rx else None
        ok = self.connected and age is not None and age < 3 / self.hz + 1.0
        info = f"{self.label} polls={self.stats.polls} errors={self.stats.errors}" if ok else (self.error or "connecting")
        return {"connected": ok, "info": info, "diag": self.diag()}

    def diag(self) -> dict:
        d = self.stats.summary()
        d.update({"source": "sensors", "label": self.label, "connected": self.connected})
        if self.master:
            d.update({"rtu": {"requests": self.master.requests, "timeouts": self.master.timeouts, "crc_errors": self.master.crc_errors,
                              "exceptions": self.master.exceptions}})
        return d

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


class SimTwinFeed:
    """Drives simulated meters from the running twin: the twin's axis torque becomes a supply current (with its own torque constant
    scaled by ``kt_scale``, so calibration code has something to recover), the supply sags with load, and the meter integrates energy.

    Like a real meter it reports the AVERAGE over its update period, not an instantaneous value: the twin's holding torque chatters from
    one scan to the next, and sampling it at an arbitrary instant would give a value that does not even correlate with the torque
    measured a tick later. Call ``step(dt)`` every tick or so (the Hub does, via ``hub.tickers``)."""

    def __init__(self, twin, devices: dict[str, SimPzem017], kt_scale: float = 1.0, idle_ma: float = 60.0, period_s: float = 0.02) -> None:
        self.twin, self.devices = twin, devices
        self.kt_scale, self.idle_ma, self.period_s = kt_scale, idle_ma, period_s
        self._acc = 0.0
        self._sum = {c: 0.0 for c in devices}                 # integral of current over the period (mA x s)

    def step(self, dt: float) -> None:
        from tools.sim_sensors import measured_current_ma, voltage_mv      # the same current/supply model as the UDP sensor simulator
        cfg = self.twin.cfg
        for ch in self.devices:
            ax = getattr(cfg, ch)
            tau = getattr(self.twin.arm, ch).tau
            self._sum[ch] += measured_current_ma({"tau": tau}, ax.ratio, ax.eta, ax.kt, self.kt_scale, 0.0, self.idle_ma) * dt
        self._acc += dt
        if self._acc < self.period_s:
            return
        for ch, dev in self.devices.items():
            ma = self._sum[ch] / self._acc
            dev.update(voltage_mv(ma) / 1000.0, ma / 1000.0, self._acc)
            self._sum[ch] = 0.0
        self._acc = 0.0
