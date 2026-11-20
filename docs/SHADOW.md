# Shadow-and-diverge toolkit (`shadow/`)

Stage 4 of [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md). Standard library only, no GUI, no hardware. It answers: *given two recordings of the same thing (the real machine and the twin), how far apart are they, when did they start to differ, and by how much?* Research angles that use it: [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md) A1-A8, B1, B3.

## Pipeline
```
bag / snapshots --> Signal --> estimate_lag --> residual --> detectors --> EventLog --> events (bag topic / report)
```

## Signals (`shadow/signals.py`)
`Signal(name, t, v, kind)`: time stamps must not go backwards. `kind="analog"` interpolates linearly, `kind="binary"` holds the last value. `at(t)` returns `None` outside the recorded range (never extrapolates). Build from snapshots or bag messages by path (`/` separates parts because PLC addresses contain dots):
```python
from shadow import from_frames, from_messages
angle = from_frames(frames, "base/deg")                             # frames: snapshots with their own "t"
bit   = from_messages(bag.messages(["plc/decoded"]), "bits/M30.1", clock="t_mono", kind="binary")
```
`clock` is `t_mono` (monotonic, for latency and ordering), `t_wall` (to line up with other PCs) or `payload` (the snapshot's own `t`). Use the **same clock for both sides**; the twin and the PLC snapshots have different `t` (twin time vs unix time), so compare them on `t_mono` or `t_wall`.

## Time alignment (`shadow/align.py`)
Convention: **positive lag = b is later than a**: `b(t) ~ a(t - lag)`.
- `estimate_lag(a, b, max_lag, dt)`: cross-correlation on a grid, refined below the grid step. Returns `LagResult(lag, score, n)`; `score` is the correlation at the best lag (near 1 = the shapes match; below about 0.5 means the signals are not the same thing, do not trust the lag). Tested: known lags of 0.37, -0.82, 0, 2.11 s recovered within 20 ms with 25 % dropped samples, time-stamp jitter and noise.
- `estimate_lag_edges(a, b)` and `edge_delays(...)`: for binary signals; matches rising edges. The per-edge delays are themselves a result (response latency of a PLC bit versus its twin).
- `lag_drift(a, b)`: lag per window and a straight-line fit; `ppm` is the clock-rate difference (tested: 200 ppm recovered within 40 ppm over 10 minutes).
`tools/compare_runs.py` has its own lag search with the opposite sign.

## Residuals (`shadow/residual.py`)
`residual(real, twin, lag, dt)` = `real(t) - twin(t + lag)` on a uniform grid. `Residual.stats()` gives `bias, rms, std, max_abs, t_max, lag`. For bits: `mismatch_intervals(res, min_len)` lists the spans where the two disagree (`min_len` drops disagreements that are only a small edge-timing offset), `mismatch_rate`.

## Detectors (`shadow/detect.py`)
| Detector | Finds | Parameters |
|---|---|---|
| `Threshold(limit, hold_s)` | residual above a limit for at least `hold_s` | limit in signal units |
| `Cusum(k, h, baseline_s)` | small persistent shifts and slow drifts early | `k` allowance and `h` limit in sigma of a baseline window; defaults 0.5 and 10 |
| `WindowRms(window_s, limit)` | sustained error rather than spikes | |
`detect(residual, *detectors)` returns `Alarm`s; `EventLog` merges alarms of the same detector and signal closer than `gap_s` and exports `events()` (dicts with `kind="divergence"`) for the bag `events` topic.
Measured on synthetic data: no false alarm in 600 s of clean white noise at 20 Hz; a 3-sigma step detected within 1 s; a slow ramp found 20 s or more before a fixed threshold. **Real residuals are correlated, so the false-alarm rate will be higher than the white-noise figure**: measure it on clean runs before quoting detection results.

## Limits
- Alignment assumes a constant lag over the analysed window; use `lag_drift` to check.
- The cross-correlation needs the signal to change; a flat signal gives score 0.
- Detector baselines come from the start of the run: start recordings with the machine in a normal state.
- Pure Python is fast enough for tens of minutes of 20 Hz data; for hours, thin the data first.
