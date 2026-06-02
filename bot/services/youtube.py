"""YouTube RSS feed fetching and channel ID resolution."""
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET

import aiohttp

from .. import storage

_TIMEOUT = aiohttp.ClientTimeout(total=30)


async def _do_fetch(session: aiohttp.ClientSession, url: str, method: str = "get", data: dict = None) -> str:
    if method == "post":
        async with session.post(url, data=data, timeout=_TIMEOUT) as resp:
            resp.raise_for_status()
            return await resp.text()
    async with session.get(url, timeout=_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.text()


async def resolve_channel_id(identifier: str) -> str:
    if not identifier:
        return None
    identifier = identifier.strip()
    if identifier.startswith("UC"):
        return identifier
    if identifier in storage.YT_CACHE and storage.YT_CACHE[identifier].get("channel_id"):
        return storage.YT_CACHE[identifier]["channel_id"]
    if identifier.startswith("http") or "youtube.com" in identifier:
        try:
            parsed = urllib.parse.urlparse(identifier)
            path = parsed.path or ""
            m = re.search(r"/channel/(UC[0-9A-Za-z_-]+)", path)
            if m:
                return m.group(1)
            for pat in (r"/@([^/]+)", r"/c/([^/]+)", r"/user/([^/]+)"):
                m2 = re.search(pat, path)
                if m2:
                    identifier = m2.group(1)
                    break
        except Exception:
            pass
    if identifier.startswith("@"):
        identifier = identifier[1:]

    async def _cache_and_return(cid: str) -> str:
        storage.YT_CACHE[identifier] = {"channel_id": cid}
        await storage.save_yt_cache()
        return cid

    async with aiohttp.ClientSession() as session:
        try:
            text = await _do_fetch(session, f"https://www.youtube.com/feeds/videos.xml?user={identifier}")
            if text and "<entry>" in text:
                m = re.search(r"<yt:channelId>(UC[0-9A-Za-z_-]+)</yt:channelId>", text)
                if m:
                    return await _cache_and_return(m.group(1))
        except Exception as e:
            logging.debug("User RSS lookup failed for %s: %s", identifier, e)

        try:
            html = await _do_fetch(session, f"https://www.youtube.com/{identifier}")
            for pat in (r'"channelId"\s*:\s*"(UC[0-9A-Za-z_-]+)"', r"/channel/(UC[0-9A-Za-z_-]+)"):
                m = re.search(pat, html)
                if m:
                    return await _cache_and_return(m.group(1))
        except Exception as e:
            logging.debug("HTML lookup failed for %s: %s", identifier, e)

        try:
            text = await _do_fetch(
                session, "https://duckduckgo.com/html/", method="post",
                data={"q": f"{identifier} site:youtube.com/channel"},
            )
            m = re.search(r'href="([^"]*/channel/(UC[0-9A-Za-z_-]+)[^"]*)"', text)
            if m:
                mm = re.search(r"/channel/(UC[0-9A-Za-z_-]+)", m.group(1))
                if mm:
                    return await _cache_and_return(mm.group(1))
        except Exception:
            pass

    return None


async def fetch_youtube_videos(channel_id: str) -> tuple:
    if not channel_id:
        return None, []
    feed_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    try:
        async with aiohttp.ClientSession() as session:
            text = await _do_fetch(session, feed_url)
        root = ET.fromstring(text)
        ns = "{http://www.w3.org/2005/Atom}"
        ch_title_el = root.find(f"{ns}title")
        channel_title = (ch_title_el.text or "").strip() if ch_title_el is not None else None
        if channel_title:
            storage.YT_CACHE.setdefault(channel_id, {})
            storage.YT_CACHE[channel_id]["channel_id"] = channel_id
            storage.YT_CACHE[channel_id]["title"] = channel_title
            await storage.save_yt_cache()
        entries = []
        for entry in root.findall(f"{ns}entry"):
            title_el = entry.find(f"{ns}title")
            link_el = entry.find(f"{ns}link")
            pub_el = entry.find(f"{ns}published")
            if title_el is None:
                continue
            title = (title_el.text or "").strip()
            url = link_el.attrib.get("href") if link_el is not None else None
            if pub_el is not None and pub_el.text:
                m = re.match(r"(\d{4}-\d{2}-\d{2})", pub_el.text.strip())
                if m:
                    title = f"[{m.group(1)}] {title}"
            if url:
                entries.append((title, url))
        return channel_title, entries
    except Exception as e:
        logging.warning("Failed fetching YouTube feed for %s: %s", channel_id, e)
        return None, []
