"""ESP32 + INA226 motor current/voltage logger, simulated: a register-level INA226 chip model, a line-for-line Python port of the sketch's
algorithm (``firmware/motor_sensors/motor_sensors.ino``), and the twin-driven feed that makes it run with no hardware.

Why simulate the firmware: the sketch has never run on hardware, and the numbers it prints depend on details that are easy to get wrong
(calibration register, LSB values, averaging window, the +-81.92 mV shunt limit). Here the chip behaves as the TI datasheet says, so the
sketch's arithmetic, its clipping behaviour with a wrong shunt, and what the host receives can all be tested first.

INA226 model (datasheet SBOS547):
    0x00 configuration (reset 0x4127): AVG bits 11:9, VBUSCT 8:6, VSHCT 5:3, MODE 2:0
    0x01 shunt voltage   signed, 1 LSB = 2.5 uV  (full scale +-81.92 mV: the result saturates there)
    0x02 bus voltage     1 LSB = 1.25 mV (measured at the IN- pin, i.e. the load side of the shunt)
    0x03 power           1 LSB = 25 x current LSB
    0x04 current         signed = shunt register x calibration / 2048
    0x05 calibration     CAL = 0.00512 / (current LSB x R_shunt)
    0xFE manufacturer ID 0x5449, 0xFF die ID 0x2260
A result is the average of AVG conversions of (VSHCT + VBUSCT) each, and the registers update once per averaged result, not continuously.
"""
from __future__ import annotations

import math
import random
import re
import time
from bisect import bisect_right
from collections import deque

AVG_COUNTS = (1, 4, 16, 64, 128, 256, 512, 1024)
CT_S = (140e-6, 204e-6, 332e-6, 588e-6, 1.1e-3, 2.116e-3, 4.156e-3, 8.244e-3)
REG_CONFIG, REG_SHUNT, REG_BUS, REG_POWER, REG_CURRENT, REG_CAL, REG_MANUF, REG_DIE = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0xFE, 0xFF


def _s16(x: int) -> int:
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


class INA226:
    """One chip on the I2C bus. The world drives it through ``set_input(t, current_a, bus_v)`` (call it as often as the signal changes);
    the master reads registers with ``read_reg(reg, t)`` at time ``t`` (seconds, same clock)."""

    def __init__(self, address: int = 0x40, r_shunt: float = 0.1, noise_uv: float = 0.0, offset_uv: float = 0.0, seed: int = 0) -> None:
        self.address, self.r_shunt = address, r_shunt
        self.noise_uv, self.offset_uv = noise_uv, offset_uv
        self.config, self.cal = 0x4127, 0
        self._rnd = random.Random(seed)
        self._t: list[float] = [0.0]
        self._i: list[float] = [0.0]
        self._v: list[float] = [0.0]

    # ---- the world side -------------------------------------------------------------------------------------------------
    def set_input(self, t: float, current_a: float, bus_v: float) -> None:
        self._t.append(t); self._i.append(current_a); self._v.append(bus_v)
        if len(self._t) > 20000:                                   # keep the window we can still need, not the whole run
            del self._t[:10000]; del self._i[:10000]; del self._v[:10000]

    @property
    def window_s(self) -> float:
        avg = AVG_COUNTS[self.config >> 9 & 7]
        return avg * (CT_S[self.config >> 3 & 7] + CT_S[self.config >> 6 & 7])

    def _averaged(self, t: float) -> tuple[float, float]:
        """Average input over the last COMPLETED conversion window before ``t`` (zero-order hold between set_input calls)."""
        w = self.window_s
        t_end = math.floor(t / w) * w if w > 0 else t
        n = max(2, int(w / 0.0005))
        si = sv = 0.0
        for k in range(n):
            tk = t_end - w + (k + 0.5) * w / n
            j = max(0, bisect_right(self._t, tk) - 1)
            si += self._i[j]; sv += self._v[j]
        return si / n, sv / n

    # ---- the I2C register interface --------------------------------------------------------------------------------------
    def write_reg(self, reg: int, value: int) -> None:
        if reg == REG_CONFIG:
            if value & 0x8000:                                     # reset bit
                self.config, self.cal = 0x4127, 0
            else:
                self.config = value & 0x7FFF | 0x4000
        elif reg == REG_CAL:
            self.cal = value & 0xFFFF

    def read_reg(self, reg: int, t: float) -> int:
        """Unsigned 16-bit value as it would come over the wire."""
        if reg == REG_CONFIG:
            return self.config
        if reg == REG_MANUF:
            return 0x5449
        if reg == REG_DIE:
            return 0x2260
        if reg == REG_CAL:
            return self.cal
        if self.config & 7 not in (3, 4, 5, 6, 7):                 # not in a measuring mode (power-down / triggered-idle): registers hold zero
            return 0
        i_a, v_bus = self._averaged(t)
        v_sh = i_a * self.r_shunt * 1e6 + self.offset_uv + (self._rnd.gauss(0, self.noise_uv) if self.noise_uv else 0.0)    # microvolts
        sh = max(-32768, min(32767, int(round(v_sh / 2.5))))                           # shunt register saturates at +-81.92 mV
        if reg == REG_SHUNT:
            return sh & 0xFFFF
        if reg == REG_BUS:
            return max(0, min(0x7FFF, int(round(v_bus / 1.25e-3))))
        cur = max(-32768, min(32767, int(sh * self.cal / 2048)))
        if reg == REG_CURRENT:
            return cur & 0xFFFF
        if reg == REG_POWER:
            return max(0, min(0xFFFF, int(abs(cur) * max(0, int(round(v_bus / 1.25e-3))) / 20000)))
        return 0


