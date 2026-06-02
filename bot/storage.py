"""All persistent state: in-memory dicts + atomic file I/O."""
import json
import logging
import os
import re
import tempfile
import urllib.parse
from typing import Optional

# ── File paths ────────────────────────────────────────────────
GUIDES_FILE = "guides.json"
FAVORITES_FILE = "favorites.json"
RATINGS_FILE = "ratings.json"
GUIDES_META_FILE = "guides_meta.json"
SETTINGS_PATH = "bot_settings.json"
YT_CHANNELS_FILE = "yt_channels.json"
YT_CACHE_FILE = "yt_channel_cache.json"
SEARCH_HISTORY_FILE = "search_history.json"

DEFAULT_SETTINGS = {"auto_resolve_and_add": True, "yt_prune_removed": True, "yt_keep_limit": 50}

# ── In-memory state ───────────────────────────────────────────
GUIDES: dict = {}
USER_FAVORITES: dict = {}
GUIDE_RATINGS: dict = {}
GUIDES_META: dict = {}
SETTINGS: dict = {}
YT_CHANNELS: list = []
YT_CACHE: dict = {}
SEARCH_HISTORY: dict = {}  # user_id -> [{"query": str, "ts": float}, ...]

try:
    YT_PRUNE_REMOVED: bool = os.environ.get("YT_PRUNE_REMOVED", "1") in ("1", "true", "True")
except Exception:
    YT_PRUNE_REMOVED = True

try:
    YT_KEEP_LIMIT: int = int(os.environ.get("YT_KEEP_LIMIT", "50"))
except Exception:
    YT_KEEP_LIMIT = 50


