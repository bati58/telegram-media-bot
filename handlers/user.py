from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import (
    add_favorite,
    add_to_playlist,
    count_content_by_category,
    create_playlist,
    delete_playlist,
    get_content_by_category,
    get_content_by_id,
    get_content_metadata,
    get_playlist,
    list_favorites,
    list_playlist_items,
    list_playlists,
    log_audit_event,
    remove_favorite,
    remove_from_playlist,
)
from keyboards import (
    category_keyboard,
    item_actions_keyboard,
    item_keyboard,
    library_menu_keyboard,
    main_menu,
    playlist_picker_keyboard,
    playlists_keyboard,
)
from utils import ensure_callback_membership, ensure_message_membership

router = Router()

PAGE_SIZE = 8
ALLOWED_CATEGORIES = {"video", "music"}


def _clamp_page(page: int, total_items: int) -> int:
    if total_items <= 0:
        return 0
    max_page = (total_items - 1) // PAGE_SIZE
    return max(0, min(page, max_page))


def _build_media_caption(title: str, metadata: dict) -> str:
    lines = [title]
    artist = metadata.get("artist")
    genre = metadata.get("genre")
    tags = metadata.get("tags")

    if artist:
        lines.append(f"Artist: {artist}")
    if genre:
        lines.append(f"Genre: {genre}")
    if isinstance(tags, list) and tags:
        lines.append(f"Tags: {', '.join(tags[:6])}")

    return "\n".join(lines)


