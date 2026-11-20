# Research angles

Written 2026-11-20. This is a list of what could be investigated with this arm, PLC and twin, not a list of results. **Nothing here has been run on the real arm yet.** Novelty has not been checked against the literature; do that before choosing a paper topic. A build alone is engineering; each angle below is only research once it has a measurable question, a baseline and a result.

## What exists today (the base for every angle)
| Piece | State |
|---|---|
| Twin that executes the real PLC program (`MAIN_MAIN.ilp`) with CiA402 drives, arm dynamics and HMI replica | built, tested against itself only |
| Read-only Modbus TCP feed from the real PLC (pymodbus) | working; V offset verified, M area and encoder words still to confirm ([LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md)) |
| View-only VNC picture of the real HMI in the GUI | working (2026-11-20) |
| Ghost arm (real encoders) beside the simulated arm, taught-point table | built |
| Recorder and replay of runs, `tools/compare_runs.py` | built, not used on real data |
| Camera motion capture (AprilTags) | built, tested on synthetic images only |
| Motor current/voltage sensors | planned, firmware sketch exists, not wired |
| CAD bodies, Ansys structural report (FOS, deformation) | CAD import built, real CAD file pending; Ansys PDF available |
| Published/draft paper | simulation-driven design of the arm (`docs/paper/`) |

## Common framework (needed by most angles)
- **Time alignment.** Every sample gets a monotonic and a wall-clock timestamp. Polling jitter makes residuals noisy; without alignment the "divergence" mostly measures latency.
- **Residual** per signal = real minus twin, with a threshold or statistical test, and an event log.
- **Bag-style log (planned, not built):** MCAP file with topics `plc/raw`, `plc/decoded`, `twin/state`, `mocap/pose`, `sensors`, `events`, `diag`; run metadata (git commit, Modbus map, PLC program hash, payload, notes); replay into the same GUI. The existing recorder/replay in `twin/sources.py` is the starting point.
- **Pipeline diagnostics (planned):** Modbus poll rate, latency, jitter, error count, data age per source, shown in the GUI.
- **Safety rule.** The twin only reads. The real e-stop stays a hardware/PLC action; the twin mirrors it. Fault-injection on the real arm only with the e-stop in reach and the arm unloaded.

---

## A. Shadow and diverge (twin runs beside the real machine; differences are the signal)

### A1. Ladder conformance and interpreter validation
- **Question.** Does the interpreter reproduce the real PLC scan by scan, given identical inputs?
- **Method.** Feed the twin the real inputs (I bits, HMI-written M/V values) from Modbus; compare Q and internal M/V bits each scan window.
- **Needs.** Live PLC feed; input snapshots recorded at least at the Modbus rate; scan-time estimate.
- **Metric.** Per-bit mismatch rate and time to first mismatch; classify each mismatch (interpreter bug, timing, real fault).
- **Value.** Validates the tool itself; a clean, citable result. Can start on recorded data.
- **Risk.** Modbus polling is slower than the PLC scan, so only state-level (not scan-level) comparison is possible unless values change slowly.

### A2. Real HMI vs simulated HMI, same commands
- **Question.** For identical operator actions (start, stop, jog, teach, reset, e-stop), do the real PLC and the twin reach the same states with the same timing?
- **Method.** Apply the same sequence to the real HMI and the twin HMI replica; compare PLC state and arm motion; the VNC picture shows what the operator sees.
- **Needs.** Real HMI via VNC (done), live PLC feed, scripted action list, a stopwatch or timestamps.
- **Metric.** State-sequence match, response latency per action, cycle-time difference.
- **Note.** Commands to the real machine are made by a person on the real HMI; the software never writes to the PLC.

### A3. Real arm vs twin arm trajectory
- **Question.** How far does the real arm deviate from the model's trajectory?
- **Method.** Ghost arm from `%MD600`/`%VD1044` vs simulated arm; per-joint target, actual and following error.
- **Metric.** RMS and max position/velocity error per phase; tip error in mm; cycle time.
- **Needs.** Calibrated counts-to-degrees ratios, real taught points, real 3-cycle time (calibration inputs listed in [BUILD_PLAN.md](BUILD_PLAN.md)).

