# Modular build plan: design each part alone, test it, then put it together

Written 2026-11-20. Covers the research goals in [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md) and the open items in [BUILD_PLAN.md](BUILD_PLAN.md) (that file stays the list of older phases; this one is the order of work from now on).

## Principles
1. **One module = one folder/file, one job, one written interface.** A module is finished when its interface is documented, it has unit tests that need **no hardware**, and it has run on synthetic or recorded data.
2. **Hardware is a plug-in, never a dependency.** `twin/` (the standalone twin) must never import `live/`, `mocap/` or any hardware library. Enforced by a test (stage 0).
3. **Everything talks through the snapshot schema** ([SCHEMA.md](SCHEMA.md)) and the bag log (stage 1). Modules exchange data, not objects.
4. **Read-only toward the PLC.** No module writes to the PLC.
5. **Integration is its own stage** and only starts when all modules it joins have passed their own stage gate.
6. Each stage ends with: tests green (`python run_tests.py`), docs updated, a commit. A stage that needs real hardware says so and has a fallback test on recorded or synthetic data.

## Module map
```
 standalone twin (twin/)  ---------------------------------------------+
   IL interpreter, drives, arm, HMI replica, web UI, demo mode          |
                                                                        v
 sources (plug-ins, each emits snapshots):                       +-------------+
   live/plc_reader   (Modbus)    -->                             |   Hub       |
   live/hmi_vnc      (picture)   -->  timestamps + diagnostics -->|  (bus)     |--> GUI
   live/sensors      (current)   -->                             |             |--> bag logger --> bag files
   mocap/            (camera)    -->                             +-------------+        |
                                                                        ^               v
 analysis (offline AND live, same code):                                |        replay source
   align -> residual -> detectors -> report  <--- real + twin snapshots-+
```

---

## Stage 0 - Standalone showcase twin (no hardware, ever)
**Status 2026-11-20: built** (0.1-0.5), tests green; the 10-minute unattended demo run has not been timed yet.
**Goal.** `python run_twin.py` (or `--demo`) runs the whole twin by itself and looks good to a visitor.
- **0.1 Isolation guard.** Test that importing `twin.server` and `twin.sim` pulls in nothing from `live`, `mocap`, `pymodbus`, `vncdotool`, `cv2`.
- **0.2 Demo mode.** `--demo` opens the UI with `?demo=1`: the page runs the 3-cycle program in a loop by itself (HMI RESET, panel RESET, START, wait for completion, repeat; this sequence was checked on the twin) and shows a small "demo" badge; any user click stops the loop.
- **0.3 3D view upgrade (done 2026-11-20).** Preset views (Iso/Top/Front/Side/Back), animated transitions, Follow tip, Fit, Reset (also double-click or `R`), zoom to cursor, right-drag pan, wider zoom limits, Tall and Full-screen buttons, keys 1-5. Reason: the old view had fixed limits, no way back to a lost view, and no pan feedback.
- **0.4 Ladder view upgrade (done 2026-11-20).** One scroll area in both directions with wide scroll bars, drag to pan, Shift+wheel sideways, Ctrl+wheel zoom, zoom buttons, Fit width, jump-to-network menu, Tall and Full-screen, sticky network titles.
- **0.5 Showcase polish.** One-page README section "Run the twin without hardware", screenshots, a 60-second recorded demo, pinned dependency list with the core needing no packages.
- **Gate.** Fresh clone, no extra packages, `python run_twin.py --demo` runs unattended for 10 minutes with no JavaScript error (headless-browser smoke test extended).

## Stage 1 - Data contract and bag log (module `bag/`)
**Status 2026-11-20: built** (writer/reader in both formats, metadata, recorder, replay, converter, CLI, tests). Not yet built: `plc/raw`, `diag` and `hmi/frame` producers (stage 2 and 3), scrub-by-bag-time in the GUI beyond the existing replay controls.
**Interface.** `BagWriter(path, meta)`, `.write(topic, t_mono, t_wall, payload)`, `BagReader(path)` iterating messages by time; a `ReplaySource` that plays a bag into the Hub at 1x/faster/scrub.
- Topics: `plc/raw`, `plc/decoded`, `twin/state`, `mocap/pose`, `sensors`, `events`, `diag`, `hmi/frame` (optional, low rate).
- Format: MCAP (opens in Foxglove). A JSON-lines fallback writer for machines without the library.
- Metadata per run: git commit, Modbus map, PLC program hash, payload, operator notes, software versions.
- **Tests (no hardware).** Round-trip write/read of every topic; time ordering; large-file streaming; replay timing accuracy; the existing recorder (`twin/sources.py`) output converts to a bag.
- **Gate.** A recorded 10-minute twin run replays identically (state hash equal) in the GUI.

