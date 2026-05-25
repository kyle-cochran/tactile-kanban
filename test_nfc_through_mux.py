#!/usr/bin/env python3
"""Verify the PN532 NFC chip is reachable through port 0 of the I2C mux.

Enables mux port 0, then opens the PN532 driver (which sends a
GetFirmwareVersion command internally) and attempts a passive NFC scan.
"""
import sys
import time
import smbus2

from pn532 import PN532

I2C_BUS = 1
MUX_ADDR = 0x70  # PCA9548A default
NFC_ADDR = 0x24  # PN532 fixed address
MUX_PORT = 0     # port the PN532 is wired to (0 = bit 0 = 0x01)


def fail(msg: str) -> None:
    print(f"  FAIL: {msg}")
    # Leave mux in all-off state on failure
    try:
        bus = smbus2.SMBus(I2C_BUS)
        bus.write_byte(MUX_ADDR, 0x00)
        bus.close()
    except Exception:
        pass
    sys.exit(1)


# ── 1. Enable mux port ───────────────────────────────────────────────────────
port_mask = 1 << MUX_PORT
print(f"[1] Enabling mux port {MUX_PORT} (mask 0x{port_mask:02X})...")
try:
    bus = smbus2.SMBus(I2C_BUS)
    bus.write_byte(MUX_ADDR, port_mask)
    readback = bus.read_byte(MUX_ADDR)
    bus.close()
    if readback != port_mask:
        fail(f"Mux readback 0x{readback:02X}, expected 0x{port_mask:02X}. Run test_mux.py first.")
    print(f"    Mux port {MUX_PORT} active.")
except OSError as e:
    fail(f"Could not reach mux at 0x{MUX_ADDR:02X}: {e}")

# ── 2. Open PN532 ─────────────────────────────────────────────────────────────
print(f"[2] Opening PN532 at 0x{NFC_ADDR:02X} (GetFirmwareVersion)...")
nfc = PN532(bus=I2C_BUS, address=NFC_ADDR)
try:
    nfc.open()   # prints firmware version on success, raises RuntimeError on failure
    print("    PN532 opened successfully.")
except RuntimeError as e:
    fail(str(e))

# ── 3. Try a passive scan ─────────────────────────────────────────────────────
print("[3] Scanning for an NFC tag (2 s)... ", end="", flush=True)
uid = nfc.read_passive_target(timeout=2.0)
if uid:
    print(f"Tag found — UID: {uid.hex().upper()}")
else:
    print("No tag present (that's fine — the chip is responding).")

# ── Cleanup ───────────────────────────────────────────────────────────────────
nfc.close()
bus = smbus2.SMBus(I2C_BUS)
bus.write_byte(MUX_ADDR, 0x00)
bus.close()
print("\nAll checks passed — PN532 is reachable through mux port 0.")
