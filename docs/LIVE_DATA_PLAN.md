# Live data plan: PLC feed, HMI, motor sensors, common data bus

Status: **planned, not started** (discussed 2026-11-19). Related: `docs/DIGITAL_TWIN.md`, `docs/MOCAP_PLAN.md`.

## Goal
Four data sources on one bus so everything can be compared and built on:
1. the digital twin (simulation)
2. mocap (real arm pose from camera)
3. live PLC memory (real controller state)
4. per-motor current and voltage sensors (real electrical data)

## Reading the PLC from Python
| Option | Verdict |
|---|---|
| **Modbus TCP** via `pymodbus` | **Use this.** PLC is 192.168.0.252, port 502; the HMI already uses it ("Kinco PLC Ethernet (TCP)", station 1). Reads coils (M bits, Q), discrete inputs, holding registers (V/M words). |
| Modbus RTU over RS485 (`minimalmodbus`/`pymodbus`) | Only if wired serially (PLC Port1/Port2 are RS485, 9600 8N1). Ethernet is simpler. |
| Profibus | Not applicable: the K615S has Ethernet, RS485 and CAN only. |
| CANopen (`python-can`) | The bus belongs to the PLC (master, node 127) and the two drives. Do not add a PC to it. Drive data is already in PLC memory (`%MD600`, `%VD1044`, ...). |
| HMI as a data source | No. The HMI is itself a Modbus client of the PLC; its widgets show PLC memory. Its internal registers are not exposed. |

### Kinco address mapping
Taken from the Kinco K-series manual, section 10.2.2.3 (page 483): coils/discrete `Q` 0..255, `I` 0..255, `M` 320..8511; registers `V` from 100 (`VW0` = 100, `VW2` = 101). The M area is **bit-only**, so M words (e.g. `%MD600`) are read as coils. Details and verification steps: [LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md). Still to be confirmed on the real PLC by reading a value shown on the HMI.

### Cautions
- **Read-only.** The reader must never write to the PLC.
- The PLC allows only a few TCP connections and the HMI already holds one. One reader polling at 10-20 Hz is fine.
- Prerequisite: the PC is on 192.168.0.x and can reach 192.168.0.252 (to be confirmed).

## Proposed design
1. `live/` module with a `PlcReader` (pymodbus) polling a configured list of names (`VD1044`, `M30.1`, ...) and emitting the same snapshot shape as the twin's `/api/stream`.
2. The twin also exposes its memory as a **Modbus TCP server** with the same mapping, so the reader can be developed and tested offline, and a real client could talk to the twin.
3. Common data bus (JSON snapshots over SSE): sources `sim`, `plc`, `mocap`, `sensors`. The three.js arm gets a **shadow mode** driven by the real encoder counts, shown next to the simulated arm with an error overlay.

## Motor current and voltage sensors
Separate sensor per motor (stated 2026-11-19). Purpose:
- calibrate the twin's assumed `kt`, gear efficiency and friction (`twin/config.py`)
- cross-check drive-reported current (object 6078; currently mapped for node 1 only, `%VW1022`)
- compute electrical power against the mechanical load from the twin
- settle the open question that the motors are rated 36 V but fed 24 V (paper section 5.3)

Hardware notes: the drives are PWM-fed from the 24 V rail. Measure DC supply current per motor with a shunt and fast ADC (INA226/INA228) or a Hall sensor. Log at kHz-level on a small MCU (ESP32, Arduino or RPi) and forward to the PC over serial/UDP/MQTT with timestamps. The PLC scan (ms) is too slow for this.

## Open inputs needed
- PC network reachability to 192.168.0.252
- Confirmation that the manual's address table matches the real PLC (read one HMI value)
- Sensor choice and where the MCU will live
