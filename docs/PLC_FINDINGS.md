# Findings from running the real ladder in the twin

Found 2026-11-19 by executing `MAIN_MAIN.ilp` instruction by instruction. Each one is reproduced by a test in `tests/test_patches.py`. **None has been checked on the real PLC**: confirm on the real machine before changing the program. The twin never edits your PLC; the patches below are options inside the twin only.

| # | Finding | Effect | Proposed fix | Twin option |
|---|---|---|---|---|
| 1 | `%VW2400` is the low word of `%VD2400` (taught shoulder INIT position); networks 28 and 36 write the cycle counter / 0 into it every scan | The shoulder INIT point is corrupted by up to 65535 counts (about 9 deg at the output). After a finished run the shoulder parks about 3 deg off home, the shoulder-home lamp stays off and RESET (`%I0.1`) is needed before the next START | Move the C2 mirror to an unused address, e.g. `%VW2450`, and point the HMI "actual cycle" field at it | `fix_vw2400_overlap = True` |
| 2 | `M30.6` (auto magnet latch) is set at the pick point and cleared only by the release timer T23 | After an E-stop mid-cycle the magnet re-energises as soon as the E-stop is released | Clear `M30.6` when `%I0.0` is low (one extra network: `LDN %I0.0` / `R %M30.6`) | `fix_estop_magnet_latch = True` |
| 3 | The ladder enables the drives (controlword 47) only while one of `M20.1..M20.4`, `%I0.1` or `M30.0` is held for the enable delay (T2 / T3); `M30.1` (auto running) is not in that condition | START must be held longer than the delay. At 10 ms time base it is 100 ms (a normal press); if the real time base is 100 ms it is 1 s and a quick tap does nothing | Add `OR %M30.1` to networks 1 and 7, or document the hold time | none (behaviour of the original) |
| 4 | In auto mode no speed is written (only jog and homing networks write 60FF) | Auto speed comes from the drive's own profile velocity (6081), not from the HMI speed fields | Write `%VD2020` / `%VD2030` to the speed registers in the auto networks, or confirm the drive setting | `profile_rpm` in `twin_config.json` |
| 5 | Operating mode 6060 is never written | The drives must already be in position mode (stored in the drive) | Write mode 1 at start-up, or confirm the drive default | none |
| 6 | Network 4 and 10: the "follow feedback" hold (`MOVE %MD600, %VD1002`) is gated by a 1-tick off-delay (T5 / T6) | The position target is only refreshed on the scan after the request drops; harmless but easy to misread | none | none |

## Calibration still needed on the real machine
Time base of T1..T26 (10 ms assumed), `%SM0.3` period (1 s assumed), drive profile speed and acceleration: use `python -m tools.calibrate_cycle --real-time <seconds for 3 cycles> --write`.
