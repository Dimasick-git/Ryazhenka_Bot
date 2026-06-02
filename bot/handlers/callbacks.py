"""Callback query handlers: category nav, ratings, favorites."""
from aiogram import F, Router, types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import storage
from ..helpers import cat_cb, create_categories_keyboard, make_rating_keyboard
from .user import DIALOG_CTX

router = Router()

_PAGE_SIZE = 15


def _build_category_page(category: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    guides = storage.GUIDES[category]
    items = list(guides.items())
    total = len(items)
    total_pages = max(1, (total + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))

    start = page * _PAGE_SIZE
    chunk = items[start : start + _PAGE_SIZE]

    text = f" *{category}*\n"
    if total_pages > 1:
        text += f"_Страница {page + 1}/{total_pages}_ — всего {total} гайдов\n"
    text += "\n"
    for key, url in chunk:
        if url:
            text += f"• [{key}]({url})\n"
        else:
            text += f"• {key}\n"
    if total_pages == 1:
        text += f"\n Всего: {total} гайдов\n"

    nav_row = []
    h = cat_cb(category)
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="◀ Назад", callback_data=f"cat|{h}|{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ▶", callback_data=f"cat|{h}|{page + 1}"))

    kb = InlineKeyboardMarkup(inline_keyboard=[])
    if nav_row:
        kb.inline_keyboard.append(nav_row)
    kb.inline_keyboard.append([InlineKeyboardButton(text="⬅ К категориям", callback_data="back_to_categories")])
    return text, kb


@router.callback_query(F.data.startswith("cat|"))
async def handle_category(callback_query: types.CallbackQuery) -> None:
    parts = callback_query.data.split("|")
    cat_hash = parts[1]
    page = int(parts[2]) if len(parts) >= 3 and parts[2].lstrip("-").isdigit() else 0

    category = next((c for c in storage.GUIDES if cat_cb(c) == cat_hash), None)
    if category is None:
        await callback_query.answer(" Категория не найдена")
        return

    text, kb = _build_category_page(category, page)
    try:
        await callback_query.message.edit_text(
            text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
        )
    except Exception:
        await callback_query.message.answer(
            text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb
        )
    await callback_query.answer()


@router.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback_query: types.CallbackQuery) -> None:
    text = (
        " *Ryazhenka Bot* — инженерный помощник по прошивке Nintendo Switch\n\n"
        " Команды:\n• /guide `<тема>` — найти гайд\n"
        "• /all — показать все категории\n"
        "• /help — полный список команд\n\n"
        " Выберите категорию ниже:"
    )
    try:
        await callback_query.message.edit_text(
            text, parse_mode="Markdown", reply_markup=create_categories_keyboard()
        )
    except Exception:
        await callback_query.message.answer(
            text, parse_mode="Markdown", reply_markup=create_categories_keyboard()
        )
    await callback_query.answer()


@router.callback_query(F.data.startswith("open|"))
async def open_suggestion(callback_query: types.CallbackQuery) -> None:
    key = callback_query.data.split("|", 1)[1]
    doc = DIALOG_CTX.get(key)
    if not doc:
        await callback_query.answer(" Контекст не найден")
        return
    url = doc.get("url")
    title = doc.get("title")
    if url:
        try:
            await callback_query.message.reply(f"Открываю гайд: {title}\n{url}")
        except Exception:
            await callback_query.message.answer(f"{title}\n{url}")
        await callback_query.answer()
    else:
        await callback_query.answer(" Нет URL для этого гайда")


@router.callback_query(F.data.startswith("rate|"))
async def handle_rating(callback_query: types.CallbackQuery) -> None:
    parts = callback_query.data.split("|", 2)
    if len(parts) != 3:
        await callback_query.answer(" Ошибка")
        return
    _, direction, guide_key = parts
    user_id = str(callback_query.from_user.id)
    voted_key = f"_voted_{user_id}|{guide_key}"
    if storage.GUIDE_RATINGS.get(voted_key):
        await callback_query.answer("Вы уже оценили этот гайд!")
        return
    ratings = storage.GUIDE_RATINGS.setdefault(guide_key, {"up": 0, "down": 0})
    if direction == "up":
        ratings["up"] = ratings.get("up", 0) + 1
        await callback_query.answer(" Спасибо за оценку!")
    else:
        ratings["down"] = ratings.get("down", 0) + 1
        await callback_query.answer(" Спасибо за оценку!")
    storage.GUIDE_RATINGS[voted_key] = True
    await storage.save_ratings()
    try:
        await callback_query.message.edit_reply_markup(reply_markup=make_rating_keyboard(guide_key))
    except Exception:
        pass


@router.callback_query(F.data.startswith("favadd|"))
async def favadd_callback(callback_query: types.CallbackQuery) -> None:
    guide_key = callback_query.data.split("|", 1)[1]
    user_id = str(callback_query.from_user.id)
    entry = storage.GUIDE_RATINGS.get(f"_meta_{guide_key}")
    if not entry:
        await callback_query.answer(" Используй /fav add <тема>")
        return
    title, url, category = entry.get("title", ""), entry.get("url", ""), entry.get("category", "")
    if not url:
        await callback_query.answer(" У гайда нет ссылки.")
        return
    favs = storage.USER_FAVORITES.setdefault(user_id, [])
    if any(f["url"] == url for f in favs):
        await callback_query.answer("⭐ Уже в избранном!")
        return
    if len(favs) >= 50:
        await callback_query.answer(" Максимум 50 гайдов в избранном.")
        return
    favs.append({"title": title, "url": url, "category": category})
    await storage.save_favorites()
    await callback_query.answer(f"⭐ Добавлено: {title[:40]}")
