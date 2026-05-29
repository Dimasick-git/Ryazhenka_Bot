"""GitHub Atom feed and REST API helpers."""
import logging
import re
import xml.etree.ElementTree as ET

import aiohttp

from ..config import GITHUB_TOKEN

_TIMEOUT_30 = aiohttp.ClientTimeout(total=30)
_TIMEOUT_20 = aiohttp.ClientTimeout(total=20)


async def fetch_github_releases(repo: str) -> list:
    if not repo:
        return []
    try:
        async with aiohttp.ClientSession() as session:
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


async def fetch_github_repos(user_or_org: str, limit: int = 20) -> list:
    api_url = f"https://api.github.com/users/{user_or_org}/repos?per_page={limit}&type=public&sort=updated"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"} if GITHUB_TOKEN else {}
    async with aiohttp.ClientSession(headers=headers) as session:
        try:
            async with session.get(api_url, timeout=_TIMEOUT_20) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [(r.get("name"), r.get("html_url"), r.get("description") or "") for r in data]
        except Exception as e:
            logging.debug("GitHub API fetch failed: %s", e)
        # HTML fallback using the same session
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
