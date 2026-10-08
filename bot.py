"""Telegram-бот на aiogram 3, подключённый к FreeDeepseekAPI.

У каждого пользователя — свой отдельный чат:
  * локальная история сообщений хранится по user_id;
  * в запрос к серверу передаётся session key `user` (см. deepseek.py),
    поэтому у DeepSeek тоже свой чат на каждого пользователя.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatAction, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

import deepseek
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")

# Без глобального parse_mode: ответы модели отправляются как обычный текст,
# HTML применяется только к статическим сообщениям бота.
bot = Bot(token=settings.bot_token)
dp = Dispatcher()
router = Router(name="main")
dp.include_router(router)

# --- Состояние по пользователям -------------------------------------------

history: dict[int, list[dict]] = defaultdict(list)
locks: dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

WELCOME = (
    "👋 Привет! Я бот на базе <b>DeepSeek</b>.\n\n"
    "Просто напиши сообщение — и я отвечу.\n"
    "Фото тоже можно присылать (модель их разглядит).\n\n"
    "Команды:\n"
    "/new — начать новый диалог (сбросить контекст)\n"
    "/help — справка"
)

HELP = (
    "🧠 <b>Как пользоваться</b>\n\n"
    "• Напиши любое сообщение — бот ответит.\n"
    "• У каждого пользователя свой диалог, контекст сохраняется между сообщениями.\n"
    "• /new — очистить историю и начать диалог заново.\n"
    "• Можно присылать фото — модель работает с картинками.\n"
    "• Модель: <code>{model}</code> на <code>{server}</code>"
)


def session_key(user_id: int) -> str:
    """Ключ сессии: у каждого пользователя свой чат на сервере."""
    return f"tg-{user_id}"


def split_text(text: str, limit: int = 4000) -> list[str]:
    """Режет длинный ответ на части под лимит Telegram (4096)."""
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        parts.append(text)
    return parts or [""]


async def keep_typing(chat_id: int, stop: asyncio.Event) -> None:
    """Показывает «печатает…», пока ждём ответ модели."""
    while not stop.is_set():
        try:
            await bot.send_chat_action(chat_id, ChatAction.TYPING)
        except TelegramAPIError:
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=4.5)
        except asyncio.TimeoutError:
            continue


async def safe_edit(message: Message, text: str) -> None:
    try:
        await message.edit_text(text)
    except TelegramBadRequest as exc:
        if "message is not modified" not in str(exc):
            log.debug("edit failed: %s", exc)


async def deliver(target: Message, full_text: str) -> None:
    """Финальная выдача: редактирует первое сообщение и досылает остаток."""
    parts = split_text(full_text)
    await safe_edit(target, parts[0])
    rest = parts[1:]
    for part in rest:
        try:
            await target.answer(part)
        except TelegramAPIError as exc:
            log.warning("не удалось отправить часть ответа: %s", exc)
            break


def build_messages(user_id: int, new_content) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": settings.system_prompt}]
    messages.extend(history[user_id])
    messages.append({"role": "user", "content": new_content})
    return messages


def trim_history(user_id: int) -> None:
    while len(history[user_id]) > settings.max_history:
        history[user_id].pop(0)


# --- Обработчики ------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME, parse_mode=ParseMode.HTML)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(
        HELP.format(model=settings.model, server=settings.api_base_url),
        parse_mode=ParseMode.HTML,
    )


@router.message(Command("new"))
async def cmd_new(message: Message) -> None:
    user_id = message.from_user.id
    async with locks[user_id]:
        history[user_id].clear()
    await deepseek.reset_session(session_key(user_id))
    await message.answer("🧹 Диалог сброшен. Начинаем заново!")


@router.message(F.photo)
async def on_photo(message: Message) -> None:
    user_id = message.from_user.id
    caption = message.caption or ""

    photo = message.photo[-1]
    if photo.file_size and photo.file_size > settings.image_max_bytes:
        await message.answer("⚠️ Фото слишком большое (лимит — 7 МБ).")
        return

    try:
        file = await bot.get_file(photo.file_id)
        data = await bot.download_file(file.file_path)
        payload = data.read() if data else b""
    except TelegramAPIError as exc:
        await message.answer(f"⚠️ Не удалось получить фото: {exc}")
        return

    if len(payload) > settings.image_max_bytes:
        await message.answer("⚠️ Фото слишком большое (лимит — 7 МБ).")
        return

    b64 = base64.b64encode(payload).decode()
    content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        }
    ]
    content.append({"type": "text", "text": caption or "Опиши, что на этом изображении."})

    await _generate(message, user_id, content, history_text=caption or "(фото)")


@router.message(F.text)
async def on_text(message: Message) -> None:
    text = message.text or ""
    if text.startswith("/"):
        await message.answer("Неизвестная команда. Попробуй /help")
        return
    await _generate(message, message.from_user.id, text, history_text=text)


async def _generate(message: Message, user_id: int, content, history_text: str) -> None:
    async with locks[user_id]:
        messages = build_messages(user_id, content)
        placeholder = await message.answer("⏳ Думаю…")
        stop = asyncio.Event()
        typing_task = asyncio.create_task(keep_typing(message.chat.id, stop))
        acc: list[str] = []
        try:
            if settings.stream:
                last_edit = 0.0
                async for chunk in deepseek.stream_chat(session_key(user_id), messages):
                    acc.append(chunk)
                    now = time.monotonic()
                    if now - last_edit >= settings.edit_interval:
                        await safe_edit(placeholder, "".join(acc) or "…")
                        last_edit = now
                full_text = "".join(acc)
            else:
                full_text = await deepseek.complete(session_key(user_id), messages)

            if not full_text.strip():
                raise deepseek.DeepSeekError("Модель вернула пустой ответ", 502)

            await deliver(placeholder, full_text)
            history[user_id].append({"role": "user", "content": history_text})
            history[user_id].append({"role": "assistant", "content": full_text})
            trim_history(user_id)
        except deepseek.DeepSeekError as exc:
            partial = "".join(acc)
            note = f"⚠️ Ошибка API: {exc}"
            if partial:
                await deliver(placeholder, partial + "\n\n" + note)
            else:
                await safe_edit(placeholder, note)
            log.error("DeepSeek error: %s", exc)
        except Exception:
            partial = "".join(acc)
            note = "⚠️ Что-то пошло не так, попробуйте ещё раз."
            if partial:
                await deliver(placeholder, partial + "\n\n" + note)
            else:
                await safe_edit(placeholder, note)
            log.exception("Ошибка при генерации")
        finally:
            stop.set()
            await typing_task


async def main() -> None:
    log.info("Бот запущен. Модель: %s, сервер: %s", settings.model, settings.api_base_url)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
