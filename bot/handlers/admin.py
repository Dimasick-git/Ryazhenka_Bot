"""Admin command handlers."""
import datetime
import functools
import logging
import os

from aiogram import Bot, Router, types
from aiogram.filters import Command, CommandObject

from .. import storage
from ..config import ADMIN_IDS, GITHUB_REPO, SYNC_INTERVAL_SECONDS
from ..helpers import safe_send
from ..nlp import invalidate_index
from ..services.sync import sync_sources

router = Router()


def _is_admin(user_id: int) -> bool:
    if not ADMIN_IDS:
        return False
    return user_id in ADMIN_IDS


def _require_admin(handler):
    @functools.wraps(handler)
    async def wrapper(message: types.Message, *args, **kwargs):
        if not _is_admin(message.from_user.id):
            await message.reply(" У вас нет прав на выполнение этой операции.")
            return
        return await handler(message, *args, **kwargs)
    return wrapper


@router.message(Command("admin_help"))
@_require_admin
async def admin_help(message: types.Message) -> None:
    text = (
        " *Админские команды* \n"
        f"{'─' * 35}\n"
        " *Управление гайдами:*\n"
        " /add\\_guide `Кат | Назв | URL`\n"
        " /remove\\_guide `Кат | Назв`\n"
        " /edit\\_guide `Кат | Назв | URL`\n"
        " /list\\_guides `[Категория]`\n\n"
        " *Данные и синхронизация:*\n"
        " /sync — Синхронизация YouTube/GitHub\n"
        " /purge\\_autoguides — Автогайды в архив\n"
        " /cleanup\\_duplicates — Удалить дубликаты\n"
        " /toggle\\_autoresolve — Авто-резолв ссылок\n\n"
        " *YouTube каналы:*\n"
        " /yt\\_add `<url>` — Добавить канал\n"
        " /yt\\_remove `<url>` — Удалить канал\n"
        " /yt\\_list — Список каналов\n"
        " /yt\\_cache — Показать кэш\n"
        " /yt\\_prune\\_on / /yt\\_prune\\_off — Прунинг\n"
        " /yt\\_set\\_limit `<N>` — Лимит видео\n\n"
        " *Система:*\n"
        " /status — Статус бота\n"
        " /restart\\_polling — Сброс webhook\n"
    )
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("status"))
@_require_admin
async def bot_status(message: types.Message, bot: Bot) -> None:
    try:
        webhook_info = await bot.get_webhook_info()
    except Exception:
        webhook_info = None
    total = sum(len(g) for g in storage.GUIDES.values())
    yt_cats = [k for k in storage.GUIDES if k.startswith("YouTube -")]
    text = (
        f" *Статус бота Ryazhenka*\n{'─' * 30}\n"
        f" Категорий: {len(storage.GUIDES)}\n"
        f" Всего гайдов: {total}\n"
        f" YouTube категорий: {len(yt_cats)}\n"
        f" Sync interval: {SYNC_INTERVAL_SECONDS}s\n"
        f" ML_MODE: {os.environ.get('ML_MODE', '0')}\n"
        f" YT Pruning: {storage.YT_PRUNE_REMOVED}\n"
        f" YT Keep limit: {storage.YT_KEEP_LIMIT}\n"
        f" YT каналов: {len(storage.YT_CHANNELS)}\n"
        f" Webhook: {webhook_info.url if webhook_info else 'N/A'}\n"
    )
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("sync"))
@_require_admin
async def manual_sync(message: types.Message, bot: Bot) -> None:
    await message.reply(" Запускаю синхронизацию источников ...")
    try:
        summary = await sync_sources()
        invalidate_index()
        await message.reply(
            f" Синхронизация завершена .\n"
            f"YouTube добавлено: {summary.get('youtube_added', 0)}\n"
            f"GitHub добавлено: {summary.get('github_added', 0)}"
        )
    except Exception as e:
        logging.exception("Manual sync failed: %s", e)
        await message.reply(f" Ошибка при синхронизации: {e}")


