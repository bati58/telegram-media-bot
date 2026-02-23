import asyncio
import logging

from aiogram import Bot, Dispatcher

from config import BACKUP_INTERVAL_MINUTES, BOT_TOKEN, ENABLE_PERIODIC_BACKUP
from database import init_db
from handlers import admin, search, start, user
from middlewares.error_logging import StructuredErrorMiddleware
from middlewares.rate_limit import RateLimitMiddleware
from utils import run_periodic_backup_loop

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bot")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
dp.update.outer_middleware(RateLimitMiddleware())
dp.update.outer_middleware(StructuredErrorMiddleware())

init_db()

dp.include_router(start.router)
dp.include_router(admin.router)
dp.include_router(user.router)
dp.include_router(search.router)


async def main() -> None:
    backup_task: asyncio.Task | None = None

    if ENABLE_PERIODIC_BACKUP:
        backup_task = asyncio.create_task(
            run_periodic_backup_loop(BACKUP_INTERVAL_MINUTES),
            name="periodic-backup",
        )
        logger.info("Periodic backups enabled (interval=%s min)", BACKUP_INTERVAL_MINUTES)
    else:
        logger.info("Periodic backups disabled")

    try:
        await dp.start_polling(bot)
    finally:
        if backup_task:
            backup_task.cancel()
            await asyncio.gather(backup_task, return_exceptions=True)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
