"""Power meter source: polling, diagnostics, faults, raw records, the twin-driven simulated meters, calibration fit, session bag.
No hardware and no serial port: everything runs on the simulated bus."""
import os, sys, tempfile, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bag import BagReader
from live.powermeter import PowerMeterSource, SimTwinFeed
from live.pzem import Pzem017, SimBus, SimPzem017, decode_regs
from live.rtu import RtuMaster
from tools.fit_motor_params import fit_log
from twin.config import TwinCfg
from twin.server import Hub
from twin.sim import Twin


def rig(hz=20.0, **bus_kw):
    devs = {"base": SimPzem017(address=1), "shoulder": SimPzem017(address=2)}
    bus = SimBus(list(devs.values()), **bus_kw)
    src = PowerMeterSource({"base": 1, "shoulder": 2}, lambda: RtuMaster(bus, retries=1), hz=hz, label="test", retry_s=0.2)
    return devs, bus, src


class EnergyResolution(unittest.TestCase):
    def test_the_meters_own_energy_counter_is_too_coarse_for_one_cycle(self):
        """FINDING: PZEM energy resolution is 1 Wh; a 30 s cycle at 20 W is 0.17 Wh and reads as 0. Integrate the power readings instead."""
        dev = SimPzem017(address=1)
        for _ in range(30): dev.update(24.0, 0.83, 1.0)                  # 30 s at about 20 W
        p = Pzem017(RtuMaster(SimBus([dev])), 1)
        r = p.read()
        self.assertEqual(r["energy_wh"], 0.0); self.assertAlmostEqual(r["power_w"], 19.9, delta=0.2)
        self.assertAlmostEqual(24.0 * 0.83 * 30 / 3600, 0.166, places=3)


class Polling(unittest.TestCase):
    def test_threaded_polling_gives_latest_values_diagnostics_and_status(self):
        devs, bus, src = rig(hz=20.0)
        devs["base"].update(24.0, 3.0, 3600.0); devs["shoulder"].update(23.8, 1.5, 3600.0)
        src.start(); time.sleep(1.5); src.stop()
        m = src.latest()
        self.assertAlmostEqual(m["base"]["mA"], 3000, delta=10); self.assertAlmostEqual(m["base"]["mV"], 24000, delta=10)
        self.assertAlmostEqual(m["base"]["W"], 72.0, delta=0.5); self.assertAlmostEqual(m["base"]["meter_W"], 72.0, delta=0.2)
        self.assertEqual(m["base"]["Wh"], 72.0); self.assertAlmostEqual(m["shoulder"]["mA"], 1500, delta=10)
        self.assertAlmostEqual(m["base"]["Wh_sw"], 72.0 * 1.4 / 3600, delta=0.25 * 72.0 * 1.4 / 3600)        # software integral of the power readings
        d = src.diag()
        self.assertEqual(d["errors"], 0); self.assertAlmostEqual(d["groups"]["base"]["rate_hz"], 20.0, delta=3.0)
        self.assertEqual(d["rtu"]["timeouts"], 0)
        snap = src.snapshot(); self.assertEqual(snap["source"], "sensors"); self.assertIn("base", snap["sensors"])

    def test_names_must_be_base_or_shoulder(self):
        with self.assertRaises(ValueError): PowerMeterSource({"elbow": 3}, lambda: None)

    def test_raw_records_decode_back_to_the_meter_values(self):
        devs, bus, src = rig()
        devs["base"].update(24.0, 2.5, 100.0)
        src.master = RtuMaster(bus); src.drivers = {c: Pzem017(src.master, s) for c, s in src.slaves.items()}
        src.poll_once()
        raws = src.drain_raw()
        self.assertEqual({r["meter"] for r in raws}, {"base", "shoulder"}); self.assertEqual(src.drain_raw(), [])
        b = next(r for r in raws if r["meter"] == "base")
        self.assertEqual(len(b["regs"]), 8); self.assertEqual(b["slave"], 1); self.assertLessEqual(b["t0"], b["t1"])
        d = decode_regs(b["regs"]); self.assertAlmostEqual(d["current_a"], 2.5, places=2); self.assertAlmostEqual(d["voltage_v"], 24.0, places=2)

    def test_dropped_and_corrupt_frames_are_counted_and_the_source_keeps_going(self):
        devs, bus, src = rig(hz=30.0, drop=0.25, corrupt=0.15, seed=5)
        devs["base"].update(24.0, 2.0, 1.0); devs["shoulder"].update(24.0, 1.0, 1.0)
        src.start(); time.sleep(2.0); src.stop()
        d = src.diag()
        self.assertGreater(d["errors"], 0); self.assertGreater(d["polls"], 20)
        self.assertGreater(d["rtu"]["timeouts"] + d["rtu"]["crc_errors"], 0)
        self.assertAlmostEqual(src.latest()["base"]["mA"], 2000, delta=20)

    def test_cut_cable_reports_disconnected_and_recovers(self):
        devs, bus, src = rig(hz=20.0)
        devs["base"].update(24.0, 2.0, 1.0); devs["shoulder"].update(24.0, 1.0, 1.0)
        src.start(); time.sleep(0.6); self.assertTrue(src.status()["connected"])
        bus.cut(True); time.sleep(2.2)
        st = src.status(); self.assertFalse(st["connected"]); self.assertTrue(st["info"])
        bus.cut(False); time.sleep(1.2)
        ok = src.status()["connected"]; ev = src.drain_events(); src.stop()
        self.assertTrue(ok)
        self.assertTrue(any(e["kind"] == "error" for e in ev)); self.assertGreaterEqual(src.diag()["errors"], 1)

    def test_a_missing_serial_port_is_an_error_status_not_a_crash(self):
        src, feed = PowerMeterSource.from_spec("COM_DOES_NOT_EXIST@9600")
        self.assertIsNone(feed)
        src.retry_s = 0.2
        src.start(); time.sleep(0.8)
        st = src.status(); src.stop()
        self.assertFalse(st["connected"]); self.assertTrue(st["info"])

    def test_sim_spec_needs_the_twin(self):
        with self.assertRaises(ValueError): PowerMeterSource.from_spec("sim")


