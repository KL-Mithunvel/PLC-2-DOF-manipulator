# DC power meters for the two motors: plan

Written 2026-11-20. Nothing has been bought, wired or tested. Prices are from search-result snippets of Indian shops on that date (the robu.in pages could not be opened directly); check the live page before ordering. Related: [LIVE_DATA_PLAN.md](LIVE_DATA_PLAN.md) (sensor section), `firmware/motor_sensors/` (untested ESP32 + INA226 sketch), [FAULTS.md](FAULTS.md) (why this matters), [HARDWARE.md](HARDWARE.md).

## Why
- The PLC exposes only the **base** motor current (`%VW1022`, object 6078); the shoulder current, which carries the load, is not in the PDO map.
- The fault study ([FAULTS.md](FAULTS.md)) found a payload increase of 3 kg **invisible** to every signal the PLC exposes. A shoulder power/current measurement is what closes that gap (sensorless payload estimation, research angle B2).
- It also calibrates the twin's assumed torque constant, gear efficiency and friction, gives energy per cycle (wear and efficiency trend, A6), and settles the open question that the motors are rated 36 V but fed 24 V ([HARDWARE.md](HARDWARE.md)).

## What to measure
Per motor: DC bus voltage, current, power, energy, on the **24 V supply line feeding that motor's drive** (the integrated servo is PWM-fed from the 24 V rail). Two independent channels: base and shoulder. The shunt goes in the supply line only, never in CAN or signal wiring, with the grounds common and a fuse in the supply.

## Size the shunt first (do this before buying)
The meters below come with shunts of 50 A and up. If the motors draw only a few amps, a 50 A shunt gives coarse resolution (a few mV across the shunt) and about 1 % accuracy of full scale means a large error at small currents. **Tomorrow, during the hardware session, log `%VW1022` (base current in mA) and read the drive's rated and peak current from the M-series manual**, then decide:
- peak current above about 10 A on both motors: the PZEM route below is a good fit;
- peak current of a few amps: prefer the INA226 route (10 A range, 100x finer) or ask for a 10-20 A shunt.
The CAN object 6078 current of the shoulder drive can also be added to the PDO map by editing the PLC program, but that changes the machine's program (see PLC integration).

## Decision (2026-11-20): ESP32 + INA226 is the route
The ESP32 + INA226 logger is the preferred route (fast sampling, cheap, already has a host side). It is built and tested in simulation: see [FIRMWARE.md](FIRMWARE.md) (`python run_twin.py --sensors esp-sim`), including the fixes found in the sketch. **Buying warning: most cheap INA226 breakouts carry a 0.1 ohm shunt (full scale 0.8 A); the motors draw several amps, so the shunt must be replaced or a 20 A board bought, and `SHUNT_OHMS` in the sketch set to the fitted value. The CJMCU-226 module linked below is the standard 0.1 ohm design unless the listing says otherwise: check before ordering.** The PZEM-017 route below stays as the PLC-compatible alternative and a slow cross-check.

## Two routes (they complement each other)

