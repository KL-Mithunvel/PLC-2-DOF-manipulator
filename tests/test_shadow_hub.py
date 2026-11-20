"""The GUI's Shadow tab: server-side job on a recorded bag, the /api/shadow payload, error handling."""
import json, os, sys, tempfile, threading, time, unittest
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shadow.synth import estop, record_session, standard_run, write_bag
from twin.config import load_config
from twin.server import Hub, make_handler
from twin.sim import Twin
import copy


def wait_done(hub, timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if hub.shadow.get("state") in ("done", "error"):
            return hub.shadow
        time.sleep(0.1)
    raise AssertionError("shadow run did not finish")


class ShadowJob(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cfg = copy.deepcopy(load_config()); cfg.fix_estop_magnet_latch = True
        recs = record_session(Twin(cfg), 25.0, standard_run(4.0) + [(7.2, estop(True)), (9.5, estop(False))], fast_hz=25)
        cls.bag = os.path.basename(write_bag(recs, os.path.join(cls.tmp.name, "latch"), fmt="jsonl"))
        cls.hub = Hub(Twin(), cls.tmp.name)
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(cls.hub)); cls.srv.daemon_threads = True
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.tmp.cleanup()

    def post(self, o):
        r = urlopen(Request(self.base + "/api/cmd", json.dumps(o).encode(), {"Content-Type": "application/json"}), timeout=10)
        return json.loads(r.read())

    def get(self, p):
        return json.loads(urlopen(self.base + p, timeout=10).read())

    def test_run_finishes_and_payload_has_traces_spans_and_text(self):
        self.assertTrue(self.post({"type": "shadow_run", "file": self.bag, "mode": "ladder", "resync": False, "warmup": 3})["ok"])
        res = wait_done(self.hub)
        self.assertEqual(res["state"], "done", res.get("error"))
        api = self.get("/api/shadow")
        self.assertEqual(api["mode"], "ladder"); self.assertIn("shadow report", api["text"])
        self.assertIn("M30.6", api["traces"]); self.assertIn("M30.6", api["spans"])                   # the seeded fault is visible
        tr = api["traces"]["M30.6"]
        self.assertEqual(len(tr["t"]), len(tr["real"])); self.assertEqual(len(tr["t"]), len(tr["twin"]))
        self.assertLessEqual(len(tr["t"]), 800)                                                       # downsampled for the browser
        self.assertNotIn("M32.1", api["traces"])                                                      # signals that never did anything are left out
        self.assertEqual(api["report"]["first_divergence"]["signal"], "M30.6")
        st = self.hub.status()["shadow"]; self.assertEqual(st["state"], "done"); self.assertNotIn("traces", st)    # the 25 Hz stream stays small

    def test_a_fresh_hub_is_idle(self):
        h = Hub(Twin(), self.tmp.name)
        self.assertEqual(h.shadow, {"state": "idle"}); self.assertEqual(h.status()["shadow"]["state"], "idle")

    def test_open_mode_payload_has_angle_traces(self):
        self.assertTrue(self.post({"type": "shadow_run", "file": self.bag, "mode": "open", "warmup": 3})["ok"])
        res = wait_done(self.hub)
        self.assertEqual(res["state"], "done", res.get("error"))
        self.assertIn("base_deg", res["traces"]); self.assertEqual(res["traces"]["base_deg"]["kind"], "angle")

    def test_errors_are_reported_not_raised(self):
        self.assertFalse(self.post({"type": "shadow_run", "file": "nope.mcap"})["ok"])
        self.assertFalse(self.post({"type": "shadow_run", "file": "../../etc/passwd"})["ok"])          # path traversal: only the base name is used
        from bag import BagWriter
        with BagWriter(os.path.join(self.tmp.name, "noraw"), fmt="jsonl") as w:
            w.write("events", {"text": "x", "kind": "info"})
        self.assertTrue(self.post({"type": "shadow_run", "file": os.path.basename(w.path)})["ok"])
        res = wait_done(self.hub)
        self.assertEqual(res["state"], "error"); self.assertIn("plc/raw", res["error"])


if __name__ == "__main__":
    unittest.main()
