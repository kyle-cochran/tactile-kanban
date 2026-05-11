import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    ap_host: str = field(default_factory=lambda: os.environ["OEPL_AP_HOST"])
    github_token: str = field(default_factory=lambda: os.environ["GITHUB_TOKEN"])
    github_org: str = field(default_factory=lambda: os.environ["GITHUB_ORG"])
    github_project_number: int = field(
        default_factory=lambda: int(os.environ["GITHUB_PROJECT_NUMBER"])
    )
    sprint_prefix: str = field(
        default_factory=lambda: os.environ.get("SPRINT_PREFIX", "Sprint")
    )
    sync_interval: int = field(
        default_factory=lambda: int(os.environ.get("SYNC_INTERVAL", "300"))
    )
    db_path: str = field(
        default_factory=lambda: os.environ.get("DB_PATH", "kanban.db")
    )
    font_path: str = field(
        default_factory=lambda: os.environ.get(
            "FONT_PATH",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        )
    )
    font_bold_path: str = field(
        default_factory=lambda: os.environ.get(
            "FONT_BOLD_PATH",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        )
    )
    # NFC device path — 'usb' lets nfcpy auto-detect; override e.g. 'tty:AMA0:pn532'
    nfc_device: str = field(
        default_factory=lambda: os.environ.get("NFC_DEVICE", "usb")
    )


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
