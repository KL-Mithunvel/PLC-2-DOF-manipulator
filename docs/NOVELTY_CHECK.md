# Novelty check: what the literature search found (2026-11-20)

**Method and limit.** Three web searches (standard mode), read from result snippets only; no paper was read in full. This is a first screen to choose angles, **not** a literature review. Before writing a paper: read the closest papers below in full and search again (IEEE Xplore, Scopus, Google Scholar) with the terms at the end. "No result found" here means "not in the first ten hits of one search", not "does not exist".

## Findings per research angle ([RESEARCH_ANGLES.md](RESEARCH_ANGLES.md))

| Angle | Closest prior art found | Status |
|---|---|---|
| **A1 ladder conformance: run the real ladder program in a second interpreter fed with recorded real inputs and compare every computed bit** | Khan et al. 2018, digital twin of a legacy PLC system: a simulation model compared against specified outputs, conformance fails when they differ ([Chalmers](https://research.chalmers.se/publication/509423/file/509423_Fulltext.pdf)). Formal verification of ladder logic (ESBMC-PLC, [arXiv 2606.15461](https://arxiv.org/pdf/2606.15461)) checks the program, not the running machine. | Conformance of a twin against a legacy PLC exists in concept; **shadow execution of the actual ladder against a live machine over Modbus, with a poll-rate sampling analysis (10 Hz cascades, 25 Hz holds), was not found.** Likely publishable as a method plus the sampling-limit finding. Cite Khan 2018 as the base. |
| **A2 synchronisation / drift between twin and machine** | "Synchronization in Digital Twins for Industrial Control Systems" ([arXiv 2006.03447](https://arxiv.org/pdf/2006.03447)); Chalmers OPC UA drone-factory thesis (real-time sync); practitioner drift metrics (blog, not validated). | Topic is occupied. Differentiator would be a measured lag/drift method (xcorr lag, edge lag, ppm drift) on a real machine with a stated sampling model. Read 2006.03447 first. |
| **B2 sensorless payload estimation from motor current** | Current-based payload estimation is well studied (MDPI Actuators 14(12) 568, disturbance Kalman filter; [arXiv 2409.03369](https://arxiv.org/html/2409.03369v1), payload calibration; [arXiv 2411.01360](https://arxiv.org/pdf/2411.01360v1)). | **Not novel by itself.** Only novel as a finding: which signals a PLC exposes make payload visible or invisible (here: invisible without shoulder current), plus a cheap ESP32/INA226 retrofit that closes it. |
| **Fault injection with a digital twin** | Stäubli TX60 twin with a fault-injection module and GRU classifier (ICINCO 2025, [SciTePress](https://www.scitepress.org/publishedPapers/2025/137056/pdf/index.html)); ESREL 2025 data-driven twin for motor temperature ([RPS](https://rpsonline.com.sg/proceedings/esrel-sra-e2025/pdf/ESREL-SRA-E2025-P9570.pdf)). | Occupied. Our synthetic library (62-75 % leave-one-severity-out) is weak evidence until real faults or real data back it. Do not lead with it. |
| **Open recorded dataset (PLC + HMI frames + arm, with metadata)** | No open PLC + bag-file + twin-drift dataset found; the nearest hit is an unrelated IIoT anomaly dataset (Zenodo 18382029). | **Plausibly a gap**, and cheap: a documented, hash-tied, replayable recording of a real two-axis PLC machine. A dataset/benchmark paper is realistic. |
| **PLC-side attack/tamper detection via twin divergence** | ESBMC-PLC+ finds ladder logic bombs by static formal analysis ([arXiv 2607.08417](https://arxiv.org/pdf/2607.08417)). | Static detection exists; **runtime divergence-based detection of a modified program is a different and open angle** (not yet built: needs a second program version to test). |

## What this means
1. **Strongest candidate:** A1 as "shadow-mode conformance checking of an unmodified legacy PLC over Modbus, and what polling rate it needs". Low-cost, hardware-ready, and our sampling finding is a concrete result. Needs real data to be more than a simulation study.
2. **Second:** the dataset (open recording with metadata and a check tool), which also strengthens the first.
3. **Do not claim:** payload estimation, generic digital-twin fault diagnosis, or generic synchronisation as novel.
4. All performance numbers so far come from a simulated PLC; a paper needs the real-machine run (H1, 2026-11-21 and after).

## Search terms for the proper review
"shadow PLC", "runtime verification" PLC Modbus, "PLC replay" traces, "ladder logic" "digital twin" conformance, "twin-to-machine divergence", "sampling rate" digital twin PLC, "legacy PLC" twin retrofit, "sensorless" payload "servo drive" PLC, ROS bag PLC dataset.
