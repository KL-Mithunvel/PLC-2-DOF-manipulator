"""The ESP32 + INA226 route, simulated: chip model against the datasheet, the sketch's arithmetic, the sketch file itself, and the whole
chain from the twin to the host. No hardware."""
import os, re, sys, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.ina226 import (INA226, EspFirmware, EspSim, REG_BUS, REG_CAL, REG_CONFIG, REG_CURRENT, REG_MANUF, REG_SHUNT, _s16,
                         parse_sketch_constants)
from live.sensors import SensorSource, parse_line
from tools.fit_motor_params import fit_log
from twin.config import TwinCfg
from twin.server import Hub
from twin.sim import Twin

INO = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "firmware", "motor_sensors", "motor_sensors.ino")


def chips(r=0.005):
    return [INA226(0x40, r), INA226(0x41, r)]


def settle(fw, c, i_a, v=24.0, t0=0.0, seconds=0.2):
    for k in range(int(seconds / 0.001)):
        for ch in c:
            ch.set_input(t0 + k * 0.001, i_a, v)
    return t0 + seconds


class ChipModel(unittest.TestCase):
    def test_registers_follow_the_datasheet(self):
        c = INA226(0x40, 0.005)
        fw = EspFirmware([c, INA226(0x41, 0.005)])
        t = settle(fw, [c], 3.0)
        self.assertEqual(fw.cal, 3355)                                           # 0.00512 / (10 A / 32768 x 5 mOhm), truncated
        self.assertEqual(_s16(c.read_reg(REG_SHUNT, t)), 6000)                    # 3 A x 5 mOhm = 15 mV = 6000 x 2.5 uV
        self.assertEqual(c.read_reg(REG_BUS, t), 19200)                           # 24 V / 1.25 mV
        self.assertAlmostEqual(_s16(c.read_reg(REG_CURRENT, t)) * fw.current_lsb, 3.0, delta=0.001)
        self.assertEqual(c.read_reg(REG_MANUF, t), 0x5449); self.assertEqual(c.read_reg(0xFF, t), 0x2260)

    def test_config_register_and_conversion_window_of_the_sketch(self):
        fw = EspFirmware(chips())
        self.assertEqual(fw.chips[0].config, 0x4527)                              # AVG=16, 1.1 ms, 1.1 ms, continuous
        self.assertAlmostEqual(fw.chips[0].window_s, 0.0352, places=4)            # the "35 ms" of the comment
        fast = INA226(); fast.write_reg(REG_CONFIG, 0x4000 | 0b001 << 9 | 0b100 << 6 | 0b100 << 3 | 7)
        self.assertAlmostEqual(fast.window_s, 0.0088, places=4)                   # what the old code (AVG=4) really gave, not what its comment said

    def test_negative_current_is_signed(self):
        c = INA226(0x40, 0.005); fw = EspFirmware([c, INA226(0x41, 0.005)])
        t = settle(fw, [c], -2.0)
        self.assertAlmostEqual(_s16(c.read_reg(REG_CURRENT, t)) * fw.current_lsb, -2.0, delta=0.001)

    def test_a_result_is_held_for_a_whole_conversion_window_and_lags_a_step(self):
        c = INA226(0x40, 0.005); fw = EspFirmware([c, INA226(0x41, 0.005)])
        for k in range(1000):
            c.set_input(k * 0.001, 0.0 if k < 500 else 4.0, 24.0)                  # a step to 4 A at t = 0.5 s
        read = lambda t: _s16(c.read_reg(REG_CURRENT, t)) * fw.current_lsb
        w = c.window_s
        self.assertAlmostEqual(read(0.5 + 0.2 * w), 0.0, delta=0.001)              # inside the window that is still completing: the old result
        self.assertAlmostEqual(read(0.5 + 3 * w), 4.0, delta=0.001)                # a few windows later the new value is there
        mid = read(0.5 + 0.99 * w)
        self.assertTrue(0.0 <= mid <= 4.0)                                         # the window straddling the step gives a partial average
        self.assertEqual(read(0.7 + 0.1 * w), read(0.7 + 0.9 * w))                  # within one window the register does not change

    def test_a_wrong_shunt_value_is_a_silent_scale_error_and_the_chip_clips(self):
        """The cheap INA226 breakouts carry 0.1 ohm. The sketch assumes 5 mOhm: nothing errors, every reading is 20 times too big."""
        real = chips(r=0.1)
        fw = EspFirmware(real, shunt_ohms=0.005, max_current=10.0)
        t = settle(fw, real, 0.2)                                                  # really 0.2 A
        self.assertAlmostEqual(_s16(real[0].read_reg(REG_CURRENT, t)) * fw.current_lsb, 4.0, delta=0.01)    # read as 4 A
        t = settle(fw, real, 1.0, t0=t)                                            # really 1 A: 100 mV > 81.92 mV, the shunt register clips
        self.assertEqual(_s16(real[0].read_reg(REG_SHUNT, t)), 32767)
        self.assertAlmostEqual(_s16(real[0].read_reg(REG_CURRENT, t)) * fw.current_lsb, 10.0, delta=0.01)   # pinned at full scale
        # and the right configuration for a 0.1 ohm board shows the limit: full scale is 0.8192 A
        ok = chips(r=0.1); fw2 = EspFirmware(ok, shunt_ohms=0.1, max_current=0.8)
        t = settle(fw2, ok, 0.5)
        self.assertAlmostEqual(_s16(ok[0].read_reg(REG_CURRENT, t)) * fw2.current_lsb, 0.5, delta=0.002)

    def test_noise_and_offset_inputs(self):
        c = INA226(0x40, 0.005, offset_uv=50.0, noise_uv=0.0); fw = EspFirmware([c, INA226(0x41, 0.005)])
        t = settle(fw, [c], 0.0)
        self.assertAlmostEqual(_s16(c.read_reg(REG_CURRENT, t)) * fw.current_lsb, 50e-6 / 0.005, delta=0.0005)   # 50 uV offset = 10 mA at 5 mOhm


