"""Discovery handlers: /random, /new, /category, /top, /trending."""
import random
from difflib import SequenceMatcher

from aiogram import Router, types
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import storage
from ..helpers import cat_cb, create_categories_keyboard, make_rating_keyboard

try:
    from rapidfuzz import fuzz as _rfuzz
    def _cat_score(q: str, cat: str) -> float:
        c = cat.lower()
        return max(_rfuzz.token_set_ratio(q, c), _rfuzz.partial_ratio(q, c))
except ImportError:
    def _cat_score(q: str, cat: str) -> float:
        return SequenceMatcher(None, q, cat.lower()).ratio() * 100

router = Router()

_GUIDES_PER_CAT_PAGE = 15


def compute_ratings() -> tuple:
    """Parse GUIDE_RATINGS into (scores, meta) dicts.

    scores: {guide_key: net_score}
    meta:   {guide_key: {title, url, category}}
    """
    scores: dict = {}
    meta: dict = {}
    for key, val in storage.GUIDE_RATINGS.items():
        if key.startswith("_meta_"):
            meta[key[len("_meta_"):]] = val
        elif isinstance(val, dict):
            up = val.get("up", 0)
            down = val.get("down", 0)
            if up + down > 0:
                scores[key] = up - down
    return scores, meta


@router.message(Command("random"))
async def random_guide(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip().lower()
    matching = {c: g for c, g in storage.GUIDES.items() if query in c.lower()} if query else storage.GUIDES
    all_entries = [(t, u, c) for c, g in matching.items() for t, u in g.items() if u]
    if not all_entries:
        await message.reply(
            "❌ Гайды не найдены."
            + ("💡 Попробуй /random без аргументов или /all." if query else "")
        )
        return
    title, url, cat = random.choice(all_entries)
    await message.reply(
        f"🎲 *Случайный гайд*\n\n📁 Категория: {cat}\n[{title}]({url})",
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
            "📭 История добавлений пока пуста.\n"
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


@router.message(Command("top"))
async def top_categories(message: types.Message) -> None:
    if not storage.GUIDES:
        await message.reply("📭 База гайдов пуста")
        return
    sorted_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)[:10]
    total = sum(len(g) for g in storage.GUIDES.values())
    text = f" *Топ категорий*\n{'─' * 35}\n"
    for i, (cat, guides) in enumerate(sorted_cats, 1):
        pct = len(guides) * 100 // max(total, 1)
        text += f"{i}. {cat} — {len(guides)} гайдов ({pct}%)\n"
    await message.reply(text, parse_mode="Markdown", reply_markup=create_categories_keyboard())


@router.message(Command("category"))
@router.message(Command("cat"))
async def category_guides(message: types.Message, command: CommandObject) -> None:
    query = (command.args or "").strip().lower()
    if not storage.GUIDES:
        await message.reply("📭 База гайдов пуста")
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

    scores, meta = compute_ratings()
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
