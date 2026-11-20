"""Peacefair PZEM-017 DC power meter (voltage, current, power, energy over Modbus RTU) and the simulated device used for tests.

**REGISTER MAP NOT VERIFIED.** It is written from memory of the Peacefair datasheet and has not been checked against the datasheet or a
real meter. ``REGISTER_MAP_VERIFIED`` stays False until someone does that on the real hardware; check these before trusting numbers:

    input registers (function 0x04), 8 registers from 0x0000:
        0x0000 voltage        1 LSB = 0.01 V
        0x0001 current        1 LSB = 0.01 A
        0x0002 power low  16 bits, 0x0003 power high 16 bits      1 LSB = 0.1 W
        0x0004 energy low 16 bits, 0x0005 energy high 16 bits     1 LSB = 1 Wh
        0x0006 high-voltage alarm status, 0x0007 low-voltage alarm status
    holding registers (functions 0x03 / 0x06):
        0x0000 high-voltage alarm threshold (0.01 V), 0x0001 low-voltage threshold (0.01 V),
        0x0002 slave address (1..247),  0x0003 current range / shunt: 0 = 100 A, 1 = 50 A, 2 = 200 A, 3 = 300 A
    function 0x42: reset the energy counter (frame: slave, 0x42, CRC)
    serial format: 9600 baud, 8 data bits, 2 stop bits (to be checked: the Kinco PLC ports are set to 8N1)
"""
from __future__ import annotations

import random
import threading
import time

from .rtu import RtuMaster, Transport, crc_ok, with_crc

REGISTER_MAP_VERIFIED = False
RANGE_CODES = {100: 0, 50: 1, 200: 2, 300: 3}
RANGE_AMPS = {v: k for k, v in RANGE_CODES.items()}


def decode_regs(r: list[int]) -> dict:
    """The 8 input registers as physical values (see the register map above)."""
    return {"voltage_v": r[0] * 0.01, "current_a": r[1] * 0.01, "power_w": (r[3] << 16 | r[2]) * 0.1,
            "energy_wh": float(r[5] << 16 | r[4]), "high_alarm": bool(r[6]), "low_alarm": bool(r[7]), "regs": list(r)}


class Pzem017:
    """Driver. ``shunt_a`` must match the current range configured in the meter."""

    def __init__(self, master: RtuMaster, slave: int = 1) -> None:
        self.m, self.slave = master, slave

    def read(self) -> dict:
        return decode_regs(self.m.read_input_registers(self.slave, 0x0000, 8))

    def read_settings(self) -> dict:
        r = self.m.read_holding_registers(self.slave, 0x0000, 4)
        return {"high_v": r[0] * 0.01, "low_v": r[1] * 0.01, "address": r[2], "range_a": RANGE_AMPS.get(r[3])}

    # ---- setup (needs RtuMaster(allow_write=True)) ----------------------------------
    def set_address(self, new: int) -> None:
        if not 1 <= new <= 247:
            raise ValueError("slave address must be 1..247")
        self.m.write_single_register(self.slave, 0x0002, new)
        self.slave = new

    def set_range(self, amps: int) -> None:
        if amps not in RANGE_CODES:
            raise ValueError(f"range must be one of {sorted(RANGE_CODES)} A (the shunt that is fitted)")
        self.m.write_single_register(self.slave, 0x0003, RANGE_CODES[amps])

    def reset_energy(self) -> None:
        self.m.raw_command(self.slave, 0x42, b"", reply_len=4)


