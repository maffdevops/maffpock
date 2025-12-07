from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

from aiogram import Router, F, Bot
from aiogram.types import (
    Message,
    CallbackQuery,
    FSInputFile,
    ChatMemberUpdated,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select, func

from ..models import base as db
from ..models.user import User
from ..models.settings import Settings
from ..models.deposit import Deposit

router = Router()

BASE_DIR = Path(__file__).resolve().parents[2]

# URL мини-апп берём из .env
BASIC_MINIAPP_URL = os.getenv("BASIC_MINIAPP_URL", "").strip()
VIP_MINIAPP_URL = os.getenv("VIP_MINIAPP_URL", "").strip()

# =====================================================================
# ТЕКСТЫ
# =====================================================================

MENU_LABELS: Dict[str, Dict[str, str]] = {
    "ru": {
        "instruction": "📘 Инструкция",
        "support": "🆘 Поддержка",
        "change_language": "🌐 Сменить язык",
        "get_signal": "📈 Получить сигнал",
        "back_to_menu": "⬅️ Вернуться в меню",
        "open_signal": "📈 Получить сигнал",
    },
    "en": {
        "instruction": "📘 Instruction",
        "support": "🆘 Support",
        "change_language": "🌐 Change language",
        "get_signal": "📈 Get signal",
        "back_to_menu": "⬅️ Back to menu",
        "open_signal": "📈 Get signal",
    },
    "es": {
        "instruction": "📘 Instrucción",
        "support": "🆘 Soporte",
        "change_language": "🌐 Cambiar idioma",
        "get_signal": "📈 Obtener señal",
        "back_to_menu": "⬅️ Volver al menú",
        "open_signal": "📈 Obtener señal",
    },
    "hi": {
        "instruction": "📘 निर्देश",
        "support": "🆘 सपोर्ट",
        "change_language": "🌐 भाषा बदलें",
        "get_signal": "📈 सिग्नल प्राप्त करें",
        "back_to_menu": "⬅️ मेनू पर वापस",
        "open_signal": "📈 सिग्नल प्राप्त करें",
    },
}

MAIN_MENU_TEXT: Dict[str, str] = {
    "ru": "📋 <b>Главное меню</b>",
    "en": "📋 <b>Main menu</b>",
    "es": "📋 <b>Menú principal</b>",
    "hi": "📋 <b>मुख्य मेनू</b>",
}

INSTRUCTION_TEXT: Dict[str, str] = {
    "ru": (
        "📘 <b>Инструкция</b>\n\n"
        "1️⃣ Нажмите «📈 Получить сигнал».\n"
        "2️⃣ Пройдите шаги: подписка, регистрация, депозит (если включены в админке).\n"
        "3️⃣ После прохождения всех обязательных шагов бот откроет доступ к мини-аппам.\n\n"
        "Все окна будут приходить автоматически, старые сообщения бот удаляет."
    ),
    "en": (
        "📘 <b>Instruction</b>\n\n"
        "1️⃣ Press “📈 Get signal”.\n"
        "2️⃣ Complete steps: subscription, registration, deposit (if enabled in admin).\n"
        "3️⃣ After all required steps, bot will open access to mini-apps.\n\n"
        "All screens are pushed automatically, old messages are deleted."
    ),
    "es": (
        "📘 <b>Instrucción</b>\n\n"
        "1️⃣ Pulsa “📈 Obtener señal”.\n"
        "2️⃣ Completa pasos: suscripción, registro, depósito (si están activos en admin).\n"
        "3️⃣ Tras todos los pasos obligatorios, el bot abrirá acceso a las mini-apps.\n\n"
        "Todas las pantallas se envían automáticamente, mensajes antiguos se borran."
    ),
    "hi": (
        "📘 <b>निर्देश</b>\n\n"
        "1️⃣ “📈 सिग्नल प्राप्त करें” दबाएँ।\n"
        "2️⃣ Шаги: подписка, регистрация, депозит (если включены в админке).\n"
        "3️⃣ После всех шагов бот откроет доступ к мини-аппам.\n\n"
        "Все окна приходят автоматически, старые сообщения бот удаляет."
    ),
}

SUBSCRIPTION_TEXT: Dict[str, str] = {
    "ru": (
        "📡 <b>Шаг 1. Подписка на канал</b>\n\n"
        "Подпишитесь на канал по кнопке ниже.\n"
        "Как только вы подпишетесь, бот автоматически переведёт вас к следующему шагу."
    ),
    "en": (
        "📡 <b>Step 1. Channel subscription</b>\n\n"
        "Subscribe to the channel using the button below.\n"
        "As soon as you subscribe, the bot will automatically move you to the next step."
    ),
    "es": (
        "📡 <b>Paso 1. Suscripción al canal</b>\n\n"
        "Suscríbete al canal con el botón de abajo.\n"
        "En cuanto te suscribas, el bot te llevará automáticamente al siguiente paso."
    ),
    "hi": (
        "📡 <b>स्टेप 1. चैनल सब्सक्रिप्शन</b>\n\n"
        "नीचे दिए गए बटन से канал подпишитесь.\n"
        "Как только подпишетесь, бот переведёт вас на следующий шаг."
    ),
}

REGISTRATION_TEXT: Dict[str, str] = {
    "ru": (
        "📝 <b>Шаг 2. Регистрация у брокера</b>\n\n"
        "Нажмите «📝 Зарегистрироваться» и завершите регистрацию на сайте брокера.\n"
        "Когда брокер пришлёт постбэк или админ отметит регистрацию вручную, "
        "бот автоматически отправит следующий шаг."
    ),
    "en": (
        "📝 <b>Step 2. Broker registration</b>\n\n"
        "Press “📝 Register” and complete registration on the broker website.\n"
        "When broker postback or admin confirms registration, "
        "the bot will automatically send the next step."
    ),
    "es": (
        "📝 <b>Paso 2. Registro con el bróker</b>\n\n"
        "Pulsa “📝 Registrarse” y completa el registro en la web del bróker.\n"
        "Cuando el bróker envíe postback o el admin confirme, "
        "el bot enviará automáticamente el siguiente paso."
    ),
    "hi": (
        "📝 <b>स्टेप 2. ब्रोकर पर रजिस्ट्रेशन</b>\n\n"
        "“📝 Register” нажмите и регистрацию завершите.\n"
        "Когда брокер postback пришлёт или admin отметит, "
        "бот автоматически следующий шаг отправит."
    ),
}

DEPOSIT_TEXT: Dict[str, str] = {
    "ru": (
        "💰 <b>Шаг 3. Депозит</b>\n\n"
        "Минимальная сумма депозита для доступа: <b>{required:.2f}$</b>.\n"
        "Сумма ваших депозитов: <b>{current:.2f}$</b>.\n\n"
        "Сделайте депозит по кнопке ниже. После подтверждения депозита бот откроет доступ."
    ),
    "en": (
        "💰 <b>Step 3. Deposit</b>\n\n"
        "Minimum deposit for access: <b>{required:.2f}$</b>.\n"
        "Your deposit sum: <b>{current:.2f}$</b>.\n\n"
        "Make a deposit using the button below. After confirmation the bot will open access."
    ),
    "es": (
        "💰 <b>Paso 3. Depósito</b>\n\n"
        "Depósito mínimo para acceso: <b>{required:.2f}$</b>.\n"
        "Tu suma de depósitos: <b>{current:.2f}$</b>.\n\n"
        "Haz un depósito usando el botón. Tras la confirmación el bot abrirá el acceso."
    ),
    "hi": (
        "💰 <b>स्टेप 3. डिपॉज़िट</b>\n\n"
        "Минимальный депозит для доступа: <b>{required:.2f}$</b>.\n"
        "Ваш текущий депозит: <b>{current:.2f}$</b>.\n\n"
        "Ниже по кнопке сделайте депозит. После подтверждения бот откроет доступ."
    ),
}

ACCESS_OPEN_TEXT: Dict[str, str] = {
    "ru": (
        "✅ <b>Доступ открыт</b>\n\n"
        "Теперь кнопка «📈 Получить сигнал» в главном меню и в этом окне "
        "открывает мини-аппу."
    ),
    "en": (
        "✅ <b>Access granted</b>\n\n"
        "Now the “📈 Get signal” button in main menu and in this window "
        "opens the mini-app."
    ),
    "es": (
        "✅ <b>Acceso abierto</b>\n\n"
        "Ahora el botón “📈 Obtener señal” en el menú principal y en esta ventana "
        "abre la mini-app."
    ),
    "hi": (
        "✅ <b>Доступ открыт</b>\n\n"
        "अब «📈 सिग्नल प्राप्त करें» кнопка मुख्य меню и в этом окне "
        "мини-аппу открывает."
    ),
}

VIP_GRANTED_TEXT: Dict[str, str] = {
    "ru": "👑 <b>Вы получили VIP-доступ</b>.\nТеперь будет открываться VIP-мини-аппа.",
    "en": "👑 <b>You have VIP access</b>.\nNow VIP mini-app will be opened.",
    "es": "👑 <b>Tienes acceso VIP</b>.\nAhora se abrirá la mini-app VIP.",
    "hi": "👑 <b>आपको VIP доступ выдан</b>.\nТеперь будет открываться VIP-мини-аппа.",
}

LIMITED_BASIC_TEXT: Dict[str, str] = {
    "ru": (
        "💎 <b>Доступ к боту ограничен</b>\n\n"
        "Пополните аккаунт для активации бота.\n"
        "Минимальная сумма депозита: <b>{required:.2f}$</b>."
    ),
    "en": (
        "💎 <b>Access to the bot is limited</b>\n\n"
        "Top up your account to activate the bot.\n"
        "Minimum deposit: <b>{required:.2f}$</b>."
    ),
    "es": (
        "💎 <b>Acceso al bot limitado</b>\n\n"
        "Recarga tu cuenta para activar el bot.\n"
        "Depósito mínimo: <b>{required:.2f}$</b>."
    ),
    "hi": (
        "💎 <b>Бот का доступ ограничен</b>\n\n"
        "Аккаунт пополните, чтобы активировать бота.\n"
        "Минимальный депозит: <b>{required:.2f}$</b>."
    ),
}

LIMITED_VIP_TEXT: Dict[str, str] = {
    "ru": (
        "💎 <b>Доступ к платинум версии ограничен</b>\n\n"
        "Пополните аккаунт для активации VIP доступа.\n"
        "VIP-порог: <b>{vip:.2f}$</b>."
    ),
    "en": (
        "💎 <b>Platinum access limited</b>\n\n"
        "Top up your account to activate VIP access.\n"
        "VIP threshold: <b>{vip:.2f}$</b>."
    ),
    "es": (
        "💎 <b>Acceso platino limitado</b>\n\n"
        "Recarga tu cuenta para activar el acceso VIP.\n"
        "Umbral VIP: <b>{vip:.2f}$</b>."
    ),
    "hi": (
        "💎 <b>Платинум доступ ограничен</b>\n\n"
        "VIP доступ активировать — аккаунт пополните.\n"
        "VIP порог: <b>{vip:.2f}$</b>."
    ),
}

CONFIG_ERROR_TEXT: Dict[str, str] = {
    "ru": (
        "⚠️ <b>Ошибка конфигурации</b>\n\n"
        "В админке не задана ссылка или порог для этого шага. "
        "Свяжитесь с админом и попросите заполнить настройки."
    ),
    "en": (
        "⚠️ <b>Configuration error</b>\n\n"
        "Some link or threshold is not configured in admin panel. "
        "Contact admin to fix the settings."
    ),
    "es": (
        "⚠️ <b>Error de configuración</b>\n\n"
        "Falta algún enlace o umbral en el panel admin. "
        "Contacta con el admin para que lo configure."
    ),
    "hi": (
        "⚠️ <b>Конфигурация ошибка</b>\n\n"
        "Админке не заданы ссылки или пороги. "
        "Напишите админу, чтобы он настроил их."
    ),
}

LANG_TITLES: Dict[str, str] = {
    "ru": "Русский 🇷🇺",
    "en": "English 🇬🇧",
    "es": "Español 🇪🇸",
    "hi": "हिन्दी 🇮🇳",
}

CHOOSE_LANGUAGE_TEXT = (
    "🌐 <b>Выбор языка интерфейса</b>\n\n"
    "Choose your language 👇"
)


# =====================================================================
# ВСПОМОГАТЕЛЬНОЕ
# =====================================================================

def get_labels(lang: str) -> Dict[str, str]:
    return MENU_LABELS.get(lang, MENU_LABELS["en"])


def _get_image_path(lang: str, name: str) -> Optional[Path]:
    base = BASE_DIR / "locales" / lang / "images" / name
    jpg = base.with_suffix(".jpg")
    png = base.with_suffix(".png")
    if jpg.exists():
        return jpg
    if png.exists():
        return png
    return None


def _get_miniapp_url_for_user(user: Optional[User]) -> Optional[str]:
    """
    Определяем, какую мини-аппу открывать для пользователя.
    """
    if user is None:
        return None

    if user.is_vip and VIP_MINIAPP_URL:
        return VIP_MINIAPP_URL

    if BASIC_MINIAPP_URL:
        return BASIC_MINIAPP_URL

    return None


async def _get_or_create_user(tg_id: int, username: Optional[str] = None) -> User:
    if db.async_session_maker is None:
        raise RuntimeError("DB not initialized")

    async with db.async_session_maker() as session:
        result = await session.execute(select(User).where(User.telegram_id == tg_id))
        user: Optional[User] = result.scalar_one_or_none()
        if user is None:
            user = User(
                telegram_id=tg_id,
                username=username,
                language=None,
                is_subscribed=False,
                is_registered=False,
                has_basic_access=False,
                is_vip=False,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            if username and user.username != username:
                user.username = username
                await session.commit()
        return user


async def _get_user_lang(tg_id: int) -> str:
    if db.async_session_maker is None:
        return "en"
    async with db.async_session_maker() as session:
        res = await session.execute(select(User).where(User.telegram_id == tg_id))
        user: Optional[User] = res.scalar_one_or_none()
        if user and user.language:
            return user.language
    return "en"


async def _get_settings() -> Settings:
    if db.async_session_maker is None:
        raise RuntimeError("DB not initialized")
    async with db.async_session_maker() as session:
        res = await session.execute(select(Settings).where(Settings.id == 1))
        settings: Optional[Settings] = res.scalar_one_or_none()
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)
            await session.commit()
            await session.refresh(settings)
        return settings


async def _get_total_deposit(user_id: int) -> float:
    if db.async_session_maker is None:
        return 0.0
    async with db.async_session_maker() as session:
        res = await session.execute(
            select(func.coalesce(func.sum(Deposit.amount), 0)).where(
                Deposit.user_id == user_id
            )
        )
        return float(res.scalar_one() or 0)


async def _is_subscribed_via_api(bot: Bot, channel_id: Optional[str], tg_id: int) -> bool:
    if not channel_id:
        return True
    try:
        member = await bot.get_chat_member(channel_id, tg_id)
    except Exception:
        return False
    status = getattr(member, "status", None)
    return status in {"member", "administrator", "creator"}


# =====================================================================
# КЛАВИАТУРЫ
# =====================================================================

def _build_main_menu_markup(
    lang: str,
    support_url: Optional[str],
    user: Optional[User] = None,
):
    """
    Главное меню:
    - если у юзера ещё нет доступа → кнопка «Получить сигнал» = callback (шаги).
    - если доступ есть → кнопка = WebApp, сразу открывает мини-аппу.
    """
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()

    kb.button(text=labels["instruction"], callback_data="menu:instruction")

    if support_url:
        kb.button(text=labels["support"], url=support_url)
    else:
        kb.button(text=labels["support"], callback_data="menu:support_empty")

    kb.button(text=labels["change_language"], callback_data="menu:change_language")

    miniapp_url = None
    if user and (user.has_basic_access or user.is_vip):
        miniapp_url = _get_miniapp_url_for_user(user)

    if miniapp_url:
        kb.button(
            text=labels["get_signal"],
            web_app=WebAppInfo(url=miniapp_url),
        )
    else:
        kb.button(
            text=labels["get_signal"],
            callback_data="menu:get_signal",
        )

    kb.adjust(1, 2, 1)
    return kb.as_markup()


def _back_markup(lang: str):
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1)
    return kb.as_markup()


