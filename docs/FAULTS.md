# Fault injection and signatures (`shadow/faults.py`)

Stage 6 of [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md), research angle A8 in [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md). **Everything here is synthetic**: a twin with a seeded fault stands in for the real PLC, and a healthy twin shadows it ([SHADOW.md](SHADOW.md)). It shows what the available signals can and cannot tell apart; it is not a result about the real machine.

## Method
1. `synthesize(fault, severity)` records a 20 s session (25 Hz fast poll) from a twin with the fault injected.
2. `signature(records)` runs the healthy twin against it in both shadow modes (ladder free-running, open loop) and reduces the two reports to 8 numbers: log base and shoulder angle rms, log base-current bias, number of timing alarms, their size in ms, a latch flag (conformance alarm on `M30.6`/`Q0.7`), a gap flag, number of bits with conformance alarms.
3. `classify(signature, library)` = nearest centroid in standardised feature space. The stored library `shadow/fault_library.json` holds 3 severities (0.3, 0.6, 0.9) of each fault.

## Faults
| Fault | Injection | Visible as |
|---|---|---|
| none | healthy | nothing (the false-alarm reference) |
| friction | Coulomb friction on both axes x20..x45 | **base current** far above the twin's, angles still normal |
| payload | 5 -> 8 kg | nothing in these signals (see limits) |
| slow_base / slow_shoulder | profile speed down by up to 50 % | large angle residual on the slowed axis, bigger on both at high severity |
| timer | PLC timer base x1..x2 | timing alarms on the timed steps (`M31.3`, `M31.7`) once the error is large enough |
| latch | e-stop magnet-latch patch in the real ladder, e-stop pressed | conformance alarm on `M30.6` and `Q0.7` |
| link_outage | poll link drops for 2.5..5.5 s | a gap in the recording (not a machine fault) |

## Measured accuracy (leave one severity out; 8 classes, 3 severities)
Held-out severity 0.3: 62 %, 0.6: 75 %, 0.9: 75 %. Confusions seen:
- **payload is not distinguishable from healthy**: +3 kg changes neither the angles nor the base current. The shoulder motor current (the load that matters) is not in the PLC's PDO map: this needs the current sensors of stage 7.
- slow_shoulder is classified as slow_base: both slow the whole motion, and the angle residuals overlap. A per-phase breakdown would separate them (the base moves first in the sequence).
- a mild timer error (x1.3) looks like noise or another fault; at x1.9 the timing alarm is clear.
- Not confused: healthy, friction, latch, link_outage in every held-out case.

## Use
```
python -m shadow faults list
python -m shadow faults build                       # rebuild the library (about 90 s)
python -m shadow faults classify logs/R3.mcap       # shadow a recording and name the closest known case + all distances
```
A large distance to every case means a new kind of difference, not that the nearest one is right. When real recordings with real faults exist, add them to the library with their true label.

## Limits
- Synthetic: the real machine has noise, backlash, compliance and sensor effects the twin does not model; expect lower accuracy.
- Eight hand-made features and a nearest-centroid rule are a baseline, not a tuned classifier; three severities per fault is a small library.
- Faults are injected one at a time; combinations are not covered.

## Measured shoulder current closes the payload gap (simulated, 2026-11-20)
`shadow.faults.power_study(fault, severity)` shadows a synthetic faulted recording in open mode **with** an ideal external current meter (the twin's own motor model, averaged over 40 ms, 100 Hz) and reports the current residuals. Result (bias of real minus twin, mA; healthy shoulder bias +75):

| case | base current (PLC-exposed) bias | shoulder current (meter) bias |
|---|---|---|
| healthy | -6 | +75 |
| payload +0.3 kg | -6 | +176 |
| payload +1.5 kg | -4 | +577 |
| payload +3 kg | +1 | +1071 |
| friction (severity 0.3) | +765 | +283 |

So the shoulder current bias grows about 340 mA per kg while the PLC-exposed base current stays flat: the payload that was invisible to every PLC signal becomes visible, and friction (base-current signature) separates from payload (shoulder-current signature). **Limits:** the meter here is ideal (no noise, offset, quantisation or shunt error), the twin and the "real" machine share the same model structure, and the RMS residual is large even when healthy (1490 mA, timing/chatter), so only the **bias** is usable. Whether the real shoulder separates equally well depends on the real meter noise and on how well the twin's torque model is calibrated. `run_open(records, sensors=...)` takes real meter samples unchanged. Tests: `tests/test_power_shadow.py`. The fault library (`fault_library.json`) was not rebuilt with a power feature.
