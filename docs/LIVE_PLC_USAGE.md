# Live PLC feed: how to use it (built 2026-11-19, tested against the twin only)

**Never tested against the real PLC.** Everything below was verified against the twin's own Modbus server. The address mapping now follows the official Kinco table (below) but has not been confirmed on the real machine.

## Safety
- The reader is **read-only by construction**: `live/plc_reader.py` wraps pymodbus in a class that has no write methods, and the twin's own Modbus server refuses write function codes.
- The PLC accepts only a few TCP connections and the HMI already holds one. The reader opens a single connection at 10 Hz by default (`--plc-hz`).

## Steps with the real PLC
1. PC on 192.168.0.x, `ping 192.168.0.252` works.
2. Check the address mapping. It comes from the Kinco K-series manual, section 10.2.2.3 (`reference/vendor/Kinco_K-Series_PLC_Application_Manual.pdf`, page 483), for the K5/KS/MK/K6 series:

   | PLC area | Modbus | address |
   |---|---|---|
   | `%I0.0`..`%I31.7` | discrete input | 0..255 |
   | `%Q0.0`..`%Q31.7` | coil | 0..255 |
   | `%M0.0`..`%M1023.7` | coil / discrete input | 320..8511 (= 320 + byte*8 + bit) |
   | `%VW0` upward | holding / input register | 100 + byte/2 (`VW0` = 100, `VW2` = 101) |

   **The M area is bit-only.** Words and double words of M, such as `%MD600` (base position), cannot be read as registers: the reader fetches them as 32 consecutive coils. Limits: 1600 bits or 100 registers per request. The manual says the Ethernet Modbus TCP slave works the same way as Modbus RTU; the PLC is a Modbus TCP slave by default.
   Verify with a value you can see on the HMI (distinctive, not 0 or 1; the base speed `VD2020` or a taught position `VD2300..2316` work): `python -m live.scan --host 192.168.0.252 --know VD2020=300 --know VW2036=3`. The scan only reads. It should report the V offset **100**. If it reports something else, add `--save` to store it in `live/modbus_map.json`.
3. Run the twin with the live feed: `python run_twin.py --plc 192.168.0.252`. In the **Data sources** tab pick `plc` as the ghost: a translucent cyan arm follows the real encoder counts (`%MD600`, `%VD1044`) next to the simulated arm, with the angle and tip error shown under the 3D view.
4. Record (Data sources tab) while running the real arm, then compare runs offline (`tools/compare_runs.py`).

## Offline / development
- `python run_twin.py --modbus-serve 1502` exposes the twin as a read-only Modbus TCP server with the same mapping; point `--plc 127.0.0.1:1502` of a second instance at it, or use any Modbus client.
- Tests: `python run_tests.py`.

## Files
`live/modbus_map.py` (mapping, assumed offsets) - `live/plc_reader.py` (read-only client + source) - `live/scan.py` (offset finder) - `twin/modbus_server.py` (twin as Modbus server).
