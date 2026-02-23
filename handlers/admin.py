import math

from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile

from config import BACKUP_INTERVAL_MINUTES, ENABLE_PERIODIC_BACKUP
from database import (
    add_content,
    count_content_by_category,
    delete_content_by_id,
    get_content_totals_by_category,
    get_health_snapshot,
    get_recent_audit_logs,
    get_recent_content,
    get_total_content,
    get_total_users,
    get_user_counts_by_role,
    is_admin_user,
    is_moderator_user,
    log_audit_event,
    set_user_role,
)
from runtime_state import format_uptime, get_uptime_seconds
from utils import broadcast_copy_message, create_backup_dump, get_latest_backup_file

router = Router()

PAGE_SIZE = 15


class Upload(StatesGroup):
    waiting_for_title = State()
    waiting_for_metadata = State()
    waiting_for_file = State()


class BulkMusicUpload(StatesGroup):
    waiting_for_files = State()


class BulkVideoUpload(StatesGroup):
    waiting_for_files = State()


class Broadcast(StatesGroup):
    waiting_for_message = State()


def _admin_help_text() -> str:
    return (
        "Admin commands:\n"
        "/addvideo - Add a new video\n"
        "/addmusic - Add a new music track\n"
        "/addvideobulk - Add many videos in one session\n"
        "/addmusicbulk - Add many music tracks in one session\n"
        "/broadcast - Broadcast any message to all users\n"
        "/health - Service and database health\n"
        "/setmoderator <id> - Grant moderator role\n"
        "/removemoderator <id> - Revoke moderator role\n"
        "/export_content - Export full JSON backup\n"
        "/audit [n] - Show recent audit logs\n"
        "/done - Finish bulk upload session\n"
        "File caption format: Title | artist=Name;genre=Pop;tags=tag1,tag2\n"
        "\n"
        "Staff commands:\n"
        "/stats - Show usage stats\n"
        "/listcontent [category] [page] - Show content IDs\n"
        "/delete <id> - Delete content by ID\n"
        "/cancel - Cancel current admin action"
    )


def _parse_listcontent_args(args: str | None) -> tuple[str | None, int]:
    category = None
    page = 1

    if not args:
        return category, page

    parts = args.split()
    first = parts[0].lower()
    if first in {"video", "music"}:
        category = first
        parts = parts[1:]

    if parts:
        try:
            page = int(parts[0])
        except ValueError as exc:
            raise ValueError("Page must be an integer.") from exc

    if page < 1:
        raise ValueError("Page must be >= 1.")

    return category, page


def _parse_target_user_id(message: types.Message, args: str | None) -> int:
    if not args:
        if message.reply_to_message and message.reply_to_message.from_user:
            return int(message.reply_to_message.from_user.id)
        raise ValueError("User ID is required. Use /setmoderator <id> or reply to a user's message.")

    raw_user_id = args.strip()
    try:
        return int(raw_user_id)
    except ValueError as exc:
        raise ValueError("User ID must be an integer.") from exc


def _parse_metadata_input(raw_input: str) -> dict[str, object]:
    metadata: dict[str, object] = {}

    parts = [part.strip() for part in raw_input.split(";") if part.strip()]
    for part in parts:
        if "=" not in part:
            continue

        key, value = part.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if not value:
            continue

        if key in {"artist", "genre", "album", "language", "source"}:
            metadata[key] = value
            continue

        if key == "tags":
            tags = [tag.strip() for tag in value.split(",") if tag.strip()]
            if tags:
                metadata["tags"] = tags
            continue

        if key in {"duration", "year"}:
            try:
                metadata[key] = int(value)
            except ValueError:
                continue

    return metadata


def _parse_caption_payload(caption: str | None) -> tuple[str, dict[str, object]]:
    raw_caption = (caption or "").strip()
    if not raw_caption:
        return "", {}

    if "|" in raw_caption:
        raw_title, raw_meta = raw_caption.split("|", 1)
        return raw_title.strip(), _parse_metadata_input(raw_meta.strip())

    return raw_caption, {}


async def _require_admin(message: types.Message) -> bool:
    if not is_admin_user(message.from_user.id):
        await message.answer("This command is available to admins only.")
        return False
    return True


