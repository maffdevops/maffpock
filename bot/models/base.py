from __future__ import annotations

from typing import Optional

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import declarative_base

# Базовый класс для всех моделей
Base = declarative_base()

# Глобальные объекты для engine и фабрики сессий
engine: Optional[AsyncEngine] = None
async_session_maker: Optional[async_sessionmaker[AsyncSession]] = None


def setup_db(database_url: str) -> None:
    """
    Инициализация async engine и фабрики сессий.
    Вызывается один раз при старте приложения (в main.py).
    """
    global engine, async_session_maker

    engine = create_async_engine(database_url, echo=False, future=True)
    async_session_maker = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )


async def init_db() -> None:
    """
    Создание таблиц в БД (если их ещё нет).
    Вызывается один раз при старте (после setup_db).
    """
    if engine is None:
        raise RuntimeError("DB engine is not initialized. Call setup_db() first.")

    # Импортируем модели, чтобы они зарегистрировались в Base.metadata
    # Важно: файлы deposit.py и settings.py уже есть как заглушки – импорт пройдёт нормально.
    from . import user, deposit, settings  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)