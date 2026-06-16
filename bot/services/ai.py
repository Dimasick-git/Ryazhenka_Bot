"""AI answer service using Anthropic Claude API with graceful degradation."""
import asyncio
import hashlib
import json
import logging
import os
import tempfile
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

# ──────────────────────────────────────────────────────────────
# TWO-LAYER CACHE: in-memory L1 + disk L2
# In-memory cache serves fast repeated queries within a session.
# Disk cache persists across Railway restarts, saving API costs.
# ──────────────────────────────────────────────────────────────
_mem_cache: dict[str, tuple[str, float]] = {}
_MEM_CACHE_TTL = 600       # 10 min in-memory
_MEM_CACHE_MAX = 200

_DISK_CACHE_TTL = 43200    # 12 hours on disk
_DISK_CACHE_MAX = 1000
_DISK_CACHE_FILE = "ai_response_cache.json"
_disk_cache: dict[str, tuple[str, float]] = {}
_disk_cache_loaded = False

_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.5

_async_client: Optional[Any] = None


# ──────────────────────────────────────────────────────────────
# CLIENT
# ──────────────────────────────────────────────────────────────

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


# ──────────────────────────────────────────────────────────────
# DISK CACHE OPS
# ──────────────────────────────────────────────────────────────

def _load_disk_cache() -> None:
    global _disk_cache, _disk_cache_loaded
    if _disk_cache_loaded:
        return
    _disk_cache_loaded = True
    if not os.path.exists(_DISK_CACHE_FILE):
        return
    try:
        with open(_DISK_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        now = time.time()
        _disk_cache = {
            k: (v[0], v[1])
            for k, v in raw.items()
            if isinstance(v, list) and len(v) == 2 and now - v[1] < _DISK_CACHE_TTL
        }
        log.debug("AI disk cache loaded: %d entries", len(_disk_cache))
    except Exception as e:
        log.warning("Failed to load AI disk cache: %s", e)
        _disk_cache = {}


def _save_disk_cache() -> None:
    try:
        now = time.time()
        active = {k: v for k, v in _disk_cache.items() if now - v[1] < _DISK_CACHE_TTL}
        if len(active) > _DISK_CACHE_MAX:
            sorted_keys = sorted(active, key=lambda k: active[k][1])
            for old in sorted_keys[:len(active) - _DISK_CACHE_MAX]:
                active.pop(old, None)
        serializable = {k: [v[0], v[1]] for k, v in active.items()}
        dir_ = os.path.dirname(os.path.abspath(_DISK_CACHE_FILE)) or "."
        fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(serializable, f, ensure_ascii=False)
        os.replace(tmp, _DISK_CACHE_FILE)
        log.debug("AI disk cache saved: %d entries", len(active))
    except Exception as e:
        log.warning("Failed to save AI disk cache: %s", e)


def _get_cached(key: str) -> Optional[str]:
    # L1: memory
    entry = _mem_cache.get(key)
    if entry and time.time() - entry[1] < _MEM_CACHE_TTL:
        return entry[0]
    _mem_cache.pop(key, None)

    # L2: disk
    _load_disk_cache()
    disk_entry = _disk_cache.get(key)
    if disk_entry and time.time() - disk_entry[1] < _DISK_CACHE_TTL:
        # Promote to memory cache
        _mem_cache[key] = disk_entry
        return disk_entry[0]
    _disk_cache.pop(key, None)
    return None


def _set_cached(key: str, value: str) -> None:
    # Evict from memory if full
    if len(_mem_cache) >= _MEM_CACHE_MAX:
        now = time.time()
        expired = [k for k, v in _mem_cache.items() if now - v[1] >= _MEM_CACHE_TTL]
        if expired:
            for k in expired:
                _mem_cache.pop(k, None)
        else:
            oldest = min(_mem_cache, key=lambda k: _mem_cache[k][1])
            _mem_cache.pop(oldest, None)
    ts = time.time()
    _mem_cache[key] = (value, ts)
    # Also write to disk cache
    _load_disk_cache()
    _disk_cache[key] = (value, ts)


async def _persist_disk_cache_async() -> None:
    await asyncio.to_thread(_save_disk_cache)


# ──────────────────────────────────────────────────────────────
# SYSTEM PROMPT
# ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "Ты — AI-помощник Ryazhenka Bot, специализированный ассистент для Nintendo Switch "
    "с кастомной прошивкой (CFW). Тебя создала команда Ryazhenka (Dimasick-git и коллеги).\n\n"
    "Экосистема Ryazhenka CFW включает:\n"
    "• RCU (Ryazha Clock Utility) — sysmodule + Tesla overlay для управления частотами CPU/GPU/RAM "
    "по приложениям с FPS-aware VRR ladder; профили частот per-Title ID\n"
    "• Ryazhahand-Overlay — Tesla overlay меню (форк Ultrahand-Overlay) с поддержкой LED, "
    "аудио-паков, PNG-обоев, namespace /config/ryazhahand/; открывается L+DDOWN+RS\n"
    "• libryazhahand — библиотека Tesla overlay (форк libultrahand+libtesla) с namespace /config/ryazhahand/\n"
    "• ovlSysmodules — управление sysmodule'ами через Tesla overlay без перезагрузки\n"
    "• nx-ovlloader — загрузчик Tesla overlay (Ryazha-edition форк ppkantorski/nx-ovlloader)\n"
    "• AIO-Switch-Updater — универсальный обновлятор CFW компонентов (Atmosphere, Hekate, sigpatches)\n"
    "• FPSLocker — блокировка FPS в играх через патч движка; поддерживает custom patches\n"
    "• Ryazha-Status-Monitor — Tesla overlay мониторинга железа Switch: нагрузка на ядра CPU/GPU, "
    "температура SoC/PCB/корпуса, RAM, FPS; режимы Full/Mini/Micro; требует SaltyNX\n"
    "• RyazhaTune — фоновый музыкальный плеер (форк sys-tune): MP3/FLAC/WAV во время игры, "
    "постоянные плейлисты, Whitelist/Blacklist и Focus-политики по Title ID, Tesla overlay управление\n"
    "• EdiZon — редактор сохранений и читкод-менеджер (форк с доработками)\n"
    "• Fizeau — Tesla overlay коррекции цветопередачи: гамма, ночной режим, цветовая температура\n"
    "• Mission-Control — sysmodule подключения Bluetooth контроллеров (PS4/PS5/Xbox/Pro)\n"
    "• SwitchWave — аудио плагин для Nintendo Switch\n"
    "• ReverseNX-RT — sysmodule принудительного Dock/Handheld режима без TV\n"
    "• Atmosphere-RYZ — кастомный форк Atmosphere с pre-configured настройками под Ryazhenka CFW\n"
    "• Hekate — bootloader (Ryazha-форк) с дополнительными конфигурациями и утилитами\n"
    "• Ryazha-cheker — GitHub Actions монитор репозиториев: отслеживает коммиты, релизы, PR, "
    "workflow-runs; уведомления в Telegram и Discord; режимы --weekly, --trending, --summary\n"
    "• RyazhaAI — AI-ассистент для Switch CFW (веб-приложение + Switch homebrew NRO, 12+ AI провайдеров)\n\n"
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
    "• DBI — мощный файловый менеджер + установщик для Switch\n"
    "• SaltyNX — sysmodule для перехвата системных вызовов (нужен Ryazha-Status-Monitor)\n"
    "• sys-botbase — sysmodule удалённого управления Switch (для ботов и автоматизации)\n"
    "• ldn_mitm — форс-локальное соединение через интернет (Lan Play)\n\n"
    "Правила ответов:\n"
    "• Отвечай кратко (3-7 предложений), практично, на русском языке\n"
    "• Если не уверен в точности — прямо скажи об этом\n"
    "• Не придумывай несуществующие команды, файлы или настройки\n"
    "• При вопросах о безопасности — напоминай о рисках бана через sysNAND онлайн\n"
    "• При вопросах о конкретных инструментах Ryazhenka — рекомендуй GitHub Dimasick-git\n"
    "• Для технических вопросов давай конкретные пути к файлам и настройкам когда уместно"
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


async def _call_anthropic(messages: list[dict], max_tokens: int) -> Optional[str]:
    """Send a request to Claude with retry on transient errors. Returns text or None."""
    client = _get_async_client()
    if client is None:
        return None
    delay = _RETRY_BASE_DELAY
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            resp = await client.messages.create(
                model=AI_MODEL,
                max_tokens=max_tokens,
                system=[{"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
            )
            return resp.content[0].text.strip() if resp.content else None
        except Exception as e:
            if _is_retryable(e) and attempt < _RETRY_ATTEMPTS:
                log.warning(
                    "Claude attempt %d/%d (%s), retry in %.1fs",
                    attempt, _RETRY_ATTEMPTS, type(e).__name__, delay,
                )
                await asyncio.sleep(delay)
                delay *= 2
                continue
            log.warning("Claude request failed: %s", e)
            return None
    return None


async def ask_ai(query: str, guide_context: str = "") -> Optional[str]:
    """Query Claude with the user question + optional guide context.

    Uses a two-layer cache (memory + disk) to reduce latency and API costs.
    Disk cache survives bot restarts on Railway.
    """
    if not ANTHROPIC_API_KEY or not _anthropic_available:
        return None

    cache_key = hashlib.sha256(f"{AI_MODEL}:{query}||{guide_context}".encode()).hexdigest()[:24]
    cached = _get_cached(cache_key)
    if cached:
        log.debug("AI cache hit: %s", query[:40])
        return cached

    max_tokens = int(os.getenv("AI_MAX_TOKENS", "1024"))
    answer = await _call_anthropic(
        [{"role": "user", "content": _build_user_prompt(query, guide_context)}],
        max_tokens,
    )
    if answer:
        _set_cached(cache_key, answer)
        asyncio.ensure_future(_persist_disk_cache_async())
        log.info("AI answer generated: %s", query[:40])
    return answer


async def ask_ai_with_history(
    query: str,
    history: list[dict],
    guide_context: str = "",
) -> Optional[str]:
    """Multi-turn conversation variant — includes previous messages for context.

    ``history`` is a list of dicts: [{"role": "user"|"assistant", "content": "..."}].
    Only the last 10 messages (5 turns) are kept to balance context quality with token budget.
    Results are NOT cached (history makes each request unique).
    """
    if not ANTHROPIC_API_KEY or not _anthropic_available:
        return None

    trimmed = history[-10:] if len(history) > 10 else history
    messages = [
        {"role": h["role"], "content": h["content"]}
        for h in trimmed
        if h.get("role") in ("user", "assistant") and h.get("content")
    ]
    messages.append({"role": "user", "content": _build_user_prompt(query, guide_context)})

    max_tokens = int(os.getenv("AI_MAX_TOKENS", "1024"))
    answer = await _call_anthropic(messages, max_tokens)
    if answer:
        log.info("AI multi-turn answer: %s", query[:40])
    return answer
