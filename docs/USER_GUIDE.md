# User guide

## Start and stop
```
python run_twin.py                 opens http://127.0.0.1:8765 (Ctrl+C in the terminal stops it)
python run_twin.py --demo                   showcase mode: loops the 3-cycle program by itself, no hardware (click to take over)
python run_twin.py --no-browser    do not open a browser
python run_twin.py --fresh         ignore saved taught points / speeds, start from the defaults
python run_twin.py --modbus-serve 1502       also serve the twin over Modbus TCP (read-only)
python run_twin.py --plc 192.168.0.252       add the real PLC as a read-only live source
python run_twin.py --power sim                     simulated per-motor power meters driven by the twin (real: --power COM5@9600)
python run_twin.py --hmi-vnc 192.168.0.100           show the real HMI (view-only VNC); password via env HMI_VNC_PASSWORD
python run_twin.py --mocap 0 --mocap-calib mocap/camera.json      add camera tracking
python run_twin.py --sensors udp:9100        add motor current/voltage sensors
```
The simulated machine takes about 3 s after start before the CANopen master is online (the "CANopen" chip turns green).

## Header controls
Pause/Resume, Step (one PLC scan), speed (0.5x to 10x), payload slider (0-10 kg; 5 kg is the design load), "auto-feed part" (a new part appears at the pick point after each drop), "Add part", "Save taught data" (stores taught points, speeds and cycle target in `twin_state.json`), "Default points".

## Operator panel
| Control | Meaning |
|---|---|
| E-STOP | toggles the normally-closed contact on `%I0.0`; pressed = everything stops, drives disable |
| RESET | hold about half a second: `%I0.1`, starts the homing sequence (shoulder first, then base) |
| POWER | power-cycles the PLC (retentive data kept) |
| LEDs | live `%I0.0`, `%I0.1`, `%Q0.7` (magnet), `%M30.1` (auto running), `%M40.0` (homing), `%M50.0/50.1` (shoulder/base at home) |

## HMI (top left)
The dropdown above the screen switches between Auto, Manual, Setting and, for reference, the panel's Wi-Fi and Login system windows.
- **Auto:** set NUMBER OF CYCLE, press START (hold until the arm moves, see troubleshooting), STOP, RESET clears the cycle counters. The timer shows min:sec of the run; the HOME lamps show base and shoulder at home.
- **Manual:** hold FWD/REV (base) or UP/DOWN (shoulder) to jog, type the speed (rpm), switch the electromagnet.
- **Setting:** jog to a pose and press TEACH to store it as INITIALIZATION or POSITION 1-4. Pick = POSITION 2, drop = POSITION 4 (the picture in the top-left corner shows the path INI -> 1 -> 2 (pick) -> 1 -> 3 -> 4 (drop)). Values can also be typed into the boxes.

## Typical workflows
1. **Run the demo:** wait for CANopen OK, Auto screen, START. The arm picks the part at POSITION 2, carries it to POSITION 4, releases, repeats for the set number of cycles, then returns to INITIALIZATION.
2. **Next run:** after a completed run press the panel RESET (shoulder parks about 3 deg off home because of the `%VW2400` overlap, see PLC_FINDINGS.md) and RESET on the Auto screen (clears the counter, otherwise the next run ends immediately).
3. **Teach points:** Manual jog, Setting TEACH, "Save taught data".
4. **Try a heavier or lighter load:** payload slider; watch shoulder torque and the Structural tab.
5. **What-if on the machine settings:** Settings tab (timer base, profile speed, rigid-body mode, program patches).

## Tabs (bottom)
| Tab | Content |
|---|---|
| Ladder program (live) | The real program as a ladder diagram or IL listing with operand values; green = power flows, amber dot = instruction executed this scan. "follow auto sequence" scrolls to the active network. Navigation: one scroll area in both directions; drag to pan, Shift + wheel = sideways, Ctrl + wheel or the +/- buttons = zoom, **Fit width** shows a whole rung, **go to** jumps to a network, **Tall** / **Full screen** enlarge the view. |
| I/O & memory | Bits, registers, timers, counters of the simulated PLC |
| CANopen / PDO | Live PDO table: node, COB-ID, object, PLC address, value, hex |
| Scope | Last 25 s: angles (with reference), speed, torque (with gravity torque), motor current (simulated and measured), magnet |
| Settings | Change whitelisted parameters live; "Apply and save" writes `twin_config.json` |
| Structural load | Reaction moment, stress per body, minimum FOS, link-2 tip deflection against the Ansys reference lines (a scaled estimate, not live FEA) |
| Shadow | Pick a recording that has `plc/raw` (a real run, or a synthetic one from `python -m shadow synth`), choose ladder conformance or open loop, press **Run shadow**. The text panel is the report; the chart shows every signal that did something, real (green) against the twin (blue), with sustained mismatches as red bands; in open mode the arm angles are drawn (solid = real, dashed = twin). Details: [SHADOW.md](SHADOW.md). |
| Data sources | Pick the primary source (sim / replay), the ghost arm (second source drawn translucent cyan), record any source, replay logs (play, speed, seek), status of live sources |
| Model & findings | Short summary of what is simulated, findings and assumptions |

