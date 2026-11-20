import argparse
import json
import sys

from .runs import export_csv, format_summary, summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m analysis", description="Analyse a recorded bag")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("summary", help="cycle and step timing, link latency, pick repeatability")
    s.add_argument("bag")
    s.add_argument("--json", help="also write the full summary as JSON")
    c = sub.add_parser("csv", help="export signals of one topic to CSV")
    c.add_argument("bag")
    c.add_argument("out")
    c.add_argument("paths", nargs="+", help="payload paths such as base/deg bits/Q0.7")
    c.add_argument("--topic", default="twin/state")
    a = ap.parse_args(argv)
    if a.cmd == "summary":
        s = summary(a.bag)
        print(format_summary(s))
        if a.json:
            with open(a.json, "w", encoding="utf-8") as fh:
                json.dump(s, fh, indent=1, default=str)
        return 0
    print("wrote", export_csv(a.bag, a.out, a.paths, a.topic), "rows to", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
