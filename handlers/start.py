from aiogram import F, Router, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext

from database import add_user, get_user_role
from keyboards import main_menu, required_channels_keyboard
from utils import (
    build_membership_required_text,
    ensure_message_membership,
    get_missing_required_channels,
)

router = Router()


def _build_help_text(user_id: int) -> str:
    role = get_user_role(user_id)

    lines = [
        "User commands:",
        "/start - Open main menu",
        "/help - Show command help",
        "/myid - Show your Telegram user ID",
        "/search [query] - Search with optional filters",
        "/favorites - Show your favorites",
        "/favorite <content_id> - Add item to favorites",
        "/unfavorite <content_id> - Remove item from favorites",
        "/playlists - Show your playlists",
        "/createplaylist <name> - Create playlist",
        "/playlist <playlist_id> - Show playlist items",
        "/addtoplaylist <playlist_id> <content_id> - Add item to playlist",
        "/removefromplaylist <playlist_id> <content_id> - Remove item from playlist",
        "/deleteplaylist <playlist_id> - Delete a playlist",
        "/cancel - Cancel active search",
    ]

    if role in {"moderator", "admin"}:
        lines.extend(
            [
                "",
                "Moderator commands:",
                "/stats - Show bot stats",
                "/listcontent [video|music] [page] - List content IDs",
                "/delete <id> - Delete content by ID",
            ]
        )

    if role == "admin":
        lines.extend(
            [
                "",
                "Admin commands:",
                "/admin - Show admin command list",
                "/addvideo - Add a video",
                "/addvideobulk - Bulk upload video files",
                "/addmusic - Add a music track",
                "/addmusicbulk - Bulk upload music files",
                "/broadcast - Broadcast any message to users",
                "/health - Service and DB health",
                "/setmoderator <id> - Grant moderator role",
                "/removemoderator <id> - Revoke moderator role",
                "/export_content - Export backup JSON",
                "/audit [n] - Show recent audit logs",
                "/done - Finish bulk upload session",
                "/cancel - Cancel current admin action",
            ]
        )

    return "\n".join(lines)


@router.message(Command("start"), StateFilter("*"))
async def cmd_start(message: types.Message, state: FSMContext) -> None:
    add_user(message.from_user.id)
    await state.clear()

    if not await ensure_message_membership(message):
        return

    await message.answer(
        "Welcome to Media Share Bot.\nChoose a category from the menu:",
        reply_markup=main_menu(),
    )


@router.message(Command("help"), StateFilter("*"))
async def cmd_help(message: types.Message) -> None:
    add_user(message.from_user.id)
    await message.answer(_build_help_text(message.from_user.id), reply_markup=main_menu())


@router.message(Command("myid"), StateFilter("*"))
async def cmd_myid(message: types.Message) -> None:
    add_user(message.from_user.id)
    await message.answer(f"Your Telegram ID: `{message.from_user.id}`", parse_mode="Markdown")


@router.callback_query(F.data == "help")
async def show_help(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    await callback.message.edit_text(
        _build_help_text(callback.from_user.id),
        reply_markup=main_menu(),
    )
    await callback.answer()


@router.callback_query(F.data == "check_membership")
async def check_membership(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    missing = await get_missing_required_channels(callback.bot, callback.from_user.id)
    if missing:
        await callback.message.edit_text(
            build_membership_required_text(missing),
            reply_markup=required_channels_keyboard(missing),
        )
        await callback.answer("You still need to join required channel(s).", show_alert=True)
        return

    await callback.message.edit_text(
        "Membership check passed. You can now use the bot.",
        reply_markup=main_menu(),
    )
    await callback.answer("Access granted")
