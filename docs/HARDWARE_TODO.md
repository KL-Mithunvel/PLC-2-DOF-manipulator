# What to do when hardware is available (list written 2026-11-20)

Ordered by what unblocks the most. Session details and checkboxes for the first visit: [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md). Everything below is untested on real equipment so far.

## A. First session with the real PLC and arm (H1, planned 2026-11-21)
1. Connect: `python run_twin.py --plc 192.168.0.252 --hmi-vnc 192.168.0.253 --plc-hz 25`; read the pipeline diagnostics (achieved rate near 25 Hz, errors 0).
2. **Verify the mapping**: type known values on the HMI, find them with `python -m live.scan`; confirm the M-area offset and that `%MD600` / `%VD1044` follow the arm (sign, scale). Fix `docs/MODBUS_MAP` entries and note what changed.
3. **Record** R1 idle 60 s, then a START cycle, then an e-stop and reset run (same actions on the real HMI and in the twin), with `--notes` and `--payload-kg`.
4. **Check every recording at once, before power-off**: `python -m bag check logs/R*.mcap`. Redo anything marked NOT USABLE.
5. Run `python -m shadow report FILE` (ladder) and `--mode open`; keep the first real divergence numbers (these replace every simulated number in the docs).
6. Log `%VW1022` with and without the payload; note the drive's rated and peak current from the manual (decides the shunt, see D).
7. Calibrate the HMI reader: save a few live VNC frames, run `python -m live.hmi_reader FRAME.png`, fix the pixel fractions, learn what the lamp colours and the switch ON look mean, and cross-check against `%Q` / `%M` bits.
8. Photograph the wiring of both drives and the supply taps.

## B. Right after the first session (no hardware needed, real data in hand)
1. Update the Modbus map, `HARDWARE.md` and `DECISIONS` with what was actually found; flip verified flags.
2. Re-run the fault library question on real data: does the open-mode angle residual look like the simulated healthy case? Retune the twin (`tools/fit_motor_params.py`) from the real logs.
3. Decide the paper angle with [NOVELTY_CHECK.md](NOVELTY_CHECK.md): if ladder conformance holds at 25 Hz on the real PLC, that is the lead result. Then read the closest papers in full (Khan 2018, synchronisation in ICS twins).
4. Fix whatever the first real recording breaks (expect timing, gaps, mapping surprises).

## C. Second recording campaign (for a paper)
1. Repeated runs: baseline (3+ days), with payloads 0 / 2 / 5 kg, with the e-stop mid-move, with an intentionally added friction (a clamp), at 10 / 25 / 50 Hz poll rates for the sampling-limit result.
2. Long soak run (hours) to measure clock drift, reconnects and file size.
3. Same operator actions logged with timestamps (notes) so divergence events can be matched to causes.
4. Save the data with its metadata and hashes; prepare an open dataset package (README, schema, `bag check` output).

## D. Power measurement (ESP32 + INA226)
1. Confirm the motor peak current from A.6, then **choose the shunt** (volts across it under 81.92 mV at peak) and check which resistor the INA226 breakout carries (0.1 ohm boards clip at 0.8 A): set `SHUNT_OHMS`, `MAX_CURRENT` in the sketch to match.
2. Bench test first: known load, bench supply and multimeter in series, check the mA and mV values; then flash and read the `H,` header and `S,` lines.
3. Wire the shunts in the +24 V supply of each drive (fuse, short I2C leads, ground rules in [FIRMWARE.md](FIRMWARE.md)); run `python run_twin.py --sensors serial:COM5@921600` next to `--plc`.
4. Fit the torque constant and efficiency (`tools/fit_motor_params.py --smooth N`); then repeat the payload study with real shoulder current ([FAULTS.md](FAULTS.md)): is the bias per kg as large as simulated?
5. If a PLC-compatible meter is still wanted: PZEM-017, verify its register map and serial format, flip `REGISTER_MAP_VERIFIED` ([POWER_METER_PLAN.md](POWER_METER_PLAN.md)).

## E. Motion capture and the CAD stage
1. Buy cameras per [MOCAP_PLAN.md](MOCAP_PLAN.md); calibrate; check marker visibility on the real arm; record `mocap/pose` in the same bag.
2. Compare the mocap pose with the PLC-derived pose and the twin (three-way shadow), measure latency between them.
3. CAD / structural stage: measure link lengths, masses and inertias on the real arm; replace the assumed values in the twin config and rerun the calibration.

## F. Housekeeping once data exists
1. Push the local commits and tag the version used for the first paper run.
2. Add a GitHub Actions workflow that runs the tests on every push (not built yet).
3. Tamper-detection study: record a run with a modified ladder (on a copy, never the machine program without a backup) and test whether divergence flags it.
4. Paper figures script from `analysis/` and `shadow/` outputs.

## Rules to keep
Read-only to the PLC (the reader has no write path), no changes to the machine program without a backup, e-stop reachable, VNC view-only, never commit passwords.
