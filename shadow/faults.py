"""Fault injection and divergence signatures (research angle A8).

A "fault" is a difference between the machine that was recorded and the healthy twin it is compared with. Each fault here is injected
into a twin that stands in for the real PLC (``shadow.synth``); the healthy twin then shadows the recording (``shadow.engine``) and the
two reports are reduced to a short feature vector, the **signature**. A library of signatures from known faults lets a new recording
be classified (nearest centroid) and shows which faults the available signals can NOT tell apart.

Faults (``severity`` 0..1 scales the effect):
  none            healthy (the false-alarm reference)
  friction        extra Coulomb + viscous friction on both axes: arm still follows, motor current rises
  payload         heavier payload: the shoulder labours, motion slows
  slow_base       base axis profile speed reduced
  slow_shoulder   shoulder axis profile speed reduced
  timer           PLC timer base wrong (twin and real disagree on every timed step)
  latch           real PLC runs a ladder patch the twin does not (the e-stop magnet latch) and the e-stop is pressed
  link_outage     the poll link to the PLC drops for a few seconds (a recording fault, not a machine fault)
Standard library plus the repo's own modules.
"""
from __future__ import annotations

import copy
import json
import math
import os
from dataclasses import dataclass

from twin.config import TwinCfg, load_config
from twin.sim import Twin

from .engine import ShadowEngine, analyse, rec_time
from .synth import estop, record_session, standard_run

LIBRARY_PATH = os.path.join(os.path.dirname(__file__), "fault_library.json")
FEATURES = ["log_base_rms", "log_shoulder_rms", "log_current_bias", "n_timing", "timing_ms", "latch", "gap", "n_conf_bits"]


@dataclass
class Fault:
    name: str
    description: str


FAULTS = {
    "none": Fault("none", "healthy machine"),
    "friction": Fault("friction", "extra friction on both axes"),
    "payload": Fault("payload", "heavier payload"),
    "slow_base": Fault("slow_base", "base axis slower"),
    "slow_shoulder": Fault("slow_shoulder", "shoulder axis slower"),
    "timer": Fault("timer", "wrong PLC timer base"),
    "latch": Fault("latch", "ladder patch not known to the twin (e-stop magnet latch)"),
    "link_outage": Fault("link_outage", "poll link dropped for a few seconds"),
}


def build_case(fault: str, severity: float, base: TwinCfg | None = None):
    """(cfg of the faulted 'real' machine, extra script, record filter or None)."""
    base = base or load_config()
    c = copy.deepcopy(base)
    script: list = []
    keep = None
    s = max(0.0, min(1.0, severity))
    if fault == "friction":
        k = 20.0 + 25.0 * s                                        # x20 .. x45: the arm still tracks, the current does not
        for ax in (c.base, c.shoulder):
            ax.friction_c *= k
    elif fault == "payload":
        c.arm.payload = 5.0 + 3.0 * s                              # 5 -> 8 kg (the shoulder peak torque allows about 9 kg)
    elif fault == "slow_base":
        c.base.profile_rpm = base.base.profile_rpm * (1.0 - 0.5 * s)
    elif fault == "slow_shoulder":
        c.shoulder.profile_rpm = base.shoulder.profile_rpm * (1.0 - 0.5 * s)
    elif fault == "timer":
        c.timer_base_ms = base.timer_base_ms * (1.0 + s)
    elif fault == "latch":
        c.fix_estop_magnet_latch = True
        script = [(7.2, estop(True)), (9.5, estop(False))]
    elif fault == "link_outage":
        dur = 2.5 + 3.0 * s
        keep = lambda r: not (9.0 < r["t_mono"] - 1000.0 < 9.0 + dur)       # noqa: E731
    elif fault != "none":
        raise ValueError(f"unknown fault {fault!r}")
    return c, script, keep


def synthesize(fault: str, severity: float = 0.5, seconds: float = 20.0, hz: float = 25.0, base: TwinCfg | None = None) -> list[dict]:
    c, extra, keep = build_case(fault, severity, base)
    # every case presses the e-stop in the same place so that the latch fault is only one of several runs sharing the script
    script = standard_run(4.0) + extra
    recs = record_session(Twin(c), seconds, script, fast_hz=hz)
    return [r for r in recs if keep(r)] if keep else recs


