"""Kinco K615S-16DT model: scan cycle, digital I/O, CANopen PDO exchange with the two drives."""
from __future__ import annotations

import json
import os

from .config import TwinCfg
from .il import ILMachine, Memory, Program

PROGRAM_PATH = os.path.join(os.path.dirname(__file__), "plc", "MAIN_MAIN.ilp")

# PDO map [doc: docs/PLC_Program_and_Communication.md section 2.2]
# (node, direction, COB-ID, object, PLC address, bits)
PDO_MAP = [
    (1, "RX", 0x201, "6040 Controlword", "VW1000", 16),
    (1, "RX", 0x201, "6060 Mode of operation", "VB1010", 8),
    (1, "RX", 0x301, "607A Target position", "VD1002", 32),
    (1, "RX", 0x301, "60FF Target velocity", "VD1006", 32),
    (1, "RX", 0x401, "6083 Profile acceleration", "VD1014", 32),
    (1, "TX", 0x181, "6041 Statusword", "VW1012", 16),
    (1, "TX", 0x181, "6060 Mode of operation", "VB1011", 8),
    (1, "TX", 0x281, "6064 Position actual", "MD600", 32),
    (1, "TX", 0x281, "606C Velocity actual", "VD1018", 32),
    (1, "TX", 0x381, "6078 Current actual", "VW1022", 16),
    (2, "RX", 0x202, "6040 Controlword", "VW1024", 16),
    (2, "RX", 0x202, "6060 Mode of operation", "VB1026", 8),
    (2, "RX", 0x302, "607A Target position", "VD1028", 32),
    (2, "RX", 0x302, "60FF Target velocity", "VD1032", 32),
    (2, "RX", 0x402, "6083 Profile acceleration", "VD1036", 32),
    (2, "RX", 0x402, "260A Electronic gear numerator", "VW1040", 16),
    (2, "TX", 0x182, "6041 Statusword", "VW1042", 16),
    (2, "TX", 0x182, "6060 Mode of operation", "VB1027", 8),
    (2, "TX", 0x282, "6064 Position actual", "VD1044", 32),
    (2, "TX", 0x282, "606C Velocity actual", "VD1048", 32),
    (2, "TX", 0x382, "607A Target position (readback)", "VD1052", 32),
]

# retentive PLC data that the real controller keeps across power cycles
RETENTIVE = (["VD2020", "VD2030", "VW2036"]
             + [f"VD{2300 + 4 * i}" for i in range(5)] + [f"VD{2400 + 4 * i}" for i in range(5)])


class PLC:
    def __init__(self, cfg: TwinCfg) -> None:
        self.cfg = cfg
        self.mem = Memory()
        with open(PROGRAM_PATH, "r", encoding="latin-1") as fh:
            src = fh.read()
        if cfg.fix_vw2400_overlap:     # move the C2 mirror from %VW2400 (aliases %VD2400) to %VW2450
            src = src.replace("%VW2400", "%VW2450")
        if cfg.fix_estop_magnet_latch:    # proposed patch: E-stop (I0.0 low) must drop the auto-magnet latch
            src = src.rstrip("\r\n") + "\r\n(* Network 39 *)\r\n(*PATCH: E-STOP CLEARS AUTO MAGNET LATCH*)\r\nLDN    %I0.0\r\nR    %M30.6\r\n"
        self.program = Program.parse(src)
        self.vm = ILMachine(self.program, self.mem, cfg.timer_base_ms)
        self.cycle_addr = "VW2450" if cfg.fix_vw2400_overlap else "VW2400"
        self.run = True
        self.can_online = False
        self.t = 0.0
        self.load_defaults()

    # --- retentive data ----------------------------------------------------
    def load_defaults(self) -> None:
        c, m = self.cfg, self.mem
        for i, (b, s) in enumerate(c.default_points_deg):
            m.write(f"VD{2300 + 4 * i}", c.base.angle_to_count(b * 3.141592653589793 / 180))
            m.write(f"VD{2400 + 4 * i}", c.shoulder.angle_to_count(s * 3.141592653589793 / 180))
        m.write("VD2020", c.default_speed_rpm[0])
        m.write("VD2030", c.default_speed_rpm[1])
        m.write("VW2036", c.default_cycles)

    def save_retentive(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump({a: self.mem.read(a) for a in RETENTIVE}, fh, indent=1)

    def load_retentive(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path) as fh:
            for a, v in json.load(fh).items():
                self.mem.write(a, v)
        return True

    # --- inputs / outputs --------------------------------------------------
    def set_inputs(self, estop_pressed: bool, reset_pressed: bool) -> None:
        self.mem.write("I0.0", 0 if estop_pressed else 1)    # NC e-stop contact
        self.mem.write("I0.1", 1 if reset_pressed else 0)

    @property
    def magnet(self) -> bool:
        return bool(self.mem.read("Q0.7"))

    # --- CANopen PDO exchange ---------------------------------------------
    def pdo_tx(self, base, shoulder) -> None:
        """Drives -> PLC (TPDOs), only when the CANopen network is operational."""
        m = self.mem
        m.write("VW1012", base.statusword)
        m.write("MD600", base.pos_count)
        m.write("VD1018", base.vel_rpm)
        m.write("VW1022", base.current_ma)
        m.write("VW1042", shoulder.statusword)
        m.write("VD1044", shoulder.pos_count)
        m.write("VD1048", shoulder.vel_rpm)
        m.write("VD1052", shoulder.cmd.target_count)

    def pdo_rx(self, base, shoulder) -> None:
        """PLC -> drives (RPDOs)."""
        m = self.mem
        for ax, cw, mode, tp, tv, acc in (
            (base, "VW1000", "VB1010", "VD1002", "VD1006", "VD1014"),
            (shoulder, "VW1024", "VB1026", "VD1028", "VD1032", "VD1036"),
        ):
            ax.cmd.controlword = m.get("V", 2, int(cw[2:]), signed=False)
            ax.cmd.mode = m.get("V", 1, int(mode[2:]), signed=False)
            ax.cmd.target_count = m.read(tp)
            ax.cmd.target_rpm = m.read(tv)
            ax.cmd.accel_rpms = m.read(acc)

    # --- scan --------------------------------------------------------------
    def scan(self, dt_ms: float) -> None:
        # %SM0.3: 1 s clock (50 % duty) -- see config
        half = self.cfg.sm03_period_s / 2
        self.mem.write("SM0.3", 1 if (self.t % self.cfg.sm03_period_s) >= half else 0)
        if self.run:
            self.vm.scan(dt_ms)
        self.t += dt_ms / 1000.0
