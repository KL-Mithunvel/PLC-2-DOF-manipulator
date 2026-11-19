# Importing the CAD (exact model + real physics)

Built 2026-11-19; tested with synthetic box bodies only. Run it when the CAD arrives.

## What to export from CAD
One **STL or OBJ per body**, all in the **home pose**: base yaw 0, shoulder pitch 0 (Link-1 pointing straight up), world axes with z up, x = the direction the arm swings towards at yaw 0, origin on the base axis at table level.

| name | frame | contains |
|---|---|---|
| `base` | yaw | fixed base housing + base motor (static in 3D, contributes base-axis inertia) |
| `joint` | yaw | shoulder motor, bearing housing, pin shaft (turns with the base) |
| `link1` | link | Arm-1, Arm-2, cross member, pin (pitches with the shoulder) |
| `link2` | drop | drop link + electromagnet (hangs vertical, turns with the base only) |
| `part` (optional) | - | the 5 kg part, for its shape |

Densities from the Ansys report: steel AISI 1010 7872 kg/m^3 (base, joint, part), aluminium 6061 2713 kg/m^3 (links). Units: pass `--scale 0.001` for millimetres.
Meshes must be closed solids (watertight) for the mass calculation. If the CAD is simplified/hollow, give the true mass with `--mass link1=2.31`.
STEP: convert to STL in your CAD tool (or with FreeCAD/cadquery), then import.

## Run
```
python -m tools.import_cad --scale 0.001 --payload-kg 5 ^
  --body base:yaw:cad\base.stl:7872   --body joint:yaw:cad\joint.stl:7872 ^
  --body link1:link:cad\link1.stl:2713 --body link2:drop:cad\link2.stl:2713 ^
  --part cad\part.stl:7872
```
It writes `twin/web/models/*.glb` + `manifest.json` (the 3D view loads them automatically and hides the primitive shapes) and `cad_mass_properties.json` in the repo root (mass, COM, inertia tensor per body; its presence switches the dynamics to the rigid-body model with CAD inertias; delete it to go back). It prints each body's mass: compare with the paper's assumed 2.0 + 1.5 kg.

Shoulder height and reach (`twin/config.py`, `ArmCfg`) must match the CAD: the link frame origin is the shoulder axis, the drop frame origin is point P (link end). Update them from the CAD first.

## What changes in the twin
- 3D view: exact meshes (same yaw/pitch/drop groups as the primitives).
- Dynamics (`twin/bodies.py`): per-body mass/COM/inertia replaces the point-mass formulas; base/shoulder coupling and Coriolis terms appear when the mass distribution is not symmetric. Regression test: with the paper's masses it reproduces the old model (30.9 N.m holding torque).
- Structural graph (`twin/loads.py`): reaction moments come from the CAD masses; stress/deflection/FOS are still scaled from the Ansys Pose A results. Replace `REF` there with per-pose FEA exports when available.

## Files
`tools/meshio.py` (STL/OBJ read, mass properties, GLB write), `tools/import_cad.py` (CLI), `twin/bodies.py`, `twin/web/arm3d.js` (`attachBodies`), `twin/web/view3d.js` (manifest loader), tests in `tests/test_cad_import.py` and `tests/test_arm3d.mjs`.
