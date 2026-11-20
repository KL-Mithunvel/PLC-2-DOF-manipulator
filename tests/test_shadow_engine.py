"""Stage 5: the shadow engine on synthetic "real" recordings (a twin standing in for the PLC, optionally with a seeded fault).
No hardware. These tests are the evidence of what the tool can and cannot see, so the limits are asserted too."""
import copy, json, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bag import BagReader
from live.raw import apply_record
from shadow.engine import ShadowEngine, analyse, covered, format_report, load_records, rec_time
from shadow.synth import estop, record_session, standard_run, write_bag
from twin.config import load_config
from twin.il import Memory
from twin.sim import Twin

CFG = load_config()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def cfg_with(**kw):
    c = copy.deepcopy(CFG)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def sustained(rep, detector="conformance"):
    return [e for e in rep["events"] if e["detector"] == detector]


class Synth(unittest.TestCase):
    def test_synthetic_records_rebuild_the_twin_memory(self):
        t = Twin()
        recs = record_session(t, 12.0, standard_run(4.0), fast_hz=10)
        mem = Memory()
        for r in recs:
            apply_record(r, mem)
        for a in ("MD600", "VD1044", "VD2020", "VD2300", "VD2404", "M30.1", "M31.2", "Q0.7", "VW1000", "VD1002"):
            self.assertEqual(mem.read(a), t.plc.mem.read(a), a)
        self.assertEqual({r["group"] for r in recs}, {"fast", "slow"})
        times = [rec_time(r) for r in recs]
        self.assertEqual(times, sorted(times))

    def test_covered_knows_which_poll_refreshed_a_cell(self):
        recs = record_session(Twin(), 2.0, [], fast_hz=10)
        fast = next(r for r in recs if r["group"] == "fast"); slow = next(r for r in recs if r["group"] == "slow")
        self.assertTrue(covered(fast, "M31.2")); self.assertTrue(covered(fast, "VD1044")); self.assertTrue(covered(fast, "MD600")); self.assertTrue(covered(fast, "VD1002"))
        self.assertFalse(covered(fast, "VD2300")); self.assertTrue(covered(slow, "VD2300")); self.assertTrue(covered(slow, "VW2500")); self.assertFalse(covered(slow, "M31.2"))


class LadderConformance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs10 = record_session(Twin(), 40.0, standard_run(4.0), fast_hz=10)
        cls.recs25 = record_session(Twin(), 40.0, standard_run(4.0), fast_hz=25)

    def test_identical_program_one_step_ahead_has_no_sustained_divergence(self):
        rep = analyse(ShadowEngine(warmup_s=3.0, resync=True).run_ladder(self.recs10))
        self.assertEqual(rep["events"], [], rep["summary"])
        self.assertIsNone(rep["first_divergence"])
        self.assertLess(max(v["mismatch_rate"] for v in rep["bits"].values()), 0.05)        # timing only: a poll here and there
        self.assertGreater(min(v["exact_match_rate"] for v in rep["words"].values()), 0.95)

    def test_free_running_needs_a_fast_poll(self):
        """LIMIT, asserted on purpose: at 10 Hz a free-running shadow misses one-scan events and cascades; at 25 Hz it holds."""
        slow = analyse(ShadowEngine(warmup_s=3.0, resync=False).run_ladder(self.recs10))
        fast = analyse(ShadowEngine(warmup_s=3.0, resync=False).run_ladder(self.recs25))
        self.assertGreaterEqual(len(sustained(slow)), 10)
        self.assertLessEqual(len(sustained(fast)), 2)
        self.assertTrue(fast["first_divergence"] is None or fast["first_divergence"]["t"] > 25.0)

    def test_a_patched_ladder_is_detected_when_the_estop_is_pressed(self):
        recs = record_session(Twin(cfg_with(fix_estop_magnet_latch=True)), 25.0, standard_run(4.0) + [(7.2, estop(True)), (9.5, estop(False))], fast_hz=25)
        rep = analyse(ShadowEngine(warmup_s=3.0, resync=False).run_ladder(recs))
        fd = rep["first_divergence"]
        self.assertIsNotNone(fd, rep["summary"])
        self.assertEqual(fd["signal"], "M30.6")                                            # the auto-magnet latch the patch clears
        self.assertGreater(fd["t"], 7.0); self.assertLess(fd["t"], 7.6)                    # within a few polls of the e-stop at 7.2 s
        self.assertIn("M30.6", {e["signal"] for e in sustained(rep)})

    def test_a_wrong_timer_base_shows_up_as_a_timing_alarm_on_the_timer_steps(self):
        recs = record_session(Twin(cfg_with(timer_base_ms=20.0)), 40.0, standard_run(4.0), fast_hz=25)
        rep = analyse(ShadowEngine(warmup_s=3.0, resync=False).run_ladder(recs))
        tm = {e["signal"]: e for e in rep["events"] if e["detector"] == "timing"}
        self.assertIn("M31.3", tm); self.assertIn("M31.7", tm)                             # the two timed steps (T21, T23 style delays)
        for e in (tm["M31.3"], tm["M31.7"]):
            self.assertAlmostEqual(e["peak"], 0.2, delta=0.06)                             # 20 ticks x (20 - 10) ms
            self.assertIn("earlier", e["text"])
        self.assertNotIn("M31.2", tm)                                                      # steps without a timer are not blamed

    def test_gaps_in_the_recording_reseed_the_twin(self):
        recs = [r for r in self.recs25 if not (1010.0 < rec_time(r) < 1016.0)]               # a 6 s hole (PLC unreachable)
        res = ShadowEngine(warmup_s=3.0, resync=False).run_ladder(recs)
        self.assertEqual(len(res.gaps), 1)
        rep = analyse(res)
        self.assertEqual(len(rep["gaps"]), 1)


