# Telegram_bot_FreeDeepseekAPI — Telegram-бот на DeepSeek (FreeDeepseekAPI)

Телеграм-бот на **aiogram 3**, который работает как нейросеть: подключается к
локальному прокси [FreeDeepseekAPI](https://github.com/ForgetMeAI/FreeDeepseekAPI) по OpenAI-совместимому
эндпоинту `POST /v1/chat/completions` и стримит ответ в чат.

## Возможности

- **Отдельный чат для каждого пользователя** — локальная история по `user_id`
  плюс session key `user: "tg-<id>"` в запросе (по документации сервера §4.1
  у каждого ключа свой чат в DeepSeek);
- стриминг ответа с редактированием сообщения в реальном времени;
- сброс диалога командой `/new` (чистит локальную историю и вызывает
  `POST /reset-session`);
- работа с фото (загружается base64 data-URL, лимит 7 МБ);
- автоматические повторы ошибок сервера выводятся пользователю;
- все секреты — в `.env`.

## Установка

```bash
pip install -r requirements.txt
```

## Настройка `.env`

Скопируй `.env.example` → `.env` и заполни:

| Переменная | Назначение |
| --- | --- |
| `BOT_TOKEN` | токен бота от @BotFather |
| `API_BASE_URL` | адрес FreeDeepseekAPI (по умолчанию `http://127.0.0.1:9655`) |
| `API_KEY` | `PROXY_API_KEY` сервера; пусто, если сервер без ключа |
| `MODEL` | алиас модели: `deepseek-chat`, `deepseek-reasoner`, `deepseek-chat-search`, `deepseek-reasoner-search` |
| `SYSTEM_PROMPT` | системный промпт бота |
| `MAX_HISTORY` | сколько сообщений истории держать на пользователя |
| `STREAM` | `1` — стриминг, `0` — обычный запрос |
| `REQUEST_TIMEOUT` | таймаут запроса к серверу, сек |
| `EDIT_INTERVAL` | как часто обновлять сообщение при стриминге, сек |
| `IMAGE_MAX_MB` | лимит размера фото, МБ |

## Запуск

```bash
# 1. Сначала подними сервер FreeDeepseekAPI (в его папке):
npm start

# 2. Затем бота:
python bot.py
```

## Команды бота

| Команда | Описание |
| --- | --- |
| `/start` | приветствие |
| `/help` | справка |
| `/new` | новый диалог (сброс контекста) |

## Структура

```
ai_bot/
├── bot.py           # aiogram-бот: хендлеры, стриминг в чат
├── deepseek.py      # HTTP-клиент FreeDeepseekAPI (stream/complete/reset)
├── config.py        # чтение настроек из .env
├── .env             # твои секреты (не коммитить)
└── requirements.txt
```
