"""Read what the real HMI shows from a picture of it (a VNC frame, ``live/hmi_vnc.py``): which screen is up, the colour of the two lamps
on the AUTO screen, and the side the electromagnet switch is on the MANUAL screen.

Developed on the six screenshots in ``docs/img/hmi/`` (which are DTools editor views, with ``####`` placeholders and tag labels, NOT live
runtime frames). Coordinates are fractions of the frame size, so any scale works. Needs Pillow (optional, not in the twin core).

Honest limits: the screen is recognised from background colour (a coarse fingerprint); the lamp colour is reported as a colour name, what
red/green MEAN on this HMI is unverified until it is seen on the live panel (compare against %Q / %M bits in the shadow tools); the
switch side is a luminance heuristic. Re-calibrate the fractions on the first real VNC frame (``python -m live.hmi_reader FRAME.png``).
"""
from __future__ import annotations

import sys

# screen fingerprints: colour sampled at fractions of the frame -> (name)
SCREENS = {
    "auto": ((0.88, 0.50), (127, 255, 212)),        # mint background
    "manual": ((0.88, 0.50), (230, 230, 250)),      # lavender panel
}
LAMPS = {"base": (0.324, 0.940), "shoulder": (0.640, 0.945)}          # AUTO screen, BL0 / BL1
SWITCH_ROW = 0.793                                                  # MANUAL screen, SW0 centre row
SWITCH_X = (0.575, 0.656)                                           # track span


def _close(a, b, tol=8) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b))


def colour_name(rgb) -> str:
    r, g, b = rgb
    if max(rgb) < 60:
        return "black"
    if min(rgb) > 200:
        return "white"
    if max(rgb) - min(rgb) < 30:
        return "grey"
    if r > 180 and g < 130 and b < 130:
        return "red"
    if g > 150 and r < 150 and b < 150:
        return "green"
    if r > 180 and g > 150 and b < 120:
        return "yellow"
    if b > 150 and r < 130:
        return "blue"
    return "other"


def _px(im, fx: float, fy: float):
    w, h = im.size
    return im.getpixel((min(w - 1, int(fx * w)), min(h - 1, int(fy * h))))


def read_frame(im) -> dict:
    """``im``: a PIL image (any mode). Returns {screen, lamps?, magnet_switch?, confidence}."""
    im = im.convert("RGB")
    out: dict = {"screen": "unknown", "size": im.size}
    for name, (pos, col) in SCREENS.items():
        if _close(_px(im, *pos), col):
            out["screen"] = name
            break
    if out["screen"] == "auto":
        out["lamps"] = {k: colour_name(_px(im, *p)) for k, p in LAMPS.items()}
    if out["screen"] == "manual":
        y = SWITCH_ROW
        xs = [SWITCH_X[0] + (SWITCH_X[1] - SWITCH_X[0]) * i / 20 for i in range(21)]
        lum = [sum(_px(im, x, y)) / 3 for x in xs]
        # in the saved MANUAL screenshot (switch off) the knob is the darker grey (161) at the left end of a lighter track (185)
        left = [v for v in lum[:10] if v > 120]          # drop the dark outline pixels
        right = [v for v in lum[11:] if v > 120]
        out["magnet_switch"] = "left" if sum(left) / max(1, len(left)) < sum(right) / max(1, len(right)) else "right"
        out["magnet_switch_note"] = "heuristic: calibrate on the live panel"
    return out


def main(argv: list[str]) -> int:
    from PIL import Image
    for p in argv:
        print(p, read_frame(Image.open(p)))
    return 0 if argv else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
