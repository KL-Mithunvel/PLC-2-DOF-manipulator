"""Bag files: timestamped, topic-based recordings of everything the twin and the live sources produce.

Two interchangeable on-disk formats behind one API:

* ``.mcap``      MCAP (ROS 2 bag container; opens in Foxglove Studio). Needs the optional ``mcap`` package.
* ``.bag.jsonl`` JSON lines, standard library only. Line 1 is the header, every other line one message.

A message is ``(topic, t_mono, t_wall, payload)``: ``t_mono`` = ``time.monotonic()`` seconds on the recording machine
(use it for latency and ordering, it never jumps), ``t_wall`` = unix time (use it to line up with other machines).
Payloads are JSON-serialisable dicts. Standard topics are listed in ``TOPICS``.
"""
from __future__ import annotations

import json
import os
import time
from struct import error as struct_error
from dataclasses import dataclass
from typing import Iterator

FORMAT_VERSION = 1
TOPICS = {
    "twin/state": "full twin snapshot (docs/SCHEMA.md)",
    "plc/raw": "raw Modbus blocks as polled",
    "plc/decoded": "decoded PLC snapshot (pose, bits, registers)",
    "mocap/pose": "camera pose snapshot",
    "sensors": "motor current/voltage",
    "events": "discrete events {text, kind}",
    "diag": "pipeline diagnostics (latency, jitter, errors)",
    "hmi/frame": "real HMI picture reference (low rate)",
}
SUFFIX_MCAP, SUFFIX_JSONL = ".mcap", ".bag.jsonl"


def mcap_available() -> bool:
    try:
        import mcap  # noqa: F401
        return True
    except ImportError:
        return False


def is_bag(name: str) -> bool:
    return name.endswith(SUFFIX_MCAP) or name.endswith(SUFFIX_JSONL)


@dataclass
class Message:
    topic: str
    t_mono: float
    t_wall: float
    payload: dict


def _dumps(o) -> str:
    return json.dumps(o, separators=(",", ":"), allow_nan=False, default=_default)


def _default(o):
    if hasattr(o, "tolist"):        # numpy scalars and arrays
        return o.tolist()
    raise TypeError(f"not JSON serialisable: {type(o).__name__}")


# ------------------------------------------------------------------------------------------------ writer
class BagWriter:
    """``BagWriter(path, meta).write(topic, payload)`` ... ``.close()``. ``fmt`` = auto | mcap | jsonl.

    ``auto`` picks MCAP when the package is installed and the path ends in .mcap or has no known suffix; otherwise JSON lines.
    The right suffix is added to ``path`` when missing.
    """

    def __init__(self, path: str, meta: dict | None = None, fmt: str = "auto") -> None:
        if fmt == "auto":
            fmt = "mcap" if (path.endswith(SUFFIX_MCAP) or (not is_bag(path) and mcap_available())) else "jsonl"
        if fmt == "mcap" and not mcap_available():
            raise RuntimeError("MCAP format needs the 'mcap' package (pip install mcap), or use fmt='jsonl'")
        if not is_bag(path):
            path += SUFFIX_MCAP if fmt == "mcap" else SUFFIX_JSONL
        self.path, self.fmt, self.meta = path, fmt, dict(meta or {})
        self.count: dict[str, int] = {}
        self.t_first_mono = None
        self.closed = False
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._fh = open(path, "wb")
        if fmt == "mcap":
            from mcap.writer import IndexType, Writer
            # No chunking: every message goes straight to the file, so a crash or power cut loses almost nothing
            # (chunked MCAP buffers up to a chunk in memory). Costs the compression; JSON bags are small anyway.
            self._w = Writer(self._fh, use_chunking=False, index_types=IndexType.NONE)
            self._w.start(profile="", library="plc-2dof-twin/bag")
            self._chan: dict[str, int] = {}
            self._w.add_metadata("run", {"json": _dumps({"format": FORMAT_VERSION, "meta": self.meta})})
        else:
            self._fh.write((_dumps({"bag": FORMAT_VERSION, "meta": self.meta}) + "\n").encode("utf-8"))

    def write(self, topic: str, payload: dict, t_mono: float | None = None, t_wall: float | None = None) -> None:
        if self.closed:
            raise ValueError("bag is closed")
        tm = time.monotonic() if t_mono is None else t_mono
        tw = time.time() if t_wall is None else t_wall
        if self.t_first_mono is None:
            self.t_first_mono = tm
        self.count[topic] = self.count.get(topic, 0) + 1
        if self.fmt == "mcap":
            cid = self._chan.get(topic)
            if cid is None:
                cid = self._chan[topic] = self._w.register_channel(topic=topic, message_encoding="json", schema_id=0)
            self._w.add_message(cid, int(tw * 1e9), _dumps(payload).encode("utf-8"), int(tm * 1e9))
        else:
            self._fh.write((_dumps({"topic": topic, "tm": tm, "tw": tw, "d": payload}) + "\n").encode("utf-8"))

    def flush(self) -> None:
        self._fh.flush()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        if self.fmt == "mcap":
            self._w.finish()
        self._fh.close()

    def __enter__(self) -> "BagWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


