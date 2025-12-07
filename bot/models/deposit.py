from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
)

from .base import Base


class Deposit(Base):
    """
    Запись о депозите пользователя.
    Потом сюда будем записывать депозиты из постбэков брокера.
    """

    __tablename__ = "deposits"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    amount = Column(Numeric(12, 2), nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:
        return f"<Deposit id={self.id} user_id={self.user_id} amount={self.amount}>"