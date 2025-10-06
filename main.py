import logging
import json
import os
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
import re
import urllib.parse
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
from fuzzywuzzy import fuzz, process

def _load_dotenv(path='.env'):
    """Simple .env loader: set variables from a .env file if they are not already in os.environ."""
    try:
        if not os.path.exists(path):
            return
        with open(path, 'r', encoding='utf-8') as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith('#') or '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass


# Load .env so local runs pick up values without external deps
_load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# support multiple channels (comma-separated). Items can be channel_id (starts with UC) or username
YT_CHANNELS = [c.strip() for c in os.environ.get("YT_CHANNELS", "chipovchik,UCjtFvdgneo1vhSAggJUJeMw").split(",") if c.strip()]
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Dimasick-git/Ryzhenka")
SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", 3600))
admin_env = os.environ.get("ADMIN_IDS", "")
ADMIN_IDS = [int(x) for x in admin_env.split(",") if x.strip().isdigit()]
# fallback: add user's id provided in chat if no admins configured
if not ADMIN_IDS:
    try:
        ADMIN_IDS = [2072467087]
    except Exception:
        ADMIN_IDS = []

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


def normalize(text: str) -> str:
    """Lowercase, remove punctuation and extra spaces for deduplication/search."""
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^a-z0-9а-яё\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


async def fetch_xml(url: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=30) as resp:
            resp.raise_for_status()
            return await resp.text()


ALLOWED_DOMAINS = [
    'github.com', 'rentry.org', 'github.io', 'gamebrew.org', 'gbatemp.net'
]


def extract_first_allowed_link_from_html(html: str) -> str:
    """Parse DuckDuckGo HTML and return the first allowed-domain link if any."""
    # find all hrefs
    hrefs = re.findall(r'href="([^"]+)"', html)
    for h in hrefs:
        try:
            # handle DDG redirects like /l/?kh=-1&uddg=<encoded>
            parsed = urllib.parse.urlparse(h)
            if parsed.path.startswith('/l/'):
                qs = urllib.parse.parse_qs(parsed.query)
                uddg = qs.get('uddg') or qs.get('uddg[]')
                if uddg:
                    target = urllib.parse.unquote(uddg[0])
                    net = urllib.parse.urlparse(target).netloc
                    for d in ALLOWED_DOMAINS:
                        if d in net:
                            return target
            else:
                net = parsed.netloc
                for d in ALLOWED_DOMAINS:
                    if d in net:
                        return h
        except Exception:
            continue
    return None


async def resolve_duckduckgo_first(title: str) -> str:
    """Query DuckDuckGo HTML endpoint and return first allowed-domain result or None."""
    query = f"{title} Nintendo Switch site:github.com OR site:rentry.org OR site:github.io OR site:gamebrew.org OR site:gbatemp.net"
    url = 'https://duckduckgo.com/html/'
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data={'q': query}, timeout=30) as resp:
                text = await resp.text()
                return extract_first_allowed_link_from_html(text)
    except Exception as e:
        logging.warning(f"DDG lookup failed for '{title}': {e}")
        return None


async def resolve_auto_guides_links(notify_admins: bool = True):
    """Go through auto-guides and replace DDG search links with direct links when found.
    Notify admins about new direct links.
    """
    cat = '🆕 Авто-гайды'
    if cat not in GUIDES:
        return
    changed = []
    for title, url in list(GUIDES[cat].items()):
        if 'duckduckgo.com' in (url or ''):
            found = await resolve_duckduckgo_first(title)
            if found:
                GUIDES[cat][title] = found
                changed.append((title, found))
    if changed:
        save_guides()
        logging.info(f"Resolved {len(changed)} auto-guides to direct links")
        if notify_admins and ADMIN_IDS:
            msg = "🔎 Найдены прямые ссылки для авто-дайдов:\n"
            for t, u in changed[:10]:
                msg += f"• {t}: {u}\n"
            # send to admins
            for aid in ADMIN_IDS:
                try:
                    await bot.send_message(aid, msg)
                except Exception:
                    logging.exception(f"Failed notifying admin {aid}")