class SketchContract(unittest.TestCase):
    def test_the_python_port_uses_the_sketchs_own_constants(self):
        k = parse_sketch_constants(INO)
        self.assertEqual(k, {"shunt_ohms": 0.005, "max_current": 10.0, "period_ms": 10, "addr": (0x40, 0x41), "avg_bits": 0b010, "ct_bits": 0b100})
        fw = EspFirmware(chips(), shunt_ohms=k["shunt_ohms"], max_current=k["max_current"], period_ms=k["period_ms"], avg_bits=k["avg_bits"], ct_bits=k["ct_bits"])
        self.assertEqual((fw.shunt_ohms, fw.max_current, fw.period_ms, fw.avg_bits, fw.ct_bits), (0.005, 10.0, 10, 0b010, 0b100))
        self.assertEqual((fw.chips[0].address, fw.chips[1].address), k["addr"])

    def test_the_sketch_text_has_the_fixes(self):
        with open(INO, encoding="utf-8") as fh:
            src = fh.read()
        code = "\n".join(line.split("//")[0] for line in src.splitlines())             # the comments may quote the bad pattern
        self.assertIsNone(re.search(r"Wire\.read\(\)[^;]*Wire\.read\(\)", code), "two Wire.read() calls in one expression: order is unspecified")
        self.assertIn("0x5449", src)                                                    # chip presence check
        self.assertIn("requestFrom", src); self.assertIn("!= 2", src)                   # a short read is an error
        self.assertIn("(int16_t)rawI", src)                                             # the current register is signed
        self.assertIn("0x4000 | ((uint16_t)AVG_BITS << 9)", src)                       # config built from the named constants
        self.assertIn("0.00512f / (currentLsb * SHUNT_OHMS)", src)                      # the calibration formula the port implements
        self.assertIn("(int32_t)(now - next) < 0", src)                                 # millis() wrap-safe timing
        self.assertIn("NOT TESTED ON HARDWARE", src)                                    # keeps saying so until it has been


