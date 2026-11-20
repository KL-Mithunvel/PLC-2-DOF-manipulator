"""Shadow engine: drive a second twin from RECORDED real PLC data and compare what it computes with what the real machine did.

Input: ``plc/raw`` records (live/raw.py) from a bag, i.e. the real PLC memory as polled (I, Q, M10..53, MD600, V1000.., V2000.., V2300..,
V2490..). Two modes:

``ladder``  (conformance, research angle A1): the second PLC runs the real ladder program, but its inputs come from the recording:
            the physical inputs (I0.0 e-stop, I0.1 reset), everything the HMI writes (buttons, jog, teach, speeds, cycle count, taught
            points) and the drive feedback (positions, status words, velocities, currents). Everything the ladder COMPUTES (outputs, step
            flags, drive commands, counters) is compared with the real values. A mismatch means the interpreter does not behave like the
            real PLC, the program differs, or timing differs.
``open``    (twin vs real arm, A3/A4): a full twin (PLC + drives + arm dynamics) is driven only by the operator inputs (e-stop, reset,
            HMI actions, speeds, taught points). Its arm motion and bits are compared with the real arm. A mismatch means the plant model
            or the calibration is off.

``resync`` (default True): after every poll the twin's polled cells are overwritten with the real values, so the test is "given the real
state at poll k-1 and the inputs during the interval, does the ladder produce the real state at poll k?". A missed one-scan event then
costs one poll and cannot cascade. ``resync=False`` lets the twin free-run from the start (any early mismatch then propagates).

Limits (be honest in any result):
* Polling is slower than the PLC scan, so comparison is state-by-state at the poll times, not scan-by-scan. Input changes are known
  only to within one poll interval; they are applied half-way through it (``input_phase``).
* Timers and counters inside the interpreter are not in the recorded memory: start recording with the machine idle (or accept the
  ``warmup_s`` at the start in which no comparison is made).
* %M30.2 is both an HMI button (STOP) and a ladder output (complete); in ladder mode it is tracked from the recording, not compared.
* The poll groups are not sampled at the same instant (see the per-block times in the raw records).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

from live.raw import apply_record
from twin.config import TwinCfg, load_config
from twin.il import Memory, parse_operand
from twin.plc import PLC
from twin.sim import HMI_BUTTONS, HMI_NUMERIC, HMI_SWITCH, Twin

INPUT_BITS = ["I0.0", "I0.1", "M20.1", "M20.2", "M20.3", "M20.4", "M20.5", "M22.0", "M22.1", "M22.2", "M22.3", "M22.4",
              "M30.0", "M30.2", "M30.4"]
INPUT_WORDS = ["VW1012", "MD600", "VD1018", "VW1022", "VW1042", "VD1044", "VD1048", "VD1052",          # drive feedback (TPDO)
               "VD2020", "VD2030", "VW2036"]                                                           # HMI numerics
# The taught points (VD2300+, VD2400+) are NOT per-scan inputs: they are PLC state that the ladder itself writes (teaching, and the
# %VW2400 overlap defect clobbers the low half of VD2400), so they only seed the shadow once.
# Analog drive feedback is interpolated linearly between two polls (the arm crosses a +-2000 count "reached" window in far less than one
# 100 ms poll interval; replaying it as a staircase would jump over the window and the ladder would never see the condition).
INTERP_WORDS = ("MD600", "VD1044", "VD1018", "VD1048", "VW1022")
COMPARE_BITS = (["Q0.7", "M30.1", "M30.6"] + [f"M31.{i}" for i in range(8)] + ["M32.0", "M32.1", "M32.2", "M33.0", "M33.6", "M34.3",
                "M40.0", "M50.0", "M50.1"])
COMPARE_WORDS = ["VW1000", "VD1002", "VD1006", "VD1014", "VW1024", "VD1028", "VD1032", "VD1036", "VW2500", "VW2510", "VW2400"]
OPEN_BITS = ["Q0.7", "M30.1", "M40.0", "M50.0", "M50.1"]


@dataclass
class Trace:
    name: str
    kind: str                         # bit | word | angle
    t: list = field(default_factory=list)
    real: list = field(default_factory=list)
    twin: list = field(default_factory=list)


@dataclass
class ShadowResult:
    mode: str
    traces: dict[str, Trace]
    t_start: float
    warmup_s: float
    n_records: int
    gaps: list = field(default_factory=list)       # (t_from, t_to) where the recording had a gap and the twin was re-seeded


def rec_time(rec: dict) -> float:
    """Best single time of a poll: the middle of its requests."""
    if not rec.get("blocks"):
        return rec["t_mono"]
    return (min(b["t0"] for b in rec["blocks"]) + max(b["t1"] for b in rec["blocks"])) / 2


def load_records(path: str) -> list[dict]:
    from bag import BagReader
    recs = [m.payload for m in BagReader(path).messages(["plc/raw"])]
    recs.sort(key=rec_time)
    return recs


def covered(rec: dict, name: str) -> bool:
    """True when this poll record refreshed the memory cell ``name`` (so its real value is fresh, not left over from an older poll)."""
    op = parse_operand(name if name.startswith("%") else "%" + name)
    size = 1 if op.kind == "bit" else op.size
    for b in rec["blocks"]:
        if b["area"] != op.area:
            continue
        length = b["n"] * 2 if b["kind"] == "word" else (b["n"] + 7) // 8
        if b["byte0"] <= op.addr and op.addr + size <= b["byte0"] + length:
            return True
    return False


def timeline(records: list[dict]):
    """Yields (t, real_memory, record) after each record once every poll group has been seen at least once. ``real_memory`` is ONE
    Memory object that is updated in place: copy what you need before advancing."""
    mem, seen = Memory(), set()
    groups = {r["group"] for r in records}
    for r in sorted(records, key=rec_time):
        apply_record(r, mem)
        seen.add(r["group"])
        if seen >= groups:
            yield rec_time(r), mem, r


def _copy_memory(src: Memory, dst: Memory) -> None:
    for k in dst.area:
        dst.area[k][:] = src.area[k]


class ShadowEngine:
    def __init__(self, cfg: TwinCfg | None = None, warmup_s: float = 3.0, input_phase: float = 0.5, gap_s: float = 2.0, resync: bool = True) -> None:
        self.cfg = cfg or load_config()
        self.warmup_s, self.input_phase, self.gap_s, self.resync = warmup_s, input_phase, gap_s, resync

    # ---- shared: rebuild the real memory poll by poll --------------------------------------------------------------
    def _timeline(self, records: list[dict]):
        return timeline(records)

    # ---- ladder conformance ------------------------------------------------------------------------------------------
    def run_ladder(self, records: list[dict]) -> ShadowResult:
        cfg = self.cfg
        plc = PLC(cfg)
        traces = {n: Trace(n, "bit") for n in COMPARE_BITS} | {n: Trace(n, "word") for n in COMPARE_WORDS}
        scan_s = cfg.scan_ms / 1000.0
        prev_t, t_start, n, gaps = None, None, 0, []
        prev_in = {}
        for t, real, rec in self._timeline(records):
            cur_in = {a: real.read(a) for a in INPUT_BITS + INPUT_WORDS}
            if prev_t is None or t - prev_t > self.gap_s:
                if prev_t is not None:
                    gaps.append((prev_t, t))
                _copy_memory(real, plc.mem)               # (re)seed the twin from the real state
                prev_t, prev_in = t, cur_in
                if t_start is None:
                    t_start = t
                continue
            dt = t - prev_t
            scans = max(1, round(dt / scan_s))
            first = int(scans * self.input_phase)
            for i in range(scans):
                src = prev_in if i < first else cur_in                      # discrete inputs: held, the change happens half-way
                for a, v in src.items():
                    if a in INTERP_WORDS:
                        v = round(prev_in[a] + (cur_in[a] - prev_in[a]) * (i + 1) / scans)   # analog feedback: linear between polls
                    plc.mem.write(a, v)
                plc.scan(cfg.scan_ms)
            for a in INPUT_BITS + INPUT_WORDS:            # leave the inputs at the new real values
                plc.mem.write(a, cur_in[a])
            for name, tr in traces.items():
                if not covered(rec, name):                     # compare only values this poll actually refreshed
                    continue
                tr.t.append(t)
                tr.real.append(real.read(name))
                tr.twin.append(plc.mem.read(name))
            if self.resync:                                  # one-step-ahead: start the next interval from what the real PLC had
                apply_record(rec, plc.mem)
            prev_t, prev_in, n = t, cur_in, n + 1
        return ShadowResult("ladder", traces, t_start or 0.0, self.warmup_s, n, gaps)

    # ---- open loop twin vs real arm --------------------------------------------------------------------------------
    def run_open(self, records: list[dict]) -> ShadowResult:
        """The twin is booted and driven by the operator inputs only. After ``warmup_s`` (the real machine is idle after power-up) its arm
        pose, taught points and speeds are set from the real machine once; from then on only operator inputs are applied."""
        cfg = self.cfg
        twin = Twin(cfg)
        traces = {"base_deg": Trace("base_deg", "angle"), "shoulder_deg": Trace("shoulder_deg", "angle"),
                  "base_mA": Trace("base_mA", "current")} | {b: Trace(b, "bit") for b in OPEN_BITS}
        tag_of_bit = {addr: tag for tag, addr in HMI_BUTTONS.items()}
        switch_of_bit = {addr: tag for tag, addr in HMI_SWITCH.items()}
        scan_s = cfg.scan_ms / 1000.0
        prev_t, t_first, n, gaps, t_cmp = None, None, 0, [], None
        deg = 180 / math.pi
        for t, real, rec in self._timeline(records):
            if prev_t is None:
                prev_t, t_first = t, t
                continue
            if t - prev_t > self.gap_s:
                gaps.append((prev_t, t))
            if t_cmp is None and t >= t_first + self.warmup_s:             # sync once, after the boot phase
                for a in [f"VD{2300 + 4 * i}" for i in range(5)] + [f"VD{2400 + 4 * i}" for i in range(5)] + ["VD2020", "VD2030", "VW2036"]:
                    twin.plc.mem.write(a, real.read(a))
                twin._update_pick_site(force=True)
                for ax, addr in ((twin.arm.base, "MD600"), (twin.arm.shoulder, "VD1044")):
                    ax.theta = ax.cfg.count_to_angle(real.read(addr))
                    ax.ref = ax.theta
                t_cmp = t
            # operator inputs from the real machine
            twin.estop = real.read("I0.0") == 0
            twin.reset_btn = bool(real.read("I0.1"))
            for addr, tag in tag_of_bit.items():
                twin.command({"type": "button", "tag": tag, "down": bool(real.read(addr))})
            for addr, tag in switch_of_bit.items():
                twin.command({"type": "switch", "tag": tag, "on": bool(real.read(addr))})
            if t_cmp is not None:
                for tag, addr in HMI_NUMERIC.items():
                    twin.plc.mem.write(addr, real.read(addr))
            for _ in range(max(1, round((t - prev_t) / scan_s))):
                twin.tick()
            prev_t = t
            if t_cmp is None:
                continue
            tr = traces
            tr["base_deg"].t.append(t); tr["base_deg"].real.append(cfg.base.count_to_angle(real.read("MD600")) * deg)
            tr["base_deg"].twin.append(math.degrees(twin.arm.base.theta))
            tr["shoulder_deg"].t.append(t); tr["shoulder_deg"].real.append(cfg.shoulder.count_to_angle(real.read("VD1044")) * deg)
            tr["shoulder_deg"].twin.append(math.degrees(twin.arm.shoulder.theta))
            tr["base_mA"].t.append(t); tr["base_mA"].real.append(real.read("VW1022")); tr["base_mA"].twin.append(twin.arm.base.current_ma)
            for b in OPEN_BITS:
                if covered(rec, b):
                    tr[b].t.append(t); tr[b].real.append(real.read(b)); tr[b].twin.append(twin.plc.mem.read(b))
            n += 1
        return ShadowResult("open", traces, t_cmp or 0.0, 0.5, n, gaps)


# ---- analysis ---------------------------------------------------------------------------------------------------------------
def analyse(res: ShadowResult, min_len: float = 0.25, angle_limit_deg: float = 3.0, angle_hold_s: float = 1.0,
            timing_tol_s: float = 0.15, use_cusum: bool = False) -> dict:
    """Turn traces into a report: per-signal mismatch spans, edge delays, residual statistics, a divergence event log.
    ``min_len``: a bit disagreement shorter than this (a couple of polls) is counted as timing, not as divergence.
    ``timing_tol_s``: a systematic edge delay (median over >= 2 edges) larger than this, and than 2.5 poll periods, raises a ``timing``
    alarm: the twin reaches the same states but earlier or later (wrong timer base, wrong speed, slow drive).
    ``use_cusum``: also run CUSUM on the angle residuals (off by default: motion transients are correlated and trigger it)."""
    from shadow import (Cusum, EventLog, Signal, Threshold, detect, edge_delays, estimate_lag, estimate_lag_edges, mismatch_intervals, mismatch_rate,
                        residual, rising_edges)
    from shadow.detect import Alarm
    log = EventLog(gap_s=1.0)
    out = {"mode": res.mode, "n_records": res.n_records, "warmup_s": res.warmup_s, "gaps": res.gaps, "bits": {}, "words": {}, "angles": {}, "currents": {}}
    t_cut = res.t_start + res.warmup_s
    for name, tr in res.traces.items():
        idx = [i for i, x in enumerate(tr.t) if x >= t_cut]
        if len(idx) < 5:
            continue
        t = [tr.t[i] for i in idx]
        real = [float(tr.real[i]) for i in idx]
        twin = [float(tr.twin[i]) for i in idx]
        if tr.kind in ("bit", "word"):
            kind = "binary" if tr.kind == "bit" else "analog"
            rs, ts = Signal(name, t, real, "binary"), Signal(name, t, twin, "binary")
            if tr.kind == "bit":
                resid = residual(rs, ts, 0.0, dt=min(0.05, (t[-1] - t[0]) / max(10, len(t))))
                spans = mismatch_intervals(resid, min_len=min_len)
                info = {"mismatch_rate": mismatch_rate(resid), "spans": spans, "real_edges": len(rising_edges(rs)), "twin_edges": len(rising_edges(ts))}
                try:
                    lag = estimate_lag_edges(rs, ts, max_lag=2.0)
                    d = edge_delays(rising_edges(rs), rising_edges(ts), 2.0)
                    info["edge_delay_s"] = {"median": lag.lag, "min": min(d), "max": max(d), "n": len(d)}
                    gaps_t = sorted(b - a for a, b in zip(t, t[1:]) if b > a)
                    poll_s = gaps_t[len(gaps_t) // 2] if gaps_t else 0.1
                    if len(d) >= 2 and abs(lag.lag) > max(timing_tol_s, 2.5 * poll_s):
                        e0 = rising_edges(rs)
                        log.add([Alarm("timing", name, e0[0], e0[-1], abs(lag.lag), "warn",
                                       f"twin {'earlier' if lag.lag < 0 else 'later'} than the real PLC by {abs(lag.lag) * 1000:.0f} ms (median of {len(d)} edges)")])
                except ValueError:
                    pass
                out["bits"][name] = info
                for a, b in spans:
                    log.add([Alarm("conformance", name, a, b, 1.0, "alarm", "bit differs from the real PLC")])
            else:
                same = sum(1 for a, b in zip(real, twin) if a == b) / len(real)
                out["words"][name] = {"exact_match_rate": same, "max_abs_diff": max(abs(a - b) for a, b in zip(real, twin))}
                if same < 0.98:
                    bad = [x for x, a, b in zip(t, real, twin) if a != b]
                    log.add([Alarm("conformance", name, bad[0], bad[-1], out["words"][name]["max_abs_diff"], "warn",
                                   f"value differs in {100 * (1 - same):.1f} % of the polls")])
        elif tr.kind == "current":                                         # motor current: residual statistics only (no alarm: it is evidence, not a verdict)
            rs, ts = Signal(name, t, real), Signal(name, t, twin)
            out["currents"][name] = residual(rs, ts, 0.0, dt=0.05).stats() | {"real_rms": (sum(x * x for x in real) / len(real)) ** 0.5}
        else:                                                              # angle
            rs, ts = Signal(name, t, real), Signal(name, t, twin)
            lag = 0.0
            try:                                                 # the open-loop twin runs on its own clock: remove the constant offset first
                lr = estimate_lag(rs, ts, max_lag=2.0, dt=0.05)
                if lr.score > 0.9:
                    lag = lr.lag
            except ValueError:
                pass
            resid = residual(rs, ts, lag, dt=0.05)
            st = resid.stats()
            out["angles"][name] = st
            dets = [Threshold(angle_limit_deg, angle_hold_s, "alarm")] + ([Cusum(baseline_s=5.0, min_sigma=1.0, h=15.0)] if use_cusum else [])
            log.add(detect(resid, *dets))
    out["events"] = log.events()
    out["first_divergence"] = (lambda a: None if a is None else {"signal": a.signal, "t": a.t_start - res.t_start})(log.first())
    out["summary"] = log.summary()
    return out


def format_report(rep: dict, verbose: bool = False) -> str:
    """Text report. Signals that never did anything and always agreed are left out unless ``verbose``."""
    lines = [f"shadow report ({rep['mode']}): {rep['n_records']} polls compared, first {rep['warmup_s']:g} s skipped"]
    if rep["gaps"]:
        lines.append(f"  recording gaps (twin re-seeded): {len(rep['gaps'])}")
    quiet = [k for k, v in rep["bits"].items() if not verbose and v["mismatch_rate"] == 0 and v["real_edges"] == 0 and v["twin_edges"] == 0]
    for k, v in rep["bits"].items():
        if k in quiet:
            continue
        extra = f", edge delay median {v['edge_delay_s']['median'] * 1000:.0f} ms" if "edge_delay_s" in v else ""
        lines.append(f"  bit  {k:7s} mismatch {100 * v['mismatch_rate']:5.1f} %  sustained spans {len(v['spans'])}  edges real/twin {v['real_edges']}/{v['twin_edges']}{extra}")
    if quiet:
        lines.append(f"  ({len(quiet)} bits never changed and always agreed: {', '.join(quiet[:6])}{' ...' if len(quiet) > 6 else ''})")
    for k, v in rep["words"].items():
        if not verbose and v["exact_match_rate"] == 1.0:
            continue
        lines.append(f"  word {k:7s} exact {100 * v['exact_match_rate']:5.1f} %  max diff {v['max_abs_diff']}")
    for k, v in rep["angles"].items():
        lines.append(f"  ang  {k:13s} bias {v['bias']:+.2f} deg  rms {v['rms']:.2f}  max {v['max_abs']:.2f} at {v['t_max']:.1f}  (twin later by {v['lag'] * 1000:.0f} ms)")
    for k, v in rep.get("currents", {}).items():
        lines.append(f"  cur  {k:13s} bias {v['bias']:+.0f}  rms {v['rms']:.0f}  (real rms {v['real_rms']:.0f})")
    fd = rep["first_divergence"]
    lines.append("first divergence: " + (f"{fd['signal']} at {fd['t']:.2f} s into the run" if fd else "none"))
    lines.append(rep["summary"])
    return "\n".join(lines)


def ui_payload(res: ShadowResult, rep: dict, max_points: int = 600) -> dict:
    """Everything the GUI's Shadow tab needs, small enough to send as JSON: the report, its text, and the traces (times relative to the
    start of the run) reduced to at most ``max_points`` samples per signal, always keeping the samples where a value changes."""
    traces = {}
    for name, tr in res.traces.items():
        if len(tr.t) < 2:
            continue
        if tr.kind in ("bit", "word") and all(a == b for a, b in zip(tr.real, tr.twin)) and len(set(tr.real)) <= 1:
            continue                                                         # nothing ever happened on this signal: not worth a row
        keep = set(range(0, len(tr.t), max(1, len(tr.t) // max_points)))
        for i in range(1, len(tr.t)):
            if tr.real[i] != tr.real[i - 1] or tr.twin[i] != tr.twin[i - 1]:
                keep.update((i - 1, i))
        idx = sorted(keep)
        traces[name] = {"kind": tr.kind, "t": [round(tr.t[i] - res.t_start, 3) for i in idx],
                        "real": [tr.real[i] for i in idx], "twin": [tr.twin[i] for i in idx]}
    spans = {k: [(round(a - res.t_start, 3), round(b - res.t_start, 3)) for a, b in v["spans"]] for k, v in rep["bits"].items() if v["spans"]}
    return {"mode": res.mode, "warmup_s": res.warmup_s, "duration_s": max((tr["t"][-1] for tr in traces.values()), default=0.0),
            "traces": traces, "spans": spans, "report": json.loads(json.dumps(rep, default=str)), "text": format_report(rep)}
