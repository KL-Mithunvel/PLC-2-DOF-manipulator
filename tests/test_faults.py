"""Stage 6: fault injection, signatures and the classifier. The fast tests use made-up feature vectors; the slow ones run a few real
shadow comparisons against the stored library (shadow/fault_library.json, built by `python -m shadow faults build`)."""
import json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shadow.faults import (FAULTS, FEATURES, LIBRARY_PATH, build_case, centroids, classify, confusion, load_library, signature,
                           synthesize)
from shadow.engine import rec_time
from twin.config import load_config


def vec(**kw):
    v = {k: 0.0 for k in FEATURES}
    v.update(kw)
    return v


class ClassifierUnit(unittest.TestCase):
    def setUp(self):
        self.lib = {
            "none": [vec(log_current_bias=0.8), vec(log_current_bias=0.7, log_base_rms=0.15)],
            "friction": [vec(log_current_bias=2.9), vec(log_current_bias=3.1)],
            "timer": [vec(n_timing=1, timing_ms=160), vec(n_timing=2, timing_ms=200)],
            "latch": [vec(latch=1, n_conf_bits=2), vec(latch=1, n_conf_bits=3)],
        }

    def test_nearest_centroid_and_confusion(self):
        self.assertEqual(classify(vec(log_current_bias=3.0), self.lib)[0], "friction")
        self.assertEqual(classify(vec(n_timing=1, timing_ms=180), self.lib)[0], "timer")
        self.assertEqual(classify(vec(latch=1, n_conf_bits=2), self.lib)[0], "latch")
        self.assertEqual(classify(vec(log_current_bias=0.75), self.lib)[0], "none")
        table, acc = confusion(self.lib, {"friction": [vec(log_current_bias=2.8)], "none": [vec(log_current_bias=3.0)]})
        self.assertEqual(acc, 0.5); self.assertEqual(table["none"], {"friction": 1})
        self.assertEqual(set(centroids(self.lib)), set(self.lib))

    def test_every_fault_builds_a_case_and_unknown_is_rejected(self):
        cfg = load_config()
        for name in FAULTS:
            c, script, keep = build_case(name, 0.5, cfg)
            self.assertIsNotNone(c)
        self.assertGreater(build_case("friction", 1.0, cfg)[0].base.friction_c, build_case("friction", 0.0, cfg)[0].base.friction_c)
        self.assertEqual(build_case("timer", 1.0, cfg)[0].timer_base_ms, 2 * cfg.timer_base_ms)
        self.assertTrue(build_case("latch", 0.5, cfg)[0].fix_estop_magnet_latch); self.assertEqual(len(build_case("latch", 0.5, cfg)[1]), 2)
        with self.assertRaises(ValueError): build_case("gremlins", 0.5, cfg)
        self.assertEqual(cfg.timer_base_ms, load_config().timer_base_ms)                 # the base config is never modified

    def test_link_outage_removes_a_window_of_records(self):
        recs = synthesize("link_outage", 0.5, seconds=14.0, hz=10)
        ts = [rec_time(r) for r in recs]
        self.assertTrue(any(b - a > 2.0 for a, b in zip(ts, ts[1:])))


@unittest.skipUnless(os.path.exists(LIBRARY_PATH), "fault library not built")
class AgainstStoredLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = load_library()

    def test_library_covers_all_faults_and_features(self):
        self.assertEqual(set(self.lib), set(FAULTS))
        with open(LIBRARY_PATH) as fh:
            self.assertEqual(json.load(fh)["features"], FEATURES)
        for fs in self.lib.values():
            self.assertGreaterEqual(len(fs), 2)

    def test_new_recordings_of_distinct_faults_are_classified(self):
        """A severity the library has not seen (0.45), classified from a fresh synthetic recording."""
        for truth in ("none", "friction", "latch", "link_outage"):
            sig = signature(synthesize(truth, 0.45))
            self.assertEqual(classify(sig, self.lib)[0], truth, (truth, classify(sig, self.lib)[1]))

    def test_a_small_payload_increase_is_not_visible_in_these_signals(self):
        """LIMIT, asserted on purpose: +1.5 kg looks like a healthy machine to every signal the PLC exposes (needs shoulder current)."""
        sig = signature(synthesize("payload", 0.5))
        self.assertIn(classify(sig, self.lib)[0], ("none", "payload"))
        self.assertLess(sig["log_base_rms"], 0.4)


if __name__ == "__main__":
    unittest.main()
