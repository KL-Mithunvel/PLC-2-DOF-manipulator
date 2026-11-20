"""Stage 4: shadow toolkit on synthetic data: alignment, residuals, detectors. Standard library only, no hardware."""
import math, os, random, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from shadow import (Cusum, EventLog, Signal, Threshold, WindowRms, detect, edge_delays, estimate_lag, estimate_lag_edges, from_frames,
                    from_messages, get_path, lag_drift, mismatch_intervals, mismatch_rate, residual, rising_edges)


def trajectory(t: float) -> float:
    """Arm-like angle: several smooth moves with dwells, never periodic (so the lag is unambiguous)."""
    return (40 * math.sin(0.31 * t) + 25 * math.sin(0.113 * t + 1.0) + 12 * math.sin(0.77 * t + 2.0)
            + 8 * math.tanh(math.sin(0.05 * t) * 6))


def make(f, t0, t1, dt, jitter=0.0, drop=0.0, noise=0.0, shift=0.0, seed=1, name="x"):
    rnd = random.Random(seed)
    ts, vs = [], []
    t = t0
    while t <= t1:
        if rnd.random() >= drop:
            tt = t + (rnd.uniform(-jitter, jitter) if jitter else 0.0)
            ts.append(tt + shift)
            vs.append(f(t) + (rnd.gauss(0, noise) if noise else 0.0))
        t += dt
    ts_sorted = sorted(range(len(ts)), key=lambda i: ts[i])
    return Signal(name, [ts[i] for i in ts_sorted], [vs[i] for i in ts_sorted])


class Signals(unittest.TestCase):
    def test_interpolation_hold_and_range(self):
        a = Signal("a", [0, 1, 2], [0, 10, 0])
        self.assertEqual(a.at(0.5), 5); self.assertEqual(a.at(1.5), 5); self.assertIsNone(a.at(-0.1)); self.assertIsNone(a.at(2.1))
        b = Signal("b", [0, 1, 2], [0, 1, 0], kind="binary")
        self.assertEqual(b.at(0.99), 0); self.assertEqual(b.at(1.0), 1); self.assertEqual(b.at(2.0), 0)
        with self.assertRaises(ValueError): Signal("bad", [1, 0], [0, 0])
        self.assertEqual(a.shifted(2).t, [2, 3, 4]); self.assertEqual(len(a.window(0.5, 1.5)), 1)

    def test_paths_with_dotted_keys_and_lists(self):
        d = {"bits": {"M30.1": 1}, "geom": {"tip": [1.0, 2.0, 3.0]}, "base": {"deg": 5}}
        self.assertEqual(get_path(d, "bits/M30.1"), 1); self.assertEqual(get_path(d, "geom/tip/2"), 3.0)
        self.assertIsNone(get_path(d, "bits/M99.9")); self.assertIsNone(get_path(d, "geom/tip/7")); self.assertIsNone(get_path(d, "x/y"))

    def test_from_frames_and_messages(self):
        frames = [{"t": i * 0.1, "base": {"deg": i}, "bits": {"M30.1": i % 2}} for i in range(5)] + [{"t": 0.5}]
        s = from_frames(frames, "base/deg"); self.assertEqual(s.v, [0, 1, 2, 3, 4])
        class M:                                             # stands in for bag.Message
            def __init__(self, t, p): self.t_mono, self.t_wall, self.payload = t, t + 1e9, p
        msgs = [M(i * 0.2, {"t": i * 0.1, "base": {"deg": i}}) for i in range(4)]
        self.assertEqual(from_messages(msgs, "base/deg").t, [0, 0.2, 0.4, 0.6000000000000001])
        self.assertAlmostEqual(from_messages(msgs, "base/deg", clock="t_wall").t[0], 1e9)
        self.assertEqual(from_messages(msgs, "base/deg", clock="payload").t[1], 0.1)


