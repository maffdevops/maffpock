import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()


@dataclass
class BotConfig:
    token: str
    default_language: str = "en"


@dataclass
class DatabaseConfig:
    url: str


@dataclass
class AppConfig:
    bot: BotConfig
    db: DatabaseConfig


def load_config() -> AppConfig:
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("BOT_TOKEN is not set in environment or .env file")

    db_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")

    return AppConfig(
        bot=BotConfig(token=bot_token),
        db=DatabaseConfig(url=db_url),
    )