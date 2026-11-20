"""Stage 10: offline analysis of recordings (cycle and step timing, link report, pick repeatability, CSV, CLI)."""
import csv, json, os, subprocess, sys, tempfile, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from analysis import cycle_table, export_csv, format_summary, link_report, pick_periods, pick_repeatability, summary
from bag import BagWriter
from shadow.synth import record_session, standard_run, write_bag
from twin.sim import Twin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Analysis(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.recs = record_session(Twin(), 40.0, standard_run(4.0), fast_hz=25)

    def test_cycle_table_finds_three_cycles_with_the_known_timer_steps(self):
        rows = cycle_table(self.recs)
        self.assertEqual([r["cycle"] for r in rows], [1, 2, 3])
        for r in rows[:3]:
            self.assertAlmostEqual(r["step_s"]["M31.3"], 0.2, delta=0.06)       # the pick delay timer: 20 ticks x 10 ms
            self.assertAlmostEqual(r["step_s"]["M31.7"], 0.2, delta=0.06)       # the drop delay timer
        self.assertGreater(rows[0]["cycle_s"], rows[1]["cycle_s"])              # the first cycle includes the approach from home

    def test_pick_to_pick_period_is_stable_in_the_twin(self):
        p = pick_periods(self.recs)
        self.assertGreaterEqual(p["n"], 2)
        self.assertLess(p["std"], 0.15)
        self.assertGreater(p["mean"], 8.0); self.assertLess(p["mean"], 12.0)

    def test_link_report_matches_what_was_simulated(self):
        lr = link_report(self.recs)
        self.assertAlmostEqual(lr["groups"]["fast"]["rate_hz"], 25.0, delta=0.5)
        self.assertAlmostEqual(lr["groups"]["slow"]["rate_hz"], 1.0, delta=0.05)
        self.assertLess(lr["groups"]["fast"]["jitter_ms"], 2.0)
        for v in lr["blocks"].values():
            self.assertAlmostEqual(v["mean"], 2.0, delta=0.05)                  # synth.poll_twin stamps a 2 ms round trip

    def test_pick_repeatability_in_a_deterministic_twin_is_tight(self):
        pr = pick_repeatability(self.recs)
        self.assertEqual(pr["n"], 3)
        self.assertLess(pr["tip_spread_mm"], 5.0)
        self.assertLess(pr["shoulder_deg_std"], 0.5)

    def test_summary_csv_and_cli(self):
        with tempfile.TemporaryDirectory() as d:
            bag = write_bag(self.recs, os.path.join(d, "r"), {"notes": "unit"}, fmt="jsonl")
            s = summary(bag)
            self.assertEqual(s["cycle_s"]["n"], 3); self.assertEqual(s["meta"]["notes"], "unit")
            self.assertIn("pick-to-pick period", format_summary(s))
            r = subprocess.run([sys.executable, "-m", "analysis", "summary", bag, "--json", os.path.join(d, "s.json")],
                               capture_output=True, text=True, cwd=ROOT, timeout=100)
            self.assertEqual(r.returncode, 0, r.stderr); self.assertIn("cycles: 3", r.stdout)
            with open(os.path.join(d, "s.json")) as fh:
                self.assertEqual(json.load(fh)["cycle_s"]["n"], 3)
            # csv from a twin/state topic
            with BagWriter(os.path.join(d, "st"), fmt="jsonl") as w:
                for i in range(5):
                    w.write("twin/state", {"t": i * 0.1, "base": {"deg": i * 2.0}, "bits": {"Q0.7": i % 2}}, t_mono=10 + i * 0.1, t_wall=1.7e9 + i)
            out = os.path.join(d, "o.csv")
            self.assertEqual(export_csv(w.path, out, ["base/deg", "bits/Q0.7", "missing/x"]), 5)
            with open(out, newline="") as fh:
                rows = list(csv.reader(fh))
            self.assertEqual(rows[0], ["t_mono", "t_wall", "base/deg", "bits/Q0.7", "missing/x"])
            self.assertEqual(rows[3][2], "4.0"); self.assertEqual(rows[1][4], "")

    def test_no_raw_records_gives_a_plain_summary(self):
        with tempfile.TemporaryDirectory() as d:
            with BagWriter(os.path.join(d, "e"), fmt="jsonl") as w:
                w.write("events", {"text": "hello", "kind": "info"})
            s = summary(w.path)
            self.assertNotIn("cycles", s); self.assertIn("events", format_summary(s))


if __name__ == "__main__":
    unittest.main()
