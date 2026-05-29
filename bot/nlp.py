"""Search engine: BM25 + fuzzy matching + NLP preprocessing."""
import json
import logging
import math
import os
import re
from typing import Optional

from . import storage

# ── Levenshtein ───────────────────────────────────────────────
try:
    from Levenshtein import distance as levenshtein_distance
except Exception:
    def levenshtein_distance(a: str, b: str) -> int:
        if a == b:
            return 0
        la, lb = len(a), len(b)
        if la == 0:
            return lb
        if lb == 0:
            return la
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            cur = [i] + [0] * lb
            for j in range(1, lb + 1):
                cost = 0 if a[i - 1] == b[j - 1] else 1
                cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            prev = cur
        return prev[lb]


# ── Fuzzy matching ────────────────────────────────────────────
try:
    from rapidfuzz import fuzz
    _HAVE_FUZZY = True
except Exception:
    try:
        from fuzzywuzzy import fuzz  # type: ignore
        _HAVE_FUZZY = True
    except Exception:
        from difflib import SequenceMatcher

        class _SimpleFuzz:
            @staticmethod
            def token_set_ratio(a: str, b: str) -> int:
                return int(SequenceMatcher(None, a, b).ratio() * 100)

            @staticmethod
            def partial_ratio(a: str, b: str) -> int:
                return int(SequenceMatcher(None, a, b).ratio() * 100)

        fuzz = _SimpleFuzz()  # type: ignore
        _HAVE_FUZZY = False

# ── Stopwords & Synonyms ──────────────────────────────────────
STOP_WORDS = {
    "the", "a", "an", "to", "for", "how", "howto", "how-to",
    "как", "что", "почему", "про", "по", "на", "и", "в", "с", "от", "у", "это", "редо",
}

SYNONYMS: dict = {
    "batter": "battery", "batery": "battery", "batt": "battery", "battery": "battery",
    "batteryfix": "battery", "batteryfixes": "battery", "battery drain": "battery",
    "batt drain": "battery", "batteryproblem": "battery", "battery problem": "battery",
    "emummc": "emummc", "emmummc": "emummc", "emmumc": "emummc", "emumc": "emummc",
    "emu mmc": "emummc", "emu-mmc": "emummc", "emu nand": "emunand",
    "emunand": "emunand", "emu-nand": "emunand", "emunad": "emunand", "emunanc": "emunand",
    "cfw": "custom firmware", "atmo": "atmosphere", "atmos": "atmosphere",
    "atmosphere": "atmosphere", "fix": "fix", "repair": "fix",
    "install": "install", "remove": "remove",
}

# Load generated synonyms if present
try:
    _gen_path = os.path.join(os.path.dirname(__file__), "..", "generated_synonyms.json")
    if os.path.exists(_gen_path):
        with open(_gen_path, "r", encoding="utf-8") as _gf:
            for _k, _v in json.load(_gf).items():
                if _k and _v and _k not in SYNONYMS:
                    SYNONYMS[_k] = _v
except Exception:
    pass

# Keyboard layout maps
_EN_TO_RU = str.maketrans(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./",
    "йцукенгшщзхъфывапролджэячсмитьбю."
)
_RU_TO_EN = str.maketrans(
    "йцукенгшщзхъфывапролджэячсмитьбю.",
    "qwertyuiop[]asdfghjkl;'zxcvbnm,./"
)
_TRANSLIT_EN_TO_RU = {
    "sh": "ш", "ch": "ч", "yo": "ё", "zh": "ж", "yu": "ю", "ya": "я", "kh": "х",
}
_TRANSLIT_SIMPLE = str.maketrans({
    "a": "а", "b": "б", "c": "ц", "d": "д", "e": "е", "f": "ф", "g": "г", "h": "х",
    "i": "и", "j": "й", "k": "к", "l": "л", "m": "м", "n": "н", "o": "о", "p": "п",
    "q": "к", "r": "р", "s": "с", "t": "т", "u": "у", "v": "в", "w": "в",
    "x": "кс", "y": "ы", "z": "з",
})

# ── Tokenization & NLP ────────────────────────────────────────
def tokenize(text: str) -> list:
    if not text:
        return []
    return re.findall(r"[a-z0-9а-яё]+", text.lower())


def term_freq(tokens: list) -> dict:
    tf: dict = {}
    for t in tokens:
        tf[t] = tf.get(t, 0) + 1
    return tf


def cosine_sim(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b[k] for k, v in a.items() if k in b)
    norm_a = sum(v * v for v in a.values()) ** 0.5
    norm_b = sum(v * v for v in b.values()) ** 0.5
    if not norm_a or not norm_b:
        return 0.0
    return dot / (norm_a * norm_b)


def apply_synonyms(tokens: list) -> list:
    return [SYNONYMS.get(t, t) for t in tokens]


