"""Conversion and inspection helpers: ``python -m bag info FILE`` / ``python -m bag convert OLD.jsonl [OUT]``."""
from __future__ import annotations

import json
import os
import sys

from .core import BagReader, BagWriter, is_bag
from .meta import collect_meta


def convert_jsonl_log(src: str, dst: str | None = None, fmt: str = "auto", topic: str = "twin/state", **meta) -> str:
    """Old ``logs/*.jsonl`` (one snapshot per line, from twin.sources.Recorder) -> bag. Source time ``t`` is used as t_mono."""
    dst = dst or os.path.splitext(src)[0]
    with open(src, encoding="utf-8") as fh, BagWriter(dst, collect_meta(converted_from=os.path.basename(src), **meta), fmt=fmt) as bw:
        for line in fh:
            if line.strip():
                s = json.loads(line)
                bw.write(topic, s, t_mono=s["t"], t_wall=s.get("wall", s["t"]))
        return bw.path


def info(path: str) -> str:
    r = BagReader(path)
    lines = [f"{path}", f"  format {r.fmt}, duration {r.duration:.1f} s (monotonic), {sum(r.topics.values())} messages"]
    for t, n in sorted(r.topics.items()):
        lines.append(f"  {t:14s} {n:8d}")
    g = r.meta.get("git", {})
    lines.append(f"  commit {g.get('commit')}{' (dirty)' if g.get('dirty') else ''}, PLC program {r.meta.get('plc_program_sha')}, created {r.meta.get('created_iso')}")
    extra = {k: v for k, v in r.meta.items() if k not in ("created_wall", "created_iso", "host", "python", "platform", "git", "plc_program_sha", "modbus_map_sha", "versions")}
    if extra:
        lines.append(f"  notes {extra}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "info":
        for p in argv[1:]:
            print(info(p))
        return 0
    if len(argv) >= 2 and argv[0] == "convert":
        print("wrote", convert_jsonl_log(argv[1], argv[2] if len(argv) > 2 else None))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
