"""Kinco KincoBuilder Instruction-List (IL) interpreter.

Runs the *actual* exported program (``plc/MAIN_MAIN.ilp``) one scan at a time.

Semantics implemented (verified against the 39 networks of the real program):
  * one boolean accumulator (``acc``) plus a parenthesis stack for ``AND(`` / ``OR(`` ... ``)``
  * LD/LDN load; AND/ANDN/OR/ORN combine; ST writes; S/R set/reset when acc is true
  * MOVE/ADD/SUB are *gated* by the accumulator and do not change it
  * GT/LT/GE/LE/EQ/NE AND their comparison result onto the accumulator
  * TON/TOF/CTU take the accumulator as input and leave the timer/counter bit in it
  * __CR_EQ_1 / __CR_RESTORE (compiler pseudo-ops) force acc=1 around an unconditional
    MOVE and then restore the previous acc
  * memory is byte addressed and little-endian, so %VW2400 aliases the low word of %VD2400
    (this reproduces a real quirk of the program, see docs)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_ADDR = re.compile(r"^%(SM|BR|I|Q|M|V)([BWD])?(\d+)(?:\.(\d))?$")
_SIZES = {"B": 1, "W": 2, "D": 4}


# --------------------------------------------------------------------------- memory
class Memory:
    """PLC data areas. All multi-byte values are little-endian, signed on read."""

    SIZES = {"I": 16, "Q": 16, "M": 1024, "V": 8192, "SM": 64, "BR": 16}

    def __init__(self) -> None:
        self.area = {k: bytearray(v) for k, v in self.SIZES.items()}

    def get_bit(self, area: str, byte: int, bit: int) -> int:
        return (self.area[area][byte] >> bit) & 1

    def set_bit(self, area: str, byte: int, bit: int, val: int) -> None:
        if val:
            self.area[area][byte] |= 1 << bit
        else:
            self.area[area][byte] &= ~(1 << bit) & 0xFF

    def get(self, area: str, size: int, addr: int, signed: bool = True) -> int:
        return int.from_bytes(self.area[area][addr:addr + size], "little", signed=signed)

    def set(self, area: str, size: int, addr: int, val: int) -> None:
        mask = (1 << (8 * size)) - 1
        self.area[area][addr:addr + size] = (int(val) & mask).to_bytes(size, "little")

    # convenience for text addresses such as "%VD1044" or "M30.1"
    def read(self, text: str) -> int:
        op = parse_operand(text if text.startswith("%") else "%" + text)
        if op.kind == "bit":
            return self.get_bit(op.area, op.addr, op.bit)
        return self.get(op.area, op.size, op.addr)

    def write(self, text: str, val: int) -> None:
        op = parse_operand(text if text.startswith("%") else "%" + text)
        if op.kind == "bit":
            self.set_bit(op.area, op.addr, op.bit, val)
        else:
            self.set(op.area, op.size, op.addr, val)


@dataclass(frozen=True)
class Operand:
    kind: str            # bit | num | imm | timer | counter
    text: str
    area: str = ""
    size: int = 0        # bytes for num/imm (0 = infer)
    addr: int = 0
    bit: int = 0
    value: int = 0       # imm
    index: int = 0       # timer / counter number


def parse_operand(tok: str) -> Operand:
    tok = tok.strip()
    m = _ADDR.match(tok)
    if m:
        area, sz, addr, bit = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        if sz is None:
            return Operand("bit", tok, area, 0, addr, int(bit or 0))
        return Operand("num", tok, area, _SIZES[sz], addr)
    if tok.startswith("DI#"):
        return Operand("imm", tok, size=4, value=int(tok[3:]))
    if tok.startswith("T") and tok[1:].isdigit():
        return Operand("timer", tok, index=int(tok[1:]))
    if tok.startswith("C") and tok[1:].isdigit():
        return Operand("counter", tok, index=int(tok[1:]))
    if re.fullmatch(r"-?\d+", tok):
        return Operand("imm", tok, size=0, value=int(tok))
    raise ValueError(f"unsupported operand {tok!r}")


# --------------------------------------------------------------------------- program
@dataclass
class Instr:
    op: str
    args: list[Operand]
    net: int
    text: str


@dataclass
class Network:
    index: int
    label: str = ""
    first: int = 0       # index of first instruction
    last: int = 0        # one past last


@dataclass
class Program:
    instrs: list[Instr] = field(default_factory=list)
    networks: list[Network] = field(default_factory=list)

    @classmethod
    def load(cls, path: str) -> "Program":
        with open(path, "r", encoding="latin-1") as fh:
            return cls.parse(fh.read())

    @classmethod
    def parse(cls, source: str) -> "Program":
        prog = cls()
        net = -1
        for raw in source.replace("\r", "").split("\n"):
            line = raw.strip()
            if not line:
                continue
            m = re.fullmatch(r"\(\*\s*Network\s+(\d+)\s*\*\)", line)
            if m:
                if prog.networks:
                    prog.networks[-1].last = len(prog.instrs)
                net = int(m.group(1))
                prog.networks.append(Network(net, first=len(prog.instrs)))
                continue
            if line.startswith("(*"):
                text = line[2:-2].strip() if line.endswith("*)") else line[2:]
                if net >= 0 and prog.networks and not prog.networks[-1].label and not text.isdigit():
                    prog.networks[-1].label = text
                continue
            parts = line.split(None, 1)
            op = parts[0].upper()
            args = [parse_operand(a) for a in parts[1].split(",")] if len(parts) > 1 else []
            prog.instrs.append(Instr(op, args, net, line))
        if prog.networks:
            prog.networks[-1].last = len(prog.instrs)
        return prog


# --------------------------------------------------------------------------- timers / counters
@dataclass
class Timer:
    kind: str = "TON"
    bit: int = 0
    elapsed_ms: float = 0.0
    preset: int = 0


@dataclass
class Counter:
    count: int = 0
    prev: int = 0
    preset: int = 0

    @property
    def bit(self) -> int:
        return 1 if self.count >= self.preset > 0 else 0


# --------------------------------------------------------------------------- VM
class ILMachine:
    """Executes a Program against a Memory, one full scan per call to :meth:`scan`."""

    def __init__(self, program: Program, memory: Memory, timer_base_ms: float = 10.0,
                 timer_base_override: dict[int, float] | None = None) -> None:
        self.p = program
        self.mem = memory
        self.timer_base_ms = timer_base_ms
        self.timer_base_override = timer_base_override or {}
        self.timers: dict[int, Timer] = {}
        self.counters: dict[int, Counter] = {}
        # per-instruction trace of the last scan: bit0 = accumulator after, bit1 = action executed
        self.trace = bytearray(len(program.instrs))
        self.net_power = bytearray(len(program.networks))
        self.scan_count = 0

    # -- operand access --------------------------------------------------
    def _base(self, n: int) -> float:
        return self.timer_base_override.get(n, self.timer_base_ms)

    def _bit(self, o: Operand) -> int:
        if o.kind == "bit":
            return self.mem.get_bit(o.area, o.addr, o.bit)
        if o.kind == "timer":
            return self.timers.get(o.index, Timer()).bit
        if o.kind == "counter":
            return self.counters.get(o.index, Counter()).bit
        raise ValueError(f"{o.text} is not a bit operand")

    def _num(self, o: Operand) -> int:
        if o.kind == "num":
            return self.mem.get(o.area, o.size, o.addr)
        if o.kind == "imm":
            return o.value
        if o.kind == "timer":
            t = self.timers.get(o.index)
            return int(t.elapsed_ms / self._base(o.index)) if t else 0
        if o.kind == "counter":
            c = self.counters.get(o.index)
            return c.count if c else 0
        if o.kind == "bit":
            return self._bit(o)
        raise ValueError(o.text)

    def _store(self, o: Operand, val: int) -> None:
        if o.kind == "bit":
            self.mem.set_bit(o.area, o.addr, o.bit, val)
        elif o.kind == "num":
            self.mem.set(o.area, o.size, o.addr, val)
        else:
            raise ValueError(f"cannot write {o.text}")

    @staticmethod
    def _wrap(val: int, size: int) -> int:
        bits = 8 * size
        val &= (1 << bits) - 1
        return val - (1 << bits) if val >> (bits - 1) else val

    # -- one scan --------------------------------------------------------
    def scan(self, dt_ms: float) -> None:
        acc = 0
        stack: list[tuple[str, int]] = []
        cr: list[int] = []
        tr = self.trace
        for i, ins in enumerate(self.p.instrs):
            op, a = ins.op, ins.args
            act = 0
            if op == "LD":
                acc = self._bit(a[0])
            elif op == "LDN":
                acc = 1 - self._bit(a[0])
            elif op == "AND":
                acc &= self._bit(a[0])
            elif op == "ANDN":
                acc &= 1 - self._bit(a[0])
            elif op == "OR":
                acc |= self._bit(a[0])
            elif op == "ORN":
                acc |= 1 - self._bit(a[0])
            elif op in ("AND(", "OR("):
                stack.append((op[:-1], acc))
            elif op == ")":
                kind, saved = stack.pop()
                acc = (saved & acc) if kind == "AND" else (saved | acc)
            elif op == "ST":
                self._store(a[0], acc)
                act = 1
            elif op == "S":
                if acc:
                    self._store(a[0], 1)
                    act = 1
            elif op == "R":
                if acc:
                    self._store(a[0], 0)
                    act = 1
            elif op == "MOVE":
                if acc:
                    self._store(a[1], self._num(a[0]))
                    act = 1
            elif op in ("ADD", "SUB"):
                if acc:
                    size = a[1].size or 4
                    d = self._num(a[1])
                    s = self._num(a[0])
                    self._store(a[1], self._wrap(d + s if op == "ADD" else d - s, size))
                    act = 1
            elif op in ("GT", "LT", "GE", "LE", "EQ", "NE"):
                x, y = self._num(a[0]), self._num(a[1])
                r = {"GT": x > y, "LT": x < y, "GE": x >= y, "LE": x <= y, "EQ": x == y, "NE": x != y}[op]
                acc &= 1 if r else 0
            elif op in ("TON", "TOF"):
                n = a[0].index
                pt = self._num(a[1])
                t = self.timers.setdefault(n, Timer(op))
                t.kind, t.preset = op, pt
                base = self._base(n)
                if op == "TON":
                    if acc:
                        t.elapsed_ms = min(t.elapsed_ms + dt_ms, pt * base)
                        t.bit = 1 if t.elapsed_ms >= pt * base else 0
                    else:
                        t.elapsed_ms, t.bit = 0.0, 0
                else:
                    if acc:
                        t.bit, t.elapsed_ms = 1, 0.0
                    elif t.bit:
                        t.elapsed_ms += dt_ms
                        if t.elapsed_ms >= pt * base:
                            t.bit = 0
                acc = t.bit
            elif op == "CTU":
                n = a[0].index
                c = self.counters.setdefault(n, Counter())
                c.preset = self._num(a[2])
                if self._bit(a[1]):
                    c.count = 0
                elif acc and not c.prev and c.count < 32767:
                    c.count += 1
                c.prev = acc
                acc = c.bit
            elif op == "__CR_EQ_1":
                cr.append(acc)
                acc = 1
            elif op == "__CR_RESTORE":
                acc = cr.pop()
            else:
                raise NotImplementedError(f"IL op {op} (network {ins.net})")
            tr[i] = (acc & 1) | (act << 1)
        for k, net in enumerate(self.p.networks):
            self.net_power[k] = 1 if any(tr[j] & 1 for j in range(net.first, net.last)) else 0
        self.scan_count += 1

    # -- helpers for the UI ---------------------------------------------
    def operand_values(self) -> dict[str, int]:
        """Current value of every operand used by the program (for the live viewer)."""
        out: dict[str, int] = {}
        for ins in self.p.instrs:
            for o in ins.args:
                if o.kind in ("bit", "timer", "counter", "num") and o.text not in out:
                    if o.kind == "bit":
                        out[o.text] = self._bit(o)
                    elif o.kind == "timer":
                        out[o.text] = self._num(o)
                        out[o.text + ".q"] = self._bit(o)
                    elif o.kind == "counter":
                        out[o.text] = self._num(o)
                        out[o.text + ".q"] = self._bit(o)
                    else:
                        out[o.text] = self._num(o)
        return out
