"""Stage 2: live PLC source with diagnostics, raw blocks, poll groups, reconnect, session recording. No hardware needed:
everything runs against the twin's own Modbus server."""
import os, sys, tempfile, threading, time, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bag import BagReader
from live.modbus_map import ModbusMap
from live.plc_reader import PlcLiveSource, ReadOnlyClient, check_plan, make_groups
from live.raw import apply_record, pack_bits, unpack_bits
from twin.diag import PollStats, Rolling
from twin.il import Memory
from twin.modbus_server import TwinModbusServer
from twin.server import Hub
from twin.sim import Twin

MAP = ModbusMap()          # the real defaults: the twin serves exactly the Kinco mapping


def running_twin():
    t = Twin()
    for _ in range(800): t.tick()
    t.command({"type": "button", "tag": "START", "down": True})
    for _ in range(60): t.tick()
    t.command({"type": "button", "tag": "START", "down": False})
    for _ in range(1400): t.tick()
    return t


class Helpers(unittest.TestCase):
    def test_rolling_and_stats(self):
        r = Rolling(5)
        for x in (1, 2, 3, 4, 5, 6): r.add(x)
        s = r.summary()
        self.assertEqual(s["n"], 5); self.assertEqual(s["max"], 6); self.assertEqual(s["min"], 2); self.assertAlmostEqual(s["mean"], 4.0)
        st = PollStats()
        for i in range(5): st.record_cycle("fast", 10 + i * 0.1, 3.0)
        st.record_block("coil:M10", 2.0); st.error("x"); st.reconnect()
        d = st.summary(now=11.0)
        self.assertEqual(d["polls"], 5); self.assertEqual(d["errors"], 1); self.assertEqual(d["reconnects"], 1)
        self.assertAlmostEqual(d["groups"]["fast"]["period_ms"]["mean"], 100.0, delta=0.5)
        self.assertAlmostEqual(d["groups"]["fast"]["rate_hz"], 10.0, delta=0.1)
        self.assertLess(d["groups"]["fast"]["jitter_ms"], 0.5)
        self.assertEqual(Rolling().summary(), {"n": 0})

    def test_bit_packing_roundtrip(self):
        for n in (1, 7, 8, 9, 64, 352):
            bits = [(i * 7 + 3) % 5 == 0 for i in range(n)]
            self.assertEqual(unpack_bits(pack_bits(bits), n), [1 if b else 0 for b in bits])

    def test_default_plan_never_splits_a_32_bit_value(self):
        self.assertEqual(check_plan(make_groups()), [])
        bad = {"x": {"hz": 1, "blocks": [("word", "V", 2300, 6), ("word", "V", 2306, 10)]}}      # VD2304 straddles two requests? no: separate blocks
        msgs = check_plan(bad, dwords=[("V", 2304), ("V", 2400)])
        self.assertTrue(any("split" in m for m in msgs), msgs)
        self.assertTrue(any("not read" in m for m in msgs), msgs)


