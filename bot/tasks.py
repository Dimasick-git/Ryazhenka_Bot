"""Background asyncio tasks for Ryazhenka Bot."""
import asyncio
import logging
import os

from aiogram import Bot

from . import storage
from .config import ADMIN_IDS, SYNC_INTERVAL_SECONDS
from .handlers.ctx import _cleanup_dialog_ctx
from .handlers.search import cleanup_stale_ask_history
from .nlp import invalidate_index
from .services.sync import resolve_auto_guides_links, sync_sources


async def _notify_admins(bot: Bot, text: str) -> None:
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, text)
        except Exception:
            logging.warning("Failed to notify admin %d", aid)


async def background_sync(bot: Bot) -> None:
    await asyncio.sleep(5)
    consecutive_failures = 0
    while True:
        try:
            summary = await sync_sources()
            invalidate_index()
            logging.info("Background sync: %s", summary)
            if consecutive_failures > 0:
                consecutive_failures = 0
                await _notify_admins(bot, "✅ Синхронизация восстановлена.")
        except Exception as e:
            consecutive_failures += 1
            logging.exception("Background sync failed")
            # Уведомляем при первой ошибке и каждые 5 последующих
            if consecutive_failures == 1 or consecutive_failures % 5 == 0:
                await _notify_admins(
                    bot,
                    f"⚠️ Ошибка фоновой синхронизации (попытка {consecutive_failures}): {e}"
                )
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)


async def background_resolver(bot: Bot) -> None:
    await asyncio.sleep(10)
    while True:
        try:
            await resolve_auto_guides_links(bot)
        except Exception:
            logging.exception("Background resolver failed")
        await asyncio.sleep(max(600, SYNC_INTERVAL_SECONDS))


async def background_ctx_cleanup() -> None:
    while True:
        await asyncio.sleep(600)
        try:
            _cleanup_dialog_ctx()
        except Exception:
            logging.exception("DIALOG_CTX cleanup failed")


async def background_ask_history_cleanup() -> None:
    """Periodically evict stale /ask conversation histories to prevent unbounded growth."""
    while True:
        await asyncio.sleep(1800)  # every 30 min
        try:
            purged = await asyncio.to_thread(cleanup_stale_ask_history)
            if purged:
                logging.debug("Purged %d stale /ask history entries", purged)
        except Exception:
            logging.exception("ASK history cleanup failed")


def start_background_tasks(bot: Bot) -> None:
    """Schedule all background tasks. Call after the event loop is running."""
    # Background sync -- только если есть источники для синхронизации.
    if (storage.YT_CHANNELS and any(storage.YT_CHANNELS)) or os.environ.get("GITHUB_REPO"):
        asyncio.create_task(background_sync(bot))

    asyncio.create_task(background_resolver(bot))
    asyncio.create_task(background_ctx_cleanup())
    asyncio.create_task(background_ask_history_cleanup())