def simple_stem(token: str) -> str:
    t = token.lower()
    for suf in ("ing", "ed", "es", "s"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    for suf in ("ами", "ов", "ев", "ия", "ий", "ие"):
        if t.endswith(suf) and len(t) > len(suf) + 2:
            return t[: -len(suf)]
    return t


def fix_keyboard_layout(word: str) -> str:
    try:
        ru = word.translate(_EN_TO_RU)
        en = word.translate(_RU_TO_EN)
        if re.search("[a-z]", word) and re.search("[а-яё]", ru):
            return ru
        if re.search("[а-яё]", word) and re.search("[a-z]", en):
            return en
    except Exception:
        pass
    return word


def transliterate_basic(word: str) -> str:
    try:
        w = word
        for k, v in _TRANSLIT_EN_TO_RU.items():
            w = w.replace(k, v)
        w = w.translate(_TRANSLIT_SIMPLE)
        w = re.sub(r"[^а-яё]", "", w)
        if w:
            return w
    except Exception:
        pass
    return word


def normalize_repeats(word: str) -> str:
    return re.sub(r"(.)\1{2,}", r"\1\1", word)


def generate_variants(token: str) -> list:
    variants = {token}
    token = token.lower()
    kf = fix_keyboard_layout(token)
    variants.add(kf)
    tr = transliterate_basic(token)
    variants.add(tr)
    nr = normalize_repeats(token)
    variants.add(nr)
    variants.add(normalize_repeats(kf))
    variants.add(normalize_repeats(tr))
    new = set()
    for v in list(variants):
        if " " in v:
            new.add(v.replace(" ", ""))
            new.add(v.replace(" ", "-"))
        elif len(v) > 4 and v.startswith("emu") and len(v) > 3:
            new.add("emu " + v[3:])
        new.add(simple_stem(v))
    variants.update(new)
    return [v for v in variants if v and v not in STOP_WORDS]


def ngrams(tokens: list, n: int = 2) -> list:
    out = []
    L = len(tokens)
    for k in range(1, n + 1):
        for i in range(L - k + 1):
            out.append(" ".join(tokens[i : i + k]))
    return out


# ── BM25 index ────────────────────────────────────────────────
BM25_INDEX: Optional[dict] = None


def build_bm25_index() -> dict:
    docs = []
    doc_tfs = []
    df: dict = {}
    for cat, items in storage.GUIDES.items():
        if isinstance(items, dict):
            for title, url in items.items():
                docs.append({"title": title, "category": cat, "url": url})
                tokens = apply_synonyms(tokenize(title))
                tf = term_freq(tokens)
                doc_tfs.append(tf)
                for t in set(tokens):
                    df[t] = df.get(t, 0) + 1
    N = len(docs)
    avg_dl = sum(sum(t.values()) for t in doc_tfs) / max(N, 1)
    return {"docs": docs, "tfs": doc_tfs, "df": df, "N": N, "avg_dl": avg_dl}


def bm25_score(query_terms: list, index: dict, k1: float = 1.5, b: float = 0.75) -> list:
    N = index["N"]
    avg_dl = index["avg_dl"]
    scores = []
    for tf, doc_len in zip(index["tfs"], (sum(t.values()) for t in index["tfs"])):
        score = 0.0
        for term in query_terms:
            if term not in tf:
                continue
            df_t = index["df"].get(term, 0)
            if df_t == 0:
                continue
            idf = math.log((N - df_t + 0.5) / (df_t + 0.5) + 1)
            tf_val = tf[term]
            score += idf * (tf_val * (k1 + 1)) / (tf_val + k1 * (1 - b + b * doc_len / avg_dl))
        scores.append(score)
    return scores


def search_guides(query: str, top_n: int = 10) -> list:
    global BM25_INDEX
    if BM25_INDEX is None:
        BM25_INDEX = build_bm25_index()

    q_terms = apply_synonyms(tokenize(query))
    q_expanded: list = []
    for t in q_terms:
        q_expanded.append(t)
        q_expanded.extend(generate_variants(t))
    q_terms = q_expanded

    bm_scores = bm25_score(q_terms, BM25_INDEX) if BM25_INDEX["N"] > 0 else []
    bm_max = max(bm_scores, default=1e-9)

    # Iterate over the index's own doc list so bm_scores indices always align.
    q_lower = query.lower()
    results = []
    for idx, doc in enumerate(BM25_INDEX["docs"]):
        title, cat, url = doc["title"], doc["category"], doc["url"]
        t_lower = title.lower()
        if q_lower in t_lower or t_lower in q_lower:
            score = 95.0
        else:
            try:
                s1 = fuzz.token_set_ratio(q_lower, t_lower)
                s2 = fuzz.partial_ratio(q_lower, t_lower)
                score = float(int(s1 * 0.7 + s2 * 0.3))
            except Exception:
                score = 0.0
            if score < 60 and len(q_lower) <= 8 and len(t_lower) <= 30:
                try:
                    d = levenshtein_distance(q_lower, t_lower)
                    lev_score = (1 - d / max(1, max(len(q_lower), len(t_lower)))) * 100
                    score = max(score, lev_score)
                except Exception:
                    pass
        if bm_scores:
            bm_norm = min(100.0, bm_scores[idx] / (bm_max + 1e-9) * 100.0)
            score = max(score, bm_norm)
        results.append(({"title": title, "category": cat, "url": url}, score))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]


def invalidate_index() -> None:
    global BM25_INDEX
    BM25_INDEX = None
