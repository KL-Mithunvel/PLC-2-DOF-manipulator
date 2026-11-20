"""Recording check: ``python -m bag check FILE`` says whether a bag is good enough for the shadow tools, and what is wrong if not.

Each check yields a finding ``(level, topic, text)`` with level OK / WARN / FAIL. Exit code 0 = no FAIL. Meant to be run right
after a hardware session, before the machine is switched off, so a bad recording can be redone.
"""
from __future__ import annotations

import os
import statistics

from .core import BagReader

# addresses the shadow ladder mode needs from the fast group (area, first byte, byte count)
NEEDED = [("I", 0, 1), ("Q", 0, 1), ("M", 10, 44), ("M", 600, 4), ("V", 1000, 64)]


def _pct(v: list[float], q: float) -> float:
    v = sorted(v)
    return v[min(len(v) - 1, int(q * len(v)))]


def _covers(recs: list[dict], area: str, byte0: int, nbytes: int) -> bool:
    spans = []
    for b in recs[0]["blocks"]:
        if b["area"] == area:
            ln = b["n"] * 2 if b["kind"] == "word" else (b["n"] + 7) // 8
            spans.append((b["byte0"], b["byte0"] + ln))
    need = set(range(byte0, byte0 + nbytes))
    for lo, hi in spans:
        need -= set(range(lo, hi))
    return not need


