# Real-hardware test plan and log

Prepared 2026-11-20 for the first full session with the real arm. Everything here is read-only from the PC: the PLC reader has no write method and the VNC feed has no input method. The operator uses the real HMI and the physical e-stop.

## Before starting
- [ ] Arm clear of people and objects; e-stop reachable; payload known (kg).
- [ ] PC on the PLC subnet with a static IP that is **not** 192.168.0.252 (PLC reply TTL 255; TTL 128 means you pinged yourself).
- [ ] `ping 192.168.0.252` works; PLC in RUN.
- [ ] HMI address used on 2026-11-20: **192.168.0.253** (DTools lists 192.168.0.100). VNC port ______ (default 5900). Password set in `HMI_VNC_PASSWORD` (never written in files).
- [ ] `pip install -r requirements.txt` (pymodbus, vncdotool).
- [ ] Start: `python run_twin.py --plc 192.168.0.252 --hmi-vnc 192.168.0.253`; open `http://127.0.0.1:8765/?ghost=plc`. Check the **Data sources -> Pipeline diagnostics** table: fast group about 10 Hz, errors 0, data age under 1 s.
- [ ] To record a run: type a run name and notes in **Session recording** and press **Record session** (or start with `--record R3 --notes "..." --payload-kg 5`). One bag file per run in `logs/`; check it afterwards with `python -m bag info logs/R3.mcap` (topics `twin/state`, `plc/decoded`, `plc/raw`, `diag`, `events`, `hmi/frame` should all be present).

## Checks (record the value seen on the HMI next to what the twin shows)
1. **Verify the mapping.** Type distinctive values on the HMI (speeds `VD2020`, `VD2030`; cycle target `VW2036`); run `python -m live.scan --host 192.168.0.252 --know VD2020=<v> --know VW2036=<v>`. Expect V offset 100 (already confirmed).
2. **M area and encoders.** While the arm is at rest and then moving: `%MD600` (base), `%VD1044` (shoulder) change; check sign and scale against the visible arm angle. Confirm M-area offset 320 with a known bit (for example the magnet switch or a teach flag).
3. **Counters.** `%VW2500` (minutes), `%VW2510` (seconds), `%VW2400` (cycle number) during a run.
4. **Taught points.** Table beside the HMI view: does the arm sit on the taught point to within a few mm at INIT, pick, drop?
5. **VNC.** Real HMI picture appears; note frame age and any refusal of a second client.

## Runs to record (use Data sources tab -> Record; name files with date and run number)
| Run | What | For angle |
|---|---|---|
| R1 | Idle, 60 s, no motion | noise floor, B1 |
| R2 | Manual jog each joint, both directions | A3, A5 |
| R3 | Auto, 3 cycles, no payload, default speeds | A2, A3, A6 |
| R4 | Auto, 3 cycles, known payload (record mass) | A3, B2 |
| R5 | Auto at 2 other speed set-points | A3, B3 |
| R6 | E-stop at 3 different phases (arm unloaded), then RESET | A4 |
| R7 | RESET during/after run, power cycle recovery | A2, A4 |
| R8 | Real 3-cycle time with stopwatch (calibration input) | A6 |
Repeat R3 at least 5 times for repeatability statistics.

## Log template (copy per session)
```
Date/time:            Operator:
PC IP:                PLC IP:        HMI IP/port:
pymodbus version:     git commit:    PLC program (name/date):
Poll rate (Hz):       Payload (kg):  Speed set-points (base/shoulder):
Run | file name | start (wall clock) | notes / anomalies
```
Also keep: screenshots of the GUI at each run, stopwatch times, and anything surprising (disconnects, refused VNC, wrong scale).

## Do not
- Do not write to the PLC from Python. Do not point a second Modbus client at the PLC while the HMI and the twin already hold connections (the PLC allows only a few).
- Do not leave a password in a command history, doc or commit.
- Do not trust the first result: the mapping beyond the V area is still unverified (see [LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md)).
