from aiogram import F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import search_content_advanced
from keyboards import item_keyboard, main_menu
from search_filters import format_search_filters, parse_search_query
from utils import ensure_callback_membership, ensure_message_membership

router = Router()


class SearchState(StatesGroup):
    waiting_for_query = State()


SEARCH_PROMPT = (
    "Send search query with optional filters. Use /cancel to stop.\n"
    "Examples:\n"
    "- hello\n"
    "- cat:music artist:adele\n"
    "- #gospel lang:en sort:newest limit:20"
)


async def _prompt_for_query(message: types.Message, state: FSMContext) -> None:
    await message.answer(SEARCH_PROMPT)
    await state.set_state(SearchState.waiting_for_query)


async def _execute_search(message: types.Message, raw_query: str) -> None:
    filters = parse_search_query(raw_query, default_limit=25, max_limit=50)

    has_constraints = any(
        [
            filters.query_text,
            filters.category,
            filters.tags,
            filters.language,
            filters.artist,
            filters.genre,
        ]
    )
    if not has_constraints:
        await message.answer(
            "Please provide a query or at least one filter.\n"
            "Example: /search cat:music #gospel"
        )
        return

    results = search_content_advanced(
        query_text=filters.query_text,
        category=filters.category,
        tags=filters.tags,
        language=filters.language,
        artist=filters.artist,
        genre=filters.genre,
        sort=filters.sort,
        limit=filters.limit,
    )

    if not results:
        await message.answer(
            f"No matches found.\nFilters: {format_search_filters(filters)}",
            reply_markup=main_menu(),
        )
        return

    keyboard_items = [
        (item_id, f"[{category.capitalize()}] {title}")
        for item_id, title, category, _file_id in results
    ]

    await message.answer(
        f"Found {len(results)} result(s).\n"
        f"Filters: {format_search_filters(filters)}\n"
        "Tap one to receive the file:",
        reply_markup=item_keyboard(keyboard_items),
    )


@router.callback_query(F.data == "search")
async def search_prompt_callback(callback: types.CallbackQuery, state: FSMContext) -> None:
    if not callback.message:
        await callback.answer()
        return

    if not await ensure_callback_membership(callback):
        return

    await callback.message.edit_text(SEARCH_PROMPT)
    await state.set_state(SearchState.waiting_for_query)
    await callback.answer()


@router.message(Command("search"))
async def search_prompt_command(
    message: types.Message,
    state: FSMContext,
    command: CommandObject,
) -> None:
    if not await ensure_message_membership(message):
        return

    if command.args and command.args.strip():
        await state.clear()
        await _execute_search(message, command.args.strip())
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

    await state.clear()
    await _execute_search(message, query)
