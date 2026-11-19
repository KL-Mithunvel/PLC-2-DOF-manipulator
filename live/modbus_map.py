"""Mapping between Kinco PLC memory (%M20.1, %VD1044, ...) and Modbus coil / register addresses.

Source: Kinco K series PLC Application Manual, section 10.2.2.3 "Modbus register number" (page 483), applicable to
K5, KS, MK and K6 series (the K615S is a K6).  The manual states that the Modbus TCP slave on the Ethernet port works
the same way as Modbus RTU.  Protocol (0-based) addresses:

    area   range            Modbus type            address
    I      I0.0  - I31.7    discrete input (FC2)   0 - 255          = byte*8 + bit
    Q      Q0.0  - Q31.7    coil (FC1/5/15)        0 - 255          = byte*8 + bit
    M      M0.0  - M1023.7  coil / discrete        320 - 8511       = 320 + byte*8 + bit
    V      VW0   - VW4094+  holding/input reg      100 - 2147+      = 100 + byte//2        (VW0 = 100, VW2 = 101)
    AI/AQ  AIW0 - AIW62     input/holding reg      0 - 31                                   (not used by this project)

Consequences:
  * the M area is reachable ONLY as bits.  M words/double words such as %MD600 (base axis position!) must be read as
    32 consecutive coils and assembled (little-endian bit order) - see ``word_via_bits``.
  * 32-bit values in V (VD) use two consecutive registers, low word first (matches the PLC's little-endian memory).
  * limits per request: 1600 bits (FC1/2), 100 words (FC3/4).

Status: taken from the manual, NOT yet verified against the real PLC.  Verify by reading a value you can see on the HMI
(e.g. %VD2020, the base speed) or run `python -m live.scan`; edit `modbus_map.json` if the PLC differs.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from twin.il import Memory

DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "modbus_map.json")

MAX_BITS_PER_READ = 1600
MAX_WORDS_PER_READ = 100


@dataclass
class ModbusMap:
    coil_base: dict = field(default_factory=lambda: {"Q": 0, "M": 320})            # [doc] manual 10.2.2.3
    discrete_base: dict = field(default_factory=lambda: {"I": 0, "M": 320})        # [doc] M is readable as DI too
    holding_base: dict = field(default_factory=lambda: {"V": 100})                 # [doc] VW0 = register 100
    unit: int = 1                                                                   # [doc] station 1

    # ---- address -> Modbus ------------------------------------------------
    def bit(self, area: str, byte: int, bit: int) -> tuple[str, int]:
        if area == "I":
            return "discrete", self.discrete_base["I"] + byte * 8 + bit
        return "coil", self.coil_base[area] + byte * 8 + bit

    def word(self, area: str, byte: int) -> int:
        if area not in self.holding_base:
            raise KeyError(f"area {area} has no register mapping on this PLC: read it as bits (word_via_bits)")
        return self.holding_base[area] + byte // 2

    def word_via_bits(self, area: str, byte: int) -> tuple[str, int]:
        """(kind, first coil address) for reading a word/dword of a bit-only area (M) as consecutive coils."""
        return self.bit(area, byte, 0)

    # ---- Modbus -> address (used by the twin's server) ---------------------
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
