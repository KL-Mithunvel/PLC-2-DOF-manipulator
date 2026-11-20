# Bag file format (stage 1 and 2)

A bag is a recording of one session: timestamped messages on named topics, plus run metadata. Code: `bag/`. Written by the Hub when you record (Data sources tab or `run_twin.py --record NAME`); read with `bag.BagReader`, `python -m bag info FILE`, or Foxglove Studio (MCAP).

## Files
| Suffix | Format | When |
|---|---|---|
| `.mcap` | MCAP, unchunked (every message goes straight to the file) | default when the `mcap` package is installed |
| `.bag.jsonl` | JSON lines: line 1 header `{"bag":1,"meta":{...}}`, then `{"topic","tm","tw","d"}` per message | standard library only |
| `<name>_hmi/frame_NNNNNN.png` | real-HMI pictures referenced by the `hmi/frame` topic | only when `--hmi-vnc` is used |

**Crash safety.** MCAP normally buffers up to one chunk in memory; this project writes unchunked and flushes about every 50 snapshots, so after a crash, kill or power cut the file still opens (`python -m bag info` prints `NOT CLOSED CLEANLY` and every complete message before the cut is readable; a half-written last record is dropped). The reader reads sequentially and does not need the MCAP footer.

## Every message
`topic`, `t_mono` (monotonic seconds on the recording PC: use for ordering, latency and jitter, it never jumps), `t_wall` (unix seconds: use to line up with other PCs, camera files, the HMI). MCAP stores `t_wall` as `log_time` and `t_mono` as `publish_time`, both in nanoseconds.

## Metadata (`bag.collect_meta`, plus what you pass)
`created_iso`, `host`, `python`, `platform`, `git.commit`, `git.dirty`, `plc_program_sha` (hash of `twin/plc/MAIN_MAIN.ilp`), `modbus_map_sha`, `versions` (pymodbus, mcap, vncdotool, numpy), and from `--notes` / `--payload-kg` / the GUI fields: `notes`, `payload_kg`, `operator`, `run`. **Never put passwords or network credentials in metadata.**

## Topics
| Topic | Payload | Rate |
|---|---|---|
| `twin/state` | full twin snapshot ([SCHEMA.md](SCHEMA.md)) | 25 Hz |
| `plc/decoded` | pose snapshot of the real PLC (angles, bits, registers, taught points) | 25 Hz of the latest poll |
| `plc/raw` | one poll of one group, see below | fast group 10 Hz, slow group 1 Hz |
| `diag` | `{"source": "plc"/"hub", ...}` statistics, see below | 1 Hz each |
| `events` | `{"text","kind","source"?}`: twin log lines, PLC connect/error | when they happen |
| `hmi/frame` | `{"n","t_frame_wall","bytes","sha","file"}` reference to a stored picture | one per 2 s |
| `mocap/pose`, `sensors` | snapshots of those sources; `sensors` = measured motor current/voltage (ESP32 feed or power meters) | with their source |
| `sensors/raw` | power meters: `{"t_mono","t_wall","meter":"base|shoulder","slave","t0","t1","regs":[8 registers]}`; `live.pzem.decode_regs` gives V, A, W, Wh | meter poll rate (about 2 Hz) |

### `plc/raw` record (one poll of one group)
```
{"t_mono","t_wall","group":"fast|slow",
 "blocks":[{"kind":"discrete|coil|word|wordbits","area":"I|Q|M|V","byte0":10,"addr":650,"n":352,
            "t0":..,"t1":..,"data":"<hex bits, LSB first>" | [register values]}]}
```
`t0`/`t1` are the monotonic times the request was sent and the reply received (the real value is somewhere in between; the Modbus round trip is `t1 - t0`). `byte0` is the PLC byte address of the first value in the block, `n` the number of bits or registers, `addr` the Modbus address used. `live.raw.apply_record(record, memory)` writes a record back into a `twin.il.Memory`, so a recorded PLC state can be rebuilt offline.

### `diag` payload for the PLC source
`polls`, `errors`, `reconnects`, `last_error`, `age_s` (time since the last good poll), `uptime_s`, `groups.{fast,slow}` with `rate_hz`, `jitter_ms` (std of the start-to-start period), `period_ms` and `cycle_ms` (each `n, mean, p50, p95, max, min, std` over the last 200 polls), `blocks.<kind:area+byte>` (round-trip ms per request). The `hub` entry has `step_ms`: the period of the Hub loop itself (shows how loaded the PC is).

## Poll groups and torn reads
The PLC reader polls two groups at their own rates: **fast** (I, Q, M10..53 bits, `%MD600` as 64 coils, the whole PDO area `V1000..V1063`) at `--plc-hz` (default 10) and **slow** (V2000.., taught data V2300.., V2490..) at `--plc-slow-hz` (default 1). A 32-bit value could be torn if its two halves arrived in different requests; `live.plc_reader.check_plan()` verifies that every double word the program uses sits inside one request (tested). Different values in one poll are NOT sampled at the same instant: use the per-block `t0`/`t1`.

## Reading in code
```python
from bag import BagReader
r = BagReader("logs/R3.mcap")
print(r.meta["notes"], r.topics, r.duration, r.truncated)
for m in r.messages(["plc/raw"], t_from=..., t_to=...):
    m.t_mono, m.t_wall, m.payload
```
