from __future__ import annotations

import os
from typing import Optional

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from sqlalchemy import select, func

from ..models import base as db
from ..models.user import User
from ..models.deposit import Deposit
from ..models.settings import Settings
from .main_menu import (
    run_access_flow_for_user,
    notify_basic_access_limited,
    notify_vip_access_limited,
    notify_vip_granted,
)

router = Router()


# ===== ADMIN ACCESS =====


def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    result: set[int] = set()
    for part in raw.replace(" ", "").split(","):
        if not part:
            continue
        try:
            result.add(int(part))
        except ValueError:
            continue
    return result


ADMIN_IDS: set[int] = _load_admin_ids()


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ===== STATES =====


class AdminLinksState(StatesGroup):
    waiting_for_ref = State()
    waiting_for_deposit = State()
    waiting_for_channel_id = State()
    waiting_for_channel_url = State()
    waiting_for_support = State()


class AdminStepsState(StatesGroup):
    waiting_for_deposit_amount = State()
    waiting_for_vip_amount = State()


class AdminPostbacksState(StatesGroup):
    waiting_for_chat_id = State()


# ===== HELPERS: DB & STATS =====


async def _get_or_create_settings() -> Settings:
    if db.async_session_maker is None:
        raise RuntimeError("DB session maker is not initialized")

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings


async def _get_stats():
    if db.async_session_maker is None:
        return 0, 0, 0, 0.0

    async with db.async_session_maker() as session:
        users_count = await session.scalar(select(func.count()).select_from(User)) or 0
        deposits_count = await session.scalar(
            select(func.count()).select_from(Deposit)
        ) or 0
        total_deposit_sum = await session.scalar(
            select(func.coalesce(func.sum(Deposit.amount), 0))
        )
        registrations_count = await session.scalar(
            select(func.count()).select_from(User).where(User.is_registered == True)
        ) or 0  # noqa: E712

    return (
        users_count,
        deposits_count,
        registrations_count,
        float(total_deposit_sum or 0.0),
    )


# ===== HELPERS: UI =====