def check(path: str, target_hz: float | None = None) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    add = lambda lvl, topic, text: out.append((lvl, topic, text))      # noqa: E731
    try:
        r = BagReader(path)
    except Exception as exc:                                            # noqa: BLE001
        return [("FAIL", "file", f"cannot read: {exc}")]
    msgs = list(r.messages())
    if not msgs:
        return [("FAIL", "file", "no messages")]
    add("OK", "file", f"{r.fmt}, {len(msgs)} messages, {r.duration:.1f} s")
    if r.truncated:
        add("WARN", "file", "not closed cleanly (crash or kill): everything before the cut is used")
    if r.duration < 30:
        add("WARN", "file", f"only {r.duration:.0f} s long; a shadow run needs the 3 s warm-up plus at least one full cycle")

    # ---- metadata
    g = r.meta.get("git", {})
    if not g.get("commit"):
        add("WARN", "meta", "no git commit recorded: the run cannot be tied to a code version")
    elif g.get("dirty"):
        add("WARN", "meta", f"code was uncommitted (dirty) at {g['commit'][:8]}: commit before the session next time")
    if not r.meta.get("plc_program_sha"):
        add("WARN", "meta", "PLC program hash missing: cannot show which program the machine ran")
    if not r.meta.get("notes"):
        add("WARN", "meta", "no notes (payload, operator actions, what was done): add --notes")

    # ---- clocks
    mono_back = 0
    last: dict[str, float] = {}
    for m in msgs:
        if m.topic in last and m.t_mono < last[m.topic] - 1e-6:
            mono_back += 1
        last[m.topic] = m.t_mono
    if mono_back:
        add("WARN", "clock", f"{mono_back} messages are out of time order within their topic")
    off = [m.t_wall - m.t_mono for m in msgs[:: max(1, len(msgs) // 200)]]
    if max(off) - min(off) > 0.05:
        add("WARN", "clock", f"wall minus monotonic clock varies by {(max(off) - min(off)) * 1000:.0f} ms (clock step during the run)")

    # ---- plc/raw
    raws = [m.payload for m in msgs if m.topic == "plc/raw"]
    if not raws:
        add("FAIL", "plc/raw", "no raw PLC records: the shadow tools cannot run (record with --plc)")
    else:
        groups = sorted({x["group"] for x in raws})
        add("OK", "plc/raw", f"{len(raws)} polls, groups {groups}")
        for grp in groups:
            rs = sorted((x for x in raws if x["group"] == grp), key=lambda x: x["t_mono"])
            ts = [x["t_mono"] for x in rs]
            if len(ts) < 3:
                add("WARN", f"plc/raw[{grp}]", f"only {len(ts)} polls")
                continue
            dts = [b - a for a, b in zip(ts, ts[1:])]
            hz = 1.0 / statistics.mean(dts)
            gaps = [d for d in dts if d > max(1.0, 5 * statistics.median(dts))]
            rtt = [(b["t1"] - b["t0"]) * 1000 for x in rs for b in x["blocks"]]
            lvl = "OK"
            note = f"{hz:.1f} Hz, period p95 {_pct(dts, .95) * 1000:.0f} ms max {max(dts) * 1000:.0f} ms, request p95 {_pct(rtt, .95):.0f} ms"
            if grp == "fast" and hz < 20:
                lvl, note = "WARN", note + " (below 20 Hz: ladder shadow cascades on missed one-scan events; use --plc-hz 25)"
            if target_hz and hz < 0.8 * target_hz:
                lvl, note = "WARN", note + f" (target {target_hz} Hz)"
            if gaps:
                lvl, note = "WARN", note + f"; {len(gaps)} gap(s) over 1 s, longest {max(gaps):.1f} s"
            add(lvl, f"plc/raw[{grp}]", note)
        fast = [x for x in raws if x["group"] == "fast"]
        if fast:
            for area, b0, n in NEEDED:
                if not _covers(fast, area, b0, n):
                    add("FAIL", "plc/raw", f"fast group does not cover {area}{b0}..{b0 + n - 1}: ladder shadow would compare stale data")
        # did anything happen
        try:
            from shadow.engine import timeline
            seen: dict[str, set] = {"MD600": set(), "VD1044": set(), "I0.0": set(), "I0.1": set(), "M20.1": set()}
            for _t, mem, _rec in timeline(raws):
                for k in seen:
                    seen[k].add(mem.read(k))
            moved = {k: len(v) for k, v in seen.items()}
            if moved["MD600"] <= 2 and moved["VD1044"] <= 2:
                add("WARN", "content", "neither arm position changed: the arm was idle, or the mapping is wrong (check %MD600 / %VD1044 against the HMI)")
            else:
                add("OK", "content", f"arm moved (base {moved['MD600']} and shoulder {moved['VD1044']} distinct counts)")
            if len(seen["M20.1"]) < 2:
                add("WARN", "content", "START button never changed: no operator action in this recording")
            if len(seen["I0.0"]) < 2:
                add("WARN", "content", "e-stop input never changed (the e-stop/reset test needs it to)")
        except Exception as exc:                                         # noqa: BLE001
            add("WARN", "content", f"could not rebuild PLC memory: {exc}")

    # ---- diag and events
    errs = last_err = None
    for m in msgs:
        if m.topic == "diag" and m.payload.get("source") == "plc":
            errs, last_err = m.payload.get("errors", errs), m.payload.get("last_error", last_err)
            rec_n = m.payload.get("reconnects")
    if errs:
        add("WARN", "diag", f"{errs} read errors, last: {last_err}")
    elif errs is not None:
        add("OK", "diag", "no read errors")
    ev = [m.payload for m in msgs if m.topic == "events"]
    if ev:
        add("OK", "events", f"{len(ev)} events (e.g. {ev[0].get('text')!r})")

    # ---- HMI frames
    fr = [m for m in msgs if m.topic == "hmi/frame"]
    if fr:
        base = os.path.dirname(os.path.abspath(path))
        missing = [m.payload["file"] for m in fr if m.payload.get("file") and not os.path.isfile(os.path.join(base, m.payload["file"]))]
        shas = len({m.payload.get("sha") for m in fr})
        if missing:
            add("FAIL", "hmi/frame", f"{len(missing)} frame files missing next to the bag (copy the *_hmi folder with it)")
        else:
            add("OK", "hmi/frame", f"{len(fr)} frames, {shas} distinct pictures")
        if shas == 1 and len(fr) > 3:
            add("WARN", "hmi/frame", "every frame is identical: the HMI screen never changed (or the VNC feed is frozen)")
        if raws:
            lo, hi = min(x["t_mono"] for x in raws), max(x["t_mono"] for x in raws)
            inside = sum(lo <= m.t_mono <= hi for m in fr)
            if inside < len(fr) * 0.9:
                add("WARN", "hmi/frame", "frames fall outside the PLC polling window")
    else:
        add("WARN", "hmi/frame", "no HMI frames (no VNC): the real HMI view cannot be compared")

    # ---- sensors
    se = [m for m in msgs if m.topic == "sensors"]
    if se:
        add("OK", "sensors", f"{len(se)} snapshots")
    else:
        add("WARN", "sensors", "no motor current/power data: payload and friction stay invisible (expected until meters exist)")
    return out


def report(path: str, target_hz: float | None = None) -> tuple[str, bool]:
    f = check(path, target_hz)
    lines = [f"check {path}"] + [f"  {lvl:4s} {topic:16s} {text}" for lvl, topic, text in f]
    ok = not any(lvl == "FAIL" for lvl, _, _ in f)
    n_w = sum(lvl == "WARN" for lvl, _, _ in f)
    lines.append(f"  => {'USABLE' if ok else 'NOT USABLE'}, {n_w} warning(s)")
    return "\n".join(lines), ok
