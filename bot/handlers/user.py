"""User-facing command handlers."""
import hashlib
import random
import time
import uuid

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent

from .. import storage
from ..config import ADMIN_IDS
from ..helpers import (
    build_guide_key,
    cat_cb,
    create_categories_keyboard,
    escape_html,
    make_rating_keyboard,
    safe_send,
)
from ..nlp import invalidate_index, search_guides
from ..services.github import fetch_github_repos

router = Router()

# Temporary context for "open" callbacks (1h TTL)
DIALOG_CTX: dict = {}
DIALOG_CTX_TIME: dict = {}


def _cleanup_dialog_ctx() -> None:
    now = time.time()
    stale = [k for k, v in DIALOG_CTX_TIME.items() if now - v > 3600]
    for k in stale:
        DIALOG_CTX.pop(k, None)
        DIALOG_CTX_TIME.pop(k, None)
    # Evict oldest entries if still too large
    if len(DIALOG_CTX) > 500:
        oldest = sorted(DIALOG_CTX_TIME.items(), key=lambda x: x[1])[:len(DIALOG_CTX) - 500]
        for k, _ in oldest:
            DIALOG_CTX.pop(k, None)
            DIALOG_CTX_TIME.pop(k, None)


@router.message(Command("start"))
async def start(message: types.Message) -> None:
    total = sum(len(g) for g in storage.GUIDES.values())
    await message.reply(
        "🛠️ *Ryazhenka Bot* — инженерный помощник по прошивке Nintendo Switch\n"
        f"{'─' * 35}\n"
        f"📚 Загружено гайдов: *{total}* в *{len(storage.GUIDES)}* категориях\n\n"
        "⚙️ *Основные команды:*\n"
        "🔍 /guide `<тема>` — найти гайд (fuzzy search)\n"
        "🧠 /aiguide `<текст>` — умный поиск (BM25 + fuzzy)\n"
        "📋 /all — все категории\n"
        "📖 /help — полный список команд\n\n"
        "📂 *Выберите категорию ниже:*",
        parse_mode="Markdown",
        reply_markup=create_categories_keyboard(),
    )


@router.message(Command("all"))
async def show_all(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply("❌ База гайдов пуста 📭")
        return
    text = "📚 *Все категории* 🗂️:\n\n"
    total = 0
    for cat, guides in storage.GUIDES.items():
        total += len(guides)
        text += f"{cat} — {len(guides)} гайдов\n"
    text += f"\n📝 Всего: {total} гайдов в {len(storage.GUIDES)} категориях\n\n"
    text += "Используйте /guide <название> для поиска или выберите категорию:"
    await safe_send(message, text, reply_markup=create_categories_keyboard())


@router.message(Command("guide"))
@router.message(Command("гайд"))
@router.message(Command("search"))
async def send_guide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.reply("❌ Укажите тему после команды, например: /guide battery")
        return
    if not storage.GUIDES:
        await message.reply("❌ База гайдов пуста 📭")
        return

    results = search_guides(query, top_n=10)
    if not results:
        await message.reply(
            "❌ Не нашёл гайд ⚠️. Попробуйте:\n"
            "• /guide atmosphere\n• /guide battery\n• /guide emunand\n\n"
            "Или /all для всех категорий."
        )
        return

    best, best_score = results[0]
    if best_score >= 75:
        guide_key = build_guide_key(best["url"])
        storage.GUIDE_RATINGS[f"_meta_{guide_key}"] = {
            "title": best["title"], "url": best["url"], "category": best["category"],
        }
        await message.reply(
            f"✅ Нашёл гайд в категории *{best['category']}*:\n\n"
            f"*{best['title']}*\n{best['url']}",
            parse_mode="Markdown",
            reply_markup=make_rating_keyboard(guide_key),
        )
        return

    # suggestions
    suggestions = [(d, sc) for d, sc in results if sc >= 55]
    if suggestions:
        text = "🤔 Ничего точного, но есть похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for doc, _ in suggestions[:10]:
            text += f"*{doc['title']}* — {doc['category']}\n"
            key = hashlib.md5(doc["title"].encode()).hexdigest()[:16]
            kb.inline_keyboard.append([InlineKeyboardButton(
                text=f"Открыть: {doc['title'][:40]}", callback_data=f"open|{key}",
            )])
            DIALOG_CTX[key] = doc
            DIALOG_CTX_TIME[key] = time.time()
        _cleanup_dialog_ctx()
        await message.reply(text, parse_mode="Markdown", reply_markup=kb)
        return

    await message.reply(
        "❌ Не нашёл гайд ⚠️. Попробуйте:\n"
        "• /guide atmosphere\n• /guide battery\n• /guide emunand\n\n"
        "Или /all для всех категорий."
    )


@router.message(Command("aiguide"))
async def handle_aiguide(message: types.Message) -> None:
    query = message.text[len("/aiguide"):].strip()
    if not query:
        await message.reply("Пожалуйста, напишите запрос для поиска гайда ⌨️.")
        return
    if not storage.GUIDES:
        await message.reply("❌ База гайдов пуста 📭")
        return
    results = search_guides(query, top_n=10)
    if results and results[0][1] >= 75:
        best = results[0][0]
        guide_key = build_guide_key(best["url"])
        storage.GUIDE_RATINGS[f"_meta_{guide_key}"] = {
            "title": best["title"], "url": best["url"], "category": best["category"],
        }
        await message.reply(
            f"✅ Найден гайд 🎯: {best['title']}\nКатегория: {best['category']}\n{best['url']}",
            reply_markup=make_rating_keyboard(guide_key),
        )
        return
    if results:
        text = "🤔 Похоже, ничего точного. Вот похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for doc, sc in results[:10]:
            text += f"{doc['title']} — {doc['category']} (score {round(sc, 1)})\n"
            if doc.get("url"):
                kb.inline_keyboard.append([InlineKeyboardButton(
                    text=f"Открыть: {doc['title'][:40]}", url=doc["url"],
                )])
        await message.reply(text, reply_markup=kb if kb.inline_keyboard else None)
        return
    await message.reply("❌ Не нашёл подходящих гайдов ⚠️. Попробуйте уточнить запрос.")


@router.message(Command("random"))
async def random_guide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip().lower()
    matching = {c: g for c, g in storage.GUIDES.items() if query in c.lower()} if query else storage.GUIDES
    all_entries = [(t, u, c) for c, g in matching.items() for t, u in g.items() if u]
    if not all_entries:
        await message.reply(
            "❌ Гайды не найдены."
            + (" Попробуй /random без аргументов или /all." if query else "")
        )
        return
    title, url, cat = random.choice(all_entries)
    await message.reply(
        f"🎲 *Случайный гайд*\n\n📂 Категория: {cat}\n📖 [{title}]({url})",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )


@router.message(Command("new"))
async def new_guides(message: types.Message) -> None:
    recent = sorted(
        storage.GUIDES_META.items(),
        key=lambda x: x[1].get("added_at", ""),
        reverse=True,
    )[:10]
    if not recent:
        await message.reply(
            "📅 История добавлений пока пуста.\n"
            "Новые гайды будут отслеживаться — добавляй через /add\\_guide!",
            parse_mode="Markdown",
        )
        return
    text = "🆕 *Последние добавленные гайды:*\n\n"
    for _, meta in recent:
        title, url, cat = meta.get("title", ""), meta.get("url", ""), meta.get("category", "")
        added = meta.get("added_at", "")[:10]
        if url:
            text += f"• [{title}]({url}) — _{cat}_ `{added}`\n"
    await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True)