async def resolve_channel_id(identifier: str) -> str:
    """Resolve a YouTube identifier to a channel_id (UC...). If identifier already starts with UC, return it.
    Tries RSS user feed, then HTML lookup for channelId in page.
    """
    if not identifier:
        return None
    identifier = identifier.strip()
    # If identifier looks like a direct channel id
    if identifier.startswith("UC"):
        return identifier
    # If identifier is a full URL, extract path
    if identifier.startswith('http') or 'youtube.com' in identifier:
        try:
            parsed = urllib.parse.urlparse(identifier)
            path = parsed.path or ''
            # /channel/UCxxxx
            m = re.search(r'/channel/(UC[0-9A-Za-z_-]+)', path)
            if m:
                return m.group(1)
            # /@handle or /c/name or /user/name
            m2 = re.search(r'/@([^/]+)', path)
            if m2:
                identifier = m2.group(1)
            else:
                m3 = re.search(r'/c/([^/]+)', path)
                if m3:
                    identifier = m3.group(1)
                else:
                    m4 = re.search(r'/user/([^/]+)', path)
                    if m4:
                        identifier = m4.group(1)
        except Exception:
            pass
    # If identifier starts with @, treat as handle
    if identifier.startswith('@'):
        identifier = identifier[1:]
    # try user RSS (some channels expose ?user=username)
    try:
        feed_url = f"https://www.youtube.com/feeds/videos.xml?user={identifier}"
        text = await fetch_xml(feed_url)
        if text and '<entry>' in text:
            # try to extract <yt:channelId>...</yt:channelId>
            m = re.search(r'<yt:channelId>(UC[0-9A-Za-z_-]+)</yt:channelId>', text)
            if m:
                logging.info(f"Resolved channel id from user RSS for {identifier}: {m.group(1)}")
                return m.group(1)
    except Exception as e:
        logging.debug(f"User RSS lookup failed for {identifier}: {e}")
    # fallback: fetch channel page and look for "channelId":"UC..." or meta tags
    try:
        url = f"https://www.youtube.com/{identifier}"
        html = await fetch_xml(url)
        m = re.search(r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]+)"', html)
        if m:
            logging.info(f"Resolved channel id from HTML for {identifier}: {m.group(1)}")
            return m.group(1)
        # try alternative: look for /channel/UC... in links
        m2 = re.search(r'/channel/(UC[0-9A-Za-z_-]+)', html)
        if m2:
            logging.info(f"Resolved channel id from HTML link for {identifier}: {m2.group(1)}")
            return m2.group(1)
    except Exception as e:
        logging.debug(f"HTML lookup failed for {identifier}: {e}")

    # As a last resort try a DuckDuckGo search for the channel and look for /channel/ links
    try:
        ddg_url = 'https://duckduckgo.com/html/'
        q = f"{identifier} site:youtube.com/channel"
        async with aiohttp.ClientSession() as session:
            async with session.post(ddg_url, data={'q': q}, timeout=20) as resp:
                text = await resp.text()
                m = re.search(r'href="([^"]*/channel/(UC[0-9A-Za-z_-]+)[^"]*)"', text)
                if m:
                    # extract the channel id
                    mm = re.search(r'/channel/(UC[0-9A-Za-z_-]+)', m.group(1))
                    if mm:
                        logging.info(f"Resolved channel id via DDG for {identifier}: {mm.group(1)}")
                        return mm.group(1)
    except Exception:
        pass
    return None


async def fetch_youtube_videos(channel_id: str) -> list:
    """Return list of (title, url) for channel uploads using the public RSS feed."""
    if not channel_id:
        return []
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        text = await fetch_xml(feed_url)
        root = ET.fromstring(text)
        entries = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title_el = entry.find('{http://www.w3.org/2005/Atom}title')
            link_el = entry.find('{http://www.w3.org/2005/Atom}link')
            if title_el is None:
                continue
            title = title_el.text or ""
            url = link_el.attrib.get('href') if link_el is not None else None
            if url:
                entries.append((title, url))
        return entries
    except Exception as e:
        logging.warning(f"Failed fetching YouTube feed: {e}")
        return []


async def fetch_github_releases(repo: str) -> list:
    """Return list of (title, url) from repo releases atom feed."""
    if not repo:
        return []
    feed_url = f"https://github.com/{repo}/releases.atom"
    try:
        text = await fetch_xml(feed_url)
        root = ET.fromstring(text)
        entries = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title_el = entry.find('{http://www.w3.org/2005/Atom}title')
            link_el = entry.find('{http://www.w3.org/2005/Atom}link')
            if title_el is None:
                continue
            title = title_el.text or ""
            url = link_el.attrib.get('href') if link_el is not None else None
            if url:
                entries.append((title, url))
        return entries
    except Exception as e:
        logging.warning(f"Failed fetching GitHub releases: {e}")
        return []


