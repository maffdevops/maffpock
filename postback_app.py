# postback_app.py

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import PlainTextResponse

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from sqlalchemy import select, func

from bot.models import base as db
from bot.models.user import User
from bot.models.deposit import Deposit
from bot.models.settings import Settings
from bot.handlers.main_menu import (
    run_access_flow_for_user,
    notify_vip_granted,
)

# -------------------------------------------------
# Логгер
# -------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("postbacks")

# -------------------------------------------------
# Конфиг и глобальные объекты
# -------------------------------------------------

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

POSTBACK_SECRET = os.getenv("BROKER_POSTBACK_SECRET") or ""

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))

app = FastAPI(title="Jogoto postbacks")


# -------------------------------------------------
# Вспомогательные функции
# -------------------------------------------------

async def check_secret(request: Request) -> None:
    """
    Если BROKER_POSTBACK_SECRET задан, проверяем его либо в query ?secret=,
    либо в заголовке X-Postback-Secret. Если не задан — ничего не проверяем.
    """
    if not POSTBACK_SECRET:
        return

    q_secret = request.query_params.get("secret")
    h_secret = request.headers.get("X-Postback-Secret")

    if q_secret != POSTBACK_SECRET and h_secret != POSTBACK_SECRET:
        logger.warning("Postback rejected: invalid secret")
        raise HTTPException(status_code=403, detail="Forbidden")


async def get_or_create_settings() -> Settings:
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


async def send_postback_to_group(
    kind: str,
    trader_id: str,
    tg_id: int,
    amount: Optional[float] = None,
) -> None:
    """
    kind: 'registration' | 'deposit' | 'withdraw'
    """
    try:
        settings = await get_or_create_settings()
    except Exception as e:
        logger.error("Failed to load Settings for group postback: %s", e)
        return

    chat_id = settings.postbacks_chat_id
    if not chat_id:
        return

    if kind == "registration" and not settings.send_postbacks_registration:
        return
    if kind == "deposit" and not settings.send_postbacks_deposit:
        return
    if kind == "withdraw" and not settings.send_postbacks_withdraw:
        return

    if kind == "registration":
        text = (
            "📝 <b>Регистрация</b>\n"
            f"trader_id: <code>{trader_id}</code>\n"
            f"tg_id: <code>{tg_id}</code>\n"
        )
    elif kind == "deposit":
        text = (
            "💰 <b>Депозит</b>\n"
            f"trader_id: <code>{trader_id}</code>\n"
            f"tg_id: <code>{tg_id}</code>\n"
            f"sumdep: <b>{amount:.2f}$</b>\n"
        )
    else:  # withdraw
        text = (
            "💸 <b>Вывод средств</b>\n"
            f"trader_id: <code>{trader_id}</code>\n"
            f"tg_id: <code>{tg_id}</code>\n"
            f"wdr_sum: <b>{amount:.2f}$</b>\n"
        )

    try:
        await bot.send_message(chat_id, text)
    except Exception as e:
        logger.error("Failed to send postback to group: %s", e)


# -------------------------------------------------
# Startup
# -------------------------------------------------

@app.on_event("startup")
async def on_startup() -> None:
    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    logger.info("Initializing DB for postback app, url=%s", db_url)
    db.setup_db(db_url)
    await db.init_db()
    logger.info("Postback app startup complete")


# -------------------------------------------------
# Healthcheck
# -------------------------------------------------

@app.get("/", response_class=PlainTextResponse)
async def root() -> str:
    return '{"status":"ok","service":"postbacks"}'


# -------------------------------------------------
# /postback/registration
# -------------------------------------------------

@app.get("/postback/registration")
@app.post("/postback/registration")
async def postback_registration(
    request: Request,
    trader_id: str,
    click_id: str,
):
    """
    Регистрация:
    trader_id={{trader_id}}
    click_id={{click_id}}  (tg id)
    """
    await check_secret(request)

    logger.info(
        "POSTBACK registration: trader_id=%s click_id=%s from %s",
        trader_id,
        click_id,
        request.client.host if request.client else "unknown",
    )

    try:
        tg_id = int(click_id)
    except ValueError:
        logger.warning("Invalid click_id for registration: %s", click_id)
        raise HTTPException(status_code=400, detail="Bad click_id")

    if db.async_session_maker is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    async with db.async_session_maker() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user: Optional[User] = result.scalar_one_or_none()

        if user is None:
            # Пользователь ещё не запускал бота, но партнёрка шлёт постбэки.
            # Всё равно создаём запись — пригодится для статистики.
            user = User(telegram_id=tg_id)
            session.add(user)

        user.trader_id = trader_id
        user.is_registered = True

        await session.commit()

    # автопуш следующего шага / доступа
    try:
        await run_access_flow_for_user(bot, tg_id)
    except Exception as e:
        logger.error("run_access_flow_for_user error after registration: %s", e)

    # отстук в группу (если включено)
    await send_postback_to_group("registration", trader_id, tg_id)

    return PlainTextResponse("OK")


