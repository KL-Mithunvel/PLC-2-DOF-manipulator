# Project files (backups of the real controller / HMI projects)

Binary project archives from the real machine. They are kept as archives; nothing in the code reads them directly (the twin uses `twin/plc/MAIN_MAIN.ilp`, which was exported from the CANopen version below).

| File | What it is |
|---|---|
| `PLC_and_HMI_CANopen_version.rar` | **Current version** (Desktop folder "PLC and HMI"). `PLC/` = KincoBuilder V8.5 project (`PLC.kpr`, program `MAIN` with 39 networks + empty `SBR_0`, `SBR_1`); `HMI  V2/` = KincoDTools 4.5.1 project (`HMI  V2.dpj`, screens in `HMI0/*.whe`, encrypted). The PLC controls both drives over CANopen (PDO map in `docs/PLC_Program_and_Communication.md`). |
| `Program_Backup_VIT_pulse-direction_version.zip` | **Earlier version** ("Program Backup - VIT"). `CANopen.kpr` + `CANopen/MAIN_MAIN.ilp` is a small pulse-train program (PJOG / PABS motion instructions, jog buttons, electromagnet on `%Q0.7`, e-stop on `%I0.0`); `arcedus/` is the matching KincoDTools HMI project (`arcedus.dpj`, `HMI0/`, compiled `tar/HMI0/HMI0.hmi`, package `arcedus.pkgx`). This matches the paper's description of pulse/direction control. |
| `drives/YZ_MOTOR_SN2.eds` | CANopen EDS file of the joint module (vendor "AIM_CANOPEN", product "AIM", created 2022-09-30, baud rates 125 k to 1 M). Use it to configure the slave in KincoBuilder. |

## Opening them
- KincoBuilder opens a project only with File > Open (Ctrl+O), not from the command line. DTools needs administrator approval on this PC.
- Extract an archive into its own new, empty folder first; do not run or import anything from an untrusted archive in place.
- `.rar` needs an unrar-capable tool (7-Zip, WinRAR); Windows' built-in tar cannot read it.

## Which version is on the real machine?
The paper describes pulse/direction control (PLC outputs `%Q0.0`..`%Q0.3`), the current ladder uses CANopen. Confirm in KincoBuilder which one is loaded in the PLC before comparing the twin with the real arm (see `docs/HARDWARE.md`).
