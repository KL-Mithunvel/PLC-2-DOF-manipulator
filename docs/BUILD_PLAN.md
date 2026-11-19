# Build plan: everything not built yet

Written 2026-11-19 from the information available at that date. Details per area: `docs/DIGITAL_TWIN.md`, `docs/MOCAP_PLAN.md`, `docs/LIVE_DATA_PLAN.md`.

## What exists today (done)
Python IL interpreter running the real `MAIN_MAIN.ilp`; K615S model with CANopen PDO exchange; CiA402 drive models; arm dynamics with 5 kg payload (point-mass formulas); HMI (Auto, Manual, Setting); web UI with live ladder, I/O, PDO table, scope; three.js arm view with primitive shapes; tests; docs.

## Rules for every phase
- Keep **one snapshot schema** (versioned) for all sources: `sim`, `plc`, `mocap`, `sensors`. Every source stamps data with a timestamp and a `source` name.
- Anything assumed stays tagged `[assumed]` in `twin/config.py` until replaced by a measurement.
- Each phase ends with a test and a commit.

## Phase 0 - Foundation (can start now, no new inputs)
Everything later depends on these.
1. **Snapshot schema v1** written down (`docs/SCHEMA.md`) and a `twin/bus.py` that carries snapshots from any source to the UI (SSE) and to a recorder.
2. **Recorder / replay**: log snapshots to JSONL with timestamps; replay a log into the UI at 0.1x-10x. Needed for mocap comparison and for sensor calibration.
3. **Source selector in the UI**: sim | recorded | live PLC; show two sources side by side.
4. `requirements.txt`, a `run` section in the README, and a single command that runs all tests.

Done when: a sim run can be recorded, replayed, and shown next to a live sim in the 3D view.

## Phase 1 - Live PLC feed (can start now; real PLC needed only to finish)
Inputs still needed: PC on 192.168.0.x; Kinco Modbus address table.
1. `live/plc_reader.py` (pymodbus): config-driven address list by name (`VD1044`, `M30.1`), read-only, 10-20 Hz, reconnect handling, never writes.
2. `live/modbus_map.py`: Kinco address mapping in a config file, with a **calibration scan** that finds known values (e.g. `%VD2020`) if the table is not found.
3. **Twin as a Modbus TCP server** (same mapping, local port) so item 1 is fully tested offline, and a real HMI could be pointed at the twin.
4. **Shadow mode** in three.js: arm driven by real `MD600` / `VD1044` counts, simulated arm beside it, error overlay (deg and mm).
5. HMI tag addresses: confirm the assumed widget-to-address map (`HMI_BUTTONS` in `twin/sim.py`) by reading the live PLC while pressing real HMI buttons.

Done when: the reader against the twin server matches the twin memory exactly; against the real PLC, a value read matches the HMI display.

## Phase 2 - Calibrate the twin to the real machine (needs 3 measurements)
Inputs: real 3-cycle time; real taught counts (VD2300..2316, VD2400..2416); real jog speeds.
1. Fit timer base (10 ms assumed), `%SM0.3` period, drive profile speed (6081) and acceleration so the simulated cycle time matches.
2. Load real taught points as retentive defaults.
3. Compare real vs simulated position traces from the Phase 1 recorder (needs the live feed) and fit gains and friction.

Done when: simulated cycle time and joint traces agree with the real arm within a tolerance you set.

## Phase 3 - Motor current / voltage sensors
Inputs: sensor choice and MCU; mounting position.
1. Firmware (ESP32/Arduino): INA226/INA228 or Hall sensor per motor, kHz sampling, timestamps, framed serial/UDP protocol.
2. `live/sensors.py`: ingest, resample onto the bus, drop/late-packet handling.
3. Clock sync with the PC (shared sync pulse, e.g. the magnet output or an LED seen by sensors/camera).
4. Calibration fit: `kt`, gear efficiency, friction from measured current vs twin torque; compare with drive-reported current (6078; add shoulder current to the PDO map if the drive allows).
5. Electrical power vs mechanical power graph; settle the 24 V vs 36 V question.

