"""Конфигурация бота: все настройки читаются из .env."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import find_dotenv, load_dotenv

if find_dotenv() is None:
    raise FileNotFoundError("Файл .env не найден рядом с ботом")

load_dotenv()


def _get(name: str, default: str = "", *, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and not value:
        raise RuntimeError(f"Переменная {name} не задана в .env")
    return value


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Переменная {name} должна быть числом, получено: {raw!r}") from exc


def _get_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"Переменная {name} должна быть числом, получено: {raw!r}") from exc


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "1" if default else "0").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # Telegram
    bot_token: str
    # FreeDeepseekAPI
    api_base_url: str
    api_key: str
    model: str
    # Поведение
    system_prompt: str
    max_history: int
    stream: bool
    request_timeout: float
    edit_interval: float
    image_max_bytes: int

    @property
    def chat_url(self) -> str:
        return self.api_base_url.rstrip("/") + "/v1/chat/completions"

    @property
    def reset_url(self) -> str:
        return self.api_base_url.rstrip("/") + "/reset-session"


settings = Settings(
    bot_token=_get("BOT_TOKEN", required=True),
    api_base_url=_get("API_BASE_URL", "http://127.0.0.1:9655"),
    api_key=_get("API_KEY"),
    model=_get("MODEL", "deepseek-chat"),
    system_prompt=_get("SYSTEM_PROMPT", "Ты — полезный ассистент."),
    max_history=_get_int("MAX_HISTORY", 40),
    stream=_get_bool("STREAM", True),
    request_timeout=_get_float("REQUEST_TIMEOUT", 180.0),
    edit_interval=_get_float("EDIT_INTERVAL", 1.5),
    image_max_bytes=_get_int("IMAGE_MAX_MB", 7) * 1024 * 1024,
)
