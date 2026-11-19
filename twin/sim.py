"""The digital twin: PLC + CANopen + two drives + arm + HMI + operator panel, stepped together."""
from __future__ import annotations

import math
import os
import threading
import time
from collections import deque

from .config import TwinCfg
from .plc import PDO_MAP, PLC
from .plant import Arm

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "twin_state.json")

# HMI widget -> PLC address. Bits are momentary unless noted. Addresses inferred from the ladder
# (docs/PLC_Program_and_Communication.md section 3); widget tags are from the DTools screenshots.
HMI_BUTTONS = {
    "START": "M30.0", "STOP": "M30.2", "RESET": "M30.4",          # Auto screen (SB4, SB0, SB1)
    "BASE_FWD": "M20.1", "BASE_REV": "M20.2",                      # Manual / Setting (SB2, SB1)
    "SH_UP": "M20.3", "SH_DOWN": "M20.4",                          # (SB0, SB3)
    "TEACH0": "M22.0", "TEACH1": "M22.1", "TEACH2": "M22.2",       # Setting screen TEACH buttons
    "TEACH3": "M22.3", "TEACH4": "M22.4",
}
HMI_SWITCH = {"MAGNET": "M20.5"}                                   # Manual screen SW0 (maintained)
HMI_NUMERIC = {"BASE_SPEED": "VD2020", "SH_SPEED": "VD2030", "CYCLES": "VW2036"}


