"""Pure utility functions: formatting, safe send, keyboard builders."""
import hashlib
import logging
import re
import urllib.parse
from typing import Optional

from aiogram import types
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from . import storage


def escape_html(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


async def safe_send(target, text: str, reply_markup=None, disable_web_page_preview: bool = False) -> None:
    try:
        await target.reply(
            text, parse_mode="Markdown", reply_markup=reply_markup,
            disable_web_page_preview=disable_web_page_preview,
        )
        return
    except Exception:
        pass
    try:
        await target.reply(text, reply_markup=reply_markup,
                           disable_web_page_preview=disable_web_page_preview)
        return
    except Exception:
        pass
    try:
        await target.answer(text)
    except Exception:
        logging.exception("Failed to send message")


def make_rating_keyboard(guide_key: str) -> InlineKeyboardMarkup:
    r = storage.GUIDE_RATINGS.get(guide_key, {"up": 0, "down": 0})
    up, down = r.get("up", 0), r.get("down", 0)
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f" {up}", callback_data=f"rate|up|{guide_key}"),
        InlineKeyboardButton(text=f" {down}", callback_data=f"rate|down|{guide_key}"),
        InlineKeyboardButton(text="⭐ В избранное", callback_data=f"favadd|{guide_key}"),
    ]])


def cat_cb(category: str) -> str:
    return hashlib.md5(category.encode("utf-8")).hexdigest()[:12]


def create_categories_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    categories = list(storage.GUIDES.keys())
    for i in range(0, len(categories), 2):
        row = [InlineKeyboardButton(text=categories[i], callback_data=f"cat|{cat_cb(categories[i])}")]
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(text=categories[i + 1], callback_data=f"cat|{cat_cb(categories[i + 1])}"))
        kb.inline_keyboard.append(row)
    return kb


def build_guide_key(url: str) -> str:
    return hashlib.md5(url.encode("utf-8")).hexdigest()[:16]
