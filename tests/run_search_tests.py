import sys
from pathlib import Path

# ensure project root is on sys.path so we can import main even when script
# is executed directly with an absolute path
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import _search_guides

queries = ['battery fix', 'emmummc', 'emummc', 'battery', 'battery fix switch']
for q in queries:
    res = _search_guides(q, top_n=5)
    print('\nQuery:', q)
    for doc, score in res:
        print('-', round(score,2), doc.get('title'), '->', doc.get('url'))
