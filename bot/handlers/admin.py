from __future__ import annotations

import os
from typing import Optional, Dict, List

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from sqlalchemy import select, func, delete

from ..models import base as db
from ..models.user import User
from ..models.settings import Settings
from ..models.deposit import Deposit
from .main_menu import (
    run_access_flow_for_user,
    notify_basic_access_limited,
    notify_vip_access_limited,
    notify_vip_granted,
)

router = Router()

# ============================================================
#  Админские ID
# ============================================================

def get_admin_ids() -> List[int]:
    raw = os.getenv("ADMINS", "")
    ids: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue
    return ids


def is_admin(tg_id: int) -> bool:
    return tg_id in get_admin_ids()


# ============================================================
#  FSM состояния
# ============================================================

class LinksEditState(StatesGroup):
    waiting_value = State()  # ждём новую ссылку / id


class SettingsEditState(StatesGroup):
    waiting_value = State()  # ждём новое число (порог)


# в FSM будем хранить:
#   field: имя поля в Settings
#   kind:  "link" или "settings"


# ============================================================
#  Хелперы для Settings
# ============================================================

async def get_settings() -> Settings:
    if db.async_session_maker is None:
        raise RuntimeError("DB not initialized")

    async with db.async_session_maker() as session:
        result = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = result.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings


async def save_settings(settings: Settings) -> None:
    if db.async_session_maker is None:
        raise RuntimeError("DB not initialized")

    async with db.async_session_maker() as session:
        db_obj = await session.get(Settings, settings.id)
        if not db_obj:
            session.add(settings)
        else:
            for attr in (
                "require_subscription",
                "require_deposit",
                "deposit_required_amount",
                "vip_threshold_amount",
                "channel_id",
                "channel_url",
                "ref_link",
                "deposit_link",
                "support_url",
                "postbacks_group_id",
                "send_reg_postbacks",
                "send_deposit_postbacks",
                "send_withdraw_postbacks",
            ):
                if hasattr(settings, attr):
                    setattr(db_obj, attr, getattr(settings, attr))
        await session.commit()


# ============================================================
#  Постбэки: базовый URL + генерация ссылок
# ============================================================

def get_postback_base_url() -> str:
    base = os.getenv("POSTBACK_BASE_URL", "").strip()
    if not base:
        return ""
    return base.rstrip("/")


def build_postback_urls() -> Dict[str, str]:
    base = get_postback_base_url()
    if not base:
        return {}

    return {
        # Регистрация: trader_id + click_id (tg id)
        "registration": (
            f"{base}/postback/registration"
            "?trader_id={{trader_id}}&click_id={{click_id}}"
        ),
        # Первый депозит: trader_id + click_id + sumdep
        "ftd": (
            f"{base}/postback/first_deposit"
            "?trader_id={{trader_id}}&click_id={{click_id}}&sumdep={{sumdep}}"
        ),
        # Повторный депозит: trader_id + click_id + sumdep
        "redep": (
            f"{base}/postback/redeposit"
            "?trader_id={{trader_id}}&click_id={{click_id}}&sumdep={{sumdep}}"
        ),
        # Вывод: trader_id + click_id + wdr_sum
        "withdraw": (
            f"{base}/postback/withdraw"
            "?trader_id={{trader_id}}&click_id={{click_id}}&wdr_sum={{wdr_sum}}"
        ),
    }


# ============================================================
#  Клавиатуры админки
# ============================================================

def admin_main_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👤 Пользователи",
                    callback_data="admin_users_page:1",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔗 URL постбэков",
                    callback_data="admin_postbacks",
                )
            ],
            [
                InlineKeyboardButton(
                    text="⚙️ Настройки",
                    callback_data="admin_settings",
                ),
                InlineKeyboardButton(
                    text="🔗 Ссылки",
                    callback_data="admin_links",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📨 Рассылка (WIP)",
                    callback_data="admin_broadcast",
                )
            ],
        ]
    )


