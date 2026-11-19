"""Run every test: python run_tests.py   (Python unit tests + node scene smoke test if node is available)."""
import shutil
import subprocess
import sys
import unittest

suite = unittest.defaultTestLoader.discover("tests", pattern="test_*.py")
ok = unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful()
if shutil.which("node"):
    for f in ("tests/test_arm3d.mjs",):
        print("node", f)
        ok &= subprocess.run(["node", "--import", "./tests/node_register.mjs", f]).returncode == 0
else:
    print("node not found: skipping JavaScript tests")
sys.exit(0 if ok else 1)
