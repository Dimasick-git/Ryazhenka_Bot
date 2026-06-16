"""Social handlers: /fav, /feedback."""
import asyncio
import logging

from aiogram import Bot, Router, types
from aiogram.filters import Command, CommandObject

from .. import storage
from ..config import ADMIN_IDS
from ..nlp import search_guides

router = Router()

_FEEDBACK_MAX_LEN = 800


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
        found = await asyncio.to_thread(search_guides, query, 1)
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
            await message.reply(" Максимум 50 гайдов. Удали лишние через /fav remove <номер>.")
            return
        favs.append({"title": entry["title"], "url": url, "category": entry["category"]})
        await storage.save_favorites()
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
        await storage.save_favorites()
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
        await message.reply("✅ Спасибо! Предложение отправлено администраторам.")
    else:
        await message.reply(" Не удалось отправить.\nНапиши напрямую: @Ryazhenkabestcfw")