def _parse_int_args(args: str | None, expected_count: int) -> list[int]:
    if not args:
        raise ValueError("Missing required arguments.")

    parts = args.split()
    if len(parts) != expected_count:
        raise ValueError("Invalid number of arguments.")

    try:
        return [int(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Arguments must be integers.") from exc


@router.callback_query(F.data.startswith("category_"))
async def show_category(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    parts = callback.data.split("_")
    if len(parts) < 2:
        await callback.answer("Invalid category.", show_alert=True)
        return

    category = parts[1].lower()
    if category not in ALLOWED_CATEGORIES:
        await callback.answer("Unknown category.", show_alert=True)
        return

    requested_page = 0
    if len(parts) >= 3:
        try:
            requested_page = int(parts[2])
        except ValueError:
            requested_page = 0

    total_items = count_content_by_category(category)
    if total_items == 0:
        await callback.message.edit_text(
            f"No {category} available yet.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="back_to_main")]]
            ),
        )
        await callback.answer()
        return

    page = _clamp_page(requested_page, total_items)
    offset = page * PAGE_SIZE
    items = get_content_by_category(category, limit=PAGE_SIZE, offset=offset)

    display_items = [(item_id, title) for item_id, title, _file_id in items]
    prev_callback = f"category_{category}_{page - 1}" if page > 0 else None
    next_callback = (
        f"category_{category}_{page + 1}" if (offset + len(items)) < total_items else None
    )

    total_pages = (total_items + PAGE_SIZE - 1) // PAGE_SIZE
    await callback.message.edit_text(
        f"{category.capitalize()} ({page + 1}/{total_pages})\nSelect an item:",
        reply_markup=category_keyboard(
            display_items,
            prev_callback=prev_callback,
            next_callback=next_callback,
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("item_"))
async def send_item(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    try:
        item_id = int(callback.data.split("_")[1])
    except (ValueError, IndexError):
        await callback.answer("Invalid item.", show_alert=True)
        return

    item = get_content_by_id(item_id)
    if not item:
        await callback.answer("Item not found.", show_alert=True)
        return

    _, title, category, file_id, _ = item
    metadata = get_content_metadata(item_id)
    caption = _build_media_caption(title, metadata)

    if category == "video":
        await callback.message.answer_video(file_id, caption=caption)
    elif category == "music":
        await callback.message.answer_audio(file_id, caption=caption)
    else:
        await callback.message.answer_document(file_id, caption=caption)

    await callback.message.answer(
        "Actions:",
        reply_markup=item_actions_keyboard(item_id),
    )

    await callback.answer("Sent")


@router.callback_query(F.data == "my_library")
async def show_library(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    await callback.message.edit_text("My Library", reply_markup=library_menu_keyboard())
    await callback.answer()


@router.callback_query(F.data == "library_favorites")
async def show_favorites_callback(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    items = list_favorites(callback.from_user.id, limit=50)
    if not items:
        await callback.message.edit_text(
            "You have no favorites yet.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="my_library")]]
            ),
        )
        await callback.answer()
        return

    display_items = [(item_id, f"[{category}] {title}") for item_id, title, category, _ in items]
    await callback.message.edit_text(
        "Your favorites:",
        reply_markup=item_keyboard(display_items, back_callback="my_library"),
    )
    await callback.answer()


@router.callback_query(F.data == "library_playlists")
async def show_playlists_callback(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    playlists = list_playlists(callback.from_user.id)
    if not playlists:
        await callback.message.edit_text(
            "No playlists yet. Use /createplaylist <name>.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="my_library")]]
            ),
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "Your playlists:",
        reply_markup=playlists_keyboard(playlists),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("playlist_open_"))
async def open_playlist_callback(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    try:
        playlist_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid playlist.", show_alert=True)
        return

    playlist = get_playlist(callback.from_user.id, playlist_id)
    if not playlist:
        await callback.answer("Playlist not found.", show_alert=True)
        return

    items = list_playlist_items(callback.from_user.id, playlist_id, limit=100)
    if not items:
        await callback.message.edit_text(
            f"Playlist '{playlist.get('name', 'Unnamed')}' is empty.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="library_playlists")]]
            ),
        )
        await callback.answer()
        return

    display_items = [(item_id, f"[{category}] {title}") for item_id, title, category, _ in items]
    await callback.message.edit_text(
        f"Playlist: {playlist.get('name', 'Unnamed')}",
        reply_markup=item_keyboard(display_items, back_callback="library_playlists"),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("playlist_delete_"))
async def delete_playlist_callback(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    try:
        playlist_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid playlist.", show_alert=True)
        return

    deleted = delete_playlist(callback.from_user.id, playlist_id)
    if not deleted:
        await callback.answer("Playlist not found.", show_alert=True)
        return

    log_audit_event(
        actor_id=callback.from_user.id,
        action="playlist_deleted",
        target_type="playlist",
        target_id=playlist_id,
    )

    playlists = list_playlists(callback.from_user.id)
    if not playlists:
        await callback.message.edit_text(
            "Playlist deleted. No playlists left.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="Back", callback_data="my_library")]]
            ),
        )
        await callback.answer("Deleted")
        return

    await callback.message.edit_text(
        "Your playlists:",
        reply_markup=playlists_keyboard(playlists),
    )
    await callback.answer("Deleted")


@router.callback_query(F.data.startswith("fav_add_"))
async def add_favorite_callback(callback: types.CallbackQuery) -> None:
    if not await ensure_callback_membership(callback):
        return

    try:
        content_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid content ID.", show_alert=True)
        return

    try:
        created = add_favorite(callback.from_user.id, content_id)
    except ValueError:
        await callback.answer("Content not found.", show_alert=True)
        return

    log_audit_event(
        actor_id=callback.from_user.id,
        action="favorite_added" if created else "favorite_exists",
        target_type="content",
        target_id=content_id,
    )
    await callback.answer("Added to favorites" if created else "Already in favorites")


@router.callback_query(F.data.startswith("fav_remove_"))
async def remove_favorite_callback(callback: types.CallbackQuery) -> None:
    if not await ensure_callback_membership(callback):
        return

    try:
        content_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid content ID.", show_alert=True)
        return

    removed = remove_favorite(callback.from_user.id, content_id)
    log_audit_event(
        actor_id=callback.from_user.id,
        action="favorite_removed" if removed else "favorite_remove_noop",
        target_type="content",
        target_id=content_id,
    )
    await callback.answer("Removed from favorites" if removed else "Not in favorites")


@router.callback_query(F.data.startswith("pl_pick_"))
async def pick_playlist_callback(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    try:
        content_id = int(callback.data.split("_")[2])
    except (ValueError, IndexError):
        await callback.answer("Invalid content ID.", show_alert=True)
        return

    playlists = list_playlists(callback.from_user.id)
    if not playlists:
        await callback.message.answer("No playlists found. Create one with /createplaylist <name>.")
        await callback.answer()
        return

    await callback.message.answer(
        "Choose a playlist:",
        reply_markup=playlist_picker_keyboard(playlists, content_id=content_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("pl_add_"))
async def add_to_playlist_callback(callback: types.CallbackQuery) -> None:
    if not await ensure_callback_membership(callback):
        return

    parts = callback.data.split("_")
    if len(parts) != 4:
        await callback.answer("Invalid action.", show_alert=True)
        return

    try:
        playlist_id = int(parts[2])
        content_id = int(parts[3])
    except ValueError:
        await callback.answer("Invalid IDs.", show_alert=True)
        return

    try:
        added = add_to_playlist(callback.from_user.id, playlist_id, content_id)
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    log_audit_event(
        actor_id=callback.from_user.id,
        action="playlist_item_added" if added else "playlist_item_exists",
        target_type="playlist",
        target_id=playlist_id,
        details={"content_id": content_id},
    )
    await callback.answer("Added to playlist" if added else "Already in playlist")


@router.message(Command("favorite"))
async def cmd_favorite(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        content_id = _parse_int_args(command.args, 1)[0]
        created = add_favorite(message.from_user.id, content_id)
    except ValueError as exc:
        await message.answer(f"Usage: /favorite <content_id>\nError: {exc}")
        return

    log_audit_event(
        actor_id=message.from_user.id,
        action="favorite_added" if created else "favorite_exists",
        target_type="content",
        target_id=content_id,
    )
    await message.answer("Added to favorites." if created else "Already in favorites.")


@router.message(Command("unfavorite"))
async def cmd_unfavorite(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        content_id = _parse_int_args(command.args, 1)[0]
    except ValueError as exc:
        await message.answer(f"Usage: /unfavorite <content_id>\nError: {exc}")
        return

    removed = remove_favorite(message.from_user.id, content_id)
    log_audit_event(
        actor_id=message.from_user.id,
        action="favorite_removed" if removed else "favorite_remove_noop",
        target_type="content",
        target_id=content_id,
    )
    await message.answer("Removed from favorites." if removed else "Not in favorites.")


@router.message(Command("favorites"))
async def cmd_favorites(message: types.Message) -> None:
    if not await ensure_message_membership(message):
        return

    items = list_favorites(message.from_user.id, limit=50)
    if not items:
        await message.answer("You have no favorites yet.")
        return

    display_items = [(item_id, f"[{category}] {title}") for item_id, title, category, _ in items]
    await message.answer("Your favorites:", reply_markup=item_keyboard(display_items))


@router.message(Command("createplaylist"))
async def cmd_create_playlist(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    if not command.args:
        await message.answer("Usage: /createplaylist <name>")
        return

    try:
        playlist_id = create_playlist(message.from_user.id, command.args.strip())
    except ValueError as exc:
        await message.answer(f"Cannot create playlist: {exc}")
        return

    log_audit_event(
        actor_id=message.from_user.id,
        action="playlist_created",
        target_type="playlist",
        target_id=playlist_id,
    )
    await message.answer(f"Playlist created. ID: {playlist_id}")


@router.message(Command("playlists"))
async def cmd_playlists(message: types.Message) -> None:
    if not await ensure_message_membership(message):
        return

    playlists = list_playlists(message.from_user.id)
    if not playlists:
        await message.answer("No playlists yet. Create one with /createplaylist <name>.")
        return

    await message.answer("Your playlists:", reply_markup=playlists_keyboard(playlists, back_callback="back_to_main"))


@router.message(Command("playlist"))
async def cmd_playlist(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        playlist_id = _parse_int_args(command.args, 1)[0]
    except ValueError as exc:
        await message.answer(f"Usage: /playlist <playlist_id>\nError: {exc}")
        return

    try:
        playlist = get_playlist(message.from_user.id, playlist_id)
        if not playlist:
            await message.answer("Playlist not found.")
            return

        items = list_playlist_items(message.from_user.id, playlist_id, limit=100)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    if not items:
        await message.answer(f"Playlist '{playlist.get('name', 'Unnamed')}' is empty.")
        return

    display_items = [(item_id, f"[{category}] {title}") for item_id, title, category, _ in items]
    await message.answer(
        f"Playlist: {playlist.get('name', 'Unnamed')}",
        reply_markup=item_keyboard(display_items),
    )


@router.message(Command("addtoplaylist"))
async def cmd_add_to_playlist(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        playlist_id, content_id = _parse_int_args(command.args, 2)
        added = add_to_playlist(message.from_user.id, playlist_id, content_id)
    except ValueError as exc:
        await message.answer(f"Usage: /addtoplaylist <playlist_id> <content_id>\nError: {exc}")
        return

    log_audit_event(
        actor_id=message.from_user.id,
        action="playlist_item_added" if added else "playlist_item_exists",
        target_type="playlist",
        target_id=playlist_id,
        details={"content_id": content_id},
    )
    await message.answer("Added to playlist." if added else "Already in playlist.")


@router.message(Command("removefromplaylist"))
async def cmd_remove_from_playlist(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        playlist_id, content_id = _parse_int_args(command.args, 2)
        removed = remove_from_playlist(message.from_user.id, playlist_id, content_id)
    except ValueError as exc:
        await message.answer(f"Usage: /removefromplaylist <playlist_id> <content_id>\nError: {exc}")
        return

    log_audit_event(
        actor_id=message.from_user.id,
        action="playlist_item_removed" if removed else "playlist_item_remove_noop",
        target_type="playlist",
        target_id=playlist_id,
        details={"content_id": content_id},
    )
    await message.answer("Removed from playlist." if removed else "Item not in playlist.")


@router.message(Command("deleteplaylist"))
async def cmd_delete_playlist(message: types.Message, command: CommandObject) -> None:
    if not await ensure_message_membership(message):
        return

    try:
        playlist_id = _parse_int_args(command.args, 1)[0]
    except ValueError as exc:
        await message.answer(f"Usage: /deleteplaylist <playlist_id>\nError: {exc}")
        return

    deleted = delete_playlist(message.from_user.id, playlist_id)
    if not deleted:
        await message.answer("Playlist not found.")
        return

    log_audit_event(
        actor_id=message.from_user.id,
        action="playlist_deleted",
        target_type="playlist",
        target_id=playlist_id,
    )
    await message.answer(f"Playlist {playlist_id} deleted.")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    await callback.message.edit_text("Choose a category:", reply_markup=main_menu())
    await callback.answer()
