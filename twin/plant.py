"""The mechanical plant: 2-DOF arm (base yaw + shoulder pitch), electromagnet and the 5 kg part."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .config import ArmCfg, G, TwinCfg
from .drive import Axis


@dataclass
class Part:
    pos: list[float]
    state: str = "free"      # free | carried | placed
    mass: float = 5.0


class Arm:
    def __init__(self, cfg: TwinCfg) -> None:
        self.cfg = cfg
        self.a: ArmCfg = cfg.arm
        self.base = Axis(cfg.base, 0.0)
        self.shoulder = Axis(cfg.shoulder, 0.0)
        self.part: Part | None = None
        self.placed: Part | None = None
        self.pick_site: list[float] | None = None
        self.events: list[str] = []
        self.drops = 0
        self.picks = 0

    # --- kinematics ------------------------------------------------------
    def fk(self, phi: float, theta: float) -> tuple[list[float], list[float], list[float]]:
        """Return (shoulder, P, tip) in metres. phi = base yaw, theta = shoulder pitch from vertical-up."""
        a = self.a
        sh = [0.0, 0.0, a.shoulder_height]
        r = a.reach * math.sin(theta)
        p = [r * math.cos(phi), r * math.sin(phi), a.shoulder_height + a.reach * math.cos(theta)]
        tip = [p[0], p[1], p[2] - a.drop_link]
        return sh, p, tip

    def tip(self) -> list[float]:
        return self.fk(self.base.theta, self.shoulder.theta)[2]

    def tip_from_counts(self, base_count: int, sh_count: int) -> list[float]:
        return self.fk(self.cfg.base.count_to_angle(base_count), self.cfg.shoulder.count_to_angle(sh_count))[2]

    # --- dynamics --------------------------------------------------------
    @property
    def carried_mass(self) -> float:
        return self.part.mass if self.part and self.part.state == "carried" else 0.0

    def loads(self) -> tuple[float, float, float, float]:
        """(J_base, J_shoulder, T_gravity_shoulder, payload_kg)"""
        a = self.a
        L = a.reach
        mp = self.carried_mass
        th = self.shoulder.theta
        # shoulder: link-1 uniform rod about its end, link-2+magnet and payload as point masses at reach
        j_sh = a.m_link1 * L * L / 3.0 + (a.m_link2 + mp) * L * L
        t_g = G * math.sin(th) * (a.m_link1 * L / 2.0 + (a.m_link2 + mp) * L)
        # base: same masses at horizontal radius L*sin(theta)
        r = L * math.sin(th)
        j_b = a.j_base_struct + (a.m_link1 / 3.0 + a.m_link2 + mp) * r * r
        return j_b, j_sh, t_g, mp

    def step(self, dt: float, magnet_on: bool) -> None:
        j_b, j_s, t_g, _ = self.loads()
        self.base.step(dt, j_b, 0.0)
        self.shoulder.step(dt, j_s, t_g)
        self._part_logic(magnet_on)

    # --- part handling ---------------------------------------------------
    def set_pick_site(self, pos: list[float]) -> None:
        self.pick_site = [pos[0], pos[1], self.a.part_height / 2]
        if self.part is None:
            self.spawn_part()

    def spawn_part(self) -> None:
        if self.pick_site:
            self.part = Part(list(self.pick_site), "free", self.a.payload)
            self.events.append("part supplied at pick point")

    def _part_logic(self, magnet_on: bool) -> None:
        a, p = self.a, self.part
        tip = self.tip()
        if p is None:
            if a.feeder and self.pick_site and math.dist(tip[:2], self.pick_site[:2]) > 0.15:
                self.spawn_part()
            return
        if p.state == "free" and magnet_on:
            d = math.dist(tip, [p.pos[0], p.pos[1], p.pos[2] + a.part_height / 2])
            if d < a.magnet_range:
                p.state = "carried"
                self.picks += 1
                self.events.append(f"magnet captured {p.mass:.1f} kg part")
        if p.state == "carried":
            if magnet_on:
                p.pos = [tip[0], tip[1], tip[2] - a.part_height / 2]
            else:
                drop_h = p.pos[2] - a.part_height / 2
                p.pos[2] = a.part_height / 2
                p.state = "placed"
                self.events.append(f"magnet released, part dropped {drop_h * 1000:.0f} mm")
                self.drops += 1
                self.placed = p
                self.part = None

    def reset_pose(self) -> None:
        self.base = Axis(self.cfg.base, 0.0)
        self.shoulder = Axis(self.cfg.shoulder, 0.0)
