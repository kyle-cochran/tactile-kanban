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
    nfc_i2c_bus: int = field(
        default_factory=lambda: int(os.environ.get("NFC_I2C_BUS", "1"))
    )
    # Comma-separated address:status pairs for the column readers
    column_sensors: str = field(
        default_factory=lambda: os.environ.get(
            "COLUMN_SENSORS",
            "0x24:Ready,0x25:In Progress,0x26:Blocked,0x27:Done",
        )
    )

    @property
    def column_map(self) -> dict[int, str]:
        result = {}
        for part in self.column_sensors.split(","):
            addr_str, _, status = part.strip().partition(":")
            if addr_str and status:
                result[int(addr_str.strip(), 16)] = status.strip()
        return result


_config: Config | None = None


def get_config() -> Config:
    global _config
    if _config is None:
        _config = Config()
    return _config
