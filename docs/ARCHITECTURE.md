# Architecture of the digital twin

## Big picture
```
                     +-------------------- twin/ (Python, standard library only) --------------------+
 HMI (web) --button--> Twin.command --> PLC memory <--> IL machine (runs MAIN_MAIN.ilp every scan)    |
                                            |  ^                                                        |
                                  RPDO (controlword, target, speed)   TPDO (status, position, speed, current)
                                            v  |                                                        |
                                    Drive model x2 (CiA402, profile + servo)  <-- gravity/inertia --  Arm + part
                     +-----------------------------------------------------------------------------+
        snapshots (JSON, schema v1)        |
   Hub: sim | replay | plc | mocap | sensors  --> recorder / replay / ghost --> HTTP + SSE --> web UI (HMI, 3D, ladder, graphs)
```
Sources other than the simulation (live PLC, mocap, sensors) are optional plug-ins registered on the hub (`run_twin.py --plc/--mocap/--sensors`).

## One tick = one PLC scan (5 ms of simulated time) - `twin/sim.py: Twin.tick`
1. Operator inputs into the PLC: `%I0.0` = not E-stop (normally-closed contact), `%I0.1` = RESET button.
2. After the CANopen power-on delay (3 s) the master is online: drive feedback is written to PLC memory (TPDO map: `%MD600` base position, `%VD1044` shoulder position, speeds, statuswords, current).
3. `PLC.scan`: update `%SM0.3` (1 s clock), run the IL program once (`twin/il.py`), advance timers and counters.
4. Controlwords, target positions, speeds and accelerations are copied from PLC memory to the drives (RPDOs).
5. Five 1 ms physics steps: `Arm.step` -> per-axis `Axis.step` (profile generator, PID + feed-forward servo, torque limit, friction, brake when disabled), then the electromagnet / part logic.
6. Every 40 ms a scope sample is stored; edge events (auto running, magnet, homing...) go to the log.

## Modules
| File | Responsibility |
|---|---|
| `twin/il.py` | Parser and interpreter for KincoBuilder instruction-list. One boolean accumulator + parenthesis stack; LD/AND/OR/ST/S/R; MOVE/ADD/SUB gated by the accumulator; comparisons AND into it; TON/TOF/CTU; byte-addressed little-endian memory (so `%VW2400` aliases `%VD2400`). Unknown opcodes raise instead of being skipped. |
| `twin/plc.py` | K615S model: memory, scan, I/O, PDO map (`PDO_MAP`), retentive data (taught points, speeds, cycle count), program patches (`fix_vw2400_overlap`, `fix_estop_magnet_latch`). |
| `twin/drive.py` | One joint module: CiA402 subset (0x0F enable/hold, 0x2F run to absolute target, 0x10F halt), trapezoid profile, PID servo, saturation at rated peak torque, brake. Position unit = motor encoder counts, speed unit = motor rpm. |
| `twin/plant.py` | The arm: forward kinematics, loads (simple formulas or rigid-body), part pick/carry/release by the magnet, feeder. |
| `twin/bodies.py` | Rigid-body model from per-body mass/COM/inertia (CAD-ready): mass matrix, gravity, Coriolis, reaction forces. |
| `twin/loads.py` | Structural estimate: stress, deflection, factor of safety from reaction moments, scaled from the Ansys Pose A results. |
| `twin/config.py` | All parameters, each tagged `[doc]`, `[calc]` or `[assumed]`; `twin_config.json` overrides (`load_config`). |
| `twin/sim.py` | `Twin`: ties everything together, HMI widget -> PLC address map, commands, snapshot, live reconfiguration. |
| `twin/sources.py` | Recorder, replay source, `pose_snapshot` helper for pose-only sources. |
| `twin/server.py` | `Hub` (sources, recorders, replay) and the HTTP/SSE server. |
| `twin/modbus_server.py` | Exposes the twin's memory as a read-only Modbus TCP server using the real Kinco address map. |
| `twin/web/` | UI: `index.html`, `app.js` (HMI, panels, tabs, graphs), `arm3d.js` + `view3d.js` + `ghost3d.js` (three.js), `ladder.js` (ladder diagram), `vendor/` (three.js 0.160, OrbitControls, GLTFLoader). |
| `bag/` | `core.py` (BagWriter/BagReader, MCAP or `.bag.jsonl`), `meta.py` (run metadata), `recorder.py` (BagRecorder, drop-in for `twin.sources.Recorder`), `convert.py` (`python -m bag info/convert`). Stage 1 of [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md). |
| `live/` | `plc_reader.py` (read-only pymodbus client + source), `modbus_map.py`, `scan.py` (find offsets), `hmi_vnc.py` (view-only VNC picture of the real HMI, served at `/api/hmi.png`), `sensors.py` (UDP/serial sensor input). |
| `mocap/` | `geometry.py` (marker layout, transforms), `tracker.py`, `calibrate.py`, `placement.py`, `synth.py` (rendered test images), `source.py`. |
| `tools/` | `calibrate_cycle`, `fit_motor_params`, `import_cad` (+ `meshio`), `make_tags`, `compare_runs`, `mocap_demo`, `sim_sensors`. |

