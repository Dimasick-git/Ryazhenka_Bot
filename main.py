"""Entry point for Ryazhenka Bot."""
import asyncio
import logging
import os

from aiogram import Bot, Dispatcher
from aiohttp import web

from bot import storage
from bot.config import BOT_TOKEN, SYNC_INTERVAL_SECONDS
from bot.handlers import admin_router, callbacks_router, inline_router, user_router
from bot.nlp import invalidate_index
from bot.services.sync import resolve_auto_guides_links, sync_sources


async def _health_server() -> None:
    async def handle_health(request):
        return web.Response(text="ok")

    async def handle_yt_latest(request):
        import re
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

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Check your .env or environment variables.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(callbacks_router)
    dp.include_router(inline_router)

    total = sum(len(g) for g in storage.GUIDES.values())
    logging.info("Loaded %d categories, %d guides total", len(storage.GUIDES), total)

    async def background_sync() -> None:
        await asyncio.sleep(5)
        while True:
            try:
                summary = await sync_sources()
                invalidate_index()
                logging.info("Background sync: %s", summary)
            except Exception:
                logging.exception("Background sync failed")
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)

    async def background_resolver() -> None:
        await asyncio.sleep(10)
        while True:
            try:
                await resolve_auto_guides_links(bot)
            except Exception:
                logging.exception("Background resolver failed")
            await asyncio.sleep(max(600, SYNC_INTERVAL_SECONDS))

    if (storage.YT_CHANNELS and any(storage.YT_CHANNELS)) or os.environ.get("GITHUB_REPO"):
        asyncio.create_task(background_sync())
        asyncio.create_task(_health_server())

    asyncio.create_task(background_resolver())

    try:
        info = await bot.get_webhook_info()
        logging.info("Webhook info at startup: %s", info)
    except Exception as e:
        logging.warning("Could not fetch webhook info: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        logging.exception("Failed to delete webhook (may be none)")

    logging.info("Starting polling...")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
