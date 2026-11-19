"""Start the PLC + HMI + arm digital twin.   python run_twin.py [--port 8765] [--no-browser] [--fresh]"""
import argparse

from twin.server import run

ap = argparse.ArgumentParser()
ap.add_argument("--host", default="127.0.0.1")
ap.add_argument("--port", type=int, default=8765)
ap.add_argument("--no-browser", action="store_true")
ap.add_argument("--fresh", action="store_true", help="ignore saved retentive data (taught points)")
a = ap.parse_args()
run(a.host, a.port, persist=not a.fresh, open_browser=not a.no_browser)
