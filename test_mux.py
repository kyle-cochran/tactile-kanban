#!/usr/bin/env python3
"""Verify the PCA9548A I2C mux is reachable and responds correctly.

Checks that the mux ACKs at its address, that writing a channel mask
reads back correctly, and that all-off also reads back correctly.
"""
import sys
import smbus2

I2C_BUS = 1
MUX_ADDR = 0x70  # PCA9548A default; adjust if A0/A1/A2 pins are pulled high


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")
    sys.exit(1)


bus = smbus2.SMBus(I2C_BUS)

# ── 1. Detect the mux ────────────────────────────────────────────────────────
print(f"[1] Looking for mux at 0x{MUX_ADDR:02X} on I2C bus {I2C_BUS}...")
try:
    current = bus.read_byte(MUX_ADDR)
    print(f"    Found — current channel register: 0x{current:02X}")
except OSError:
    fail(f"No ACK from 0x{MUX_ADDR:02X}. Check wiring and that MUX_ADDR is correct.")

# ── 2. Enable channel 0 and read back ────────────────────────────────────────
print("[2] Writing 0x01 (enable channel 0)...")
bus.write_byte(MUX_ADDR, 0x01)
val = bus.read_byte(MUX_ADDR)
print(f"    Read back: 0x{val:02X}", end="  ")
if val == 0x01:
    print("OK")
else:
    fail(f"expected 0x01, got 0x{val:02X}")

# ── 3. Disable all channels and read back ────────────────────────────────────
print("[3] Writing 0x00 (disable all channels)...")
bus.write_byte(MUX_ADDR, 0x00)
val = bus.read_byte(MUX_ADDR)
print(f"    Read back: 0x{val:02X}", end="  ")
if val == 0x00:
    print("OK")
else:
    fail(f"expected 0x00, got 0x{val:02X}")

bus.close()
print("\nMux OK — all checks passed.")
