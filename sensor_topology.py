"""Load and represent the physical NFC sensor topology from sensors.yaml.

The tree is walked recursively so cascaded muxes (mux → mux → nfc) work
without any special-casing.  Each NfcSensor carries a mux_path — an ordered
list of (mux_address, channel) pairs from outermost to innermost — which is
everything the NfcReader needs to set up the I2C path to that sensor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class NfcSensor:
    status: str
    address: int                          # I2C address of the PN532 chip
    mux_path: list[tuple[int, int]]       # [(mux_addr, channel), ...] outermost first


@dataclass
class SensorTopology:
    i2c_bus: int
    sensors: list[NfcSensor]


def load_topology(path: str | Path) -> SensorTopology:
    with open(path) as f:
        data = yaml.safe_load(f)
    i2c_bus = int(data.get("i2c_bus", 1))
    sensors: list[NfcSensor] = []
    for node in data.get("sensors", []):
        _walk(node, [], sensors)
    return SensorTopology(i2c_bus=i2c_bus, sensors=sensors)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _addr(val) -> int:
    if isinstance(val, str):
        return int(val, 16)
    return int(val)


def _walk(node: dict, mux_path: list[tuple[int, int]], out: list[NfcSensor]) -> None:
    node_type = node.get("type", "").lower()

    if node_type == "nfc":
        out.append(NfcSensor(
            status=str(node["status"]),
            address=_addr(node.get("address", 0x24)),
            mux_path=list(mux_path),
        ))

    elif node_type == "mux":
        mux_addr = _addr(node["address"])
        for child in node.get("channels", []):
            port = int(child["port"])
            _walk(child, mux_path + [(mux_addr, port)], out)

    else:
        raise ValueError(f"Unknown sensor node type: {node_type!r}")
