"""
🧪 Core unit tests for Ryazhenka Bot
Tests key functions without requiring a live Telegram connection.
"""
import json
import os
import sys
import pytest

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Patch BOT_TOKEN before importing main to avoid Bot() init error
os.environ.setdefault("BOT_TOKEN", "0000000000:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")


class TestNormalizeUrl:
    """Tests for URL normalization utility."""

    def test_youtube_short_link(self):
        from main import normalize_url
        result = normalize_url("https://youtu.be/dQw4w9WgXcQ")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_full_link(self):
        from main import normalize_url
        result = normalize_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10")
        assert result == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_github_link(self):
        from main import normalize_url
        result = normalize_url("https://github.com/user/repo/")
        assert result == "https://github.com/user/repo"

    def test_empty_url(self):
        from main import normalize_url
        assert normalize_url("") == ""

    def test_none_url(self):
        from main import normalize_url
        assert normalize_url(None) == ""


class TestNormalize:
    """Tests for text normalization."""

    def test_lowercase(self):
        from main import normalize
        assert normalize("BATTERY FIX") == "battery fix"

    def test_punctuation_removal(self):
        from main import normalize
        assert normalize("battery-fix!") == "battery fix"

    def test_empty_string(self):
        from main import normalize
        assert normalize("") == ""

    def test_extra_spaces(self):
        from main import normalize
        assert normalize("  battery   fix  ") == "battery fix"


class TestTokenize:
    """Tests for tokenization."""

    def test_basic_tokenize(self):
        from main import _tokenize
        tokens = _tokenize("battery fix guide")
        assert "battery" in tokens
        assert "fix" in tokens
        assert "guide" in tokens

    def test_cyrillic(self):
        from main import _tokenize
        tokens = _tokenize("прошивка атмосфера")
        assert "прошивка" in tokens
        assert "атмосфера" in tokens

    def test_empty(self):
        from main import _tokenize
        assert _tokenize("") == []


class TestApplySynonyms:
    """Tests for synonym expansion."""

    def test_cfw_synonym(self):
        from main import _apply_synonyms
        result = _apply_synonyms(["cfw"])
        assert "custom firmware" in result

    def test_atmo_synonym(self):
        from main import _apply_synonyms
        result = _apply_synonyms(["atmo"])
        assert "atmosphere" in result

    def test_unknown_token(self):
        from main import _apply_synonyms
        result = _apply_synonyms(["unknowntoken"])
        assert "unknowntoken" in result


class TestGuidesJson:
    """Tests for guides.json data integrity."""

    def test_guides_json_loads(self):
        with open("guides.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict), "guides.json must be a dict"

    def test_guides_have_categories(self):
        with open("guides.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) > 0, "guides.json must have at least one category"

    def test_guides_entries_are_dicts(self):
        with open("guides.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for cat, items in data.items():
            assert isinstance(items, dict), f"Category {cat!r} must be a dict"

    def test_guides_urls_are_strings(self):
        with open("guides.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        for cat, items in data.items():
            for title, url in items.items():
                if url:
                    assert isinstance(url, str), f"URL for {title!r} must be a string"


class TestBotSettings:
    """Tests for bot_settings.json."""

    def test_settings_json_loads(self):
        with open("bot_settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_auto_resolve_setting_exists(self):
        with open("bot_settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "auto_resolve_and_add" in data


class TestBM25Index:
    """Tests for BM25 search index."""

    def test_bm25_builds(self):
        from main import _build_bm25_index
        index = _build_bm25_index()
        assert index is not None
        assert "N" in index
        assert index["N"] >= 0

    def test_bm25_scores_returns_list(self):
        from main import _build_bm25_index, _bm25_score
        index = _build_bm25_index()
        if index and index["N"] > 0:
            scores = _bm25_score(["battery"], index)
            assert isinstance(scores, list)
            assert len(scores) == index["N"]


class TestSearchGuides:
    """Tests for the main search function."""

    def test_search_returns_results(self):
        from main import _search_guides
        results = _search_guides("battery", top_n=5)
        assert isinstance(results, list)

    def test_search_result_structure(self):
        from main import _search_guides
        results = _search_guides("atmosphere", top_n=3)
        for doc, score in results:
            assert isinstance(doc, dict)
            assert "title" in doc
            assert isinstance(score, (int, float))

    def test_search_empty_query(self):
        from main import _search_guides
        results = _search_guides("", top_n=5)
        assert isinstance(results, list)


class TestDeduplication:
    """Tests for URL deduplication."""

    def test_normalize_url_deduplication(self):
        from main import normalize_url
        url1 = "https://youtu.be/dQw4w9WgXcQ"
        url2 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"
        assert normalize_url(url1) == normalize_url(url2)

    def test_github_url_deduplication(self):
        from main import normalize_url
        url1 = "https://github.com/user/repo/"
        url2 = "https://github.com/user/repo"
        assert normalize_url(url1) == normalize_url(url2)
