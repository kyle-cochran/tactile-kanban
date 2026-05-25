"""NFC reader layer — polls PN532 sensors described in a SensorTopology.

Mux safety pattern: every channel switch writes 0x00 (all-off) to the mux
*before* opening the new channel, so no two sensors are ever on the bus
simultaneously even if execution is interrupted between writes.
"""
from __future__ import annotations

from typing import Optional

import smbus2

from pn532 import PN532
from sensor_topology import NfcSensor, SensorTopology


class _MuxGate:
    """Wraps a single PCA9548A with the 0x00-first safety pattern."""

    def __init__(self, bus: smbus2.SMBus, address: int):
        self._bus  = bus
        self._addr = address

    def select(self, channel: int) -> None:
        self._bus.write_byte(self._addr, 0x00)          # all channels off first
        self._bus.write_byte(self._addr, 1 << channel)  # then open only the requested one

    def close_all(self) -> None:
        self._bus.write_byte(self._addr, 0x00)


class NfcReader:
    """Polls NFC sensors described in a SensorTopology.

    Each sensor is initialised once at start() (SAM config, RF config).
    poll() sequences through every sensor — opening its mux path, reading,
    then closing before moving on — so only one PN532 is ever on the bus.
    """

    def __init__(self, topology: SensorTopology):
        self._topology = topology
        self._mux_bus:  Optional[smbus2.SMBus] = None
        self._gates:    dict[int, _MuxGate]    = {}            # mux_addr → gate
        self._readers:  dict[int, PN532]        = {}            # sensor index → reader
        self._ready:    set[int]                = set()         # successfully init'd indices

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        self._mux_bus = smbus2.SMBus(self._topology.i2c_bus)

        for i, sensor in enumerate(self._topology.sensors):
            label = self._label(sensor)
            self._open_path(sensor)
            reader = PN532(bus=self._topology.i2c_bus, address=sensor.address)
            try:
                reader.open()
                self._readers[i] = reader
                self._ready.add(i)
                print(f"[nfc] {label} → '{sensor.status}' ready")
            except Exception as exc:
                reader.close()
                print(f"[nfc] {label} → '{sensor.status}' FAILED: {exc}")
            finally:
                self._close_path(sensor)

    def stop(self) -> None:
        for gate in self._gates.values():
            try:
                gate.close_all()
            except Exception:
                pass
        for reader in self._readers.values():
            reader.close()
        if self._mux_bus:
            self._mux_bus.close()
        self._gates.clear()
        self._readers.clear()
        self._ready.clear()
        self._mux_bus = None

    # ── Polling ──────────────────────────────────────────────────────────────

    def poll(self) -> Optional[tuple[str, str]]:
        """Scan all sensors in order. Returns (uid_hex, status_name) on first tap."""
        for i, sensor in enumerate(self._topology.sensors):
            if i not in self._ready:
                continue
            self._open_path(sensor)
            try:
                uid = self._readers[i].read_passive_target(timeout=0.05)
            except Exception:
                uid = None
            finally:
                self._close_path(sensor)
            if uid:
                return uid.hex().upper(), sensor.status
        return None

    # ── Mux path helpers ─────────────────────────────────────────────────────

    def _gate(self, mux_addr: int) -> _MuxGate:
        if mux_addr not in self._gates:
            self._gates[mux_addr] = _MuxGate(self._mux_bus, mux_addr)
        return self._gates[mux_addr]

    def _open_path(self, sensor: NfcSensor) -> None:
        """Enable each mux in the sensor's path, outermost first."""
        for mux_addr, channel in sensor.mux_path:
            self._gate(mux_addr).select(channel)

    def _close_path(self, sensor: NfcSensor) -> None:
        """Close all muxes in the sensor's path, outermost first."""
        for mux_addr, _ in sensor.mux_path:
            self._gate(mux_addr).close_all()

    @staticmethod
    def _label(sensor: NfcSensor) -> str:
        if sensor.mux_path:
            mux_addr, channel = sensor.mux_path[-1]
            return f"mux@0x{mux_addr:02X}/port{channel}"
        return f"0x{sensor.address:02X}"
