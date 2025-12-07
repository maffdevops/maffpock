from __future__ import annotations

from typing import Optional

from aiogram import Router, F
from aiogram.filters import CommandStart
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from ..models import base as db
from ..models.user import User
from .main_menu import send_main_menu, send_language_choice

router = Router()


async def _get_or_create_user(tg_id: int, username: Optional[str]) -> User:
    """
    Создаём юзера, если его ещё нет.
    ВАЖНО: language по умолчанию None — чтобы сначала показывать выбор языка.
    """
    if db.async_session_maker is None:
        raise RuntimeError("DB session maker is not initialized")

    async with db.async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user: Optional[User] = result.scalar_one_or_none()

        if user is None:
            user = User(
                telegram_id=tg_id,
                username=username,
                language=None,        # язык не выбран
                is_subscribed=False,
                is_registered=False,
                has_basic_access=False,
                is_vip=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # обновим username, если поменялся
            if username and user.username != username:
                user.username = username
                await session.commit()

        return user


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """
    /start:
    - создаём/находим юзера
    - если язык ещё не выбран → окно выбора языка (EN-картинка)
    - если язык уже есть → сразу главное меню
    """
    from_user = message.from_user
    if from_user is None:
        return

    user = await _get_or_create_user(
        tg_id=from_user.id,
        username=from_user.username,
    )

    # удаляем /start
    try:
        await message.delete()
    except Exception:
        pass

    if not user.language:
        # язык ещё не выбран → используем EN-картинку
        await send_language_choice(message)
    else:
        await send_main_menu(message, user.language)


@router.callback_query(F.data.startswith("set_lang:"))
async def handle_set_language(callback: CallbackQuery) -> None:
    """
    Выбор языка по кнопке:
    callback.data = "set_lang:ru" / "set_lang:en" / "set_lang:es" / "set_lang:hi"
    """
    from_user = callback.from_user
    if from_user is None:
        await callback.answer()
        return

    if not callback.data:
        await callback.answer()
        return

    _, lang_code_raw = callback.data.split(":", 1)
    lang_code = lang_code_raw.strip().lower()

    if lang_code not in ("ru", "en", "es", "hi"):
        lang_code = "en"

    if db.async_session_maker is None:
        await callback.answer("Ошибка БД", show_alert=True)
        return

    async with db.async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == from_user.id)
        )
        user: Optional[User] = result.scalar_one_or_none()

        if user is None:
            # на всякий случай, если по какой-то причине нет записи
            user = User(
                telegram_id=from_user.id,
                username=from_user.username,
                language=lang_code,
                is_subscribed=False,
                is_registered=False,
                has_basic_access=False,
                is_vip=False,
            )
            session.add(user)
        else:
            user.language = lang_code

        await session.commit()

    await callback.answer()

    # удаляем окно выбора языка
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

        # показываем главное меню уже на выбранном языке
        await send_main_menu(callback.message, lang_code)