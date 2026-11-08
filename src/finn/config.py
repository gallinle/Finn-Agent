"""Konfiguration aus Umgebung/.env (keine Secrets im Repo)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

PROJEKT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    vertraege_dir: Path = PROJEKT_ROOT / "data" / "vertraege"
    cache_dir: Path = PROJEKT_ROOT / "cache"
    stichtag: date = date(2027, 12, 31)
    modell: str = "claude-opus-5-5"
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    mail_user: str = ""
    mail_password: str = field(default="", repr=False)
    poll_timeout: int = 60

    @property
    def planjahr(self) -> int:
        return self.stichtag.year


def lade_config() -> Config:
    load_dotenv(PROJEKT_ROOT / ".env")
    env = os.environ.get
    kw: dict = {}
    if v := env("VERTRAEGE_DIR"):
        kw["vertraege_dir"] = Path(v)
    if v := env("CACHE_DIR"):
        kw["cache_dir"] = Path(v)
    if v := env("STICHTAG"):
        kw["stichtag"] = date.fromisoformat(v)
    return Config(
        imap_host=env("IMAP_HOST", ""),
        imap_port=int(env("IMAP_PORT", "993")),
        smtp_host=env("SMTP_HOST", ""),
        smtp_port=int(env("SMTP_PORT", "465")),
        mail_user=env("MAIL_USER", ""),
        mail_password=env("MAIL_PASSWORD", ""),
        poll_timeout=int(env("POLL_TIMEOUT", "60")),
        **kw,
    )