class Alignment(unittest.TestCase):
    def test_known_lag_recovered_with_noise_jitter_and_drops(self):
        for true_lag in (0.37, -0.82, 0.0, 2.113):
            a = make(trajectory, 0, 120, 0.04, noise=0.3, seed=1)
            b = make(trajectory, 0, 120, 0.04, jitter=0.01, drop=0.25, noise=0.3, shift=true_lag, seed=2)      # b is later by true_lag
            r = estimate_lag(a, b, max_lag=4.0, dt=0.05)
            self.assertAlmostEqual(r.lag, true_lag, delta=0.02, msg=f"true {true_lag}")
            self.assertGreater(r.score, 0.99)

    def test_sub_grid_precision(self):
        a = make(trajectory, 0, 60, 0.02, seed=3); b = make(trajectory, 0, 60, 0.02, shift=0.123, seed=4)
        self.assertAlmostEqual(estimate_lag(a, b, 1.0, 0.05).lag, 0.123, delta=0.01)

    def test_rejects_unrelated_or_non_overlapping(self):
        a = make(trajectory, 0, 30, 0.05)
        far = make(trajectory, 1000, 1030, 0.05)
        with self.assertRaises(ValueError): estimate_lag(a, far, 5.0)
        rnd = random.Random(5)
        noise = Signal("n", [i * 0.05 for i in range(600)], [rnd.gauss(0, 1) for _ in range(600)])
        self.assertLess(estimate_lag(a, noise, 3.0).score, 0.4)               # no real match: low score tells the caller

    def test_edges_lag_and_per_edge_delays(self):
        rnd = random.Random(7)
        ts = sorted(rnd.uniform(0, 300) for _ in range(40))
        def pulses(starts, delay, drop=0.0):
            t, v = [0.0], [0.0]
            for s in starts:
                if rnd.random() < drop: continue
                t += [s + delay, s + delay + 0.4]; v += [1.0, 0.0]
            return Signal("p", t, v, kind="binary")
        # keep pulses apart so each is its own edge
        starts = [i * 7.0 + rnd.uniform(0, 1) for i in range(40)]
        a = pulses(starts, 0.0); b = pulses(starts, 0.21 , drop=0.1)
        r = estimate_lag_edges(a, b, max_lag=2.0)
        self.assertAlmostEqual(r.lag, 0.21, delta=0.001); self.assertGreaterEqual(r.score, 0.75); self.assertEqual(r.method, "edges")
        d = edge_delays(rising_edges(a), rising_edges(b), 2.0)
        self.assertTrue(all(abs(x - 0.21) < 1e-9 for x in d)); self.assertLess(len(d), 40)

    def test_clock_drift(self):
        eps, off = 2e-4, 0.2                                                  # b's clock runs 200 ppm fast, offset 0.2 s
        a = make(trajectory, 0, 600, 0.1, seed=1)
        b = Signal("b", [t * (1 + eps) + off for t in a.t], list(a.v))
        d = lag_drift(a, b, window_s=60, step_s=60, max_lag=1.0, dt=0.1)
        self.assertAlmostEqual(d["ppm"], 200.0, delta=40.0)
        self.assertAlmostEqual(d["lag0"], off, delta=0.03)


class Residuals(unittest.TestCase):
    def test_offset_and_lag_are_separated(self):
        a = make(trajectory, 0, 60, 0.05, seed=1)
        b = make(lambda t: trajectory(t) - 1.5, 0, 60, 0.05, shift=0.4, seed=1)           # twin is 1.5 deg low and 0.4 s late
        lag = estimate_lag(a, b, 2.0).lag
        res = residual(a, b, lag, dt=0.05)
        st = res.stats()
        self.assertAlmostEqual(st["bias"], 1.5, delta=0.1); self.assertLess(st["std"], 0.3)
        self.assertAlmostEqual(st["lag"], 0.4, delta=0.02)
        self.assertGreater(residual(a, b, 0.0).stats()["rms"], 3 * st["rms"] - 1)           # without the lag correction the error is large

    def test_no_overlap_raises(self):
        with self.assertRaises(ValueError): residual(make(trajectory, 0, 10, 0.1), make(trajectory, 100, 110, 0.1))

    def test_binary_mismatch_intervals(self):
        t = [i * 0.05 for i in range(400)]
        real = Signal("bit", t, [1.0 if 5 <= x < 15 else 0.0 for x in t], kind="binary")
        twin = Signal("bit", t, [1.0 if 5.1 <= x < 15 or 17 <= x < 18.5 else 0.0 for x in t], kind="binary")   # late edge + a spurious pulse
        res = residual(real, twin, 0.0, dt=0.05)
        spans = mismatch_intervals(res)
        self.assertEqual(len(spans), 2)
        self.assertEqual(len(mismatch_intervals(res, min_len=0.5)), 1)                    # the 0.1 s edge delay is dropped, the pulse stays
        self.assertAlmostEqual(spans[1][0], 17.0, delta=0.06)
        self.assertGreater(mismatch_rate(res), 0.0); self.assertLess(mismatch_rate(res), 0.1)


