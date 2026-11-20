"""Minimal Modbus RTU master (standard library; pyserial only for a real serial port).

Why our own: the same code path runs on a real RS485 adapter and on the simulated bus used in tests (CRC errors, timeouts, drops can be
injected), and the master is **read-only unless you ask otherwise**: write functions raise ``PermissionError`` unless
``allow_write=True`` (needed only for the one-time setup of a meter: slave address, current range, energy reset).

Frames: ``[slave][function][data...][crc lo][crc hi]``. Supported: 0x03 / 0x04 (read registers), 0x06 (write one register) and
``raw_command`` for vendor functions (the PZEM energy reset 0x42).
"""
from __future__ import annotations

import time


def crc16(data: bytes) -> int:
    """Modbus CRC-16 (polynomial 0xA001, initial value 0xFFFF). The frame carries it low byte first."""
    crc = 0xFFFF
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(frame: bytes) -> bytes:
    c = crc16(frame)
    return frame + bytes((c & 0xFF, c >> 8))


def crc_ok(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16(frame[:-2]) == (frame[-2] | frame[-1] << 8)


class RtuError(Exception):
    pass


class RtuTimeout(RtuError):
    pass


class RtuCrcError(RtuError):
    pass


class RtuException(RtuError):
    """The slave answered with a Modbus exception (function | 0x80)."""

    def __init__(self, function: int, code: int) -> None:
        super().__init__(f"modbus exception {code} for function {function:#04x}")
        self.function, self.code = function, code


class Transport:
    """What the master needs from a wire: write bytes, read up to n bytes within the transport's timeout, drop stale input."""

    def write(self, data: bytes) -> None:
        raise NotImplementedError

    def read(self, n: int) -> bytes:
        raise NotImplementedError

    def reset_input(self) -> None:
        pass

    def close(self) -> None:
        pass


class SerialTransport(Transport):
    def __init__(self, port: str, baud: int = 9600, bytesize: int = 8, parity: str = "N", stopbits: int = 1, timeout: float = 0.3) -> None:
        import serial        # pyserial (optional dependency)
        self._s = serial.Serial(port, baud, bytesize=bytesize, parity=parity, stopbits=stopbits, timeout=timeout)

    def write(self, data: bytes) -> None:
        self._s.write(data)
        self._s.flush()

    def read(self, n: int) -> bytes:
        return self._s.read(n)

    def reset_input(self) -> None:
        self._s.reset_input_buffer()

    def close(self) -> None:
        self._s.close()


class RtuMaster:
    def __init__(self, transport: Transport, retries: int = 2, allow_write: bool = False) -> None:
        self.t, self.retries, self.allow_write = transport, retries, allow_write
        self.requests = 0
        self.timeouts = 0
        self.crc_errors = 0
        self.exceptions = 0

    # ---- reads ------------------------------------------------------------------
    def read_input_registers(self, slave: int, addr: int, count: int) -> list[int]:
        return self._read(slave, 0x04, addr, count)

    def read_holding_registers(self, slave: int, addr: int, count: int) -> list[int]:
        return self._read(slave, 0x03, addr, count)

    def _read(self, slave: int, fc: int, addr: int, count: int) -> list[int]:
        if not 1 <= count <= 125:
            raise ValueError("count must be 1..125")
        req = with_crc(bytes((slave, fc, addr >> 8, addr & 0xFF, count >> 8, count & 0xFF)))
        resp = self._transact(req, lambda head: 3 + head[2] + 2 if not head[1] & 0x80 else 5, 3)
        data = resp[3:3 + resp[2]]
        if resp[2] != 2 * count:
            raise RtuError(f"expected {2 * count} data bytes, got {resp[2]}")
        return [data[i] << 8 | data[i + 1] for i in range(0, len(data), 2)]

    # ---- writes (setup only) -----------------------------------------------------
    def write_single_register(self, slave: int, addr: int, value: int) -> None:
        self._need_write()
        req = with_crc(bytes((slave, 0x06, addr >> 8, addr & 0xFF, value >> 8, value & 0xFF)))
        resp = self._transact(req, lambda head: 8 if not head[1] & 0x80 else 5, 3)
        if resp[2:6] != req[2:6]:
            raise RtuError("write was not echoed correctly")

    def raw_command(self, slave: int, function: int, payload: bytes = b"", reply_len: int = 4) -> bytes:
        """A vendor function (for example PZEM-017 energy reset 0x42). ``reply_len`` is the whole reply including CRC."""
        self._need_write()
        req = with_crc(bytes((slave, function)) + payload)
        return self._transact(req, lambda head: reply_len if not head[1] & 0x80 else 5, min(3, reply_len))

    def _need_write(self) -> None:
        if not self.allow_write:
            raise PermissionError("this RtuMaster is read-only: create it with allow_write=True for meter setup")

    # ---- transport -----------------------------------------------------------------
    def _transact(self, req: bytes, total_len, head_len: int) -> bytes:
        last: Exception | None = None
        for _attempt in range(self.retries + 1):
            self.requests += 1
            self.t.reset_input()
            self.t.write(req)
            try:
                head = self._read_exact(head_len)
                n = total_len(head)
                resp = head + self._read_exact(n - len(head))
            except RtuTimeout as exc:
                self.timeouts += 1
                last = exc
                continue
            if not crc_ok(resp):
                self.crc_errors += 1
                last = RtuCrcError("bad CRC in the reply")
                continue
            if resp[0] != req[0]:
                last = RtuError(f"reply from slave {resp[0]}, asked {req[0]}")
                continue
            if resp[1] & 0x80:
                self.exceptions += 1
                raise RtuException(resp[1] & 0x7F, resp[2])
            return resp
        raise last if last else RtuError("no reply")

    def _read_exact(self, n: int) -> bytes:
        out = b""
        while len(out) < n:
            chunk = self.t.read(n - len(out))
            if not chunk:
                raise RtuTimeout(f"timeout waiting for {n - len(out)} more bytes")
            out += chunk
        return out

    def close(self) -> None:
        self.t.close()
