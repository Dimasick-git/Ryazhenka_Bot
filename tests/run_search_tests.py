import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.nlp import search_guides

queries = ['battery fix', 'emmummc', 'emummc', 'battery', 'battery fix switch']
for q in queries:
    res = search_guides(q, top_n=5)
    print('\nQuery:', q)
    for doc, score in res:
        print('-', round(score,2), doc.get('title'), '->', doc.get('url'))
