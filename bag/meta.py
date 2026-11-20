"""Run metadata stored in every bag: enough to reproduce or interpret a run later."""
from __future__ import annotations

import hashlib
import os
import platform
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRAM = os.path.join(ROOT, "twin", "plc", "MAIN_MAIN.ilp")
MODBUS_MAP = os.path.join(ROOT, "live", "modbus_map.json")


def _sha(path: str) -> str | None:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()[:16]
    except OSError:
        return None


def _git() -> dict:
    out = {}
    for key, args in (("commit", ["rev-parse", "--short", "HEAD"]), ("dirty", ["status", "--porcelain", "--untracked-files=no"])):
        try:
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, timeout=5)
            out[key] = r.stdout.strip() if key == "commit" else bool(r.stdout.strip())
        except Exception:      # noqa: BLE001  (no git, not a repo)
            out[key] = None
    return out


def _version(mod: str) -> str | None:
    try:
        import importlib.metadata as md
        return md.version(mod)
    except Exception:           # noqa: BLE001
        return None


def collect_meta(**extra) -> dict:
    """Standard metadata plus any keyword arguments (``payload_kg=5``, ``notes="run R3"``, ``operator=...``).

    Never put passwords or network credentials here.
    """
    meta = {
        "created_wall": time.time(), "created_iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "host": platform.node(), "python": sys.version.split()[0], "platform": platform.platform(),
        "git": _git(), "plc_program_sha": _sha(PROGRAM), "modbus_map_sha": _sha(MODBUS_MAP),
        "versions": {m: _version(m) for m in ("pymodbus", "mcap", "vncdotool", "numpy")},
    }
    meta.update(extra)
    return meta