class FirmwareLoop(unittest.TestCase):
    def test_boot_header_and_sample_cadence_and_parseable_lines(self):
        fw = EspFirmware(chips())
        self.assertTrue(fw.boot_lines[-1].startswith("H,1,5.0,10000,3355,2,10"))
        lines, t = [], 0.0
        c0, c1 = fw.chips
        for k in range(1000):
            t = k * 0.001
            c0.set_input(t, 2.0, 23.9); c1.set_input(t, 1.0, 23.9)
            lines += fw.loop(t)
        parsed = [parse_line(l) for l in lines]
        self.assertTrue(all(p is not None for p in parsed))
        self.assertAlmostEqual(len(lines), 200, delta=4)                              # 100 sets of 2 channels in one second
        ms = [p[0] for p in parsed if p[1] == "base"]
        self.assertTrue(all(b - a == 10 for a, b in zip(ms, ms[1:])))
        late = [p for p in parsed if p[0] > 200]
        self.assertTrue(all(abs(p[2] - (2000 if p[1] == "base" else 1000)) <= 1 for p in late if p[1] in ("base", "shoulder")))

    def test_a_missing_chip_gives_an_error_line_and_the_other_channel_still_works(self):
        class Dead(INA226):
            def read_reg(self, reg, t): return 0xFFFF if reg == REG_MANUF else 0
        fw = EspFirmware([INA226(0x40, 0.005), Dead(0x41, 0.005)])
        self.assertTrue(any(l.startswith("E,0,ina226 1 not found") for l in fw.boot_lines))
        src = SensorSource(lambda stop: iter(()))
        for l in fw.boot_lines: self.assertTrue(src.feed_line(l))
        self.assertEqual(src.bad, 0); self.assertTrue(src.errors); self.assertEqual(src.header[1], "1")


class EndToEnd(unittest.TestCase):
    def run_twin(self, kt_scale, seconds=40.0):
        cfg = TwinCfg(); twin = Twin(cfg)
        src = SensorSource(lambda stop: iter(()), window_s=0.04)
        sim = EspSim(twin, src, kt_scale=kt_scale)
        for _ in range(800): twin.tick(); sim.step(0.005)
        twin.command({"type": "button", "tag": "START", "down": True})
        frames, nxt, tau_sum, n, err = [], 0.0, {"base": 0.0, "shoulder": 0.0}, 0, []
        for i in range(int(seconds / 0.005)):
            twin.tick(); sim.step(0.005)
            if i == 80: twin.command({"type": "button", "tag": "START", "down": False})
            for ch in tau_sum: tau_sum[ch] += abs(getattr(twin.arm, ch).tau)
            n += 1
            if i * 0.005 >= nxt:
                nxt += 0.04
                lat = src.latest(now=sim.wall0 + sim.t)
                frames.append({ch: {"tau": tau_sum[ch] / n} for ch in tau_sum} | {"sensors": lat})
                tau_sum = {"base": 0.0, "shoulder": 0.0}; n = 0
        return cfg, frames, src, sim

    def test_the_chain_from_the_twin_to_the_host_recovers_the_torque_constant(self):
        cfg, frames, src, sim = self.run_twin(1.25)
        res = fit_log(frames, cfg, smooth=3)
        self.assertAlmostEqual(res["shoulder"]["kt"], cfg.shoulder.kt * 1.25, delta=cfg.shoulder.kt * 1.25 * 0.10)
        self.assertGreater(res["shoulder"]["r2"], 0.9)
        self.assertEqual(src.bad, 0); self.assertGreater(src.count, 7000)             # ~100 Hz x 2 channels for 44 s
        self.assertEqual(src.header[1], "1")
        v = [f["sensors"]["shoulder"]["mV"] for f in frames if "shoulder" in f["sensors"]]
        self.assertTrue(all(20000 < x <= 24000 for x in v))                           # supply sag stays sensible

    def test_hub_runs_the_simulated_logger_in_the_sensors_slot(self):
        twin = Twin(); hub = Hub(twin)
        src = SensorSource(lambda stop: iter(()), label="esp-sim"); hub.register("sensors", src.start()); hub.tickers.append(EspSim(twin, src))
        t_end = time.time() + 2.0
        while time.time() < t_end:
            for _ in range(10): twin.tick()
            hub.step(); time.sleep(0.01)
        src.stop()
        s = hub.snapshot("sim")
        self.assertIn("base", s["sensors"]); self.assertIn("shoulder", s["sensors"]); self.assertGreater(s["sensors"]["base"]["mV"], 20000)
        self.assertTrue(hub.status()["live"]["sensors"]["info"].startswith("esp-sim"))


if __name__ == "__main__":
    unittest.main()
