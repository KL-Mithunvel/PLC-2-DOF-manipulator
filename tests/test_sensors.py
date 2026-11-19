import os
import random
import socket
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.sensors import SensorSource, parse_line, udp_reader
from tools.fit_motor_params import fit_log, linfit
from tools.sim_sensors import measured_current_ma, voltage_mv
from twin.config import TwinCfg
from twin.server import Hub
from twin.sim import Twin


class Protocol(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse_line("S,1200,1,850,23800\n"), (1200, "shoulder", 850.0, 23800.0))
        for bad in ("", "S,1,2,3", "X,1,0,1,1", "S,a,0,1,1", "S,1,5,1,1"):
            self.assertIsNone(parse_line(bad))

    def test_window_average_and_power(self):
        s = SensorSource(lambda stop: iter(()), window_s=1.0)
        for i, ma in enumerate((1000, 2000, 3000)):
            s.feed_line(f"S,{i},0,{ma},24000", now=100.0 + i * 0.1)
        s.feed_line("junk", now=100.0)
        self.assertEqual(s.bad, 1)
        m = s.latest(now=100.3)["base"]
        self.assertAlmostEqual(m["mA"], 2000)
        self.assertAlmostEqual(m["W"], 2.0 * 24.0)
        self.assertNotIn("shoulder", s.latest(now=100.3))

    def test_udp_roundtrip(self):
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        src = SensorSource(udp_reader(port, "127.0.0.1")).start()
        time.sleep(0.3)
        tx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tx.sendto(b"S,10,0,1500,24000\nS,10,1,700,23900\n", ("127.0.0.1", port))
        deadline = time.time() + 3
        while time.time() < deadline and src.count < 2:
            time.sleep(0.05)
        src.stop()
        self.assertEqual(src.count, 2)
        self.assertTrue(src.status()["connected"])


class Fit(unittest.TestCase):
    def test_linfit(self):
        a, b, r2 = linfit([0, 1, 2, 3], [5, 7, 9, 11])
        self.assertAlmostEqual((a, b, r2), (2.0, 5.0, 1.0))

    def test_recovers_torque_constant(self):
        random.seed(1)
        cfg = TwinCfg()
        t = Twin(cfg)
        for _ in range(800):
            t.tick()
        t.command({"type": "button", "tag": "START", "down": True})
        frames = []
        for i in range(int(40 / 0.005)):
            t.tick()
            if i == 80:
                t.command({"type": "button", "tag": "START", "down": False})
            if i % 8 == 0:
                s = t.snapshot()
                s["sensors"] = {}
                for key, ax in (("base", cfg.base), ("shoulder", cfg.shoulder)):
                    ma = measured_current_ma(s[key], ax.ratio, ax.eta, ax.kt, 1.25, 30, 60)
                    s["sensors"][key] = {"mA": ma, "mV": voltage_mv(ma)}
                frames.append({k: s[k] for k in ("base", "shoulder", "sensors")})
        res = fit_log(frames, cfg)
        self.assertAlmostEqual(res["shoulder"]["kt"], cfg.shoulder.kt * 1.25, delta=cfg.shoulder.kt * 1.25 * 0.05)
        self.assertGreater(res["shoulder"]["r2"], 0.95)
        self.assertAlmostEqual(res["shoulder"]["idle_mA"], 60, delta=60)


class HubMerge(unittest.TestCase):
    def test_sim_snapshot_contains_measured_sensors(self):
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(Twin(), d)
            src = SensorSource(lambda stop: iter(()))
            hub.register("sensors", src)
            for _ in range(200):
                hub.twin.tick()
            src.feed_line("S,1,0,1234,24000")
            s = hub.snapshot("sim")
            self.assertAlmostEqual(s["sensors"]["base"]["mA"], 1234)
            self.assertIn("base_a_meas", s["sample"])


if __name__ == "__main__":
    unittest.main()
