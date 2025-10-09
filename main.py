import logging
import json
import os
import asyncio
import aiohttp
import xml.etree.ElementTree as ET
import re
import urllib.parse
import math
from aiogram import Bot, Dispatcher, types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, CommandObject
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

# YT channels persistence: allow managing channels without editing .env by using a small file.
YT_CHANNELS_FILE = 'yt_channels.json'
YT_CHANNELS = []
def _load_yt_channels():
    try:
        if os.path.exists(YT_CHANNELS_FILE):
            with open(YT_CHANNELS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    # fallback to environment variable (comma separated)
    return [c.strip() for c in os.environ.get("YT_CHANNELS", "").split(",") if c.strip()]

def _save_yt_channels(list_channels):
    try:
        with open(YT_CHANNELS_FILE, 'w', encoding='utf-8') as f:
            json.dump(list_channels, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception('Failed saving YT_CHANNELS_FILE')

YT_CHANNELS = _load_yt_channels()
# YouTube pruning and retention settings (can be overridden via env)
try:
    YT_PRUNE_REMOVED = os.environ.get('YT_PRUNE_REMOVED', '1') in ('1', 'true', 'True')
except Exception:
    YT_PRUNE_REMOVED = True
try:
    YT_KEEP_LIMIT = int(os.environ.get('YT_KEEP_LIMIT', '50'))
except Exception:
    YT_KEEP_LIMIT = 50
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")

BOT_TOKEN = os.environ.get("BOT_TOKEN")

# Admin IDs may be provided as comma-separated env var; default to empty list
try:
    ADMIN_IDS = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
except Exception:
    ADMIN_IDS = []

# Optional GitHub token for API usage
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Background sync interval (seconds), default to 1 hour
try:
    SYNC_INTERVAL_SECONDS = int(os.environ.get("SYNC_INTERVAL_SECONDS", "3600"))
except Exception:
    SYNC_INTERVAL_SECONDS = 3600

# Robust fallback: try to read BOT_TOKEN directly from .env if loader missed it
def _read_key_from_env_file(path: str, key: str):
    try:
        if not os.path.exists(path):
            return None
        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith('#') or '=' not in ln:
                    continue
                k, v = ln.split('=', 1)
                if k.strip() == key:
                    val = v.strip().strip('"').strip("'")
                    if val:
                        return val
    except Exception:
        return None
    return None

# YouTube resolution cache to avoid repeated lookups
YT_CACHE_FILE = 'yt_channel_cache.json'
def _load_yt_cache():
    try:
        if os.path.exists(YT_CACHE_FILE):
            with open(YT_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def _save_yt_cache(cache):
    try:
        with open(YT_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        logging.exception('Failed saving YT cache')

YT_CACHE = _load_yt_cache()

if not BOT_TOKEN:
    token_from_env = _read_key_from_env_file('.env', 'BOT_TOKEN')
    if token_from_env:
        os.environ['BOT_TOKEN'] = token_from_env
        BOT_TOKEN = token_from_env


try:
    from Levenshtein import distance as levenshtein_distance
except Exception:
    def levenshtein_distance(a: str, b: str) -> int:
        # simple iterative DP implementation
        if a == b:
            return 0
        la = len(a)
        lb = len(b)
        if la == 0:
            return lb
        if lb == 0:
            return la
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            cur = [i] + [0] * lb
            for j in range(1, lb + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            prev = cur
        return prev[lb]
try:
    from fuzzywuzzy import fuzz, process
    _HAVE_FUZZY = True
except Exception:
    # lightweight fallback using difflib
    from difflib import SequenceMatcher
    _HAVE_FUZZY = False

    class _SimpleFuzz:
        @staticmethod
        def token_set_ratio(a: str, b: str) -> int:
            return int(SequenceMatcher(None, a, b).ratio() * 100)

        @staticmethod
        def partial_ratio(a: str, b: str) -> int:
            return int(SequenceMatcher(None, a, b).ratio() * 100)

    fuzz = _SimpleFuzz()
    process = None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

try:
    with open("guides.json", "r", encoding="utf-8") as f:
        GUIDES = json.load(f)
except Exception as e:
    GUIDES = {}
    print(f"❌ Ошибка загрузки guides.json: {e}")


# --- deduplication utilities: remove duplicate URLs across categories ---
def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        u = urllib.parse.urlparse(url.strip())
        scheme = u.scheme.lower() if u.scheme else 'https'
        netloc = u.netloc.lower()
        path = u.path.rstrip('/')
        # Special-case YouTube URLs: preserve video id
        if 'youtu.be' in netloc:
            # short link: https://youtu.be/VIDEOID
            vid = u.path.lstrip('/')
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        if 'youtube.com' in netloc or 'youtube-nocookie.com' in netloc:
            qs = urllib.parse.parse_qs(u.query)
            if 'v' in qs and qs['v']:
                return f"https://www.youtube.com/watch?v={qs['v'][0]}"
            # shorts format: /shorts/VIDEOID
            parts = [p for p in path.split('/') if p]
            if parts and parts[0] == 'shorts' and len(parts) >= 2:
                return f"https://www.youtube.com/shorts/{parts[1]}"
            # keep channel or other path
            return f"https://{netloc}{path}"
        # Default behaviour for other sites: keep scheme + netloc + path (drop query/fragment)
        return f"{scheme}://{netloc}{path}"
    except Exception:
        return url.strip().lower()

def dedupe_guides() -> int:
    """Remove duplicate URLs across all categories (keep first occurrence). Returns number removed."""
    seen = {}
    removed = 0
    for category in list(GUIDES.keys()):
        entries = GUIDES.get(category, {})
        for title, url in list(entries.items()):
            if not url:
                continue
            n = normalize_url(url)
            if n in seen:
                # duplicate -> remove
                try:
                    del GUIDES[category][title]
                    removed += 1
                except Exception:
                    continue
            else:
                seen[n] = (category, title)
    if removed:
        save_guides()
    return removed

# Run a cleanup pass on load to remove repeated profile links (e.g. https://github.com/Dimasick-git)
try:
    removed_count = dedupe_guides()
    if removed_count:
        logging.info(f"Removed {removed_count} duplicate guide links on startup")
except Exception:
    pass


# persistent small settings file (to keep runtime toggles between restarts)
SETTINGS_PATH = "bot_settings.json"
DEFAULT_SETTINGS = {"auto_resolve_and_add": True}
def load_settings():
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as sf:
                return json.load(sf)
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as sf:
            json.dump(settings, sf, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed saving settings: {e}")

SETTINGS = load_settings()


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
    placeholder_re = re.compile(r"^\s*авто[- ]?гайд\b\s*\d+", re.I)
    for title, url in list(GUIDES[cat].items()):
        # skip numeric placeholder auto-guides (they were autogenerated and don't resolve)
        if placeholder_re.search(title):
            logging.debug(f"Skipping placeholder auto-guide: {title}")
            continue
        if 'duckduckgo.com' in (url or ''):
            found = await resolve_duckduckgo_first(title)
            if found:
                # If configured, move the resolved link into a proper category instead of
                # overwriting the auto-guides bucket. This implements "resolve-first then add".
                if SETTINGS.get('auto_resolve_and_add', True):
                    target_cat = '🔎 Авто-найденные'
                    added = merge_entries_into_category(target_cat, [(title, found)])
                    # remove from auto-guides queue so we don't retry
                    try:
                        del GUIDES[cat][title]
                    except Exception:
                        pass
                    if added:
                        changed.append((title, found))
                else:
                    # legacy behavior: replace url in place
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


@dp.message(Command("toggle_autoresolve"))
async def toggle_autoresolve(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    current = SETTINGS.get('auto_resolve_and_add', True)
    SETTINGS['auto_resolve_and_add'] = not current
    save_settings(SETTINGS)
    await message.reply(f"Настройка auto_resolve_and_add теперь: {SETTINGS['auto_resolve_and_add']}")



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
    # consult cache
    try:
        if identifier in YT_CACHE and YT_CACHE[identifier].get('channel_id'):
            return YT_CACHE[identifier]['channel_id']
    except Exception:
        pass
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
                cid = m.group(1)
                logging.info(f"Resolved channel id from user RSS for {identifier}: {cid}")
                try:
                    YT_CACHE[identifier] = {'channel_id': cid}
                    if identifier.startswith('@'):
                        YT_CACHE[identifier[1:]] = {'channel_id': cid}
                    _save_yt_cache(YT_CACHE)
                except Exception:
                    pass
                return cid
    except Exception as e:
        logging.debug(f"User RSS lookup failed for {identifier}: {e}")
    # fallback: fetch channel page and look for "channelId":"UC..." or meta tags
    try:
        url = f"https://www.youtube.com/{identifier}"
        html = await fetch_xml(url)
        m = re.search(r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]+)"', html)
        if m:
            cid = m.group(1)
            logging.info(f"Resolved channel id from HTML for {identifier}: {cid}")
            try:
                YT_CACHE[identifier] = {'channel_id': cid}
                _save_yt_cache(YT_CACHE)
            except Exception:
                pass
            return cid
        # try alternative: look for /channel/UC... in links
        m2 = re.search(r'/channel/(UC[0-9A-Za-z_-]+)', html)
        if m2:
            cid = m2.group(1)
            logging.info(f"Resolved channel id from HTML link for {identifier}: {cid}")
            try:
                YT_CACHE[identifier] = {'channel_id': cid}
                _save_yt_cache(YT_CACHE)
            except Exception:
                pass
            return cid
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
                        # persist to cache (both the input form and the possible @handle)
                        try:
                            YT_CACHE[identifier] = {'channel_id': mm.group(1)}
                            if identifier.startswith('@'):
                                YT_CACHE[identifier[1:]] = {'channel_id': mm.group(1)}
                            _save_yt_cache(YT_CACHE)
                        except Exception:
                            pass
                        return mm.group(1)
    except Exception:
        pass
    return None


async def fetch_youtube_videos(channel_id: str):
    """Return (channel_title, list_of_(title,url)) for channel uploads using the public RSS feed.
    If channel_title can't be determined, returns (None, entries).
    """
    if not channel_id:
        return None, []
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        text = await fetch_xml(feed_url)
        root = ET.fromstring(text)
        # feed title contains the channel name
        ch_title_el = root.find('{http://www.w3.org/2005/Atom}title')
        channel_title = (ch_title_el.text or '').strip() if ch_title_el is not None else None
        # persist channel_title in cache
        try:
            if channel_title:
                YT_CACHE[channel_id] = YT_CACHE.get(channel_id, {})
                YT_CACHE[channel_id]['channel_id'] = channel_id
                YT_CACHE[channel_id]['title'] = channel_title
                _save_yt_cache(YT_CACHE)
        except Exception:
            pass

        entries = []
        for entry in root.findall('{http://www.w3.org/2005/Atom}entry'):
            title_el = entry.find('{http://www.w3.org/2005/Atom}title')
            link_el = entry.find('{http://www.w3.org/2005/Atom}link')
            pub_el = entry.find('{http://www.w3.org/2005/Atom}published')
            if title_el is None:
                continue
            title = (title_el.text or "").strip()
            url = link_el.attrib.get('href') if link_el is not None else None
            # try to parse date and prefix the title with YYYY-MM-DD for readability
            try:
                if pub_el is not None and pub_el.text:
                    dt = pub_el.text.strip()
                    # expecting ISO 8601-ish format: 2025-10-09T12:34:56+00:00
                    m = re.match(r"(\d{4}-\d{2}-\d{2})", dt)
                    if m:
                        title = f"[{m.group(1)}] {title}"
            except Exception:
                pass
            if url:
                entries.append((title, url))
        return channel_title, entries
    except Exception as e:
        logging.warning(f"Failed fetching YouTube feed for {channel_id}: {e}")
        return None, []


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


async def fetch_github_repos(user_or_org: str, limit: int = 20) -> list:
    """Return list of (name, url, description) for public repos of a GitHub user/org using unauthenticated API.
    Falls back to scraping GitHub HTML if API fails.
    """
    api_url = f"https://api.github.com/users/{user_or_org}/repos?per_page={limit}&type=public&sort=updated"
    try:
        headers = {}
        if GITHUB_TOKEN:
            headers['Authorization'] = f'token {GITHUB_TOKEN}'
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(api_url, timeout=20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    out = []
                    for r in data:
                        out.append((r.get('name'), r.get('html_url'), r.get('description') or ''))
                    return out
    except Exception as e:
        logging.debug(f"GitHub API fetch failed: {e}")
    # fallback: simple HTML scraping of user's repo list page
    try:
        url = f"https://github.com/{user_or_org}?tab=repositories"
        text = await fetch_xml(url)
        repos = []
        for m in re.finditer(r'itemprop="name codeRepository">\s*<a[^>]+href="/[^/]+/([^\"]+)"', text):
            name = m.group(1).strip()
            repos.append((name, f"https://github.com/{user_or_org}/{name}", ''))
            if len(repos) >= limit:
                break
        return repos
    except Exception:
        return []


def save_guides():
    try:
        with open("guides.json", "w", encoding="utf-8") as f:
            json.dump(GUIDES, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Failed to save guides.json: {e}")

def backup_guides():
    try:
        if os.path.exists('guides.json'):
            import shutil, datetime
            dst = f"guides.json.bak.{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}"
            shutil.copyfile('guides.json', dst)
            logging.info(f"Backed up guides.json to {dst}")
    except Exception:
        logging.exception('Failed to backup guides.json')



def merge_entries_into_category(category: str, entries: list):
    """Merge list of (title,url) into GUIDES[category] avoiding duplicates by normalized title."""
    if category not in GUIDES:
        GUIDES[category] = {}
    existing_norm = {normalize(k): k for k in GUIDES[category].keys()}
    # also maintain a map of normalized URLs to keys so we can dedupe videos by URL
    existing_urls = {}
    for k, v in GUIDES[category].items():
        if v:
            existing_urls[normalize_url(v)] = k
    added = 0
    for title, url in entries:
        n = normalize(title)
        # prefer to dedupe by URL when provided (YouTube videos have stable URLs)
        if url:
            nu = normalize_url(url)
            if nu in existing_urls:
                key = existing_urls[nu]
                if GUIDES[category].get(key) != url:
                    GUIDES[category][key] = url
                continue
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
            if url:
                existing_urls[normalize_url(url)] = key
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
            channel_title, yt_entries = await fetch_youtube_videos(cid) if cid else (None, [])
            logging.info(f"Fetched {len(yt_entries)} entries from YouTube channel {cid} ({channel_title})")
            if yt_entries:
                # if we resolved cid from an input like a handle or URL, persist a stable UC id in yt_channels.json
                try:
                    # prefer storing UC id form for stability
                    if cid and not ch.startswith('UC'):
                        # replace the original entry in YT_CHANNELS with the UC id
                        try:
                            idx = YT_CHANNELS.index(ch)
                            YT_CHANNELS[idx] = cid
                            _save_yt_channels(YT_CHANNELS)
                        except ValueError:
                            pass
                except Exception:
                    pass

                # create a per-channel category name for cleanliness
                safe_name = channel_title or ch or cid or 'Видео'
                # sanitize category name
                safe_name = re.sub(r"[^0-9a-zA-Zа-яёА-ЯЁ _\-]", " ", safe_name).strip()
                cat_name = f"YouTube - {safe_name}"

                # optionally sort the entries by date prefix [YYYY-MM-DD] (newest first)
                def _extract_date_pref(tu):
                    t = tu[0]
                    m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", t)
                    if m:
                        return m.group(1)
                    return '1970-01-01'

                try:
                    yt_entries.sort(key=lambda x: _extract_date_pref(x), reverse=True)
                except Exception:
                    pass

                added = merge_entries_into_category(cat_name, yt_entries)
                total_added += added
                # --- Prune removed videos if enabled: remove entries in this category whose URLs are not in the current feed ---
                try:
                    if YT_PRUNE_REMOVED:
                        existing_map = {normalize_url(v): k for k, v in GUIDES.get(cat_name, {}).items() if v}
                        feed_urls = {normalize_url(u) for (_, u) in yt_entries}
                        removed_local = 0
                        for nu, key in list(existing_map.items()):
                            if nu and nu not in feed_urls:
                                try:
                                    del GUIDES[cat_name][key]
                                    removed_local += 1
                                except Exception:
                                    pass
                        if removed_local:
                            logging.info(f"Pruned {removed_local} removed videos from {cat_name}")
                except Exception:
                    pass

                # --- Enforce keep limit: keep newest N entries (by [YYYY-MM-DD] prefix) ---
                try:
                    keys = list(GUIDES.get(cat_name, {}).keys())
                    def _key_date(k):
                        m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", k)
                        return m.group(1) if m else '1970-01-01'
                    # sort keys newest first
                    keys_sorted = sorted(keys, key=lambda x: _key_date(x), reverse=True)
                    if len(keys_sorted) > YT_KEEP_LIMIT:
                        for old in keys_sorted[YT_KEEP_LIMIT:]:
                            try:
                                del GUIDES[cat_name][old]
                            except Exception:
                                pass
                        logging.info(f"Trimmed {len(keys_sorted)-YT_KEEP_LIMIT} old videos from {cat_name}")
                except Exception:
                    pass
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
        "🔍 Часто используемые команды:\n"
        "• /guide <тема> — найти гайд (fuzzy search)\n"
        "• /aiguide <текст> — AI-подобный поиск по гайдам (локально)\n"
        "• /all — показать все категории\n"
        "• /help — полный список команд\n\n"
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
    
    await safe_send(message, text, reply_markup=create_categories_keyboard())

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
        await callback_query.message.edit_text(text, disable_web_page_preview=True, reply_markup=kb_nav)
    except Exception:
        await callback_query.message.answer(text, disable_web_page_preview=True, reply_markup=kb_nav)

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


@dp.callback_query(F.data.startswith("open|"))
async def open_suggestion(callback_query: types.CallbackQuery):
    data = callback_query.data.split('|', 1)[1]
    ctx = DIALOG_CTX.get(data)
    if not ctx:
        await callback_query.answer("❌ Контекст не найден")
        return
    url = ctx.get('url')
    title = ctx.get('title')
    if url:
        try:
            await callback_query.message.reply(f"Открываю гайд: {title}\n{url}")
        except Exception:
            await callback_query.message.answer(f"{title}\n{url}")
    else:
        await callback_query.answer("❌ Нет URL для этого гайда")
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
    # We'll compute a combined score per title to be more tolerant.
    results = []
    q_lower = query.lower()
    # try BM25 if available (build index on first use)
    global BM25_INDEX
    if BM25_INDEX is None:
        BM25_INDEX = _build_bm25_index()
    q_terms = _apply_synonyms(_tokenize(query))
    q_expanded = []
    for t in q_terms:
        q_expanded.append(t)
        q_expanded.extend(_generate_variants(t))
    q_terms = q_expanded
    bm25_scores = _bm25_score(q_terms, BM25_INDEX) if BM25_INDEX and BM25_INDEX['N'] > 0 else None
    for idx_t, t in enumerate(titles):
        t_lower = t.lower()
        # exact substring match -> high score
        if q_lower in t_lower or t_lower in q_lower:
            score = 95
        else:
            try:
                s1 = fuzz.token_set_ratio(q_lower, t_lower)
                s2 = fuzz.partial_ratio(q_lower, t_lower)
                # combined weighted score
                score = int((s1 * 0.7) + (s2 * 0.3))
            except Exception:
                score = 0
            # short-typo fallback using levenshtein distance
            if score < 60 and len(q_lower) <= 8 and len(t_lower) <= 30:
                try:
                    d = levenshtein_distance(q_lower, t_lower)
                    # convert distance to rough similarity
                    maxlen = max(1, max(len(q_lower), len(t_lower)))
                    lev_score = int((1 - (d / maxlen)) * 100)
                    # take the max of both
                    score = max(score, lev_score)
                except Exception:
                    pass
        # if BM25 available, combine its score
        if bm25_scores is not None:
            try:
                bm = bm25_scores[idx_t]
                # normalize bm to 0..1 by a simple scale (not perfect but helps)
                score = max(score, min(1.0, bm / (bm25_scores[0] + 1e-9)))
            except Exception:
                pass
        results.append((t, score))
    # sort by score desc
    results.sort(key=lambda x: x[1], reverse=True)

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
        # suggest matches >= 55% as requested
        if score < 55:
            continue
        entry = next((c for c in choices if c[0] == title), None)
        if entry:
            suggestions.append((entry[0], entry[1], entry[2], score))

    if suggestions:
        text = f"🤔 Ничего точного не найдено, но есть похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for t, cat, url, score in suggestions[:10]:
            text += f"*{t}* — {cat} (score {score})\n"
            # store conversational context so callback can open the url
            kb.inline_keyboard.append([InlineKeyboardButton(text=f"Открыть: {t}", callback_data=f"open|{t}")])
            DIALOG_CTX[t] = {'title': t, 'category': cat, 'url': url}
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


@dp.message(Command("purge_autoguides"))
async def purge_autoguides(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    cat = '🆕 Авто-гайды'
    if cat not in GUIDES:
        await message.reply("ℹ️ Категория автогайдов уже отсутствует.")
        return
    # move to archive
    archive = 'Архив - Авто-гайды'
    GUIDES[archive] = GUIDES.get(archive, {})
    GUIDES[archive].update(GUIDES[cat])
    del GUIDES[cat]
    save_guides()
    await message.reply(f"🗑️ Категория '{cat}' перемещена в '{archive}' и удалена из основных категорий.")


@dp.message(Command("cleanup_duplicates"))
async def cleanup_duplicates_cmd(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    await message.reply("🧹 Выполняю очистку дубликатов...")
    removed = dedupe_guides()
    await message.reply(f"✅ Очистка завершена. Удалено дубликатов: {removed}")


@dp.message(Command("recommend"))
async def recommend_repos(message: types.Message):
    # Show recommended repos for the project's author
    user = 'Dimasick-git'
    await message.reply(f"🔎 Получаю публичные репозитории {user}...")
    repos = await fetch_github_repos(user, limit=20)
    if not repos:
        await message.reply("❌ Не удалось получить репозитории.")
        return
    text = f"📦 Рекомендуемые репозитории {user}:\n\n"
    for name, url, desc in repos[:15]:
        text += f"• [{name}]({url}) — {desc}\n"
    await safe_send(message, text, disable_web_page_preview=True)


@dp.message(Command("admin_help"))
async def admin_help(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    text = (
        "🔐 Админские команды:\n"
        "• /sync — Запустить синхронизацию YouTube/GitHub\n"
        "• /purge_autoguides — Переместить автогайды в архив\n"
        "• /toggle_autoresolve — Вкл/выкл авто-резолв и добавление\n"
        "• /cleanup_duplicates — Удалить повторяющиеся ссылки\n"
        "• /recommend — Показать репозитории Dimasick-git\n"
    )
    await message.reply(text)


@dp.message(Command("help"))
async def help_command(message: types.Message):
    text = (
        "📘 Полный список команд:\n"
        "• /start — Приветствие и быстрые ссылки\n"
        "• /all — Показать все категории\n"
        "• /guide <тема> — Найти гайд (fuzzy search)\n"
        "• /aiguide <текст> — AI-подобный поиск (локально, быстрый)\n"
        "• /sync — (админ) Синхронизация источников\n"
        "• /purge_autoguides — (админ) Переместить автогайды в архив\n"
        "• /cleanup_duplicates — (админ) Удалить дубликаты\n"
        "• /recommend — Показать репозитории автора\n"
        "• /status — (админ) Статус бота и webhook\n"
        "• /restart_polling — (админ) Удалить webhook и предложить перезапуск\n"
        "• /admin_help — Список админ-команд\n"
    )
    await message.reply(text)

def _tokenize(text: str) -> list:
    if not text:
        return []
    text = text.lower()
    # simple tokenization: words and numbers, keep cyrillic
    tokens = re.findall(r"[a-z0-9а-яё]+", text)
    return tokens


def _term_freq(tokens: list) -> dict:
    tf = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def _cosine_sim(a: dict, b: dict) -> float:
    # a and b are term-frequency dicts
    if not a or not b:
        return 0.0
    # compute dot product
    dot = 0
    for k, v in a.items():
        if k in b:
            dot += v * b[k]
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _vec_dot(a, b):
    try:
        return float(sum(x * y for x, y in zip(a, b)))
    except Exception:
        return 0.0


def _vec_norm(a):
    try:
        return float(sum(x * x for x in a) ** 0.5)
    except Exception:
        return 0.0


# small synonyms/aliases table to map common typos or shorthand -> canonical form
SYNONYMS = {
    # battery-related
    'batter': 'battery',
    'batery': 'battery',
    'batt': 'battery',
    'battery': 'battery',
    'batteryfix': 'battery',
    'batteryfixes': 'battery',
    'battery drain': 'battery',
    'batt drain': 'battery',
    'battery drain': 'battery',
    'batteryproblem': 'battery',
    'battery problem': 'battery',

    # emu/emummc/emunand variants
    'emummc': 'emummc',
    'emmummc': 'emummc',
    'emmumc': 'emummc',
    'emumc': 'emummc',
    'emu mmc': 'emummc',
    'emu-mmc': 'emummc',
    'emu-mmc': 'emummc',
    'emu nand': 'emunand',
    'emunand': 'emunand',
    'emu-nand': 'emunand',
    'emunad': 'emunand',
    'emunanc': 'emunand',

    # common acronyms and firmware shorthand
    'cfw': 'custom firmware',
    'atmo': 'atmosphere',
    'atmos': 'atmosphere',
    'atmosphere': 'atmosphere',

    # actions
    'fix': 'fix',
    'repair': 'fix',
    'install': 'install',
    'remove': 'remove',
}

# lightweight stopwords (English + simple Russian fillers) to ignore in ranking
STOP_WORDS = set([
    'the', 'a', 'an', 'to', 'for', 'how', 'howto', 'how-to', 'как', 'что', 'почему', 'про', 'по', 'на',
    'и', 'в', 'с', 'от', 'у', 'как', 'это', 'что', 'редо'
])


def _simple_stem(token: str) -> str:
    """Very small stemmer: remove common English suffixes and trailing punctuation.
    Also remove a few Russian noun suffixes heuristically."""
    t = token.lower()
    # english
    for suf in ('ing', 'ed', 'es', 's'):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            t = t[: -len(suf)]
            break
    # russian light endings
    for suf in ('ами', 'ами', 'ами', 'ов', 'ев', 'ия', 'ий', 'ие'):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            t = t[: -len(suf)]
            break
    return t


# Merge generated synonyms if present (created by scripts/generate_synonyms.py)
try:
    gen_path = os.path.join(os.path.dirname(__file__), 'generated_synonyms.json')
    if os.path.exists(gen_path):
        with open(gen_path, 'r', encoding='utf-8') as gf:
            gen = json.load(gf)
            for k, v in gen.items():
                if k and v and k not in SYNONYMS:
                    SYNONYMS[k] = v
except Exception:
    pass

# explicit manual overrides for EmuMMC/EmuNAND variants (ensure they map to tokens present in guides)
try:
    SYNONYMS.setdefault('emummc', 'emummc')
    SYNONYMS.setdefault('emumc', 'emummc')
    SYNONYMS.setdefault('emu-mmc', 'emummc')
    SYNONYMS.setdefault('emu mmc', 'emummc')
    SYNONYMS.setdefault('emunand', 'emunand')
    SYNONYMS.setdefault('emu nand', 'emunand')
except Exception:
    pass

def _apply_synonyms(tokens: list) -> list:
    return [SYNONYMS.get(t, t) for t in tokens]


# keyboard layout maps for common mistypes (ru<->en)
_EN_TO_RU = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./",
    "йцукенгшщзхъфывапролджэячсмитьбю."
)
_RU_TO_EN = str.maketrans(
    "йцукенгшщзхъфывапролджэячсмитьбю.",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
)


def _fix_keyboard_layout(word: str) -> str:
    # try mapping assuming the word was typed in wrong layout
    try:
        ru = word.translate(_EN_TO_RU)
        en = word.translate(_RU_TO_EN)
        # return the one that contains letters from the opposite set
        # prefer ru if original looks Latin
        if re.search('[a-z]', word) and re.search('[а-яё]', ru):
            return ru
        if re.search('[а-яё]', word) and re.search('[a-z]', en):
            return en
    except Exception:
        pass
    return word


_TRANSLIT_EN_TO_RU = {
    'sh': 'ш', 'ch': 'ч', 'yo': 'ё', 'zh': 'ж', 'yu': 'ю', 'ya': 'я', 'kh': 'х',
}
_TRANSLIT_SIMPLE = str.maketrans({
    'a':'а','b':'б','c':'ц','d':'д','e':'е','f':'ф','g':'г','h':'х','i':'и','j':'й','k':'к','l':'л','m':'м',
    'n':'н','o':'о','p':'п','q':'к','r':'р','s':'с','t':'т','u':'у','v':'в','w':'в','x':'кс','y':'ы','z':'з'
})


def _transliterate_basic(word: str) -> str:
    # rough transliteration from latin to cyrillic for common mistakes
    try:
        w = word
        # handle digraphs first
        for k,v in _TRANSLIT_EN_TO_RU.items():
            w = w.replace(k, v)
        w = w.translate(_TRANSLIT_SIMPLE)
        # keep only cyrillic letters
        w = re.sub(r'[^а-яё]', '', w)
        if w:
            return w
    except Exception:
        pass
    return word


def _normalize_repeats(word: str) -> str:
    # collapse repeated letters: loool -> lol, baaaattery -> bater y (reduce repeats)
    return re.sub(r'(.)\1{2,}', r'\1\1', word)


def _generate_variants(token: str) -> list:
    variants = {token}
    token = token.lower()
    # keyboard layout fixes
    kf = _fix_keyboard_layout(token)
    variants.add(kf)
    # transliteration attempt
    tr = _transliterate_basic(token)
    variants.add(tr)
    # repeats normalization
    nr = _normalize_repeats(token)
    variants.add(nr)
    # try combinations
    variants.add(_normalize_repeats(kf))
    variants.add(_normalize_repeats(tr))
    # keep only non-empty
    # splitting/joining variants: e.g., emu nand -> emunand and vice versa
    new = set()
    for v in list(variants):
        if ' ' in v:
            new.add(v.replace(' ', ''))
            new.add(v.replace(' ', '-'))
        else:
            # try inserting space in camel-ish tokens
            if len(v) > 4:
                # emunand -> emu nand
                if v.startswith('emu') and 'emu' not in ('emu',):
                    new.add('emu ' + v[3:])
        # add stemmed variant
        st = _simple_stem(v)
        new.add(st)
    variants.update(new)
    # filter stopwords and empty
    out = [v for v in variants if v and v not in STOP_WORDS]
    return out


def _escape_markdown_v2(text: str) -> str:
    """Escape text for MarkdownV2 minimally."""
    if not text:
        return text
    # escape characters as per Telegram MarkdownV2
    escape_chars = r"_ * [ ] ( ) ~ ` > # + - = | { } . !"
    for ch in "_ * [ ] ( ) ~ ` > # + - = | { } . !".split():
        text = text.replace(ch, f"\\{ch}")
    return text


async def safe_send(target, text: str, reply_markup=None, disable_web_page_preview=False):
    """Try to send MarkdownV2 escaped text, fallback to plain text if Telegram rejects entities."""
    try:
        # first try MarkdownV2 with escaping
        esc = _escape_markdown_v2(text)
        await target.reply(esc, parse_mode='MarkdownV2', reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
        return
    except Exception as e:
        # fallback: plain text
        try:
            await target.reply(text, reply_markup=reply_markup, disable_web_page_preview=disable_web_page_preview)
            return
        except Exception:
            # last resort: send without reply
            try:
                await target.answer(text)
            except Exception:
                logging.exception('Failed to send message')

def _ngrams(tokens: list, n=2) -> list:
    out = []
    L = len(tokens)
    for k in range(1, n+1):
        if L >= k:
            for i in range(L - k + 1):
                out.append(' '.join(tokens[i:i+k]))
    return out

_RAPIDFUZZ = None
try:
    from rapidfuzz import fuzz as _rf_fuzz
    _RAPIDFUZZ = _rf_fuzz
except Exception:
    _RAPIDFUZZ = None


# --- BM25 index (pure Python) for better offline semantic-like ranking ---
BM25_INDEX = None

def _build_bm25_index():
    """Build BM25 index over guide titles. Returns dict with needed structures."""
    docs = []
    doc_tfs = []
    df = {}
    for cat, items in GUIDES.items():
        if isinstance(items, dict):
            for title, url in items.items():
                docs.append({'title': title, 'category': cat, 'url': url})
        elif isinstance(items, list):
            for it in items:
                title = it.get('title') if isinstance(it, dict) else str(it)
                url = it.get('url') if isinstance(it, dict) else ''
                docs.append({'title': title, 'category': cat, 'url': url})

    for d in docs:
        tokens = _apply_synonyms(_tokenize(d['title']))
        # expand tokens with variants (keyboard/translit/repeats)
        expanded = []
        for t in tokens:
            expanded.append(t)
            expanded.extend(_generate_variants(t))
        tokens = expanded + _ngrams(expanded, n=2)
        tf = {}
        for t in tokens:
            tf[t] = tf.get(t, 0) + 1
        doc_tfs.append(tf)
        for t in set(tokens):
            df[t] = df.get(t, 0) + 1

    N = len(docs)
    idf = {}
    for t, freq in df.items():
        idf[t] = max(0.0, math.log((N - freq + 0.5) / (freq + 0.5) + 1))

    avgdl = 0.0
    lengths = [sum(v for v in tf.values()) for tf in doc_tfs]
    if lengths:
        avgdl = sum(lengths) / len(lengths)

    return {
        'docs': docs,
        'doc_tfs': doc_tfs,
        'idf': idf,
        'avgdl': avgdl,
        'lengths': lengths,
        'N': N,
    }


def _bm25_score(query_terms, index, k1=1.5, b=0.75):
    scores = [0.0] * index['N']
    for i, tf in enumerate(index['doc_tfs']):
        score = 0.0
        dl = index['lengths'][i] if index['lengths'] else 0.0
        for term in query_terms:
            if term not in tf:
                continue
            f = tf.get(term, 0)
            idf = index['idf'].get(term, 0.0)
            denom = f + k1 * (1 - b + b * (dl / (index['avgdl'] + 1e-9)))
            score += idf * (f * (k1 + 1)) / (denom + 1e-9)
        scores[i] = score
    return scores


def _search_guides(query: str, top_n: int = 10):
    """Return list of (doc, combined_score) where doc is {'title','category','url'}.
    Combines BM25 (when available), fuzzy and simple lexical similarity.
    Scores are returned 0..100 (higher better).
    """
    if not query or not GUIDES:
        return []

    # ensure BM25 index
    global BM25_INDEX
    if BM25_INDEX is None:
        BM25_INDEX = _build_bm25_index()

    # Prepare query terms and expansions
    q = query.strip().lower()
    q_tokens = _apply_synonyms(_tokenize(q))
    expanded = []
    for t in q_tokens:
        expanded.append(t)
        expanded.extend(_generate_variants(t))
    # include ngrams (bi-grams)
    expanded += _ngrams(expanded, n=2)

    # BM25
    bm25_scores = None
    if BM25_INDEX and BM25_INDEX['N'] > 0:
        bm25_scores = _bm25_score(expanded, BM25_INDEX)

    # build flat choices to align with BM25 index order
    choices = BM25_INDEX['docs'] if BM25_INDEX else []

    results = []
    # compute normalization factor for BM25
    max_bm = max(bm25_scores) if bm25_scores else 0.0

    for i, doc in enumerate(choices):
        title = doc.get('title', '')
        title_l = title.lower()

        # fuzzy scores (0..100)
        try:
            if _RAPIDFUZZ:
                fscore = _RAPIDFUZZ.token_set_ratio(q, title_l)
            else:
                fscore = fuzz.token_set_ratio(q, title_l)
        except Exception:
            fscore = 0

        # simple lexical overlap: number of query tokens found in title
        qtok = [t for t in q_tokens if t]
        if qtok:
            found = sum(1 for t in qtok if t in title_l)
            lex_score = int((found / len(qtok)) * 100)
        else:
            lex_score = 0

        bm_norm = 0.0
        if bm25_scores is not None:
            bm = bm25_scores[i]
            if max_bm > 0:
                bm_norm = float(bm / (max_bm + 1e-9)) * 100.0

        # combine: BM25(50%), fuzzy(30%), lexical overlap(20%) => final 0..100
        combined = (bm_norm * 0.5) + (fscore * 0.3) + (lex_score * 0.2)

        # fallback boost for short fuzzy-correct matches (distance small)
        if combined < 50 and len(q) <= 12:
            # try levenshtein against title tokens
            try:
                tkns = re.findall(r"[a-z0-9а-яё]+", title_l)
                best_lev = min((levenshtein_distance(q, t) for t in tkns), default=999)
                if best_lev <= 2:
                    combined = max(combined, 65)
            except Exception:
                pass

        results.append((doc, combined))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]


# conversational suggestion storage per chat_id
DIALOG_CTX = {}




@dp.message(Command("aiguide"))
async def handle_aiguide(message: types.Message):
    query = message.text[len('/aiguide'):].strip()
    if not query:
        await message.reply('Пожалуйста, напишите запрос для поиска гайда.')
        return
    try:
        with open('guides.json', 'r', encoding='utf-8') as f:
            guides_data = json.load(f)
    except Exception:
        await message.reply('Ошибка загрузки гайдов.')
        return

    # guides.json is structured as categories -> {title: url}
    # build a flat list of entries with title and optional url/content
    entries = []
    for cat, items in guides_data.items():
        if isinstance(items, dict):
            for title, url in items.items():
                entries.append({'title': title, 'category': cat, 'url': url})
        elif isinstance(items, list):
            for it in items:
                # support list of objects
                title = it.get('title') if isinstance(it, dict) else str(it)
                url = it.get('url') if isinstance(it, dict) else ''
                entries.append({'title': title, 'category': cat, 'url': url})

    if not entries:
        await message.reply('❌ База гайдов пуста')
        return

    # Optionally use ML semantic embeddings if environment variable ML_MODE=1 and sentence-transformers is installed
    use_ml = os.environ.get('ML_MODE', '0') in ('1', 'true', 'True')
    ml_model = None
    if use_ml:
        try:
            # dynamic import to avoid static analyzer false-positives and import-time errors
            import importlib, importlib.util
            if importlib.util.find_spec('sentence_transformers'):
                st = importlib.import_module('sentence_transformers')
                SentenceTransformer = getattr(st, 'SentenceTransformer', None)
                if SentenceTransformer is not None:
                    ml_model = SentenceTransformer('paraphrase-multilingual-MiniLM-L12-v2')
                else:
                    ml_model = None
            else:
                ml_model = None
        except Exception:
            ml_model = None

    # First try the fast BM25 + fuzzy combination
    quick = _search_guides(query, top_n=10)
    if quick and quick[0][1] >= 0.35 * 100:  # scaled 0..100 threshold ~35
        best, score = quick[0]
        if score >= 75:
            # send plain text to avoid Markdown parsing issues from user-provided titles/urls
            await message.reply(f"✅ Найден гайд: {best.get('title')}\nКатегория: {best.get('category')}\n{best.get('url')}")
            return
        # otherwise suggest
        text = "🤔 Похоже, ничего точного не найдено. Вот похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for doc, sc in quick[:10]:
            text += f"{doc.get('title')} — {doc.get('category')} (score {round(sc,2)})\n"
            if doc.get('url'):
                kb.inline_keyboard.append([InlineKeyboardButton(text=f"Открыть: {doc.get('title')}", url=doc.get('url'))])
        # send plain text to avoid entity parsing errors
        await message.reply(text, reply_markup=kb if kb.inline_keyboard else None)
        return

    # Fallback: previous lexical+ML approach if quick attempt failed
    q_tokens = _tokenize(query)
    q_tokens = _apply_synonyms(q_tokens)
    q_tokens = q_tokens + _ngrams(q_tokens, n=2)
    q_tf = _term_freq(q_tokens)

    scored = []
    for e in entries:
        title = e.get('title', '')
        combined_text = title
        tokens = _tokenize(combined_text)
        tokens = _apply_synonyms(tokens)
        tokens = tokens + _ngrams(tokens, n=2)
        tf = _term_freq(tokens)
        sim = _cosine_sim(q_tf, tf)
        # ML similarity if available
        ml_score = 0.0
        if ml_model is not None:
            try:
                q_emb = ml_model.encode([query])[0]
                t_emb = ml_model.encode([title])[0]
                ml_score = float(_vec_dot(q_emb, t_emb) / ((_vec_norm(q_emb) * _vec_norm(t_emb)) + 1e-9))
            except Exception:
                ml_score = 0.0
        # fuzzy boost: prefer rapidfuzz if available
        try:
            if _RAPIDFUZZ:
                fscore = _RAPIDFUZZ.token_set_ratio(query.lower(), title.lower()) / 100.0
            else:
                fscore = fuzz.token_set_ratio(query.lower(), title.lower()) / 100.0
        except Exception:
            fscore = 0.0
        # combine: 60% lexical, 25% ML (if present), 15% fuzzy
        weight_ml = 0.25 if ml_model is not None else 0.0
        weight_lex = 0.6
        weight_fuzz = 0.15
        total = sim * weight_lex + ml_score * weight_ml + fscore * weight_fuzz
        scored.append((e, total))

    scored.sort(key=lambda x: x[1], reverse=True)
    best_entry, best_score = scored[0]

    # thresholds are scaled 0..1; require at least 0.4 to auto-return
    if best_score >= 0.4:
        e = best_entry
        await message.reply(f"✅ Найден гайд: *{e.get('title')}*\nКатегория: {e.get('category')}\n{e.get('url')}", parse_mode='Markdown')
        return

    # otherwise suggest top 5 with scores
    suggestions = [(s[0], s[1]) for s in scored if s[1] >= 0.15][:10]
    if suggestions:
        text = "🤔 Похоже, ничего точного не найдено. Вот похожие варианты:\n\n"
        kb = InlineKeyboardMarkup(inline_keyboard=[])
        for e, sc in suggestions:
            text += f"*{e.get('title')}* — {e.get('category')} (score {round(sc,3)})\n"
            if e.get('url'):
                kb.inline_keyboard.append([InlineKeyboardButton(text=f"Открыть: {e.get('title')}", url=e.get('url'))])
        await message.reply(text, parse_mode='Markdown', reply_markup=kb if kb.inline_keyboard else None)
        return

    await message.reply('❌ Не нашёл подходящих гайдов. Попробуйте уточнить запрос.')


@dp.message(Command("status"))
async def bot_status(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    # basic status
    try:
        webhook_info = await bot.get_webhook_info()
    except Exception:
        webhook_info = None
    text = f"Bot id: {bot.id}\nCategories: {len(GUIDES)}\nTotal guides: {sum(len(g) for g in GUIDES.values())}\nML_MODE: {os.environ.get('ML_MODE', '0')}\nWebhook: {webhook_info}"
    await message.reply(text)


@dp.message(Command("sync"))
async def manual_sync(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    await message.reply("🔄 Запускаю синхронизацию источников...")
    try:
        summary = await sync_sources()
        await message.reply(f"✅ Синхронизация завершена. YouTube добавлено: {summary.get('youtube_added',0)}, GitHub добавлено: {summary.get('github_added',0)}")
    except Exception as e:
        logging.exception(f"Manual sync failed: {e}")
        await message.reply(f"❌ Ошибка при синхронизации: {e}")


@dp.message(Command("yt_add"))
async def yt_add(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    arg = command.args.strip() if command.args else ''
    if not arg:
        await message.reply("Использование: /yt_add <channel_url_or_handle_or_UC_id>")
        return
    if arg in YT_CHANNELS:
        await message.reply("Канал уже в списке.")
        return
    YT_CHANNELS.append(arg)
    _save_yt_channels(YT_CHANNELS)
    await message.reply(f"Добавил канал: {arg}")


@dp.message(Command("yt_remove"))
async def yt_remove(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    arg = command.args.strip() if command.args else ''
    if not arg:
        await message.reply("Использование: /yt_remove <channel_url_or_handle_or_UC_id>")
        return
    try:
        YT_CHANNELS.remove(arg)
        _save_yt_channels(YT_CHANNELS)
        await message.reply(f"Удалил канал: {arg}")
    except ValueError:
        await message.reply("Канал не найден в списке.")


@dp.message(Command("yt_list"))
async def yt_list(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    if not YT_CHANNELS:
        await message.reply("Список YT каналов пуст")
        return
    text = "YouTube каналы в мониторинге:\n"
    for ch in YT_CHANNELS:
        text += f"• {ch}\n"
    await message.reply(text)


@dp.message(Command("yt_cache"))
async def yt_cache_cmd(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    # show a compact cache view
    try:
        items = list(YT_CACHE.items())[:40]
        text = "YT cache (sample):\n"
        for k, v in items:
            text += f"{k} -> {v.get('channel_id','?')} ({v.get('title','')})\n"
        await message.reply(text)
    except Exception as e:
        await message.reply(f"Ошибка при чтении cache: {e}")


@dp.message(Command("yt_prune_on"))
async def yt_prune_on(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    global YT_PRUNE_REMOVED
    YT_PRUNE_REMOVED = True
    await message.reply("✅ Прuning включён: удалённые видео будут удаляться при sync.")


@dp.message(Command("yt_prune_off"))
async def yt_prune_off(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    global YT_PRUNE_REMOVED
    YT_PRUNE_REMOVED = False
    await message.reply("✅ Pruning выключен: удалённые видео НЕ будут удаляться при sync.")


@dp.message(Command("yt_set_limit"))
async def yt_set_limit(message: types.Message, command: CommandObject):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    arg = command.args.strip() if command.args else ''
    if not arg or not arg.isdigit():
        await message.reply("Использование: /yt_set_limit <число> — сколько видео хранить на канал")
        return
    global YT_KEEP_LIMIT
    YT_KEEP_LIMIT = int(arg)
    await message.reply(f"✅ Новый лимит хранения видео установлен: {YT_KEEP_LIMIT}")


@dp.message(Command("restart_polling"))
async def restart_polling_cmd(message: types.Message):
    user_id = message.from_user.id
    if ADMIN_IDS and user_id not in ADMIN_IDS:
        await message.reply("❌ У вас нет прав на выполнение этой операции.")
        return
    await message.reply("🔁 Перезапускаю polling: удаляю webhook и пытаюсь перезапустить")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.exception(f"Failed deleting webhook: {e}")
    # instruct admins to restart the process if desired
    await message.reply("✅ Удалил webhook. Пожалуйста, перезапустите процесс бота на хосте, если polling не восстановится автоматически.")

async def main():
    logging.basicConfig(level=logging.INFO)
    print("🤖 Бот запущен и готов к работе!")
    print(f"📚 Загружено {len(GUIDES)} категорий")
    total = sum(len(guides) for guides in GUIDES.values())
    print(f"📝 Всего гайдов: {total}")
    # start tiny aiohttp health server so Railway can treat this as a web service
    async def _start_health_server():
        from aiohttp import web

        async def handle_health(request):
            return web.Response(text="ok")

        async def handle_yt_latest(request):
            # collect latest N videos across YouTube categories
            try:
                items = []
                for cat, entries in GUIDES.items():
                    if cat.startswith('YouTube -'):
                        for title, url in entries.items():
                            items.append((cat, title, url))
                # sort by date prefix in title
                def _dkey(t):
                    m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", t[1])
                    return m.group(1) if m else '1970-01-01'
                items.sort(key=lambda x: _dkey(x), reverse=True)
                html = '<html><body><h1>Latest YouTube videos</h1><ul>'
                for cat, title, url in items[:100]:
                    html += f'<li><strong>{cat}</strong>: <a href="{url}">{title}</a></li>'
                html += '</ul></body></html>'
                return web.Response(text=html, content_type='text/html')
            except Exception:
                return web.Response(text='error', status=500)

        app = web.Application()
        app.add_routes([web.get('/health', handle_health), web.get('/yt_latest', handle_yt_latest)])
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, '0.0.0.0', int(os.environ.get('PORT', 8080)))
        try:
            await site.start()
        except OSError as e:
            logging.warning(f"Health server failed to bind port {os.environ.get('PORT', 8080)}: {e}")
            # continue without health server

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
        # start health server
        try:
            asyncio.create_task(_start_health_server())
        except Exception:
            logging.exception("Health server failed to start")
    # Log webhook info at startup to help debug TelegramConflictError
    try:
        info = await bot.get_webhook_info()
        logging.info(f"Webhook info at startup: {info}")
    except Exception as e:
        logging.warning(f"Could not fetch webhook info at startup: {e}")
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

    # Remove any webhook (avoids TelegramConflictError when switching from webhook to long polling)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        logging.exception("Failed to delete webhook (may be none)")

    # Start polling. If another polling instance exists, aiogram will retry internally.
    await dp.start_polling(bot, skip_updates=True)

if __name__ == "__main__":
    asyncio.run(main())
