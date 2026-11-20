"""Shadow-and-diverge toolkit (stage 4): signals, time alignment, residuals, detectors, event log. Standard library only.

    from shadow import Signal, from_frames, estimate_lag, residual, Cusum, Threshold, detect, EventLog
"""
from .align import LagResult, edge_delays, estimate_lag, estimate_lag_edges, lag_drift
from .detect import Alarm, Cusum, EventLog, Threshold, WindowRms, detect
from .residual import Residual, mismatch_intervals, mismatch_rate, residual
from .signals import Signal, falling_edges, from_frames, from_messages, get_path, rising_edges

__all__ = ["Alarm", "Cusum", "EventLog", "LagResult", "Residual", "Signal", "Threshold", "WindowRms", "detect", "edge_delays",
           "estimate_lag", "estimate_lag_edges", "falling_edges", "from_frames", "from_messages", "get_path", "lag_drift",
           "mismatch_intervals", "mismatch_rate", "residual", "rising_edges"]
