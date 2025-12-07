import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import load_config
from .models.base import setup_db, init_db
from .handlers.language import router as language_router
from .handlers.main_menu import router as main_menu_router
from .handlers.admin import router as admin_router


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )

    config = load_config()

    # Инициализируем БД
    setup_db(config.db.url)
    await init_db()

    # Создаём бота
    bot = Bot(
        token=config.bot.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )

    dp = Dispatcher()

    # Порядок: язык/меню для обычных юзеров, админка
    dp.include_router(language_router)
    dp.include_router(main_menu_router)
    dp.include_router(admin_router)

    logging.info("Starting bot polling...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())