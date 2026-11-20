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

## Diagnostics, raw blocks and session recording (stage 2, 2026-11-20)
- **Two poll groups** at their own rates: fast (I, Q, M bits, `%MD600` and the whole CANopen PDO area V1000..V1063 with the drive status words and `%VD1044`; `--plc-hz`, default 10, use 25 for shadow/conformance runs) and slow (taught data, speeds, counters; `--plc-slow-hz`, default 1). `check_plan()` proves no double word is split across requests.
- **Diagnostics** per source, shown in the **Data sources** tab ("Pipeline diagnostics") and written to the `diag` bag topic: achieved rate, poll time mean/p95/max, jitter, errors, reconnects, data age, last error. The real-HMI picture age is listed too.
- **Raw blocks**: every Modbus reply is recorded with its send and receive times in the `plc/raw` topic, so a recording can be re-analysed (rebuild the memory with `live.raw.apply_record`). Format: [BAG_FORMAT.md](BAG_FORMAT.md).
- **Connection events** (connected, error, reconnect) go to the `events` topic. After an error the reader waits 2 s and reconnects by itself.
- **Record everything in one file**: `python run_twin.py --plc 192.168.0.252 --hmi-vnc 192.168.0.253 --record R3 --notes "3 cycles, 5 kg" --payload-kg 5` (or press **Record session** in the Data sources tab). With `--hmi-vnc`, a picture of the real HMI is stored every 2 s next to the bag. Stop with Ctrl+C; a crash still leaves a readable file.
- Tested without hardware against the twin's own Modbus server: raw round trip, group rates, injected delay and dropped requests, reconnect, session bag with all topics (`tests/test_plc_diag.py`). Not yet run against the real PLC.

## Real HMI over VNC (view only)
The real HMI panel (Kinco M2070HE-WIFI; the address used on 2026-11-20 was **192.168.0.253**; DTools lists 192.168.0.100) is grabbed as a picture over VNC and shown in the twin GUI next to the HMI replica, with the taught-point table beside it. Code: `live/hmi_vnc.py` (built 2026-11-20, first step, design to be revisited).

- Start: `python run_twin.py --plc 192.168.0.252 --hmi-vnc <hmi-ip>[:5900]`. The password is given with `--hmi-vnc-password` or the environment variable `HMI_VNC_PASSWORD`; **it is never stored in the repo** (do not write it into docs or config).
- Library: `vncdotool` (in `requirements.txt`). Only `captureScreen` is ever called: no mouse, key or clipboard call exists in the code, so the feed cannot operate the HMI. Frame rate 2 Hz; it reconnects every 3 s after an error.
- The twin serves the latest frame at `GET /api/hmi.png` and its status (connected, info, age) in the snapshot as `hmi_vnc`. The GUI card "Real HMI" shows it.
- What it gives you: the operator's view (which screen is open, lamps, values). The PLC does not expose which HMI screen is showing, so VNC is the only way to see it. It is a picture, not data: nothing is parsed from it yet (reading numbers from the picture by OCR is a possible later step, see RESEARCH_ANGLES.md).
- Limits: the panel allows a limited number of VNC clients; a second viewer may be refused. Frame age is not synchronised with the Modbus samples, so do not use VNC frames for timing measurements.
- Status on 2026-11-20: connected and viewed with the real HMI; the address, port and whether a password was needed on the day are not recorded here. Write them in the test log (HARDWARE_TEST_PLAN.md) when you repeat it.

## Reading the PLC with pymodbus (what was done on 2026-11-20)
- Library: `pymodbus` 3.16.2, Modbus TCP client, unit (station) 1, port 502. Reads only: `read_coils`, `read_discrete_inputs`, `read_holding_registers`. `live/plc_reader.py` has no write method.
- Poll plan: `DEFAULT_PLAN` in `live/plc_reader.py` (I, Q, M10..53 bits, V1000.., V2000.., V2300..2427 taught data, V2490.., `%MD600` as 64 coils), 10 Hz by default (`--plc-hz`). Values are mirrored into a `twin.il.Memory`, so the HMI replica, the ghost arm and the ladder viewer use the same code as for the simulation.
- Result: V offset 100 verified (`%VD2020`, `%VD2030`); M-area offset 320, `%MD600`, `%VD1044` and the cycle counters still need a non-zero value on the real machine (see the top of this file). Tomorrow's checklist: HARDWARE_TEST_PLAN.md.
- The pose shown for the real arm comes from encoder counts `%MD600` (base) and `%VD1044` (shoulder), converted with the ratios in `twin/config.py`.

## Offline / development
- `python run_twin.py --modbus-serve 1502` exposes the twin as a read-only Modbus TCP server with the same mapping; point `--plc 127.0.0.1:1502` of a second instance at it, or use any Modbus client.
- Tests: `python run_tests.py`.

## Files
`live/modbus_map.py` (mapping, assumed offsets) - `live/plc_reader.py` (read-only client + source) - `live/scan.py` (offset finder) - `twin/modbus_server.py` (twin as Modbus server).

## Reading the real HMI picture: `python -m live.hmi_reader FRAME.png`
`live/hmi_reader.py` recognises which screen the VNC frame shows (AUTO, MANUAL, other), the two lamp colours on AUTO and the electromagnet switch side on MANUAL, using fractions of the frame size. It was built on the saved DTools screenshots in `docs/img/hmi/` (editor views with `####` placeholders, not live frames), so **the lamp meaning and the switch ON look are unverified**: calibrate on the first real frame and cross-check against `%Q`/`%M` bits. Needs Pillow; tests: `tests/test_hmi_reader.py`.
