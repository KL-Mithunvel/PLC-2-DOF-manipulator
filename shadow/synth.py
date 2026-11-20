"""Synthetic ``plc/raw`` records from a running twin: a stand-in for the real PLC when no hardware is attached.

``poll_twin`` reads the twin's memory with exactly the block layout the live reader uses (live.plc_reader FAST/SLOW groups) and
returns raw records in the format of live/raw.py. ``record_session`` runs a twin under a script of operator actions and returns
(or writes to a bag) the records a 10 Hz / 1 Hz poll of that twin would have produced. Used by the tests, and handy for trying
the shadow tools before the first real recording.
"""
from __future__ import annotations

from live.plc_reader import make_groups
from live.raw import pack_bits
from twin.sim import Twin


def poll_twin(twin: Twin, group: str, spec: dict, t_mono: float, t_wall: float) -> dict:
    mem = twin.plc.mem
    rec = {"t_mono": t_mono, "t_wall": t_wall, "group": group, "blocks": []}
    for kind, area, byte0, nbytes in spec["blocks"]:
        if kind == "word":
            n = nbytes // 2
            data = [mem.get(area, 2, byte0 + 2 * i, signed=False) for i in range(n)]
        else:
            n = nbytes * 8
            data = pack_bits([mem.get_bit(area, byte0 + i // 8, i % 8) for i in range(n)])
        rec["blocks"].append({"kind": kind, "area": area, "byte0": byte0, "addr": 0, "n": n,
                              "t0": t_mono, "t1": t_mono + 0.002, "data": data})
    return rec


def record_session(twin: Twin, seconds: float, script=None, fast_hz: float = 10.0, slow_hz: float = 1.0,
                   t_mono0: float = 1000.0, wall0: float = 1.7e9) -> list[dict]:
    """Run ``twin`` for ``seconds`` of simulated time. ``script`` = list of ``(t_seconds, fn(twin))`` operator actions.
    Returns the raw records a poll would have produced, in time order."""
    script = sorted(script or [], key=lambda x: x[0])
    groups = make_groups(fast_hz, slow_hz)
    due = {g: 0.0 for g in groups}
    out: list[dict] = []
    dt = twin.cfg.scan_ms / 1000.0
    t = 0.0
    si = 0
    while t < seconds:
        while si < len(script) and script[si][0] <= t:
            script[si][1](twin)
            si += 1
        twin.tick()
        t += dt
        for g, spec in groups.items():
            if t >= due[g]:
                out.append(poll_twin(twin, g, spec, t_mono0 + t, wall0 + t))
                due[g] += 1.0 / spec["hz"]
    return out


def write_bag(records: list[dict], path: str, meta: dict | None = None, fmt: str = "auto") -> str:
    from bag import BagWriter, collect_meta
    with BagWriter(path, collect_meta(synthetic=True, **(meta or {})), fmt=fmt) as w:
        for r in records:
            w.write("plc/raw", r, r["t_mono"], r["t_wall"])
        return w.path


# handy operator actions ----------------------------------------------------------------------------------------------
def press(tag: str, seconds: float = 0.3):
    """Action: hold an HMI button for a while (the twin's tick loop is stepped by the caller, so this only sets the button;
    pair it with ``release``)."""
    return lambda tw: tw.command({"type": "button", "tag": tag, "down": True})


def release(tag: str):
    return lambda tw: tw.command({"type": "button", "tag": tag, "down": False})


def estop(on: bool):
    return lambda tw: tw.command({"type": "estop", "pressed": on})


def standard_run(start_at: float = 4.0) -> list:
    """Power up, wait for CANopen, press and release START."""
    return [(start_at, press("START")), (start_at + 0.5, release("START"))]