### A4. Reset and e-stop behaviour
- **Question.** Does the twin reproduce stopping time, stopping distance, overshoot and the recovery after RESET?
- **Method.** E-stop and reset applied at the same program phase on the real machine and in the twin; compare the logged traces.
- **Needs.** The real e-stop wiring knowledge (docs/HARDWARE.md), repeated trials at several phases and speeds.
- **Metric.** Stop time, overshoot (degrees), state after reset, mismatch of safety-related bits.

### A5. CiA402 drive state shadow
- **Question.** Do control word, status word, error codes and the enable/disable sequence match?
- **Method.** Compare the mirrored PDO words (via PLC memory) with the twin's drive model.
- **Needs.** The PDO-mapped words exposed in PLC memory (see PLC_Program_and_Communication.md); a way to provoke a drive fault safely.

### A6. Timing and cycle-time shadow
- **Question.** Is there a drift between real and twin timer behaviour or per-phase cycle time, and does it grow with use?
- **Method.** Phase durations per cycle on both; trend over many cycles.
- **Metric.** Phase-time residual vs cycle number. Drift is a candidate wear indicator.

### A7. Program-change regression and virtual commissioning
- **Question.** Can a ladder change be validated on recorded real input traces before it touches hardware?
- **Method.** Replay a recorded input trace into the old and new program in the twin; diff outputs and arm behaviour.
- **Needs.** Bag logger/replay; the edited `.ilp`. The defect list in [PLC_FINDINGS.md](PLC_FINDINGS.md) (for example the `%VW2400`/`%VD2400` overlap) gives real test cases.

### A8. Fault injection and divergence signature library
- **Question.** Does each fault leave a distinguishable divergence pattern?
- **Method.** Inject faults in the twin (stuck limit switch, drive fault, lost comms, payload step, extra friction, slipped steps); record the residual signatures; reproduce the safe ones on the real arm; train or hand-build a classifier.
- **Metric.** Detection delay, false-alarm rate, classification accuracy.

### A9. Tamper and integrity detection (defensive PLC security)
- **Question.** Can unexpected register writes, a changed program or a spoofed value be detected as divergence from the twin?
- **Method.** The twin runs the known-good program and the known command sequence; any real-side behaviour the twin cannot explain raises an alarm. Compare with the program hash.
- **Note.** Do this only on this lab machine, with test writes made by you through the normal HMI/engineering tool; the twin never writes. Check related work on PLC intrusion detection.

### A10. Communication staleness and state estimation
- **Question.** How much twin fidelity is lost with late or dropped Modbus data, and does a predictor/observer (for example a Kalman filter) recover it?
- **Method.** Inject delay and loss into the recorded feed; compare ghost accuracy with and without the estimator.

---

## B. Measurement and modelling studies

### B1. Modbus as a twin data link on a low-end PLC
- **Question.** How much can be observed, and at what rate and accuracy, through Modbus TCP on a Kinco K6 PLC? (M area bit-only, 100 registers or 1600 bits per request, a few TCP connections, the HMI already holds one.)
- **Method.** Measure round-trip latency, jitter, maximum sustainable rate, torn reads of 32-bit values, effect on the PLC scan time, as a function of poll plan.
- **Value.** Concrete, measurable, specific to cheap PLCs. Needs the pipeline-diagnostics panel.

### B2. Sensorless payload and collision estimation
- **Question.** Can payload and collisions be estimated from drive current and the twin's torque model?
- **Method.** Predicted vs measured motor current at known payloads (the twin already takes a payload in kg); step changes show collisions or jams.
- **Needs.** Motor current sensors (planned) or drive current objects over CANopen/PLC memory; known test masses.