# ------------------------------------------------------------------------------------------------ reader
class BagReader:
    """Reads either format. ``meta``, ``topics`` (name -> message count) and ``messages()`` in recording order."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.fmt = "mcap" if path.endswith(SUFFIX_MCAP) else "jsonl"
        self.meta: dict = {}
        self.topics: dict[str, int] = {}
        self.truncated = False                   # True when the file was not closed cleanly (crash, power cut) or ends mid-record
        self.t_mono_range = (None, None)
        self._scan()

    def _scan(self) -> None:
        lo = hi = None
        for m in self.messages():
            self.topics[m.topic] = self.topics.get(m.topic, 0) + 1
            lo = m.t_mono if lo is None else min(lo, m.t_mono)
            hi = m.t_mono if hi is None else max(hi, m.t_mono)
        self.t_mono_range = (lo, hi)

    @property
    def duration(self) -> float:
        lo, hi = self.t_mono_range
        return 0.0 if lo is None else hi - lo

    def messages(self, topics: set[str] | list[str] | None = None, t_from: float | None = None, t_to: float | None = None) -> Iterator[Message]:
        """Messages in file order. ``t_from``/``t_to`` are ``t_mono`` seconds (inclusive)."""
        want = set(topics) if topics else None
        for m in (self._iter_mcap() if self.fmt == "mcap" else self._iter_jsonl()):
            if want is not None and m.topic not in want:
                continue
            if t_from is not None and m.t_mono < t_from:
                continue
            if t_to is not None and m.t_mono > t_to:
                continue
            yield m

    def _iter_jsonl(self) -> Iterator[Message]:
        with open(self.path, "r", encoding="utf-8") as fh:
            head = fh.readline()
            if not head.strip():
                return
            h = json.loads(head)
            if "bag" not in h:
                raise ValueError(f"{self.path}: not a bag file (missing header)")
            self.meta = h.get("meta", {})
            for line in fh:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:         # a half-written last line after a crash: stop there
                    self.truncated = True
                    return
                yield Message(o["topic"], o["tm"], o["tw"], o["d"])

    def _iter_mcap(self) -> Iterator[Message]:
        """Sequential read (ignores the summary/footer), so files from a process that was killed still open;
        ``self.truncated`` is set when the file ends in the middle of a record."""
        from mcap.records import Channel, Message as McapMessage, Metadata
        from mcap.stream_reader import StreamReader
        chans: dict[int, str] = {}
        self.truncated = False
        with open(self.path, "rb") as fh:
            try:
                for rec in StreamReader(fh, record_size_limit=1 << 28).records:
                    if isinstance(rec, Channel):
                        chans[rec.id] = rec.topic
                    elif isinstance(rec, Metadata):
                        if rec.name == "run":
                            try:
                                self.meta = json.loads(rec.metadata["json"]).get("meta", {})
                            except (KeyError, json.JSONDecodeError):
                                pass
                    elif isinstance(rec, McapMessage):
                        yield Message(chans.get(rec.channel_id, f"channel{rec.channel_id}"), rec.publish_time / 1e9, rec.log_time / 1e9, json.loads(rec.data))
            except (EOFError, ValueError, OSError, json.JSONDecodeError, struct_error):
                self.truncated = True
            except Exception as exc:        # noqa: BLE001  (mcap raises its own exception types for a cut-off record)
                if type(exc).__module__.startswith("mcap"):
                    self.truncated = True
                else:
                    raise


def open_bag(path: str) -> BagReader:
    return BagReader(path)


def read_all(path: str, topics=None) -> list[Message]:
    return list(BagReader(path).messages(topics))
