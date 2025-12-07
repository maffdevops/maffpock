from __future__ import annotations

from sqlalchemy import Column, Integer, String, Boolean, Numeric

from .base import Base


class Settings(Base):
    """
    Глобальные настройки бота/админки.
    Предполагаем одну запись с id = 1.
    """

    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)

    # ---- Ссылки ----

    # Реферальная ссылка регистрации у брокера
    ref_link = Column(String, nullable=True)

    # Ссылка на страницу депозита/пополнения
    deposit_link = Column(String, nullable=True)

    # ID канала (например, -1001234567890)
    channel_id = Column(String, nullable=True)

    # Публичная ссылка на канал (t.me/...)
    channel_url = Column(String, nullable=True)

    # Ссылка на поддержку (чат/бот)
    support_url = Column(String, nullable=True)

    # ---- Настройка шагов доступа ----

    # Проверять ли подписку на канал
    require_subscription = Column(Boolean, nullable=False, default=True)

    # Проверять ли наличие депозита
    require_deposit = Column(Boolean, nullable=False, default=True)

    # Порог депозита (USD) для прохождения проверки (обычный доступ)
    deposit_required_amount = Column(Numeric(12, 2), nullable=False, default=0)

    # Порог VIP (USD) по сумме депозитов
    vip_threshold_amount = Column(Numeric(12, 2), nullable=False, default=0)

    # ---- Постбэки в группу ----

    # ID/username чата для постбэков (группа/канал)
    postbacks_chat_id = Column(String, nullable=True)

    # Какие события слать в группу
    send_postbacks_registration = Column(Boolean, nullable=False, default=False)
    send_postbacks_deposit = Column(Boolean, nullable=False, default=False)
    send_postbacks_withdraw = Column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return (
            f"<Settings id={self.id} "
            f"ref_link={self.ref_link} "
            f"deposit_link={self.deposit_link} "
            f"channel_id={self.channel_id} "
            f"channel_url={self.channel_url} "
            f"support_url={self.support_url} "
            f"require_subscription={self.require_subscription} "
            f"require_deposit={self.require_deposit} "
            f"deposit_required_amount={self.deposit_required_amount} "
            f"vip_threshold_amount={self.vip_threshold_amount} "
            f"postbacks_chat_id={self.postbacks_chat_id} "
            f"send_postbacks_registration={self.send_postbacks_registration} "
            f"send_postbacks_deposit={self.send_postbacks_deposit} "
            f"send_postbacks_withdraw={self.send_postbacks_withdraw}>"
        )