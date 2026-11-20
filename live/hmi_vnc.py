"""View-only screen grab of the REAL HMI panel over VNC (vncdotool), so the twin GUI can show it next to the replica.

* Only ``captureScreen`` is ever called: no mouse, key or clipboard method is used, so this cannot operate the HMI.
* The password is never stored in the repo: pass it with ``--hmi-vnc-password`` or the ``HMI_VNC_PASSWORD`` environment variable.
* The latest frame is kept as PNG bytes and served by the twin at ``/api/hmi.png``.
"""
from __future__ import annotations

import io
import threading
import time


class HmiVnc:
    def __init__(self, host: str, port: int = 5900, password: str | None = None, hz: float = 2.0) -> None:
        self.host, self.port, self.password, self.hz = host, port, password, hz
        self.png: bytes | None = None
        self.frame_t = 0.0
        self.frames = 0
        self.connected = False
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> "HmiVnc":
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        import warnings
        warnings.filterwarnings("ignore")
        from vncdotool import api
        client = None
        while not self._stop.is_set():
            try:
                if client is None:
                    client = api.connect(f"{self.host}::{self.port}", password=self.password, timeout=8)
                buf = io.BytesIO()
                client.captureScreen(buf, format="png")
                self.png, self.frame_t = buf.getvalue(), time.time()
                self.frames += 1
                self.connected, self.error = True, ""
            except Exception as exc:   # noqa: BLE001
                self.connected, self.error = False, str(exc) or type(exc).__name__
                if client is not None:
                    try:
                        client.disconnect()
                    except Exception:   # noqa: BLE001
                        pass
                client = None
                self._stop.wait(3.0)
                continue
            self._stop.wait(1.0 / self.hz)
        if client is not None:
            try:
                client.disconnect()
            except Exception:   # noqa: BLE001
                pass

    def status(self) -> dict:
        age = time.time() - self.frame_t if self.frames else None
        info = f"{self.host}:{self.port} frames={self.frames}" if self.connected else (self.error or "connecting")
        return {"connected": self.connected, "info": info, "age_s": age}
