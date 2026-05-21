"""Non-blocking status-change sound effects.

Looks for assets/<status-slug>.mp3 and plays it via mpg123 in the
background. Missing files and a missing mpg123 binary are both silent
no-ops, so partial sound libraries are fine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ASSETS = Path(__file__).parent / "assets"


def play_status_sound(status: str) -> None:
    """Fire-and-forget: play the MP3 for `status` if one exists."""
    slug = status.lower().strip().replace(" ", "-")
    path = _ASSETS / f"{slug}.mp3"
    if not path.exists():
        return
    try:
        subprocess.Popen(
            ["mpg123", "-q", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass  # mpg123 not installed
