"""Run analysis from a bag that contains ``plc/raw`` (real PLC) or ``twin/state`` (the twin).

What it computes, and what each number is good for:
* ``cycle_table``       per auto cycle: the time of every sequence step (M31.0 .. M32.0) and the step durations. Cycle-to-cycle spread
                        and trend are the wear indicator (research angle A6); the durations are what to compare with the twin.
* ``link_report``       round trip, poll period and jitter measured straight from the raw request times (an independent check of the
                        ``diag`` topic): the data for the Modbus fidelity study (B1).
* ``pick_repeatability`` where the arm was when each pick step was reached (taught-point miss and its spread, angle and tip mm; C2).
* ``export_csv``        any signals to CSV for spreadsheets and papers.
Standard library only (the bag module and shadow.engine.timeline are used to read the recording).
"""
from __future__ import annotations

import csv
import math
import statistics

from bag import BagReader
from shadow.engine import rec_time, timeline
from shadow.signals import get_path
from twin.config import load_config

# the auto sequence as the ladder runs it (docs/PLC_Program_and_Communication.md): M31.0 INIT reached ... M32.0
STEP_BITS = ["M31.0", "M31.1", "M31.2", "M31.3", "M31.4", "M31.5", "M31.6", "M31.7", "M32.0"]
STEP_NAMES = ["INIT reached", "POS1 reached", "POS2 (pick) reached", "pick delay done", "lifted to POS1", "POS3 reached",
              "POS4 (drop) reached", "drop delay done", "back at POS3"]


def _records(path: str) -> list[dict]:
    return [m.payload for m in BagReader(path).messages(["plc/raw"])]


def _bit_edges(records: list[dict], addr: str):
    """(rise times, fall times) of a bit in the reconstructed real memory."""
    rises, falls, prev = [], [], None
    for t, mem, _rec in timeline(records):
        v = mem.read(addr)
        if prev is not None and v != prev:
            (rises if v else falls).append(t)
        prev = v
    return rises, falls


def cycle_table(records: list[dict]) -> list[dict]:
    """One row per auto run segment: for each step flag the time of its first rising edge after the run started (M30.1 rising)."""
    runs, rows = [], []
    starts, stops = _bit_edges(records, "M30.1")
    edges = {b: _bit_edges(records, b)[0] for b in STEP_BITS}
    if not starts:
        return []
    ends = stops + [math.inf]
    for t0 in starts:
        t1 = next((e for e in ends if e > t0), math.inf)
        row = {"run_start": t0, "run_end": None if t1 == math.inf else t1, "steps": {}}
        for b in STEP_BITS:
            row["steps"][b] = [e for e in edges[b] if t0 <= e <= t1]
        runs.append(row)
    # the sequence repeats within a run (3 cycles): cycle k = k-th rising edge of every step flag
    for r in runs:
        n = max((len(v) for v in r["steps"].values()), default=0)
        for k in range(n):
            times = {b: (r["steps"][b][k] if k < len(r["steps"][b]) else None) for b in STEP_BITS}
            ts = [times[b] for b in STEP_BITS if times[b] is not None]
            dur = {}
            for a, b in zip(STEP_BITS, STEP_BITS[1:]):
                dur[b] = None if times[a] is None or times[b] is None else times[b] - times[a]
            rows.append({"run_start": r["run_start"], "cycle": k + 1, "times": times, "step_s": dur,
                         "cycle_s": (max(ts) - min(ts)) if len(ts) > 1 else None})
    return rows


def pick_periods(records: list[dict], step: str = "M31.2") -> dict:
    """Time between successive arrivals at the pick position: the cleanest cycle time (the first cycle includes the approach
    from home, so ``cycle_s`` of the first row is longer). Its spread over cycles and its trend over days is the wear indicator."""
    rises, _ = _bit_edges(records, step)
    per = [b - a for a, b in zip(rises, rises[1:])]
    if not per:
        return {"n": 0}
    return {"n": len(per), "periods_s": per, "mean": statistics.mean(per), "std": statistics.pstdev(per) if len(per) > 1 else 0.0,
            "min": min(per), "max": max(per)}


