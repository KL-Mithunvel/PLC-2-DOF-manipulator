"""Open-mode shadow with an external shoulder-current meter (synthetic): payload becomes visible, which the PLC signals could not show."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shadow.faults import power_study


class PowerShadow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = power_study("none", 0.0, seconds=20)
        cls.p = power_study("payload", 0.5, seconds=20)      # +1.5 kg

    def test_shoulder_bias_reveals_payload(self):
        self.assertLess(abs(self.h["shoulder_mA"]["bias"]), 200)
        self.assertGreater(self.p["shoulder_mA"]["bias"], self.h["shoulder_mA"]["bias"] + 300)

    def test_plc_exposed_base_current_does_not(self):
        self.assertLess(abs(self.p["base_mA"]["bias"] - self.h["base_mA"]["bias"]), 30)

    def test_without_meter_no_shoulder_trace(self):
        from shadow.engine import ShadowEngine
        from shadow.synth import record_session, standard_run
        from twin.sim import Twin
        res = ShadowEngine(warmup_s=3.0).run_open(record_session(Twin(), 8.0, standard_run(4.0), fast_hz=25))
        self.assertNotIn("shoulder_mA", res.traces)


if __name__ == "__main__":
    unittest.main()
