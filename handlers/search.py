from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import search_content
from keyboards import item_keyboard, main_menu
from utils import ensure_callback_membership, ensure_message_membership

router = Router()


class SearchState(StatesGroup):
    waiting_for_query = State()


async def _prompt_for_query(message: types.Message, state: FSMContext) -> None:
    await message.answer("Send the title (or part of it) to search. Use /cancel to stop.")
    await state.set_state(SearchState.waiting_for_query)


@router.callback_query(F.data == "search")
async def search_prompt_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    await callback.message.edit_text("Send the title (or part of it) to search. Use /cancel to stop.")
    await state.set_state(SearchState.waiting_for_query)
    await callback.answer()


@router.message(Command("search"))
async def search_prompt_command(message: types.Message, state: FSMContext) -> None:
    if not await ensure_message_membership(message):
        return

    await _prompt_for_query(message, state)


@router.message(SearchState.waiting_for_query, Command("cancel"))
async def cancel_search(message: types.Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Search cancelled.", reply_markup=main_menu())


@router.message(SearchState.waiting_for_query)
async def process_search(message: types.Message, state: FSMContext) -> None:
    if not await ensure_message_membership(message):
        await state.clear()
        return

    query = (message.text or "").strip()
    if not query:
        await message.answer("Please send a text query.")
        return

    results = search_content(query, limit=25)
    await state.clear()

    if not results:
        await message.answer("No matches found.", reply_markup=main_menu())
        return

    keyboard_items = [
        (item_id, f"[{category.capitalize()}] {title}")
        for item_id, title, category, _file_id in results
    ]

    await message.answer(
        f"Found {len(results)} result(s). Tap one to receive the file:",
        reply_markup=item_keyboard(keyboard_items),
    )
