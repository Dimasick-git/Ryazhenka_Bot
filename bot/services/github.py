"""GitHub Atom feed and REST API helpers."""
import asyncio
import logging
import re
import time
import xml.etree.ElementTree as ET

import aiohttp

from ..config import GITHUB_TOKEN

_TIMEOUT_30 = aiohttp.ClientTimeout(total=30)
_TIMEOUT_20 = aiohttp.ClientTimeout(total=20)

# Reuse a single session across calls (created lazily, one per event loop).
_session: aiohttp.ClientSession | None = None

# Release cache: repo_full → (release_dict | None, timestamp)
_releases_cache: dict[str, tuple] = {}
_RELEASES_CACHE_TTL = 3600  # 1 hour

_RYAZHA_REPOS = [
    "Dimasick-git/RCU",
    "Dimasick-git/AIO-Switch-Updater",
    "Dimasick-git/ovlSysmodules",
    "Dimasick-git/FPSLocker",
    "Dimasick-git/nx-ovlloader",
    "Dimasick-git/EdiZon",
    "Dimasick-git/Fizeau",
    "Dimasick-git/Mission-Control",
    "Dimasick-git/libryazhahand",
    "Dimasick-git/RyazhaTune",
    "Dimasick-git/Ryazha-Status-Monitor",
    "Dimasick-git/Ryazha-cheker",
    "Dimasick-git/RyazhaAI",
    "Dimasick-git/Atmosphere-RYZ",
    "Dimasick-git/Hekate",
    "Dimasick-git/SwitchWave",
    "Dimasick-git/ReverseNX-RT",
]


def _get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
        connector = aiohttp.TCPConnector(limit=10, limit_per_host=5)
        _session = aiohttp.ClientSession(headers=headers, connector=connector)
    return _session


async def close_session() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
        _session = None


async def fetch_github_releases(repo: str) -> list:
    if not repo:
        return []
    try:
        session = _get_session()
        async with session.get(
            f"https://github.com/{repo}/releases.atom",
            timeout=_TIMEOUT_30,
        ) as resp:
            resp.raise_for_status()
            text = await resp.text()
        root = ET.fromstring(text)
        ns = "{http://www.w3.org/2005/Atom}"
        entries = []
        for entry in root.findall(f"{ns}entry"):
            title_el = entry.find(f"{ns}title")
            link_el = entry.find(f"{ns}link")
            if title_el is None:
                continue
            url = link_el.attrib.get("href") if link_el is not None else None
            if url:
                entries.append((title_el.text or "", url))
        return entries
    except Exception as e:
        logging.warning("Failed fetching GitHub releases: %s", e)
        return []


async def fetch_latest_release(repo: str) -> dict | None:
    """Fetch the latest release for a repo via GitHub REST API."""
    try:
        session = _get_session()
        async with session.get(
            f"https://api.github.com/repos/{repo}/releases/latest",
            timeout=_TIMEOUT_20,
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            data = await resp.json()
            return {
                "tag": data.get("tag_name", ""),
                "name": data.get("name", ""),
                "url": data.get("html_url", ""),
                "date": (data.get("published_at") or "")[:10],
                "prerelease": data.get("prerelease", False),
                "assets": [
                    {
                        "name": a.get("name", ""),
                        "url": a.get("browser_download_url", ""),
                        "size": a.get("size", 0),
                    }
                    for a in data.get("assets", [])[:4]
                ],
            }
    except Exception as e:
        logging.debug("Failed fetching release for %s: %s", repo, e)
        return None


async def fetch_ryazha_releases() -> list[tuple[str, dict]]:
    """Fetch latest releases from all Ryazhenka repos concurrently, with 1h cache."""
    now = time.monotonic()
    cached_results: list[tuple[str, dict]] = []
    repos_to_fetch: list[str] = []

    for repo in _RYAZHA_REPOS:
        entry = _releases_cache.get(repo)
        if entry is not None:
            data, ts = entry
            if now - ts < _RELEASES_CACHE_TTL:
                if data:
                    cached_results.append((repo, data))
                continue
        repos_to_fetch.append(repo)

    if repos_to_fetch:
        results = await asyncio.gather(
            *[fetch_latest_release(r) for r in repos_to_fetch],
            return_exceptions=True,
        )
        for repo, result in zip(repos_to_fetch, results):
            if isinstance(result, dict):
                _releases_cache[repo] = (result, now)
                cached_results.append((repo, result))
            else:
                _releases_cache[repo] = (None, now)

    cached_results.sort(key=lambda x: x[1].get("date", ""), reverse=True)
    return cached_results


async def fetch_github_repos(user_or_org: str, limit: int = 20) -> list:
    api_url = f"https://api.github.com/users/{user_or_org}/repos?per_page={limit}&type=public&sort=updated"
    session = _get_session()
    try:
        async with session.get(api_url, timeout=_TIMEOUT_20) as resp:
            if resp.status == 200:
                data = await resp.json()
                return [(r.get("name"), r.get("html_url"), r.get("description") or "") for r in data]
    except Exception as e:
        logging.debug("GitHub API fetch failed: %s", e)
    # HTML fallback
    try:
        async with session.get(
            f"https://github.com/{user_or_org}?tab=repositories",
            timeout=_TIMEOUT_20,
        ) as resp:
            text = await resp.text()
        repos = []
        for m in re.finditer(r'itemprop="name codeRepository">\s*<a[^>]+href="/[^/]+/([^\"]+)"', text):
            name = m.group(1).strip()
            repos.append((name, f"https://github.com/{user_or_org}/{name}", ""))
            if len(repos) >= limit:
                break
        return repos
    except Exception:
        return []