async def _require_staff(message: types.Message) -> bool:
    if not is_moderator_user(message.from_user.id):
        await message.answer("This command is available to moderators/admins only.")
        return False
    return True


@router.message(Command("admin"))
async def cmd_admin(message: types.Message) -> None:
    if not await _require_admin(message):
        return

    await message.answer(_admin_help_text())


@router.message(
    Command("cancel"),
    StateFilter(
        Upload.waiting_for_title,
        Upload.waiting_for_metadata,
        Upload.waiting_for_file,
        BulkMusicUpload.waiting_for_files,
        BulkVideoUpload.waiting_for_files,
        Broadcast.waiting_for_message,
    ),
)
async def cmd_cancel(message: types.Message, state: FSMContext) -> None:
    if not await _require_staff(message):
        return

    if await state.get_state() is None:
        await message.answer("No active admin action.")
        return

    await state.clear()
    await message.answer("Action cancelled.")


@router.message(Command("addvideo"))
async def cmd_addvideo(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    await state.clear()
    await state.set_state(Upload.waiting_for_title)
    await state.update_data(category="video")
    await message.answer(
        "Send the video title. Use /cancel to abort.\n"
        "Tip: while sending the file, caption can override title/metadata:\n"
        "My Video Title | genre=Education;tags=tutorial,lesson;language=en"
    )


@router.message(Command("addmusic"))
async def cmd_addmusic(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    await state.clear()
    await state.set_state(Upload.waiting_for_title)
    await state.update_data(category="music")
    await message.answer(
        "Send the music title. Use /cancel to abort.\n"
        "Tip: while sending the file, caption can override title/metadata:\n"
        "My Song Title | artist=Name;genre=Pop;tags=tag1,tag2"
    )


@router.message(Command("addmusicbulk"))
async def cmd_addmusicbulk(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    await state.clear()
    await state.set_state(BulkMusicUpload.waiting_for_files)
    await state.update_data(
        bulk_category="music",
        bulk_total=0,
        bulk_new=0,
        bulk_updated=0,
    )
    await message.answer(
        "Bulk music upload started.\n"
        "Send audio files one by one.\n"
        "Optional caption format:\n"
        "My Song Title | artist=Name;genre=Pop;tags=tag1,tag2\n"
        "Use /done to finish, /cancel to abort."
    )


@router.message(Command("addvideobulk"))
async def cmd_addvideobulk(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    await state.clear()
    await state.set_state(BulkVideoUpload.waiting_for_files)
    await state.update_data(
        bulk_category="video",
        bulk_total=0,
        bulk_new=0,
        bulk_updated=0,
    )
    await message.answer(
        "Bulk video upload started.\n"
        "Send video files one by one.\n"
        "Optional caption format:\n"
        "My Video Title | genre=Education;tags=tutorial,lesson;language=en\n"
        "Use /done to finish, /cancel to abort."
    )


def _extract_bulk_title_and_metadata(message: types.Message) -> tuple[str, dict[str, object]]:
    if not message.audio:
        return ("", {})

    title_from_caption, metadata = _parse_caption_payload(message.caption)

    title = (
        title_from_caption
        or (message.audio.title or "").strip()
        or (message.audio.file_name or "").strip()
        or f"Track {message.audio.file_unique_id[:8]}"
    )

    if message.audio.performer:
        metadata.setdefault("artist", message.audio.performer)
    if message.audio.duration:
        metadata.setdefault("duration", message.audio.duration)

    return title, metadata


def _extract_bulk_video_title_and_metadata(message: types.Message) -> tuple[str, dict[str, object]]:
    if not message.video:
        return ("", {})

    title_from_caption, metadata = _parse_caption_payload(message.caption)

    title = title_from_caption or f"Video {message.video.file_unique_id[:8]}"
    if message.video.duration:
        metadata.setdefault("duration", message.video.duration)
    return title, metadata


@router.message(
    Command("done"),
    StateFilter(BulkMusicUpload.waiting_for_files, BulkVideoUpload.waiting_for_files),
)
async def cmd_done_bulk_upload(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    data = await state.get_data()
    bulk_category = str(data.get("bulk_category", "music"))
    total = int(data.get("bulk_total", 0))
    created = int(data.get("bulk_new", 0))
    updated = int(data.get("bulk_updated", 0))
    await state.clear()

    await message.answer(
        "Bulk upload finished.\n"
        f"Processed: {total}\n"
        f"New: {created}\n"
        f"Duplicates updated: {updated}"
    )

    log_audit_event(
        actor_id=message.from_user.id,
        action=f"bulk_{bulk_category}_upload_finished",
        target_type="content",
        details={
            "category": bulk_category,
            "processed": total,
            "new": created,
            "updated": updated,
        },
    )


@router.message(BulkMusicUpload.waiting_for_files, F.audio)
async def process_bulk_music_file(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can upload content.")
        return

    if not message.audio:
        await message.answer("Please send an audio file.")
        return

    title, metadata = _extract_bulk_title_and_metadata(message)
    content_id, is_new = add_content(
        title,
        "music",
        message.audio.file_id,
        file_unique_id=message.audio.file_unique_id,
        metadata=metadata,
        uploaded_by=message.from_user.id,
    )

    data = await state.get_data()
    total = int(data.get("bulk_total", 0)) + 1
    created = int(data.get("bulk_new", 0)) + (1 if is_new else 0)
    updated = int(data.get("bulk_updated", 0)) + (0 if is_new else 1)
    await state.update_data(bulk_total=total, bulk_new=created, bulk_updated=updated)

    if is_new:
        await message.answer(f"Saved [{total}] ID {content_id}: {title}")
    else:
        await message.answer(f"Duplicate updated [{total}] ID {content_id}: {title}")

    log_audit_event(
        actor_id=message.from_user.id,
        action="content_uploaded" if is_new else "content_deduplicated",
        target_type="content",
        target_id=content_id,
        details={
            "category": "music",
            "title": title,
            "file_unique_id": message.audio.file_unique_id,
            "bulk_mode": True,
        },
    )


@router.message(BulkMusicUpload.waiting_for_files)
async def process_bulk_music_invalid(message: types.Message) -> None:
    await message.answer("Bulk mode expects audio files only. Send audio, /done, or /cancel.")


@router.message(BulkVideoUpload.waiting_for_files, F.video)
async def process_bulk_video_file(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can upload content.")
        return

    if not message.video:
        await message.answer("Please send a video file.")
        return

    title, metadata = _extract_bulk_video_title_and_metadata(message)
    content_id, is_new = add_content(
        title,
        "video",
        message.video.file_id,
        file_unique_id=message.video.file_unique_id,
        metadata=metadata,
        uploaded_by=message.from_user.id,
    )

    data = await state.get_data()
    total = int(data.get("bulk_total", 0)) + 1
    created = int(data.get("bulk_new", 0)) + (1 if is_new else 0)
    updated = int(data.get("bulk_updated", 0)) + (0 if is_new else 1)
    await state.update_data(bulk_total=total, bulk_new=created, bulk_updated=updated)

    if is_new:
        await message.answer(f"Saved [{total}] ID {content_id}: {title}")
    else:
        await message.answer(f"Duplicate updated [{total}] ID {content_id}: {title}")

    log_audit_event(
        actor_id=message.from_user.id,
        action="content_uploaded" if is_new else "content_deduplicated",
        target_type="content",
        target_id=content_id,
        details={
            "category": "video",
            "title": title,
            "file_unique_id": message.video.file_unique_id,
            "bulk_mode": True,
        },
    )


@router.message(BulkVideoUpload.waiting_for_files)
async def process_bulk_video_invalid(message: types.Message) -> None:
    await message.answer("Bulk mode expects video files only. Send video, /done, or /cancel.")


@router.message(Upload.waiting_for_title, F.text)
async def process_title(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can upload content.")
        return

    title = (message.text or "").strip()
    if title == "/skip":
        await state.update_data(title="", metadata={})
        await state.set_state(Upload.waiting_for_file)
        await message.answer(
            "Title/metadata skipped. Now send the media file.\n"
            "Optional file caption format:\n"
            "Title | artist=Name;genre=Pop;tags=tag1,tag2"
        )
        return

    if not title:
        await message.answer("Title cannot be empty. Send a valid title.")
        return

    await state.update_data(title=title)
    await state.set_state(Upload.waiting_for_metadata)
    await message.answer(
        "Send metadata in this format (or /skip):\n"
        "artist=Name;genre=Pop;tags=tag1,tag2;language=en;year=2026"
    )


@router.message(Upload.waiting_for_title, F.video | F.audio)
async def process_file_from_title_step(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can upload content.")
        return

    await state.update_data(title="", metadata={})
    await state.set_state(Upload.waiting_for_file)
    await process_file(message, state)


@router.message(Upload.waiting_for_title)
async def process_title_invalid(message: types.Message) -> None:
    await message.answer(
        "Send a title text, or /skip, or send the media file directly with optional caption."
    )


@router.message(Command("skip"), Upload.waiting_for_metadata)
async def skip_metadata(message: types.Message, state: FSMContext) -> None:
    await state.update_data(metadata={})
    await state.set_state(Upload.waiting_for_file)
    await message.answer(
        "Metadata skipped. Now send the media file.\n"
        "Optional file caption format:\n"
        "Title | artist=Name;genre=Pop;tags=tag1,tag2"
    )


@router.message(Upload.waiting_for_metadata)
async def process_metadata(message: types.Message, state: FSMContext) -> None:
    raw_input = (message.text or "").strip()
    metadata = _parse_metadata_input(raw_input)

    await state.update_data(metadata=metadata)
    await state.set_state(Upload.waiting_for_file)
    await message.answer(
        "Metadata saved. Now send the media file.\n"
        "Optional file caption format:\n"
        "Title | artist=Name;genre=Pop;tags=tag1,tag2"
    )


@router.message(Upload.waiting_for_file, F.video | F.audio)
async def process_file(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can upload content.")
        return

    data = await state.get_data()
    category = data.get("category")
    title = str(data.get("title", "")).strip()
    metadata = dict(data.get("metadata", {})) if isinstance(data.get("metadata"), dict) else {}

    caption_title, caption_metadata = _parse_caption_payload(message.caption)
    if caption_title:
        title = caption_title
    if caption_metadata:
        metadata.update(caption_metadata)

    if not category:
        await state.clear()
        await message.answer("Upload state lost. Please start again with /addvideo or /addmusic.")
        return

    file_id = None
    file_unique_id = None
    if category == "video" and message.video:
        file_id = message.video.file_id
        file_unique_id = message.video.file_unique_id
        if not title:
            title = f"Video {file_unique_id[:8]}"
        metadata.setdefault("duration", message.video.duration)
    elif category == "music" and message.audio:
        file_id = message.audio.file_id
        file_unique_id = message.audio.file_unique_id
        if not title:
            title = (
                (message.audio.title or "").strip()
                or (message.audio.file_name or "").strip()
                or f"Track {file_unique_id[:8]}"
            )
        metadata.setdefault("duration", message.audio.duration)
        if message.audio.performer:
            metadata.setdefault("artist", message.audio.performer)

    if not file_id:
        expected = "video" if category == "video" else "audio"
        await message.answer(f"Wrong file type. Please send a {expected} file.")
        return

    content_id, is_new = add_content(
        title,
        category,
        file_id,
        file_unique_id=file_unique_id,
        metadata=metadata,
        uploaded_by=message.from_user.id,
    )
    await state.clear()

    if is_new:
        await message.answer(
            f"Saved successfully.\n"
            f"ID: {content_id}\n"
            f"Type: {category}\n"
            f"Title: {title}"
        )
    else:
        await message.answer(
            f"Duplicate detected. Existing content updated.\n"
            f"ID: {content_id}\n"
            f"Type: {category}\n"
            f"Title: {title}"
        )

    log_audit_event(
        actor_id=message.from_user.id,
        action="content_uploaded" if is_new else "content_deduplicated",
        target_type="content",
        target_id=content_id,
        details={
            "category": category,
            "title": title,
            "file_unique_id": file_unique_id,
        },
    )


@router.message(Upload.waiting_for_file)
async def process_file_invalid(message: types.Message, state: FSMContext) -> None:
    data = await state.get_data()
    category = data.get("category", "video")
    expected = "video" if category == "video" else "audio"
    await message.answer(f"Please send a {expected} file.")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: types.Message, state: FSMContext) -> None:
    if not await _require_admin(message):
        return

    await state.clear()
    await state.set_state(Broadcast.waiting_for_message)
    await message.answer(
        "Send the message you want to broadcast (text, photo, video, audio, or document).\n"
        "Use /cancel to abort."
    )


@router.message(Broadcast.waiting_for_message)
async def process_broadcast(message: types.Message, state: FSMContext) -> None:
    if not is_admin_user(message.from_user.id):
        await state.clear()
        await message.answer("Only admins can broadcast.")
        return

    await state.clear()
    success, failed = await broadcast_copy_message(message.bot, message)
    await message.answer(
        f"Broadcast completed.\n"
        f"Delivered: {success}\n"
        f"Failed: {failed}"
    )

    log_audit_event(
        actor_id=message.from_user.id,
        action="broadcast_sent",
        target_type="users",
        details={"delivered": success, "failed": failed},
    )


@router.message(Command("stats"))
async def cmd_stats(message: types.Message) -> None:
    if not await _require_staff(message):
        return

    total_users = get_total_users()
    total_content = get_total_content()
    by_category = get_content_totals_by_category()
    by_role = get_user_counts_by_role()

    video_count = by_category.get("video", 0)
    music_count = by_category.get("music", 0)
    other_count = sum(count for key, count in by_category.items() if key not in {"video", "music"})

    await message.answer(
        "Bot stats:\n"
        f"Users: {total_users}\n"
        f"  - Admins: {by_role.get('admin', 0)}\n"
        f"  - Moderators: {by_role.get('moderator', 0)}\n"
        f"  - Regular users: {by_role.get('user', 0)}\n"
        f"Total content: {total_content}\n"
        f"Videos: {video_count}\n"
        f"Music: {music_count}\n"
        f"Other: {other_count}"
    )


@router.message(Command("listcontent"))
async def cmd_listcontent(message: types.Message, command: CommandObject) -> None:
    if not await _require_staff(message):
        return

    try:
        category, page = _parse_listcontent_args(command.args)
    except ValueError as exc:
        await message.answer(
            f"Invalid arguments: {exc}\n"
            "Usage: /listcontent [video|music] [page]"
        )
        return

    if category:
        total_items = count_content_by_category(category)
    else:
        total_items = get_total_content()

    if total_items == 0:
        await message.answer("No content found.")
        return

    total_pages = max(1, math.ceil(total_items / PAGE_SIZE))
    page = min(page, total_pages)
    offset = (page - 1) * PAGE_SIZE

    items = get_recent_content(limit=PAGE_SIZE, offset=offset, category=category)
    if not items:
        await message.answer("No content on this page.")
        return

    scope = category if category else "all categories"
    lines = [f"Content list ({scope}) page {page}/{total_pages}:"]
    for content_id, title, item_category, _upload_date in items:
        short_title = title if len(title) <= 60 else f"{title[:57]}..."
        lines.append(f"{content_id}. [{item_category}] {short_title}")

    lines.append("Use /delete <id> to remove an item.")
    await message.answer("\n".join(lines))


@router.message(Command("delete"))
async def cmd_delete(message: types.Message, command: CommandObject) -> None:
    if not await _require_staff(message):
        return

    if not command.args:
        await message.answer("Usage: /delete <content_id>")
        return

    raw_id = command.args.strip()
    try:
        content_id = int(raw_id)
    except ValueError:
        await message.answer("Content ID must be an integer.")
        return

    deleted = delete_content_by_id(content_id)
    if not deleted:
        await message.answer(f"Content ID {content_id} not found.")
        return

    await message.answer(f"Deleted content ID {content_id}.")

    log_audit_event(
        actor_id=message.from_user.id,
        action="content_deleted",
        target_type="content",
        target_id=content_id,
    )


@router.message(Command("health"))
async def cmd_health(message: types.Message) -> None:
    if not await _require_admin(message):
        return

    health = get_health_snapshot()
    uptime = format_uptime(get_uptime_seconds())
    latest_backup = get_latest_backup_file()

    lines = [
        "Health report:",
        f"Uptime: {uptime}",
        f"Periodic backup: {'enabled' if ENABLE_PERIODIC_BACKUP else 'disabled'}",
        f"Backup interval (min): {BACKUP_INTERVAL_MINUTES}",
    ]

    if health.get("ok"):
        collections = health.get("collections", {})
        roles = health.get("roles", {})
        lines.extend(
            [
                f"MongoDB: OK ({health.get('latency_ms')} ms)",
                f"Database: {health.get('db_name')}",
                f"Collections -> users: {collections.get('users', 0)}, content: {collections.get('content', 0)}, favorites: {collections.get('favorites', 0)}, playlists: {collections.get('playlists', 0)}",
                f"Roles -> admins: {roles.get('admin', 0)}, moderators: {roles.get('moderator', 0)}, users: {roles.get('user', 0)}",
            ]
        )
    else:
        lines.extend(
            [
                "MongoDB: ERROR",
                f"Error: {health.get('error', 'unknown error')}",
            ]
        )

    if latest_backup:
        lines.append(f"Latest backup: {latest_backup.name}")
    else:
        lines.append("Latest backup: none")

    await message.answer("\n".join(lines))


@router.message(Command("setmoderator"))
async def cmd_set_moderator(message: types.Message, command: CommandObject) -> None:
    if not await _require_admin(message):
        return

    try:
        user_id = _parse_target_user_id(message, command.args)
        set_user_role(user_id, "moderator")
    except ValueError as exc:
        await message.answer(f"Failed to set moderator: {exc}")
        return

    await message.answer(f"User {user_id} is now a moderator.")

    log_audit_event(
        actor_id=message.from_user.id,
        action="moderator_granted",
        target_type="user",
        target_id=user_id,
    )


@router.message(Command("removemoderator"))
async def cmd_remove_moderator(message: types.Message, command: CommandObject) -> None:
    if not await _require_admin(message):
        return

    try:
        user_id = _parse_target_user_id(message, command.args)
        set_user_role(user_id, "user")
    except ValueError as exc:
        await message.answer(f"Failed to remove moderator: {exc}")
        return

    await message.answer(f"User {user_id} is now a regular user.")

    log_audit_event(
        actor_id=message.from_user.id,
        action="moderator_revoked",
        target_type="user",
        target_id=user_id,
    )


@router.message(Command("export_content"))
async def cmd_export_content(message: types.Message) -> None:
    if not await _require_admin(message):
        return

    backup_file = create_backup_dump(prefix="manual_export")
    file_bytes = backup_file.read_bytes()
    document = BufferedInputFile(file_bytes, filename=backup_file.name)

    await message.answer_document(
        document=document,
        caption=f"Export created successfully.\nFile: {backup_file.name}",
    )

    log_audit_event(
        actor_id=message.from_user.id,
        action="backup_exported",
        target_type="backup",
        details={"file": backup_file.name},
    )


@router.message(Command("audit"))
async def cmd_audit(message: types.Message, command: CommandObject) -> None:
    if not await _require_admin(message):
        return

    limit = 10
    if command.args:
        try:
            limit = max(1, min(50, int(command.args.strip())))
        except ValueError:
            await message.answer("Usage: /audit [1-50]")
            return

    events = get_recent_audit_logs(limit=limit)
    if not events:
        await message.answer("No audit logs found.")
        return

    lines = [f"Recent audit events ({len(events)}):"]
    for event in events:
        ts = str(event.get("timestamp", ""))
        actor_id = event.get("actor_id", "?")
        action = event.get("action", "unknown")
        target_type = event.get("target_type")
        target_id = event.get("target_id")

        target_part = ""
        if target_type:
            target_part = f" -> {target_type}"
            if target_id is not None:
                target_part += f":{target_id}"

        lines.append(f"{ts} | user={actor_id} | {action}{target_part}")

    await message.answer("\n".join(lines))
