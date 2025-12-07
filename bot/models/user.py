from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, String, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class User(Base):
    """
    Модель пользователя бота.

    Поля:
    - telegram_id: Telegram ID пользователя
    - username: @username пользователя (если есть)
    - language: выбранный язык ("ru", "en", "es", "hi") или None, если ещё не выбрал

    Логика шагов:
    - is_subscribed: факт подписки на канал
    - is_registered: факт регистрации у брокера
    - has_basic_access: открыт ли обычный доступ к мини-аппам
    - is_vip: есть ли VIP-доступ

    Интеграция с брокером:
    - trader_id: ID пользователя на стороне брокера (из постбэка Pocket Option)
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    telegram_id: Mapped[int] = mapped_column(
        BigInteger,
        unique=True,
        nullable=False,
        index=True,
    )

    username: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # язык не задаём по умолчанию — сначала показываем окно выбора языка
    language: Mapped[Optional[str]] = mapped_column(
        String(8),
        nullable=True,
    )

    # --- логика шагов ---

    is_subscribed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_registered: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    has_basic_access: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_vip: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    # --- брокер ---

    trader_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    # --- таймстемпы ---

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    def __repr__(self) -> str:
        return (
            f"<User id={self.id} tg={self.telegram_id} "
            f"user={self.username!r} lang={self.language!r} "
            f"sub={self.is_subscribed} reg={self.is_registered} "
            f"access={self.has_basic_access} vip={self.is_vip} "
            f"trader_id={self.trader_id!r}>"
        )