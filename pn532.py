"""PN532 NFC controller over I2C."""
from __future__ import annotations

import time
from typing import Optional

try:
    import smbus2
except ImportError:
    smbus2 = None  # type: ignore

# PN532 host-to-chip command codes
_CMD_GET_FIRMWARE = 0x02
_CMD_SAM_CONFIG   = 0x14
_CMD_RF_CONFIG    = 0x32
_CMD_LIST_TARGET  = 0x4A


class PN532:
    """Minimal PN532 driver for passive NFC-A tag reading over I2C.

    Usage:
        nfc = PN532(bus=1, address=0x24)
        nfc.open()                          # initialise; raises on failure
        uid = nfc.read_passive_target(timeout=2.0)   # bytes or None
        nfc.close()
    """

    def __init__(self, bus: int = 1, address: int = 0x24):
        self._bus_num = bus
        self._addr    = address
        self._bus: Optional["smbus2.SMBus"] = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def open(self) -> None:
        """Open I2C, verify chip, configure SAM. Raises RuntimeError on failure."""
        if smbus2 is None:
            raise RuntimeError("smbus2 not installed — pip install smbus2")
        self._bus = smbus2.SMBus(self._bus_num)

        fw = self._send(_CMD_GET_FIRMWARE)
        if fw is None or len(fw) < 4:
            raise RuntimeError(
                f"No response from PN532 at 0x{self._addr:02X} on I2C bus {self._bus_num}"
            )
        ic, ver, rev = fw[0], fw[1], fw[2]
        print(f"[pn532] 0x{self._addr:02X}  IC=0x{ic:02X}  firmware v{ver}.{rev}")

        self._send(_CMD_SAM_CONFIG, bytes([0x01, 0x14, 0x01]))

        # Set PassiveActivation MaxRetries to 0x02 so read_passive_target returns
        # quickly when no tag is present, allowing the caller to poll in a loop.
        self._send(_CMD_RF_CONFIG, bytes([0x05, 0xFF, 0x01, 0x02]))

    def close(self) -> None:
        if self._bus:
            self._bus.close()
            self._bus = None

    # ── Public API ───────────────────────────────────────────────────────────

    def read_passive_target(self, timeout: float = 1.0) -> Optional[bytes]:
        """Return UID bytes for the first NFC-A tag found, or None.

        With MaxRetries=0x02 (set in open()), the PN532 returns quickly when
        nothing is present, so this is safe to call in a tight polling loop.
        """
        resp = self._send(_CMD_LIST_TARGET, bytes([0x01, 0x00]),
                          resp_timeout=max(timeout, 0.5))
        if not resp or len(resp) < 7 or resp[0] == 0:
            return None
        uid_len = resp[5]
        uid = resp[6:6 + uid_len]
        return uid if uid else None

    # ── PN532 framing ────────────────────────────────────────────────────────

    def _frame(self, cmd: int, data: bytes = b"") -> bytes:
        body = bytes([0xD4, cmd]) + data
        lcs  = (~len(body) + 1) & 0xFF
        dcs  = (~sum(body)  + 1) & 0xFF
        return bytes([0x00, 0x00, 0xFF, len(body), lcs]) + body + bytes([dcs, 0x00])

    def _write(self, data: bytes) -> None:
        self._bus.i2c_rdwr(smbus2.i2c_msg.write(self._addr, list(data)))

    def _read_raw(self, n: int) -> bytes:
        msg = smbus2.i2c_msg.read(self._addr, n)
        self._bus.i2c_rdwr(msg)
        return bytes(msg)

    def _wait_ready(self, timeout: float) -> bool:
        time.sleep(0.01)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self._read_raw(1)[0] == 0x01:
                    return True
            except OSError:
                pass
            time.sleep(0.01)
        return False

    def _send(self, cmd: int, data: bytes = b"",
              resp_timeout: float = 2.0) -> Optional[bytes]:
        try:
            self._write(self._frame(cmd, data))
        except OSError:
            return None

        # Phase 1: ACK (00 00 FF 00 FF 00, prefixed by status byte)
        if not self._wait_ready(2.0):
            return None
        self._read_raw(7)

        # Phase 2: response
        if not self._wait_ready(resp_timeout):
            return None
        raw = self._read_raw(32)
        if not raw or raw[0] != 0x01:
            return None

        buf = raw[1:]
        for i in range(len(buf) - 4):
            if buf[i:i+3] == b"\x00\x00\xff":
                llen = buf[i+3]
                if llen == 0:
                    continue
                body = buf[i+5 : i+5+llen]
                return body[2:] if len(body) >= 2 else b""
        return None
