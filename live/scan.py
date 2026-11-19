"""Find the real Kinco->Modbus address offsets from values you can see on the HMI / in KincoBuilder.

    python -m live.scan --host 192.168.0.252 --know VD2020=300 --know VW2036=3 [--save]

For every known word value the whole holding-register space is searched (read-only); the offset
``found_register - byte//2`` is reported per area, and offsets that agree across all known values win.
Use values that are distinctive (not 0 / 1). 32-bit values (VD/MD) are matched as two registers, low word first.
"""
from __future__ import annotations

import argparse
import re
from collections import Counter

from twin.il import parse_operand

from .modbus_map import ModbusMap


def read_all_words(read_words, limit: int = 65536, chunk: int = 100) -> dict[int, int]:
    regs: dict[int, int] = {}
    for a in range(0, limit, chunk):
        try:
            for i, v in enumerate(read_words(a, min(chunk, limit - a))):
                regs[a + i] = v
        except Exception:   # noqa: BLE001  (unmapped block: skip)
            continue
    return regs


def find_offsets(regs: dict[int, int], known: dict[str, int]) -> dict[str, Counter]:
    """known: {"VD2020": 300, ...} -> {"V": Counter({offset: votes}), ...}"""
    votes: dict[str, Counter] = {}
    for text, value in known.items():
        op = parse_operand("%" + text)
        if op.kind != "num" or op.size not in (2, 4):
            continue
        raw = value & ((1 << (8 * op.size)) - 1)
        words = [raw & 0xFFFF] if op.size == 2 else [raw & 0xFFFF, raw >> 16]
        hits = [a for a in regs if all(regs.get(a + i) == w for i, w in enumerate(words))]
        c = votes.setdefault(op.area, Counter())
        for a in hits:
            c[a - op.addr // 2] += 1
    return votes


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=502)
    ap.add_argument("--know", action="append", default=[], help="NAME=VALUE, e.g. VD2020=300")
    ap.add_argument("--save", action="store_true", help="write the best offsets to live/modbus_map.json")
    a = ap.parse_args()
    from .plc_reader import ReadOnlyClient
    cl = ReadOnlyClient(a.host, a.port)
    if not cl.connect():
        raise SystemExit("cannot connect")
    known = {k: int(v) for k, v in (s.split("=") for s in a.know)}
    votes = find_offsets(read_all_words(cl.read_words), known)
    m = ModbusMap.load()
    for area, c in votes.items():
        print(area, c.most_common(5))
        if c:
            m.holding_base[area] = c.most_common(1)[0][0]
    if a.save:
        m.save()
        print("saved live/modbus_map.json")
    cl.close()


if __name__ == "__main__":
    main()
