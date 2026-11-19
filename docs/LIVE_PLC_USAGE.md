# Live PLC feed: how to use it (built 2026-11-19, tested against the twin only)

**Never tested against the real PLC.** Everything below was verified against the twin's own Modbus server. The Kinco address mapping is an assumed default.

## Safety
- The reader is **read-only by construction**: `live/plc_reader.py` wraps pymodbus in a class that has no write methods, and the twin's own Modbus server refuses write function codes.
- The PLC accepts only a few TCP connections and the HMI already holds one. The reader opens a single connection at 10 Hz by default (`--plc-hz`).

## Steps with the real PLC
1. PC on 192.168.0.x, `ping 192.168.0.252` works.
2. Find the real address offsets (do this before trusting any number):
   `python -m live.scan --host 192.168.0.252 --know VD2020=300 --know VW2036=3` where the values are what the HMI currently shows (use distinctive numbers, not 0 or 1; the taught positions `VD2300..2316` also work). Add `--save` to write `live/modbus_map.json`. If nothing matches, the mapping is different from the register-per-word rule in `live/modbus_map.py`: get the address table from the KincoBuilder manual.
3. Run the twin with the live feed: `python run_twin.py --plc 192.168.0.252`. In the **Data sources** tab pick `plc` as the ghost: a translucent cyan arm follows the real encoder counts (`%MD600`, `%VD1044`) next to the simulated arm, with the angle and tip error shown under the 3D view.
4. Record (Data sources tab) while running the real arm, then compare runs offline (`tools/compare_runs.py`).

## Offline / development
- `python run_twin.py --modbus-serve 1502` exposes the twin as a read-only Modbus TCP server with the same mapping; point `--plc 127.0.0.1:1502` of a second instance at it, or use any Modbus client.
- Tests: `python run_tests.py`.

## Files
`live/modbus_map.py` (mapping, assumed offsets) - `live/plc_reader.py` (read-only client + source) - `live/scan.py` (offset finder) - `twin/modbus_server.py` (twin as Modbus server).