async def _send_admin_menu(bot, chat_id: int) -> None:
    users_count, deposits_count, registrations_count, total_deposit = await _get_stats()

    text = (
        "<b>АДМИНКА</b>\n\n"
        f"👥 Пользователей: <b>{users_count}</b>\n"
        f"💳 Депозитов: <b>{deposits_count}</b>\n"
        f"✅ Регистраций: <b>{registrations_count}</b>\n"
        f"💰 Сумма депозитов: <b>{total_deposit:.2f}</b>\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="👥 Пользователи", callback_data="admin:users")
    kb.button(text="🔗 URL постбэков", callback_data="admin:postbacks")
    kb.button(text="⚙️ Настройки", callback_data="admin:settings")
    kb.button(text="🔗 Ссылки", callback_data="admin:links")
    kb.button(text="📨 Рассылка", callback_data="admin:broadcast")
    kb.adjust(1, 1, 2, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_links_window(bot, chat_id: int) -> None:
    settings = await _get_or_create_settings()

    def norm(val: Optional[str]) -> str:
        return val if val else "— не задано —"

    text = (
        "🔗 <b>Ссылки</b>\n\n"
        f"Реф. ссылка:\n<code>{norm(settings.ref_link)}</code>\n\n"
        f"Ссылка на депозит:\n<code>{norm(settings.deposit_link)}</code>\n\n"
        f"ID канала:\n<code>{norm(settings.channel_id)}</code>\n\n"
        f"Ссылка на канал:\n<code>{norm(settings.channel_url)}</code>\n\n"
        f"Ссылка поддержки:\n<code>{norm(settings.support_url)}</code>\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✏️ Реф. ссылка", callback_data="admin:links:edit:ref")
    kb.button(text="✏️ Ссылка на депозит", callback_data="admin:links:edit:deposit")
    kb.button(text="✏️ ID канала", callback_data="admin:links:edit:channel_id")
    kb.button(text="✏️ Ссылка на канал", callback_data="admin:links:edit:channel_url")
    kb.button(text="✏️ Ссылка поддержки", callback_data="admin:links:edit:support")
    kb.button(text="⬅️ В админ-меню", callback_data="admin:menu")
    kb.adjust(1, 1, 1, 1, 1, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_users_list(bot, chat_id: int, page: int = 1, page_size: int = 5) -> None:
    if page < 1:
        page = 1

    if db.async_session_maker is None:
        await bot.send_message(chat_id, "DB not initialized")
        return

    async with db.async_session_maker() as session:
        total_users = await session.scalar(
            select(func.count()).select_from(User)
        ) or 0

        total_pages = max((total_users + page_size - 1) // page_size, 1)
        if page > total_pages:
            page = total_pages

        offset = (page - 1) * page_size
        result = await session.execute(
            select(User)
            .order_by(User.id)
            .offset(offset)
            .limit(page_size)
        )
        users = result.scalars().all()

    text = (
        "👥 <b>Пользователи</b>\n\n"
        f"Всего: <b>{total_users}</b>\n"
        f"Страница: <b>{page}</b> / <b>{total_pages}</b>\n"
    )

    kb = InlineKeyboardBuilder()

    kb.button(text="🔍 Поиск", callback_data="admin:users:search")

    for u in users:
        label = f"#{u.id} | tg:{u.telegram_id}"
        kb.button(
            text=label,
            callback_data=f"admin:user:{u.id}:view",
        )

    prev_page = max(page - 1, 1)
    next_page = min(page + 1, total_pages)
    kb.button(text="⬅️", callback_data=f"admin:users:page:{prev_page}")
    kb.button(text=f"Стр {page}", callback_data="admin:users:noop")
    kb.button(text="➡️", callback_data=f"admin:users:page:{next_page}")
    kb.button(text="⬅️ В админ-меню", callback_data="admin:menu")

    rows = [1]
    rows += [1] * len(users)
    rows += [3, 1]
    kb.adjust(*rows)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_user_card(bot, chat_id: int, user_id: int, page: int = 1) -> None:
    if db.async_session_maker is None:
        await bot.send_message(chat_id, "DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user: Optional[User] = result.scalar_one_or_none()
        if user is None:
            await bot.send_message(chat_id, "Пользователь не найден.")
            return

        total_deposit = await session.scalar(
            select(func.coalesce(func.sum(Deposit.amount), 0)).where(
                Deposit.user_id == user.id
            )
        ) or 0.0

    is_registered_display = bool(user.is_registered or user.trader_id)
    has_deposit = total_deposit > 0

    text = (
        "👤 <b>Пользователь</b>\n\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: <b>{user.username or '—'}</b>\n"
        f"Trader ID: <b>{user.trader_id or '—'}</b>\n"
        f"Язык: <b>{user.language or '—'}</b>\n\n"
        f"📡 Подписка: <b>{'✅' if user.is_subscribed else '❌'}</b>\n"
        f"📝 Регистрация: <b>{'✅' if is_registered_display else '❌'}</b>\n"
        f"💰 Депозит: <b>{'✅' if has_deposit else '❌'}</b> "
        f"(сумма: <b>{float(total_deposit):.2f}$</b>)\n"
        f"🔓 Доступ: <b>{'✅' if user.has_basic_access else '❌'}</b>\n"
        f"👑 VIP: <b>{'✅' if user.is_vip else '❌'}</b>\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="✅ Выдать регу", callback_data=f"admin:user:{user.id}:give_reg")
    kb.button(text="💰 Выдать деп", callback_data=f"admin:user:{user.id}:give_dep")
    kb.button(text="👑 Выдать VIP", callback_data=f"admin:user:{user.id}:give_vip")
    kb.button(
        text="🚫 Забрать доступ",
        callback_data=f"admin:user:{user.id}:revoke_access",
    )
    kb.button(
        text="💎 Забрать VIP доступ",
        callback_data=f"admin:user:{user.id}:revoke_vip",
    )
    kb.button(text="🗑 Удалить юзера", callback_data=f"admin:user:{user.id}:delete")
    kb.button(
        text="⬅️ Назад к пользователям",
        callback_data=f"admin:users:page:{page}",
    )
    kb.adjust(2, 2, 2, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_settings_window(bot, chat_id: int) -> None:
    settings = await _get_or_create_settings()

    def yn(val: bool) -> str:
        return "✅ Да" if val else "❌ Нет"

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        "🔹 <b>Проверки шагов</b>\n"
        f"• Проверять подписку: <b>{yn(settings.require_subscription)}</b>\n"
        f"• Проверять депозит: <b>{yn(settings.require_deposit)}</b>\n"
        f"• Порог депозита: <b>{float(settings.deposit_required_amount or 0):.2f}$</b>\n"
        f"• Порог VIP: <b>{float(settings.vip_threshold_amount or 0):.2f}$</b>\n\n"
        "🔹 <b>Постбэки в группу</b>\n"
        f"• Чат для постбэков: <code>{settings.postbacks_chat_id or '— не задан —'}</code>\n"
        f"• Регистрация: <b>{yn(settings.send_postbacks_registration)}</b>\n"
        f"• Депозит: <b>{yn(settings.send_postbacks_deposit)}</b>\n"
        f"• Вывод: <b>{yn(settings.send_postbacks_withdraw)}</b>\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="⚙️ Настройка шагов", callback_data="admin:settings:steps")
    kb.button(
        text="📩 Постбэки в группу",
        callback_data="admin:settings:postbacks_group",
    )
    kb.button(text="⬅️ В админ-меню", callback_data="admin:menu")
    kb.adjust(1, 1, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_steps_window(bot, chat_id: int) -> None:
    settings = await _get_or_create_settings()

    def yn(val: bool) -> str:
        return "✅ Да" if val else "❌ Нет"

    text = (
        "⚙️ <b>Настройка шагов доступа</b>\n\n"
        f"• Проверять подписку: <b>{yn(settings.require_subscription)}</b>\n"
        f"• Проверять депозит: <b>{yn(settings.require_deposit)}</b>\n"
        f"• Порог депозита: <b>{float(settings.deposit_required_amount or 0):.2f}$</b>\n"
        f"• Порог VIP: <b>{float(settings.vip_threshold_amount or 0):.2f}$</b>\n\n"
        "Регистрация считается обязательным шагом по умолчанию.\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="🔁 Переключить подписку",
        callback_data="admin:steps:toggle:subscription",
    )
    kb.button(
        text="🔁 Переключить депозит",
        callback_data="admin:steps:toggle:deposit",
    )
    kb.button(
        text="✏️ Порог депозита", callback_data="admin:steps:edit:deposit_amount"
    )
    kb.button(text="✏️ Порог VIP", callback_data="admin:steps:edit:vip_amount")
    kb.button(
        text="⬅️ Назад к настройкам",
        callback_data="admin:settings",
    )
    kb.adjust(1, 1, 1, 1, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


async def _send_postbacks_group_window(bot, chat_id: int) -> None:
    settings = await _get_or_create_settings()

    def yn(val: bool) -> str:
        return "✅ Вкл" if val else "❌ Выкл"

    text = (
        "📩 <b>Постбэки в группу</b>\n\n"
        f"Чат для постбэков:\n<code>{settings.postbacks_chat_id or '— не задан —'}</code>\n\n"
        "Какие события слать в группу:\n"
        f"• Регистрация: <b>{yn(settings.send_postbacks_registration)}</b>\n"
        f"• Депозит: <b>{yn(settings.send_postbacks_deposit)}</b>\n"
        f"• Вывод: <b>{yn(settings.send_postbacks_withdraw)}</b>\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(
        text="✏️ Чат постбэков",
        callback_data="admin:postbacks_group:edit:chat",
    )
    kb.button(
        text="🔁 Регистрация",
        callback_data="admin:postbacks_group:toggle:registration",
    )
    kb.button(
        text="🔁 Депозит",
        callback_data="admin:postbacks_group:toggle:deposit",
    )
    kb.button(
        text="🔁 Вывод",
        callback_data="admin:postbacks_group:toggle:withdraw",
    )
    kb.button(
        text="⬅️ Назад к настройкам",
        callback_data="admin:settings",
    )
    kb.adjust(1, 1, 1, 1, 1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


def _get_postback_base_url() -> str:
    """
    Базовый URL для постбэков берём из POSTBACK_BASE_URL,
    чтобы в админке не руками писать IP+порт.
    """
    base = os.getenv("POSTBACK_BASE_URL", "").strip()
    if not base:
        base = "http://45.90.218.187:8000"
    base = base.rstrip("/")
    return base


async def _send_postbacks_urls_window(bot, chat_id: int) -> None:
    base = _get_postback_base_url()

    reg_url = (
        base
        + "/postback/registration?trader_id={trader_id}&click_id={click_id}"
    )
    ftd_url = (
        base
        + "/postback/first_deposit?"
        "trader_id={trader_id}&click_id={click_id}&sumdep={sumdep}"
    )
    redep_url = (
        base
        + "/postback/redeposit?"
        "trader_id={trader_id}&click_id={click_id}&sumdep={sumdep}"
    )
    wdr_url = (
        base
        + "/postback/withdraw?"
        "trader_id={trader_id}&click_id={click_id}&wdr_sum={wdr_sum}"
    )

    text = (
        "🔗 <b>URL постбэков для партнёрки</b>\n\n"
        f"Базовый адрес: <code>{base}</code>\n\n"
        "<b>Регистрация:</b>\n"
        f"<code>{reg_url}</code>\n\n"
        "<b>Первый депозит (FTD):</b>\n"
        f"<code>{ftd_url}</code>\n\n"
        "<b>Повторный депозит:</b>\n"
        f"<code>{redep_url}</code>\n\n"
        "<b>Вывод средств:</b>\n"
        f"<code>{wdr_url}</code>\n\n"
        "📌 <b>Макросы</b>\n"
        "• {trader_id} — ID трейдера у брокера\n"
        "• {click_id} — Telegram ID (tg id)\n"
        "• {sumdep} — сумма депозита\n"
        "• {wdr_sum} — сумма вывода\n"
    )

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ В админ-меню", callback_data="admin:menu")
    kb.adjust(1)

    await bot.send_message(chat_id, text, reply_markup=kb.as_markup())


# ===== HANDLERS: /admin =====


@router.message(Command("admin"))
async def admin_entry(message: Message) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа.")
        return

    chat_id = message.chat.id
    try:
        await message.delete()
    except Exception:
        pass

    await _send_admin_menu(message.bot, chat_id)


@router.callback_query(F.data == "admin:menu")
async def admin_menu_from_callback(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    await _send_admin_menu(callback.message.bot, chat_id)


# ===== HANDLERS: ССЫЛКИ =====


@router.callback_query(F.data == "admin:links")
async def admin_links(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    chat_id = callback.message.chat.id if callback.message else callback.from_user.id

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    await _send_links_window(callback.message.bot, chat_id)


@router.callback_query(F.data.startswith("admin:links:edit:"))
async def admin_links_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    _, _, _, field = data.split(":", 3)

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    if field == "ref":
        await state.set_state(AdminLinksState.waiting_for_ref)
        prompt = "✏️ Отправьте новую реферальную ссылку:"
    elif field == "deposit":
        await state.set_state(AdminLinksState.waiting_for_deposit)
        prompt = "✏️ Отправьте новую ссылку на депозит:"
    elif field == "channel_id":
        await state.set_state(AdminLinksState.waiting_for_channel_id)
        prompt = "✏️ Отправьте новый ID канала (например, -1001234567890):"
    elif field == "channel_url":
        await state.set_state(AdminLinksState.waiting_for_channel_url)
        prompt = "✏️ Отправьте новую ссылку на канал (t.me/...):"
    elif field == "support":
        await state.set_state(AdminLinksState.waiting_for_support)
        prompt = "✏️ Отправьте новую ссылку поддержки:"
    else:
        await callback.answer("Неизвестное поле", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад к ссылкам", callback_data="admin:links")

    chat_id = callback.from_user.id
    await callback.message.bot.send_message(
        chat_id, prompt, reply_markup=kb.as_markup()
    )


@router.message(AdminLinksState.waiting_for_ref)
async def admin_links_set_ref(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.ref_link = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_links_window(message.bot, message.chat.id)


@router.message(AdminLinksState.waiting_for_deposit)
async def admin_links_set_deposit(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.deposit_link = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_links_window(message.bot, message.chat.id)


@router.message(AdminLinksState.waiting_for_channel_id)
async def admin_links_set_channel_id(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.channel_id = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_links_window(message.bot, message.chat.id)


@router.message(AdminLinksState.waiting_for_channel_url)
async def admin_links_set_channel_url(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.channel_url = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_links_window(message.bot, message.chat.id)


@router.message(AdminLinksState.waiting_for_support)
async def admin_links_set_support(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.support_url = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_links_window(message.bot, message.chat.id)


# ===== HANDЛERS: НАСТРОЙКИ =====


@router.callback_query(F.data == "admin:settings")
async def admin_settings(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_settings_window(callback.message.bot, chat_id)


@router.callback_query(F.data == "admin:settings:steps")
async def admin_settings_steps(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_steps_window(callback.message.bot, chat_id)


@router.callback_query(F.data.startswith("admin:steps:toggle:"))
async def admin_steps_toggle(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    _, _, _, field = data.split(":", 3)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)

        if field == "subscription":
            settings.require_subscription = not bool(settings.require_subscription)
        elif field == "deposit":
            settings.require_deposit = not bool(settings.require_deposit)
        else:
            await callback.answer("Неизвестное поле", show_alert=True)
            return

        await session.commit()

    await callback.answer("Обновлено")
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _send_steps_window(callback.message.bot, callback.message.chat.id)


@router.callback_query(F.data.startswith("admin:steps:edit:"))
async def admin_steps_edit(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    _, _, _, field = data.split(":", 3)

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    if field == "deposit_amount":
        await state.set_state(AdminStepsState.waiting_for_deposit_amount)
        prompt = "✏️ Отправьте новый порог депозита в $ (например, 100 или 250.50):"
    elif field == "vip_amount":
        await state.set_state(AdminStepsState.waiting_for_vip_amount)
        prompt = "✏️ Отправьте новый порог VIP в $ (например, 1000 или 1500.00):"
    else:
        await callback.answer("Неизвестное поле", show_alert=True)
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="⬅️ Назад к шагам", callback_data="admin:settings:steps")

    chat_id = callback.from_user.id
    await callback.message.bot.send_message(
        chat_id, prompt, reply_markup=kb.as_markup()
    )


@router.message(AdminStepsState.waiting_for_deposit_amount)
async def admin_steps_set_deposit_amount(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 100 или 250.50")
        return

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.deposit_required_amount = value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_steps_window(message.bot, message.chat.id)


@router.message(AdminStepsState.waiting_for_vip_amount)
async def admin_steps_set_vip_amount(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    raw = (message.text or "").strip().replace(",", ".")
    try:
        value = float(raw)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("Нужно положительное число, например 1000 или 1500.00")
        return

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.vip_threshold_amount = value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_steps_window(message.bot, message.chat.id)


# ===== HANDLERS: ПОСТБЭКИ В ГРУППУ =====


@router.callback_query(F.data == "admin:settings:postbacks_group")
async def admin_postbacks_group(callback: CallbackQuery, state: FSMContext) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.clear()
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_postbacks_group_window(callback.message.bot, chat_id)


@router.callback_query(F.data.startswith("admin:postbacks_group:toggle:"))
async def admin_postbacks_group_toggle(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    _, _, _, field = data.split(":", 3)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)

        if field == "registration":
            settings.send_postbacks_registration = not bool(
                settings.send_postbacks_registration
            )
        elif field == "deposit":
            settings.send_postbacks_deposit = not bool(
                settings.send_postbacks_deposit
            )
        elif field == "withdraw":
            settings.send_postbacks_withdraw = not bool(
                settings.send_postbacks_withdraw
            )
        else:
            await callback.answer("Неизвестное поле", show_alert=True)
            return

        await session.commit()

    await callback.answer("Обновлено")
    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await _send_postbacks_group_window(callback.message.bot, callback.message.chat.id)


@router.callback_query(F.data == "admin:postbacks_group:edit:chat")
async def admin_postbacks_group_edit_chat(
    callback: CallbackQuery, state: FSMContext
) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    await state.set_state(AdminPostbacksState.waiting_for_chat_id)

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    kb = InlineKeyboardBuilder()
    kb.button(
        text="⬅️ Назад к постбэкам",
        callback_data="admin:settings:postbacks_group",
    )

    chat_id = callback.from_user.id
    await callback.message.bot.send_message(
        chat_id,
        "✏️ Отправьте ID или @username чата/группы для постбэков:",
        reply_markup=kb.as_markup(),
    )


@router.message(AdminPostbacksState.waiting_for_chat_id)
async def admin_postbacks_group_set_chat(message: Message, state: FSMContext) -> None:
    if message.from_user is None or not _is_admin(message.from_user.id):
        return

    new_value = (message.text or "").strip()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
        settings.postbacks_chat_id = new_value
        await session.commit()

    await state.clear()
    try:
        await message.delete()
    except Exception:
        pass

    await _send_postbacks_group_window(message.bot, message.chat.id)


# ===== HANDЛЕР: ОКНО URL ПОСТБЭКОВ =====


@router.callback_query(F.data == "admin:postbacks")
async def admin_postbacks(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_postbacks_urls_window(callback.message.bot, chat_id)


# ===== HANDЛЕРЫ: ПОЛЬЗОВАТЕЛИ =====


@router.callback_query(F.data == "admin:users")
async def admin_users(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_users_list(callback.message.bot, chat_id, page=1)


@router.callback_query(F.data.startswith("admin:users:page:"))
async def admin_users_page(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    try:
        _, _, _, page_str = data.split(":")
        page = int(page_str)
    except Exception:
        page = 1

    if callback.message:
        try:
            await callback.message.delete()
        except Exception:
            pass

    chat_id = callback.message.chat.id if callback.message else callback.from_user.id
    await _send_users_list(callback.message.bot, chat_id, page=page)


@router.callback_query(F.data == "admin:users:search")
async def admin_users_search(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Поиск пока не реализован", show_alert=True)


@router.callback_query(F.data.startswith("admin:user:"))
async def admin_user_actions(callback: CallbackQuery) -> None:
    """
    admin:user:<id>:action

    action = view | give_reg | give_dep | give_vip | revoke_access | revoke_vip | delete
    """
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    parts = data.split(":")
    if len(parts) < 4:
        await callback.answer("Некорректные данные", show_alert=True)
        return

    _, _, user_id_str, action = parts
    try:
        user_id = int(user_id_str)
    except Exception:
        await callback.answer("Некорректный ID", show_alert=True)
        return

    admin_chat_id = callback.message.chat.id if callback.message else callback.from_user.id

    # просто посмотреть карточку
    if action == "view":
        if callback.message:
            try:
                await callback.message.delete()
            except Exception:
                pass
        await _send_user_card(callback.message.bot, admin_chat_id, user_id)
        return

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user: Optional[User] = result.scalar_one_or_none()
        if user is None:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        settings = await _get_or_create_settings()

        # --- ВЫДАТЬ РЕГУ ---
        if action == "give_reg":
            user.is_registered = True
            await session.commit()

            await callback.answer("Регистрация выдана", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await run_access_flow_for_user(callback.message.bot, user.telegram_id)
            await _send_user_card(callback.message.bot, admin_chat_id, user_id)
            return

        # --- ВЫДАТЬ ДЕП ---
        elif action == "give_dep":
            amount = float(settings.deposit_required_amount or 0)
            if amount <= 0:
                amount = 1.0

            dep = Deposit(user_id=user.id, amount=amount)
            session.add(dep)
            await session.commit()

            await callback.answer("Депозит выдан", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await run_access_flow_for_user(callback.message.bot, user.telegram_id)
            await _send_user_card(callback.message.bot, admin_chat_id, user_id)
            return

        # --- ВЫДАТЬ VIP ---
        elif action == "give_vip":
            user.is_vip = True
            await session.commit()

            await callback.answer("VIP выдан", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await notify_vip_granted(callback.message.bot, user.telegram_id)
            await _send_user_card(callback.message.bot, admin_chat_id, user_id)
            return

        # --- ЗАБРАТЬ БАЗОВЫЙ ДОСТУП ---
        elif action == "revoke_access":
            user.has_basic_access = False
            await session.commit()

            await callback.answer("Доступ забран", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await notify_basic_access_limited(callback.message.bot, user.telegram_id)
            await _send_user_card(callback.message.bot, admin_chat_id, user_id)
            return

        # --- ЗАБРАТЬ VIP ---
        elif action == "revoke_vip":
            user.is_vip = False
            await session.commit()

            await callback.answer("VIP доступ забран", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await notify_vip_access_limited(callback.message.bot, user.telegram_id)
            await _send_user_card(callback.message.bot, admin_chat_id, user_id)
            return

        # --- УДАЛИТЬ ЮЗЕРА ---
        elif action == "delete":
            await session.delete(user)
            await session.commit()

            await callback.answer("Пользователь удалён", show_alert=False)
            if callback.message:
                try:
                    await callback.message.delete()
                except Exception:
                    pass

            await _send_users_list(callback.message.bot, admin_chat_id, page=1)
            return

        else:
            await callback.answer("Неизвестное действие", show_alert=True)
            return


# ===== ПРОЧИЕ КНОПКИ =====


@router.callback_query(F.data == "admin:broadcast")
async def admin_broadcast_stub(callback: CallbackQuery) -> None:
    if callback.from_user is None or not _is_admin(callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer("Рассылку сделаем позже.", show_alert=True)


@router.callback_query(F.data == "admin:users:noop")
async def admin_users_noop(callback: CallbackQuery) -> None:
    await callback.answer()