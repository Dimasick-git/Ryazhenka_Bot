"""Background sync: YouTube channels + GitHub releases → GUIDES."""
import asyncio
import logging
import re

import aiohttp

from .. import storage
from ..config import GITHUB_REPO
from . import youtube, github

_sync_lock = asyncio.Lock()


def _is_valid_url(url: str) -> bool:
    return isinstance(url, str) and url.startswith("https://")


async def resolve_duckduckgo_first(title: str) -> str:
    from ..config import ALLOWED_DOMAINS
    import urllib.parse
    query = f"{title} Nintendo Switch site:github.com OR site:rentry.org OR site:github.io OR site:gamebrew.org OR site:gbatemp.net"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://duckduckgo.com/html/", data={"q": query},
                timeout=aiohttp.ClientTimeout(total=30),
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
                        if any(d in net for d in ALLOWED_DOMAINS):
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
    from ..config import ADMIN_IDS
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
                    target_cat = "🔎 Авто-найденные"
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
        storage.save_guides()
        logging.info("Resolved %d auto-guides to direct links", len(changed))
        if notify_admins and ADMIN_IDS:
            msg = "🔎 Найдены прямые ссылки для авто-гайдов:\n"
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
                    resolved = await youtube.resolve_channel_id(ch)
                    if resolved:
                        cid = resolved
                logging.info("Fetching YouTube for channel '%s' resolved to '%s'", ch, cid)
                channel_title, yt_entries = await youtube.fetch_youtube_videos(cid) if cid else (None, [])
                logging.info("Fetched %d entries from YouTube channel %s (%s)", len(yt_entries), cid, channel_title)
                # Filter out entries with invalid URLs
                yt_entries = [(t, u) for t, u in yt_entries if _is_valid_url(u)]
                if yt_entries:
                    # persist UC id for stability
                    if cid and not ch.startswith("UC"):
                        try:
                            idx = storage.YT_CHANNELS.index(ch)
                            storage.YT_CHANNELS[idx] = cid
                            storage.save_yt_channels()
                        except ValueError:
                            pass
                    safe_name = re.sub(r"[^0-9a-zA-Zа-яёА-ЯЁ _\-]", " ", channel_title or ch or cid or "Видео").strip()
                    cat_name = f"YouTube - {safe_name}"

                    def _date_key(tu):
                        m = re.match(r"\[(\d{4}-\d{2}-\d{2})\]", tu[0])
                        return m.group(1) if m else "1970-01-01"

                    yt_entries.sort(key=_date_key, reverse=True)
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
                    keys_sorted = sorted(keys, key=lambda k: re.match(r"\[(\d{4}-\d{2}-\d{2})\]", k).group(1)
                                         if re.match(r"\[(\d{4}-\d{2}-\d{2})\]", k) else "1970-01-01", reverse=True)
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
            gh_entries = await github.fetch_github_releases(GITHUB_REPO) if GITHUB_REPO else []
            # Filter out entries with invalid URLs
            gh_entries = [(t, u) for t, u in gh_entries if _is_valid_url(u)]
            if gh_entries:
                summary["github_added"] = storage.merge_entries_into_category("📦 Прошивка и CFW", gh_entries)
        except Exception as e:
            logging.warning("GitHub sync failed: %s", e)

        storage.save_guides()
        return summary
