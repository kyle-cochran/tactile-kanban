"""Column NFC readers — four PN532 boards over I2C, one per kanban column."""
from __future__ import annotations

from typing import Optional

from pn532 import PN532


class NfcReader:
    """Polls multiple PN532 readers and returns (uid, target_status) on a tap.

    columns: dict mapping I2C address → GitHub status name
             e.g. {0x24: "Ready", 0x25: "In Progress", 0x26: "Blocked", 0x27: "Done"}
    """

    def __init__(self, columns: dict[int, str], i2c_bus: int = 1):
        self._columns  = columns
        self._bus      = i2c_bus
        self._readers: dict[int, PN532] = {}

    def start(self) -> None:
        for addr, status in self._columns.items():
            reader = PN532(bus=self._bus, address=addr)
            try:
                reader.open()
                self._readers[addr] = reader
                print(f"[nfc] 0x{addr:02X} ready → '{status}'")
            except Exception as e:
                print(f"[nfc] 0x{addr:02X} unavailable: {e}")

    def stop(self) -> None:
        for reader in self._readers.values():
            reader.close()
        self._readers.clear()

    def poll(self) -> Optional[tuple[str, str]]:
        """Check all readers. Returns (uid_hex, status_name) or None."""
        for addr, reader in self._readers.items():
            uid = reader.read_passive_target(timeout=0.05)
            if uid:
                return uid.hex().upper(), self._columns[addr]
        return None
