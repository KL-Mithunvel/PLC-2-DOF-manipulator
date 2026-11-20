import json, os, subprocess, sys, tempfile, time, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bag import BagReader, BagRecorder, BagWriter, collect_meta, mcap_available
from bag.convert import convert_jsonl_log, info
from twin.server import Hub
from twin.sim import Twin
from twin.sources import Recorder, ReplaySource, load_snapshots

FORMATS = ["jsonl"] + (["mcap"] if mcap_available() else [])


class RoundTrip(unittest.TestCase):
    def test_every_topic_roundtrips_in_both_formats(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as d:
                msgs = [("twin/state", {"t": 1.0, "base": {"deg": 3.5}, "bits": {"M30.1": True}}),
                        ("plc/raw", {"V1000": [1, 2, 3], "M10": [0, 1]}),
                        ("events", {"text": "E-STOP pressed", "kind": "info"}),
                        ("diag", {"lat_ms": 4.2, "errors": 0}),
                        ("sensors", {"base": {"mA": 120.5}})]
                with BagWriter(os.path.join(d, "a"), collect_meta(notes="x", payload_kg=5), fmt=fmt) as w:
                    for i, (tp, pl) in enumerate(msgs):
                        w.write(tp, pl, t_mono=10 + i * 0.1, t_wall=1.7e9 + i)
                r = BagReader(w.path)
                got = list(r.messages())
                self.assertEqual([(m.topic, m.payload) for m in got], msgs)
                self.assertEqual([round(m.t_mono, 6) for m in got], [round(10 + i * 0.1, 6) for i in range(5)])
                self.assertEqual([round(m.t_wall, 3) for m in got], [1.7e9 + i for i in range(5)])
                self.assertEqual(r.topics["plc/raw"], 1)
                self.assertAlmostEqual(r.duration, 0.4, places=6)
                self.assertEqual(r.meta["notes"], "x"); self.assertEqual(r.meta["payload_kg"], 5)
                self.assertTrue(r.meta["plc_program_sha"])
                self.assertEqual([m.topic for m in r.messages(["events", "diag"])], ["events", "diag"])
                self.assertEqual(len(list(r.messages(t_from=10.15, t_to=10.35))), 2)

    def test_suffix_added_and_auto_format(self):
        with tempfile.TemporaryDirectory() as d:
            w = BagWriter(os.path.join(d, "run1")); w.close()
            self.assertTrue(w.path.endswith(".mcap" if mcap_available() else ".bag.jsonl"))
            w = BagWriter(os.path.join(d, "run2.bag.jsonl")); w.close(); self.assertEqual(w.fmt, "jsonl")

    def test_numpy_values_and_nan_are_handled(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("no numpy")
        with tempfile.TemporaryDirectory() as d, BagWriter(os.path.join(d, "n"), fmt="jsonl") as w:
            w.write("x", {"a": np.float64(1.5), "b": np.array([1, 2])})
            with self.assertRaises(ValueError):            # NaN would silently produce invalid JSON
                w.write("x", {"a": float("nan")})
            w.flush()
            self.assertEqual([m.payload for m in BagReader(w.path).messages()], [{"a": 1.5, "b": [1, 2]}])

    def test_half_written_last_line_is_tolerated(self):
        with tempfile.TemporaryDirectory() as d:
            with BagWriter(os.path.join(d, "c"), fmt="jsonl") as w:
                for i in range(5):
                    w.write("x", {"i": i})
            with open(w.path, "ab") as fh:
                fh.write(b'{"topic":"x","tm":1,"tw":1,"d":{"i":')       # power cut mid-write
            self.assertEqual([m.payload["i"] for m in BagReader(w.path).messages()], [0, 1, 2, 3, 4])

    def test_unclosed_and_cut_files_are_still_readable(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as d:
                w = BagWriter(os.path.join(d, "k"), {"a": 1}, fmt=fmt)
                for i in range(500):
                    w.write("x", {"i": i, "pad": "y" * 50})
                w.flush()                                         # a killed process: no close()
                r = BagReader(w.path)
                self.assertEqual(r.topics, {"x": 500}); self.assertEqual(r.meta, {"a": 1})
                self.assertEqual(r.truncated, fmt == "mcap")      # MCAP notices the missing footer; JSON lines cannot tell
                suffix = ".mcap" if fmt == "mcap" else ".bag.jsonl"
                cut = os.path.join(d, "cut" + suffix)
                with open(w.path, "rb") as a, open(cut, "wb") as b:
                    b.write(a.read()[:-25])                        # power cut in the middle of the last record
                c = BagReader(cut)
                self.assertEqual(c.topics, {"x": 499}); self.assertTrue(c.truncated)
                self.assertIn("NOT CLOSED", info(cut))
                w.close()

    def test_not_a_bag_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.bag.jsonl")
            open(p, "w").write('{"hello": 1}\n')
            with self.assertRaises(ValueError):
                BagReader(p)

    def test_large_bag_streams(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt), tempfile.TemporaryDirectory() as d:
                t0 = time.time()
                with BagWriter(os.path.join(d, "big"), fmt=fmt) as w:
                    for i in range(20000):
                        w.write("twin/state", {"t": i * 0.005, "pad": "x" * 200}, t_mono=i * 0.005, t_wall=1.7e9 + i * 0.005)
                n = sum(1 for _ in BagReader(w.path).messages())
                self.assertEqual(n, 20000); self.assertLess(time.time() - t0, 30)


class RecorderAndReplay(unittest.TestCase):
    def run_twin(self, fmt, seconds=12):
        d = tempfile.mkdtemp()
        hub = Hub(Twin(), d, record_format="bag")
        hub.recorder.fmt = fmt
        for _ in range(800): hub.twin.tick()
        self.assertTrue(hub.command({"type": "record_start", "name": "r"})["ok"])
        hub.twin.command({"type": "button", "tag": "START", "down": True})
        offered = []
        for i in range(int(seconds / 0.005)):
            hub.twin.tick()
            if i == 100: hub.twin.command({"type": "button", "tag": "START", "down": False})
            snap = hub.twin.snapshot()
            if i % 8 == 0:
                hub.recorder.offer(snap)
            if i % 400 == 0:
                hub.step()                      # events path
        hub.command({"type": "record_stop"})
        return d, hub

    def test_recorded_twin_run_replays_identically(self):
        for fmt in FORMATS:
            with self.subTest(fmt=fmt):
                d, hub = self.run_twin(fmt)
                path = hub.recorder.path
                frames = load_snapshots(path)
                self.assertGreater(len(frames), 50)
                rp = ReplaySource(d)
                self.assertEqual(rp.load(os.path.basename(path)), len(frames))
                self.assertIn(os.path.basename(path), hub.status()["logs"])
                # replay returns exactly the recorded frame at each recorded time (state equal, not approximately)
                for k in (0, len(frames) // 3, len(frames) - 1):
                    rp.pos = frames[k]["t"] - frames[0]["t"]
                    s = rp.snapshot()
                    self.assertEqual(s["t"], frames[k]["t"]); self.assertEqual(s["base"], frames[k]["base"]); self.assertEqual(s["bits"], frames[k]["bits"])
                self.assertEqual([f["t"] for f in frames], sorted(f["t"] for f in frames))
                r = BagReader(path)
                self.assertIn("twin/state", r.topics)
                self.assertTrue(r.meta["git"] is not None and "python" in r.meta)

    def test_twin_notes_become_events(self):
        d, hub = self.run_twin(FORMATS[0])
        ev = [m.payload["text"] for m in BagReader(hub.recorder.path).messages(["events"])]
        self.assertGreaterEqual(len(ev), 1); self.assertTrue(all(isinstance(t, str) and t for t in ev))

    def test_old_jsonl_log_converts_and_matches(self):
        with tempfile.TemporaryDirectory() as d:
            t = Twin(); rec = Recorder(d); rec.start("old")
            for i in range(600):
                t.tick(); rec.offer(t.snapshot())
            rec.stop()
            old = load_snapshots(rec.path)
            for fmt in FORMATS:
                out = convert_jsonl_log(rec.path, os.path.join(d, "conv_" + fmt), fmt=fmt)
                self.assertEqual(load_snapshots(out), old)

    def test_replay_path_traversal_still_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(FileNotFoundError):
                ReplaySource(d).load("../x.mcap")

    def test_info_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            with BagWriter(os.path.join(d, "i"), collect_meta(notes="R3"), fmt="jsonl") as w:
                w.write("twin/state", {"t": 0}); w.write("events", {"text": "a", "kind": "info"})
            text = info(w.path)
            self.assertIn("twin/state", text); self.assertIn("R3", text)
            r = subprocess.run([sys.executable, "-m", "bag", "info", w.path], capture_output=True, text=True,
                               cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("events", r.stdout)


if __name__ == "__main__":
    unittest.main()
