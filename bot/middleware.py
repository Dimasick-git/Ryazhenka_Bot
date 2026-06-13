"""Rate-limiting middleware for Ryazhenka Bot."""
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import InlineQuery, Message

# Per-user cooldown buckets: command -> (window_seconds, max_calls)
_LIMITS: Dict[str, tuple] = {
    "default":   (5,   3),   # any command: 3 calls per 5s
    "aiguide":   (10,  2),   # heavy BM25 search: 2 calls per 10s
    "guide":     (5,   5),
    "search":    (5,   5),
    "ask":       (15,  2),   # AI API call: 2 per 15s
    "compare":   (20,  2),   # AI API call: 2 per 20s
    "releases":  (30,  3),   # GitHub API call
    "modules":   (30,  3),   # GitHub API call
    "digest":    (30,  2),   # AI + ratings
    "inline":    (3,   4),   # inline mode: 4 queries per 3s — tighter to prevent API spam
    "feedback":  (60,  3),   # anti-spam: 3 per minute
    "random":    (5,   5),
    "recommend": (30,  2),   # GitHub API call
}

_COOLDOWNS: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
_LAST_CLEANUP: float = 0.0
_CLEANUP_INTERVAL: float = 3600.0  # purge stale user entries hourly


def _get_bucket(command: str) -> tuple:
    return _LIMITS.get(command, _LIMITS["default"])


def _maybe_cleanup(now: float) -> None:
    global _LAST_CLEANUP
    if now - _LAST_CLEANUP < _CLEANUP_INTERVAL:
        return
    _LAST_CLEANUP = now
    max_window = max(w for w, _ in _LIMITS.values())
    for uid in list(_COOLDOWNS.keys()):
        for cmd in list(_COOLDOWNS[uid].keys()):
            _COOLDOWNS[uid][cmd] = [t for t in _COOLDOWNS[uid][cmd] if now - t < max_window]
            if not _COOLDOWNS[uid][cmd]:
                del _COOLDOWNS[uid][cmd]
        if not _COOLDOWNS[uid]:
            del _COOLDOWNS[uid]


_MAX_USERS = 10_000


class ThrottlingMiddleware(BaseMiddleware):
    """Drops repeated commands/inline queries if the user exceeds the rate limit."""

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any],
    ) -> Any:
        if isinstance(event, InlineQuery):
            user_id = str(event.from_user.id) if event.from_user else "anon"
            window, max_calls = _get_bucket("inline")
            now = time.monotonic()
            _maybe_cleanup(now)
            if len(_COOLDOWNS) >= _MAX_USERS and user_id not in _COOLDOWNS:
                return None
            bucket = _COOLDOWNS[user_id]["inline"]
            _COOLDOWNS[user_id]["inline"] = [t for t in bucket if now - t < window]
            if len(_COOLDOWNS[user_id]["inline"]) >= max_calls:
                return None
            _COOLDOWNS[user_id]["inline"].append(now)
            return await handler(event, data)

        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)

        user_id = str(event.from_user.id) if event.from_user else "anon"
        text = event.text.strip()
        if not text.startswith("/"):
            return await handler(event, data)

        command = text.split()[0].lstrip("/").split("@")[0].lower()
        window, max_calls = _get_bucket(command)

        now = time.monotonic()
        _maybe_cleanup(now)

        if len(_COOLDOWNS) >= _MAX_USERS and user_id not in _COOLDOWNS:
            # Map is full: force an immediate cleanup to reclaim stale slots.
            # If the map is still full after cleanup the request is dropped to
            # prevent attackers from exhausting the map with unique IDs and
            # then bypassing throttling entirely for legitimate commands.
            _maybe_cleanup(now - _CLEANUP_INTERVAL)  # force cleanup regardless of timer
            if len(_COOLDOWNS) >= _MAX_USERS:
                return None

        timestamps = _COOLDOWNS[user_id][command]
        _COOLDOWNS[user_id][command] = [t for t in timestamps if now - t < window]

        if len(_COOLDOWNS[user_id][command]) >= max_calls:
            remaining = window - (now - _COOLDOWNS[user_id][command][0])
            await event.reply(
                f"⏳ Слишком часто. Подождите {remaining:.0f} сек.",
                parse_mode=None,
            )
            return None

        _COOLDOWNS[user_id][command].append(now)
        return await handler(event, data)
