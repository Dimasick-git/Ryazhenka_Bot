"""Search command handlers: /guide, /aiguide, /ask."""
import asyncio
import hashlib
import logging
import time

from aiogram import Router, types
from aiogram.enums import ChatAction
from aiogram.filters import Command, CommandObject
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from .. import storage
from ..helpers import build_guide_key, escape_html, make_rating_keyboard, safe_send
from ..nlp import search_guides
from ..services.ai import ask_ai, ask_ai_with_history
from .ctx import DIALOG_CTX, DIALOG_CTX_TIME, _cleanup_dialog_ctx

router = Router()

# Per-user conversation history for /ask command
# Key: str(user_id), Value: list of {"role": "user"|"assistant", "content": str}
_ASK_HISTORY: dict[str, list[dict]] = {}
_ASK_HISTORY_MAX_TURNS = 10      # Keep last 10 turns (20 messages)
_ASK_HISTORY_TTL = 1800          # Reset context after 30 min of inactivity (seconds)
_ASK_HISTORY_TS: dict[str, float] = {}  # last-message timestamps per user


def _get_user_history(user_id: str) -> list[dict]:
    """Return conversation history for user, evicting if stale."""
    ts = _ASK_HISTORY_TS.get(user_id, 0)
    if time.time() - ts > _ASK_HISTORY_TTL:
        _ASK_HISTORY.pop(user_id, None)
        _ASK_HISTORY_TS.pop(user_id, None)
    return _ASK_HISTORY.get(user_id, [])


def _append_history(user_id: str, role: str, content: str) -> None:
    """Append a message to the user's history, trimming to the last N turns."""
    hist = _ASK_HISTORY.setdefault(user_id, [])
    hist.append({"role": role, "content": content})
    max_msgs = _ASK_HISTORY_MAX_TURNS * 2
    if len(hist) > max_msgs:
        del hist[:-max_msgs]
    _ASK_HISTORY_TS[user_id] = time.time()


def _clear_user_history(user_id: str) -> int:
    """Clear history for a user, return the number of turns removed."""
    msgs = len(_ASK_HISTORY.pop(user_id, []))
    _ASK_HISTORY_TS.pop(user_id, None)
    return msgs // 2


def cleanup_stale_ask_history() -> int:
    """Purge conversation history entries older than TTL. Called by background task."""
    now = time.time()
    stale = [uid for uid, ts in list(_ASK_HISTORY_TS.items()) if now - ts > _ASK_HISTORY_TTL]
    for uid in stale:
        _ASK_HISTORY.pop(uid, None)
        _ASK_HISTORY_TS.pop(uid, None)
    return len(stale)


async def _register_guide_meta(guide: dict) -> str:
    """Ensure guide metadata exists in GUIDE_RATINGS; return guide_key."""
    guide_key = build_guide_key(guide["url"])
    meta_key = f"_meta_{guide_key}"
    if meta_key not in storage.GUIDE_RATINGS:
        storage.GUIDE_RATINGS[meta_key] = {
            "title": guide["title"],
            "url": guide["url"],
            "category": guide["category"],
        }
        await storage.save_ratings()
    return guide_key


