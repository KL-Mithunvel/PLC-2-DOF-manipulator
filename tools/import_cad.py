"""Import the arm's CAD bodies: GLB models for three.js + mass properties for the rigid-body physics.

Export each body from CAD as an STL (or OBJ) **in the home pose**: base yaw 0, shoulder pitch 0 (link vertical up),
world frame with z up, x = the direction the arm swings towards at yaw 0, origin on the base axis at table level.
Units are set with ``--scale`` (e.g. 0.001 for millimetres).

    python -m tools.import_cad \\
        --body base:yaw:cad/base.stl:7872  --body joint:yaw:cad/joint.stl:7872 \\
        --body link1:link:cad/link1.stl:2713  --body link2:drop:cad/link2.stl:2713 \\
        --part cad/part.stl:7872 --scale 0.001 --payload-kg 5

--body NAME:FRAME:FILE:DENSITY    FRAME = yaw | link | drop (see twin/bodies.py), DENSITY in kg/m^3
                                   (steel AISI 1010 7872, aluminium 6061 2713, per the Ansys report)
--mass NAME=KG                     override a body's mass (e.g. when the CAD mesh is hollow / simplified); the inertia is rescaled
Writes: twin/web/models/<name>.glb, twin/web/models/manifest.json, cad_mass_properties.json (auto-enables the rigid-body model).
Shoulder height and reach are taken from twin/config.py (ArmCfg); the link frame origin is the shoulder axis, the drop
frame origin is point P (link end), at yaw 0 / pitch 0.
"""
from __future__ import annotations

import argparse
import json
import os

from twin.config import ArmCfg

from .meshio import mass_properties, read_mesh, transform, write_glb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODELS = os.path.join(ROOT, "twin", "web", "models")
COLORS = {"base": (0.35, 0.40, 0.46, 1), "joint": (0.18, 0.43, 0.62, 1), "link1": (0.76, 0.80, 0.84, 1),
          "link2": (0.76, 0.80, 0.84, 1), "part": (0.54, 0.59, 0.64, 1)}


def frame_origin(frame: str, arm: ArmCfg) -> tuple[float, float, float]:
    if frame == "yaw":
        return (0.0, 0.0, 0.0)
    if frame == "link":
        return (0.0, 0.0, arm.shoulder_height)
    if frame == "drop":
        return (0.0, 0.0, arm.shoulder_height + arm.reach)
    raise SystemExit(f"unknown frame {frame!r} (yaw | link | drop)")


def body_record(name: str, frame: str, tris, density: float, arm: ArmCfg, mass_override: float | None = None) -> dict:
    mp = mass_properties(tris, density)
    o = frame_origin(frame, arm)
    com = [mp["com"][i] - o[i] for i in range(3)]               # at home pose the frame axes equal the world axes
    inertia = mp["inertia"]
    mass = mp["mass"]
    if mass_override:
        k = mass_override / mass
        inertia = [[v * k for v in row] for row in inertia]
        mass = mass_override
    return {"name": name, "frame": frame, "mass": mass, "com": com, "inertia": inertia}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--body", action="append", required=True, metavar="NAME:FRAME:FILE:DENSITY")
    ap.add_argument("--part", help="FILE:DENSITY of the 5 kg part (visual + payload mass if --payload-kg is not given)")
    ap.add_argument("--payload-kg", type=float, help="payload mass (default: from the part mesh, else 5)")
    ap.add_argument("--mass", action="append", default=[], metavar="NAME=KG")
    ap.add_argument("--scale", type=float, default=1.0, help="multiply mesh coordinates by this to get metres")
    ap.add_argument("--out-mass", default=os.path.join(ROOT, "cad_mass_properties.json"))
    ap.add_argument("--models-dir", default=MODELS)
    a = ap.parse_args(argv)
    arm = ArmCfg()
    overrides = {k: float(v) for k, v in (m.split("=") for m in a.mass)}
    MODELS_DIR = a.models_dir
    os.makedirs(MODELS_DIR, exist_ok=True)
    bodies, manifest = [], {"units": "m", "frame": "home pose, world axes, z up", "bodies": {}}
    for spec in a.body:
        name, frame, rest = spec.split(":", 2)             # the file path may contain "C:" so split the density off the end
        path, density = rest.rsplit(":", 1)
        tris = read_mesh(path, a.scale)
        rec = body_record(name, frame, tris, float(density), arm, overrides.get(name))
        bodies.append(rec)
        write_glb(os.path.join(MODELS_DIR, name + ".glb"), tris, COLORS.get(name, (0.7, 0.75, 0.8, 1)), name)
        manifest["bodies"][name] = {"file": name + ".glb", "frame": frame}
        print(f"{name:10s} frame={frame:5s} mass={rec['mass']:.3f} kg  com={[round(c, 4) for c in rec['com']]}")
    payload = a.payload_kg
    if a.part:
        path, density = a.part.rsplit(":", 1)
        tris = read_mesh(path, a.scale)
        pm = mass_properties(tris, float(density))
        payload = payload if payload is not None else pm["mass"]
        write_glb(os.path.join(MODELS_DIR, "part.glb"), tris, COLORS["part"], "part")
        manifest["bodies"]["part"] = {"file": "part.glb", "frame": "part", "center": pm["com"]}
        print(f"part       mesh mass={pm['mass']:.3f} kg (payload used: {payload:.3f} kg)")
    bodies.append({"name": "payload", "frame": "drop", "mass": payload if payload is not None else 5.0, "com": [0, 0, 0],
                   "inertia": [0, 0, 0], "active": False})
    with open(a.out_mass, "w") as fh:
        json.dump({"bodies": bodies, "note": "generated by tools/import_cad.py"}, fh, indent=1)
    with open(os.path.join(MODELS_DIR, "manifest.json"), "w") as fh:
        json.dump(manifest, fh, indent=1)
    print("wrote", a.out_mass, "and", MODELS_DIR)
    total = sum(b["mass"] for b in bodies if b["name"] != "payload")
    print(f"total structure mass {total:.2f} kg (the paper assumed 2.0 + 1.5 kg for the two links)")


if __name__ == "__main__":
    main()