### B3. Parameter identification and drift
- **Question.** Can motor and friction parameters be fitted from logged runs, and do they drift with use?
- **Method.** `tools/fit_motor_params.py` on recorded real runs, repeated over days; plot parameter vs cycle count.
- **Value.** Basis for predictive maintenance.

### B4. Live structural load and factor of safety
- **Question.** Can the twin show live reaction moments, stress and FOS comparable to the Ansys study, and is it accurate enough to be trusted?
- **Method.** CAD masses and inertias, joint reaction moments from the dynamics, stress via the Ansys sensitivities or a reduced-order surrogate fitted to the Ansys cases (holding and pick-up deformation, FOS).
- **Needs.** The CAD file and the Ansys exports (see [CAD_IMPORT.md](CAD_IMPORT.md)). Validate against measured deflection from motion capture (C1).

### B5. Surrogate/reduced-order model of the Ansys study
- Fit a fast model to the Ansys runs so the live twin can estimate stress in real time; report surrogate error against the full FEA.

### B6. Calibration quality
- **Question.** How good is the twin after calibration, and how does error depend on the amount and type of data used?
- **Method.** Calibrate on one run, test on others; report held-out error.

---

## C. Motion capture as independent ground truth

### C1. Triple comparison: encoder, camera, twin
- **Question.** Where do the three disagree, and why (backlash, flex, calibration, lost steps)?
- **Method.** AprilTag pose from the camera ([MOCAP_PLAN.md](MOCAP_PLAN.md)) vs encoder-derived tip vs twin tip.
- **Metric.** Tip error in mm per phase; an error budget per source.

### C2. Taught-point repeatability and drift
- Over many cycles, how far does the real arm miss each taught point, and does it grow? Camera plus the taught-point table in the GUI.

### C3. Structural deflection measurement
- Camera-measured deflection under load against the Ansys prediction (B4). Needs a camera accurate to well below the expected deflection; the mocap doc lists the measured accuracy.

---

## D. HMI-side angles

### D1. Read the real HMI by OCR
- **Idea.** Parse values, screen name and lamp states from the VNC picture, so the screen the operator sees (not exposed by the PLC) becomes data.
- **Value.** Lets A2 compare the displayed HMI to the PLC value, which detects HMI/PLC mismatch. Not built.
- **Risk.** Picture latency (2 Hz) and unsynchronised timestamps.

### D2. Operator-action logging
- Record button presses seen as state changes and their effects; compare operator sequences with automation sequences.

---

## E. Other directions
- **E1. Cyber-physical anomaly detection** combining A5, A6, B2 and A9 into one residual-based detector with a published false-alarm figure.
- **E2. Teaching points by demonstration** using the camera; compare accuracy with HMI teaching.
- **E3. Energy and cycle-time optimisation** in the twin (speed set-points vs cycle time and peak current), then verify on the real arm.
- **E4. Open dataset.** Release a documented dataset of real runs (PLC memory, drive words, sensors, camera) with the twin as baseline; datasets of cheap PLC cells with fault labels are rare. Check licensing and that nothing sensitive (passwords, network details) is in it.
- **E5. Educational/low-cost twin.** Report how little hardware and software this twin needs (Python only, three.js in the browser, Modbus) as a reproducible recipe.

---

## Suggested priority
1. Logger/replay and pipeline diagnostics (needed by everything).
2. A3 + A2 + A4 on tomorrow's real run (see [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md)); B1 falls out of the same data.
3. A1 (can start on recorded data) and B3.
4. A8 and B2 once sensors exist; C1 once the camera is calibrated.
5. Pick the paper from what the data shows. Likeliest pairs: **A1 + A8** (executable-ladder shadowing with fault signatures), **B1** (Modbus fidelity study), **B2 + B3** (sensorless payload and wear), **A9** (tamper detection).

## Candidate venues (check scope and deadlines yourself)
Conferences: IEEE ETFA, INDIN, CASE, IECON, ICPS; journals: Sensors, IEEE Access, Robotics and Computer-Integrated Manufacturing. These are suggestions from general knowledge, not checked.
