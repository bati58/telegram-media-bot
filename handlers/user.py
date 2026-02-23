from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database import count_content_by_category, get_content_by_category, get_content_by_id
from keyboards import category_keyboard, main_menu
from utils import ensure_callback_membership

router = Router()

PAGE_SIZE = 8
ALLOWED_CATEGORIES = {"video", "music"}


def _clamp_page(page: int, total_items: int) -> int:
    if total_items <= 0:
        return 0
    max_page = (total_items - 1) // PAGE_SIZE
    return max(0, min(page, max_page))


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
    if category == "video":
        await callback.message.answer_video(file_id, caption=title)
    elif category == "music":
        await callback.message.answer_audio(file_id, caption=title)
    else:
        await callback.message.answer_document(file_id, caption=title)

    await callback.answer("Sent")


@router.callback_query(F.data == "back_to_main")
async def back_to_main(callback: types.CallbackQuery) -> None:
    if not callback.message:
        await callback.answer()
        return

    await callback.message.edit_text("Choose a category:", reply_markup=main_menu())
    await callback.answer()
