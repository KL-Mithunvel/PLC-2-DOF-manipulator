# Offline analysis (`analysis/`)

Stage 10 of [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md). Reads a recorded bag ([BAG_FORMAT.md](BAG_FORMAT.md)) and prints or exports the numbers a paper table or a maintenance log needs. Standard library only.

```
python -m analysis summary logs/R3.mcap [--json s.json]
python -m analysis csv logs/R3.mcap out.csv base/deg shoulder/deg bits/Q0.7 [--topic twin/state]
```
`summary` needs `plc/raw` (a recording of the real PLC, or `python -m shadow synth` for a synthetic one).

| Output | How it is computed | Use |
|---|---|---|
| **cycle table** | the real memory is rebuilt poll by poll; for each auto run, the time of the first rising edge of every step flag `M31.0`..`M32.0` per cycle, and the step durations | compare step durations with the twin; the timed steps `M31.3` and `M31.7` show the timer base |
| **pick-to-pick period** | time between successive rising edges of `M31.2` (arrival at the pick position) | the cleanest cycle time (the first cycle includes the approach from home); its spread and trend over days is the wear indicator (A6) |
| **link report** | round trip per Modbus request from the raw `t0`/`t1`, poll period, achieved rate, jitter, longest gap, per poll group | the data of the Modbus fidelity study (B1); an independent check of the `diag` topic |
| **pick repeatability** | arm counts, angles and tip position at each arrival at `M31.2`; spread over cycles | taught-point miss and repeatability (C2) |
| **CSV export** | one row per message of a topic, with `t_mono`, `t_wall` and the chosen payload paths (`/` separated; missing values stay empty) | spreadsheets, plots, papers |

Checked on synthetic recordings: three cycles found, pick delay `M31.3` and drop delay `M31.7` measured at 0.20 s (20 ticks x 10 ms), 25 Hz and 1 Hz poll rates recovered, jitter and round trip equal to what was simulated, pick spread of a deterministic twin under 5 mm. **Not yet run on a real recording**: the numbers on the real arm will show how much of the spread is the machine and how much is the measurement.
