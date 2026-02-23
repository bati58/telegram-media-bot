import os
from pathlib import Path


def _load_dotenv_if_present() -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip().lstrip("\ufeff")
        value = value.strip()

        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]

        # Keep explicit shell environment values higher priority than .env
        os.environ.setdefault(key, value)


def _parse_admin_ids(raw_admin_ids: str) -> set[int]:
    admin_ids: set[int] = set()
    for part in raw_admin_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            admin_ids.add(int(part))
        except ValueError as exc:
            raise RuntimeError("ADMIN_IDS must be a comma-separated list of integers.") from exc
    return admin_ids


def _parse_csv(raw_value: str) -> list[str]:
    return [part.strip() for part in raw_value.split(",") if part.strip()]


def _parse_bool(raw_value: str, default: bool = False) -> bool:
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _parse_positive_int(raw_value: str, default: int) -> int:
    try:
        value = int(raw_value)
        if value > 0:
            return value
    except (TypeError, ValueError):
        pass
    return default


_load_dotenv_if_present()

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required.")

# Comma-separated Telegram user IDs, e.g. "12345,67890"
ADMIN_IDS = _parse_admin_ids(os.getenv("ADMIN_IDS", "7048929478"))
MODERATOR_IDS = _parse_admin_ids(os.getenv("MODERATOR_IDS", ""))

MONGODB_URI = os.getenv("MONGODB_URI")
if not MONGODB_URI:
    raise RuntimeError("MONGODB_URI environment variable is required.")

MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "telegram_media_bot")
REQUIRED_CHANNELS = _parse_csv(os.getenv("REQUIRED_CHANNELS", ""))
ENABLE_PERIODIC_BACKUP = _parse_bool(os.getenv("ENABLE_PERIODIC_BACKUP", "true"), True)
BACKUP_INTERVAL_MINUTES = _parse_positive_int(os.getenv("BACKUP_INTERVAL_MINUTES", "60"), 60)
BACKUP_DIRECTORY = os.getenv("BACKUP_DIRECTORY", "backups")