### Route A: Modbus RTU DC power meters (PLC-compatible, slow)
| Item | Detail | Price (as listed) |
|---|---|---|
| **2 x Peacefair PZEM-017 with shunt** | DC 0.05-300 V, 0.02-300 A, power and energy, RS485 Modbus RTU, 1 % accuracy; [Robu: module + 50 A shunt](https://st.robu.in/product/pzem-017-module50a-shunt-dc-meter), in stock | Rs 599 each (incl. GST) |
| alternative: PZEM-051 | DC 6.5-100 V, 0-100 A, [Robu](https://st.robu.in/product/pzem-051); interface not stated in the snippet: confirm RS485 before buying | not captured |
| USB to RS485 adapter (for the PC and for setting addresses) | [Robocraze CH340](https://robocraze.com/products/usb-ch340-to-rs485-converter-adapter-module) or [FTDI FT232 + SN75176](https://robocraze.com/products/usb-2-0-to-ttl-rs485-serial-converter-adapter-ftdi-module-ft232frl-sn75176) | Rs 89 / Rs 139 |
| 120 ohm terminator, shielded twisted pair, DIN-rail or fused supply taps | | small |
- Both meters share one RS485 pair with **different slave addresses**: set one of them to address 2 first from the PC (adapter plus a Modbus tool or a short Python script).
- **Update rate is slow** (plan for about 1 Hz and verify; the listings do not state it): good for energy per cycle, average power, calibration, and a sanity check of the supply voltage; **not** for the instantaneous power during acceleration.
- A seller note says the PZEM-017 communication side needs its own supply (unlike the PZEM-016): read the datasheet wiring before powering.
- Register map, to be **verified against the Peacefair datasheet before coding** (from memory, not checked): input registers 0x0000 voltage (0.01 V), 0x0001 current (0.01 A), 0x0002-0x0003 power (0.1 W), 0x0004-0x0005 energy (Wh); holding registers: alarm thresholds, slave address, current range (must match the shunt: 50/100/200/300 A).

### Route B: fast sampling (ESP32 + INA226), for dynamic power
| Item | Price (as listed) |
|---|---|
| 2 x INA226 module (36 V, I2C), e.g. [Vishaworld CJMCU-226](https://vishaworld.com/products/cjmcu-226-ina226-current-sensor-module) | Rs 250 each |
| ESP32 dev board | not priced here |
| low-ohmic shunts or the module's own 0.1 ohm / 2 mohm parts, wiring, fuse | small |
- The existing sketch (`firmware/motor_sensors/motor_sensors.ino`) samples both INA226 at 100 Hz and sends UDP/serial lines that `live/sensors.py` already reads (`python run_twin.py --sensors udp:9100`). **It has never been run on hardware.** INA226 bus limit is 36 V: fine for the 24 V rail, not for a 36 V supply.
- This is the route that makes acceleration peaks and the shoulder gravity load visible.

### Recommendation
1. Tomorrow: log `%VW1022` and note the motors' rated current; photograph the supply wiring of the two drives.
2. Buy **2 x PZEM-017 with shunts (about Rs 1,200) + one USB-RS485 adapter (about Rs 100-140)**. This meets "PLC-compatible, one meter per motor" and gives a first independent check.
3. If currents turn out to be small, or you want the dynamic power for the paper, add Route B (about Rs 500-1,000 plus an ESP32).

## PLC integration (optional, decide later)
- The Kinco K615S has two RS485 ports; the project's current settings are Port1 and Port2 at 9600 8N1, station 1, **Modbus master off** ([PLC_Program_and_Communication.md](PLC_Program_and_Communication.md)). Reading the meters from the PLC would mean enabling Modbus RTU master on one port in KincoBuilder and adding Modbus-read instructions (see the Kinco K-series manual, `reference/vendor/`) to the ladder.
- **Check the serial format**: the PZEM meters may use 2 stop bits (to be verified in the datasheet), the PLC port is set to 8N1 and must be able to match.
- This changes the machine's program: do it only on a copy of the project, keep the known-good backup (`project_files/`), and test with the arm unpowered. The HMI link is Modbus TCP over Ethernet and is not affected by an RS485 port.
- **Simpler and safer first step: read the meters from the PC** (USB-RS485, Python), so the PLC program stays untouched. Everything in the twin (recording, shadow tab, analysis) then sees the power data.

## Software: built 2026-11-20, with simulated meters only
Everything below runs and is tested **without hardware**; the PZEM register map is still unverified (`live/pzem.py: REGISTER_MAP_VERIFIED = False`) and no real meter or RS485 adapter has been used.
| Piece | File | What it does |
|---|---|---|
| Modbus RTU master | `live/rtu.py` | CRC16, retries, timeout / CRC / exception errors; **read-only unless `allow_write=True`** (meter setup only) |
| PZEM-017 driver | `live/pzem.py` | read V, A, W, Wh; setup helpers (address, current range, energy reset) |
| Simulated meter and bus | `live/pzem.py` | `SimPzem017` (0.01 V / 0.01 A / 0.1 W / 1 Wh quantisation, energy, address, range, gain error) and `SimBus` (drop, corrupt, delay, cut cable) |
| Live source | `live/powermeter.py` | polls both meters, diagnostics, raw records, connection events, software energy integral; sits in the same `sensors` slot as the ESP32 feed, so the GUI (measured current, voltage, power in the axis panels and scope), `tools/fit_motor_params.py`, the recorder and the shadow tools work unchanged |
| Twin-driven simulation | `live/powermeter.py: SimTwinFeed` | torque -> current -> supply sag -> simulated meters |
Run: `python run_twin.py --power sim` (no hardware), or later `python run_twin.py --power COM5@9600 --power-slaves base=1,shoulder=2`. Recorded topics: `sensors` (snapshot with `mA`, `mV`, `W`, `meter_W`, `Wh`, `Wh_sw` per motor), `sensors/raw` (the 8 registers of every read with send/receive times, [BAG_FORMAT.md](BAG_FORMAT.md)), `diag` (rate, errors, reconnects, request counts), `events`. Tests: `tests/test_rtu_pzem.py`, `tests/test_powermeter.py`.

### Findings from building it (so the real meters are not a surprise)
- **The meter's energy counter counts whole Wh**: one 30 s cycle at 20 W is 0.17 Wh and reads 0. Energy per cycle must be integrated from the 0.1 W power readings (`Wh_sw`, trapezoid over the time between polls; gaps over 5 s are not bridged).
- **Calibrating `kt` from a meter needs averaged torque**: the twin's holding torque chatters from one scan to the next, and a meter value (an average) regressed on an instantaneous torque gives a badly biased `kt` (0.19 instead of 0.10 in the first attempt). The simulated meter now averages over its update period, the comparison uses the torque averaged over the same interval, and `tools.fit_motor_params` has a `--smooth N` option for slow meters. With that the torque constant is recovered within 10 %.
- **A loaded shoulder draws measurably more power** (8 kg against 2 kg, simulated): this is the signal that the PLC-exposed data could not show ([FAULTS.md](FAULTS.md)). Whether the real one separates equally well depends on the real shunt range and meter noise.

## Software still to build once real meters exist
1. Verify the register map and serial format on a real meter; flip `REGISTER_MAP_VERIFIED`; add the real response times to the simulated bus.
2. `shadow`: add measured power to the open-mode comparison and extend the fault library with it (re-measure the payload case); `analysis`: energy per cycle and power per phase from `Wh_sw`.
3. A meter setup command (set address 2 on one meter, set the shunt range) as an explicit, confirm-first tool.
4. PLC-side reading only if wanted (see PLC integration above).

(The list that was here before the build, for reference:)
1. `live/powermeter.py`: Modbus RTU reader for N meters (pymodbus serial), read-only except the one-time setup helper (address and current range, behind an explicit flag); emits the same `sensors` snapshot as `live/sensors.py` (mA, mV per channel) plus power and energy, timestamps, diagnostics (rate, errors) like the PLC reader; recorded into the bag (`sensors` topic).
2. Tests without hardware: a fake RTU device (in-process) with register values, address change, CRC errors, timeouts, reconnect.
3. `shadow`: add measured power to the open-mode comparison (twin predicts electrical power from torque, speed, `kt`, efficiency); the residual is the new evidence for payload and friction; extend the fault library (`FAULTS.md`) and re-measure the payload case.
4. `analysis`: energy per cycle, peak and mean power per phase, trend over days.
5. Calibration tool: fit `kt`, efficiency and friction from logged power and motion (`tools/fit_motor_params.py` already fits from logs).

## Open questions
- Rated and peak current of the M8025 and M8010 at 24 V (manual), and whether the drives are fed from separate supplies.
- Where the supply for each drive can be tapped for a shunt, and whether the two drives share a protection device.
- Sample rate you want in the paper (1 Hz energy-per-cycle only, or full dynamic power).
