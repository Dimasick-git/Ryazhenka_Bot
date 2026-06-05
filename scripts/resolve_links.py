#!/usr/bin/env python3
r"""
Resolve DuckDuckGo search links in guides.json (category 'Авто-гайды')
into direct links on allowed domains (github.com, rentry.org, github.io,
gamebrew.org, gbatemp.net).

Usage (PowerShell):
    .\.venv\Scripts\Activate.ps1
    python .\resolve_links.py

Stdlib only (urllib). Writes back to guides.json.
"""
import json
import urllib.parse
import urllib.request
import re
import time
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
GUIDES_PATH = ROOT / 'guides.json'
ALLOWED_DOMAINS = ['github.com', 'rentry.org', 'github.io', 'gamebrew.org', 'gbatemp.net']


def resolve_one(title: str, timeout=20):
    query = f"{title} Nintendo Switch site:github.com OR site:rentry.org OR site:github.io OR site:gamebrew.org OR site:gbatemp.net"
    url = 'https://duckduckgo.com/html/'
    data_post = urllib.parse.urlencode({'q': query}).encode('utf-8')
    req = urllib.request.Request(url, data=data_post, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode('utf-8', errors='ignore')
            hrefs = re.findall(r'href=\"([^\"]+)\"', text)
            for h in hrefs:
                try:
                    parsed = urllib.parse.urlparse(h)
                    if parsed.path.startswith('/l/'):
                        qs = urllib.parse.parse_qs(parsed.query)
                        uddg = qs.get('uddg') or qs.get('uddg[]')
                        if uddg:
                            target = urllib.parse.unquote(uddg[0])
                            net = urllib.parse.urlparse(target).netloc
                            for d in ALLOWED_DOMAINS:
                                if d in net:
                                    return target
                    else:
                        net = parsed.netloc
                        for d in ALLOWED_DOMAINS:
                            if d in net:
                                return h
                except Exception:
                    continue
    except Exception as e:
        return None
    return None


def main():
    if not GUIDES_PATH.exists():
        print('guides.json not found in', GUIDES_PATH)
        sys.exit(1)

    with open(GUIDES_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)

    cat = '🆕 Авто-гайды'
    if cat not in data:
        print('No auto-guides category found')
        sys.exit(0)

    items = [(t, u) for t, u in data[cat].items() if 'duckduckgo.com' in (u or '')]
    total = len(items)
    print(f'Found {total} DuckDuckGo entries to resolve')
    if total == 0:
        return

    resolved = []
    for idx, (title, old) in enumerate(items, start=1):
        print(f'[{idx}/{total}] Resolving: {title}')
        found = resolve_one(title)
        if found:
            data[cat][title] = found
            resolved.append((title, found))
            print(f'  -> {found}')
        else:
            print('  -> nothing found')
        time.sleep(0.4)  # polite delay

    if resolved:
        with open(GUIDES_PATH, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f'Updated guides.json with {len(resolved)} resolved links')
    else:
        print('No links were resolved')


if __name__ == '__main__':
    main()
