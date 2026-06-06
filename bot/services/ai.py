"""AI answer service using Anthropic Claude API with graceful degradation."""
import asyncio
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

# In-memory LRU-style response cache (query → answer, ttl=10 min)
_cache: dict[str, tuple[str, float]] = {}
_CACHE_TTL = 600
_CACHE_MAX = 200

# Reuse a single async client instance — avoids creating a new connection pool per call
_async_client: Optional[Any] = None

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.5  # seconds


def _get_async_client() -> Optional[Any]:
    global _async_client
    if _async_client is None and _anthropic_available and ANTHROPIC_API_KEY:
        _async_client = _anthropic_mod.AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    return _async_client


async def close_client() -> None:
    global _async_client
    if _async_client is not None:
        await _async_client.aclose()
        _async_client = None


def _get_cached(key: str) -> Optional[str]:
    entry = _cache.get(key)
    if entry and time.time() - entry[1] < _CACHE_TTL:
        return entry[0]
    _cache.pop(key, None)
    return None


def _set_cached(key: str, value: str) -> None:
    if len(_cache) >= _CACHE_MAX:
        # Evict expired entries first; fall back to oldest by timestamp
        now = time.time()
        expired = [k for k, v in _cache.items() if now - v[1] >= _CACHE_TTL]
        if expired:
            for k in expired:
                _cache.pop(k, None)
        else:
            oldest = min(_cache, key=lambda k: _cache[k][1])
            _cache.pop(oldest, None)
    _cache[key] = (value, time.time())


_SYSTEM_PROMPT = (
    "Ты — AI-помощник Ryazhenka Bot, специализированный ассистент для Nintendo Switch "
    "с кастомной прошивкой (CFW). Тебя создала команда Ryazhenka (Dimasick-git и коллеги).\n\n"
    "Экосистема Ryazhenka CFW включает:\n"
    "• RCU (Ryazha Clock Utility) — sysmodule + Tesla overlay для управления частотами CPU/GPU/RAM "
    "по приложениям с FPS-aware VRR ladder\n"
    "• Ryazhahand-Overlay — Tesla overlay меню (форк Ultrahand-Overlay) с поддержкой LED, "
    "аудио-паков, PNG-обоев, namespace /config/ryazhahand/\n"
    "• libryazhahand — библиотека Tesla overlay (форк libultrahand+libtesla)\n"
    "• ovlSysmodules — управление sysmodule'ами через Tesla overlay\n"
    "• nx-ovlloader — загрузчик Tesla overlay (Ryazha-edition форк ppkantorski/nx-ovlloader)\n"
    "• AIO-Switch-Updater — универсальный обновлятор CFW компонентов\n"
    "• FPSLocker — блокировка FPS в играх через патч\n"
    "• Ryazha-Status-Monitor — Tesla overlay мониторинга железа Switch: нагрузка на ядра CPU/GPU, "
    "температура SoC/PCB/корпуса, RAM, FPS (режимы Full/Mini/Micro, зависит от SaltyNX)\n"
    "• EdiZon, Fizeau, Mission-Control, RyazhaTune — форки с доработками команды\n"
    "• Ryazha-cheker — GitHub Actions монитор репозиториев: отслеживает коммиты, релизы, PR, "
    "workflow-runs и отправляет уведомления в Telegram\n"
    "• RyazhaAI — AI-ассистент для Switch CFW (веб + Switch homebrew NRO)\n\n"
    "Основные Switch CFW концепции:\n"
    "• Atmosphere — основная кастомная прошивка от Team Neptune\n"
    "• Hekate — bootloader, управляет запуском CFW и emuNAND\n"
    "• emuNAND/emummc — эмулированная NAND на microSD, безопасна для онлайна\n"
    "• sysNAND — встроенная NAND консоли (риск бана при использовании CFW онлайн)\n"
    "• Tesla Menu — система overlay меню (комбо L+DDOWN+RS)\n"
    "• sys-clk — sysmodule управления частотами (оригинал 4TU, RCU — Ryazha-форк)\n"
    "• Tinfoil, Goldleaf, Awoo-Installer — homebrew установщики игр\n"
    "• Lockpick_RCM — дамп ключей шифрования Switch\n"
    "• sigpatches — патчи подписи для запуска неподписанного кода\n"
    "• DBI — мощный файловый менеджер + установщик для Switch\n\n"
    "Правила ответов:\n"
    "• Отвечай кратко (3-7 предложений), практично, на русском языке\n"
    "• Если не уверен в точности — прямо скажи об этом\n"
    "• Не придумывай несуществующие команды, файлы или настройки\n"
    "• При вопросах о безопасности — напоминай о рисках бана через sysNAND онлайн\n"
    "• При вопросах о конкретных инструментах Ryazhenka — рекомендуй GitHub Dimasick-git"
)


def _build_user_prompt(query: str, guide_context: str) -> str:
    parts = [f"Вопрос пользователя: {query}"]
    if guide_context:
        parts.append(f"\nРелевантные гайды из базы знаний:\n{guide_context}")
    parts.append("\nДай краткий и практичный ответ.")
    return "\n".join(parts)


def _is_retryable(exc: Exception) -> bool:
    """Return True for transient errors (rate limit, server error, network)."""
    if _anthropic_available:
        if isinstance(exc, _anthropic_mod.RateLimitError):
            return True
        if isinstance(exc, _anthropic_mod.APIStatusError) and exc.status_code >= 500:
            return True
        if isinstance(exc, _anthropic_mod.APIConnectionError):
            return True
    return False


async def ask_ai(query: str, guide_context: str = "") -> Optional[str]:
    """
    Query Claude API with the user question + optional guide context.
    Returns the AI answer string, or None if AI is unavailable/failed.
    Uses prompt caching for the system prompt to reduce latency and cost.
    Retries up to _RETRY_ATTEMPTS times on transient errors (rate limit, 5xx, network).
    """
    if not ANTHROPIC_API_KEY or not _anthropic_available:
        return None

    cache_key = hashlib.sha256(f"{query}||{guide_context}".encode()).hexdigest()[:24]
    cached = _get_cached(cache_key)
    if cached:
        log.debug("AI cache hit for query: %s", query[:40])
        return cached

    client = _get_async_client()
    if client is None:
        return None

    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            message = await client.messages.create(
                model=AI_MODEL,
                max_tokens=1024,
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
            if _is_retryable(e) and attempt < _RETRY_ATTEMPTS:
                log.warning("AI request attempt %d/%d failed (%s), retrying in %.1fs",
                            attempt, _RETRY_ATTEMPTS, type(e).__name__, delay)
                await asyncio.sleep(delay)
                delay *= 2
                continue
            log.warning("AI request failed: %s", e)
            return None
    return None