def admin_users_pagination_kb(page: int, has_prev: bool, has_next: bool) -> InlineKeyboardMarkup:
    buttons_row = []
    if has_prev:
        buttons_row.append(
            InlineKeyboardButton(
                text="⬅️",
                callback_data=f"admin_users_page:{page - 1}",
            )
        )
    buttons_row.append(
        InlineKeyboardButton(
            text=f"Стр {page}",
            callback_data="noop",
        )
    )
    if has_next:
        buttons_row.append(
            InlineKeyboardButton(
                text="➡️",
                callback_data=f"admin_users_page:{page + 1}",
            )
        )

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔍 Поиск",
                    callback_data="admin_user_search",
                )
            ],
            buttons_row,
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в меню",
                    callback_data="admin_menu",
                )
            ],
        ]
    )


def admin_user_card_kb(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Выдать регу",
                    callback_data=f"admin_user_give_reg:{user_id}",
                ),
                InlineKeyboardButton(
                    text="💰 Выдать деп",
                    callback_data=f"admin_user_give_dep:{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👑 Выдать VIP",
                    callback_data=f"admin_user_give_vip:{user_id}",
                ),
                InlineKeyboardButton(
                    text="🚫 Забрать доступ",
                    callback_data=f"admin_user_take_access:{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Забрать VIP",
                    callback_data=f"admin_user_take_vip:{user_id}",
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить юзера",
                    callback_data=f"admin_user_delete:{user_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад к пользователям",
                    callback_data="admin_users_page:1",
                )
            ],
        ]
    )


def admin_links_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔗 Реф. ссылка",
                    callback_data="admin_link_edit:ref_link",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💰 Ссылка на депозит",
                    callback_data="admin_link_edit:deposit_link",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="📡 ID канала",
                    callback_data="admin_link_edit:channel_id",
                ),
                InlineKeyboardButton(
                    text="📡 Ссылка на канал",
                    callback_data="admin_link_edit:channel_url",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🆘 Ссылка поддержки",
                    callback_data="admin_link_edit:support_url",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в меню",
                    callback_data="admin_menu",
                ),
            ],
        ]
    )


def admin_settings_kb(settings: Settings) -> InlineKeyboardMarkup:
    require_sub = "✅" if settings.require_subscription else "❌"
    require_dep = "✅" if settings.require_deposit else "❌"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{require_sub} Проверять подписку",
                    callback_data="admin_settings_toggle:require_subscription",
                )
            ],
            [
                InlineKeyboardButton(
                    text=f"{require_dep} Проверять депозит",
                    callback_data="admin_settings_toggle:require_deposit",
                )
            ],
            [
                InlineKeyboardButton(
                    text="💰 Порог депозита",
                    callback_data="admin_settings_edit:deposit_required_amount",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="👑 Порог VIP",
                    callback_data="admin_settings_edit:vip_threshold_amount",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в меню",
                    callback_data="admin_menu",
                ),
            ],
        ]
    )


def admin_postbacks_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в меню",
                    callback_data="admin_menu",
                )
            ]
        ]
    )


# ============================================================
#  /admin вход
# ============================================================

@router.message(Command("admin"))
async def admin_entry(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    # Статистика
    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        total_users = (await session.execute(
            select(func.count(User.id))
        )).scalar_one()

        total_registered = (await session.execute(
            select(func.count(User.id)).where(User.is_registered == True)
        )).scalar_one()

        total_deposit_sum = (await session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0.0))
        )).scalar_one()

    text = (
        "👨‍💻 <b>Админка</b>\n\n"
        f"Пользователей: <b>{total_users}</b>\n"
        f"Регистраций: <b>{total_registered}</b>\n"
        f"Сумма депозитов: <b>{float(total_deposit_sum):.2f}$</b>\n"
    )

    await message.answer(
        text,
        reply_markup=admin_main_kb(),
    )


# ============================================================
#  Главное меню админки (callback)
# ============================================================

