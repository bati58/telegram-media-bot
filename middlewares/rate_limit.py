import logging
from collections import defaultdict, deque
from time import monotonic
from typing import Any, Awaitable, Callable, Deque, Dict, Tuple

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from config import ADMIN_IDS, MODERATOR_IDS, RATE_LIMIT_EXEMPT_STAFF, RATE_LIMIT_MAX_EVENTS, RATE_LIMIT_WINDOW_SECONDS

logger = logging.getLogger("bot.rate_limit")


class RateLimitMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        window_seconds: int = RATE_LIMIT_WINDOW_SECONDS,
        max_events: int = RATE_LIMIT_MAX_EVENTS,
        exempt_staff: bool = RATE_LIMIT_EXEMPT_STAFF,
    ) -> None:
        self.window_seconds = max(1, int(window_seconds))
        self.max_events = max(1, int(max_events))
        self.exempt_staff = exempt_staff
        self._events: Dict[Tuple[int, str], Deque[float]] = defaultdict(deque)
        self._last_notice_at: Dict[Tuple[int, str], float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id, event_type = self._extract_user_and_type(event)
        if user_id is None:
            return await handler(event, data)

        if self.exempt_staff and user_id in ADMIN_IDS.union(MODERATOR_IDS):
            return await handler(event, data)

        key = (user_id, event_type)
        now = monotonic()
        event_window = self._events[key]
        while event_window and (now - event_window[0]) > self.window_seconds:
            event_window.popleft()

        if len(event_window) >= self.max_events:
            await self._notify_rate_limited(event, key, now)
            return None

        event_window.append(now)
        return await handler(event, data)

    @staticmethod
    def _extract_user_and_type(event: TelegramObject) -> tuple[int | None, str]:
        if isinstance(event, Message):
            return (event.from_user.id if event.from_user else None, "message")
        if isinstance(event, CallbackQuery):
            return (event.from_user.id if event.from_user else None, "callback")
        return (None, "other")

    async def _notify_rate_limited(self, event: TelegramObject, key: tuple[int, str], now: float) -> None:
        last_notice_at = self._last_notice_at.get(key, 0.0)
        if now - last_notice_at < 2.0:
            return
        self._last_notice_at[key] = now

        logger.warning("Rate limit exceeded for user_id=%s event_type=%s", key[0], key[1])

        try:
            if isinstance(event, CallbackQuery):
                await event.answer("Too many requests. Please wait a moment.", show_alert=True)
                return
            if isinstance(event, Message):
                await event.answer("You are sending requests too fast. Please slow down.")
        except Exception:
            logger.exception("Failed to send rate limit notification")
