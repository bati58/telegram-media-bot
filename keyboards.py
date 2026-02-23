from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def _truncate_title(title: str, max_length: int = 48) -> str:
    if len(title) <= max_length:
        return title
    return f"{title[: max_length - 3]}..."


def _channel_join_url(channel_ref: str) -> str | None:
    channel_ref = channel_ref.strip()
    if channel_ref.startswith("@"):
        return f"https://t.me/{channel_ref[1:]}"
    if channel_ref.startswith("https://t.me/"):
        return channel_ref
    if channel_ref.startswith("http://t.me/"):
        return f"https://{channel_ref.removeprefix('http://')}"
    if channel_ref.startswith("t.me/"):
        return f"https://{channel_ref}"
    return None


def _channel_display_name(channel_ref: str) -> str:
    if channel_ref.startswith("https://t.me/"):
        return f"@{channel_ref.removeprefix('https://t.me/').strip('/')}"
    if channel_ref.startswith("http://t.me/"):
        return f"@{channel_ref.removeprefix('http://t.me/').strip('/')}"
    if channel_ref.startswith("t.me/"):
        return f"@{channel_ref.removeprefix('t.me/').strip('/')}"
    return channel_ref


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Videos", callback_data="category_video")],
            [InlineKeyboardButton(text="Music", callback_data="category_music")],
            [
                InlineKeyboardButton(text="Search", callback_data="search"),
                InlineKeyboardButton(text="Help", callback_data="help"),
            ],
        ]
    )


def item_keyboard(
    items: list[tuple[int, str]],
    *,
    back_callback: str = "back_to_main",
    include_back: bool = True,
) -> InlineKeyboardMarkup:
    keyboard_rows: list[list[InlineKeyboardButton]] = []

    for item_id, title in items:
        keyboard_rows.append(
            [InlineKeyboardButton(text=_truncate_title(title), callback_data=f"item_{item_id}")]
        )

    if include_back:
        keyboard_rows.append([InlineKeyboardButton(text="Back", callback_data=back_callback)])

    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def category_keyboard(
    items: list[tuple[int, str]],
    *,
    prev_callback: str | None = None,
    next_callback: str | None = None,
    back_callback: str = "back_to_main",
) -> InlineKeyboardMarkup:
    keyboard_rows = item_keyboard(items, include_back=False).inline_keyboard

    nav_row: list[InlineKeyboardButton] = []
    if prev_callback:
        nav_row.append(InlineKeyboardButton(text="Prev", callback_data=prev_callback))
    if next_callback:
        nav_row.append(InlineKeyboardButton(text="Next", callback_data=next_callback))
    if nav_row:
        keyboard_rows.append(nav_row)

    keyboard_rows.append([InlineKeyboardButton(text="Back", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=keyboard_rows)


def required_channels_keyboard(
    channels: list[str],
    *,
    recheck_callback: str = "check_membership",
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for channel in channels:
        url = _channel_join_url(channel)
        if not url:
            continue
        rows.append(
            [InlineKeyboardButton(text=f"Join {_channel_display_name(channel)}", url=url)]
        )

    rows.append([InlineKeyboardButton(text="I Joined", callback_data=recheck_callback)])
    rows.append([InlineKeyboardButton(text="Back", callback_data="back_to_main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
