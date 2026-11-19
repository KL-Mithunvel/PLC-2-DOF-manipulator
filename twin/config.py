"""All physical / electrical parameters of the digital twin, with their provenance.

Source tags:  [doc]  = taken from the repo documents (paper, CANopen manual, PLC program)
              [calc] = derived from [doc] values
              [assumed] = a placeholder: replace with measured / CAD / datasheet values
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

G = 9.81


@dataclass
class AxisCfg:
    name: str
    ratio: float                 # [doc] harmonic drive ratio
    cpr_motor: int               # [doc] CANopen manual: 15-bit absolute encoder, 32768 counts/rev
    home_count: int              # [doc] PLC program: count at angle 0
    sign: int                    # +1: angle grows with count; -1: angle grows as count falls
    rpm_limit: float             # [doc] HMI max speed (motor rpm)
    tau_peak: float              # [doc] paper: output peak torque N.m (vendor, at ~80:1)
    tau_cont: float              # [doc] paper: output continuous torque N.m
    j_rotor: float               # [assumed] rotor inertia kg.m^2 (paper: 0.69e-4 for M8010)
    accel_default_rpms: float    # [doc] manual example 20000 rpm/s; used when PDO 6083 = 0; manual example is 20000 but 5000 assumed here
    kt: float                    # [assumed] motor torque constant N.m/A (for current estimate)
    profile_rpm: float = 500.0   # [assumed] drive object 6081 (profile velocity), used when PDO 60FF = 0
    eta: float = 0.8             # [assumed] gear efficiency
    friction_c: float = 0.5      # [assumed] Coulomb friction N.m at output
    friction_v: float = 0.3      # [assumed] viscous friction N.m.s/rad at output
    angle_min_deg: float = -2.0
    angle_max_deg: float = 178.0

    @property
    def cpr_out(self) -> float:
        return self.cpr_motor * self.ratio

    def angle_to_count(self, rad: float) -> int:
        return int(round(self.home_count + self.sign * rad / (2 * math.pi) * self.cpr_out))

    def count_to_angle(self, count: float) -> float:
        return self.sign * (count - self.home_count) / self.cpr_out * 2 * math.pi


@dataclass
class ArmCfg:
    # geometry
    reach: float = 0.42            # [doc] shoulder -> point P (Link-2 axis), m
    shoulder_height: float = 0.17  # [assumed] shoulder axis above table, m
    drop_link: float = 0.12        # [assumed] Link-2 + magnet hangs below P, m
    # masses
    m_link1: float = 2.0           # [doc, assumed in paper] kg
    m_link2: float = 1.5           # [doc, assumed in paper] kg  (Link-2 + magnet)
    payload: float = 5.0           # [doc] kg, steel cylinder
    j_base_struct: float = 0.05    # [assumed] base-axis structure inertia kg.m^2
    part_radius: float = 0.04      # [assumed] m (5 kg steel cylinder ~ 80 mm dia)
    part_height: float = 0.05      # [assumed] m
    magnet_range: float = 0.05     # [assumed] m, capture distance of the electromagnet
    feeder: bool = True            # re-supply a part at the pick point after each cycle


@dataclass
class TwinCfg:
    scan_ms: float = 5.0           # [assumed] PLC scan period
    physics_ms: float = 1.0        # drive/physics sub-step
    can_boot_delay_s: float = 3.0  # [doc] CANopen "power-on delay 3 s"
    timer_base_ms: float = 10.0    # [assumed] KincoBuilder time base of T1..T26 -> calibrate against real cycle time
    sm03_period_s: float = 1.0     # [assumed] %SM0.3 = 1 s clock (C4 counts seconds up to 59)
    base: AxisCfg = field(default_factory=lambda: AxisCfg(
        name="base", ratio=101, cpr_motor=32768, home_count=-750000, sign=+1,
        rpm_limit=1500, tau_peak=178, tau_cont=85, j_rotor=1.0e-4,
        accel_default_rpms=5000, kt=0.12))
    shoulder: AxisCfg = field(default_factory=lambda: AxisCfg(
        name="shoulder", ratio=81, cpr_motor=32768, home_count=-57646473, sign=-1,
        rpm_limit=2000, tau_peak=56, tau_cont=35, j_rotor=0.69e-4,
        accel_default_rpms=5000, kt=0.08))
    arm: ArmCfg = field(default_factory=ArmCfg)

    # default retentive PLC data (first start). Taught points: angle pairs (base deg, shoulder deg)
    # INIT, POS1 (above pick), POS2 (pick), POS3 (above drop), POS4 (drop)
    default_points_deg: tuple = (
        (0.0, 0.0), (0.0, 55.0), (0.0, 86.0), (90.0, 55.0), (90.0, 86.0))
    default_speed_rpm: tuple = (300, 300)   # HMI speed entries (base, shoulder)
    default_cycles: int = 3
    fix_vw2400_overlap: bool = False  # True = remap the C2 mirror away from %VD2400 (program bug, see docs)


# ---------------------------------------------------------------------------------------------
# Calibration overrides: a JSON file {"timer_base_ms": 100, "base.profile_rpm": 400, ...} next to run_twin.py
# is applied on top of the defaults above. Written by tools/calibrate_cycle.py.
import json as _json
import os as _os

OVERRIDE_FILE = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "twin_config.json")


def apply_overrides(cfg: "TwinCfg", overrides: dict) -> "TwinCfg":
    for key, value in overrides.items():
        obj = cfg
        *path, leaf = key.split(".")
        for part in path:
            obj = getattr(obj, part)
        if not hasattr(obj, leaf):
            raise KeyError(f"unknown config key {key!r}")
        setattr(obj, leaf, value)
    return cfg


def load_config(path: str | None = None) -> "TwinCfg":
    """Defaults + overrides from ``path`` (default: twin_config.json if it exists)."""
    cfg = TwinCfg()
    path = path or OVERRIDE_FILE
    if _os.path.exists(path):
        with open(path) as fh:
            apply_overrides(cfg, _json.load(fh))
    return cfg
