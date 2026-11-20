"""The standalone twin must run with no hardware modules and no optional packages."""
import os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = (
    "import sys\n"
    "sys.path.insert(0, sys.argv[1])\n"
    "import twin.server, twin.sim\n"
    "bad = [m for m in sys.modules if m.split('.')[0] in ('live', 'mocap', 'pymodbus', 'vncdotool', 'cv2', 'serial')]\n"
    "print('BAD', bad) if bad else print('OK')\n"
)


class Standalone(unittest.TestCase):
    def test_no_hardware_imports(self):
        out = subprocess.run([sys.executable, "-c", CODE, ROOT], capture_output=True, text=True, cwd=ROOT, timeout=60)
        self.assertEqual(out.stdout.strip(), "OK", out.stdout + out.stderr)


if __name__ == "__main__":
    unittest.main()