class Polling(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.twin = running_twin()
        cls.srv = TwinModbusServer(cls.twin, MAP, port=0).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown(); cls.srv.server_close()

    def source(self, **kw):
        return PlcLiveSource("127.0.0.1", self.srv.port, mapping=MAP,
                             client_factory=kw.pop("client_factory", lambda: ReadOnlyClient("127.0.0.1", self.srv.port)), **kw)

    def test_raw_record_rebuilds_the_memory(self):
        src = self.source()
        src._client = src._factory(); src._client.connect()
        recs = [src.poll_group("fast"), src.poll_group("slow")]
        mem = Memory()
        for r in recs: apply_record(r, mem)
        for a in ("MD600", "VD1044", "VD2020", "VD2300", "VD2404", "VW2036", "M30.1", "M31.2", "Q0.7", "I0.0", "VW2400"):
            self.assertEqual(mem.read(a), src.mem.read(a), a)
        for r in recs:
            self.assertEqual(r["blocks"][0]["kind"] in ("discrete", "coil", "word", "wordbits"), True)
            for b in r["blocks"]:
                self.assertLessEqual(b["t0"], b["t1"]); self.assertLessEqual(r["t_mono"], b["t0"])
        d = src.diag()
        self.assertEqual(d["polls"], 2); self.assertIn("fast", d["groups"]); self.assertIn("slow", d["groups"])
        self.assertTrue(all(v["n"] >= 1 for v in d["blocks"].values()))
        self.assertEqual(len(src.drain_raw()), 2); self.assertEqual(src.drain_raw(), [])
        src._client.close()

    def test_groups_run_at_their_own_rates(self):
        src = self.source(hz=20.0, slow_hz=2.0).start()
        time.sleep(2.6)
        src.stop()
        g = src.diag()["groups"]
        self.assertGreater(g["fast"]["cycle_ms"]["n"], 3 * g["slow"]["cycle_ms"]["n"])
        self.assertAlmostEqual(g["fast"]["rate_hz"], 20.0, delta=4.0)
        self.assertAlmostEqual(g["slow"]["rate_hz"], 2.0, delta=0.6)
        self.assertEqual(src.diag()["errors"], 0)

    def test_added_delay_shows_up_in_latency(self):
        class Slow(ReadOnlyClient):
            def read_words(self, *a, **k): time.sleep(0.03); return super().read_words(*a, **k)
            def read_bits(self, *a, **k): time.sleep(0.03); return super().read_bits(*a, **k)
        src = self.source(client_factory=lambda: Slow("127.0.0.1", self.srv.port))
        src._client = src._factory(); src._client.connect()
        for _ in range(3): src.poll_group("fast")
        b = src.diag()["blocks"]
        self.assertTrue(all(v["mean"] >= 28 for v in b.values()), b)
        self.assertGreaterEqual(src.diag()["groups"]["fast"]["cycle_ms"]["mean"], 5 * 28)
        src._client.close()

    def test_dropped_requests_are_counted_and_recovered(self):
        n = {"i": 0}
        class Flaky(ReadOnlyClient):
            def read_bits(self, *a, **k):
                n["i"] += 1
                if n["i"] % 7 == 0: raise IOError("injected drop")
                return super().read_bits(*a, **k)
        src = self.source(hz=40.0, slow_hz=4.0, client_factory=lambda: Flaky("127.0.0.1", self.srv.port))
        src.stats  # noqa
        src._thread = None
        src.start()
        time.sleep(7.0)           # the loop backs off 2 s after each error
        src.stop()
        d = src.diag()
        self.assertGreaterEqual(d["errors"], 2); self.assertGreaterEqual(d["reconnects"], 1)
        self.assertGreater(d["polls"], 4)
        ev = src.drain_events()
        self.assertTrue(any(e["kind"] == "error" for e in ev)); self.assertTrue(any("connected" in e["text"] for e in ev))

    def test_reconnect_after_connection_loss(self):
        state = {"down": False}
        class Broken(ReadOnlyClient):
            def connect(self):
                return False if state["down"] else super().connect()
            def read_words(self, *a, **k):
                if state["down"]: raise IOError("link down")
                return super().read_words(*a, **k)
            def read_bits(self, *a, **k):
                if state["down"]: raise IOError("link down")
                return super().read_bits(*a, **k)
        src = self.source(hz=20.0, slow_hz=2.0, client_factory=lambda: Broken("127.0.0.1", self.srv.port)).start()
        time.sleep(1.0); self.assertTrue(src.connected)
        state["down"] = True
        time.sleep(3.0); self.assertFalse(src.connected); self.assertGreaterEqual(src.diag()["errors"], 1)
        state["down"] = False
        time.sleep(4.0)
        ok, d = src.connected, src.diag()
        src.stop()
        self.assertTrue(ok); self.assertGreaterEqual(d["reconnects"], 1)


class SessionRecording(unittest.TestCase):
    def test_one_bag_with_every_topic(self):
        twin = running_twin()
        srv = TwinModbusServer(twin, MAP, port=0).start()
        with tempfile.TemporaryDirectory() as d:
            hub = Hub(twin, d, record_format="bag")
            src = PlcLiveSource("127.0.0.1", srv.port, cfg=twin.cfg, mapping=MAP, hz=20.0, slow_hz=2.0,
                                client_factory=lambda: ReadOnlyClient("127.0.0.1", srv.port)).start()
            hub.register("plc", src)

            class FakeVnc:
                png = b"\x89PNG fake"; frames = 3; frame_t = time.time()
                def status(self): return {"connected": True, "info": "fake", "age_s": 0.1}
            hub.hmi_vnc = FakeVnc(); hub.hmi_frame_period = 0.0
            time.sleep(1.0)                                   # polls happen before recording; they must NOT leak into the bag
            res = hub.start_recording("S1", {"notes": "unit test", "payload_kg": 5})
            self.assertTrue(res["ok"]); self.assertEqual(res["sources"], ["sim", "plc"])
            t_end = time.time() + 3.5
            while time.time() < t_end:
                for _ in range(4): twin.tick()
                hub.step(); time.sleep(0.02)
            hub.stop_recording()
            src.stop(); srv.shutdown(); srv.server_close()
            r = BagReader(res["file"])
            for topic in ("twin/state", "plc/decoded", "plc/raw", "diag", "events", "hmi/frame"):
                self.assertIn(topic, r.topics, (topic, r.topics))
            self.assertEqual(r.meta["notes"], "unit test"); self.assertEqual(r.meta["payload_kg"], 5)
            raws = [m for m in r.messages(["plc/raw"])]
            self.assertGreater(len(raws), 20)
            self.assertGreaterEqual(min(m.payload["t_mono"] for m in raws), r.t_mono_range[0] - 0.5)    # nothing from before the recording
            tm = [m.payload["t_mono"] for m in raws if m.payload["group"] == "fast"]
            self.assertEqual(tm, sorted(tm))
            mem = Memory()
            for m in raws: apply_record(m.payload, mem)
            self.assertEqual(mem.read("VD2020"), twin.plc.mem.read("VD2020"))
            diags = [m.payload for m in r.messages(["diag"])]
            self.assertTrue(any(x.get("source") == "plc" and x["polls"] > 0 for x in diags)); self.assertTrue(any(x.get("source") == "hub" for x in diags))
            ev = [m.payload for m in r.messages(["events"])]
            self.assertTrue(any(e.get("source") == "plc" for e in ev), ev[:3])
            fr = next(m.payload for m in r.messages(["hmi/frame"]))
            self.assertTrue(os.path.exists(os.path.join(d, fr["file"])))
            self.assertEqual(open(os.path.join(d, fr["file"]), "rb").read(), FakeVnc.png)


if __name__ == "__main__":
    unittest.main()