def link_report(records: list[dict]) -> dict:
    """Per poll group and per request kind: round trip (ms) and period / jitter (ms), from the raw times."""
    out = {"groups": {}, "blocks": {}}
    by_group: dict[str, list[float]] = {}
    rt: dict[str, list[float]] = {}
    for r in sorted(records, key=rec_time):
        by_group.setdefault(r["group"], []).append(r["t_mono"])
        for b in r["blocks"]:
            rt.setdefault(f"{b['kind']}:{b['area']}{b['byte0']}", []).append((b["t1"] - b["t0"]) * 1000)

    def stats(v):
        v = sorted(v)
        n = len(v)
        if not n:
            return {"n": 0}
        mean = sum(v) / n
        return {"n": n, "mean": mean, "p50": v[n // 2], "p95": v[min(n - 1, int(0.95 * n))], "max": v[-1],
                "std": math.sqrt(sum((x - mean) ** 2 for x in v) / n)}
    for g, ts in by_group.items():
        per = [(b - a) * 1000 for a, b in zip(ts, ts[1:])]
        out["groups"][g] = {"polls": len(ts), "period_ms": stats(per), "rate_hz": (1000 / statistics.mean(per)) if per else None,
                            "jitter_ms": stats(per).get("std"), "longest_gap_s": (max(per) / 1000) if per else None}
    out["blocks"] = {k: stats(v) for k, v in rt.items()}
    return out


def pick_repeatability(records: list[dict], step: str = "M31.2") -> dict:
    """Arm position (counts, degrees, tip mm) at the moment each pick step flag rises. Spread over cycles = repeatability."""
    cfg = load_config()
    pts, prev = [], None
    for t, mem, _rec in timeline(records):
        v = mem.read(step)
        if prev == 0 and v == 1:
            pts.append({"t": t, "base_count": mem.read("MD600"), "shoulder_count": mem.read("VD1044")})
        prev = v
    if not pts:
        return {"n": 0}
    deg = 180 / math.pi
    for p in pts:
        p["base_deg"] = cfg.base.count_to_angle(p["base_count"]) * deg
        p["shoulder_deg"] = cfg.shoulder.count_to_angle(p["shoulder_count"]) * deg
        from twin.sources import pose_snapshot
        p["tip"] = pose_snapshot("plc", cfg, p["base_deg"], p["shoulder_deg"])["geom"]["tip"]
    out = {"n": len(pts), "points": pts}
    if len(pts) >= 2:
        for k in ("base_deg", "shoulder_deg"):
            out[k + "_std"] = statistics.pstdev(p[k] for p in pts)
        out["tip_spread_mm"] = max(math.dist(a["tip"], b["tip"]) for a in pts for b in pts) * 1000
    return out


def summary(path: str) -> dict:
    r = BagReader(path)
    recs = _records(path)
    out = {"file": path, "duration_s": r.duration, "topics": r.topics, "meta": {k: r.meta.get(k) for k in ("created_iso", "notes", "payload_kg", "git", "plc_program_sha")},
           "truncated": r.truncated}
    if recs:
        cyc = cycle_table(recs)
        cs = [c["cycle_s"] for c in cyc if c["cycle_s"]]
        out["cycles"] = cyc
        out["cycle_s"] = {"n": len(cs), "mean": statistics.mean(cs), "std": statistics.pstdev(cs) if len(cs) > 1 else 0.0,
                          "min": min(cs), "max": max(cs)} if cs else {"n": 0}
        out["pick_period"] = pick_periods(recs)
        out["link"] = link_report(recs)
        out["pick"] = pick_repeatability(recs)
        ev = [m.payload for m in r.messages(["events"])]
        out["events"] = [e.get("text") for e in ev][:50]
    return out


def format_summary(s: dict) -> str:
    L = [f"{s['file']}: {s['duration_s']:.1f} s, topics {s['topics']}" + ("  [NOT CLOSED CLEANLY]" if s["truncated"] else "")]
    m = s["meta"]
    L.append(f"  created {m.get('created_iso')}, notes {m.get('notes')!r}, payload {m.get('payload_kg')}, commit {(m.get('git') or {}).get('commit')}, PLC program {m.get('plc_program_sha')}")
    if "cycles" in s:
        c = s["cycle_s"]
        L.append("  cycles: " + (f"{c['n']}  mean {c['mean']:.2f} s  std {c['std']:.2f}  range {c['min']:.2f}..{c['max']:.2f}" if c["n"] else "none found"))
        pp = s["pick_period"]
        if pp["n"]:
            L.append(f"  pick-to-pick period: {pp['n']}  mean {pp['mean']:.2f} s  std {pp['std']:.3f}  range {pp['min']:.2f}..{pp['max']:.2f}   (the cleanest cycle time)")
        for row in s["cycles"]:
            steps = "  ".join(f"{b[-4:]}:{(v if v is not None else float('nan')):.2f}" for b, v in row["step_s"].items())
            L.append(f"    cycle {row['cycle']}: {('%.2f' % row['cycle_s']) if row['cycle_s'] else '-'} s   step durations {steps}")
        for g, v in s["link"]["groups"].items():
            L.append(f"  link {g}: {v['polls']} polls, {v['rate_hz'] and round(v['rate_hz'], 1)} Hz, jitter {v['jitter_ms'] and round(v['jitter_ms'], 1)} ms, longest gap {v['longest_gap_s'] and round(v['longest_gap_s'], 2)} s")
        for k, v in s["link"]["blocks"].items():
            L.append(f"    request {k:14s} round trip mean {v['mean']:.1f} ms  p95 {v['p95']:.1f}  max {v['max']:.1f}")
        p = s["pick"]
        if p["n"]:
            L.append(f"  pick: {p['n']} picks" + (f", base std {p['base_deg_std']:.2f} deg, shoulder std {p['shoulder_deg_std']:.2f} deg, tip spread {p['tip_spread_mm']:.1f} mm" if p["n"] > 1 else ""))
    return "\n".join(L)


def export_csv(path: str, out_csv: str, paths: list[str], topic: str = "twin/state", clock: str = "t_mono") -> int:
    """Write one row per message of ``topic``: time columns plus the requested payload paths (e.g. ``base/deg``, ``bits/Q0.7``)."""
    n = 0
    with open(out_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["t_mono", "t_wall"] + paths)
        for m in BagReader(path).messages([topic]):
            w.writerow([f"{m.t_mono:.6f}", f"{m.t_wall:.6f}"] + [get_path(m.payload, p) for p in paths])
            n += 1
    return n
