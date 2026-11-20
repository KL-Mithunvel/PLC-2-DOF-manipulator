# Live PLC feed: how to use it (built 2026-11-19, tested against the twin only)

**Verified on the real PLC (2026-11-20, 192.168.0.252, PLC in RUN):**
- Modbus TCP on port 502 works with `pymodbus` 3.16.2 (coil, discrete-input and holding-register reads).
- **V area offset 100 confirmed**: `python -m live.scan --host 192.168.0.252 --know VD2020=300 --know VD2030=777` found offset 100 for both values, and direct reads returned 300 and 777 (`%VD2020` = base speed, `%VD2030` = shoulder speed, typed on the HMI; 32-bit values are low word first). The scan only reads.
- With all HMI values at 0 the scan cannot find anything: it needs distinctive non-zero values.

**Still unverified on the real PLC:** the M area (bits at 320 + byte*8 + bit, `%MD600` read as 32 coils), `%VD1044`, and the cycle counters (`%VW2500` minutes / `%VW2510` seconds, `%VW2400` cycle number); they read 0 while the machine was idle.

Network: the PC needs a static IP on the PLC's subnet that is **not** the PLC's own address (e.g. `192.168.0.10/24` while the PLC is `192.168.0.252`). If the PC takes the PLC's address, `ping` succeeds against the PC itself (TTL 128, <1 ms) and proves nothing; a real PLC reply has TTL 255.

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
3. Run the twin with the live feed: `python run_twin.py --plc 192.168.0.252`. In the **Data sources** tab pick `plc` as the ghost: a translucent cyan arm follows the real encoder counts (`%MD600`, `%VD1044`) next to the simulated arm, with the angle and tip error shown under the 3D view. While the ghost is `plc` the **HMI replica mirrors the real PLC values** (speeds, taught positions, cycle counters, magnet switch; read-only, cyan outline); with ghost `none` it shows the simulation. Open `http://127.0.0.1:8765/?ghost=plc` (optionally `&screen=MANUAL`) to start mirrored. Reload the page after restarting the twin. The replica cannot follow which screen the real HMI shows (the PLC does not expose it).
4. Record (Data sources tab) while running the real arm, then compare runs offline (`tools/compare_runs.py`).

## Offline / development
- `python run_twin.py --modbus-serve 1502` exposes the twin as a read-only Modbus TCP server with the same mapping; point `--plc 127.0.0.1:1502` of a second instance at it, or use any Modbus client.
- Tests: `python run_tests.py`.

## Files
`live/modbus_map.py` (mapping, assumed offsets) - `live/plc_reader.py` (read-only client + source) - `live/scan.py` (offset finder) - `twin/modbus_server.py` (twin as Modbus server).
