# Motion-capture plan (to revisit)

Status: **planned, not started** (discussed 2026-11-19). Builds on the digital twin (`docs/DIGITAL_TWIN.md`).

## Purpose
The drive encoders (object 6064) already give joint angles, so mocap is an *independent* measurement of the real arm to:
- validate the twin's tip path, timing and settling
- see the effect of the 5 kg load
- check assumed geometry (shoulder height, drop link, link lengths)
- overlay the twin on real video

Not possible: verifying the 0.085 mm structural deflection. An RGB camera at ~1 m gives ~0.5 mm/pixel, ~1 mm with good markers.

## Camera count
| Setup | Good for | Weak point |
|---|---|---|
| 1 RGB camera + flat tags | Yaw, pitch and tip; each tag gives full 6-DOF pose from one view | Depth along the lens axis is the weakest; links can hide a tag during the 90 deg sweep |
| 2 cameras, 60-90 deg apart | Triangulated 3D, good depth, robust to occlusion | Needs sync and stereo calibration |
| 3-4 cameras or IR system (OptiTrack/Vicon) | Sub-mm, very robust | Cost; overkill for 2 DOF |

Decision: start with **1 camera**, rigidly mounted, raised and in front so it sees both yaw and pitch. Add a second only if depth error or occlusion is a problem.

## Markers
- **No reflective tape with RGB cameras**: retroreflective tape needs IR cameras with their own IR ring light. Under room light it glares or goes dull; polished aluminium also gives specular glare.
- Use **matte printed AprilTag/ArUco tags** (~4-6 cm): one on the base, one on Link-1, one on top of the part.
- Optional: a coloured dot or LED at the magnet tip for the tip point directly.
- Camera settings: fixed exposure, 1080p at 60 fps, global shutter if possible, diffuse lighting.

## Steps
1. Calibrate the camera (chessboard, OpenCV); fix a world frame on the base tag.
2. Detect tags per frame; compute joint angles and tip position.
3. Synchronise clocks (e.g. magnet LED visible in frame, or log the PLC scan count against frame timestamps).
4. Replay a logged run and overlay the twin on the video; plot error per axis.
5. Feed the error back into the twin's `[assumed]` parameters (`twin/config.py`).
6. Add a second camera if needed.

Implementation idea: a `mocap/` Python module (OpenCV) emitting the same snapshot shape as the twin's `/api/stream`, so real and simulated runs compare directly.

## Open inputs needed
- Camera model: resolution, fps, shutter type
- Target accuracy
- Whether lighting is controllable
- Plus, for the twin itself: real 3-cycle time, real taught counts, CAD masses

---

# Status: pipeline BUILT (2026-11-19), tested on synthetic images only
No real camera or printed tags have been used yet. Everything below was validated against rendered images of the tagged arm.

## What exists
| piece | file |
|---|---|
| marker layout (ids 0 base top, 1 and 3 on the two Link-1 plates, 2 on the part) | `mocap/geometry.py` (`default_layout`: measure your real placements and edit) |
| printable tags | `python -m tools.make_tags --size-mm 60` -> `tags/tag_N.png` (print at 100 %, matte) |
| camera calibration | `python -m mocap.calibrate --images "calib/*.jpg" --pattern 9x6 --square 0.03` |
| tracker (tags -> yaw, pitch, part position) | `mocap/tracker.py` |
| camera placement check | `python -m mocap.placement --camera X Y Z` |
| live source on the bus | `python run_twin.py --mocap 0 --mocap-calib mocap/camera.json` (index or video file) |
| record any source, compare runs (auto time alignment) | Data sources tab; `python -m tools.compare_runs a.jsonl b.jsonl` |
| hardware-free demo | `python -m tools.mocap_demo --video demo.mp4` |

## How it works
The base tag has a known world pose, which gives the camera pose. Each Link-1 tag has a known mounting on the link, so its measured pose gives the link frame in the world and from it yaw and pitch (yaw from the pitch axis, so pitch 0 is well defined). Both plate tags are used when visible. Quality is reported as `resid_mm`: how far the estimated shoulder axis is from its known position.

## Findings
- **Accuracy (synthetic, noise 2 grey levels, 6 cm tags, camera ~1 m away):** 1920x1080 about 0.6 deg RMS (about 4-5 mm at the tip, 0.42 m reach); 1280x720 about 1.0 deg RMS. 4 cm tags are about 2x worse; 8-10 cm tags help only a little and get cut off by the frame at close range. End-to-end demo: 350/350 frames tracked, 0.5 deg RMS, 5 mm tip RMS, a 0.7 s clock offset recovered exactly by the alignment. Real lenses add distortion (calibrate!), motion blur and lighting effects: expect worse until measured.
- **Camera placement matters.** With a tag on each plate, only the anti-diagonal azimuths (135 and 315 deg: behind-left or front-right of the arm when it points along +x at yaw 0) keep a tag facing the camera over the whole 0-90 deg base sweep. Axis-aligned cameras lose the tags edge-on at one end of the sweep, and the 45 deg diagonal loses both at yaw 45. Check with `mocap.placement`.
- Not modelled: the arm body hiding a tag, motion blur, rolling shutter, lens distortion beyond what you calibrate.

## Still needed from you
Camera model/resolution, the tag size you can fit on the plates, lighting, and the real tag mounting positions (edit `default_layout`).