# ── Atomic write helper ───────────────────────────────────────
def _atomic_write(path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        logging.exception("Atomic write failed for %s", path)


# ── Guides ────────────────────────────────────────────────────
def load_guides() -> dict:
    try:
        if os.path.exists(GUIDES_FILE):
            with open(GUIDES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logging.error("Failed loading guides.json: %s", e)
    return {}


def save_guides() -> None:
    _atomic_write(GUIDES_FILE, GUIDES)


def backup_guides() -> None:
    import datetime, shutil
    try:
        if os.path.exists(GUIDES_FILE):
            dst = f"guides.json.bak.{datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
            shutil.copyfile(GUIDES_FILE, dst)
            logging.info("Backed up guides.json to %s", dst)
    except Exception:
        logging.exception("Failed to backup guides.json")


# ── Favorites ─────────────────────────────────────────────────
def load_favorites() -> dict:
    try:
        if os.path.exists(FAVORITES_FILE):
            with open(FAVORITES_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_favorites() -> None:
    _atomic_write(FAVORITES_FILE, USER_FAVORITES)


# ── Ratings ───────────────────────────────────────────────────
def load_ratings() -> dict:
    try:
        if os.path.exists(RATINGS_FILE):
            with open(RATINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_ratings() -> None:
    _atomic_write(RATINGS_FILE, GUIDE_RATINGS)


# ── Guides meta ───────────────────────────────────────────────
def load_guides_meta() -> dict:
    try:
        if os.path.exists(GUIDES_META_FILE):
            with open(GUIDES_META_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_guides_meta() -> None:
    _atomic_write(GUIDES_META_FILE, GUIDES_META)


# ── Settings ──────────────────────────────────────────────────
def load_settings() -> dict:
    try:
        if os.path.exists(SETTINGS_PATH):
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()


def save_settings() -> None:
    _atomic_write(SETTINGS_PATH, SETTINGS)


# ── YouTube state ─────────────────────────────────────────────
def load_yt_channels() -> list:
    try:
        if os.path.exists(YT_CHANNELS_FILE):
            with open(YT_CHANNELS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return [str(x).strip() for x in data if str(x).strip()]
    except Exception:
        pass
    return [c.strip() for c in os.environ.get("YT_CHANNELS", "").split(",") if c.strip()]


def save_yt_channels() -> None:
    _atomic_write(YT_CHANNELS_FILE, YT_CHANNELS)


def load_yt_cache() -> dict:
    try:
        if os.path.exists(YT_CACHE_FILE):
            with open(YT_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_yt_cache() -> None:
    _atomic_write(YT_CACHE_FILE, YT_CACHE)


# ── Search history ────────────────────────────────────────────
def load_search_history() -> dict:
    try:
        if os.path.exists(SEARCH_HISTORY_FILE):
            with open(SEARCH_HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def save_search_history() -> None:
    _atomic_write(SEARCH_HISTORY_FILE, SEARCH_HISTORY)


def add_to_search_history(user_id: str, query: str) -> None:
    import time as _time
    history = SEARCH_HISTORY.setdefault(user_id, [])
    history[:] = [h for h in history if h.get("query", "").lower() != query.lower()]
    history.append({"query": query, "ts": _time.time()})
    if len(history) > 15:
        history[:] = history[-15:]
    save_search_history()


# ── URL normalization & deduplication ─────────────────────────
def normalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        u = urllib.parse.urlparse(url)
        netloc = u.netloc.lower().replace("www.", "")
        path = u.path.rstrip("/")
        if netloc == "youtu.be":
            vid = u.path.lstrip("/")
            if vid:
                return f"https://www.youtube.com/watch?v={vid}"
        if netloc in ("youtube.com", "m.youtube.com", "youtube-nocookie.com"):
            qs = urllib.parse.parse_qs(u.query)
            if "v" in qs and qs["v"]:
                return f"https://www.youtube.com/watch?v={qs['v'][0]}"
            parts = [p for p in path.split("/") if p]
            if parts and parts[0] == "shorts" and len(parts) >= 2:
                return f"https://www.youtube.com/watch?v={parts[1]}"
        return f"https://{netloc}{path}"
    except Exception:
        return url.strip().lower()


def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"[^a-z0-9а-яё\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def dedupe_guides() -> int:
    seen: dict = {}
    removed = 0
    for category in list(GUIDES.keys()):
        entries = GUIDES.get(category, {})
        for title, url in list(entries.items()):
            if not url:
                continue
            n = normalize_url(url)
            if n in seen:
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


def merge_entries_into_category(category: str, entries: list) -> int:
    if category not in GUIDES:
        GUIDES[category] = {}
    existing_norm = {normalize(k): k for k in GUIDES[category].keys()}
    existing_urls: dict = {}
    for k, v in GUIDES[category].items():
        if v:
            existing_urls[normalize_url(v)] = k
    added = 0
    for title, url in entries:
        n = normalize(title)
        if url:
            nu = normalize_url(url)
            if nu in existing_urls:
                key = existing_urls[nu]
                if GUIDES[category].get(key) != url:
                    GUIDES[category][key] = url
                continue
        if n in existing_norm:
            key = existing_norm[n]
            if GUIDES[category].get(key) != url:
                GUIDES[category][key] = url
        else:
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


# ── Boot: load all state ──────────────────────────────────────
def _boot() -> None:
    global GUIDES, USER_FAVORITES, GUIDE_RATINGS, GUIDES_META
    global SETTINGS, YT_CHANNELS, YT_CACHE, SEARCH_HISTORY
    global YT_PRUNE_REMOVED, YT_KEEP_LIMIT

    GUIDES.update(load_guides())
    USER_FAVORITES.update(load_favorites())
    GUIDE_RATINGS.update(load_ratings())
    GUIDES_META.update(load_guides_meta())
    SETTINGS.update(load_settings())
    YT_CHANNELS[:] = load_yt_channels()
    YT_CACHE.update(load_yt_cache())
    SEARCH_HISTORY.update(load_search_history())

    YT_PRUNE_REMOVED = SETTINGS.get("yt_prune_removed", YT_PRUNE_REMOVED)
    YT_KEEP_LIMIT = SETTINGS.get("yt_keep_limit", YT_KEEP_LIMIT)

    try:
        removed = dedupe_guides()
        if removed:
            logging.info("Removed %d duplicate guide links on startup", removed)
    except Exception:
        pass


_boot()
