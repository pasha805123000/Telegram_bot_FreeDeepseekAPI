"""Клиент FreeDeepseekAPI (OpenAI-совместимый /v1/chat/completions).

Каждому пользователю Telegram соответствует свой session key (`user` в теле
запроса) — по документации сервера это ключ сессии, и у каждого ключа свой
отдельный чат в DeepSeek.
"""

from __future__ import annotations

import json
from typing import AsyncIterator

import httpx

from config import settings


class DeepSeekError(Exception):
    """Ошибка ответа FreeDeepseekAPI."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if settings.api_key:
        headers["Authorization"] = f"Bearer {settings.api_key}"
    return headers


def _payload(user_key: str, messages: list[dict], stream: bool) -> dict:
    return {
        "model": settings.model,
        "messages": messages,
        "stream": stream,
        "user": user_key,  # session key -> отдельный чат на пользователя
    }


def _extract_error(body: bytes, status: int) -> str:
    try:
        data = json.loads(body)
        err = data.get("error")
        if isinstance(err, dict):
            message = err.get("message") or err.get("type")
            if message:
                return f"HTTP {status}: {message}"
        if isinstance(err, str):
            return f"HTTP {status}: {err}"
        return f"HTTP {status}: {data}"
    except (json.JSONDecodeError, UnicodeDecodeError):
        text = body.decode(errors="replace")[:500]
        return f"HTTP {status}: {text or 'пустой ответ сервера'}"


async def stream_chat(
    user_key: str, messages: list[dict]
) -> AsyncIterator[str]:
    """Стриминг ответа модели. Отдаёт кусочки текста по мере генерации."""
    timeout = httpx.Timeout(settings.request_timeout, read=settings.request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST",
            settings.chat_url,
            json=_payload(user_key, messages, stream=True),
            headers=_headers(),
        ) as response:
            if response.status_code != 200:
                body = await response.aread()
                raise DeepSeekError(_extract_error(body, response.status_code), response.status_code)

            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue  # ": keep-alive" комментарии
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue

                if isinstance(event, dict) and "error" in event:
                    err = event["error"]
                    message = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    raise DeepSeekError(message)

                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if content:
                    yield content


async def complete(user_key: str, messages: list[dict]) -> str:
    """Обычный (не-стриминговый) запрос, используется как fallback."""
    timeout = httpx.Timeout(settings.request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            settings.chat_url,
            json=_payload(user_key, messages, stream=False),
            headers=_headers(),
        )
    if response.status_code != 200:
        raise DeepSeekError(
            _extract_error(response.content, response.status_code),
            response.status_code,
        )
    data = response.json()
    choices = data.get("choices") or []
    if not choices:
        raise DeepSeekError("Сервер вернул ответ без содержимого", 502)
    content = (choices[0].get("message") or {}).get("content")
    if not content:
        raise DeepSeekError("Модель вернула пустой ответ", 502)
    return content


async def reset_session(user_key: str) -> None:
    """Сброс удалённого чата на сервере (POST /reset-session?agent=<key>)."""
    timeout = httpx.Timeout(30.0)
    params = {"agent": user_key}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            await client.post(
                settings.reset_url, params=params, headers=_headers()
            )
    except httpx.HTTPError:
        # Локальная история всё равно очищается — сбой сервера не критичен
        pass