## Stage 2 - Live PLC source with diagnostics (extends `live/plc_reader.py`)
**Status 2026-11-20: built and tested without hardware** (poll groups, diagnostics, raw blocks with send/receive times, events, reconnect, session bag, GUI panel, `--record`). Remaining: run it against the real PLC (H1), check the numbers there.
**Interface.** Source emits snapshots plus `diag`: poll period, round-trip latency, jitter, error and reconnect counts, data age, read-plan coverage.
- Timestamp each poll (monotonic + wall) before and after the request; mark torn or partial reads.
- Configurable poll plans (fast set for encoders, slow set for taught data) so rates can be measured per plan.
- **Tests (no hardware).** Against the twin's own Modbus server (`--modbus-serve`): correct mapping of I/Q/M/V incl. `%MD600` via coils, 32-bit word order, reconnect after server restart, error injection (delay, drop). 
- **Hardware step.** Tomorrow's session ([HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md)): verify M area offset, encoders, counters; record R1-R8.
- **Gate.** Mapping verified on the real PLC; diagnostics numbers recorded for the Modbus-fidelity study (B1).

## Stage 3 - Real HMI picture module (`live/hmi_vnc.py`, extended)
- Timestamp each frame; report frame age; handle refusal of a second client.
- Optional later: OCR of screen name, lamps and values (D1) behind a switch.
- **Tests.** A local fake VNC server (or a still-image source) for the frame path; OCR on saved screenshots (`docs/img/hmi/`) with expected values.
- **Gate.** Screen name and at least the cycle counters read correctly from saved real frames.

## Stage 4 - Alignment and residual engine (module `shadow/`, pure Python, no GUI)
**Status 2026-11-20: built and tested on synthetic data** (see [SHADOW.md](SHADOW.md)): lag recovered within 20 ms with drops/jitter/noise, drift in ppm, edge delays, CUSUM/threshold/RMS detectors with measured detection delay and no false alarm on clean white noise. Not yet measured on real residuals.
**Interface.** `align(stream_a, stream_b, method)` (resample to a common clock, estimate and remove constant lag); `residual(real, twin, signal)`; detectors: threshold, CUSUM, windowed RMS; an event log with severity.
- **Tests (synthetic).** Known lag recovered within tolerance; injected offsets and drifts detected with the expected delay and no false alarms on clean data; stable with dropped samples.
- **Gate.** Detection delay and false-alarm rate measured on synthetic data and written down.

## Stage 5 - Shadow engine (conformance, A1/A3/A5/A6)
**Status 2026-11-20: built and tested on synthetic recordings** (ladder conformance in two modes, open-loop arm comparison, timing and conformance alarms, CLI, seeded faults detected). Not yet run on a real recording; see [SHADOW.md](SHADOW.md) for results and limits.
**Interface.** Takes real input snapshots (I bits, HMI-written M/V, encoders), drives a second twin instance with them, outputs twin snapshots aligned with the real ones for stage 4.
- **Offline first.** Runs on a recorded bag (stage 1), so it can be developed and re-run without the arm.
- Signals compared: Q bits, M step flags, drive words, joint positions, tip, per-phase durations.
- **Tests.** Twin-vs-twin (same program, one with a changed parameter) gives the expected divergence; real-recorded bag from tomorrow gives the first real conformance numbers.
- **Gate.** Mismatch report for tomorrow's runs, each mismatch classified (interpreter, timing, real fault).

## Stage 6 - Fault injection and signatures (A8, A9)
**Status 2026-11-20: A8 built and tested on synthetic data** (7 faults + healthy, signature extractor, nearest-centroid classifier, stored library, measured accuracy 62-75 % leave-one-severity-out, see [FAULTS.md](FAULTS.md)). A9 (tamper detection / program-hash integrity check) is NOT built.
- A library of injectable faults in the twin (stuck limit switch, drive fault, lost comms, payload step, extra friction, slipped steps), each tagged and logged.
- Signature extractor: which residuals move, by how much, how soon.
- Integrity check: program hash and unexpected-behaviour alarm (A9), tested only on this machine.
- **Tests.** Every fault produces its expected signature; a simple classifier meets a stated accuracy on injected faults.
- **Gate.** Signature table plus confusion matrix.

