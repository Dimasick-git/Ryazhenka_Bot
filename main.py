"""Entry point for Ryazhenka Bot."""
import asyncio
import json as _json
import logging
import os
import re
import sys


class _JsonLogFormatter(logging.Formatter):
    """Emit each log record as a single JSON line for Railway log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            obj["exc"] = self.formatException(record.exc_info)
        if record.stack_info:
            obj["stack"] = self.formatStack(record.stack_info)
        return _json.dumps(obj, ensure_ascii=False)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonLogFormatter())
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers.clear()
    root.addHandler(handler)

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiogram.types import BotCommand
from aiohttp import web

from bot import storage
from bot.config import BOT_TOKEN
from bot.handlers import (
    admin_router,
    callbacks_router,
    discovery_router,
    download_router,
    info_router,
    inline_router,
    quiz_router,
    search_router,
    social_router,
)
from bot.middleware import ThrottlingMiddleware
from bot.nlp import warm_index
from bot.services import ai, github
from bot.services.sync import close_ddg_session
from bot.tasks import start_background_tasks


async def _health_server() -> None:
    async def handle_health(request):
        return web.Response(text="ok")

    def _yt_date_key(item: tuple) -> str:
        m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", item[1])
        return m.group(1) if m else "1970-01-01"

    async def handle_yt_latest(request):
        try:
            items = [
                (cat, title, url)
                for cat, entries in storage.GUIDES.items()
                if cat.startswith("YouTube -")
                for title, url in entries.items()
            ]
            items.sort(key=_yt_date_key, reverse=True)
            html = "<html><body><h1>Latest YouTube videos</h1><ul>"
            for cat, title, url in items[:100]:
                html += f"<li><strong>{cat}</strong>: <a href='{url}'>{title}</a></li>"
            html += "</ul></body></html>"
            return web.Response(text=html, content_type="text/html")
        except Exception:
            return web.Response(text="error", status=500)

    app = web.Application()
    app.router.add_get("/health", handle_health)
    app.router.add_get("/yt_latest", handle_yt_latest)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    try:
        await web.TCPSite(runner, "0.0.0.0", port).start()
        logging.info("Health server on port %d", port)
    except OSError as e:
        logging.warning("Health server failed to bind port %d: %s", port, e)


async def main() -> None:
    _setup_logging()

    # ВАЖНО: health server стартует ПЕРВЫМ, до всех валидаций. Если
    # BOT_TOKEN невалидный -- Railway health check всё равно проходит,
    # контейнер не убивается, юзер видит понятный ERROR в логах и фиксит
    # переменную. Иначе deploy крутится по бесконечному loop'у healthcheck
    # fail -> kill -> restart -> healthcheck fail.
    asyncio.create_task(_health_server())

    if not BOT_TOKEN:
        logging.error(
            "BOT_TOKEN env variable is EMPTY/MISSING. "
            "Fix: Railway -> service -> Variables -> add BOT_TOKEN with "
            "token from @BotFather (формат 123456:AAH...)."
        )
        # Idle loop: health server отвечает, юзер чинит env, делает Restart.
        while True:
            await asyncio.sleep(3600)

    bot = Bot(token=BOT_TOKEN)

    # Early token validation. Раньше 401 от Telegram прилетал глубоко в
    # polling loop'е и spam'ил 200-строчный traceback каждый restart.
    try:
        me = await bot.get_me()
        logging.info("Authenticated as @%s (id=%d)", me.username, me.id)
        await bot.set_my_commands([
            BotCommand(command="guide",     description="Найти гайд (fuzzy + BM25)"),
            BotCommand(command="aiguide",   description="Умный поиск + AI если гайд не найден"),
            BotCommand(command="ask",       description="Задать вопрос AI по Switch CFW"),
            BotCommand(command="ask_reset", description="Сбросить контекст разговора с AI"),
            BotCommand(command="all",       description="Все категории"),
            BotCommand(command="random",    description="Случайный гайд"),
            BotCommand(command="new",       description="Последние добавленные гайды"),
            BotCommand(command="stats",     description="Статистика базы гайдов"),
            BotCommand(command="top",       description="Топ категорий"),
            BotCommand(command="trending",  description="Топ гайдов по оценкам"),
            BotCommand(command="history",   description="История поиска"),
            BotCommand(command="recommend", description="Репозитории автора"),
            BotCommand(command="fav",       description="Избранное"),
            BotCommand(command="feedback",  description="Предложить гайд"),
            BotCommand(command="tip",       description="Случайный совет по Switch CFW"),
            BotCommand(command="quiz",      description="Тест знаний по Switch CFW (30 вопросов)"),
            BotCommand(command="digest",    description="Персональный дайджест гайдов"),
            BotCommand(command="week",      description="Недельная статистика и топ поисков"),
            BotCommand(command="compare",   description="Сравнить два инструмента/CFW"),
            BotCommand(command="releases",   description="Последние релизы Ryazhenka"),
            BotCommand(command="changelog",  description="Свежие коммиты по репозиториям"),
            BotCommand(command="download",   description="Скачать последний релиз Ryazhenka CFW"),
            BotCommand(command="modules",   description="Все модули Ryazhenka с версиями и ссылками"),
            BotCommand(command="help",      description="Список всех команд"),
        ])
        logging.info("Bot commands registered with Telegram")
    except TelegramUnauthorizedError:
        logging.error(
            "BOT_TOKEN is REJECTED by Telegram (401 Unauthorized). "
            "Likely causes: token revoked in BotFather, typo in Railway "
            "Variables, или extra whitespace при paste'е. "
            "Fix: BotFather -> /mybots -> bot -> API Token -> Revoke -> "
            "copy fresh -> Railway Variables -> BOT_TOKEN -> Update."
        )
        await bot.session.close()
        # Не sys.exit -- держим health server живым, чтобы Railway не убил
        # контейнер. Юзер видит ERROR, фиксит token, делает Restart.
        while True:
            await asyncio.sleep(3600)

    dp = Dispatcher()
    throttle = ThrottlingMiddleware()
    dp.message.middleware(throttle)
    dp.inline_query.middleware(throttle)
    dp.include_router(search_router)
    dp.include_router(discovery_router)
    dp.include_router(social_router)
    dp.include_router(info_router)
    dp.include_router(download_router)
    dp.include_router(admin_router)
    dp.include_router(callbacks_router)
    dp.include_router(inline_router)
    dp.include_router(quiz_router)

    total = sum(len(g) for g in storage.GUIDES.values())
    logging.info("Loaded %d categories, %d guides total", len(storage.GUIDES), total)
    await asyncio.to_thread(warm_index)
    logging.info("BM25 index pre-warmed (%d docs)", total)

    # Health server уже стартовал в начале main(), не дублируем.
    start_background_tasks(bot)

    # Railway rolling-deploy: новый контейнер стартует ДО того как
    # старый полностью отключился. Оба полят getUpdates -> Telegram
    # отвечает "Conflict: terminated by other getUpdates request".
    # Ждём 15с (Telegram long-poll timeout 25-30с) -- к этому моменту
    # любой in-flight getUpdates от старого контейнера истечёт по timeout'у,
    # либо SIGTERM убьёт его.
    startup_delay = int(os.environ.get("STARTUP_DELAY_SECONDS", "0"))
    if startup_delay > 0:
        logging.info("Startup delay: %ds (waiting for any previous container to release getUpdates)", startup_delay)
        await asyncio.sleep(startup_delay)

    # Webhook cleanup -- если кто-то выставил, polling работать не будет.
    try:
        info = await bot.get_webhook_info()
        if info.url:
            logging.warning("Webhook detected: %s -- will delete to enable polling", info.url)
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        logging.exception("Failed to clear webhook (may be none)")

    logging.info("Starting polling...")
    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        # Graceful shutdown -- закрываем aiohttp session чтобы SIGTERM от
        # Railway не оставил висящий getUpdates на стороне Telegram'а.
        await bot.session.close()
        await github.close_session()
        await close_ddg_session()
        await ai.close_client()
        logging.info("Bot session closed cleanly")


if __name__ == "__main__":
    asyncio.run(main())
