"""Raw Modbus blocks as recorded in the ``plc/raw`` bag topic, and how to turn them back into PLC memory.

A raw record is one poll of one group::

    {"t_mono": s, "t_wall": s, "group": "fast",
     "blocks": [{"kind": "coil|discrete|word|wordbits", "area": "M", "byte0": 10, "addr": 650, "n": 352,
                 "t0": s, "t1": s, "data": <hex string of bits, LSB first>  or  [register values]}]}

``t0``/``t1`` are the monotonic times the request was sent and the reply received. Bits are packed 8 per byte, bit 0 first,
as a hex string, to keep recordings small.
"""
from __future__ import annotations

from twin.il import Memory


def pack_bits(bits: list[int]) -> str:
    out = bytearray((len(bits) + 7) // 8)
    for i, b in enumerate(bits):
        if b:
            out[i // 8] |= 1 << (i % 8)
    return out.hex()


def unpack_bits(hexstr: str, n: int) -> list[int]:
    raw = bytes.fromhex(hexstr)
    return [(raw[i // 8] >> (i % 8)) & 1 for i in range(n)]


def apply_block(block: dict, mem: Memory) -> None:
    """Write one raw block into ``mem`` (same placement the live reader uses)."""
    area, byte0, n = block["area"], block["byte0"], block["n"]
    if block["kind"] == "word":
        for i, r in enumerate(block["data"]):
            mem.set(area, 2, byte0 + i * 2, r)
    else:
        for i, b in enumerate(unpack_bits(block["data"], n)):
            mem.set_bit(area, byte0 + i // 8, i % 8, b)


def apply_record(record: dict, mem: Memory) -> None:
    for b in record["blocks"]:
        apply_block(b, mem)