async def _perform_search(message: types.Message, query: str) -> None:
    """Shared search logic for /guide and /aiguide."""
    _cleanup_dialog_ctx()

    if not storage.GUIDES:
        await message.reply(" База гайдов пуста ")
        return

    await storage.add_to_search_history(str(message.from_user.id), query)
    results = await asyncio.to_thread(search_guides, query, 10)

    if not results:
        await message.reply(
            " Не нашёл гайд . Попробуйте:\n"
            "• /guide atmosphere\n• /guide battery\n• /guide emunand\n\n"
            "Или /all для всех категорий."
        )
        return

    best, best_score = results[0]
    if best_score >= 75:
        guide_key = await _register_guide_meta(best)
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
                kb.inline_keyboard.append([InlineKeyboardButton(
                    text=f"Открыть: {doc['title'][:40]}", url=doc["url"],
                )])
            else:
                key = hashlib.md5(doc["title"].encode()).hexdigest()[:16]
                DIALOG_CTX[key] = doc
                DIALOG_CTX_TIME[key] = now
                kb.inline_keyboard.append([InlineKeyboardButton(
                    text=f"Открыть: {doc['title'][:40]}", callback_data=f"open|{key}",
                )])
        await message.reply(text, parse_mode="Markdown", reply_markup=kb if kb.inline_keyboard else None)
        return

    guide_context = ""
    if results:
        lines = [
            f"• {d['title']} ({d['category']}): {d.get('url', '')}"
            for d, sc in results[:3] if sc >= 20
        ]
        guide_context = "\n".join(lines)

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    thinking_msg = await message.reply("🔍 Не нашёл точного совпадения, спрашиваю AI...")
    ai_answer = await ask_ai(query, guide_context)
    if ai_answer:
        reply_text = f" *AI-ответ по запросу:* _{query}_\n\n{ai_answer}"
        if guide_context:
            reply_text += "\n\n Похожие гайды в базе:"
            for doc, score in results[:3]:
                if score >= 20 and doc.get("url"):
                    reply_text += f"\n• [{doc['title']}]({doc['url']})"
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    top_cats = sorted(storage.GUIDES.items(), key=lambda x: len(x[1]), reverse=True)[:3]
    cat_hints = "".join(f"\n• /category `{c}`" for c, _ in top_cats)
    await thinking_msg.edit_text(
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
    if len(query) > 200:
        await message.reply(" Запрос слишком длинный. Максимум 200 символов.")
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
    if len(query) > 200:
        await message.reply(" Запрос слишком длинный. Максимум 200 символов.")
        return

    await storage.add_to_search_history(str(message.from_user.id), query)
    results = await asyncio.to_thread(search_guides, query, 5)

    guide_context = ""
    if results:
        lines = []
        for doc, score in results[:3]:
            if score >= 30:
                lines.append(f"• {doc['title']} ({doc['category']}): {doc.get('url', '')}")
        guide_context = "\n".join(lines)

    best_score = results[0][1] if results else 0
    if best_score >= 75:
        best = results[0][0]
        guide_key = await _register_guide_meta(best)
        await message.reply(
            f" Нашёл гайд в категории *{best['category']}*:\n\n"
            f"*{best['title']}*\n{best['url']}",
            parse_mode="Markdown",
            reply_markup=make_rating_keyboard(guide_key),
        )
        return

    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    thinking_msg = await message.reply("🤖 Думаю...")
    ai_answer = await ask_ai(query, guide_context)

    if ai_answer:
        reply_text = f"🤖 *AI-ответ по запросу:* _{query}_\n\n{ai_answer}"
        if guide_context:
            reply_text += "\n\n Связанные гайды в базе:"
            for doc, score in results[:3]:
                if score >= 30 and doc.get("url"):
                    reply_text += f"\n• [{doc['title']}]({doc['url']})"
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
        return

    await thinking_msg.delete()
    await _perform_search(message, query)


@router.message(Command("ask"))
async def ask_command(message: types.Message, command: CommandObject) -> None:
    """Free-form AI question about Nintendo Switch CFW with multi-turn conversation."""
    query = (command.args or "").strip()
    if not query:
        await message.reply(
            "🤖 *Задай вопрос AI по Nintendo Switch CFW:*\n\n"
            "`/ask как сделать backup NAND?`\n"
            "`/ask в чём разница emuNAND и sysNAND?`\n"
            "`/ask как установить игру через Tinfoil?`\n\n"
            "_Я запоминаю контекст разговора — можно задавать уточняющие вопросы!_\n"
            "Сброс контекста: /ask\_reset",
            parse_mode="Markdown",
        )
        return
    if len(query) > 300:
        await message.reply(" Запрос слишком длинный. Максимум 300 символов.")
        return

    user_id = str(message.from_user.id)
    await message.bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)
    thinking_msg = await message.reply("🤔 Думаю...")

    results = await asyncio.to_thread(search_guides, query, 3)
    guide_context = ""
    if results:
        lines = [f"• {d['title']} ({d['category']}): {d.get('url', '')}" for d, sc in results if sc >= 25]
        guide_context = "\n".join(lines)

    history = _get_user_history(user_id)
    ai_answer = await ask_ai_with_history(query, history, guide_context)

    if ai_answer:
        _append_history(user_id, "user", query)
        _append_history(user_id, "assistant", ai_answer)
        turn_count = len(_ASK_HISTORY.get(user_id, [])) // 2
        turn_badge = f" _[{turn_count} реплик в контексте]_" if turn_count > 1 else ""
        reply_text = f"🤖 *Ответ AI:*{turn_badge}\n\n{ai_answer}"
        if guide_context:
            reply_text += "\n\n📚 Связанные гайды:"
            for doc, score in results[:3]:
                if score >= 25 and doc.get("url"):
                    reply_text += f"\n• [{doc['title']}]({doc['url']})"
        await thinking_msg.edit_text(reply_text, parse_mode="Markdown", disable_web_page_preview=True)
    else:
        await thinking_msg.edit_text(
            "❌ AI недоступен. Попробуй:\n"
            "• /guide — поиск по базе гайдов\n"
            "• /all — все категории\n"
            "• /feedback — предложи добавить гайд"
        )


@router.message(Command("ask_reset"))
async def ask_reset_command(message: types.Message) -> None:
    """Reset the AI conversation context for the current user."""
    user_id = str(message.from_user.id)
    turns = _clear_user_history(user_id)
    if turns:
        await message.reply(
            f"🔄 Контекст разговора сброшен ({turns} реплик удалено).\n"
            "Следующий /ask начнёт новый разговор с нуля.",
        )
    else:
        await message.reply("ℹ️ Контекст пустой — нечего сбрасывать.")
