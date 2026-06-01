"""User-facing command handlers."""
import hashlib
import random
import time
import uuid
from difflib import SequenceMatcher

from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InlineQueryResultArticle, InputTextMessageContent

try:
    from rapidfuzz import fuzz as _rfuzz
    def _cat_score(q: str, cat: str) -> float:
        c = cat.lower()
        return max(_rfuzz.token_set_ratio(q, c), _rfuzz.partial_ratio(q, c))
except ImportError:
    def _cat_score(q: str, cat: str) -> float:
        return SequenceMatcher(None, q, cat.lower()).ratio() * 100

from .. import storage
from ..config import ADMIN_IDS, GITHUB_REPO
from ..helpers import (
    build_guide_key,
    cat_cb,
    create_categories_keyboard,
    escape_html,
    make_rating_keyboard,
    safe_send,
)
from ..nlp import invalidate_index, search_guides
from ..services.ai import ask_ai
from ..services.github import fetch_github_repos

_GUIDES_PER_CAT_PAGE = 15

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
    overflow = len(DIALOG_CTX) - 500
    if overflow > 0:
        # Single O(n) pass: find the `overflow` oldest entries without full sort
        import heapq
        oldest_keys = heapq.nsmallest(overflow, DIALOG_CTX_TIME, key=DIALOG_CTX_TIME.__getitem__)
        for k in oldest_keys:
            DIALOG_CTX.pop(k, None)
            DIALOG_CTX_TIME.pop(k, None)



@router.message(Command("start"))
async def start(message: types.Message) -> None:
    total = sum(len(g) for g in storage.GUIDES.values())
    await message.reply(
        " *Ryazhenka Bot* — инженерный помощник по прошивке Nintendo Switch\n"
        f"{'─' * 35}\n"
        f" Загружено гайдов: *{total}* в *{len(storage.GUIDES)}* категориях\n\n"
        " *Основные команды:*\n"
        " /guide `<тема>` — найти гайд (fuzzy search)\n"
        " /aiguide `<текст>` — умный поиск (BM25 + fuzzy)\n"
        " /all — все категории\n"
        " /help — полный список команд\n\n"
        " *Выберите категорию ниже:*",
        parse_mode="Markdown",
        reply_markup=create_categories_keyboard(),
    )