Done when: measured motor current is shown next to simulated current for a full cycle with the fitted parameters.

## Phase 4 - CAD model and real physics (blocked on the CAD file)
Inputs: STEP or per-body meshes with units/axes; mass properties per body; material assignments; Ansys exports if available.
Prep that can be done now: make the model loader and physics parameter-driven so the CAD drops in.
1. **Asset pipeline** (script): STEP/STL -> per-body GLB, origins on joint axes, units to metres. Replace the primitives in `twin/web/arm3d.js`; keep the yaw/pitch groups.
2. **Rigid-body dynamics** in `twin/plant.py`: per-body mass, COM and inertia tensor (replaces the paper's assumed 2.0 / 1.5 kg masses and the point-mass formulas); include base-axis coupling and the payload as a separate body.
3. Gear backlash/compliance if data exists (harmonic drive backlash under 20 arcsec per the paper).
4. Regression: the new model must reproduce the old holding torque (about 31 N.m with 5 kg at horizontal) within a few percent when fed the same masses.

Done when: the 3D view shows the exact CAD and the dynamics use CAD mass properties, with the regression passing.

## Phase 5 - Structural load graph (like the Ansys study)
Depends on Phase 4 for exact loads; a first version can use the current analytic reaction loads.
1. Compute joint reaction force/moment over time from the rigid-body model (first version: analytic from the current model).
2. FEA scaling: obtain stress/deformation per unit load or per pose (Ansys exports, or an open solver such as CalculiX/FEniCS on the CAD), then scale by live reaction loads or interpolate over (shoulder angle, payload).
3. Live graph: reaction moment, equivalent stress, factor of safety, deformation vs time; reference lines from the report (min FOS 4.63 at the joint, 0.085 mm max deflection, 8.81 MPa peak stress).
4. Optional: colour the 3D meshes by stress/FOS.

State in the UI: quasi-static, linear; not a live FEA solve.
Done when: the graph reproduces the Ansys static results for Pose A and Pose B within a few percent.

## Phase 6 - Motion capture
Inputs: camera model (resolution, fps, shutter), target accuracy, lighting.
1. `mocap/calibrate.py`: chessboard calibration, world frame from the base tag.
2. `mocap/tracker.py`: AprilTag/ArUco detection (base, Link-1, part), joint angles and tip position per frame.
3. Sync (shared pulse, or PLC scan count vs frame timestamps) and publish onto the bus as source `mocap`.
4. Overlay the twin on the video; error plots per axis; run logs saved by the recorder.
5. Add a second camera only if depth error or occlusion requires it.

Done when: a recorded run shows tip-position error vs the twin and vs the encoder-derived pose, with a stated uncertainty.

## Phase 7 - Smaller gaps found along the way
- HMI Wi-Fi/network screen (window 11) and Login popup (window 9) are not replicated.
- Graphical ladder rendering (contacts/coils) instead of the IL listing; the original screenshots are in `docs/img/plc/`.
- Timing and model options exposed in the UI (timer base, `fix_vw2400_overlap`, accel/profile speed) instead of editing `config.py`.
- Automated browser test (headless Edge `?snap`) so UI regressions are caught.
- Decide what to do about the program findings (`%VW2400` overlap, `M30.6` not cleared by E-stop): document only, or propose a corrected ladder.

## Suggested order
0 -> 1 -> 2 -> (3 and 4 in parallel as inputs arrive) -> 5 -> 6 -> 7 (pick items as needed).
Phase 0 and the offline half of Phase 1 need nothing from you; Phases 4 and 6 are blocked on the CAD file and camera details; Phase 2 needs the real cycle time and taught counts.

## Inputs checklist (what unblocks what)
| Input | Unblocks |
|---|---|
| PC can reach 192.168.0.252; Kinco Modbus address table | Phase 1 finish |
| Real 3-cycle time; real taught counts | Phase 2 |
| Sensor part choice, MCU, mounting | Phase 3 |
| CAD (STEP/meshes), mass properties, Ansys exports | Phases 4, 5 |
| Camera model, accuracy target, lighting | Phase 6 |
