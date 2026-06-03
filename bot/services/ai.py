"""AI answer service using Anthropic Claude API with graceful degradation."""
import hashlib
import logging
import time
from typing import Any, Optional

try:
    import anthropic as _anthropic_mod
    _anthropic_available = True
except ImportError:
    _anthropic_mod = None
    _anthropic_available = False

from ..config import ANTHROPIC_API_KEY, AI_MODEL

log = logging.getLogger(__name__)

# Simple in-memory response cache (query → answer, ttl=10 min)
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 600

# Reuse a single async client instance — avoids creating a new connection pool per call
_async_client: Optional[Any] = None


def _get_async_client() -> Optional[Any]:
    global _async_client
    if _async_client is None and _anthropic_available and ANTHROPIC_API_KEY:
        _async_client = _anthropic_mod.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _async_client


def _get_cached(key: str) -> Optional[str]:
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    _cache.pop(key, None)
    return None


def _set_cached(key: str, value: str) -> None:
    # Evict oldest entries if cache grows too large
    if len(_cache) >= 200:
        oldest = min(_cache, key=lambda k: _cache[k][1])
        _cache.pop(oldest, None)
    _cache[key] = (value, time.time())


_SYSTEM_PROMPT = (
    "Ты — AI-помощник Ryazhenka Bot для Nintendo Switch с кастомной прошивкой (CFW). "
    "Помогаешь пользователям разобраться с Ryazhenka CFW, sys-clk, FPSLocker, Atmosphere, "
    "установкой игр, emuNAND, homebrew и другими Switch-темами. "
    "Отвечай кратко (3-6 предложений), практично и на русском языке. "
    "Если не уверен — так и скажи. Не придумывай несуществующие команды или файлы."
)


def _build_user_prompt(query: str, guide_context: str) -> str:
    parts = [f"Вопрос пользователя: {query}"]
    if guide_context:
        parts.append(f"\nРелевантные гайды из базы знаний:\n{guide_context}")
    parts.append("\nДай краткий и практичный ответ.")
    return "\n".join(parts)


async def ask_ai(query: str, guide_context: str = "") -> Optional[str]:
    """
    Query Claude API with the user question + optional guide context.
    Returns the AI answer string, or None if AI is unavailable/failed.
    Uses prompt caching for the system prompt to reduce latency and cost.
    """
    if not ANTHROPIC_API_KEY or not _anthropic_available:
        return None

    cache_key = hashlib.sha256(f"{query}||{guide_context}".encode()).hexdigest()[:24]
    cached = _get_cached(cache_key)
    if cached:
        log.debug("AI cache hit for query: %s", query[:40])
        return cached

    try:
        client = _get_async_client()
        if client is None:
            return None
        message = await client.messages.create(
            model=AI_MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[
                {"role": "user", "content": _build_user_prompt(query, guide_context)}
            ],
        )
        answer = message.content[0].text.strip() if message.content else None
        if answer:
            _set_cached(cache_key, answer)
            log.info("AI answer generated for: %s", query[:40])
        return answer
    except Exception as e:
        log.warning("AI request failed: %s", e)
        return None
