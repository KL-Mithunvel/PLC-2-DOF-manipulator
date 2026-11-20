# Session record: scope, decisions and work of 2026-11-20

A record of the planning discussion and what was done, so the reasoning is not lost. Details live in the linked documents.

## Scope (stated by the project owner)
- Use the existing setup to build something novel that is credible on a resume and tests skills, with the aim of publishing papers or conference talks.
- Data can now be read from the real PLC over Modbus (pymodbus) and the real HMI can be viewed over VNC (both worked on 2026-11-20).
- Wanted: a digital twin and a clear idea of what outputs it gives; the same GUI fed with live data from the Python code; a bag-file style log of real PLC movement data.
- Real-hardware test planned for 2026-11-21.
- A **standalone twin with no hardware**, kept separate so it can be shown to people, with a better 3D view and ladder view.

## What a digital twin gives (conclusions)
1. Shadow and diverge: run the real PLC program in the twin beside the real machine; differences reveal faults, wear, wrong parameters or network problems.
2. Estimate what is not measured (joint torque, reaction moment, stress, factor of safety, payload).
3. Predict (what-if runs before real runs).
4. Calibrate (fit motor and friction parameters from logged runs).
5. Triple-check against ground truth (encoder, camera, twin).

## Main plan chosen: shadow and diverge
Real HMI and simulated HMI side by side, the same commands to both, reset and e-stop applied in both, twin arm compared with the real arm. Rules agreed: the twin only reads; the real e-stop stays a hardware action; time alignment is the main technical problem.
Further shadow-and-diverge work identified: ladder conformance, timing, drive state machine, trajectory residuals, current/torque (payload and collision), mocap residual, taught-point drift, stop behaviour, fault-injection signatures, communication staleness, tamper detection, regression testing of program changes. All listed with questions, methods and metrics in [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md).
Pairs judged most promising for a paper (novelty not yet checked): executable-ladder shadowing with fault signatures; a Modbus fidelity study on a low-end PLC; sensorless payload and wear estimation; tamper detection.

## Decisions
| Decision | Reason |
|---|---|
| Bag log format: MCAP (JSON-lines fallback) with replay into the GUI | opens in Foxglove, ROS-compatible, lets real runs be re-analysed offline; not built yet |
| Build the divergence framework (aligned residuals, thresholds, event log) once and reuse it | every shadow angle needs it |
| Pipeline diagnostics panel (poll rate, latency, jitter, errors, data age) | shows how the code runs, and is the data for the Modbus study |
| Standalone twin must never import hardware modules | showcase must always run; enforced by `tests/test_standalone.py` |
| Build in modules with a gate per stage, integrate last | [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md) |
| Record raw data from the first real session even if the bag logger is not ready | real data is the scarcest input |

## Done today
- Documented what was missing: the real HMI over VNC and the pymodbus reading ([LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md), ARCHITECTURE, USER_GUIDE).
- New documents: [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md), [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md), [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md), this file.
- 3D view: preset views, animated transitions, follow tip, fit, reset (double-click or R), zoom to cursor, right-drag pan, wider limits, tall and full-screen, keys 1-5.
- Ladder view: single two-axis scroll area, drag to pan, Shift+wheel sideways, Ctrl+wheel zoom, zoom buttons, fit width, jump-to-network menu, tall and full-screen, sticky titles.
- `--demo` mode: the page loops the 3-cycle program unattended (sequence checked on the twin); click to take over.
- Test: standalone isolation. Suite: 66 Python tests and the node tests pass.

## Not verified / open
- 3D interactions and the demo loop were not tried by a person in a live browser (only a headless screenshot and the load smoke test). Demo timing is tuned for 1x speed.
- On real hardware: M-area offset, `%MD600`, `%VD1044` and the cycle counters are still unverified (V offset 100 is verified).
- The HMI address, port and password setting used on the day were not recorded; the docs list the panel at 192.168.0.100 and the `run_twin.py` help shows 192.168.0.253 as an example.
- Nothing has been run on the real arm, camera or sensors yet; novelty of the paper angles has not been checked against the literature.