class Detectors(unittest.TestCase):
    def noise(self, n=12000, sigma=0.1, seed=11):
        rnd = random.Random(seed)
        return [i * 0.05 for i in range(n)], [rnd.gauss(0, sigma) for _ in range(n)]

    def test_threshold_with_hold(self):
        t = [i * 0.1 for i in range(200)]
        r = [0.0] * 200
        r[50] = 5.0                                  # a one-sample spike
        for i in range(100, 120): r[i] = 3.0         # a 2 s excursion
        a = Threshold(1.0, hold_s=0.5).run(t, r, "x")
        self.assertEqual(len(a), 1); self.assertAlmostEqual(a[0].t_start, 10.0); self.assertEqual(a[0].peak, 3.0)
        self.assertEqual(len(Threshold(1.0, hold_s=0.0).run(t, r, "x")), 2)

    def test_cusum_no_false_alarm_on_clean_noise_and_fast_on_a_step(self):
        t, r = self.noise()
        self.assertEqual(Cusum().run(t, r, "x"), [])                                      # 600 s of clean noise
        shifted = [v + (0.3 if x > 300 else 0.0) for x, v in zip(t, r)]                   # a 3-sigma step at t = 300 s
        alarms = Cusum().run(t, shifted, "x")
        self.assertGreaterEqual(len(alarms), 1)
        delay = alarms[0].t_start - 300
        self.assertGreaterEqual(delay, 0.0); self.assertLess(delay, 1.0)

    def test_cusum_finds_a_slow_ramp_before_a_threshold_does(self):
        t, r = self.noise()
        ramp = [v + max(0.0, (x - 200) * 0.0025) for x, v in zip(t, r)]                   # grows to 1.0 over 400 s
        c = Cusum().run(t, ramp, "x"); th = Threshold(0.5, 1.0).run(t, ramp, "x")
        self.assertTrue(c and th)
        self.assertLess(c[0].t_start, th[0].t_start - 20)                                 # CUSUM is much earlier
        down = [v - max(0.0, (x - 200) * 0.0025) for x, v in zip(t, r)]
        self.assertIn("down", Cusum().run(t, down, "x")[0].detail)

    def test_window_rms(self):
        t, r = self.noise(2000, 0.05)
        for i in range(800, 1000): r[i] += 1.0
        a = WindowRms(2.0, 0.5).run(t, r, "x")
        self.assertEqual(len(a), 1); self.assertGreater(a[0].t_start, 40.0); self.assertLess(a[0].t_start, 43.0)

    def test_event_log_merges_and_exports(self):
        from shadow import Alarm
        log = EventLog(gap_s=1.0)
        log.add([Alarm("d", "s", 10, 11, 2), Alarm("d", "s", 11.5, 12, 5), Alarm("d", "s", 30, 31, 1), Alarm("d", "other", 11, 12, 1)])
        self.assertEqual(len(log.alarms), 3)
        first = log.first("s"); self.assertEqual((first.t_start, first.t_end, first.peak), (10, 12, 5))
        ev = log.events()
        self.assertTrue(all(e["kind"] == "divergence" and "text" in e for e in ev))
        self.assertIn("peak", log.summary()); self.assertEqual(EventLog().summary(), "no divergence detected")

    def test_detect_runs_several_detectors_on_a_residual(self):
        a = make(trajectory, 0, 120, 0.05, seed=1)
        b = make(lambda t: trajectory(t) + (2.0 if t > 80 else 0.0), 0, 120, 0.05, seed=1)
        res = residual(a, b, 0.0)
        alarms = detect(res, Threshold(1.0, 1.0), Cusum(baseline_s=20.0, min_sigma=0.01))
        self.assertEqual({x.detector.split("(")[0].split(">")[0] for x in alarms}, {"threshold", "cusum"})
        self.assertTrue(all(x.t_start >= 79.9 for x in alarms))


if __name__ == "__main__":
    unittest.main()