@router.message(Command("add_guide"))
@_require_admin
async def add_guide_cmd(message: types.Message, command: CommandObject) -> None:
    if not command.args:
        await message.reply(
            " *Формат:* `/add_guide Категория | Название | URL`",
            parse_mode="Markdown",
        )
        return
    parts = [p.strip() for p in command.args.split("|")]
    if len(parts) < 3:
        await message.reply(" Нужно три части через `|`: `Категория | Название | URL`", parse_mode="Markdown")
        return
    category, title, url = parts[0], parts[1], parts[2]
    if not url.startswith(("http://", "https://")):
        await message.reply(" URL должен начинаться с `http://` или `https://`", parse_mode="Markdown")
        return
    if category not in storage.GUIDES:
        storage.GUIDES[category] = {}
    if title in storage.GUIDES[category]:
        await message.reply(
            f" Гайд `{title}` уже существует. Используйте `/edit_guide` для изменения.",
            parse_mode="Markdown",
        )
        return
    storage.GUIDES[category][title] = url
    storage.save_guides()
    meta_key = f"{category}|{title}"
    storage.GUIDES_META[meta_key] = {
        "title": title, "url": url, "category": category,
        "added_at": datetime.datetime.utcnow().isoformat()[:19],
    }
    storage.save_guides_meta()
    invalidate_index()
    await message.reply(
        f" Гайд добавлен!\n\n *Категория:* {category}\n *Название:* {title}\n {url}",
        parse_mode="Markdown",
    )


@router.message(Command("remove_guide"))
@_require_admin
async def remove_guide_cmd(message: types.Message, command: CommandObject) -> None:
    if not command.args:
        await message.reply(" *Формат:* `/remove_guide Категория | Название`", parse_mode="Markdown")
        return
    parts = [p.strip() for p in command.args.split("|")]
    if len(parts) < 2:
        await message.reply(" Нужно две части через `|`", parse_mode="Markdown")
        return
    category, title = parts[0], parts[1]
    if category not in storage.GUIDES or title not in storage.GUIDES.get(category, {}):
        await message.reply(f" Гайд `{title}` не найден в `{category}`.", parse_mode="Markdown")
        return
    del storage.GUIDES[category][title]
    if not storage.GUIDES[category]:
        del storage.GUIDES[category]
    storage.save_guides()
    meta_key = f"{category}|{title}"
    storage.GUIDES_META.pop(meta_key, None)
    storage.save_guides_meta()
    invalidate_index()
    await message.reply(f" Гайд удалён:\n `{category}` → `{title}`", parse_mode="Markdown")


@router.message(Command("edit_guide"))
@_require_admin
async def edit_guide_cmd(message: types.Message, command: CommandObject) -> None:
    if not command.args:
        await message.reply(" *Формат:* `/edit_guide Категория | Название | Новый URL`", parse_mode="Markdown")
        return
    parts = [p.strip() for p in command.args.split("|")]
    if len(parts) < 3:
        await message.reply(" Нужно три части через `|`", parse_mode="Markdown")
        return
    category, title, new_url = parts[0], parts[1], parts[2]
    if category not in storage.GUIDES or title not in storage.GUIDES.get(category, {}):
        await message.reply(f" Гайд `{title}` не найден в `{category}`.", parse_mode="Markdown")
        return
    old_url = storage.GUIDES[category][title]
    storage.GUIDES[category][title] = new_url
    storage.save_guides()
    invalidate_index()
    await message.reply(
        f" Гайд обновлён!\n\n *Категория:* {category}\n *Название:* {title}\n"
        f" *Старый:* {old_url}\n *Новый:* {new_url}",
        parse_mode="Markdown",
    )


@router.message(Command("list_guides"))
@_require_admin
async def list_guides_cmd(message: types.Message, command: CommandObject) -> None:
    category = (command.args or "").strip()
    if not category:
        cats = "\n".join(f"• `{c}`" for c in storage.GUIDES)
        await message.reply(
            f" *Доступные категории:*\n{cats}\n\nИспользуйте `/list_guides Категория`.",
            parse_mode="Markdown",
        )
        return
    best = next((c for c in storage.GUIDES if c.lower() == category.lower()), None)
    if best is None:
        best = next((c for c in storage.GUIDES if category.lower() in c.lower()), None)
    if best is None:
        await message.reply(f" Категория не найдена: `{category}`", parse_mode="Markdown")
        return
    guides = storage.GUIDES[best]
    if not guides:
        await message.reply(f" Категория `{best}` пуста.", parse_mode="Markdown")
        return
    lines = [f" *{best}* — {len(guides)} гайдов\n"]
    for i, (t, u) in enumerate(guides.items(), 1):
        lines.append(f"{i}. [{t}]({u})")
    await safe_send(message, "\n".join(lines), disable_web_page_preview=True)