## Next
Stage 1 (bag logger and replay) and stage 2 (live PLC source with diagnostics), then the field test H1 on 2026-11-21 with [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md).

---

# Build session, later on 2026-11-20 (stages 0-6, 10 and the Shadow tab)

Authorised by the project owner to build as much as possible within the agreed scope, test, commit each step and update the docs. Nothing was pushed in this session. Everything below was tested **without hardware**; nothing has been run against the real PLC, camera or sensors yet.

## Built (one commit each)
| Step | What | Doc |
|---|---|---|
| Stage 0 | showcase README section, overview screenshot, demo-mode smoke test | README |
| Stage 1 | `bag/`: MCAP or JSON-lines bags, run metadata, recorder, replay, converter, `python -m bag` | [BAG_FORMAT.md](BAG_FORMAT.md) |
| Stage 2 | live PLC diagnostics, raw Modbus blocks with send/receive times, fast/slow poll groups, reconnect, session recording (`--record`), diagnostics panel | [LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md) |
| Stage 4 | `shadow/`: signals, time alignment, residuals, detectors, event log | [SHADOW.md](SHADOW.md) |
| Stage 5 | shadow engine: ladder conformance and open-loop twin vs real arm, CLI | [SHADOW.md](SHADOW.md) |
| Stage 6 | fault injection, signatures, nearest-centroid classifier, stored library | [FAULTS.md](FAULTS.md) |
| Stage 10 | `analysis/`: cycle and step timing, pick period, link report, repeatability, CSV | [ANALYSIS.md](ANALYSIS.md) |
| I4 (offline part) | Shadow tab in the GUI on a recorded bag | [SHADOW.md](SHADOW.md) |

## Problems found while building, and what was done
- **`--record-format bag` was parsed but never reached the Hub** (stage 1 claimed bag was the default but recordings were still the old format). Fixed in stage 2 and tested end to end.
- **Hard-killed recordings were unreadable** (chunked MCAP keeps data in memory and needs a footer). The writer is now unchunked and flushed, the reader reads sequentially; a killed process leaves a readable file (tested, and checked with a real hard kill).
- **Drive status words were in the slow (1 Hz) poll group**, so a ladder-level comparison saw them up to a second stale. The fast group now covers the whole CANopen PDO area `V1000..V1063`.
- **The taught points are PLC state, not inputs**: the ladder itself writes them (teaching, and the `%VW2400` overlap defect). Feeding them in every scan corrupted the shadow; they are seeded once.
- **10 Hz sampling is too slow to follow a free-running ladder**: the arm crosses a +-2000 count window faster than one poll, and one event (`M31.4`) depends on two quantities that are only inside their windows together for a moment while one of them moves because of the event itself. Linear interpolation of the analogue feedback and a one-step-ahead (resync) mode contain this; at 25 Hz a free-running shadow holds for 40 s. **Record conformance runs at 25 Hz or more.**
- The headless Edge used by the UI smoke test occasionally hangs at start-up; the test now retries once.

## What the synthetic tests establish (and what they do not)
Established, on a twin standing in for the PLC: a patched ladder (e-stop latch) is detected 70 ms after the e-stop; a doubled timer base is reported as "twin earlier by 200 ms" on exactly the two timed steps; a slower real axis is found in open mode; friction shows only in the base current; the fault classifier is 62-75 % accurate leave-one-severity-out, with payload invisible and slow shoulder confused with slow base. Not established: any statement about the real machine. The real recording will show how large the unexplained part is.

## Not built / still open
- Stage 3 (reading the real HMI picture by OCR) and the `hmi/frame` consumers: pictures are stored with the recording, nothing reads them yet.
- Stage 7 (motor current sensors: hardware), stage 8 (real camera calibration), stage 9 (needs the CAD file and Ansys exports).
- A9 tamper detection, plots in `analysis/` (CSV export only), integration stages I5-I7.
- First real recording (H1, 2026-11-21): [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md). The HMI address used on 2026-11-20 was 192.168.0.253.
