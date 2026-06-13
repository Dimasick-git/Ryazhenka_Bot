"""Background sync: YouTube channels + GitHub releases → GUIDES."""
import asyncio
import logging
import re
import urllib.parse
from typing import Callable, TypeVar

import aiohttp

from .. import storage
from ..config import ADMIN_IDS, ALLOWED_DOMAINS, GITHUB_REPO
from . import github, youtube

_T = TypeVar("_T")


async def _retry_async(
    fn: Callable,
    *args,
    retries: int = 3,
    base_delay: float = 2.0,
    label: str = "",
    **kwargs,
):
    """Call an async function with exponential-backoff retry on exception.

    Returns the function's return value, or re-raises the last exception
    after all attempts are exhausted.
    """
    delay = base_delay
    for attempt in range(1, retries + 1):
        try:
            return await fn(*args, **kwargs)
        except Exception as exc:
            if attempt == retries:
                logging.warning(
                    "%s failed after %d attempt(s): %s", label or fn.__name__, retries, exc
                )
                raise
            logging.debug(
                "%s attempt %d/%d failed (%s). Retrying in %.1fs.",
                label or fn.__name__, attempt, retries, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2

_DATE_RE = re.compile(r"\[(\d{4}-\d{2}-\d{2})\]")
_DDG_TIMEOUT = aiohttp.ClientTimeout(total=30)
_sync_lock = asyncio.Lock()

# Module-level session reused across DDG calls to avoid per-call connection overhead.
_ddg_session: aiohttp.ClientSession | None = None


def _date_sort_key(k: str) -> str:
    m = _DATE_RE.match(k)
    return m.group(1) if m else "1970-01-01"


def _is_valid_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://")


def _get_ddg_session() -> aiohttp.ClientSession:
    global _ddg_session
    if _ddg_session is None or _ddg_session.closed:
        _ddg_session = aiohttp.ClientSession()
    return _ddg_session


async def close_ddg_session() -> None:
    global _ddg_session
    if _ddg_session is not None and not _ddg_session.closed:
        await _ddg_session.close()
        _ddg_session = None


async def resolve_duckduckgo_first(title: str) -> str:
    query = f"{title} Nintendo Switch site:github.com OR site:rentry.org OR site:github.io OR site:gamebrew.org OR site:gbatemp.net"
    try:
        session = _get_ddg_session()
        async with session.post(
            "https://duckduckgo.com/html/", data={"q": query},
            timeout=_DDG_TIMEOUT,
        ) as resp:
            text = await resp.text()
        hrefs = re.findall(r'href="([^"]+)"', text)
        for h in hrefs:
            try:
                parsed = urllib.parse.urlparse(h)
                if parsed.path.startswith("/l/"):
                    qs = urllib.parse.parse_qs(parsed.query)
                    uddg = qs.get("uddg") or qs.get("uddg[]")
                    if uddg:
                        target = urllib.parse.unquote(uddg[0])
                        net = urllib.parse.urlparse(target).netloc
                        if any(net == d or net.endswith("." + d) for d in ALLOWED_DOMAINS):
                            return target
                else:
                    net = parsed.netloc
                    if any(d in net for d in ALLOWED_DOMAINS):
                        return h
            except Exception:
                continue
    except Exception as e:
        logging.warning("DDG lookup failed for '%s': %s", title, e)
    return None


async def resolve_auto_guides_links(bot, notify_admins: bool = True) -> None:
    cat = "🆕 Авто-гайды"
    if cat not in storage.GUIDES:
        return
    changed = []
    placeholder_re = re.compile(r"^\s*авто[- ]?гайд\b\s*\d+", re.I)
    for title, url in list(storage.GUIDES[cat].items()):
        if placeholder_re.search(title):
            continue
        if "duckduckgo.com" in (url or ""):
            found = await resolve_duckduckgo_first(title)
            if found:
                if storage.SETTINGS.get("auto_resolve_and_add", True):
                    target_cat = " Авто-найденные"
                    added = storage.merge_entries_into_category(target_cat, [(title, found)])
                    try:
                        del storage.GUIDES[cat][title]
                    except Exception:
                        pass
                    if added:
                        changed.append((title, found))
                else:
                    storage.GUIDES[cat][title] = found
                    changed.append((title, found))
    if changed:
        await storage.save_guides()
        logging.info("Resolved %d auto-guides to direct links", len(changed))
        if notify_admins and ADMIN_IDS:
            msg = " Найдены прямые ссылки для авто-гайдов:\n"
            for t, u in changed[:10]:
                msg += f"• {t}: {u}\n"
            for aid in ADMIN_IDS:
                try:
                    await bot.send_message(aid, msg)
                except Exception:
                    logging.exception("Failed notifying admin %d", aid)


async def sync_sources() -> dict:
    if _sync_lock.locked():
        return {"skipped": True, "reason": "sync already in progress"}
    async with _sync_lock:
        summary = {"youtube_added": 0, "github_added": 0}
        # YouTube
        try:
            total_added = 0
            for ch in storage.YT_CHANNELS:
                cid = ch
                if not cid.startswith("UC"):
                    try:
                        resolved = await _retry_async(
                            youtube.resolve_channel_id, ch,
                            label=f"resolve_channel_id({ch!r})",
                        )
                    except Exception:
                        resolved = None
                    if resolved:
                        cid = resolved
                logging.info("Fetching YouTube for channel '%s' resolved to '%s'", ch, cid)
                try:
                    channel_title, yt_entries = await _retry_async(
                        youtube.fetch_youtube_videos, cid,
                        label=f"fetch_youtube_videos({cid!r})",
                    ) if cid else (None, [])
                except Exception as e:
                    logging.warning("YouTube fetch failed for channel %s after retries: %s", cid, e)
                    channel_title, yt_entries = None, []
                logging.info("Fetched %d entries from YouTube channel %s (%s)", len(yt_entries), cid, channel_title)
                # Filter out entries with invalid URLs
                yt_entries = [(t, u) for t, u in yt_entries if _is_valid_url(u)]
                if yt_entries:
                    # persist UC id for stability
                    if cid and not ch.startswith("UC"):
                        try:
                            idx = storage.YT_CHANNELS.index(ch)
                            storage.YT_CHANNELS[idx] = cid
                            await storage.save_yt_channels()
                        except ValueError:
                            pass
                    safe_name = re.sub(r"[^0-9a-zA-Zа-яёА-ЯЁ _\-]", " ", channel_title or ch or cid or "Видео").strip()
                    cat_name = f"YouTube - {safe_name}"

                    yt_entries.sort(key=lambda tu: _date_sort_key(tu[0]), reverse=True)
                    added = storage.merge_entries_into_category(cat_name, yt_entries)
                    total_added += added

                    # prune removed videos
                    if storage.YT_PRUNE_REMOVED:
                        existing_map = {storage.normalize_url(v): k for k, v in storage.GUIDES.get(cat_name, {}).items() if v}
                        feed_urls = {storage.normalize_url(u) for (_, u) in yt_entries}
                        for nu, key in list(existing_map.items()):
                            if nu and nu not in feed_urls:
                                try:
                                    del storage.GUIDES[cat_name][key]
                                except Exception:
                                    pass

                    # enforce keep limit
                    keys = list(storage.GUIDES.get(cat_name, {}).keys())
                    keys_sorted = sorted(keys, key=_date_sort_key, reverse=True)
                    for old in keys_sorted[storage.YT_KEEP_LIMIT:]:
                        try:
                            del storage.GUIDES[cat_name][old]
                        except Exception:
                            pass
            summary["youtube_added"] = total_added
        except Exception as e:
            logging.warning("YouTube sync failed: %s", e)

        # GitHub releases
        try:
            gh_entries = await _retry_async(
                github.fetch_github_releases, GITHUB_REPO,
                label=f"fetch_github_releases({GITHUB_REPO!r})",
            ) if GITHUB_REPO else []
            # Filter out entries with invalid URLs
            gh_entries = [(t, u) for t, u in gh_entries if _is_valid_url(u)]
            if gh_entries:
                summary["github_added"] = storage.merge_entries_into_category(" Прошивка и CFW", gh_entries)
        except Exception as e:
            logging.warning("GitHub sync failed after retries: %s", e)

        await storage.save_guides()
        return summary
