import os
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties

from bot.config import load_config
from bot.models import base as db
from bot.models.user import User
from bot.models.deposit import Deposit
from bot.models.settings import Settings
from bot.handlers.main_menu import run_access_flow_for_user

app = FastAPI(title="Jogoto Postbacks")

# ===== ENV =====

BOT_TOKEN = os.getenv("BOT_TOKEN") or ""
BROKER_POSTBACK_SECRET = os.getenv("BROKER_POSTBACK_SECRET") or ""

bot: Optional[Bot] = None


# ===== HELPERS =====

def _check_secret(secret: Optional[str]) -> bool:
    """
    Если BROKER_POSTBACK_SECRET пустой – проверка отключена.
    Если задан – партнёрка должна передавать ?secret=... в запросе.
    """
    if not BROKER_POSTBACK_SECRET:
        return True
    return secret == BROKER_POSTBACK_SECRET


async def _get_or_create_settings(session) -> Settings:
    result = await session.execute(select(Settings).where(Settings.id == 1))
    settings: Optional[Settings] = result.scalar_one_or_none()
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    return settings


async def _find_user_by_click_id(session, click_id: str) -> Optional[User]:
    """
    click_id = tg id (строка). Если не кастится к int – юзера не найдём.
    """
    try:
        tg_id = int(click_id)
    except (TypeError, ValueError):
        return None

    result = await session.execute(select(User).where(User.telegram_id == tg_id))
    return result.scalar_one_or_none()


async def _send_postback_message_to_group(
    text: str,
    event: Optional[str] = None,  # "registration" | "deposit" | "withdraw"
) -> None:
    """
    Отправка уведомления в чат постбэков с учётом флагов settings.send_postbacks_*.
    """
    if bot is None:
        return

    if db.async_session_maker is None:
        return

    async with db.async_session_maker() as session:
        settings = await _get_or_create_settings(session)

        chat_id = settings.postbacks_chat_id
        if not chat_id:
            return

        # уважаем флаги
        if event == "registration" and not settings.send_postbacks_registration:
            return
        if event == "deposit" and not settings.send_postbacks_deposit:
            return
        if event == "withdraw" and not settings.send_postbacks_withdraw:
            return

    try:
        await bot.send_message(chat_id=chat_id, text=text)
    except Exception:
        # не роняем приложение из-за ошибки отправки
        pass


# ===== FASTAPI LIFECYCLE =====

@app.on_event("startup")
async def on_startup() -> None:
    global bot

    # грузим конфиг так же, как бот
    config = load_config()

    # инициализируем БД
    db.setup_db(config.db.url)
    await db.init_db()

    # поднимаем aiogram-бота для уведомлений
    if BOT_TOKEN:
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode="HTML"),
        )


@app.on_event("shutdown")
async def on_shutdown() -> None:
    global bot
    if bot:
        await bot.session.close()
        bot = None


# ===== HEALTHCHECK =====

@app.get("/")
async def root():
    return {"status": "ok", "service": "postbacks"}


# ===== POSTBACK ENDPOINTS =====
#   /postback/registration
#   /postback/first_deposit
#   /postback/redeposit
#   /postback/withdraw
# Макросы:
#   trader_id, click_id (tg id), sumdep, wdr_sum, + secret (если нужен)
# ================================

@app.get("/postback/registration")
async def postback_registration(
    trader_id: str = Query(...),
    click_id: str = Query(...),
    secret: Optional[str] = Query(None),
):
    if not _check_secret(secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    if db.async_session_maker is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    async with db.async_session_maker() as session:
        user = await _find_user_by_click_id(session, click_id)

        if user is None:
            await _send_postback_message_to_group(
                text=(
                    "⚠️ Регистрация без найденного пользователя в БД\n"
                    f"trader_id: <code>{trader_id}</code>\n"
                    f"click_id (tg id): <code>{click_id}</code>"
                ),
                event="registration",
            )
            return JSONResponse(
                {"status": "no_user", "trader_id": trader_id, "click_id": click_id}
            )

        user.trader_id = trader_id
        user.is_registered = True
        await session.commit()

        await _send_postback_message_to_group(
            text=(
                "🟢 <b>Регистрация</b>\n"
                f"trader_id: <code>{trader_id}</code>\n"
                f"tg id: <code>{click_id}</code>"
            ),
            event="registration",
        )

        try:
            if bot is not None:
                await run_access_flow_for_user(bot, user.telegram_id)
        except Exception:
            pass

    return {"status": "ok"}


@app.get("/postback/first_deposit")
async def postback_first_deposit(
    trader_id: str = Query(...),
    click_id: str = Query(...),
    sumdep: float = Query(...),
    secret: Optional[str] = Query(None),
):
    return await _handle_deposit_postback(
        kind="FTD", trader_id=trader_id, click_id=click_id, amount=sumdep, secret=secret
    )


@app.get("/postback/redeposit")
async def postback_redeposit(
    trader_id: str = Query(...),
    click_id: str = Query(...),
    sumdep: float = Query(...),
    secret: Optional[str] = Query(None),
):
    return await _handle_deposit_postback(
        kind="REDEP",
        trader_id=trader_id,
        click_id=click_id,
        amount=sumdep,
        secret=secret,
    )


async def _handle_deposit_postback(
    kind: str,
    trader_id: str,
    click_id: str,
    amount: float,
    secret: Optional[str],
):
    if not _check_secret(secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    if db.async_session_maker is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    async with db.async_session_maker() as session:
        user = await _find_user_by_click_id(session, click_id)
        if user is None:
            await _send_postback_message_to_group(
                text=(
                    f"⚠️ Депозит ({kind}) без найденного пользователя в БД\n"
                    f"trader_id: <code>{trader_id}</code>\n"
                    f"click_id (tg id): <code>{click_id}</code>\n"
                    f"sumdep: <b>{amount:.2f}$</b>"
                ),
                event="deposit",
            )
            return JSONResponse(
                {
                    "status": "no_user",
                    "kind": kind,
                    "trader_id": trader_id,
                    "click_id": click_id,
                    "amount": amount,
                }
            )

        dep = Deposit(user_id=user.id, amount=float(amount))
        session.add(dep)
        await session.commit()

        await _send_postback_message_to_group(
            text=(
                f"💰 <b>Депозит ({kind})</b>\n"
                f"trader_id: <code>{trader_id}</code>\n"
                f"tg id: <code>{click_id}</code>\n"
                f"Сумма: <b>{amount:.2f}$</b>"
            ),
            event="deposit",
        )

        try:
            if bot is not None:
                await run_access_flow_for_user(bot, user.telegram_id)
        except Exception:
            pass

    return {
        "status": "ok",
        "kind": kind,
        "trader_id": trader_id,
        "click_id": click_id,
        "amount": amount,
    }


@app.get("/postback/withdraw")
async def postback_withdraw(
    trader_id: str = Query(...),
    click_id: str = Query(...),
    wdr_sum: float = Query(...),
    secret: Optional[str] = Query(None),
):
    if not _check_secret(secret):
        raise HTTPException(status_code=403, detail="Invalid secret")

    await _send_postback_message_to_group(
        text=(
            "📤 <b>Вывод средств</b>\n"
            f"trader_id: <code>{trader_id}</code>\n"
            f"tg id: <code>{click_id}</code>\n"
            f"Сумма: <b>{wdr_sum:.2f}$</b>"
        ),
        event="withdraw",
    )

    return {
        "status": "ok",
        "trader_id": trader_id,
        "click_id": click_id,
        "wdr_sum": wdr_sum,
    }