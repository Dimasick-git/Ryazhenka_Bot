"""Entry point for Ryazhenka Bot."""
import asyncio
import logging
import os
import re
import sys

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramUnauthorizedError
from aiohttp import web

from bot import storage
from bot.config import ADMIN_IDS, BOT_TOKEN, SYNC_INTERVAL_SECONDS
from bot.handlers import admin_router, callbacks_router, inline_router, user_router
from bot.nlp import invalidate_index
from bot.services.sync import resolve_auto_guides_links, sync_sources


async def _health_server() -> None:
    async def handle_health(request):
        return web.Response(text="ok")

    async def handle_yt_latest(request):
        try:
            items = [
                (cat, title, url)
                for cat, entries in storage.GUIDES.items()
                if cat.startswith("YouTube -")
                for title, url in entries.items()
            ]
            items.sort(
                key=lambda x: re.match(r"\[(\d{4}-\d{2}-\d{2})\]", x[1]).group(1)
                if re.match(r"\[(\d{4}-\d{2}-\d{2})\]", x[1]) else "1970-01-01",
                reverse=True,
            )
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

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
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(callbacks_router)
    dp.include_router(inline_router)

    total = sum(len(g) for g in storage.GUIDES.values())
    logging.info("Loaded %d categories, %d guides total", len(storage.GUIDES), total)

    async def _notify_admins(text: str) -> None:
        for aid in ADMIN_IDS:
            try:
                await bot.send_message(aid, text)
            except Exception:
                pass

    async def background_sync() -> None:
        await asyncio.sleep(5)
        consecutive_failures = 0
        while True:
            try:
                summary = await sync_sources()
                invalidate_index()
                logging.info("Background sync: %s", summary)
                if consecutive_failures > 0:
                    consecutive_failures = 0
                    await _notify_admins("✅ Синхронизация восстановлена.")
            except Exception as e:
                consecutive_failures += 1
                logging.exception("Background sync failed")
                # Уведомляем при первой ошибке и каждые 5 последующих
                if consecutive_failures == 1 or consecutive_failures % 5 == 0:
                    await _notify_admins(
                        f"⚠️ Ошибка фоновой синхронизации (попытка {consecutive_failures}): {e}"
                    )
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)

    async def background_resolver() -> None:
        await asyncio.sleep(10)
        while True:
            try:
                await resolve_auto_guides_links(bot)
            except Exception:
                logging.exception("Background resolver failed")
            await asyncio.sleep(max(600, SYNC_INTERVAL_SECONDS))

    # Background sync -- только если есть источники для синхронизации.
    # Health server уже стартовал в начале main(), не дублируем.
    if (storage.YT_CHANNELS and any(storage.YT_CHANNELS)) or os.environ.get("GITHUB_REPO"):
        asyncio.create_task(background_sync())

    asyncio.create_task(background_resolver())

    # Railway rolling-deploy: новый контейнер стартует ДО того как
    # старый полностью отключился. Оба полят getUpdates -> Telegram
    # отвечает "Conflict: terminated by other getUpdates request".
    # Ждём 15с (Telegram long-poll timeout 25-30с) -- к этому моменту
    # любой in-flight getUpdates от старого контейнера истечёт по timeout'у,
    # либо SIGTERM убьёт его.
    startup_delay = int(os.environ.get("STARTUP_DELAY_SECONDS", "15"))
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
        logging.info("Bot session closed cleanly")


if __name__ == "__main__":
    asyncio.run(main())
