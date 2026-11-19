# Hardware reference

Compiled from the paper, the electrical drawings, the Kinco manuals (`reference/`), the PLC program and the CANopen manual. Items marked **[check]** are not confirmed on the real machine.

## Components
| Item | Model | Notes |
|---|---|---|
| PLC | Kinco K615S-16DT | 24 VDC, 8 DI (sink/source), 8 DO (PNP), 3x200 kHz + 1x10 kHz pulse outputs, 1 Ethernet, 2 RS485, 1 CAN (CANopen master), 8k instructions, 20 kB V+M data |
| HMI | Kinco M2070HE-WIFI | 7", 1024x600, ARM Cortex-A7, 10.8-28 VDC (4.2 W at 24 V), Ethernet and Wi-Fi, 192x138 mm cut-out, programmed in KincoDTools |
| Base motor | M8025(B)E25B101L | integrated harmonic-drive servo, 101:1; vendor rating about 85 N.m continuous / 178 N.m peak (at 80:1); top speed about 15 rpm at the output; "(B)" = holding brake |
| Shoulder motor | M8010(B)E17B81L | integrated servo, 81:1; about 35 N.m continuous / 56 N.m peak; output speed up to about 18 rpm |
| Electromagnet | 24 V, switched by a relay from `%Q0.7` | end effector, holds the 5 kg ferrous part |
| Supply | 3-phase + N, 440/230 V, 50 Hz -> key switch + SMPS -> 24 VDC | PLC, HMI, both servos, magnet. The paper notes the servos are rated 36 V but fed 24 V **[check]** |

## Encoder, units and gear ratios
- Integrated 15-bit absolute encoder, 32768 counts per motor revolution (CANopen manual), multi-turn with battery.
- CANopen position unit is taken as **motor encoder counts** (before the reducer) and speed as **motor rpm**. Counts per output revolution = 32768 x ratio: base 3,309,568, shoulder 2,654,208. **[check]**
- Evidence: the shoulder jog range in the ladder (-57,646,473 to -58,321,097 = 674,624 counts) is 91.5 deg of output rotation, i.e. home = link vertical, lower limit = horizontal; HMI speed limits of 1500 / 2000 rpm are motor-side.
- Home positions in the ladder: base about -750,000 counts (angle 0), shoulder -57,646,473 (angle 0, link vertical up).

## CANopen (PLC is master, node 127, 1000 kbit/s)
Slave 1 = base, slave 2 = shoulder, heartbeat 500 ms, 3 s power-on delay. PDO map and PLC addresses: [PLC_Program_and_Communication.md](PLC_Program_and_Communication.md). Drive object reference: `reference/vendor/M-Series_Robot_Joint_Module_CANopen_Manual_v1.6.pdf`; EDS file: `project_files/drives/YZ_MOTOR_SN2.eds`. In position mode the drive's speed limit is object 6081 and acceleration 6083; the ladder maps 60FF (target velocity) but never writes the operating mode 6060 **[check]**.

## Ethernet
| Device | Address |
|---|---|
| PLC | 192.168.0.252 / 255.255.255.0, gateway 192.168.0.1, Modbus TCP port 502 |
| HMI | 192.168.0.100 |
The HMI reads and writes PLC memory over Modbus TCP ("Kinco PLC Ethernet (TCP)", station 1). Modbus address map for the PLC: `live/modbus_map.py` (from the Kinco manual, section 10.2.2.3).

## Digital I/O in the current program
| Address | Function |
|---|---|
| `%I0.0` | enable / E-stop chain (low stops everything) |
| `%I0.1` | reset / homing push button |
| `%Q0.7` | electromagnet relay |

## Paper vs program: two control schemes
The paper (and the electrical drawing, wiring details and the older program in `project_files/Program_Backup_VIT_pulse-direction_version.zip`) describe **pulse/direction control**: base pulse `%Q0.0` / direction `%Q0.2`, shoulder pulse `%Q0.1` / direction `%Q0.3`, reset output `%Q0.4`, buzzer `%Q0.5`, drive alarms on `%I0.2` / `%I0.3`, shoulder zero on `%I0.4`. The **current** program (`project_files/PLC_and_HMI_CANopen_version.rar`) drives both axes over CANopen and does not use those outputs. Confirm which program is loaded in the PLC **[check]**.

## Wiring (`reference/drawings/2DOF_Arm_Wiring_Details.pdf`)
24-pin signal connector: base drive PU+/PU-/DIR+/DIR-/WR+ (alarm) / COM / CANL / CANH, shoulder drive PU+/PU-/DIR+/DIR-/WR+ / ZO (multi-turn zero) / CANL / CANH. 8-pin power connector: 24 V and 0 V to base motor, shoulder motor and electromagnet. Note the CAN bus needs 120 ohm termination at the far end (the drives have none inside).

## Mechanics and structural study
Reach 420 mm from the shoulder axis to point P (Link-2 axis); plan-view envelope diameter 843 mm; shoulder arc 180 deg. Link-1 and Link-2 are aluminium 6061, base/joint/part are mild steel AISI 1010. Link masses 2.0 kg and 1.5 kg are **assumed** in the paper. Ansys 2023 R1 results: maximum deflection 0.085 mm (Link-2 tip, pick pose), peak stress 8.81 MPa (joint), minimum FOS 4.63 (joint, holding pose), holding gravity torque about 30.9 N.m at full horizontal reach with 5 kg. The paper itself notes the joint FOS (9.79 / 4.63) does not follow from its stress plot (8.81 MPa would give FOS about 28, capped at 15). Full report: `reference/reports/2DOF_Arm_Ansys_Simulation_Report.pdf`.

## Open points **[check]**
1. Which PLC program (pulse/direction or CANopen) is on the machine.
2. Supply voltage: 24 V used, 36 V rated.
3. Position unit (motor counts assumed) and the drives' stored operating mode and profile speed.
4. Time base of the PLC timers (10 ms assumed) and the `%SM0.3` clock period (1 s assumed).
