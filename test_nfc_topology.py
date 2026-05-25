#!/usr/bin/env python3
"""Poll all NFC sensors described in sensors.yaml and report any tags seen.

Run with a tag in hand and tap it to each reader in turn to verify
the full chain: topology loader → mux gate → PN532 → tag detection.

Usage:
    uv run python test_nfc_topology.py [--topology sensors.yaml] [--duration 30]
"""
import argparse
import time

from sensor_topology import load_topology
from nfc import NfcReader


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topology", default="sensors.yaml")
    parser.add_argument("--duration", type=float, default=30,
                        help="How many seconds to poll (default: 30)")
    args = parser.parse_args()

    topology = load_topology(args.topology)
    print(f"Loaded {len(topology.sensors)} sensor(s) from {args.topology}")
    for s in topology.sensors:
        mux_addr, port = s.mux_path[-1]
        print(f"  mux@0x{mux_addr:02X}/port{port}  →  '{s.status}'")

    print("\nInitialising sensors...")
    reader = NfcReader(topology)
    reader.start()

    ready = [topology.sensors[i] for i in reader._ready]
    failed = [topology.sensors[i] for i in range(len(topology.sensors)) if i not in reader._ready]
    print(f"\n{len(ready)} sensor(s) ready, {len(failed)} failed.")
    if failed:
        for s in failed:
            mux_addr, port = s.mux_path[-1]
            print(f"  [FAILED] mux@0x{mux_addr:02X}/port{port} → '{s.status}'")

    if not ready:
        print("No sensors available — check wiring.")
        reader.stop()
        return

    print(f"\nPolling for {args.duration}s — tap a tag to any reader...\n")
    seen: dict[str, str] = {}   # uid → last status seen on
    deadline = time.monotonic() + args.duration

    try:
        while time.monotonic() < deadline:
            result = reader.poll()
            if result:
                uid, status = result
                if seen.get(uid) != status:
                    seen[uid] = status
                    print(f"  Tag {uid}  →  '{status}'")
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        reader.stop()

    print(f"\nDone. {len(seen)} unique tag(s) seen:")
    for uid, status in seen.items():
        print(f"  {uid}  last seen on  '{status}'")


if __name__ == "__main__":
    main()
