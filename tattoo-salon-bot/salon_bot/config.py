from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class Config:
    token: str
    admin_ids: frozenset[int]
    db_path: Path
    tz: ZoneInfo
    currency: str


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader: KEY=VALUE lines, existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _parse_ids(raw: str) -> frozenset[int]:
    ids = set()
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if part:
            ids.add(int(part))
    return frozenset(ids)


def load_config() -> Config:
    _load_dotenv(Path(".env"))
    token = os.environ.get("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("Не задан BOT_TOKEN. Скопируйте .env.example в .env и вставьте токен от @BotFather.")
    db_path = Path(os.environ.get("DB_PATH", "data/salon.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return Config(
        token=token,
        admin_ids=_parse_ids(os.environ.get("ADMIN_IDS", "")),
        db_path=db_path,
        tz=ZoneInfo(os.environ.get("TZ_NAME", "Europe/Moscow")),
        currency=os.environ.get("CURRENCY", "₽"),
    )
