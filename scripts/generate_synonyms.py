import json
import re
from pathlib import Path
from difflib import SequenceMatcher

ROOT = Path(__file__).resolve().parents[1]
GUIDES_PATH = ROOT / 'guides.json'
OUT_PATH = ROOT / 'generated_synonyms.json'

if not GUIDES_PATH.exists():
    print('guides.json not found')
    raise SystemExit(1)

with open(GUIDES_PATH, 'r', encoding='utf-8') as f:
    guides = json.load(f)

# tokenize helper
def tokenize(text):
    return re.findall(r"[a-z0-9а-яё]+", text.lower())

# collect tokens from titles
tokens = set()
for cat, items in guides.items():
    if isinstance(items, dict):
        for title in items.keys():
            for t in tokenize(title):
                tokens.add(t)
    elif isinstance(items, list):
        for it in items:
            title = it.get('title') if isinstance(it, dict) else str(it)
            for t in tokenize(title):
                tokens.add(t)

tokens = sorted(tokens)
print(f'Collected {len(tokens)} unique tokens from guides')

# seeds we want to ensure mappings for
seeds = ['emummc','emumc','emu mmc','emu-mmc','emunand','emu nand','emun','emmc','battery','battery fix','battery drain','cfw','atmosphere','atmos']

# fuzzy helper
def fuzz_ratio(a, b):
    return int(SequenceMatcher(None, a, b).ratio() * 100)

mappings = {}

# map variants of existing tokens to canonical token
for t in tokens:
    # generate simple variants
    mappings[t] = t
    mappings[t.replace('-', '')] = t
    mappings[t.replace('-', ' ')] = t
    mappings[t.replace(' ', '')] = t

# for seeds, find best matching token
for s in seeds:
    best = None
    best_score = 0
    for t in tokens:
        score = fuzz_ratio(s, t)
        if score > best_score:
            best_score = score
            best = t
    if best_score >= 65:
        mappings[s] = best
        print(f"Seed '{s}' -> '{best}' (score {best_score})")
    else:
        print(f"Seed '{s}' no close token (best {best} {best_score})")

# additionally generate keyboard-layout and translit simple variants for tokens
eng_to_ru = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./",
    "йцукенгшщзхъфывапролджэячсмитьбю."
)
ru_to_eng = str.maketrans(
    "йцукенгшщзхъфывапролджэячсмитьбю.",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
)

for t in list(tokens):
    try:
        ru = t.translate(eng_to_ru)
        en = t.translate(ru_to_eng)
        if ru and ru != t:
            mappings[ru] = t
        if en and en != t:
            mappings[en] = t
    except Exception:
        pass

# reduce collisions: keep first mapping for a key
final = {}
for k, v in mappings.items():
    if not k or k in final:
        continue
    final[k] = v

with open(OUT_PATH, 'w', encoding='utf-8') as f:
    json.dump(final, f, ensure_ascii=False, indent=2)

print(f'Wrote {len(final)} mappings to {OUT_PATH}')
