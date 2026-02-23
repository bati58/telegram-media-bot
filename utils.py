import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Bot, types
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter

from config import BACKUP_DIRECTORY, REQUIRED_CHANNELS
from database import get_all_users, get_backup_payload, is_moderator_user

logger = logging.getLogger("bot.utils")

SEND_DELAY_SECONDS = 0.05
REQUIRED_MEMBER_STATUSES = {"member", "administrator", "creator"}


def _channel_display_name(channel_ref: str) -> str:
    channel_ref = channel_ref.strip()
    if channel_ref.startswith("https://t.me/"):
        suffix = channel_ref.removeprefix("https://t.me/").strip("/")
        if suffix:
            return f"@{suffix}"
    if channel_ref.startswith("http://t.me/"):
        suffix = channel_ref.removeprefix("http://t.me/").strip("/")
        if suffix:
            return f"@{suffix}"
    if channel_ref.startswith("t.me/"):
        suffix = channel_ref.removeprefix("t.me/").strip("/")
        if suffix:
            return f"@{suffix}"
    return channel_ref


def build_membership_required_text(missing_channels: list[str]) -> str:
    lines = ["Please join the required channel(s) to use this bot:"]
    for channel in missing_channels:
        lines.append(f"- {_channel_display_name(channel)}")
    lines.append("After joining, tap 'I Joined'.")
    return "\n".join(lines)


async def get_missing_required_channels(bot: Bot, user_id: int) -> list[str]:
    if not REQUIRED_CHANNELS:
        return []

    if is_moderator_user(user_id):
        return []

    missing: list[str] = []
    for channel in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(chat_id=channel, user_id=user_id)
            if member.status not in REQUIRED_MEMBER_STATUSES:
                missing.append(channel)
        except (TelegramBadRequest, TelegramForbiddenError, TelegramAPIError):
            # Misconfigured channel or bot lacks access: treat as missing for safety.
            missing.append(channel)

    return missing


async def ensure_message_membership(message: types.Message) -> bool:
    if not message.from_user:
        return False

    missing = await get_missing_required_channels(message.bot, message.from_user.id)
    if not missing:
        return True

    from keyboards import required_channels_keyboard

    await message.answer(
        build_membership_required_text(missing),
        reply_markup=required_channels_keyboard(missing),
    )
    return False


async def ensure_callback_membership(callback: types.CallbackQuery) -> bool:
    missing = await get_missing_required_channels(callback.bot, callback.from_user.id)
    if not missing:
        return True

    from keyboards import required_channels_keyboard

    text = build_membership_required_text(missing)
    if callback.message:
        await callback.message.edit_text(text, reply_markup=required_channels_keyboard(missing))

    await callback.answer("Join required channel(s) first.", show_alert=True)
    return False


def ensure_backup_directory() -> Path:
    backup_dir = Path(BACKUP_DIRECTORY)
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def create_backup_dump(prefix: str = "backup") -> Path:
    payload = get_backup_payload()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = ensure_backup_directory() / f"{prefix}_{timestamp}.json"
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return backup_path


def get_latest_backup_file() -> Path | None:
    backup_dir = ensure_backup_directory()
    candidates = [path for path in backup_dir.glob("*.json") if path.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


async def run_periodic_backup_loop(interval_minutes: int) -> None:
    interval_seconds = max(60, int(interval_minutes) * 60)
    logger.info("Periodic backup loop started (interval=%ss)", interval_seconds)

    while True:
        try:
            await asyncio.sleep(interval_seconds)
            backup_file = create_backup_dump(prefix="auto_backup")
            logger.info("Periodic backup created: %s", backup_file)
        except asyncio.CancelledError:
            logger.info("Periodic backup loop cancelled")
            raise
        except Exception:
            logger.exception("Periodic backup failed")


async def broadcast_copy_message(
    bot: Bot,
    source_message: types.Message,
    disable_notification: bool = False,
) -> tuple[int, int]:
    users = get_all_users()
    success = 0
    failed = 0

    for user_id in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=source_message.chat.id,
                message_id=source_message.message_id,
                disable_notification=disable_notification,
            )
            success += 1
            await asyncio.sleep(SEND_DELAY_SECONDS)
        except TelegramForbiddenError:
            failed += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=source_message.chat.id,
                    message_id=source_message.message_id,
                    disable_notification=disable_notification,
                )
                success += 1
                await asyncio.sleep(SEND_DELAY_SECONDS)
            except Exception:
                failed += 1
        except TelegramAPIError:
            failed += 1
        except Exception:
            failed += 1

    return success, failed


async def broadcast_message(
    bot: Bot,
    text: str,
    disable_notification: bool = False,
) -> tuple[int, int]:
    users = get_all_users()
    success = 0
    failed = 0

    for user_id in users:
        try:
            await bot.send_message(
                chat_id=user_id,
                text=text,
                disable_notification=disable_notification,
            )
            success += 1
            await asyncio.sleep(SEND_DELAY_SECONDS)
        except TelegramForbiddenError:
            failed += 1
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after)
            try:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    disable_notification=disable_notification,
                )
                success += 1
                await asyncio.sleep(SEND_DELAY_SECONDS)
            except Exception:
                failed += 1
        except TelegramAPIError:
            failed += 1
        except Exception:
            failed += 1

    return success, failed
