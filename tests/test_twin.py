import os, sys, unittest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from twin.il import Memory, ILMachine, Program
from twin.sim import Twin


class IL(unittest.TestCase):
    def test_gating_compare_timer(self):
        m = Memory(); m.write("I0.0", 1)
        p = Program.parse("(* Network 0 *)\nLD %I0.0\nMOVE 5, %VW10\nGT %VW10, 3\nTON T1, 2\nST %Q0.0\n")
        vm = ILMachine(p, m, timer_base_ms=10)
        vm.scan(10); self.assertEqual(m.read("VW10"), 5); self.assertEqual(m.read("Q0.0"), 0)
        vm.scan(10); self.assertEqual(m.read("Q0.0"), 1)

    def test_little_endian_alias(self):          # the %VW2400 / %VD2400 overlap of the real program
        m = Memory(); m.write("VD2400", -57646473); m.write("VW2400", 0)
        self.assertEqual(m.read("VD2400"), -57671680)


class Cycle(unittest.TestCase):
    def run_for(self, t, s):
        for _ in range(int(s / 0.005)): t.tick()

    def test_auto_cycles_with_5kg(self):
        t = Twin(); self.run_for(t, 4)
        t.command({"type": "button", "tag": "START", "down": True}); self.run_for(t, 0.3)
        t.command({"type": "button", "tag": "START", "down": False})
        peak = 0
        for _ in range(int(60 / 0.005)):
            t.tick(); peak = max(peak, abs(t.arm.shoulder.tau))
            if t.plc.mem.read("M30.2"): break
        self.assertEqual(t.arm.picks, 3); self.assertEqual(t.arm.drops, 3)
        self.assertGreater(peak, 28)             # ~31 N.m holding torque with 5 kg (paper: 30.9)
        self.assertLess(peak, t.cfg.shoulder.tau_peak)

if __name__ == "__main__": unittest.main()
