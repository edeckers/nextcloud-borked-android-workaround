import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    base_url: str
    username: str
    app_password: str
    remote_root: str
    local_root: str
    local_name_contains: str | None
    adb_serial: str | None


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(
            f"Missing required environment variable: {name}. "
            f"See README for the .env setup."
        )
    return value


def load_config() -> Config:
    load_dotenv()
    return Config(
        base_url=os.environ.get("NEXTCLOUD_URL", "https://cloud.example.com").rstrip("/"),
        username=_require("NEXTCLOUD_USER"),
        app_password=_require("NEXTCLOUD_APP_PASSWORD"),
        remote_root=os.environ.get("NEXTCLOUD_REMOTE_ROOT", "").strip("/"),
        local_root=os.environ.get("PHONE_PHOTO_ROOT", "/sdcard/DCIM/Camera"),
        local_name_contains=os.environ.get("PHONE_PHOTO_NAME_CONTAINS") or None,
        adb_serial=os.environ.get("ADB_SERIAL") or None,
    )
