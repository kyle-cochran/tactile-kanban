#!/usr/bin/env python3
"""Hardware probe for the NFC sensor topology.

Phase 1 — connectivity check:
  • Verifies every mux is reachable on the I2C bus
  • Verifies every PN532 responds through its mux channel

Phase 2 — continuous poll loop:
  • Reads all live sensors in sequence
  • Prints the configured status whenever a tag is detected

Usage:
    uv run python probe_sensors.py [--topology sensors.yaml]
"""
import argparse
import sys
import time
from collections import defaultdict

import smbus2

from sensor_topology import load_topology, NfcSensor, SensorTopology
from nfc import NfcReader, _MuxGate


# ── Phase 1: check ──────────────────────────────────────────────────────────

def check_topology(topology: SensorTopology) -> bool:
    """Returns True if everything in the topology is reachable."""
    bus = smbus2.SMBus(topology.i2c_bus)
    ok = True

    # --- Check each unique mux ---
    seen_muxes: set[int] = set()
    for sensor in topology.sensors:
        for mux_addr, _ in sensor.mux_path:
            seen_muxes.add(mux_addr)

    print(f"Checking {len(seen_muxes)} mux(es)...")
    mux_ok: set[int] = set()
    for addr in sorted(seen_muxes):
        try:
            bus.read_byte(addr)
            print(f"  [OK]   mux @ 0x{addr:02X}")
            mux_ok.add(addr)
        except OSError:
            print(f"  [FAIL] mux @ 0x{addr:02X}  — no ACK")
            ok = False

    # --- Check each sensor through its mux path ---
    print(f"\nChecking {len(topology.sensors)} NFC sensor(s)...")
    gates: dict[int, _MuxGate] = {addr: _MuxGate(bus, addr) for addr in mux_ok}

    for sensor in topology.sensors:
        mux_addr, port = sensor.mux_path[-1]
        label = f"mux@0x{mux_addr:02X}/port{port}"

        # Skip if the mux itself is down
        if mux_addr not in mux_ok:
            print(f"  [SKIP] {label} → '{sensor.status}'  (mux unreachable)")
            ok = False
            continue

        # Open the path
        for ma, ch in sensor.mux_path:
            if ma in gates:
                gates[ma].select(ch)

        # Ping the PN532 at its I2C address
        try:
            bus.read_byte(sensor.address)
            print(f"  [OK]   {label} → '{sensor.status}'  (PN532 @ 0x{sensor.address:02X})")
        except OSError:
            print(f"  [FAIL] {label} → '{sensor.status}'  (no ACK from PN532 @ 0x{sensor.address:02X})")
            ok = False

        # Close the path
        for ma, _ in sensor.mux_path:
            if ma in gates:
                gates[ma].close_all()

    bus.close()
    return ok


# ── Phase 2: poll loop ───────────────────────────────────────────────────────

def poll_loop(topology: SensorTopology) -> None:
    reader = NfcReader(topology)
    print("\nInitialising sensors (SAM config + RF config)...")
    reader.start()

    n_ready = len(reader._ready)
    n_failed = len(topology.sensors) - n_ready

    if n_failed:
        print(f"  {n_failed} sensor(s) did not initialise — they will be skipped.")
    if not n_ready:
        print("No sensors available. Exiting.")
        reader.stop()
        return

    print(f"\n{n_ready} sensor(s) live. Tap a tag to any reader (Ctrl-C to stop).\n")

    last_uid_status: dict[str, str] = {}

    try:
        while True:
            result = reader.poll()
            if result:
                uid, status = result
                if last_uid_status.get(uid) != status:
                    last_uid_status[uid] = status
                    print(f"  {uid}  →  {status}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        reader.stop()


# ── Entry point ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--topology", default="sensors.yaml")
    args = parser.parse_args()

    topology = load_topology(args.topology)
    print(f"Topology: {args.topology}  ({len(topology.sensors)} sensors, I2C bus {topology.i2c_bus})\n")

    all_ok = check_topology(topology)

    if not all_ok:
        print("\nSome checks failed. Fix wiring and re-run, or continue anyway? [y/N] ", end="")
        if input().strip().lower() != "y":
            sys.exit(1)

    poll_loop(topology)


if __name__ == "__main__":
    main()