def signature(recs: list[dict], base: TwinCfg | None = None, warmup_s: float = 3.0) -> dict:
    """Run the healthy twin against the recording in both modes and reduce the two reports to a feature vector (``FEATURES``)."""
    base = base or load_config()
    lad = analyse(ShadowEngine(base, warmup_s=warmup_s, resync=False).run_ladder(recs))
    opn = analyse(ShadowEngine(base, warmup_s=warmup_s).run_open(recs))
    conf = {e["signal"] for e in lad["events"] if e["detector"] == "conformance" and e["signal"] in lad["bits"]}
    timing = [e for e in lad["events"] if e["detector"] == "timing"]
    cur = opn["currents"].get("base_mA", {"bias": 0.0})
    a = opn["angles"]
    return {
        "log_base_rms": math.log10(1.0 + a["base_deg"]["rms"]),
        "log_shoulder_rms": math.log10(1.0 + a["shoulder_deg"]["rms"]),
        "log_current_bias": math.log10(1.0 + abs(cur["bias"])),
        "n_timing": float(len(timing)),
        "timing_ms": max([e["peak"] * 1000 for e in timing], default=0.0),
        "latch": 1.0 if conf & {"M30.6", "Q0.7"} else 0.0,
        "gap": 1.0 if (lad["gaps"] or opn["gaps"]) else 0.0,
        "n_conf_bits": float(len(conf)),
    }


# ---- classifier ---------------------------------------------------------------------------------------------------------------
def _scales(library: dict) -> dict:
    rows = [f for fs in library.values() for f in fs]
    sc = {}
    for k in FEATURES:
        v = [r[k] for r in rows]
        m = sum(v) / len(v)
        sd = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
        sc[k] = max(sd, 0.25 if k.startswith("log_") else 0.5)           # floors: avoid dividing by ~0 for features that barely vary
    return sc


def centroids(library: dict) -> dict:
    return {name: {k: sum(f[k] for f in fs) / len(fs) for k in FEATURES} for name, fs in library.items() if fs}


def classify(sig: dict, library: dict) -> tuple[str, dict]:
    """Nearest centroid in standardised feature space. Returns (name, {name: distance})."""
    sc, cen = _scales(library), centroids(library)
    d = {n: math.sqrt(sum(((sig[k] - c[k]) / sc[k]) ** 2 for k in FEATURES)) for n, c in cen.items()}
    return min(d, key=d.get), d


def build_library(severities=(0.3, 0.9), faults=None, seconds: float = 20.0, hz: float = 25.0, progress=None) -> dict:
    lib: dict[str, list] = {}
    for f in faults or FAULTS:
        for s in severities:
            if progress:
                progress(f, s)
            lib.setdefault(f, []).append(signature(synthesize(f, s, seconds, hz)))
    return lib


def confusion(library_train: dict, test: dict) -> tuple[dict, float]:
    """``test``: {fault: [signatures]}. Returns ({truth: {predicted: n}}, accuracy)."""
    table, ok, n = {}, 0, 0
    for truth, sigs in test.items():
        for s in sigs:
            pred, _ = classify(s, library_train)
            table.setdefault(truth, {}).setdefault(pred, 0)
            table[truth][pred] += 1
            ok += pred == truth
            n += 1
    return table, ok / n if n else 0.0


def load_library(path: str = LIBRARY_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)["signatures"]


def save_library(lib: dict, path: str = LIBRARY_PATH, meta: dict | None = None) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"features": FEATURES, "meta": meta or {}, "signatures": lib}, fh, indent=1)


# ---- what a per-motor current meter adds (research angle B2) ------------------------------------------------------------------
def power_study(fault: str, severity: float, seconds: float = 25.0, hz: float = 25.0, meter_window_s: float = 0.04, base: TwinCfg | None = None) -> dict:
    """Shadow one synthetic faulted recording in open mode WITH an external current meter. Returns the open-mode current residuals:
    ``base`` is what the PLC exposes (``%VW1022``), ``shoulder`` is only available with the meter. Compare healthy and faulted runs."""
    base = base or load_config()
    c, extra, keep = build_case(fault, severity, base)
    meter: list = []
    recs = record_session(Twin(c), seconds, standard_run(4.0) + extra, fast_hz=hz, sensors_hz=100.0, sensors=meter, meter_window_s=meter_window_s)
    if keep:
        recs = [r for r in recs if keep(r)]
    rep = analyse(ShadowEngine(base, warmup_s=3.0).run_open(recs, sensors=meter))
    cur = rep["currents"]
    return {k: {"bias": v["bias"], "rms": v["rms"], "real_rms": v["real_rms"]} for k, v in cur.items()}
