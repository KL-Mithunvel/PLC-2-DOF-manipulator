# Documentation index

## Our documents (Markdown)
| Document | What it covers |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | How the twin is built: modules, scan cycle, data flow, HTTP API, configuration, tests |
| [USER_GUIDE.md](USER_GUIDE.md) | Running the twin, HMI/panel controls, every UI tab, recording and replay, command-line tools, troubleshooting |
| [HARDWARE.md](HARDWARE.md) | Components, ratios and encoders, I/O, wiring, power, and the differences between the paper and the real program |
| [PLC_Program_and_Communication.md](PLC_Program_and_Communication.md) | Extracted ladder structure, CANopen/PDO map, PLC memory map, Ethernet settings, HMI screens |
| [PLC_FINDINGS.md](PLC_FINDINGS.md) | Defects and quirks found by running the real ladder (with proposed fixes) |
| [SCHEMA.md](SCHEMA.md) | JSON snapshot format shared by every data source |
| [SHADOW.md](SHADOW.md) | Shadow toolkit and shadow engine: alignment, residuals, detectors, ladder conformance and open-loop comparison against a recording |
| [ANALYSIS.md](ANALYSIS.md) | Offline analysis of bags: cycle and step timing, link report, pick repeatability, CSV |
| [FAULTS.md](FAULTS.md) | Fault injection, divergence signatures, classifier and its measured accuracy (synthetic) |
| [BAG_FORMAT.md](BAG_FORMAT.md) | Bag recordings: files, topics, `plc/raw` and `diag` payloads, crash safety |
| [LIVE_PLC_USAGE.md](LIVE_PLC_USAGE.md) | Connecting to the real PLC over Modbus TCP (read-only) and the real HMI over VNC (view-only) |
| [RESEARCH_ANGLES.md](RESEARCH_ANGLES.md) | Every research angle (shadow-and-diverge and others): question, data, method, metric, status |
| [HARDWARE_TEST_PLAN.md](HARDWARE_TEST_PLAN.md) | Checklist and log template for real-hardware sessions (PLC, HMI over VNC, arm) |
| [LIVE_DATA_PLAN.md](LIVE_DATA_PLAN.md) | Plan for live PLC, HMI and per-motor current/voltage sensors |
| [MOCAP_PLAN.md](MOCAP_PLAN.md) | Motion-capture plan, what was built, measured accuracy, camera placement |
| [CAD_IMPORT.md](CAD_IMPORT.md) | Importing CAD bodies (3D models and mass properties) |
| [DECISIONS_2026-11-20.md](DECISIONS_2026-11-20.md) | Record of the scope discussion, decisions and work of 2026-11-20 |
| [MODULAR_BUILD_PLAN.md](MODULAR_BUILD_PLAN.md) | Staged plan: build and test each module alone, then integrate; field-test gates |
| [BUILD_PLAN.md](BUILD_PLAN.md) | Roadmap, what is built and what is blocked on inputs |

## Project background
| Item | Location |
|---|---|
| Technical paper (draft) | `paper/` (PDF and DOCX): "Simulation-Driven Design of a PLC-Controlled 2-DOF Robotic Manipulator" |
| Project website source | `website/index.html` (published as a private artifact; images in `website/img`) |
| Screenshots of the PLC project and HMI | `img/plc`, `img/hmi` (copies in `website/img`) |
| Work envelope drawings | `workspace/` |

## Reference files (`reference/`)
| File | Content |
|---|---|
| `vendor/Kinco_K-Series_PLC_Application_Manual.pdf` | Kinco K-series PLC application manual, 859 pages. Instruction set, memory areas, **Modbus address table (section 10.2.2.3, page 483)**, Ethernet and CANopen |
| `vendor/Kinco_K6S_Series_User_Manual_V000.pdf` | K6S series user manual (hardware, wiring, specifications), 102 pages, first edition 2023-12 |
| `vendor/Kinco_M2070HE_Flyer_2023-04-26.pdf` | M2070HE HMI product flyer |
| `vendor/Kinco_M2070HE_Environment_and_Power_Requirements.pdf` | M2070HE environment and power requirements (1 page) |
| `vendor/M-Series_Robot_Joint_Module_CANopen_Manual_v1.6.pdf` | Joint module (the integrated servo) CANopen manual: objects, PDO, control word, examples |
| `drawings/2DOF_Arm_Electrical_Drawing.pdf` and `..._Corrected.pdf` | Electrical drawing, original and corrected version (5 sheets each) |
| `drawings/2DOF_Arm_Wiring_Details.pdf` | 24-pin signal connector and 8-pin power connector wiring |
| `reports/2DOF_Arm_Ansys_Simulation_Report.pdf` | Arcedus structural simulation report (Ansys 2023 R1), 15 Feb 2026 |

Project backups (KincoBuilder / KincoDTools) and the drive EDS file are in [`../project_files/`](../project_files/README.md).
