"""NFC reader interface — stubbed for local testing.

Set NFC_ENABLED=1 in your environment to activate real hardware via nfcpy.
When disabled the reader silently does nothing, so the rest of the service
(display sync, GitHub updates) works without a physical NFC reader attached.
"""

from __future__ import annotations

import os
import queue
import threading
from typing import Optional

_ENABLED = os.environ.get("NFC_ENABLED", "0") == "1"


class NfcReader:
    """Background NFC polling thread.

    Usage:
        reader = NfcReader(device='usb')
        reader.start()
        uid = reader.poll(timeout=1.0)   # None if nothing tapped
        reader.stop()
    """

    def __init__(self, device: str = "usb"):
        self.device = device
        self._queue: queue.Queue[str] = queue.Queue()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._clf = None

    def start(self):
        if not _ENABLED:
            print("[nfc] NFC stub active — set NFC_ENABLED=1 to use real hardware")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._clf is not None:
            try:
                self._clf.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=3)

    def poll(self, timeout: float = 0.1) -> Optional[str]:
        """Return the next tapped tag UID, or None if the queue is empty."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def _run(self):
        try:
            import nfc  # type: ignore
        except ImportError:
            print("[nfc] nfcpy not installed — NFC tap detection disabled.")
            return

        try:
            self._clf = nfc.ContactlessFrontend(self.device)
        except Exception as exc:
            print(f"[nfc] Could not open NFC reader ({self.device}): {exc}")
            return

        print(f"[nfc] Reader ready on {self.device}")

        def on_connect(tag) -> bool:
            uid = tag.identifier.hex().upper()
            self._queue.put(uid)
            return False  # release tag immediately

        while not self._stop_event.is_set():
            try:
                self._clf.connect(
                    rdwr={
                        "on-connect": on_connect,
                        "targets": ["106A", "106B", "212F"],
                    },
                    terminate=lambda: self._stop_event.is_set(),
                )
            except Exception:
                pass
