import json
import logging
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger("bot.middleware")


def _build_context(event: TelegramObject, data: Dict[str, Any]) -> dict[str, Any]:
    update = data.get("event_update")
    context: dict[str, Any] = {
        "event_type": type(event).__name__,
        "update_id": getattr(update, "update_id", None),
        "user_id": None,
        "chat_id": None,
    }

    if isinstance(event, Message):
        context["user_id"] = event.from_user.id if event.from_user else None
        context["chat_id"] = event.chat.id if event.chat else None
    elif isinstance(event, CallbackQuery):
        context["user_id"] = event.from_user.id if event.from_user else None
        context["chat_id"] = event.message.chat.id if event.message and event.message.chat else None

    return context


async def _safe_notify_user(event: TelegramObject) -> None:
    try:
        if isinstance(event, CallbackQuery):
            try:
                await event.answer("Something went wrong. Please try again.", show_alert=True)
            except TelegramAPIError:
                pass

            if event.message:
                await event.message.answer("Unexpected error. Please try again.")
            return

        if isinstance(event, Message):
            await event.answer("Unexpected error. Please try again.")
    except Exception:
        logger.exception("Failed to notify user after handler exception")


class StructuredErrorMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        context = _build_context(event, data)
        started = perf_counter()
        logger.info(json.dumps({"event": "update_received", **context}, ensure_ascii=True))

        try:
            result = await handler(event, data)
            duration_ms = round((perf_counter() - started) * 1000, 2)
            logger.info(
                json.dumps(
                    {"event": "update_handled", "duration_ms": duration_ms, **context},
                    ensure_ascii=True,
                )
            )
            return result
        except Exception:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            logger.exception(
                json.dumps(
                    {"event": "handler_exception", "duration_ms": duration_ms, **context},
                    ensure_ascii=True,
                )
            )
            await _safe_notify_user(event)
            return None
