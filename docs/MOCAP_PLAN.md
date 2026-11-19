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