@router.message(Command("all"))
async def show_all(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return
    text = " *Все категории* :\n\n"
    total = 0
    for cat, guides in storage.GUIDES.items():
        total += len(guides)
        text += f"{cat} — {len(guides)} гайдов\n"
    text += f"\n Всего: {total} гайдов в {len(storage.GUIDES)} категориях\n\n"
    text += "Используйте /guide <название> для поиска или выберите категорию:"
    await safe_send(message, text, reply_markup=create_categories_keyboard())


async def _perform_search(message: types.Message, query: str) -> None:
    """Shared search logic for /guide and /aiguide."""
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return

    storage.add_to_search_history(str(message.from_user.id), query)
    results = search_guides(query, top_n=10)

    if not results:
        await message.reply(
            " Не нашёл гайд . Попробуйте:\n"
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
        storage.save_ratings()
        await message.reply(
            f" Нашёл гайд в категории *{best['category']}*:\n\n"
            f"*{best['title']}*\n{best['url']}",
            parse_mode="Markdown",
            reply_markup=make_rating_keyboard(guide_key),
        )
        return

    suggestions = [(d, sc) for d, sc in results if sc >= 55]
    if suggestions:
        text = " Ничего точного, но есть похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        now = time.time()
        for doc, _ in suggestions[:10]:
            text += f"*{doc['title']}* — {doc['category']}\n"
            if doc.get("url"):
                # Прямая ссылка — никакой контекст не нужен
                kb.inline_keyboard.append([InlineKeyboardButton(
                    text=f"Открыть: {doc['title'][:40]}", url=doc["url"],
                )])
            else:
                # Нет URL — используем callback + DIALOG_CTX
                key = hashlib.md5(doc["title"].encode()).hexdigest()[:16]
                DIALOG_CTX[key] = doc
                DIALOG_CTX_TIME[key] = now
                kb.inline_keyboard.append([InlineKeyboardButton(
                    text=f"Открыть: {doc['title'][:40]}", callback_data=f"open|{key}",
                )])
        _cleanup_dialog_ctx()
        await message.reply(text, parse_mode="Markdown", reply_markup=kb if kb.inline_keyboard else None)
        return

    top_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    cat_hints = "".join(f"\n• /category `{c}`" for c, _ in top_cats)
    await message.reply(
        " Не нашёл гайд . Попробуйте:\n"
        "• /guide atmosphere\n• /guide battery\n• /guide emunand\n\n"
        f"Популярные категории:{cat_hints}\n\nИли /all для всех категорий."
    )


@router.message(Command("guide"))
@router.message(Command("гайд"))
@router.message(Command("search"))
async def send_guide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.reply(" Укажите тему после команды, например: /guide battery")
        return
    await _perform_search(message, query)


@router.message(Command("aiguide"))
async def handle_aiguide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip()
    if not query:
        await message.reply(
            " Введи вопрос, например:\n"
            "`/aiguide как настроить emuNAND`\n"
            "`/aiguide установка игр atmosphere`",
            parse_mode="Markdown",
        )
        return

    storage.add_to_search_history(str(message.from_user.id), query)
    results = search_guides(query, top_n=5)

    # Build guide context for AI from top local results
    guide_context = ""
    if results:
        lines = []
        for doc, score in results[:3]:
            if score >= 30:
                lines.append(f"• {doc['title']} ({doc['category']}): {doc.get('url', '')}")
        guide_context = "\n".join(lines)

    # Use AI when local search has no confident match
    best_score = results[0][1] if results else 0
    if best_score >= 75:
        # High-confidence local hit — show it directly (fast path)
        best = results[0][0]
        guide_key = build_guide_key(best["url"])
        storage.GUIDE_RATINGS[f"_meta_{guide_key}"] = {
            "title": best["title"], "url": best["url"], "category": best["category"],
        }
        storage.save_ratings()
        await message.reply(
            f" Нашёл гайд в категории *{best['category']}*:\n\n"
            f"*{best['title']}*\n{best['url']}",
            parse_mode="Markdown",
            reply_markup=make_rating_keyboard(guide_key),
        )
        return

    # Try AI for uncertain or missing results
    thinking_msg = await message.reply(" Думаю...")
    import asyncio
    loop = asyncio.get_event_loop()
    ai_answer = await loop.run_in_executor(None, ask_ai, query, guide_context)

    if ai_answer:
        reply_text = f" *AI-ответ по запросу:* _{query}_\n\n{ai_answer}"
        if guide_context:
            reply_text += "\n\n Связанные гайды в базе:"
            for doc, score in results[:3]:
                if score >= 30 and doc.get("url"):
                    reply_text += f"\n• [{doc['title']}]({doc['url']})"
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    # Fallback to local suggestions or not-found message
    await thinking_msg.delete()
    await _perform_search(message, query)


@router.message(Command("ask"))
async def ask_command(message: types.Message, command: CommandObject) -> None:
    """Free-form AI question about Nintendo Switch CFW."""
    query = (command.args or "").strip()
    if not query:
        await message.reply(
            " *Задай вопрос AI по Nintendo Switch CFW:*\n\n"
            "`/ask как сделать backup NAND?`\n"
            "`/ask в чём разница emuNAND и sysNAND?`\n"
            "`/ask как установить игру через Tinfoil?`",
            parse_mode="Markdown",
        )
        return

    thinking_msg = await message.reply(" Думаю...")
    import asyncio

    # Enrich context with local search results
    results = search_guides(query, top_n=3)
    guide_context = ""
    if results:
        lines = [f"• {d['title']} ({d['category']}): {d.get('url', '')}" for d, sc in results if sc >= 25]
        guide_context = "\n".join(lines)

    loop = asyncio.get_event_loop()
    ai_answer = await loop.run_in_executor(None, ask_ai, query, guide_context)

    if ai_answer:
        reply_text = f" *Ответ AI:*\n\n{ai_answer}"
        if guide_context:
            reply_text += "\n\n Связанные гайды:"
            for doc, score in results[:3]:
                if score >= 25 and doc.get("url"):
                    reply_text += f"\n• [{doc['title']}]({doc['url']})"
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await thinking_msg.edit_text(
            " AI недоступен. Попробуй:\n"
            "• /guide — поиск по базе гайдов\n"
            "• /all — все категории\n"
            "• /feedback — предложи добавить гайд"
        )


@router.message(Command("random"))
async def random_guide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip().lower()
    matching = {c: g for c, g in storage.GUIDES.items() if query in c.lower()} if query else storage.GUIDES
    all_entries = [(t, u, c) for c, g in matching.items() for t, u in g.items() if u]
    if not all_entries:
        await message.reply(
            " Гайды не найдены."
            + (" Попробуй /random без аргументов или /all." if query else "")
        )
        return
    title, url, cat = random.choice(all_entries)
    await message.reply(
        f" *Случайный гайд*\n\n Категория: {cat}\n [{title}]({url})",
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
            " История добавлений пока пуста.\n"
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
        await message.reply(" База гайдов пуста ")
        return
    total = sum(len(g) for g in storage.GUIDES.values())
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)
    text = f" *Статистика базы гайдов*\n{'─' * 30}\n Всего: *{total}*\n Категорий: *{len(storage.GUIDES)}*\n\n*Топ категорий:*\n"
    for cat, guides in sorted_cats[:8]:
        bar = "█" * min(len(guides) // max(1, total // 20), 10)
        text += f"  {cat} — {len(guides)} {bar}\n"
    if len(sorted_cats) > 8:
        text += f"  _...и ещё {len(sorted_cats) - 8} категорий_\n"
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("top"))
async def top_categories(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    total = sum(len(g) for g in storage.GUIDES.values())
    text = f" *Топ категорий*\n{'─' * 35}\n"
    for i, (cat, guides) in enumerate(sorted_cats, 1):
        pct = len(guides) * 100 // max(total, 1)
        text += f"{i}. {cat} — {len(guides)} гайдов ({pct}%)\n"
    await message.reply(text, parse_mode="Markdown", reply_markup=create_categories_keyboard())


def _recommend_user() -> str:
    """Определяет GitHub пользователя из GITHUB_REPO или fallback."""
    if GITHUB_REPO and "/" in GITHUB_REPO:
        return GITHUB_REPO.split("/")[0]
    return "Dimasick-git"


@router.message(Command("recommend"))
async def recommend_repos(message: types.Message) -> None:
    user = _recommend_user()
    await message.reply(f" Получаю публичные репозитории  {user}...")
    repos = await fetch_github_repos(user, limit=20)
    if not repos:
        await message.reply(" Не удалось получить репозитории.")
        return
    text = f" Рекомендуемые репозитории  {user}:\n\n"
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
        text += "\n Удалить: `/fav remove <номер>`"
        await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    if args.startswith("add "):
        query = args[4:].strip()
        if not query:
            await message.reply("Укажи тему: `/fav add <тема>`", parse_mode="Markdown")
            return
        found = search_guides(query, top_n=1)
        if not found or found[0][1] < 30:
            await message.reply(f" Гайд по запросу «{query}» не найден.")
            return
        entry = found[0][0]
        url = entry.get("url", "")
        if not url:
            await message.reply(" У этого гайда нет ссылки.")
            return
        favs = storage.USER_FAVORITES.setdefault(user_id, [])
        if any(f["url"] == url for f in favs):
            await message.reply(f"⭐ «{entry['title']}» уже в избранном!")
            return
        if len(favs) >= 50:
            await message.reply(" Максимум 50 гайдов. Удали лишние через /fav remove <номер>.")
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
            await message.reply(f" Нет гайда #{idx + 1} в избранном.")
            return
        removed = favs.pop(idx)
        storage.save_favorites()
        await message.reply(f" Удалено из избранного: *{removed['title']}*", parse_mode="Markdown")
        return

    await message.reply(
        "⭐ *Команды избранного:*\n/fav — список\n/fav add `<тема>` — добавить\n/fav remove `<номер>` — удалить",
        parse_mode="Markdown",
    )


_FEEDBACK_MAX_LEN = 800


@router.message(Command("feedback"))
async def user_feedback(message: types.Message, command: CommandObject, bot: Bot) -> None:
    text = (command.args or "").strip()
    if not text:
        await message.reply(
            " *Предложить гайд администраторам:*\n\n"
            "`/feedback <название | ссылка | описание>`",
            parse_mode="Markdown",
        )
        return
    if len(text) > _FEEDBACK_MAX_LEN:
        await message.reply(
            f" Сообщение слишком длинное ({len(text)} симв.).\n"
            f"Максимум {_FEEDBACK_MAX_LEN} символов."
        )
        return
    if not ADMIN_IDS:
        await message.reply(" Администраторы не настроены.\nНапиши напрямую: @Ryazhenkabestcfw")
        return
    user = message.from_user
    user_info = f"@{user.username}" if user.username else f"ID {user.id}"
    safe_text = text.replace("*", "\\*").replace("_", "\\_").replace("`", "\\`").replace("[", "\\[")
    msg_to_admin = (
        f" *Предложение гайда*\n{'─' * 30}\n"
        f" От: {user_info}\n Текст: {safe_text}\n\n"
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
        await message.reply(" Спасибо! Предложение отправлено администраторам.")
    else:
        await message.reply(" Не удалось отправить.\nНапиши напрямую: @Ryazhenkabestcfw")


@router.message(Command("category"))
@router.message(Command("cat"))
async def category_guides(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip().lower()
    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return

    if not query:
        cats = sorted(storage.GUIDES.keys())
        text = " *Выберите категорию:*\n\n" + "\n".join(f"• `{c}`" for c in cats)
        text += "\n\nИспользование: `/category <название>`"
        await message.reply(text, parse_mode="Markdown")
        return

    q = query.lower()
    matched = None
    for cat in storage.GUIDES:
        if q in cat.lower() or cat.lower() in q:
            matched = cat
            break
    if not matched:
        scored = sorted(storage.GUIDES.keys(), key=lambda c: _cat_score(q, c), reverse=True)
        if scored and _cat_score(q, scored[0]) >= 55:
            matched = scored[0]
    if not matched:
        cats = sorted(storage.GUIDES.keys())
        await message.reply(
            f" Категория «{query}» не найдена.\n\nДоступные:\n" + "\n".join(f"• `{c}`" for c in cats),
            parse_mode="Markdown",
        )
        return

    guides = storage.GUIDES[matched]
    if not guides:
        await message.reply(f" Категория *{matched}* пуста.", parse_mode="Markdown")
        return

    items = list(guides.items())
    total = len(items)
    page_size = _GUIDES_PER_CAT_PAGE
    total_pages = max(1, (total + page_size - 1) // page_size)
    chunk = items[:page_size]

    text = f" *{matched}*\n"
    if total_pages > 1:
        text += f"_Страница 1/{total_pages}_ — всего {total} гайдов\n"
    text += "\n"
    for title, url in chunk:
        if url:
            text += f"• [{title}]({url})\n"
        else:
            text += f"• {title}\n"
    if total_pages == 1:
        text += f"\n Всего: {total} гайдов\n"

    h = cat_cb(matched)
    nav_row = []
    if total_pages > 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"cat|{h}|1"))
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if nav_row:
        kb.inline_keyboard.append(nav_row)
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅ К категориям", callback_data="back_to_categories")])

    await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True,
                        reply_markup=kb if kb.inline_keyboard else None)


@router.message(Command("trending"))
async def trending_guides(message: types.Message) -> None:
    if not storage.GUIDE_RATINGS:
        await message.reply(" Пока нет оценок. Оценивай гайды кнопками под результатами поиска!")
        return

    scores: dict = {}
    meta: dict = {}
    for key, val in storage.GUIDE_RATINGS.items():
        if key.startswith("_meta_"):
            guide_key = key[len("_meta_"):]
            meta[guide_key] = val
        elif isinstance(val, dict):
            up = val.get("up", 0)
            down = val.get("down", 0)
            if up + down > 0:
                scores[key] = up - down

    if not scores:
        await message.reply(" Пока нет оценок. Оценивай гайды кнопками под результатами поиска!")
        return

    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    text = "🔥 *Топ гайдов по оценкам:*\n\n"
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    for i, (key, score) in enumerate(top, 1):
        m = meta.get(key, {})
        title = m.get("title", key)
        url = m.get("url", "")
        cat = m.get("category", "")
        rating_val = storage.GUIDE_RATINGS.get(key, {})
        up = rating_val.get("up", 0) if isinstance(rating_val, dict) else 0
        down = rating_val.get("down", 0) if isinstance(rating_val, dict) else 0
        score_str = f"👍{up} 👎{down}"
        if url:
            text += f"{i}. [{title}]({url}) — _{cat}_ {score_str}\n"
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"{i}. {title[:45]}", url=url)])
        else:
            text += f"{i}. {title} — _{cat}_ {score_str}\n"
    await message.reply(text, parse_mode="Markdown", disable_web_page_preview=True,
                        reply_markup=kb if kb.inline_keyboard else None)