def _subscribe_markup(lang: str, channel_url: Optional[str]):
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    if channel_url:
        kb.button(
            text="📡 Подписаться" if lang == "ru" else "📡 Subscribe",
            url=channel_url,
        )
    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def _registration_markup(lang: str, ref_link: Optional[str]):
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    if ref_link:
        kb.button(
            text="📝 Зарегистрироваться" if lang == "ru" else "📝 Register",
            url=ref_link,
        )
    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def _deposit_markup(lang: str, deposit_link: Optional[str]):
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    if deposit_link:
        kb.button(
            text="💰 Сделать депозит" if lang == "ru" else "💰 Make deposit",
            url=deposit_link,
        )
    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def _access_opened_markup(lang: str, user: User):
    """
    Окно «Доступ открыт»:
    - кнопка «Получить сигнал» сразу WebApp, как в главном меню.
    """
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()

    miniapp_url = _get_miniapp_url_for_user(user)

    if miniapp_url:
        kb.button(
            text=labels["open_signal"],
            web_app=WebAppInfo(url=miniapp_url),
        )
    else:
        # fallback, если URL не настроен
        kb.button(
            text=labels["open_signal"],
            callback_data="menu:get_signal",
        )

    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def _limited_markup(lang: str, deposit_link: Optional[str]):
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    if deposit_link:
        kb.button(
            text="💰 Сделать депозит" if lang == "ru" else "💰 Make deposit",
            url=deposit_link,
        )
    kb.button(text=labels["back_to_menu"], callback_data="menu:back_to_menu")
    kb.adjust(1, 1)
    return kb.as_markup()


