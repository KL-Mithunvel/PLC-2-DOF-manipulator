"""Recording check (bag/check.py) on synthetic bags: a good one passes, broken ones are flagged. No hardware."""
import os, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bag import BagWriter, collect_meta
from bag.check import check, report
from shadow.synth import estop, record_session, standard_run
from twin.sim import Twin


def levels(path, **kw):
    return {(l, t) for l, t, _ in check(path, **kw)}


class BagCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tw = Twin()
        script = standard_run(4.0) + [(20.0, estop(True)), (22.0, estop(False))]
        cls.recs = record_session(tw, 40.0, script, fast_hz=25.0)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def write(self, name, recs, notes="x", **kw):
        p = os.path.join(self.tmp.name, name)
        with BagWriter(p, collect_meta(notes=notes) if notes else collect_meta(), fmt="jsonl") as w:
            for r in recs:
                w.write("plc/raw", r, r["t_mono"], r["t_wall"])
        return w.path

    def test_good_recording_is_usable(self):
        p = self.write("good", self.recs)
        text, ok = report(p)
        self.assertTrue(ok, text)
        self.assertIn("USABLE", text)
        self.assertNotIn(("FAIL", "plc/raw"), levels(p))

    def test_slow_polling_warned(self):
        slow = [r for i, r in enumerate(self.recs) if r["group"] != "fast" or i % 6 == 0]
        p = self.write("slow", slow)
        self.assertTrue(any(l == "WARN" and "Hz" in t for l, topic, t in check(p) if topic.startswith("plc/raw[fast")))

    def test_gap_warned(self):
        cut = [r for r in self.recs if not (15 < r["t_mono"] - 1000 < 19)]
        p = self.write("gap", cut)
        self.assertTrue(any("gap" in t for _, _, t in check(p)))

    def test_missing_coverage_fails(self):
        cut = [dict(r, blocks=[b for b in r["blocks"] if b["area"] != "V"]) if r["group"] == "fast" else r for r in self.recs]
        p = self.write("nov", cut)
        self.assertIn(("FAIL", "plc/raw"), levels(p))

    def test_no_raw_fails_and_idle_warned(self):
        p = os.path.join(self.tmp.name, "empty")
        with BagWriter(p, collect_meta(), fmt="jsonl") as w:
            w.write("events", {"text": "hi", "kind": "info"})
        self.assertIn(("FAIL", "plc/raw"), levels(w.path))
        idle = self.write("idle", record_session(Twin(), 10.0, [], fast_hz=25.0))
        self.assertIn(("WARN", "content"), levels(idle))

    def test_missing_notes_warned_and_unreadable(self):
        p = self.write("nonotes", self.recs, notes="")
        self.assertIn(("WARN", "meta"), levels(p))
        bad = os.path.join(self.tmp.name, "bad.bag.jsonl")
        open(bad, "w").write("garbage\n")
        self.assertIn(("FAIL", "file"), levels(bad))


if __name__ == "__main__":
    unittest.main()