## HMI -> PLC address map (`twin/sim.py`)
Widget tags are from the KincoDTools screenshots; the addresses are inferred from the ladder and **not confirmed** (the `.whe` files are encrypted). Buttons are momentary (pressed = 1) unless noted.

| HMI widget | PLC address |
|---|---|
| Auto: START / STOP / RESET (counters) | `%M30.0` / `%M30.2` / `%M30.4` |
| Auto: number of cycles, actual cycle, time min:sec | `%VW2036`, `%VW2400` (C2), `%VW2500` (C3) : `%VW2510` (C4) |
| Manual/Setting: base FWD / REV | `%M20.1` / `%M20.2` |
| Manual/Setting: shoulder UP / DOWN | `%M20.3` / `%M20.4` |
| Manual: electromagnet switch (maintained) | `%M20.5` |
| Speed entries (base, shoulder) | `%VD2020`, `%VD2030` |
| Setting: TEACH buttons (INIT, POS1..4) | `%M22.0` .. `%M22.4` |
| Setting: taught base / shoulder values | `%VD2300 .. 2316` / `%VD2400 .. 2416` (step 4) |
| Auto: HOME lamps (base, shoulder) | `%M50.1`, `%M50.0` |
Physical inputs: `%I0.0` enable (E-stop chain), `%I0.1` reset/home. Output: `%Q0.7` electromagnet.

## HTTP API (`twin/server.py`)
`GET /api/state[?source=]`, `GET /api/stream?source=sim&ghost=plc` (SSE, 25 Hz), `GET /api/program`, `GET /api/watch`, `GET /api/scope`, `GET /api/sources`, `POST /api/cmd`. Commands: HMI (`button`, `switch`, `numeric`, `screen`), panel (`estop`, `reset_btn`, `power`), run control (`pause`, `step`, `speed`, `payload`, `feeder`, `spawn`), data (`save`, `defaults`, `record_start|stop`, `replay_load|play|speed|seek`, `src`), configuration (`config_get`, `config`). Snapshot format: [SCHEMA.md](SCHEMA.md).

## Configuration
`TwinCfg` -> `AxisCfg` (gear ratio, encoder, home count, limits, torque ratings, friction, profile speed) and `ArmCfg` (geometry, masses, rigid-body switch). Overrides in `twin_config.json` (written by `tools.calibrate_cycle` and the Settings tab), key form `base.profile_rpm`. Only whitelisted keys can be changed from the UI/HTTP (`Twin.CONFIG_KEYS`). `cad_mass_properties.json` in the repo root (made by `tools.import_cad`) switches the dynamics to the rigid-body model.

## Threads and locking
A run loop thread calls `Hub.step` every 2 ms (advances the twin by wall-clock x speed, offers snapshots to recorders). The HTTP server is threaded; all access to twin state goes through `twin.lock` (RLock). Live sources run their own threads and only expose `snapshot()`.

## Tests (`python run_tests.py`)
Python unit tests for the interpreter, full pick-and-place cycle, bus/recorder/HTTP, Modbus reader and address map, calibration, sensors, rigid-body physics, structural model, CAD import, mocap (synthetic images), program patches, live configuration, plus node tests (3D scene with CAD attach, ladder layout of all 39 real networks) and a headless-browser smoke test (skipped if no browser is found).

## Extending
- New data source: implement `snapshot()`, `status()`, `control()` and `hub.register(name, source)`.
- New IL opcode: add a branch in `ILMachine.scan`; add a test in `tests/test_twin.py`.
- New tunable parameter: add it to `twin/config.py` and, if the UI should change it, to `Twin.CONFIG_KEYS`.