def _miniapp_markup(lang: str, url: str):
    """
    Если всё-таки открываем мини-аппу отдельным сообщением (fallback),
    используем эту клаву.
    """
    labels = get_labels(lang)
    kb = InlineKeyboardBuilder()
    kb.button(
        text=labels["open_signal"],
        web_app=WebAppInfo(url=url),
    )
    kb.button(
        text=labels["back_to_menu"],
        callback_data="menu:back_to_menu",
    )
    kb.adjust(1, 1)
    return kb.as_markup()


# =====================================================================
# ПУБЛИЧНЫЕ ФУНКЦИИ ДЛЯ ДРУГИХ МОДУЛЕЙ (admin)
# =====================================================================

async def run_access_flow_for_user(bot: Bot, tg_id: int) -> None:
    await _run_flow(bot, chat_id=tg_id, tg_id=tg_id)


async def notify_basic_access_limited(bot: Bot, tg_id: int) -> None:
    lang = await _get_user_lang(tg_id)
    settings = await _get_settings()
    required = float(settings.deposit_required_amount or 0)
    text_tpl = LIMITED_BASIC_TEXT.get(lang, LIMITED_BASIC_TEXT["en"])
    text = text_tpl.format(required=required)
    markup = _limited_markup(lang, settings.deposit_link)

    img_path = _get_image_path(lang, "deposit")
    if img_path:
        await bot.send_photo(
            tg_id,
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await bot.send_message(tg_id, text, reply_markup=markup)


async def notify_vip_access_limited(bot: Bot, tg_id: int) -> None:
    lang = await _get_user_lang(tg_id)
    settings = await _get_settings()
    vip_thr = float(settings.vip_threshold_amount or 0)
    text_tpl = LIMITED_VIP_TEXT.get(lang, LIMITED_VIP_TEXT["en"])
    text = text_tpl.format(vip=vip_thr)
    markup = _limited_markup(lang, settings.deposit_link)

    img_path = _get_image_path(lang, "deposit")
    if img_path:
        await bot.send_photo(
            tg_id,
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await bot.send_message(tg_id, text, reply_markup=markup)


async def notify_vip_granted(bot: Bot, tg_id: int) -> None:
    lang = await _get_user_lang(tg_id)

    # берём актуального юзера, чтобы понимать VIP/доступ
    user = await _get_or_create_user(tg_id)

    text = VIP_GRANTED_TEXT.get(lang, VIP_GRANTED_TEXT["en"])
    markup = _access_opened_markup(lang, user)

    img_path = _get_image_path(lang, "vip_opened")
    if img_path:
        await bot.send_photo(
            tg_id,
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await bot.send_message(tg_id, text, reply_markup=markup)


# =====================================================================
# ГЛАВНОЕ МЕНЮ / ВЫБОР ЯЗЫКА
# =====================================================================

async def send_main_menu(
    message: Message,
    lang: str,
    user: Optional[User] = None,
) -> None:
    """
    Если user передан — сразу строим правильную кнопку (callback/webapp).
    Если нет — подтягиваем юзера по from_user.
    """
    settings = await _get_settings()
    support_url = settings.support_url

    if user is None and message.from_user:
        user = await _get_or_create_user(
            message.from_user.id,
            message.from_user.username,
        )

    text = MAIN_MENU_TEXT.get(lang, MAIN_MENU_TEXT["en"])
    markup = _build_main_menu_markup(lang, support_url, user)
    img_path = _get_image_path(lang, "main_menu")

    if img_path:
        await message.answer_photo(
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await message.answer(text, reply_markup=markup)


async def send_language_choice(message: Message, lang: str | None = None) -> None:
    kb = InlineKeyboardBuilder()
    for code, title in LANG_TITLES.items():
        kb.button(text=title, callback_data=f"set_lang:{code}")
    kb.adjust(2)

    img_lang = lang if (lang is not None and lang in LANG_TITLES) else "en"
    img_path = _get_image_path(img_lang, "language_choice")
    if img_path:
        await message.answer_photo(
            photo=FSInputFile(str(img_path)),
            caption=CHOOSE_LANGUAGE_TEXT,
            reply_markup=kb.as_markup(),
        )
    else:
        await message.answer(
            CHOOSE_LANGUAGE_TEXT,
            reply_markup=kb.as_markup(),
        )


# =====================================================================
# МИНИ-АППЫ (fallback: если кто-то нажал callback при уже открытом доступе)
# =====================================================================

async def _open_miniapp(bot: Bot, chat_id: int, user: User, settings: Settings) -> None:
    lang = user.language or "en"

    url = _get_miniapp_url_for_user(user)
    if not url:
        await bot.send_message(
            chat_id,
            "⚠️ URL мини-аппы не настроен. Задай BASIC_MINIAPP_URL / VIP_MINIAPP_URL в .env.",
        )
        return

    markup = _miniapp_markup(lang, url)
    await bot.send_message(chat_id, "🚀 Мини-аппа:", reply_markup=markup)


# =====================================================================
# ЛОГИКА ФЛОУ «ПОЛУЧИТЬ СИГНАЛ»
# =====================================================================

async def _run_flow(bot: Bot, chat_id: int, tg_id: int) -> None:
    user = await _get_or_create_user(tg_id)
    lang = user.language or "en"
    settings = await _get_settings()

    # Если доступ уже есть — на всякий случай можем открыть мини-аппу (fallback),
    # но по нормальному сценарию юзер жмёт WebApp-кнопку и сюда не попадает.
    if user.has_basic_access or user.is_vip:
        await _open_miniapp(bot, chat_id, user, settings)
        return

    # 1. подписка
    if settings.require_subscription:
        if not user.is_subscribed:
            subscribed = await _is_subscribed_via_api(bot, settings.channel_id, tg_id)
            if subscribed and db.async_session_maker is not None:
                async with db.async_session_maker() as session:
                    db_user = await session.get(User, user.id)
                    if db_user:
                        db_user.is_subscribed = True
                        await session.commit()
                user.is_subscribed = True

        if not user.is_subscribed:
            text = SUBSCRIPTION_TEXT.get(lang, SUBSCRIPTION_TEXT["en"])
            markup = _subscribe_markup(lang, settings.channel_url)
            img_path = _get_image_path(lang, "subscription")
            if img_path:
                await bot.send_photo(
                    chat_id,
                    photo=FSInputFile(str(img_path)),
                    caption=text,
                    reply_markup=markup,
                )
            else:
                await bot.send_message(chat_id, text, reply_markup=markup)
            return

    # 2. регистрация (обязательный шаг)
    if not user.is_registered and not user.trader_id:
        if not settings.ref_link:
            text = CONFIG_ERROR_TEXT.get(lang, CONFIG_ERROR_TEXT["en"])
            await bot.send_message(chat_id, text)
            return

        text = REGISTRATION_TEXT.get(lang, REGISTRATION_TEXT["en"])
        markup = _registration_markup(lang, settings.ref_link)
        img_path = _get_image_path(lang, "registration")
        if img_path:
            await bot.send_photo(
                chat_id,
                photo=FSInputFile(str(img_path)),
                caption=text,
                reply_markup=markup,
            )
        else:
            await bot.send_message(chat_id, text, reply_markup=markup)
        return

    # 3. депозит (если включён)
    required_dep = float(settings.deposit_required_amount or 0)
    need_deposit = bool(settings.require_deposit)

    total_deposit = await _get_total_deposit(user.id)

    if need_deposit:
        if required_dep <= 0:
            text = CONFIG_ERROR_TEXT.get(lang, CONFIG_ERROR_TEXT["en"])
            await bot.send_message(chat_id, text)
            return

        if total_deposit < required_dep:
            if not settings.deposit_link:
                text = CONFIG_ERROR_TEXT.get(lang, CONFIG_ERROR_TEXT["en"])
                await bot.send_message(chat_id, text)
                return

            text_tpl = DEPOSIT_TEXT.get(lang, DEPOSIT_TEXT["en"])
            text = text_tpl.format(required=required_dep, current=total_deposit)
            markup = _deposit_markup(lang, settings.deposit_link)
            img_path = _get_image_path(lang, "deposit")
            if img_path:
                await bot.send_photo(
                    chat_id,
                    photo=FSInputFile(str(img_path)),
                    caption=text,
                    reply_markup=markup,
                )
            else:
                await bot.send_message(chat_id, text, reply_markup=markup)
            return

    # 4. все шаги пройдены → открываем доступ (+ проверяем VIP по сумме депозитов)
    vip_thr = float(settings.vip_threshold_amount or 0)
    is_vip_now = user.is_vip or (vip_thr > 0 and total_deposit >= vip_thr)

    if db.async_session_maker is not None:
        async with db.async_session_maker() as session:
            db_user = await session.get(User, user.id)
            if db_user:
                db_user.has_basic_access = True
                if is_vip_now:
                    db_user.is_vip = True
            await session.commit()
        user.has_basic_access = True
        if is_vip_now:
            user.is_vip = True

    text = ACCESS_OPEN_TEXT.get(lang, ACCESS_OPEN_TEXT["en"])
    if is_vip_now:
        vip_extra = VIP_GRANTED_TEXT.get(lang, VIP_GRANTED_TEXT["en"])
        text = f"{text}\n\n{vip_extra}"

    markup = _access_opened_markup(lang, user)
    img_path = _get_image_path(lang, "access_opened")
    if img_path:
        await bot.send_photo(
            chat_id,
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await bot.send_message(chat_id, text, reply_markup=markup)


# =====================================================================
# ОБРАБОТЧИКИ КНОПОК МЕНЮ
# =====================================================================

@router.callback_query(F.data == "menu:instruction")
async def handle_instruction(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return

    chat_id = callback.message.chat.id
    tg_id = callback.from_user.id

    try:
        await callback.message.delete()
    except Exception:
        pass

    lang = await _get_user_lang(tg_id)
    text = INSTRUCTION_TEXT.get(lang, INSTRUCTION_TEXT["en"])
    markup = _back_markup(lang)
    img_path = _get_image_path(lang, "instruction")

    if img_path:
        await callback.message.bot.send_photo(
            chat_id,
            photo=FSInputFile(str(img_path)),
            caption=text,
            reply_markup=markup,
        )
    else:
        await callback.message.bot.send_message(
            chat_id,
            text,
            reply_markup=markup,
        )


@router.callback_query(F.data == "menu:get_signal")
async def handle_get_signal(callback: CallbackQuery) -> None:
    """
    Эта ветка срабатывает только когда у юзера ЕЩЁ НЕТ доступа.
    Потом, когда доступ открыт, кнопка в меню становится WebApp — сюда уже не попадём.
    """
    await callback.answer()
    if not callback.message:
        return

    chat_id = callback.message.chat.id
    tg_id = callback.from_user.id

    try:
        await callback.message.delete()
    except Exception:
        pass

    await _run_flow(callback.message.bot, chat_id, tg_id)


@router.callback_query(F.data == "menu:change_language")
async def handle_change_language(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return

    tg_id = callback.from_user.id
    lang = await _get_user_lang(tg_id)

    try:
        await callback.message.delete()
    except Exception:
        pass

    await send_language_choice(callback.message, lang=lang)


@router.callback_query(F.data == "menu:back_to_menu")
async def handle_back_to_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if not callback.message:
        return

    tg_id = callback.from_user.id
    lang = await _get_user_lang(tg_id)

    try:
        await callback.message.delete()
    except Exception:
        pass

    user = await _get_or_create_user(
        tg_id,
        callback.from_user.username if callback.from_user else None,
    )
    await send_main_menu(callback.message, lang, user=user)


@router.callback_query(F.data == "menu:support_empty")
async def handle_support_empty(callback: CallbackQuery) -> None:
    await callback.answer("Ссылка поддержки не настроена.", show_alert=True)


# =====================================================================
# АВТОПУШ ПОСЛЕ ПОДПИСКИ НА КАНАЛ
# =====================================================================

@router.chat_member()
async def handle_channel_subscription(event: ChatMemberUpdated, bot: Bot) -> None:
    try:
        settings = await _get_settings()
    except Exception:
        return

    if not settings.require_subscription or not settings.channel_id:
        return

    target = settings.channel_id.strip()
    chat = event.chat

    is_our_chat = False
    if target.startswith("@"):
        if chat.username and chat.username.lower() == target.lstrip("@").lower():
            is_our_chat = True
    else:
        try:
            target_id = int(target)
        except ValueError:
            return
        if chat.id == target_id:
            is_our_chat = True

    if not is_our_chat:
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status

    was_outside = old_status in ("left", "kicked")
    is_member = new_status in ("member", "administrator", "creator")

    if not (was_outside and is_member):
        return

    tg_id = event.new_chat_member.user.id

    if db.async_session_maker is not None:
        async with db.async_session_maker() as session:
            result = await session.execute(
                select(User).where(User.telegram_id == tg_id)
            )
            user: Optional[User] = result.scalar_one_or_none()
            if user:
                user.is_subscribed = True
                await session.commit()

    await run_access_flow_for_user(bot, tg_id)