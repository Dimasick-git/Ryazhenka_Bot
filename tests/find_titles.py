import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json
from pprint import pprint

with open(ROOT / 'guides.json', 'r', encoding='utf-8') as f:
    g = json.load(f)

keywords = ['emu', 'emummc', 'emunand', 'emu-mmc', 'emumc', 'emumm', 'emun']
matches = []
for cat, items in g.items():
    if isinstance(items, dict):
        for title, url in items.items():
            tl = title.lower()
            for k in keywords:
                if k in tl:
                    matches.append((cat, title, url))
                    break

print(f'Found {len(matches)} matches for keywords: {keywords}')
for m in matches[:200]:
    print('-', m[0], '|', m[1])