class TwinDriven(unittest.TestCase):
    def run_twin(self, kt_scale, seconds=40.0, meter_period=0.04):
        cfg = TwinCfg()
        twin = Twin(cfg)
        src, feed = PowerMeterSource.from_spec("sim", twin)
        feed.kt_scale = kt_scale
        src.window_s = 0.001                    # this loop runs many sim-seconds per wall-second: use the newest sample only, no wall-clock averaging
        src.master = src._factory(); src.drivers = {c: Pzem017(src.master, s) for c, s in src.slaves.items()}
        for _ in range(800): twin.tick(); feed.step(0.005)
        twin.command({"type": "button", "tag": "START", "down": True})
        frames, nxt = [], 0.0
        tau_sum = {"base": 0.0, "shoulder": 0.0}; n = 0
        for i in range(int(seconds / 0.005)):
            twin.tick(); feed.step(0.005)
            if i == 80: twin.command({"type": "button", "tag": "START", "down": False})
            for ch in tau_sum: tau_sum[ch] += abs(getattr(twin.arm, ch).tau)
            n += 1
            if i * 0.005 >= nxt:
                nxt += meter_period
                src.poll_once()
                # the twin's holding torque chatters from scan to scan: compare the meter with the torque AVERAGED over the same interval
                frames.append({ch: {"tau": tau_sum[ch] / n} for ch in tau_sum} | {"sensors": src.latest()})
                tau_sum = {"base": 0.0, "shoulder": 0.0}; n = 0
        return cfg, frames

    def test_the_calibration_fit_recovers_kt_through_the_meters(self):
        cfg, frames = self.run_twin(kt_scale=1.25)
        res = fit_log(frames, cfg, smooth=5)
        self.assertAlmostEqual(res["shoulder"]["kt"], cfg.shoulder.kt * 1.25, delta=cfg.shoulder.kt * 1.25 * 0.10)
        self.assertGreater(res["shoulder"]["r2"], 0.9)
        e = frames[-1]["sensors"]
        self.assertTrue(all(0 < e[c]["mV"] <= 24000 for c in e))                          # supply sags under load, never above 24 V

    def test_a_loaded_shoulder_draws_more_than_an_unloaded_one(self):
        """The point of the meters: payload shows up as power, which no PLC-exposed signal could show (docs/FAULTS.md)."""
        def mean_shoulder_w(payload):
            cfg = TwinCfg(); cfg.arm.payload = payload
            twin = Twin(cfg)
            src, feed = PowerMeterSource.from_spec("sim", twin)
            src.master = src._factory(); src.drivers = {c: Pzem017(src.master, s) for c, s in src.slaves.items()}
            for _ in range(800): twin.tick(); feed.step(0.005)
            twin.command({"type": "button", "tag": "START", "down": True})
            ws = []
            for i in range(int(25 / 0.005)):
                twin.tick(); feed.step(0.005)
                if i == 80: twin.command({"type": "button", "tag": "START", "down": False})
                if i % 40 == 0:
                    src.poll_once(); ws.append(src.latest()["shoulder"]["meter_W"])
            return sum(ws) / len(ws)
        self.assertGreater(mean_shoulder_w(8.0), 1.05 * mean_shoulder_w(2.0))


class HubIntegration(unittest.TestCase):
    def test_session_bag_has_meter_samples_raw_and_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            twin = Twin()
            hub = Hub(twin, d, record_format="bag")
            src, feed = PowerMeterSource.from_spec("sim", twin, hz=20.0)
            hub.register("sensors", src.start()); hub.tickers.append(feed)
            res = hub.start_recording("PM", {"notes": "power meter test"})
            self.assertEqual(res["sources"], ["sim", "sensors"])
            t_end = time.time() + 3.0
            while time.time() < t_end:
                for _ in range(10): twin.tick()
                hub.step(); time.sleep(0.02)
            hub.stop_recording(); src.stop()
            r = BagReader(res["file"])
            for topic in ("twin/state", "sensors", "sensors/raw", "diag", "events"):
                self.assertIn(topic, r.topics, (topic, r.topics))
            raws = [m.payload for m in r.messages(["sensors/raw"])]
            self.assertGreater(len(raws), 20); self.assertEqual({x["meter"] for x in raws}, {"base", "shoulder"})
            snap = next(m.payload for m in r.messages(["sensors"]))
            self.assertIn("sensors", snap)
            diag = [m.payload for m in r.messages(["diag"]) if m.payload.get("source") == "sensors"]
            self.assertTrue(diag and diag[-1]["polls"] > 10)
            # the twin's own snapshot carries the measured current for the GUI
            self.assertIn("sensors", hub.snapshot("sim"))

    def test_standalone_twin_never_imports_the_meter_code(self):
        import subprocess
        code = "import sys; sys.path.insert(0, %r); import twin.server, twin.sim; print(any(m.startswith('live') for m in sys.modules))" % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.stdout.strip(), "False", out.stderr)


if __name__ == "__main__":
    unittest.main()