@router.callback_query(F.data == "admin_menu")
async def admin_menu_cb(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    await callback.message.edit_text(
        "👨‍💻 <b>Админка</b>",
        reply_markup=admin_main_kb(),
    )
    await callback.answer()


# ============================================================
#  Пользователи: список и поиск
# ============================================================

PAGE_SIZE = 5


async def format_user_line(user: User) -> str:
    lang = user.language or "—"
    sub = "✅" if user.is_subscribed else "❌"
    reg = "✅" if user.is_registered else "❌"
    dep = "✅" if user.has_basic_access else "❌"
    vip = "✅" if user.is_vip else "❌"

    return (
        f"ID: <code>{user.id}</code> | TG: <code>{user.telegram_id}</code>\n"
        f"Username: <code>{user.username or '—'}</code>\n"
        f"Язык: <b>{lang}</b> | Подписка: {sub} | Рег: {reg} | Доступ: {dep} | VIP: {vip}\n"
        f"<b>Открыть карточку:</b> /user_{user.id}\n"
        "-----------\n"
    )


@router.callback_query(F.data.startswith("admin_users_page:"))
async def admin_users_page(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, page_str = callback.data.split(":", 1)
    try:
        page = int(page_str)
    except ValueError:
        page = 1
    if page < 1:
        page = 1

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        total_users = (await session.execute(
            select(func.count(User.id))
        )).scalar_one()

        offset = (page - 1) * PAGE_SIZE
        result = await session.execute(
            select(User)
            .order_by(User.id.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        users = result.scalars().all()

    text_lines = ["👤 <b>Пользователи</b>\n"]
    if not users:
        text_lines.append("Пока нет пользователей.")
    else:
        for u in users:
            text_lines.append(await format_user_line(u))

    has_prev = page > 1
    has_next = total_users > page * PAGE_SIZE

    await callback.message.edit_text(
        "\n".join(text_lines),
        reply_markup=admin_users_pagination_kb(page, has_prev, has_next),
        disable_web_page_preview=True,
    )
    await callback.answer()


# простенький поиск: ждём tg id или trader id
class UserSearchState(StatesGroup):
    waiting_query = State()


@router.callback_query(F.data == "admin_user_search")
async def admin_user_search_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    await state.set_state(UserSearchState.waiting_query)
    await callback.message.edit_text(
        "🔍 Введите <b>Telegram ID</b> или <b>Trader ID</b> пользователя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад к пользователям",
                        callback_data="admin_users_page:1",
                    )
                ]
            ]
        ),
    )
    await callback.answer()


@router.message(UserSearchState.waiting_query)
async def admin_user_search_process(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    query = message.text.strip()
    await state.clear()

    if db.async_session_maker is None:
        await message.answer("DB not initialized")
        return

    async with db.async_session_maker() as session:
        stmt = select(User)
        # пробуем как tg_id
        try:
            tg_id = int(query)
            stmt = stmt.where(User.telegram_id == tg_id)
        except ValueError:
            # ищем по trader_id
            stmt = stmt.where(User.trader_id == query)
        result = await session.execute(stmt)
        user: Optional[User] = result.scalar_one_or_none()

    if not user:
        await message.answer(
            "Пользователь не найден.",
            reply_markup=admin_users_pagination_kb(page=1, has_prev=False, has_next=False),
        )
        return

    await send_user_card(message.bot, message.chat.id, user.id)


# ============================================================
#  Карточка пользователя
# ============================================================

async def send_user_card(bot: Bot, chat_id: int, user_id: int) -> None:
    if db.async_session_maker is None:
        await bot.send_message(chat_id, "DB not initialized")
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await bot.send_message(chat_id, "Пользователь не найден.")
            return

        # сумма депов
        total_deposit = (await session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0.0)).where(
                Deposit.user_id == user.id
            )
        )).scalar_one()

    sub = "✅" if user.is_subscribed else "❌"
    reg = "✅" if user.is_registered else "❌"
    dep = "✅" if user.has_basic_access else "❌"
    vip = "✅" if user.is_vip else "❌"

    text = (
        "👤 <b>Пользователь</b>\n\n"
        f"Telegram ID: <code>{user.telegram_id}</code>\n"
        f"Username: <code>{user.username or '—'}</code>\n"
        f"Trader ID: <code>{user.trader_id or '—'}</code>\n"
        f"Язык: <b>{user.language or '—'}</b>\n\n"
        f"Подписка: {sub}\n"
        f"Регистрация: {reg}\n"
        f"Депозит: {dep} (сумма: <b>{float(total_deposit):.2f}$</b>)\n"
        f"VIP: {vip}\n"
    )

    await bot.send_message(
        chat_id,
        text,
        reply_markup=admin_user_card_kb(user.id),
    )


