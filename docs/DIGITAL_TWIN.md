# Digital twin (PLC + HMI + arm, 5 kg payload)

Run: `.venv\Scripts\python.exe run_twin.py` (opens http://127.0.0.1:8765). Tests: `python -m unittest tests.test_twin`.
The 3D view (three.js 0.160, vendored in `twin/web/vendor`, scene in `arm3d.js`, glue in `view3d.js`) needs no network. Node smoke test: `node tests/test_arm3d.mjs`. `?snap` in the URL fetches one snapshot instead of streaming (for headless screenshots).
Standard library only; no install needed.

| Module | Role |
|---|---|
| `twin/il.py` | Interpreter for KincoBuilder IL; runs the real `twin/plc/MAIN_MAIN.ilp` every scan |
| `twin/plc.py` | K615S model: I/O, scan, CANopen PDO map (docs section 2.2), retentive data |
| `twin/drive.py` | CiA402 drive: enable/halt/run controlword, trapezoid profile, PID servo, brake |
| `twin/plant.py` | Arm kinematics, gravity/inertia, electromagnet and 5 kg part |
| `twin/sim.py` | Orchestrator + HMI widget-to-PLC-address map |
| `twin/server.py`, `twin/web/` | HTTP/SSE API and the UI (HMI, arm, live ladder, PDO, scope) |
| `twin/config.py` | All parameters, tagged [doc] / [calc] / [assumed] |

API for the future three.js view: `GET /api/stream` (SSE, ~25 Hz) carries joint angles, `geom` (shoulder, P, tip in metres, z up),
part pose, taught points and all PLC state; commands go to `POST /api/cmd`.

## Findings from running the real program
1. `%VW2400` aliases the low word of `%VD2400`: the C2 counter mirror corrupts the taught shoulder INIT point (shoulder parks ~3 deg off home after a run; RESET needed). `fix_vw2400_overlap=True` remaps it.
2. `M30.6` (auto magnet) is not cleared by E-stop: the magnet re-energises on release.
3. In auto mode no speed is written (only jog/home do); the drive's own profile velocity must be used.
4. Operating mode 6060 is never written.

## Assumptions to replace with real data
Counts = motor encoder counts (15-bit, 32768/rev) before the reducer; timer base 10 ms; `%SM0.3` = 1 s clock; shoulder height, drop link, rotor inertias,
friction, torque constants, accel/profile speed defaults; default taught points; HMI button behaviour (momentary vs maintained). Compare the simulated
cycle time with the real one to calibrate the timer base and speeds.

## Planned next stage (stated 2026-11-19): CAD model, real physics, load graphs
1. **Exact 3D model.** User will supply the CAD. Replace the primitives in `twin/web/arm3d.js` with per-body glTF/GLB meshes (base, joint, Link-1, Link-2+magnet, part), each with its origin on its joint axis so the existing yaw/pitch groups drive them unchanged.
2. **Real physics.** Replace the point-mass/rod formulas in `twin/plant.py` with rigid-body dynamics using CAD mass, centre of mass and inertia tensor per body (also replaces the assumed 2.0 / 1.5 kg masses), plus gear/backlash/compliance if data exists.
3. **Load graph like the Ansys study.** Live graph of what the structure is going through: joint reaction force/moment (from the rigid-body model), equivalent stress, factor of safety and deformation, over time, for comparison with the Ansys report (min FOS 4.63 at the joint, 0.085 mm max deflection, 8.81 MPa peak stress).
   - Approach: the structure is linear and lightly loaded (<9 MPa), so run FEA at unit loads/poses (Ansys exports, or an open solver) and scale by the live reaction loads, or interpolate a table over (shoulder angle, payload).
   - Optional: colour the 3D meshes by stress/FOS.
   - Limit: this reproduces the static/quasi-static Ansys result; it is not a live FEA solve.

Inputs needed: CAD (STEP, or per-body STL/OBJ/GLB) with units and axes; per-body mass properties from CAD with material assignments; Ansys result exports if available (stress/deformation per pose, joint reaction probes).

## Planned: live data sources (stated 2026-11-19)
Target: digital twin + mocap + live PLC feed + **separate current and voltage sensors on each motor**, all on one data bus (same snapshot shape as `/api/stream`).
- Live PLC: Modbus TCP (pymodbus) to 192.168.0.252:502, read-only; Kinco coil/register mapping to be verified (see KincoBuilder manual).
- Motor sensors: independent measurement of each motor's supply current/voltage. Use to calibrate the twin's assumed `kt`, gear efficiency and friction (`twin/config.py`), to compare against drive-reported current (6078, currently mapped for node 1 only: `%VW1022`), and to compute electrical power vs the mechanical load from the twin.
- Notes: the drives are PWM-fed from the 24 V rail, so measure DC supply current per motor (shunt + fast ADC, e.g. INA226/INA228 or a Hall sensor) and log at kHz-level on a small MCU (ESP32/Arduino/RPi), forwarded to the PC over serial/UDP/MQTT with timestamps. The PLC scan (~ms) is too slow for this. Motors are rated 36 V but fed 24 V (paper section 5.3): the voltage sensor will also settle that open question.
