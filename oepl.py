from __future__ import annotations

from io import BytesIO
from typing import Optional

import requests
from PIL import Image


class OEPLClient:
    def __init__(self, host: str):
        self.base = f"http://{host}"
        self.session = requests.Session()
        self._tagtype_cache: dict[int, tuple[int, int]] = {}

    def get_tags(self) -> list[dict]:
        """Return all known tags from the AP tag database."""
        tags: list[dict] = []
        pos = 0
        while True:
            resp = self.session.get(
                f"{self.base}/get_db", params={"pos": pos}, timeout=10
            )
            resp.raise_for_status()
            data = resp.json()
            batch: list[dict] = data.get("tags", [])
            tags.extend(batch)
            if not data.get("continu"):
                break
            pos += len(batch)
        return tags

    def get_tag_dimensions(self, hw_type: int) -> tuple[int, int]:
        """Return (width, height) for a given hwType, querying the AP tagtypes."""
        if hw_type in self._tagtype_cache:
            return self._tagtype_cache[hw_type]
        try:
            resp = self.session.get(
                f"{self.base}/tagtypes/{hw_type:02X}.json", timeout=5
            )
            resp.raise_for_status()
            data = resp.json()
            dims = (int(data.get("width", 0)), int(data.get("height", 0)))
        except Exception:
            dims = (0, 0)
        self._tagtype_cache[hw_type] = dims
        return dims

    def push_image(self, mac: str, image: Image.Image, dither: int = 0) -> bool:
        """Upload a PIL Image to the specified tag via /imgupload."""
        buf = BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=95)
        buf.seek(0)
        resp = self.session.post(
            f"{self.base}/imgupload",
            data={"mac": mac, "dither": dither},
            files={"file": ("card.jpg", buf, "image/jpeg")},
            timeout=20,
        )
        return resp.status_code == 200