# ---- the sketch, ported ------------------------------------------------------------------------------------------------
def parse_sketch_constants(path: str) -> dict:
    """Read the constants the sketch is configured with, so the simulation can be checked against the real file."""
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    out = {}
    m = re.search(r"SHUNT_OHMS\s*=\s*([0-9.eE+-]+)f", src); out["shunt_ohms"] = float(m.group(1)) if m else None
    m = re.search(r"MAX_CURRENT\s*=\s*([0-9.eE+-]+)f", src); out["max_current"] = float(m.group(1)) if m else None
    m = re.search(r"PERIOD_MS\s*=\s*(\d+)", src); out["period_ms"] = int(m.group(1)) if m else None
    m = re.search(r"ADDR\[2\]\s*=\s*\{\s*(0x[0-9A-Fa-f]+)\s*,\s*(0x[0-9A-Fa-f]+)", src); out["addr"] = (int(m.group(1), 16), int(m.group(2), 16)) if m else None
    m = re.search(r"AVG_BITS\s*=\s*(0b[01]+|\d+)", src); out["avg_bits"] = int(m.group(1), 0) if m else None
    m = re.search(r"CT_BITS\s*=\s*(0b[01]+|\d+)", src); out["ct_bits"] = int(m.group(1), 0) if m else None
    return out


class EspFirmware:
    """The sketch's setup() and loop() in Python, against two INA226 chips (ch 0 = base, ch 1 = shoulder). ``loop(t)`` returns the text
    lines the sketch would print/send, at most one set per PERIOD_MS."""

    def __init__(self, chips: list[INA226], shunt_ohms: float = 0.005, max_current: float = 10.0, period_ms: int = 10,
                 avg_bits: int = 0b010, ct_bits: int = 0b100) -> None:
        self.chips, self.shunt_ohms, self.max_current, self.period_ms = chips, shunt_ohms, max_current, period_ms
        self.avg_bits, self.ct_bits = avg_bits, ct_bits
        self._next_ms = 0
        self.lines_sent = 0
        self.boot_lines = self.setup()

    def setup(self) -> list[str]:
        self.current_lsb = self.max_current / 32768.0
        cal = int(0.00512 / (self.current_lsb * self.shunt_ohms)) & 0xFFFF                   # (uint16_t) cast truncates
        out = []
        for i, c in enumerate(self.chips):
            if c.read_reg(REG_MANUF, 0.0) != 0x5449:                                           # the hardened check: is an INA226 really there?
                out.append(f"E,0,ina226 {i} not found at {c.address:#04x}")
                continue
            c.write_reg(REG_CONFIG, 0x4000 | self.avg_bits << 9 | self.ct_bits << 6 | self.ct_bits << 3 | 0b111)
            c.write_reg(REG_CAL, cal)
        self.cal = cal
        out.append(f"H,1,{self.shunt_ohms * 1000:.1f},{self.max_current * 1000:.0f},{cal},{self.avg_bits},{self.period_ms}" + chr(10))
        return out

    def loop(self, t: float) -> list[str]:
        ms = int(t * 1000)
        if ms < self._next_ms:
            return []
        self._next_ms = ms + self.period_ms
        out = []
        for ch, c in enumerate(self.chips):
            ma = _s16(c.read_reg(REG_CURRENT, t)) * self.current_lsb * 1000.0
            mv = c.read_reg(REG_BUS, t) * 1.25
            out.append(f"S,{ms},{ch},{ma:.0f},{mv:.0f}\n")
        self.lines_sent += len(out)
        return out


class EspSim:
    """The whole logger, driven by the twin: torque -> supply current -> INA226 inputs, the firmware port reads them on its own 10 ms
    clock and the resulting lines go to a ``live.sensors.SensorSource`` exactly as UDP/serial lines would. ``step(dt)`` is called by the Hub
    (``hub.tickers``); time here is the accumulated ``dt``, so a faster-than-real-time test run keeps a consistent clock."""

    def __init__(self, twin, source, r_shunt: float = 0.005, kt_scale: float = 1.0, idle_ma: float = 60.0, **fw_kw) -> None:
        self.twin, self.source = twin, source
        self.kt_scale, self.idle_ma = kt_scale, idle_ma
        self.chips = [INA226(0x40, r_shunt), INA226(0x41, r_shunt)]
        self.fw = EspFirmware(self.chips, shunt_ohms=r_shunt, **fw_kw)
        self.t = 0.0
        self.wall0 = time.time()
        for line in self.fw.boot_lines:
            source.feed_line(line, now=self.wall0)

    def step(self, dt: float) -> None:
        from tools.sim_sensors import measured_current_ma, voltage_mv
        self.t += dt
        cfg = self.twin.cfg
        for chip, ch in zip(self.chips, ("base", "shoulder")):
            ax = getattr(cfg, ch)
            ma = measured_current_ma({"tau": getattr(self.twin.arm, ch).tau}, ax.ratio, ax.eta, ax.kt, self.kt_scale, 0.0, self.idle_ma)
            chip.set_input(self.t, ma / 1000.0, voltage_mv(ma) / 1000.0)
        for line in self.fw.loop(self.t):
            self.source.feed_line(line, now=self.wall0 + self.t)
