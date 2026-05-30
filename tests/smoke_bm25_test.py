import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.nlp import build_bm25_index, generate_variants

print('variants for batter:', generate_variants('batter'))
idx = build_bm25_index()
print('BM25 N=', idx.get('N'), 'avgdl=', idx.get('avgdl'))
