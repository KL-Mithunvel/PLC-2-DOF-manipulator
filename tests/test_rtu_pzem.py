"""Modbus RTU master, PZEM-017 driver and the simulated meter/bus. No hardware, no serial port."""
import os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.pzem import REGISTER_MAP_VERIFIED, SimBus, SimPzem017, Pzem017
from live.rtu import RtuCrcError, RtuException, RtuMaster, RtuTimeout, crc16, crc_ok, with_crc


def rig(**bus_kw):
    dev = SimPzem017(address=1)
    bus = SimBus([dev], **bus_kw)
    return dev, bus, RtuMaster(bus, retries=2, allow_write=True)


class Crc(unittest.TestCase):
    def test_known_vectors(self):
        self.assertEqual(with_crc(bytes.fromhex("010300000 00A".replace(" ", ""))), bytes.fromhex("01030000000AC5CD"))     # the textbook example
        self.assertEqual(crc16(bytes.fromhex("0103000000 0A".replace(" ", ""))), 0xCDC5)
        self.assertTrue(crc_ok(bytes.fromhex("01030000000AC5CD"))); self.assertFalse(crc_ok(bytes.fromhex("01030000000AC5CC")))


class MasterAndDevice(unittest.TestCase):
    def test_register_map_is_flagged_unverified(self):
        self.assertFalse(REGISTER_MAP_VERIFIED)               # whoever checks the datasheet flips this deliberately

    def test_read_quantisation_power_and_energy(self):
        dev, bus, m = rig()
        for _ in range(3600):                                  # one hour at 24.00 V, 3.21 A in 1 s steps
            dev.update(24.0, 3.214, 1.0)
        r = Pzem017(m, 1).read()
        self.assertAlmostEqual(r["voltage_v"], 24.00, places=2); self.assertAlmostEqual(r["current_a"], 3.21, places=2)     # 0.01 A resolution
        self.assertAlmostEqual(r["power_w"], 77.1, delta=0.1)                                                                # 24 x 3.214 = 77.1 W
        self.assertEqual(r["energy_wh"], 77.0)                                                                               # 77.1 Wh truncated to 1 Wh
        self.assertFalse(r["low_alarm"]); self.assertFalse(r["high_alarm"])

    def test_power_beyond_16_bits_uses_the_high_register(self):
        dev, bus, m = rig()
        dev.update(250.0, 300.0, 1.0)                          # 75 kW -> 750000 x 0.1 W does not fit in 16 bits
        self.assertAlmostEqual(Pzem017(m, 1).read()["power_w"], 75000.0, delta=0.2)

    def test_two_meters_share_one_bus_by_address(self):
        a, b = SimPzem017(address=1), SimPzem017(address=2)
        bus = SimBus([a, b]); m = RtuMaster(bus)
        a.update(24.0, 1.0, 1.0); b.update(23.5, 4.0, 1.0)
        self.assertAlmostEqual(Pzem017(m, 1).read()["current_a"], 1.0, places=2)
        self.assertAlmostEqual(Pzem017(m, 2).read()["current_a"], 4.0, places=2)

    def test_setup_needs_explicit_permission(self):
        dev, bus, _ = rig()
        ro = RtuMaster(bus)                                    # default: read-only by construction
        for call in (lambda: ro.write_single_register(1, 2, 5), lambda: ro.raw_command(1, 0x42), lambda: Pzem017(ro, 1).set_address(5)):
            with self.assertRaises(PermissionError): call()
        self.assertEqual(dev.address, 1)

    def test_address_range_and_energy_reset_setup(self):
        dev, bus, m = rig()
        p = Pzem017(m, 1)
        dev.update(24.0, 10.0, 3600.0)
        self.assertGreater(p.read()["energy_wh"], 200)
        p.reset_energy(); self.assertEqual(p.read()["energy_wh"], 0.0)
        p.set_range(100); self.assertEqual(p.read_settings()["range_a"], 100)
        with self.assertRaises(ValueError): p.set_range(75)
        p.set_address(7); self.assertEqual(dev.address, 7); self.assertEqual(p.slave, 7)
        self.assertEqual(p.read()["voltage_v"], 24.0)          # answers at the new address
        with self.assertRaises(RtuTimeout): Pzem017(m, 1).read()   # and no longer at the old one
        with self.assertRaises(ValueError): p.set_address(0)

    def test_modbus_exception_is_raised(self):
        dev, bus, m = rig()
        with self.assertRaises(RtuException) as cm: m.read_input_registers(1, 6, 8)     # past the end of the register file
        self.assertEqual(cm.exception.code, 2); self.assertEqual(m.exceptions, 1)

    def test_corrupted_replies_are_retried_and_counted(self):
        dev, bus, m = rig(corrupt=0.5, seed=3)
        dev.update(24.0, 2.0, 1.0)
        ok = fail = 0
        for _ in range(60):
            try:
                m.read_input_registers(1, 0, 2); ok += 1
            except RtuCrcError:
                fail += 1
        self.assertGreater(m.crc_errors, 10); self.assertGreater(ok, 40)                 # most reads succeed on a retry
        self.assertLess(fail, 15)

    def test_dropped_requests_time_out_and_a_cut_line_fails_cleanly(self):
        dev, bus, m = rig(drop=1.0)
        with self.assertRaises(RtuTimeout): m.read_input_registers(1, 0, 8)
        self.assertEqual(m.timeouts, 3); self.assertEqual(m.requests, 3)                 # one try plus two retries
        bus.drop = 0.0; bus.cut(True)
        with self.assertRaises(RtuTimeout): m.read_input_registers(1, 0, 8)
        bus.cut(False)
        self.assertEqual(len(m.read_input_registers(1, 0, 8)), 8)

    def test_gain_error_and_noise_are_applied(self):
        dev = SimPzem017(gain_error=0.01, noise_a=0.0)
        dev.update(24.0, 5.0, 1.0)
        self.assertAlmostEqual(Pzem017(RtuMaster(SimBus([dev])), 1).read()["current_a"], 5.05, places=2)

    def test_bad_arguments(self):
        dev, bus, m = rig()
        with self.assertRaises(ValueError): m.read_input_registers(1, 0, 0)
        with self.assertRaises(ValueError): m.read_input_registers(1, 0, 126)


if __name__ == "__main__":
    unittest.main()