@router.message(Command("history"))
async def search_history_cmd(message: types.Message) -> None:
    user_id = str(message.from_user.id)
    history = storage.SEARCH_HISTORY.get(user_id, [])
    if not history:
        await message.reply(
            " *История поиска пуста.*\n\nИспользуй /guide или /aiguide чтобы искать гайды.",
            parse_mode="Markdown",
        )
        return
    text = " *Ваши последние запросы:*\n\n"
    for i, entry in enumerate(reversed(history[-10:]), 1):
        q = entry.get("query", "")
        text += f"{i}. `/guide {q}`\n"
    text += "\nНажмите на запрос чтобы повторить поиск."
    await message.reply(text, parse_mode="Markdown")


@router.message(Command("help"))
async def help_command(message: types.Message) -> None:
    text = (
        " *Полный список команд* \n"
        f"{'─' * 35}\n"
        " *Основные:*\n"
        " /start — Приветствие и быстрые ссылки\n"
        " /all — Показать все категории\n"
        " /guide `<тема>` — Найти гайд (fuzzy + BM25)\n"
        " /aiguide `<текст>` — Умный поиск + AI если гайд не найден\n"
        " /ask `<вопрос>` — Задать вопрос AI по Switch CFW\n"
        " /random `[категория]` — Случайный гайд\n"
        "🆕 /new — Последние добавленные гайды\n"
        " /stats — Статистика базы гайдов\n"
        " /top — Топ категорий\n"
        " /category `<название>` — Гайды по категории (с пагинацией)\n"
        " /cat `<название>` — Псевдоним /category\n"
        "🔥 /trending — Топ гайдов по оценкам\n"
        " /history — Ваши последние поисковые запросы\n"
        " /recommend — Репозитории автора\n\n"
        "⭐ *Избранное:*\n"
        "/fav — Показать избранное\n"
        "/fav add `<тема>` — Добавить гайд\n"
        "/fav remove `<номер>` — Удалить\n\n"
        " *Обратная связь:*\n"
        "/feedback `<текст>` — Предложить новый гайд\n\n"
        " *Inline-режим:*\n"
        "Напиши `@botname запрос` в любом чате!\n\n"
        " *Админ-команды:*\n"
        "/sync, /add\\_guide, /remove\\_guide, /edit\\_guide, /list\\_guides, /admin\\_help\n"
    )
    await message.reply(text, parse_mode="Markdown")
