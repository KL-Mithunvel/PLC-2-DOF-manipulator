"""Kinco integrated harmonic-drive servo (M8025 / M8010) as seen over CANopen (CiA402 subset).

The PLC only ever writes controlword 271 (0x10F, halt), 47 (0x2F, run to target) and 15 (0x0F, enabled/hold).
Behaviour follows the CANopen manual: 0x0F enables (brake released), 0x2F = absolute position,
change-immediately, bit 8 = halt. Drive disabled => holding brake engaged (the "(B)" motors).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from .config import AxisCfg

RPM = 2 * math.pi / 60.0


@dataclass
class DriveCmd:
    controlword: int = 0
    mode: int = 0
    target_count: int = 0
    target_rpm: int = 0
    accel_rpms: int = 0


class Axis:
    def __init__(self, cfg: AxisCfg, theta0: float = 0.0) -> None:
        self.cfg = cfg
        self.theta = theta0        # output angle, rad
        self.omega = 0.0           # output rad/s
        self.ref = theta0          # profile position
        self.ref_v = 0.0
        self.integ = 0.0
        self.tau = 0.0             # actual motor torque at output, N.m
        self.t_ext = 0.0           # gravity torque last step
        self.cmd = DriveCmd()
        self.enabled = False
        self.running = False
        self.at_target = False
        self.saturated = False
        self.target_angle = theta0
        self.overload_s = 0.0

    # --- CANopen objects -------------------------------------------------
    @property
    def pos_count(self) -> int:
        return self.cfg.angle_to_count(self.theta)

    @property
    def vel_rpm(self) -> int:
        return int(round(self.omega * self.cfg.ratio / RPM))

    @property
    def statusword(self) -> int:
        sw = 0x0237 if self.enabled else 0x0250
        if self.enabled and self.at_target:
            sw |= 1 << 10
        return sw

    @property
    def current_ma(self) -> int:
        c = self.cfg
        return int(abs(self.tau) / (c.ratio * c.eta * c.kt) * 1000)

    @property
    def load_pct(self) -> float:
        return 100.0 * abs(self.tau) / self.cfg.tau_cont

    # --- one physics step ------------------------------------------------
    def step(self, dt: float, j_load: float, t_grav: float) -> None:
        c, cmd = self.cfg, self.cmd
        self.t_ext = t_grav
        self.enabled = (cmd.controlword & 0x0F) == 0x0F
        if not self.enabled:                       # brake engaged, no torque
            self.omega = 0.0
            self.ref, self.ref_v, self.integ, self.tau = self.theta, 0.0, 0.0, 0.0
            self.running = self.at_target = self.saturated = False
            return

        halt = bool(cmd.controlword & 0x100)
        run = bool(cmd.controlword & 0x20) and not halt
        self.running = run
        self.target_angle = c.count_to_angle(cmd.target_count)
        n = c.ratio
        vmax = min(abs(cmd.target_rpm) or c.profile_rpm, c.rpm_limit) / n * RPM
        acc_rpms = cmd.accel_rpms if cmd.accel_rpms > 0 else c.accel_default_rpms
        amax = max(acc_rpms, 1) / n * RPM          # rad/s^2 at the output

        # trapezoidal profile generator
        if run and vmax > 0:
            e = self.target_angle - self.ref
            v_des = math.copysign(min(vmax, math.sqrt(2 * amax * abs(e))), e) if abs(e) > 1e-7 else 0.0
        else:
            v_des = 0.0
        if halt:
            amax *= 4
        dv = max(-amax * dt, min(amax * dt, v_des - self.ref_v))
        a_ref = dv / dt
        self.ref_v += dv
        self.ref += self.ref_v * dt
        if run and abs(self.target_angle - self.ref) < 2e-7 and abs(self.ref_v) < amax * dt * 2:
            self.ref, self.ref_v, a_ref = self.target_angle, 0.0, 0.0

        # servo loop (PID + feed-forward), gains scheduled on the current total inertia
        j = j_load + n * n * c.j_rotor
        wn = 50.0
        kp, kd, ki = j * wn * wn, 2.0 * j * wn, j * wn ** 3 * 0.15
        e = self.ref - self.theta
        tau_cmd = kp * e + kd * (self.ref_v - self.omega) + ki * self.integ + j * a_ref
        tau_lim = c.tau_peak
        self.saturated = abs(tau_cmd) > tau_lim
        tau = max(-tau_lim, min(tau_lim, tau_cmd))
        if not self.saturated:
            self.integ = max(-0.5, min(0.5, self.integ + e * dt))
        self.tau = tau

        # plant
        fric = c.friction_v * self.omega + c.friction_c * math.tanh(self.omega / 0.01)
        alpha = (tau + t_grav - fric) / j
        self.omega += alpha * dt
        self.theta += self.omega * dt
        lo, hi = math.radians(c.angle_min_deg), math.radians(c.angle_max_deg)
        if self.theta < lo or self.theta > hi:
            self.theta = min(max(self.theta, lo), hi)
            self.omega = 0.0

        tol = 100 / c.cpr_out * 2 * math.pi        # 100 counts
        self.at_target = run and abs(self.theta - self.target_angle) < tol and abs(self.omega) < 0.02
        self.overload_s = self.overload_s + dt if abs(tau) > c.tau_cont else max(0.0, self.overload_s - dt)
