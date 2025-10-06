import logging
import json
import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from fuzzywuzzy import fuzz

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    print("❌ Ошибка: BOT_TOKEN не найден в переменных окружения!")
    print("Установите переменную окружения BOT_TOKEN с токеном от @BotFather")
    exit(1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    with open("guides.json", "r", encoding="utf-8") as f:
        GUIDES = json.load(f)
except Exception as e:
    GUIDES = {}
    print(f"❌ Ошибка загрузки guides.json: {e}")

def create_categories_keyboard():
    kb = InlineKeyboardMarkup(inline_keyboard=[])
    categories = list(GUIDES.keys())
    
    for i in range(0, len(categories), 2):
        row = []
        row.append(InlineKeyboardButton(text=categories[i], callback_data=f"cat_{i}"))
        if i + 1 < len(categories):
            row.append(InlineKeyboardButton(text=categories[i+1], callback_data=f"cat_{i+1}"))
        kb.inline_keyboard.append(row)
    
    return kb

@dp.message(Command("start"))
async def start(message: types.Message):
    await message.reply(
        "👋 Привет! Я бот-помощник по прошивке Nintendo Switch.\n\n"
        "🔍 Команды:\n"
        "• /guide <тема> — найти гайд (fuzzy search)\n"
        "• /all — показать все категории\n\n"
        "📚 Выберите категорию ниже:",
        reply_markup=create_categories_keyboard()
    )

@dp.message(Command("all"))
async def show_all(message: types.Message):
    if not GUIDES:
        await message.reply("❌ База гайдов пуста")
        return
    
    text = "📚 *Все категории:*\n\n"
    total_guides = 0
    
    for category, guides in GUIDES.items():
        count = len(guides)
        total_guides += count
        text += f"{category} — {count} гайдов\n"
    
    text += f"\n📝 Всего: {total_guides} гайдов в {len(GUIDES)} категориях\n\n"
    text += "Используйте /guide <название> для поиска или выберите категорию:"
    
    await message.reply(text, parse_mode="Markdown", reply_markup=create_categories_keyboard())

@dp.callback_query(F.data.startswith("cat_"))
async def handle_category(callback_query: types.CallbackQuery):
    category_index = int(callback_query.data.split("_")[1])
    categories = list(GUIDES.keys())
    
    if category_index >= len(categories):
        await callback_query.answer("❌ Категория не найдена")
        return
    
    category = categories[category_index]
    guides = GUIDES[category]
    
    text = f"📚 *{category}*\n\n"
    
    for key, url in guides.items():
        text += f"🔹 [{key}]({url})\n"
    
    text += f"\n📝 Всего: {len(guides)} гайдов"
    
    try:
        await callback_query.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True)
    except:
        await callback_query.message.answer(text, parse_mode="Markdown", disable_web_page_preview=True)
    
    await callback_query.answer()

@dp.callback_query(F.data == "back_to_categories")
async def back_to_categories(callback_query: types.CallbackQuery):
    text = (
        "👋 Привет! Я бот-помощник по прошивке Nintendo Switch.\n\n"
        "🔍 Команды:\n"
        "• /guide <тема> — найти гайд (fuzzy search)\n"
        "• /all — показать все категории\n\n"
        "📚 Выберите категорию ниже:"
    )
    
    try:
        await callback_query.message.edit_text(text, reply_markup=create_categories_keyboard())
    except:
        await callback_query.message.answer(text, reply_markup=create_categories_keyboard())
    
    await callback_query.answer()

@dp.message(Command("guide"))
async def send_guide(message: types.Message, command: CommandObject):
    query = command.args
    if not query:
        await message.reply("❌ Укажите тему после команды, например: /guide battery")
        return

    query = query.lower()
    best_match = None
    best_score = 0
    best_category = None

    for category, guides in GUIDES.items():
        for key, url in guides.items():
            score = fuzz.partial_ratio(query, key.lower())
            if score > best_score:
                best_score = score
                best_match = (key, url)
                best_category = category

    if best_match and best_score > 80:
        await message.reply(
            f"✅ Нашёл гайд в категории *{best_category}*:\n\n"
            f"*{best_match[0]}*\n{best_match[1]}",
            parse_mode="Markdown"
        )
    elif best_match and best_score > 50:
        kb_guide = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Открыть", url=best_match[1])]
        ])
        await message.reply(
            f"🤔 Похоже, вы имели в виду:\n\n"
            f"Категория: *{best_category}*\n"
            f"Гайд: *{best_match[0]}*",
            reply_markup=kb_guide,
            parse_mode="Markdown"
        )
    else:
        await message.reply(
            "❌ Не нашёл гайд. Попробуйте:\n"
            "• /guide atmosphere\n"
            "• /guide battery\n"
            "• /guide emunand\n\n"
            "Или используйте /all чтобы увидеть все категории"
        )

@dp.message(Command("гайд"))
async def send_guide_ru(message: types.Message, command: CommandObject):
    await send_guide(message, command)

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🤖 Бот запущен и готов к работе!")
    print(f"📚 Загружено {len(GUIDES)} категорий")
    total = sum(len(guides) for guides in GUIDES.values())
    print(f"📝 Всего гайдов: {total}")
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