class Twin:
    def __init__(self, cfg: TwinCfg | None = None, persist: bool = False) -> None:
        self.cfg = cfg or TwinCfg()
        self.persist = persist
        self.lock = threading.RLock()
        self.plc = PLC(self.cfg)
        self.arm = Arm(self.cfg)
        self.estop = False
        self.reset_btn = False
        self.powered = True
        self.paused = False
        self.speed = 1.0
        self.t = 0.0                    # simulated seconds
        self.can_t = 0.0
        self.hmi_screen = "AUTO"
        self.scope: deque = deque(maxlen=2000)
        self.log: deque = deque(maxlen=200)
        self._acc = 0.0
        self._last_wall = time.perf_counter()
        self._scope_t = 0.0
        self._prev_bits = {}
        self.cycle_started_at: float | None = None
        if persist:
            self.plc.load_retentive(STATE_FILE)
        self._update_pick_site(force=True)
        self.note("power on")

    # ------------------------------------------------------------------ log
    def note(self, msg: str) -> None:
        self.log.append(f"{self.t:8.2f}s  {msg}")

    # ------------------------------------------------------------------ stepping
    def tick(self) -> None:
        """One PLC scan (+ the physics sub-steps that fit in it)."""
        cfg, plc, arm = self.cfg, self.plc, self.arm
        if not self.powered:
            return
        dt_ms = cfg.scan_ms
        # CANopen master comes up after the power-on delay
        if not plc.can_online:
            self.can_t += dt_ms / 1000
            if self.can_t >= cfg.can_boot_delay_s:
                plc.can_online = True
                self.note("CANopen network operational (nodes 1, 2)")
        plc.set_inputs(self.estop, self.reset_btn)
        if plc.can_online:
            plc.pdo_tx(arm.base, arm.shoulder)
        plc.scan(dt_ms)
        if plc.can_online:
            plc.pdo_rx(arm.base, arm.shoulder)
        n = max(1, int(round(dt_ms / cfg.physics_ms)))
        for _ in range(n):
            arm.step(cfg.physics_ms / 1000, plc.magnet)
        self.t += dt_ms / 1000
        self._update_pick_site()
        self._edge_log()
        self._scope_t += dt_ms / 1000
        if self._scope_t >= 0.04:
            self._scope_t = 0.0
            self._sample_scope()

    def advance(self) -> None:
        """Advance by wall-clock time x speed (call regularly from the run loop)."""
        now = time.perf_counter()
        wall = min(now - self._last_wall, 0.25)
        self._last_wall = now
        if self.paused:
            return
        self._acc += wall * self.speed
        step = self.cfg.scan_ms / 1000
        n = 0
        while self._acc >= step and n < 400:
            self.tick()
            self._acc -= step
            n += 1
        if n == 400:
            self._acc = 0.0

    # ------------------------------------------------------------------ helpers
    def _update_pick_site(self, force: bool = False) -> None:
        m, c = self.plc.mem, self.cfg
        b = c.base.count_to_angle(m.read("VD2308"))
        s = c.shoulder.count_to_angle(m.read("VD2408"))
        tip = self.arm.fk(b, s)[2]
        site = self.arm.pick_site
        if force or site is None or math.dist(site[:2], tip[:2]) > 1e-3:
            part = self.arm.part
            self.arm.pick_site = None
            self.arm.set_pick_site(tip)
            if part is not None and part.state == "free":
                part.pos = list(self.arm.pick_site)

    def _sample_scope(self) -> None:
        a, m = self.arm, self.plc.mem
        self.scope.append({
            "t": round(self.t, 3),
            "base_deg": round(math.degrees(a.base.theta), 3),
            "sh_deg": round(math.degrees(a.shoulder.theta), 3),
            "base_ref": round(math.degrees(a.base.ref), 3),
            "sh_ref": round(math.degrees(a.shoulder.ref), 3),
            "base_rpm": a.base.vel_rpm, "sh_rpm": a.shoulder.vel_rpm,
            "base_nm": round(a.base.tau, 2), "sh_nm": round(a.shoulder.tau, 2),
            "sh_grav": round(a.shoulder.t_ext, 2),
            "mag": int(m.read("Q0.7")),
        })

    def _edge_log(self) -> None:
        m = self.plc.mem
        for name, addr in (("auto running", "M30.1"), ("auto stop/complete", "M30.2"), ("homing", "M40.0"),
                           ("magnet", "Q0.7"), ("base at home", "M50.1"), ("shoulder at home", "M50.0")):
            v = m.read(addr)
            if self._prev_bits.get(addr) is not None and v != self._prev_bits[addr]:
                self.note(f"{name}: {'ON' if v else 'OFF'}")
                if addr == "M30.1" and v:
                    self.cycle_started_at = self.t
            self._prev_bits[addr] = v
        while self.arm.events:
            self.note(self.arm.events.pop(0))

    # ------------------------------------------------------------------ commands (UI)
    def command(self, c: dict) -> dict:
        with self.lock:
            kind = c.get("type")
            m = self.plc.mem
            if kind == "button":
                addr = HMI_BUTTONS.get(c["tag"])
                if addr:
                    m.write(addr, 1 if c.get("down") else 0)
            elif kind == "switch":
                addr = HMI_SWITCH.get(c["tag"])
                if addr:
                    m.write(addr, 1 if c.get("on") else 0)
            elif kind == "numeric":
                addr = HMI_NUMERIC.get(c["tag"], c.get("addr"))
                if addr:
                    m.write(addr, int(c["value"]))
            elif kind == "estop":
                self.estop = bool(c.get("pressed"))
                self.note("E-STOP pressed" if self.estop else "E-STOP released")
            elif kind == "reset_btn":
                self.reset_btn = bool(c.get("down"))
            elif kind == "power":
                self.set_power(bool(c.get("on")))
            elif kind == "pause":
                self.paused = bool(c.get("on"))
            elif kind == "step":
                self.tick()
            elif kind == "speed":
                self.speed = max(0.1, min(20.0, float(c["value"])))
            elif kind == "payload":
                self.cfg.arm.payload = max(0.0, min(15.0, float(c["value"])))
                if self.arm.part:
                    self.arm.part.mass = self.cfg.arm.payload
                self.note(f"payload set to {self.cfg.arm.payload:.1f} kg")
            elif kind == "feeder":
                self.cfg.arm.feeder = bool(c.get("on"))
            elif kind == "spawn":
                if self.arm.part is None:
                    self.arm.spawn_part()
            elif kind == "screen":
                self.hmi_screen = c["name"]
            elif kind == "save":
                self.plc.save_retentive(STATE_FILE)
                self.note("retentive data saved")
            elif kind == "defaults":
                self.plc.load_defaults()
                self.note("taught points reset to defaults")
            elif kind == "teach_jog":
                pass
            return {"ok": True}

    def set_power(self, on: bool) -> None:
        if on == self.powered:
            return
        if not on:
            if self.persist:
                self.plc.save_retentive(STATE_FILE)
            self.powered = False
            self.note("power OFF")
            return
        # power-on: volatile memory cleared, retentive kept, arm stays where it is
        keep = {a: self.plc.mem.read(a) for a in __import__("twin.plc", fromlist=["RETENTIVE"]).RETENTIVE}
        self.plc = PLC(self.cfg)
        for a, v in keep.items():
            self.plc.mem.write(a, v)
        for ax in (self.arm.base, self.arm.shoulder):
            ax.cmd.controlword = 0
            ax.enabled = False
        self.can_t = 0.0
        self._prev_bits.clear()
        self.powered = True
        self.note("power ON")

    # ------------------------------------------------------------------ snapshot for the UI
    def snapshot(self) -> dict:
        with self.lock:
            a, m, p = self.arm, self.plc.mem, self.plc
            sh, pt, tip = a.fk(a.base.theta, a.shoulder.theta)
            j_b, j_s, t_g, mp = a.loads()
            vm = p.vm

            def bit(x): return int(m.read(x))

            def ax(x):
                return {
                    "deg": math.degrees(x.theta), "ref_deg": math.degrees(x.ref),
                    "target_deg": math.degrees(x.target_angle),
                    "count": x.pos_count, "rpm": x.vel_rpm, "tau": x.tau, "tau_cont": x.cfg.tau_cont,
                    "tau_peak": x.cfg.tau_peak, "load_pct": x.load_pct, "current_ma": x.current_ma,
                    "enabled": x.enabled, "running": x.running, "at_target": x.at_target,
                    "saturated": x.saturated, "overload_s": x.overload_s,
                    "statusword": x.statusword, "controlword": x.cmd.controlword,
                    "target_count": x.cmd.target_count, "target_rpm": x.cmd.target_rpm,
                }
            part = None
            if a.part:
                part = {"pos": a.part.pos, "state": a.part.state, "mass": a.part.mass}
            placed = {"pos": a.placed.pos, "mass": a.placed.mass} if a.placed else None
            cyc_s = vm.counters.get(4).count if vm.counters.get(4) else 0
            cyc_m = vm.counters.get(3).count if vm.counters.get(3) else 0
            return {
                "t": self.t, "powered": self.powered, "paused": self.paused, "speed": self.speed,
                "can_online": p.can_online, "can_boot": min(1.0, self.can_t / self.cfg.can_boot_delay_s),
                "scan_count": vm.scan_count, "scan_ms": self.cfg.scan_ms,
                "estop": self.estop,
                "io": {"I0.0": bit("I0.0"), "I0.1": bit("I0.1"), "Q0.7": bit("Q0.7")},
                "bits": {k: bit(k) for k in (
                    "M10.0", "M10.1", "M20.1", "M20.2", "M20.3", "M20.4", "M20.5", "M22.0", "M22.1", "M22.2",
                    "M22.3", "M22.4", "M30.0", "M30.1", "M30.2", "M30.4", "M30.6", "M31.0", "M31.1", "M31.2",
                    "M31.3", "M31.4", "M31.5", "M31.6", "M31.7", "M32.0", "M32.1", "M32.2", "M33.0", "M33.6",
                    "M34.3", "M40.0", "M50.0", "M50.1", "SM0.3")},
                "regs": {k: int(m.read(k)) for k in (
                    ["VD2020", "VD2030", "VW2036", self.plc.cycle_addr, "VW2500", "VW2510", "MD600", "VD1044", "VD1002",
                     "VD1028", "VD1006", "VD1032", "VW1000", "VW1024"]
                    + [f"VD{2300 + 4 * i}" for i in range(5)] + [f"VD{2400 + 4 * i}" for i in range(5)])},
                "timers": {f"T{n}": {"q": t.bit, "ms": round(t.elapsed_ms), "pt": t.preset, "kind": t.kind}
                           for n, t in sorted(vm.timers.items())},
                "counters": {f"C{n}": {"n": c.count, "pv": c.preset, "q": c.bit} for n, c in sorted(vm.counters.items())},
                "trace": "".join(chr(48 + b) for b in vm.trace),
                "net_power": "".join(str(b) for b in vm.net_power),
                "base": ax(a.base), "shoulder": ax(a.shoulder),
                "geom": {"shoulder": sh, "p": pt, "tip": tip},
                "load": {"payload_kg": mp, "j_base": j_b, "j_shoulder": j_s, "t_grav": t_g,
                         "t_grav_unloaded": 9.81 * math.sin(a.shoulder.theta) * (
                             a.cfg.arm.m_link1 * a.cfg.arm.reach / 2 + a.cfg.arm.m_link2 * a.cfg.arm.reach)},
                "part": part, "placed": placed, "cfg_payload": self.cfg.arm.payload, "feeder": self.cfg.arm.feeder,
                "hmi": {"screen": self.hmi_screen, "cyc_min": cyc_m, "cyc_sec": cyc_s,
                        "magnet_sw": bit("M20.5")},
                "cycle_s": (self.t - self.cycle_started_at) if (self.cycle_started_at and bit("M30.1")) else 0,
                "picks": a.picks, "drops": a.drops,
                "log": list(self.log)[-14:],
                "points": [a.fk(self.cfg.base.count_to_angle(m.read(f"VD{2300 + 4 * i}")),
                                self.cfg.shoulder.count_to_angle(m.read(f"VD{2400 + 4 * i}")))[2] for i in range(5)],
                "pdo": [int(m.read(addr)) for (_n, _d, _c, _o, addr, _b) in PDO_MAP],
                "cycle_reg": self.plc.cycle_addr,
                "geo_cfg": {"reach": a.a.reach, "h": a.a.shoulder_height, "drop": a.a.drop_link,
                            "part_r": a.a.part_radius, "part_h": a.a.part_height},
            }

    def program_info(self) -> dict:
        prog = self.plc.program
        return {
            "networks": [{"index": n.index, "label": n.label, "first": n.first, "last": n.last} for n in prog.networks],
            "instrs": [{"op": i.op, "text": i.text, "net": i.net, "args": [o.text for o in i.args]} for i in prog.instrs],
            "pdo": [{"node": n, "dir": d, "cob": f"0x{c:03X}", "obj": o, "addr": a, "bits": b} for n, d, c, o, a, b in PDO_MAP],
        }