## 3D view
**Navigation:** left-drag orbit, right-drag pan, wheel zoom (towards the cursor), double-click or `R` = back to the default view. The bar over the view has **Iso / Top / Front / Side / Back** (keys 1-5, animated), **Follow tip** (`F`, keeps the arm tip centred), **Fit** (`0`, frames the whole arm), **Reset**, **Tall** and **Full screen**. Keys work while the pointer is over the 3D view. If the view ever feels stuck, press `R`.
Pink glow = magnet on, joint colour = load against the continuous rating, orange trail = tip path, markers = taught points (INI, 1, 2 PICK, 3, 4 DROP), dashed ring = 843 mm work envelope. If `twin/web/models/manifest.json` exists the CAD models replace the placeholder shapes.

## Recording, replay, comparison
Data sources tab: choose a source, Record (writes `logs/<time>.jsonl`), Stop. Load a log under Replay and choose it as the primary source, or as the ghost. Compare two logs (time alignment is automatic):
`python -m tools.compare_runs logs/a.jsonl logs/b.jsonl`

## Command-line tools
| Command | Purpose |
|---|---|
| `python run_tests.py` | all tests |
| `python -m tools.calibrate_cycle --real-time 29.5 --cycles 3 --write` | fit drive speed (or `--fit timer_base_ms`) to the real cycle time |
| `python -m tools.fit_motor_params logs/run.jsonl --write` | fit motor torque constants from a log containing sensor current |
| `python -m tools.import_cad ...` | CAD bodies -> 3D models + mass properties ([CAD_IMPORT.md](CAD_IMPORT.md)) |
| `python -m tools.make_tags --size-mm 60` | printable ArUco tags |
| `python -m mocap.calibrate --images "calib/*.jpg"` | camera calibration |
| `python -m mocap.placement --camera X Y Z` | check a camera position |
| `python -m tools.mocap_demo --video demo.mp4` | hardware-free mocap demo and accuracy check |
| `python -m live.scan --host 192.168.0.252 --know VD2020=300` | verify the Modbus addresses against the real PLC ([LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md)) |
| `python -m tools.sim_sensors` | fake sensor MCU for testing the sensor input |

URL options for scripted screenshots: `?snap` (one snapshot instead of streaming), `&tab=struct`, `&screen=WIFI`.

## Troubleshooting
| Symptom | Cause / fix |
|---|---|
| Arm does not move after START | START was released too early: the ladder enables the drives only while START is held for the enable delay (T2/T3), or CANopen is not online yet (first 3 s). Hold START about 1 s. |
| Run ends immediately | The cycle counter still holds the previous count: press RESET on the Auto screen. |
| Home lamp for the shoulder stays red after a run | `%VW2400` overlap bug: press the panel RESET to home the arm. |
| Magnet comes on after releasing the E-stop | Original program behaviour (`M30.6` latch); patch option in Settings. |
| "port in use" / page does not load | An old server is still running: stop it, or start with `--port 8766`. |
| 3D view empty | The browser needs WebGL; reload the page. |
| Live PLC "not connected" | Check ping, port 502, the address offsets (`live.scan`) and that the HMI is not the only allowed connection. |

## Bag files (recordings)
Full topic and payload reference: [BAG_FORMAT.md](BAG_FORMAT.md). **Session recording** (Data sources tab, or `--record NAME`) writes every source into ONE bag, including the raw PLC Modbus blocks, connection events, pipeline diagnostics and real-HMI pictures. The **Pipeline diagnostics** table in the same tab shows poll rate, latency, jitter, errors and data age per live source.
`python run_twin.py` records in the **bag** format by default (`--record-format jsonl` gives the old one-snapshot-per-line logs). Press Record in the Data sources tab; files go to `logs/`.
- A bag holds several **topics** with two timestamps per message (`t_mono`: monotonic clock, for ordering and latency; `t_wall`: unix time): `twin/state` (full snapshot), `plc/decoded`, `mocap/pose`, `sensors`, `events` (the twin's log lines), later `plc/raw`, `diag`, `hmi/frame`. The header stores run metadata: git commit and whether the tree was dirty, PLC program hash, Modbus map hash, library versions, host, time.
- Format: **MCAP** when the `mcap` package is installed (`pip install mcap`; opens in Foxglove Studio), otherwise `.bag.jsonl` (standard library only). Both read back the same.
- Replay: choose the file in the Data sources tab (bags and old `.jsonl` logs are listed together).
- Inspect: `python -m bag info logs/run_xxx.mcap` (topics, counts, duration, commit, notes). Convert an old log: `python -m bag convert logs/old.jsonl`.
- Analysis tools (`tools/compare_runs.py`, `tools/fit_motor_params.py`) accept bags and old logs.
- In code: `from bag import BagWriter, BagReader, collect_meta`; `BagWriter(path, collect_meta(notes="R3", payload_kg=5)).write("events", {...})`. Never put passwords in metadata.