def save_guides():
    try:
        with open("guides.json", "w", encoding="utf-8") as f:
            json.dump(GUIDES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save guides.json: {e}")


def merge_entries_into_category(category: str, entries: list):
    """Merge list of (title,url) into GUIDES[category] avoiding duplicates by normalized title."""
    if category not in GUIDES:
        GUIDES[category] = {}
    existing_norm = {normalize(k): k for k in GUIDES[category].keys()}
    added = 0
    for title, url in entries:
        n = normalize(title)
        if n in existing_norm:
            # if url changed, update
            key = existing_norm[n]
            if GUIDES[category].get(key) != url:
                GUIDES[category][key] = url
        else:
            # ensure unique key by appending short suffix if needed
            key = title
            suffix = 1
            while key in GUIDES[category]:
                suffix += 1
                key = f"{title} ({suffix})"
            GUIDES[category][key] = url
            existing_norm[n] = key
            added += 1
    return added


async def sync_sources():
    """Fetch YouTube and GitHub feeds and merge into GUIDES. Returns summary."""
    summary = {"youtube_added": 0, "github_added": 0}
    try:
        total_added = 0
        for ch in YT_CHANNELS:
            # resolve to channel id if needed
            cid = ch
            if not cid.startswith('UC'):
                resolved = await resolve_channel_id(ch)
                if resolved:
                    cid = resolved
            logging.info(f"Fetching YouTube for channel identifier '{ch}' resolved to '{cid}'")
            yt_entries = await fetch_youtube_videos(cid) if cid else []
            logging.info(f"Fetched {len(yt_entries)} entries from YouTube channel {cid}")
            if yt_entries:
                added = merge_entries_into_category('YouTube - Видео', yt_entries)
                total_added += added
        summary['youtube_added'] = total_added
    except Exception as e:
        logging.warning(f"YouTube sync failed: {e}")

    try:
        gh_entries = await fetch_github_releases(GITHUB_REPO) if GITHUB_REPO else []
        if gh_entries:
            # merge into existing Прошивка / CFW category to avoid duplicates
            summary['github_added'] = merge_entries_into_category('📦 Прошивка и CFW', gh_entries)
    except Exception as e:
        logging.warning(f"GitHub sync failed: {e}")

    save_guides()
    return summary

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

    text += f"\n📝 Всего: {len(guides)} гайдов\n\n"
    # navigation
    kb_nav = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅ Назад", callback_data="back_to_categories")]
    ])
    
    try:
        await callback_query.message.edit_text(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb_nav)
    except:
        await callback_query.message.answer(text, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=kb_nav)
    
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
    # fuzzy search across all guide titles using process.extract
    query = query.strip()
    choices = []  # list of (title, category, url)
    for category, guides in GUIDES.items():
        for title, url in guides.items():
            choices.append((title, category, url))

    if not choices:
        await message.reply("❌ База гайдов пуста")
        return

    # build mapping for process.extract
    titles = [c[0] for c in choices]
    try:
        raw_results = process.extract(query, titles, scorer=fuzz.token_set_ratio, limit=5)
    except Exception as e:
        logging.exception(f"Fuzzy search failed: {e}")
        raw_results = []

    # normalize results to list of (title, score)
    results = []
    for r in raw_results:
        if not r:
            continue
        if isinstance(r, tuple) or isinstance(r, list):
            if len(r) >= 2:
                results.append((r[0], r[1]))
            else:
                results.append((r[0], 0))
        else:
            results.append((r, 0))

    if not results:
        await message.reply(
            "❌ Не нашёл гайд. Попробуйте:\n"
            "• /guide atmosphere\n"
            "• /guide battery\n"
            "• /guide emunand\n\n"
            "Или используйте /all чтобы увидеть все категории"
        )
        return

    best_title, best_score = results[0]
    matched = next((c for c in choices if c[0] == best_title), None)

    if matched and best_score >= 75:
        title, category, url = matched
        await message.reply(
            f"✅ Нашёл гайд в категории *{category}* (оценка {best_score}):\n\n"
            f"*{title}*\n{url}",
            parse_mode="Markdown"
        )
        return

    # if no high-score match, show top suggestions with buttons
    suggestions = []
    for title, score in results:
        if score < 40:
            continue
        entry = next((c for c in choices if c[0] == title), None)
        if entry:
            suggestions.append((entry[0], entry[1], entry[2], score))

    if suggestions:
        text = f"🤔 Ничего точного не найдено, но есть похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for t, cat, url, score in suggestions[:10]:
            text += f"*{t}* — {cat} (score {score})\n"
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"Открыть: {t}", url=url)])
        await message.reply(text, parse_mode="Markdown", reply_markup=kb)
        return

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


@dp.message(Command("sync"))
async def manual_sync(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение синхронизации.")
        return
    await message.reply("🔁 Запускаю синхронизацию источников...")
    summary = await sync_sources()
    await message.reply(f"✅ Синхронизация завершена. YouTube добавлено: {summary['youtube_added']}, GitHub добавлено: {summary['github_added']}")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🤖 Бот запущен и готов к работе!")
    print(f"📚 Загружено {len(GUIDES)} категорий")
    total = sum(len(guides) for guides in GUIDES.values())
    print(f"📝 Всего гайдов: {total}")
    # start periodic sync background task if configured
    async def background_sync():
        await asyncio.sleep(5)
        while True:
            try:
                summary = await sync_sources()
                logging.info(f"Background sync completed: {summary}")
            except Exception as e:
                logging.exception(f"Background sync failed: {e}")
            await asyncio.sleep(SYNC_INTERVAL_SECONDS)

    if (YT_CHANNELS and any(YT_CHANNELS)) or GITHUB_REPO:
        asyncio.create_task(background_sync())
        # also start resolver loop
        async def background_resolver():
            await asyncio.sleep(10)
            while True:
                try:
                    await resolve_auto_guides_links()
                except Exception as e:
                    logging.exception(f"Background resolver failed: {e}")
                await asyncio.sleep(max(600, SYNC_INTERVAL_SECONDS))

        asyncio.create_task(background_resolver())

    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
