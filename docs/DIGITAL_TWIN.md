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
