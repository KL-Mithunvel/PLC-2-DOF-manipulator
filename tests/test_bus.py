import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.config import TwinCfg
from twin.server import Hub, make_handler
from twin.sim import Twin
from twin.sources import Recorder, ReplaySource, pose_snapshot
from http.server import ThreadingHTTPServer


class RecorderReplay(unittest.TestCase):
    def test_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            t = Twin()
            rec = Recorder(d)
            rec.start("a")
            for _ in range(400):
                t.tick()
                rec.offer(t.snapshot())
            rec.stop()
            self.assertGreater(rec.n, 30)
            rp = ReplaySource(d)
            self.assertEqual(rp.load("a.jsonl"), rec.n)
            first = rp.snapshot()
            self.assertEqual(first["source"], "replay")
            self.assertEqual(first["schema"], 1)
            rp.advance(1.0)
            self.assertAlmostEqual(rp.snapshot()["t"] - first["t"], 1.0, delta=0.08)
            rp.seek(1.0)
            self.assertEqual(rp.snapshot()["replay"]["index"], rec.n - 1)

    def test_load_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                ReplaySource(d).load("../secret.jsonl")


class PoseSnapshot(unittest.TestCase):
    def test_home_pose_is_vertical(self):
        s = pose_snapshot("plc", TwinCfg(), 0.0, 0.0)
        self.assertAlmostEqual(s["geom"]["p"][0], 0.0)
        self.assertAlmostEqual(s["geom"]["p"][2], 0.17 + 0.42)


class HubHttp(unittest.TestCase):
    def test_http_endpoints_and_record(self):
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(Twin(), d)
            srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(hub))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            base = f"http://127.0.0.1:{srv.server_address[1]}"

            def get(p):
                return json.loads(urllib.request.urlopen(base + p, timeout=5).read())

            def post(o):
                r = urllib.request.Request(base + "/api/cmd", json.dumps(o).encode(), {"Content-Type": "application/json"})
                return json.loads(urllib.request.urlopen(r, timeout=5).read())

            self.assertEqual(get("/api/state")["source"], "sim")
            self.assertTrue(post({"type": "record_start", "name": "t1"})["ok"])
            for _ in range(300):
                hub.twin.tick()
                hub.recorder.offer(hub.twin.snapshot())
            post({"type": "record_stop"})
            self.assertIn("t1.jsonl", get("/api/sources")["logs"])
            self.assertGreater(post({"type": "replay_load", "file": "t1.jsonl"})["frames"], 10)
            self.assertEqual(get("/api/state?source=replay")["source"], "replay")
            self.assertTrue(post({"type": "button", "tag": "START", "down": True})["ok"])   # sim commands still routed
            srv.shutdown()
            hub.recorder.stop()


if __name__ == "__main__":
    unittest.main()