## Stage 7 - Sensors (current/voltage) (`live/sensors.py` + firmware)
**Status 2026-11-20: host side built for PZEM-017 power meters and tested on simulated meters** (RTU master, driver, source, twin-driven simulation, calibration check; see [POWER_METER_PLAN.md](POWER_METER_PLAN.md)). Hardware (meters, shunts, ESP32 firmware) not yet bought, wired or tested.
- Firmware sketch exists (`firmware/motor_sensors/`). Define the message format, calibration (offset/gain), timestamps.
- **Tests.** `tools/sim_sensors` generator; calibration math; packet loss.
- **Hardware step.** Wire, calibrate against a meter; log current for known payloads (B2).
- **Gate.** Predicted vs measured current error reported.

## Stage 8 - Motion capture (`mocap/`)
- Already built and tested on synthetic images. Remaining: real camera calibration, mounting, accuracy check against known positions.
- **Gate.** Measured tip error in mm on the real arm (C1).

## Stage 9 - CAD and structural load (B4/B5)
- Needs the CAD file and Ansys exports ([CAD_IMPORT.md](CAD_IMPORT.md)). Import bodies, masses, inertias; live reaction moments; scaled stress/FOS; optional surrogate.
- **Tests.** Mass and inertia sums match the CAD report; static loads match hand calculation; compare with the Ansys cases.

## Stage 10 - Analysis and reporting (module `analysis/`, offline)
**Status 2026-11-20: built and tested on synthetic recordings** (cycle/step table, pick-to-pick period, link report, pick repeatability, CSV, CLI; see [ANALYSIS.md](ANALYSIS.md)). Plots are not built (CSV export instead).
- Notebook-free scripts: load bags, align, plot, tabulate (run summary, divergence table, latency histograms, repeatability), export figures and CSV for papers.
- **Tests.** Golden-file tests on a small saved bag.

---

## Integration stages (only after the module gates pass)
| Stage | Joins | Result | Test |
|---|---|---|---|
| I1 | 1 + 2 | **Record real runs** to bags with diagnostics | record, close, replay: same values; no loss of samples at 10 Hz for 30 min |
| I2 | I1 + 3 | Real HMI picture stored with the run, shown in replay | frame times lie inside the run |
| I3 | I1 + 4 + 5 | **Offline shadow:** replay a real bag through the shadow engine; divergence report | reproducible report from the same bag |
| I4 (offline part built 2026-11-20: Shadow tab on a recorded bag) | I3 + GUI | **Live shadow dashboard:** real vs twin, residual plots, event log, diagnostics panel | headless-browser test with replayed bag as the "live" source |
| I5 | I4 + 6 | Fault signatures matched live | injected fault in the twin is classified within the stated delay |
| I6 | I4 + 7 + 8 | Multi-source ground-truth view (encoder, camera, current) | error budget table per source |
| I7 | all | **Full system:** standalone mode untouched; each source switchable on/off; one command per mode | stage 0 gate still passes with all optional modules absent |

## Field-test gates (real hardware)
| Gate | When | What must be true afterwards |
|---|---|---|
| H1 | 2026-11-21 | Mapping verified (M area, encoders, counters); runs R1-R8 recorded; session log filled in |
| H2 | after sensors | Current logs for 3 known payloads |
| H3 | after camera | Tip error measured against known positions |
| H4 | before paper | Repeat runs (>= 5 per condition) for statistics |

## Order of work
Stage 0 (finish) -> 1 -> 2 (then **H1**) -> 4 -> 5 -> I1-I3 -> 3 -> I4 -> 6 -> 7 -> 8 -> 9 -> 10 -> I5-I7. Stage 1 comes before H1 if time allows: raw data from the first real session is the most valuable thing the project can have, so if the bag logger is not ready tomorrow, use the existing recorder and keep notes.

## Risks to watch
- Modbus polling is slower than a PLC scan: scan-level conformance (A1) may only be possible state-by-state.
- Only a few TCP connections to the PLC: HMI + twin + any extra tool may exceed it.
- Timestamp quality limits every comparison; measure it first (stage 2).
- Novelty is unchecked: do a literature search before committing to a paper topic.
