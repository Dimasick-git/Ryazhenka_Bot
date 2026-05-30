"""Rate-limiting middleware for Ryazhenka Bot."""
import time
from collections import defaultdict
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import Message

# Per-user cooldown buckets: command -> (window_seconds, max_calls)
_LIMITS: Dict[str, tuple] = {
    "default":   (5,   3),   # any command: 3 calls per 5s
    "aiguide":   (10,  2),   # heavy BM25 search: 2 calls per 10s
    "guide":     (5,   5),
    "search":    (5,   5),
    "feedback":  (60,  3),   # anti-spam: 3 per minute
    "random":    (5,   5),
    "recommend": (30,  2),   # GitHub API call
}

_COOLDOWNS: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))


def _get_bucket(command: str) -> tuple:
    return _LIMITS.get(command, _LIMITS["default"])


class ThrottlingMiddleware(BaseMiddleware):
    """Drops repeated commands if the user exceeds the rate limit."""

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any],
    ) -> Any:
        if not isinstance(event, Message) or not event.text:
            return await handler(event, data)

        user_id = str(event.from_user.id) if event.from_user else "anon"
        text = event.text.strip()
        if not text.startswith("/"):
            return await handler(event, data)

        command = text.split()[0].lstrip("/").split("@")[0].lower()
        window, max_calls = _get_bucket(command)

        now = time.monotonic()
        timestamps = _COOLDOWNS[user_id][command]
        # Evict stale timestamps outside the window
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
