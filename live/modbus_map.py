"""Mapping between Kinco PLC memory (%M20.1, %VD1044, ...) and Modbus TCP coil / register addresses.

!! The offsets below are an ASSUMED default. The real mapping is in the KincoBuilder manual (Modbus
!! address table) and has NOT been verified. Edit `modbus_map.json` or run `python -m live.scan` against the
!! PLC to find the real offsets from values you can see on the HMI.

Rules (shape of the mapping, not the numbers):
  * bit areas are coils (Q, M) or discrete inputs (I): address = base[area] + byte*8 + bit
  * word areas (V, M) are holding registers: address = base[area] + byte//2   (VW1000 -> reg base+500)
  * 32-bit values (VD/MD) use two consecutive registers, low word first (matches the PLC's little-endian memory)
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from twin.il import Memory

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "modbus_map.json")


@dataclass
class ModbusMap:
    coil_base: dict = field(default_factory=lambda: {"Q": 0, "M": 1024})          # [assumed]
    discrete_base: dict = field(default_factory=lambda: {"I": 0})                  # [assumed]
    holding_base: dict = field(default_factory=lambda: {"V": 0, "M": 8192})        # [assumed]
    unit: int = 1                                                                   # [doc] station 1

    # ---- address -> Modbus ------------------------------------------------
    def bit(self, area: str, byte: int, bit: int) -> tuple[str, int]:
        if area == "I":
            return "discrete", self.discrete_base["I"] + byte * 8 + bit
        return "coil", self.coil_base[area] + byte * 8 + bit

    def word(self, area: str, byte: int) -> int:
        return self.holding_base[area] + byte // 2

    # ---- Modbus -> address (used by the server) ---------------------------
    def resolve_bit(self, kind: str, addr: int):
        bases = self.discrete_base if kind == "discrete" else self.coil_base
        for area, base in bases.items():
            n = Memory.SIZES[area] * 8
            if base <= addr < base + n:
                off = addr - base
                return area, off // 8, off % 8
        return None

    def resolve_word(self, addr: int):
        for area, base in self.holding_base.items():
            n = Memory.SIZES[area] // 2
            if base <= addr < base + n:
                return area, (addr - base) * 2
        return None

    # ---- persistence -------------------------------------------------------
    def save(self, path: str = DEFAULT_PATH) -> None:
        with open(path, "w") as fh:
            json.dump(asdict(self), fh, indent=1)

    @classmethod
    def load(cls, path: str = DEFAULT_PATH) -> "ModbusMap":
        if os.path.exists(path):
            with open(path) as fh:
                return cls(**json.load(fh))
        return cls()
