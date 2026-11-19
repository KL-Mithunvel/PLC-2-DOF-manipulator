# Snapshot schema v1

Every data source (`sim`, `replay`, `plc`, `mocap`, `sensors`) emits JSON snapshots. Units: metres, degrees, seconds, N.m, rpm (motor side), counts (motor encoder).
World frame: z up, base yaw about z, shoulder pitch measured from vertical-up (0 = home).

## Always present
| field | meaning |
|---|---|
| `schema` | 1 |
| `source` | `sim`, `replay`, `plc`, `mocap`, `sensors` |
| `t` | source time, seconds (sim time for `sim`; unix time for live sources) |
| `wall` | unix time when the snapshot was made |

## Pose (needed by the 3D ghost arm and error overlays)
`base.deg`, `shoulder.deg`, `geom.shoulder|p|tip` (xyz m), `io["Q0.7"]` (magnet), `geo_cfg` (reach, h, drop, part_r, part_h).
`twin.sources.pose_snapshot()` builds this from two angles.

## Full `sim` snapshot (also what the recorder stores)
`io`, `bits` (M/SM bits), `regs` (V/M registers), `timers`, `counters`, `trace` (per-instruction power flow of the last scan, one char per instruction), `net_power`,
`base` / `shoulder` axis objects (deg, ref_deg, target_deg, count, rpm, tau, load_pct, current_ma, statusword, controlword, ...), `load` (payload, inertias, gravity torque),
`part`, `placed`, `points` (taught tips), `pdo`, `hmi`, `sample` (scope point), `structural` (stress / FOS, see `twin/loads.py`), `sensors` (measured current/voltage if a sensor source is attached).

## Extras by transport
`watch` (operand values) and `hub` (source/recorder status) are added to stream frames only, never recorded. `ghost` carries a second source's snapshot. `replay` carries transport state.

## Compatibility rule
Add fields freely; never change the meaning or unit of an existing one without bumping `schema`.
