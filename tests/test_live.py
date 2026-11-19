import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from live.modbus_map import ModbusMap
from live.plc_reader import PlcLiveSource, ReadOnlyClient
from live.scan import find_offsets, read_all_words
from twin.modbus_server import TwinModbusServer
from twin.sim import Twin


def running_twin():
    t = Twin()
    for _ in range(800):
        t.tick()
    t.command({"type": "button", "tag": "START", "down": True})
    for _ in range(60):
        t.tick()
    t.command({"type": "button", "tag": "START", "down": False})
    for _ in range(1400):                    # mid-cycle, magnet likely on, taught data present
        t.tick()
    return t


class LiveReader(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.twin = running_twin()
        cls.map = ModbusMap(coil_base={"Q": 300, "M": 2000}, discrete_base={"I": 50},
                            holding_base={"V": 100, "M": 9000})        # deliberately not the defaults
        cls.srv = TwinModbusServer(cls.twin, cls.map, port=0).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def test_poll_matches_twin_memory(self):
        src = PlcLiveSource("127.0.0.1", self.srv.port, mapping=self.map,
                            client_factory=lambda: ReadOnlyClient("127.0.0.1", self.srv.port))
        src._client = src._factory()
        self.assertTrue(src._client.connect())
        src.poll_once()
        m, tm = src.mem, self.twin.plc.mem
        for a in ("MD600", "VD1044", "VD2020", "VD2300", "VD2404", "VD2416", "VW2036", "M30.1", "M31.2", "M50.1", "Q0.7", "I0.0"):
            self.assertEqual(m.read(a), tm.read(a), a)
        snap = src.snapshot()
        self.assertEqual(snap["source"], "plc")
        import math
        cfg = self.twin.cfg           # PDO feedback lags the physics by one scan, so compare with the PLC's own counts
        self.assertAlmostEqual(snap["base"]["deg"], math.degrees(cfg.base.count_to_angle(tm.read("MD600"))), places=6)
        self.assertAlmostEqual(snap["shoulder"]["deg"], math.degrees(cfg.shoulder.count_to_angle(tm.read("VD1044"))), places=6)
        self.assertAlmostEqual(snap["shoulder"]["deg"], math.degrees(self.twin.arm.shoulder.theta), delta=0.5)
        src._client.close()

    def test_reader_cannot_write_and_server_refuses_writes(self):
        c = ReadOnlyClient("127.0.0.1", self.srv.port)
        self.assertFalse(any(hasattr(c, n) for n in ("write_register", "write_coil", "write_words", "write_bits")))
        c.connect()
        rr = c._c.write_register(100 + 1010, 1, **c._kw())             # raw client, bypassing the wrapper
        self.assertTrue(rr.isError())
        self.assertNotEqual(self.twin.plc.mem.read("VD2020"), 1)
        c.close()

    def test_scan_finds_offsets(self):
        c = ReadOnlyClient("127.0.0.1", self.srv.port)
        c.connect()
        regs = read_all_words(c.read_words, limit=12000)
        mem = self.twin.plc.mem
        known = {k: mem.read(k) for k in ("VD2020", "VW2036", "VD2300", "VD1044")}
        votes = find_offsets(regs, known)
        self.assertEqual(votes["V"].most_common(1)[0][0], 100)
        c.close()

    def test_unreachable_plc_reports_error_without_crashing(self):
        src = PlcLiveSource("127.0.0.1", 1, mapping=self.map).start()
        import time
        time.sleep(0.6)
        self.assertFalse(src.status()["connected"])
        self.assertIsNone(src.snapshot())
        src.stop()


if __name__ == "__main__":
    unittest.main()


class HubIntegration(unittest.TestCase):
    def test_plc_source_as_ghost_through_hub(self):
        import tempfile, time
        from twin.server import Hub
        plc_twin = running_twin()                                  # stands in for the real PLC
        srv = TwinModbusServer(plc_twin, ModbusMap(), port=0).start()
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(Twin(), d)
            src = PlcLiveSource("127.0.0.1", srv.port, mapping=ModbusMap(), hz=50).start()
            hub.register("plc", src)
            deadline = time.time() + 5
            while time.time() < deadline and not hub.snapshot("plc"):
                time.sleep(0.05)
            ghost = hub.snapshot("plc")
            self.assertEqual(ghost["source"], "plc")
            self.assertTrue(hub.status()["live"]["plc"]["connected"])
            src.stop()
        srv.shutdown()
        srv.server_close()