@router.message(Command("stats"))
async def guide_stats(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply("❌ База гайдов пуста 📭")
        return
    total = sum(len(g) for g in storage.GUIDES.values())
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)
    text = f"📊 *Статистика базы гайдов*\n{'─' * 30}\n📚 Всего: *{total}*\n📂 Категорий: *{len(storage.GUIDES)}*\n\n*Топ категорий:*\n"
    for cat, guides in sorted_cats[:8]:
        bar = "█" * min(len(guides) // max(1, total // 20), 10)
        text += f"  {cat} — {len(guides)} {bar}\n"
    if len(sorted_cats) > 8:
        text += f"  _...и ещё {len(sorted_cats) - 8} категорий_\n"
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("top"))
async def top_categories(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply("❌ База гайдов пуста 📭")
        return
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    total = sum(len(g) for g in storage.GUIDES.values())
    text = f"🏆 *Топ категорий*\n{'─' * 35}\n"
    for i, (cat, guides) in enumerate(sorted_cats, 1):
        pct = len(guides) * 100 // max(total, 1)
        text += f"{i}. {cat} — {len(guides)} гайдов ({pct}%)\n"
    await message.reply(text, parse_mode="Markdown", reply_markup=create_categories_keyboard())


@router.message(Command("recommend"))
async def recommend_repos(message: types.Message) -> None:
    user = "Dimasick-git"
    await message.reply(f"🔎 Получаю публичные репозитории 📡 {user}...")
    repos = await fetch_github_repos(user, limit=20)
    if not repos:
        await message.reply("❌ Не удалось получить репозитории.")
        return
    text = f"📦 Рекомендуемые репозитории 🛠️ {user}:\n\n"
    for name, url, desc in repos[:15]:
        text += f"• [{name}]({url}) — {desc}\n"
    await safe_send(message, text, disable_web_page_preview=True)


@router.message(Command("fav"))
async def favorites_command(message: types.Message, command: CommandObject) -> None:
    user_id = str(message.from_user.id)
    args = (command.args or "").strip()

    if not args or args == "list":
        favs = storage.USER_FAVORITES.get(user_id, [])
        if not favs:
            await message.reply(
                "⭐ У вас нет избранных гайдов.\n\nДобавить: `/fav add <тема>`\nИли нажмите ⭐ под любым гайдом.",
                parse_mode="Markdown",
            )
            return
        text = f"⭐ *Ваше избранное* ({len(favs)} гайдов):\n\n"
        for i, fav in enumerate(favs, 1):
            text += f"{i}. [{fav['title']}]({fav['url']}) — _{fav['category']}_\n"
        text += "\n🗑️ Удалить: `/fav remove <номер>`"
        await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    if args.startswith("add "):
        query = args[4:].strip()
        if not query:
            await message.reply("Укажи тему: `/fav add <тема>`", parse_mode="Markdown")
            return
        found = search_guides(query, top_n=1)
        if not found or found[0][1] < 30:
            await message.reply(f"❌ Гайд по запросу «{query}» не найден.")
            return
        entry = found[0][0]
        url = entry.get("url", "")
        if not url:
            await message.reply("❌ У этого гайда нет ссылки.")
            return
        favs = storage.USER_FAVORITES.setdefault(user_id, [])
        if any(f["url"] == url for f in favs):
            await message.reply(f"⭐ «{entry['title']}» уже в избранном!")
            return
        if len(favs) >= 50:
            await message.reply("❌ Максимум 50 гайдов. Удали лишние через /fav remove <номер>.")
            return
        favs.append({"title": entry["title"], "url": url, "category": entry["category"]})
        storage.save_favorites()
        await message.reply(f"⭐ Добавлено в избранное: *{entry['title']}*", parse_mode="Markdown")
        return

    if args.startswith(("remove ", "rm ")):
        num_str = args.split(None, 1)[1] if " " in args else ""
        if not num_str.isdigit():
            await message.reply("Укажи номер: `/fav remove <номер>`", parse_mode="Markdown")
            return
        idx = int(num_str) - 1
        favs = storage.USER_FAVORITES.get(user_id, [])
        if idx < 0 or idx >= len(favs):
            await message.reply(f"❌ Нет гайда #{idx + 1} в избранном.")
            return
        removed = favs.pop(idx)
        storage.save_favorites()
        await message.reply(f"🗑️ Удалено из избранного: *{removed['title']}*", parse_mode="Markdown")
        return

    await message.reply(
        "⭐ *Команды избранного:*\n/fav — список\n/fav add `<тема>` — добавить\n/fav remove `<номер>` — удалить",
        parse_mode="Markdown",
    )


@router.message(Command("feedback"))
async def user_feedback(message: types.Message, command: CommandObject, bot: Bot) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.reply(
            "📬 *Предложить гайд администраторам:*\n\n"
            "`/feedback <название | ссылка | описание>`",
            parse_mode="Markdown",
        )
        return
    if not ADMIN_IDS:
        await message.reply("❌ Администраторы не настроены.\nНапиши напрямую: @Ryazhenkabestcfw")
        return
    user = message.from_user
    user_info = f"@{user.username}" if user.username else f"ID {user.id}"
    msg_to_admin = (
        f"📬 *Предложение гайда*\n{'─' * 30}\n"
        f"👤 От: {user_info}\n💬 Текст: {text}\n\n"
        "_Добавить: /add\\_guide Категория | Название | URL_"
    )
    sent = False
    for aid in ADMIN_IDS:
        try:
            await bot.send_message(aid, msg_to_admin, parse_mode="Markdown")
            sent = True
        except Exception:
            pass
    if sent:
        await message.reply("✅ Спасибо! Предложение отправлено администраторам.")
    else:
        await message.reply("❌ Не удалось отправить.\nНапиши напрямую: @Ryazhenkabestcfw")


@router.message(Command("help"))
async def help_command(message: types.Message) -> None:
    text = (
        "📘 *Полный список команд* 📜\n"
        f"{'─' * 35}\n"
        "📌 *Основные:*\n"
        "👋 /start — Приветствие и быстрые ссылки\n"
        "📋 /all — Показать все категории\n"
        "🔍 /guide `<тема>` — Найти гайд (fuzzy search)\n"
        "🧠 /aiguide `<текст>` — Умный поиск (BM25 + fuzzy)\n"
        "🎲 /random `[категория]` — Случайный гайд\n"
        "🆕 /new — Последние добавленные гайды\n"
        "📊 /stats — Статистика базы гайдов\n"
        "🏆 /top — Топ категорий\n"
        "📦 /recommend — Репозитории автора\n\n"
        "⭐ *Избранное:*\n"
        "/fav — Показать избранное\n"
        "/fav add `<тема>` — Добавить гайд\n"
        "/fav remove `<номер>` — Удалить\n\n"
        "📬 *Обратная связь:*\n"
        "/feedback `<текст>` — Предложить новый гайд\n\n"
        "🔍 *Inline-режим:*\n"
        "Напиши `@botname запрос` в любом чате!\n\n"
        "🔐 *Админ-команды:*\n"
        "/sync, /add\\_guide, /remove\\_guide, /edit\\_guide, /list\\_guides, /admin\\_help\n"
    )
    await message.reply(text, parse_mode="Markdown")
