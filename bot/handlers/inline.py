"""Inline query handler."""
import asyncio
import random
import uuid

from aiogram import Router
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from .. import storage
from ..helpers import escape_html
from ..nlp import search_guides

router = Router()


@router.inline_query()
async def inline_guide_search(query: InlineQuery) -> None:
    search_text = query.query.strip()
    results = []

    if not search_text:
        sample = [(c, t, u) for c, g in storage.GUIDES.items() for t, u in g.items() if u]
        random.shuffle(sample)
        for cat, title, url in sample[:20]:
            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title=title,
                input_message_content=InputTextMessageContent(
                    message_text=f" <b>{escape_html(title)}</b>\n {escape_html(cat)}\n{url}",
                    parse_mode="HTML",
                ),
                description=cat,
                url=url,
            ))
    else:
        found = await asyncio.to_thread(search_guides, search_text, 20)
        matched = [(d, sc) for d, sc in found if sc >= 45]
        if matched:
            for doc, _ in matched:
                results.append(InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=doc["title"],
                    input_message_content=InputTextMessageContent(
                        message_text=f" <b>{escape_html(doc['title'])}</b>\n {escape_html(doc['category'])}\n{doc['url']}",
                        parse_mode="HTML",
                    ),
                    description=doc["category"],
                    url=doc.get("url") or None,
                ))
        else:
            results.append(InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="Ничего не найдено",
                input_message_content=InputTextMessageContent(
                    message_text=f" По запросу <b>{escape_html(search_text)}</b> ничего не найдено.\nПопробуй /guide или /all в боте @Ryazhenkabestcfw",
                    parse_mode="HTML",
                ),
                description="Попробуйте другой запрос",
            ))

    await query.answer(results[:20], cache_time=15, is_personal=True)
