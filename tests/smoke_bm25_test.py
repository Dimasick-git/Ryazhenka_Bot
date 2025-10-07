from main import _build_bm25_index, _generate_variants

print('variants for batter:', _generate_variants('batter'))
idx = _build_bm25_index()
print('BM25 N=', idx.get('N'), 'avgdl=', idx.get('avgdl'))
