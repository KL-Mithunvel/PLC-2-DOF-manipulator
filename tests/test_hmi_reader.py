"""HMI screen reader on the saved DTools screenshots (editor views, not live frames). Needs Pillow; skipped without it."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:
    from PIL import Image
except ImportError:
    Image = None
from live.hmi_reader import read_frame

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "img", "hmi")


@unittest.skipIf(Image is None, "Pillow not installed")
class HmiReader(unittest.TestCase):
    def read(self, n):
        return read_frame(Image.open(os.path.join(D, n)))

    def test_screens(self):
        self.assertEqual(self.read("hmi_auto.png")["screen"], "auto")
        self.assertEqual(self.read("hmi_manual.png")["screen"], "manual")
        for n in ("hmi_settings.png", "hmi_wifi_network.png", "hmi_login.png"):
            self.assertEqual(self.read(n)["screen"], "unknown", n)

    def test_auto_lamps_and_scale(self):
        r = self.read("hmi_auto.png")
        self.assertEqual(r["lamps"], {"base": "red", "shoulder": "red"})
        small = read_frame(Image.open(os.path.join(D, "hmi_auto.png")).resize((514, 302), Image.NEAREST))
        self.assertEqual(small["screen"], "auto")

    def test_switch_side_flips(self):
        im = Image.open(os.path.join(D, "hmi_manual.png")).convert("RGB")
        self.assertEqual(read_frame(im)["magnet_switch"], "left")
        w, h = im.size
        y = int(0.793 * h)
        flipped = im.copy()
        x0, x1 = int(0.575 * w), int(0.656 * w)
        for x in range(x0, x1):
            for dy in range(-6, 7):
                flipped.putpixel((x0 + x1 - x, y + dy), im.getpixel((x, y + dy)))
        self.assertEqual(read_frame(flipped)["magnet_switch"], "right")


if __name__ == "__main__":
    unittest.main()