# ---- simulated device and bus --------------------------------------------------------------------------------------
class SimPzem017:
    """A PZEM-017 as the master sees it: register file, quantisation, energy accumulation, address and range settings.

    ``update(voltage_v, current_a, dt)`` is how the world drives it (the tests, or the twin feed). ``gain_error`` models the meter's
    own error (1 % datasheet) so calibration code can be tested against a known bias."""

    def __init__(self, address: int = 1, range_a: int = 50, gain_error: float = 0.0, noise_a: float = 0.0, seed: int = 0) -> None:
        self.address, self.range_a, self.gain_error, self.noise_a = address, range_a, gain_error, noise_a
        self.v = self.i = 0.0
        self.energy_wh = 0.0
        self.high_v, self.low_v = 3000, 700                   # 30.00 V / 7.00 V thresholds (0.01 V units)
        self._rnd = random.Random(seed)
        self._lock = threading.Lock()

    def update(self, voltage_v: float, current_a: float, dt: float) -> None:
        with self._lock:
            self.v = voltage_v
            self.i = max(0.0, current_a * (1.0 + self.gain_error) + (self._rnd.gauss(0, self.noise_a) if self.noise_a else 0.0))
            self.energy_wh += self.v * self.i * dt / 3600.0

    def _regs(self) -> list[int]:
        with self._lock:
            p = int(round(self.v * self.i * 10))
            e = int(self.energy_wh)
            return [int(round(self.v * 100)) & 0xFFFF, int(round(self.i * 100)) & 0xFFFF, p & 0xFFFF, p >> 16 & 0xFFFF,
                    e & 0xFFFF, e >> 16 & 0xFFFF, int(self.v * 100 > self.high_v), int(self.v * 100 < self.low_v)]

    def handle(self, frame: bytes) -> bytes | None:
        """Answer one request frame; None = stay silent (wrong address or bad CRC, as a real device does)."""
        if len(frame) < 4 or not crc_ok(frame) or frame[0] != self.address:
            return None
        fc = frame[1]
        if fc in (3, 4) and len(frame) == 8:
            addr, n = frame[2] << 8 | frame[3], frame[4] << 8 | frame[5]
            if fc == 4:
                src = self._regs()
            else:
                src = [self.high_v, self.low_v, self.address, RANGE_CODES[self.range_a]]
            if addr + n > len(src) or n < 1:
                return with_crc(bytes((self.address, fc | 0x80, 2)))             # illegal data address
            data = b"".join(v.to_bytes(2, "big") for v in src[addr:addr + n])
            return with_crc(bytes((self.address, fc, len(data))) + data)
        if fc == 6 and len(frame) == 8:
            addr, val = frame[2] << 8 | frame[3], frame[4] << 8 | frame[5]
            if addr == 0 and 0 <= val <= 65535:
                self.high_v = val
            elif addr == 1:
                self.low_v = val
            elif addr == 2 and 1 <= val <= 247:
                reply = with_crc(frame[:6])
                self.address = val
                return reply
            elif addr == 3 and val in RANGE_AMPS:
                self.range_a = RANGE_AMPS[val]
            else:
                return with_crc(bytes((self.address, 0x86, 3)))                  # illegal data value / address
            return with_crc(frame[:6])
        if fc == 0x42 and len(frame) == 4:
            self.energy_wh = 0.0
            return with_crc(bytes((self.address, 0x42)))
        return with_crc(bytes((self.address, fc | 0x80, 1)))                     # illegal function


class SimBus(Transport):
    """A fake RS485 line with simulated devices on it. Fault injection: ``drop`` (probability a request gets no answer),
    ``corrupt`` (probability one reply byte is flipped, so the CRC fails), ``delay_s`` (answer time), and ``cut()`` (cable pulled)."""

    def __init__(self, devices: list[SimPzem017] | None = None, timeout: float = 0.05, drop: float = 0.0, corrupt: float = 0.0,
                 delay_s: float = 0.0, seed: int = 1) -> None:
        self.devices = list(devices or [])
        self.timeout, self.drop, self.corrupt, self.delay_s = timeout, drop, corrupt, delay_s
        self._rx = bytearray()
        self._rnd = random.Random(seed)
        self.cut_line = False
        self.sent: list[bytes] = []

    def cut(self, on: bool = True) -> None:
        self.cut_line = on

    def write(self, data: bytes) -> None:
        self.sent.append(bytes(data))
        if self.cut_line or self._rnd.random() < self.drop:
            return
        for d in self.devices:
            resp = d.handle(bytes(data))
            if resp is not None:
                if self._rnd.random() < self.corrupt:
                    i = self._rnd.randrange(len(resp))
                    resp = resp[:i] + bytes((resp[i] ^ 0x5A,)) + resp[i + 1:]
                if self.delay_s:
                    time.sleep(self.delay_s)
                self._rx += resp
                return

    def read(self, n: int) -> bytes:
        if not self._rx:
            return b""                                     # nothing queued = the master's timeout elapsed (no real waiting needed)
        out, self._rx = bytes(self._rx[:n]), self._rx[n:]
        return out

    def reset_input(self) -> None:
        self._rx.clear()