@router.message(Command("purge_autoguides"))
@_require_admin
async def purge_autoguides(message: types.Message) -> None:
    cat = "🆕 Авто-гайды"
    if cat not in storage.GUIDES:
        await message.reply("ℹ Категория автогайдов уже отсутствует.")
        return
    archive = "Архив - Авто-гайды"
    storage.GUIDES.setdefault(archive, {})
    storage.GUIDES[archive].update(storage.GUIDES[cat])
    del storage.GUIDES[cat]
    storage.save_guides()
    await message.reply(f" '{cat}' перемещена в '{archive}'.")


@router.message(Command("cleanup_duplicates"))
@_require_admin
async def cleanup_duplicates_cmd(message: types.Message) -> None:
    await message.reply(" Выполняю очистку дубликатов...")
    removed = storage.dedupe_guides()
    await message.reply(f" Очистка завершена. Удалено дубликатов: {removed}")


@router.message(Command("toggle_autoresolve"))
@_require_admin
async def toggle_autoresolve(message: types.Message) -> None:
    current = storage.SETTINGS.get("auto_resolve_and_add", True)
    storage.SETTINGS["auto_resolve_and_add"] = not current
    storage.save_settings()
    await message.reply(f"Настройка auto_resolve_and_add: {storage.SETTINGS['auto_resolve_and_add']}")


@router.message(Command("yt_add"))
@_require_admin
async def yt_add(message: types.Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.reply("Использование: /yt_add <channel_url_or_handle_or_UC_id>")
        return
    if arg in storage.YT_CHANNELS:
        await message.reply("Канал уже в списке .")
        return
    storage.YT_CHANNELS.append(arg)
    storage.save_yt_channels()
    await message.reply(f"Добавил канал : {arg}")


@router.message(Command("yt_remove"))
@_require_admin
async def yt_remove(message: types.Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg:
        await message.reply("Использование: /yt_remove <channel_url_or_handle_or_UC_id>")
        return
    try:
        storage.YT_CHANNELS.remove(arg)
        storage.save_yt_channels()
        await message.reply(f"Удалил канал : {arg}")
    except ValueError:
        await message.reply("Канал не найден в списке .")


@router.message(Command("yt_list"))
@_require_admin
async def yt_list(message: types.Message) -> None:
    if not storage.YT_CHANNELS:
        await message.reply("Список YT каналов пуст ")
        return
    text = "YouTube каналы в мониторинге :\n" + "\n".join(f"• {ch}" for ch in storage.YT_CHANNELS)
    await message.reply(text)


@router.message(Command("yt_cache"))
@_require_admin
async def yt_cache_cmd(message: types.Message) -> None:
    items = list(storage.YT_CACHE.items())[:40]
    text = "YT cache (sample):\n"
    for k, v in items:
        text += f"{k} -> {v.get('channel_id', '?')} ({v.get('title', '')})\n"
    await message.reply(text or "Cache пустой.")


@router.message(Command("yt_prune_on"))
@_require_admin
async def yt_prune_on(message: types.Message) -> None:
    storage.YT_PRUNE_REMOVED = True
    storage.SETTINGS["yt_prune_removed"] = True
    storage.save_settings()
    await message.reply(" Pruning включён ")


@router.message(Command("yt_prune_off"))
@_require_admin
async def yt_prune_off(message: types.Message) -> None:
    storage.YT_PRUNE_REMOVED = False
    storage.SETTINGS["yt_prune_removed"] = False
    storage.save_settings()
    await message.reply(" Pruning выключен ")


@router.message(Command("yt_set_limit"))
@_require_admin
async def yt_set_limit(message: types.Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    if not arg or not arg.isdigit():
        await message.reply("Использование: /yt_set_limit <число>")
        return
    storage.YT_KEEP_LIMIT = int(arg)
    storage.SETTINGS["yt_keep_limit"] = storage.YT_KEEP_LIMIT
    storage.save_settings()
    await message.reply(f" Новый лимит: {storage.YT_KEEP_LIMIT}")


@router.message(Command("restart_polling"))
@_require_admin
async def restart_polling_cmd(message: types.Message, bot: Bot) -> None:
    await message.reply(" Удаляю webhook и пытаюсь перезапустить...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.exception("Failed deleting webhook: %s", e)
    await message.reply(" Удалил webhook. Перезапустите процесс бота на хосте, если нужно.")
