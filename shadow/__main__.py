"""Command line for the shadow engine.

    python -m shadow report logs/R3.mcap [--mode ladder|open] [--no-resync] [--warmup 3] [--json out.json] [--events-bag out.mcap]
    python -m shadow synth out.mcap [--fault none|latch|timer|slow] [--seconds 40] [--hz 25]
    python -m shadow faults list | build | classify logs/R3.mcap

``report`` shadows a recording that contains ``plc/raw`` and prints what diverged and when. ``synth`` writes a synthetic "real" recording
from a twin, optionally with a seeded fault, so the tools can be tried without hardware.
"""
import argparse
import copy
import json
import sys

from twin.config import load_config

from .engine import ShadowEngine, analyse, format_report, load_records


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m shadow", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report", help="shadow a recording and print the divergence report")
    r.add_argument("bag")
    r.add_argument("--mode", choices=("ladder", "open"), default="ladder")
    r.add_argument("--no-resync", action="store_true", help="ladder mode: let the twin free-run (needs a fast poll, about 25 Hz)")
    r.add_argument("--warmup", type=float, default=3.0, help="seconds at the start that are not compared")
    r.add_argument("--min-len", type=float, default=0.25, help="bit disagreements shorter than this are timing, not divergence")
    r.add_argument("--json", help="write the full report as JSON")
    r.add_argument("--events-bag", help="write the divergence events to a new bag (topic 'events')")
    s = sub.add_parser("synth", help="write a synthetic real recording from a twin")
    s.add_argument("out")
    s.add_argument("--fault", choices=("none", "latch", "timer", "slow"), default="none",
                   help="latch = real PLC has the e-stop magnet-latch patch; timer = real timer base is 20 ms; slow = real base axis is slower")
    s.add_argument("--seconds", type=float, default=40.0)
    s.add_argument("--hz", type=float, default=25.0, help="fast poll rate")
    f = sub.add_parser("faults", help="fault signature library: list, build, or classify a recording")
    f.add_argument("action", choices=("list", "build", "classify"))
    f.add_argument("bag", nargs="?")
    f.add_argument("--severities", default="0.3,0.6,0.9")
    a = ap.parse_args(argv)

    if a.cmd == "faults":
        from . import faults as fl
        if a.action == "list":
            for n, ft in fl.FAULTS.items():
                print(f"  {n:14s} {ft.description}")
            return 0
        if a.action == "build":
            sev = tuple(float(x) for x in a.severities.split(","))
            lib = fl.build_library(sev, progress=lambda n, v: print("building", n, v, flush=True))
            fl.save_library(lib, meta={"severities": list(sev), "seconds": 20, "hz": 25, "note": "synthetic: a twin stands in for the real PLC"})
            print("saved", fl.LIBRARY_PATH)
            return 0
        if not a.bag:
            print("classify needs a recording")
            return 2
        recs = load_records(a.bag)
        sig = fl.signature(recs)
        name, d = fl.classify(sig, fl.load_library())
        print("signature:", {k: round(v, 2) for k, v in sig.items()})
        print("closest known case:", name)
        for n, v in sorted(d.items(), key=lambda x: x[1]):
            print(f"  {n:14s} distance {v:5.2f}")
        print("(the library is built from a twin standing in for the PLC: a large distance to every case means a new kind of difference)")
        return 0

    if a.cmd == "report":
        recs = load_records(a.bag)
        if not recs:
            print("no plc/raw records in", a.bag, "(record with --plc ... --record NAME)")
            return 2
        eng = ShadowEngine(warmup_s=a.warmup, resync=not a.no_resync)
        res = eng.run_ladder(recs) if a.mode == "ladder" else eng.run_open(recs)
        rep = analyse(res, min_len=a.min_len)
        print(format_report(rep))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(rep, fh, indent=1, default=str)
        if a.events_bag:
            from bag import BagWriter, collect_meta
            with BagWriter(a.events_bag, collect_meta(source_bag=a.bag, shadow_mode=a.mode)) as w:
                for ev in rep["events"]:
                    w.write("events", ev)
        return 0

    from twin.sim import Twin

    from .synth import estop, record_session, standard_run, write_bag
    cfg = load_config()
    script = standard_run(4.0)
    c = copy.deepcopy(cfg)
    if a.fault == "latch":
        c.fix_estop_magnet_latch = True
        script += [(7.2, estop(True)), (9.5, estop(False))]
    elif a.fault == "timer":
        c.timer_base_ms = 20.0
    elif a.fault == "slow":
        c.base.profile_rpm = cfg.base.profile_rpm * 0.6
    recs = record_session(Twin(c), a.seconds, script, fast_hz=a.hz)
    print("wrote", write_bag(recs, a.out, {"fault": a.fault}), f"({len(recs)} polls)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