class OpenLoop(unittest.TestCase):
    def test_same_model_tracks_the_arm_within_timing_noise(self):
        recs = record_session(Twin(), 35.0, standard_run(4.0), fast_hz=10)
        rep = analyse(ShadowEngine(warmup_s=3.0).run_open(recs))
        for k in ("base_deg", "shoulder_deg"):
            self.assertLess(rep["angles"][k]["rms"], 1.5, k); self.assertLess(rep["angles"][k]["max_abs"], 3.0, k)
        self.assertEqual([e for e in rep["events"] if e["detector"].startswith("threshold")], [])

    def test_a_slower_real_axis_is_detected(self):
        c = copy.deepcopy(CFG); c.base.profile_rpm = CFG.base.profile_rpm * 0.6
        recs = record_session(Twin(c), 35.0, standard_run(4.0), fast_hz=10)
        rep = analyse(ShadowEngine(warmup_s=3.0).run_open(recs))
        self.assertGreater(rep["angles"]["base_deg"]["rms"], 10.0)
        fd = rep["first_divergence"]; self.assertIsNotNone(fd)
        self.assertTrue(any(e["signal"].startswith("base_deg") and e["severity"] == "alarm" for e in rep["events"]))


class BagAndCli(unittest.TestCase):
    def test_load_records_from_a_bag_and_cli_report(self):
        with tempfile.TemporaryDirectory() as d:
            recs = record_session(Twin(cfg_with(timer_base_ms=20.0)), 40.0, standard_run(4.0), fast_hz=25)
            path = write_bag(recs, os.path.join(d, "syn"), {"fault": "timer"}, fmt="jsonl")
            back = load_records(path)
            self.assertEqual(len(back), len(recs)); self.assertEqual(BagReader(path).meta["synthetic"], True)
            out = os.path.join(d, "rep.json"); ev = os.path.join(d, "ev")
            r = subprocess.run([sys.executable, "-m", "shadow", "report", path, "--no-resync", "--json", out, "--events-bag", ev],
                               capture_output=True, text=True, cwd=ROOT, timeout=100)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("timing", r.stdout); self.assertIn("twin earlier", r.stdout)
            with open(out) as fh:
                rep = json.load(fh)
            self.assertTrue(any(e["detector"] == "timing" for e in rep["events"]))
            evbag = next(f for f in os.listdir(d) if f.startswith("ev"))
            self.assertGreaterEqual(BagReader(os.path.join(d, evbag)).topics.get("events", 0), 2)
            self.assertIn("shadow report", format_report(rep))

    def test_cli_synth_writes_a_usable_recording(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "s.bag.jsonl")
            r = subprocess.run([sys.executable, "-m", "shadow", "synth", out, "--fault", "latch", "--seconds", "12", "--hz", "20"],
                               capture_output=True, text=True, cwd=ROOT, timeout=100)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertGreater(len(load_records(out)), 100)


if __name__ == "__main__":
    unittest.main()
