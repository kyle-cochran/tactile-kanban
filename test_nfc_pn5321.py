#!/usr/bin/env python3
"""PN532 NFC reader test — I2C on Raspberry Pi.

The PN532 uses its own framing protocol (not NCI), with a status byte
prefix on reads (0x01 = data ready, 0x00 = busy).

Wiring:
  VCC  → 3.3 V  (pin 1)
  GND  → GND    (pin 6)
  SDA  → GPIO 2 (pin 3)
  SCL  → GPIO 3 (pin 5)
  IRQ  → GPIO 24 (pin 18)  ← optional

Run:
  python3 test_nfc_pn5321.py
"""

import sys
import time

try:
    import smbus2
except ImportError:
    sys.exit("smbus2 not installed — run: pip install smbus2")

# ── Config ───────────────────────────────────────────────────────────────────
I2C_BUS    = 1
PN532_ADDR = 0x24
IRQ_GPIO   = None    # set to BCM pin number if IRQ line is wired, else None
TIMEOUT_S  = 30
# ─────────────────────────────────────────────────────────────────────────────

_gpio_ready = False
if IRQ_GPIO is not None:
    try:
        import RPi.GPIO as GPIO
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(IRQ_GPIO, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        _gpio_ready = True
        print(f"[init] IRQ on GPIO {IRQ_GPIO}")
    except Exception as e:
        print(f"[init] GPIO unavailable ({e}) — timed polling")


# ── PN532 I2C framing ────────────────────────────────────────────────────────
# Frame: 00 00 FF <LEN> <LCS> D4 <CMD> [data] <DCS> 00
# Read prefix: first byte is status (0x01=ready, 0x00=busy)

def _frame(cmd: int, data: bytes = b"") -> bytes:
    body = bytes([0xD4, cmd]) + data
    length = len(body)
    lcs = (~length + 1) & 0xFF
    dcs = (~sum(body) + 1) & 0xFF
    return bytes([0x00, 0x00, 0xFF, length, lcs]) + body + bytes([dcs, 0x00])


def _write(bus: smbus2.SMBus, data: bytes) -> None:
    bus.i2c_rdwr(smbus2.i2c_msg.write(PN532_ADDR, list(data)))


def _read_raw(bus: smbus2.SMBus, length: int) -> bytes:
    msg = smbus2.i2c_msg.read(PN532_ADDR, length)
    bus.i2c_rdwr(msg)
    return bytes(msg)


def _wait_ready(bus: smbus2.SMBus, timeout: float = 2.0) -> bool:
    """Poll status byte until 0x01 (ready) or timeout."""
    if _gpio_ready:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not GPIO.input(IRQ_GPIO):   # IRQ active-low on PN532
                return True
            time.sleep(0.005)
        return False
    else:
        time.sleep(0.01)  # give PN532 time to prepare response
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                status = _read_raw(bus, 1)[0]
            except OSError:
                time.sleep(0.01)
                continue
            if status == 0x01:
                return True
            time.sleep(0.01)
        return False


def _send(bus: smbus2.SMBus, cmd: int, data: bytes = b"", label: str = "",
          resp_timeout: float = 2.0) -> bytes | None:
    """Send a PN532 command and return the response payload (bytes after D5 + cmd+1).

    PN532 protocol has two phases:
      1. chip sends ACK  (00 00 FF 00 FF 00)  once it has parsed the command
      2. chip sends response frame            once it has executed the command
    Each phase is signalled by status byte 0x01 on the next I2C read.
    """
    frame = _frame(cmd, data)
    try:
        _write(bus, frame)
    except OSError as e:
        print(f"  [{label}] write failed: {e}")
        return None

    # ── Phase 1: ACK ─────────────────────────────────────────────────────────
    if not _wait_ready(bus, timeout=2.0):
        print(f"  [{label}] timeout waiting for ACK")
        return None
    ack = _read_raw(bus, 7)   # status(1) + ACK frame(6)
    if ack[1:7] != bytes([0x00, 0x00, 0xFF, 0x00, 0xFF, 0x00]):
        print(f"  [{label}] unexpected ACK bytes: {ack.hex(' ').upper()}")

    # ── Phase 2: response ────────────────────────────────────────────────────
    if not _wait_ready(bus, timeout=resp_timeout):
        print(f"  [{label}] timeout waiting for response")
        return None
    raw = _read_raw(bus, 32)   # status(1) + frame(up to 31)
    print(f"  [{label}] raw: {raw.hex(' ').upper()}")

    if raw[0] != 0x01:
        print(f"  [{label}] status not ready: 0x{raw[0]:02X}")
        return None

    # Parse: find 00 00 FF LEN LCS in buf, extract body
    buf = raw[1:]
    for i in range(len(buf) - 4):
        if buf[i] == 0x00 and buf[i+1] == 0x00 and buf[i+2] == 0xFF:
            llen = buf[i+3]
            if llen == 0x00:
                continue   # ACK frame — shouldn't appear here, but skip it
            body = buf[i+5 : i+5+llen]   # TFI(D5) + CMD+1 + payload
            return body[2:] if len(body) >= 2 else b""

    print(f"  [{label}] could not parse response frame")
    return None


# ── Commands ─────────────────────────────────────────────────────────────────
CMD_GET_FIRMWARE     = 0x02
CMD_SAM_CONFIG       = 0x14
CMD_IN_LIST_TARGET   = 0x4A


def main() -> None:
    print("PN532 NFC test")
    print(f"  I2C bus {I2C_BUS}, address 0x{PN532_ADDR:02X}")
    print()

    try:
        bus = smbus2.SMBus(I2C_BUS)
    except Exception as e:
        sys.exit(f"Cannot open I2C bus: {e}")

    print("[1/3] GetFirmwareVersion")
    fw = _send(bus, CMD_GET_FIRMWARE, label="GetFirmwareVersion")
    if fw is None:
        bus.close()
        sys.exit("No response — check wiring and I2C address.")
    if len(fw) >= 4:
        print(f"  IC=0x{fw[0]:02X}  Ver={fw[1]}.{fw[2]}  Support=0x{fw[3]:02X}")

    print("[2/3] SAMConfiguration (normal mode)")
    _send(bus, CMD_SAM_CONFIG, bytes([0x01, 0x14, 0x01]), label="SAMConfig")

    print(f"\nReady — tap a tag within {TIMEOUT_S} s …\n")

    # InListPassiveTarget: 1 target, 106 kbps Type A (NFC-A / MIFARE)
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        resp = _send(bus, CMD_IN_LIST_TARGET, bytes([0x01, 0x00]),
                     label="InListPassiveTarget", resp_timeout=TIMEOUT_S)
        if resp is None:
            time.sleep(0.1)
            continue
        if len(resp) < 1 or resp[0] == 0:
            time.sleep(0.1)
            continue

        # resp: NumTargets, Tg, ATQA(2), SAK(1), NfcIdLength(1), NfcId(n), [ATS]
        num_targets = resp[0]
        if num_targets == 0:
            time.sleep(0.1)
            continue

        atqa    = resp[2:4]
        sak     = resp[4]
        uid_len = resp[5]
        uid     = resp[6:6 + uid_len]

        print("=" * 40)
        print("Tag detected!")
        print(f"  UID:  {uid.hex().upper()}  ({uid_len} bytes)")
        print(f"  ATQA: {atqa.hex().upper()}")
        print(f"  SAK:  0x{sak:02X}")
        print("=" * 40)
        break
    else:
        print("Timeout — no tag detected.")

    bus.close()
    if _gpio_ready:
        GPIO.cleanup()


if __name__ == "__main__":
    main()