@router.message(F.text.regexp(r"^/user_(\d+)$"))
async def admin_user_by_command(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return

    import re
    m = re.match(r"^/user_(\d+)$", message.text.strip())
    if not m:
        return
    user_id = int(m.group(1))
    await send_user_card(message.bot, message.chat.id, user_id)


@router.callback_query(F.data.startswith("admin_user_give_reg:"))
async def admin_user_give_reg(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user.is_registered = True
        await session.commit()
        tg_id = user.telegram_id

    await callback.answer("Регистрация выдана ✅", show_alert=False)
    await callback.message.delete()
    await send_user_card(callback.message.bot, callback.message.chat.id, user_id)

    # запускаем флоу, чтобы прислать следующий шаг (депозит или доступ)
    await run_access_flow_for_user(callback.message.bot, tg_id)


@router.callback_query(F.data.startswith("admin_user_give_dep:"))
async def admin_user_give_dep(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    # Для простоты: даём депозит 0.0 — всё равно дальше логика опирается
    # на общую сумму и пороги. В реале можно сделать отдельное окно ввода суммы.
    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return

        dep = Deposit(user_id=user.id, amount=0.0)
        session.add(dep)
        await session.commit()
        tg_id = user.telegram_id

    await callback.answer("Депозит выдан (0.0$) ✅", show_alert=False)
    await callback.message.delete()
    await send_user_card(callback.message.bot, callback.message.chat.id, user_id)

    # перезапускаем флоу
    await run_access_flow_for_user(callback.message.bot, tg_id)


@router.callback_query(F.data.startswith("admin_user_give_vip:"))
async def admin_user_give_vip(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user.is_vip = True
        # на всякий случай откроем и обычный доступ
        user.has_basic_access = True
        await session.commit()
        tg_id = user.telegram_id

    await callback.answer("VIP выдан ✅", show_alert=False)
    await callback.message.delete()
    await send_user_card(callback.message.bot, callback.message.chat.id, user_id)

    await notify_vip_granted(callback.message.bot, tg_id)


@router.callback_query(F.data.startswith("admin_user_take_access:"))
async def admin_user_take_access(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user.has_basic_access = False
        await session.commit()
        tg_id = user.telegram_id

    await callback.answer("Доступ забран", show_alert=False)
    await callback.message.delete()
    await send_user_card(callback.message.bot, callback.message.chat.id, user_id)

    await notify_basic_access_limited(callback.message.bot, tg_id)


@router.callback_query(F.data.startswith("admin_user_take_vip:"))
async def admin_user_take_vip(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Пользователь не найден", show_alert=True)
            return
        user.is_vip = False
        await session.commit()
        tg_id = user.telegram_id

    await callback.answer("VIP доступ забран", show_alert=False)
    await callback.message.delete()
    await send_user_card(callback.message.bot, callback.message.chat.id, user_id)

    await notify_vip_access_limited(callback.message.bot, tg_id)


@router.callback_query(F.data.startswith("admin_user_delete:"))
async def admin_user_delete(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, id_str = callback.data.split(":", 1)
    user_id = int(id_str)

    if db.async_session_maker is None:
        await callback.answer("DB not initialized", show_alert=True)
        return

    async with db.async_session_maker() as session:
        user = await session.get(User, user_id)
        if not user:
            await callback.answer("Уже удалён", show_alert=True)
            return

        # удаляем все депозиты и самого юзера
        await session.execute(delete(Deposit).where(Deposit.user_id == user.id))
        await session.delete(user)
        await session.commit()

    await callback.answer("Пользователь полностью удалён", show_alert=True)
    await callback.message.delete()


# ============================================================
#  Ссылки (ref, депозит, канал, поддержка)
# ============================================================

@router.callback_query(F.data == "admin_links")
async def admin_links_menu(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    settings = await get_settings()

    text = (
        "🔗 <b>Ссылки</b>\n\n"
        f"Реф. ссылка: <code>{settings.ref_link or '—'}</code>\n\n"
        f"Ссылка на депозит: <code>{settings.deposit_link or '—'}</code>\n\n"
        f"ID канала: <code>{settings.channel_id or '—'}</code>\n"
        f"Ссылка на канал: <code>{settings.channel_url or '—'}</code>\n\n"
        f"Ссылка поддержки: <code>{settings.support_url or '—'}</code>\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_links_kb(),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_link_edit:"))
async def admin_link_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, field = callback.data.split(":", 1)

    field_titles = {
        "ref_link": "реферальную ссылку",
        "deposit_link": "ссылку на депозит",
        "channel_id": "ID канала",
        "channel_url": "ссылку на канал",
        "support_url": "ссылку поддержки",
    }

    title = field_titles.get(field, field)

    await state.set_state(LinksEditState.waiting_value)
    await state.update_data(field=field)

    await callback.message.edit_text(
        f"✏️ Отправь новое значение для <b>{title}</b>.\n"
        f"Для очистки отправь прочерк <code>-</code>.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад к ссылкам",
                        callback_data="admin_links",
                    )
                ]
            ]
        ),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.message(LinksEditState.waiting_value)
async def admin_link_edit_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    field = data.get("field")
    value = message.text.strip()
    await state.clear()

    settings = await get_settings()

    if value == "-":
        value = None

    if field and hasattr(settings, field):
        setattr(settings, field, value)

    await save_settings(settings)

    await message.answer("✅ Сохранено.", reply_markup=admin_links_kb())
    # сразу обновим текст со ссылками
    await admin_links_menu_fake(message)


async def admin_links_menu_fake(message: Message) -> None:
    """Та же логика, что и admin_links_menu, но от Message."""
    settings = await get_settings()
    text = (
        "🔗 <b>Ссылки</b>\n\n"
        f"Реф. ссылка: <code>{settings.ref_link or '—'}</code>\n\n"
        f"Ссылка на депозит: <code>{settings.deposit_link or '—'}</code>\n\n"
        f"ID канала: <code>{settings.channel_id or '—'}</code>\n"
        f"Ссылка на канал: <code>{settings.channel_url or '—'}</code>\n\n"
        f"Ссылка поддержки: <code>{settings.support_url or '—'}</code>\n"
    )
    await message.answer(
        text,
        reply_markup=admin_links_kb(),
        disable_web_page_preview=True,
    )


# ============================================================
#  Настройки (флаги и пороги)
# ============================================================

@router.callback_query(F.data == "admin_settings")
async def admin_settings_menu(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    settings = await get_settings()

    text = (
        "⚙️ <b>Настройки</b>\n\n"
        f"Проверять подписку: <b>{'Да' if settings.require_subscription else 'Нет'}</b>\n"
        f"Проверять депозит: <b>{'Да' if settings.require_deposit else 'Нет'}</b>\n\n"
        f"Порог депозита для доступа: <b>{float(settings.deposit_required_amount or 0.0):.2f}$</b>\n"
        f"Порог VIP: <b>{float(settings.vip_threshold_amount or 0.0):.2f}$</b>\n"
    )

    await callback.message.edit_text(
        text,
        reply_markup=admin_settings_kb(settings),
        disable_web_page_preview=True,
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_settings_toggle:"))
async def admin_settings_toggle(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, field = callback.data.split(":", 1)
    settings = await get_settings()

    if hasattr(settings, field):
        current = bool(getattr(settings, field))
        setattr(settings, field, not current)
        await save_settings(settings)

    await admin_settings_menu(callback)


@router.callback_query(F.data.startswith("admin_settings_edit:"))
async def admin_settings_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    _, field = callback.data.split(":", 1)

    titles = {
        "deposit_required_amount": "порог депозита для доступа (в $)",
        "vip_threshold_amount": "порог VIP (в $)",
    }

    await state.set_state(SettingsEditState.waiting_value)
    await state.update_data(field=field)

    await callback.message.edit_text(
        f"✏️ Введи новое значение для <b>{titles.get(field, field)}</b>.\n"
        f"Текущее будет переписано.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⬅️ Назад к настройкам",
                        callback_data="admin_settings",
                    )
                ]
            ]
        ),
    )
    await callback.answer()


@router.message(SettingsEditState.waiting_value)
async def admin_settings_edit_save(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id):
        await state.clear()
        return

    data = await state.get_data()
    field = data.get("field")
    value_raw = message.text.strip()
    await state.clear()

    try:
        value = float(value_raw.replace(",", "."))
    except ValueError:
        await message.answer("❌ Нужно ввести число.")
        return

    settings = await get_settings()
    if field and hasattr(settings, field):
        setattr(settings, field, value)
        await save_settings(settings)

    await message.answer("✅ Порог сохранён.")
    # покажем настройки
    fake_cb = type("FakeCb", (), {"from_user": message.from_user, "message": message})
    await admin_settings_menu(fake_cb)  # небольшой трюк, чтобы переиспользовать функцию


# ============================================================
#  URL постбэков
# ============================================================

@router.callback_query(F.data == "admin_postbacks")
async def admin_postbacks_menu(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    urls = build_postback_urls()
    base = get_postback_base_url()

    if not base:
        text = (
            "⚠️ <b>URL постбэков</b>\n\n"
            "Базовый адрес постбэков не настроен.\n\n"
            "Добавь переменную <code>POSTBACK_BASE_URL</code> в <code>.env</code>, например:\n"
            "<code>POSTBACK_BASE_URL=http://45.90.218.187:8000</code>\n"
        )
    else:
        text = (
            "🔗 <b>URL постбэков для партнёрки</b>\n\n"
            f"Базовый адрес: <code>{base}</code>\n\n"
            "Регистрация:\n"
            f"<code>{urls['registration']}</code>\n\n"
            "Первый депозит (FTD):\n"
            f"<code>{urls['ftd']}</code>\n\n"
            "Повторный депозит:\n"
            f"<code>{urls['redep']}</code>\n\n"
            "Вывод средств:\n"
            f"<code>{urls['withdraw']}</code>\n\n"
            "📌 <b>Макросы</b>\n"
            "• <code>{trader_id}</code> — ID трейдера у брокера\n"
            "• <code>{click_id}</code> — Telegram ID пользователя\n"
            "• <code>{sumdep}</code> — сумма депозита\n"
            "• <code>{wdr_sum}</code> — сумма вывода\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=admin_postbacks_kb(),
        disable_web_page_preview=True,
    )
    await callback.answer()


# ============================================================
#  Рассылка (пока заглушка)
# ============================================================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast_stub(callback: CallbackQuery) -> None:
    if not callback.from_user or not is_admin(callback.from_user.id):
        await callback.answer()
        return

    text = (
        "📨 <b>Рассылка</b>\n\n"
        "Функция рассылки пока в разработке."
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⬅️ Назад в меню",
                    callback_data="admin_menu",
                )
            ]
        ]
    )

    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()