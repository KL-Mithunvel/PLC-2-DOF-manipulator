"""Headless-browser smoke test: loads the UI in Edge/Chrome, checks the DOM got built and that no JavaScript error was logged.
Skipped automatically when no browser is installed. Never kills browser processes: each run is a fresh headless instance."""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.server import Hub, make_handler
from twin.sim import Twin

CANDIDATES = [os.environ.get("BROWSER", ""), r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              shutil.which("msedge") or "", shutil.which("google-chrome") or "", shutil.which("chromium") or ""]
BROWSER = next((c for c in CANDIDATES if c and os.path.exists(c)), None)
BAD = ("Uncaught", "SyntaxError", "Failed to load module", "TypeError", "ReferenceError", "is not defined", "Failed to fetch dynamically")


@unittest.skipUnless(BROWSER, "no Chromium-based browser found")
class UiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.hub = Hub(Twin(), cls.tmp.name)
        for _ in range(1500):
            cls.hub.twin.tick()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.hub))
        cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.srv.server_address[1]}/"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.tmp.cleanup()

    def load(self, query):
        prof = tempfile.mkdtemp()
        r = subprocess.run([BROWSER, "--headless=new", "--disable-gpu", "--enable-unsafe-swiftshader", f"--user-data-dir={prof}",
                            "--enable-logging=stderr", "--v=0", "--virtual-time-budget=6000", "--dump-dom", self.url + query],
                           capture_output=True, text=True, timeout=90, encoding="utf-8", errors="ignore")
        shutil.rmtree(prof, ignore_errors=True)
        errs = [l for l in r.stderr.splitlines() if "CONSOLE" in l and any(b in l for b in BAD)]
        return r.stdout, errs

    def test_main_page_builds_everything(self):
        dom, errs = self.load("?snap")
        self.assertEqual(errs, [])
        self.assertGreaterEqual(dom.count('class="net'), 39)                 # all ladder networks rendered
        for needle in ("Wi-Fi / network (system)", "NUMBER OF CYCLE", "Data sources", "Structural load", 'id="cvIso"'):
            self.assertIn(needle, dom)

    def test_demo_mode_loads_without_errors(self):
        dom, errs = self.load("?snap&demo=1")      # ?snap: no live stream, so the headless dump can finish
        self.assertEqual(errs, [])
        self.assertIn("demoBadge", dom)                                       # the badge is created
        self.assertIn('id="viewBar"', dom)                                    # 3D navigation bar and ladder controls are present
        self.assertIn('id="selJump"', dom)

    def test_tabs_load_without_errors(self):
        for tab, needle in (("struct", "reaction bending moment"), ("cfg", "timer_base_ms"), ("src", "Recorder"), ("mem", "Bit memory"), ("can", "COB-ID")):
            dom, errs = self.load(f"?snap&tab={tab}")
            self.assertEqual(errs, [], tab)
            if tab in ("cfg", "src", "mem", "can"):
                self.assertIn(needle, dom, tab)


if __name__ == "__main__":
    unittest.main()
