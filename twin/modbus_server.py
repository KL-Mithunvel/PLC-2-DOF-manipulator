"""Minimal Modbus TCP server that exposes the twin's PLC memory (standard library only).

Lets the live-PLC reader be developed and tested without the real PLC, and lets a real HMI or any
Modbus client talk to the twin.  Read functions 1-4 only; writes are refused (exception 1) unless
``allow_write`` is set, so a client cannot disturb the simulation by accident.
"""
from __future__ import annotations

import socketserver
import struct
import threading

from live.modbus_map import ModbusMap


class _Handler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        srv: "TwinModbusServer" = self.server  # type: ignore[assignment]
        sock = self.request
        while True:
            head = self._recv(sock, 7)
            if not head:
                return
            tid, pid, length, unit = struct.unpack(">HHHB", head)
            pdu = self._recv(sock, length - 1)
            if not pdu:
                return
            resp = srv.process(pdu)
            sock.sendall(struct.pack(">HHHB", tid, pid, len(resp) + 1, unit) + resp)

    @staticmethod
    def _recv(sock, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            try:
                chunk = sock.recv(n - len(buf))
            except OSError:
                return b""
            if not chunk:
                return b""
            buf += chunk
        return buf


class TwinModbusServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, twin, mapping: ModbusMap | None = None, host: str = "127.0.0.1", port: int = 1502,
                 allow_write: bool = False) -> None:
        super().__init__((host, port), _Handler)
        self.twin = twin
        self.map = mapping or ModbusMap()
        self.allow_write = allow_write
        self.requests = 0

    @property
    def port(self) -> int:
        return self.server_address[1]

    def start(self) -> "TwinModbusServer":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    # ---- protocol ----------------------------------------------------------
    @staticmethod
    def _exc(fc: int, code: int) -> bytes:
        return bytes([fc | 0x80, code])

    def process(self, pdu: bytes) -> bytes:
        self.requests += 1
        fc = pdu[0]
        mem = self.twin.plc.mem
        try:
            if fc in (1, 2):
                addr, count = struct.unpack(">HH", pdu[1:5])
                if not 1 <= count <= 2000:
                    return self._exc(fc, 3)
                kind = "coil" if fc == 1 else "discrete"
                bits = []
                with self.twin.lock:
                    for a in range(addr, addr + count):
                        loc = self.map.resolve_bit(kind, a)
                        if loc is None:
                            return self._exc(fc, 2)
                        bits.append(mem.get_bit(*loc))
                out = bytearray((count + 7) // 8)
                for i, b in enumerate(bits):
                    if b:
                        out[i // 8] |= 1 << (i % 8)
                return bytes([fc, len(out)]) + bytes(out)
            if fc in (3, 4):
                addr, count = struct.unpack(">HH", pdu[1:5])
                if not 1 <= count <= 125:
                    return self._exc(fc, 3)
                words = []
                with self.twin.lock:
                    for a in range(addr, addr + count):
                        loc = self.map.resolve_word(a)
                        if loc is None:
                            return self._exc(fc, 2)
                        words.append(mem.get(loc[0], 2, loc[1], signed=False))
                return bytes([fc, count * 2]) + struct.pack(f">{count}H", *words)
            if fc in (5, 6, 15, 16) and self.allow_write:
                return self._write(fc, pdu)
            return self._exc(fc, 1)
        except Exception:   # noqa: BLE001
            return self._exc(fc, 4)

    def _write(self, fc: int, pdu: bytes) -> bytes:
        mem = self.twin.plc.mem
        with self.twin.lock:
            if fc == 5:
                addr, val = struct.unpack(">HH", pdu[1:5])
                loc = self.map.resolve_bit("coil", addr)
                if loc is None:
                    return self._exc(fc, 2)
                mem.set_bit(*loc, 1 if val == 0xFF00 else 0)
                return pdu[:5]
            if fc == 6:
                addr, val = struct.unpack(">HH", pdu[1:5])
                loc = self.map.resolve_word(addr)
                if loc is None:
                    return self._exc(fc, 2)
                mem.set(loc[0], 2, loc[1], val)
                return pdu[:5]
            if fc == 16:
                addr, count, nbytes = struct.unpack(">HHB", pdu[1:6])
                vals = struct.unpack(f">{count}H", pdu[6:6 + nbytes])
                for i, v in enumerate(vals):
                    loc = self.map.resolve_word(addr + i)
                    if loc is None:
                        return self._exc(fc, 2)
                    mem.set(loc[0], 2, loc[1], v)
                return pdu[:5]
        return self._exc(fc, 1)
