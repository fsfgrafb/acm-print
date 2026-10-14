import os
import tomllib
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

ROOT = Path(__file__).resolve().parents[2]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Branding(StrictModel):
    platform_name: str = Field(min_length=1, max_length=80, strict=True)
    organization_name: str = Field(min_length=1, max_length=80, strict=True)
    identity_label: str = Field(min_length=1, max_length=20, strict=True)
    logo_url: str = Field(default="/brand/team-logo.svg", max_length=200)
    icon_url: str = Field(default="/brand/favicon.svg", max_length=200)

    @field_validator("logo_url", "icon_url")
    @classmethod
    def asset_url(cls, value):
        import re

        if not re.fullmatch(r"/brand/[A-Za-z0-9_-]+\.(svg|png|webp|ico)", value):
            raise ValueError("品牌图片必须使用 /brand/ 下的本地文件")
        return value

    @field_validator("platform_name", "organization_name", "identity_label", mode="before")
    @classmethod
    def clean(cls, value):
        if not isinstance(value, str):
            raise ValueError("必须是字符串")
        if any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in value):
            raise ValueError("不允许控制字符")
        return value.strip()


class Server(StrictModel):
    public_origin: str = "http://localhost:5173"
    secure_cookie: bool = False

    @field_validator("public_origin")
    @classmethod
    def origin(cls, value):
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc or parsed.path not in ("", "/"):
            raise ValueError("public_origin 必须是无路径的 HTTP(S) 来源")
        return value.rstrip("/")


class Storage(StrictModel):
    root: str = "var/storage"


class Printer(StrictModel):
    backend: str = "disabled"
    queue: str = "HP LaserJet Professional P1106"
    cancel_verified: bool = False

    @field_validator("backend")
    @classmethod
    def backend_name(cls, value):
        if value not in {"disabled", "windows"}:
            raise ValueError("backend 仅支持 disabled/windows")
        return value


class Converter(StrictModel):
    office_program: str = ""


class Config(StrictModel):
    branding: Branding
    server: Server = Field(default_factory=Server)
    storage: Storage = Field(default_factory=Storage)
    printer: Printer = Field(default_factory=Printer)
    converter: Converter = Field(default_factory=Converter)

    @property
    def storage_path(self):
        path = Path(self.storage.root)
        return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


@lru_cache
def config() -> Config:
    path = Path(os.environ.get("PLATFORM_CONFIG_FILE", ROOT / "config/platform.toml"))
    if not path.is_absolute():
        raise ValueError("PLATFORM_CONFIG_FILE 必须是绝对路径")
    with path.open("rb") as stream:
        return Config.model_validate(tomllib.load(stream))