# -------------------------------------------------
# /postback/first_deposit и /postback/redeposit
# -------------------------------------------------

async def _handle_deposit_common(
    request: Request,
    trader_id: str,
    click_id: str,
    sumdep: float,
    event_name: str,
):
    await check_secret(request)

    logger.info(
        "POSTBACK %s: trader_id=%s click_id=%s sumdep=%s from %s",
        event_name,
        trader_id,
        click_id,
        sumdep,
        request.client.host if request.client else "unknown",
    )

    try:
        tg_id = int(click_id)
    except ValueError:
        logger.warning("Invalid click_id for %s: %s", event_name, click_id)
        raise HTTPException(status_code=400, detail="Bad click_id")

    if db.async_session_maker is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    became_vip = False

    async with db.async_session_maker() as session:
        # находим / создаём пользователя
        result = await session.execute(
            select(User).where(User.telegram_id == tg_id)
        )
        user: Optional[User] = result.scalar_one_or_none()
        if user is None:
            user = User(telegram_id=tg_id)
            session.add(user)

        if trader_id and not user.trader_id:
            user.trader_id = trader_id

        # пишем депозит
        dep = Deposit(user_id=user.id, amount=float(sumdep))
        session.add(dep)

        # считаем сумму всех депозитов
        total_dep = await session.scalar(
            select(func.coalesce(func.sum(Deposit.amount), 0.0)).where(
                Deposit.user_id == user.id
            )
        )
        total_dep = float(total_dep or 0.0)

        # получаем настройки (в этой же сессии)
        settings = await session.get(Settings, 1)
        if settings is None:
            settings = Settings(id=1)
            session.add(settings)

        vip_threshold = float(settings.vip_threshold_amount or 0.0)

        if vip_threshold > 0 and total_dep >= vip_threshold and not user.is_vip:
            user.is_vip = True
            became_vip = True

        await session.commit()

    # автопуш следующего шага / доступа
    try:
        await run_access_flow_for_user(bot, tg_id)
    except Exception as e:
        logger.error("run_access_flow_for_user error after deposit: %s", e)

    # если новый VIP — отдельное уведомление
    if became_vip:
        try:
            await notify_vip_granted(bot, tg_id)
        except Exception as e:
            logger.error("notify_vip_granted error: %s", e)

    # отстук в группу
    await send_postback_to_group("deposit", trader_id, tg_id, amount=float(sumdep))

    return PlainTextResponse("OK")


@app.get("/postback/first_deposit")
@app.post("/postback/first_deposit")
async def postback_first_deposit(
    request: Request,
    trader_id: str,
    click_id: str,
    sumdep: float,
):
    """
    Первый депозит (FTD):
    trader_id={{trader_id}}&click_id={{click_id}}&sumdep={{sumdep}}
    """
    return await _handle_deposit_common(
        request=request,
        trader_id=trader_id,
        click_id=click_id,
        sumdep=sumdep,
        event_name="first_deposit",
    )


@app.get("/postback/redeposit")
@app.post("/postback/redeposit")
async def postback_redeposit(
    request: Request,
    trader_id: str,
    click_id: str,
    sumdep: float,
):
    """
    Повторный депозит:
    trader_id={{trader_id}}&click_id={{click_id}}&sumdep={{sumdep}}
    """
    return await _handle_deposit_common(
        request=request,
        trader_id=trader_id,
        click_id=click_id,
        sumdep=sumdep,
        event_name="redeposit",
    )


# -------------------------------------------------
# /postback/withdraw
# -------------------------------------------------

@app.get("/postback/withdraw")
@app.post("/postback/withdraw")
async def postback_withdraw(
    request: Request,
    trader_id: str,
    click_id: str,
    wdr_sum: float,
):
    """
    Вывод средств:
    trader_id={{trader_id}}&click_id={{click_id}}&wdr_sum={{wdr_sum}}
    Сейчас мы не пишем выводы в БД, только отстук в группу.
    """
    await check_secret(request)

    logger.info(
        "POSTBACK withdraw: trader_id=%s click_id=%s wdr_sum=%s from %s",
        trader_id,
        click_id,
        wdr_sum,
        request.client.host if request.client else "unknown",
    )

    try:
        tg_id = int(click_id)
    except ValueError:
        logger.warning("Invalid click_id for withdraw: %s", click_id)
        raise HTTPException(status_code=400, detail="Bad click_id")

    await send_postback_to_group("withdraw", trader_id, tg_id, amount=float(wdr_sum))

    return PlainTextResponse("OK")