from aiogram import Bot, Dispatcher, executor, types
import json

# Загружаем базу
with open("guides.json", "r", encoding="utf-8") as f:
    GUIDES = json.load(f)

BOT_TOKEN = "8279939836:AAGyuLLWMgyMkW6HmLM2fAC2kibKYCfWMeA"
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot)

@dp.message_handler(commands=['guide', 'гайд'])
async def send_guide(message: types.Message):
    query = message.get_args().lower()
    for key, url in GUIDES.items():
        if key in query:
            await message.reply(f"✅ Гайд по '{key}':\n{url}")
            return
    await message.reply("❌ Не нашёл гайд. Попробуй: прошивка, atmosphere, hekate, emunand, fuse")

if name == 'main':
    executor.start_polling(dp, skip_updates=True)