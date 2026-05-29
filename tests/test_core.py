"""
Core unit tests for Ryazhenka Bot.
Tests key functions without requiring a live Telegram connection.
"""
import json
import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("BOT_TOKEN", "TEST_TOKEN_PLACEHOLDER_DO_NOT_USE")

from bot.storage import normalize_url, normalize
from bot.nlp import tokenize, apply_synonyms, build_bm25_index, bm25_score, search_guides


class TestNormalizeUrl:
    def test_youtube_short_link(self):
        assert normalize_url("https://youtu.be/dQw4w9WgXcQ") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_youtube_full_link(self):
        assert normalize_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10") == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_github_link(self):
        assert normalize_url("https://github.com/user/repo/") == "https://github.com/user/repo"

    def test_empty_url(self):
        assert normalize_url("") == ""

    def test_none_url(self):
        assert normalize_url(None) == ""


class TestNormalize:
    def test_lowercase(self):
        assert normalize("BATTERY FIX") == "battery fix"

    def test_punctuation_removal(self):
        assert normalize("battery-fix!") == "battery fix"

    def test_empty_string(self):
        assert normalize("") == ""

    def test_extra_spaces(self):
        assert normalize("  battery   fix  ") == "battery fix"


class TestTokenize:
    def test_basic_tokenize(self):
        tokens = tokenize("battery fix guide")
        assert "battery" in tokens
        assert "fix" in tokens
        assert "guide" in tokens

    def test_cyrillic(self):
        tokens = tokenize("прошивка атмосфера")
        assert "прошивка" in tokens
        assert "атмосфера" in tokens

    def test_empty(self):
        assert tokenize("") == []


class TestApplySynonyms:
    def test_cfw_synonym(self):
        result = apply_synonyms(["cfw"])
        assert "custom firmware" in result

    def test_atmo_synonym(self):
        result = apply_synonyms(["atmo"])
        assert "atmosphere" in result

    def test_unknown_token(self):
        result = apply_synonyms(["unknowntoken"])
        assert "unknowntoken" in result


class TestGuidesJson:
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
    def test_settings_json_loads(self):
        with open("bot_settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_auto_resolve_setting_exists(self):
        with open("bot_settings.json", "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "auto_resolve_and_add" in data


class TestBM25Index:
    def test_bm25_builds(self):
        index = build_bm25_index()
        assert index is not None
        assert "N" in index
        assert index["N"] >= 0

    def test_bm25_scores_returns_list(self):
        index = build_bm25_index()
        if index and index["N"] > 0:
            scores = bm25_score(["battery"], index)
            assert isinstance(scores, list)
            assert len(scores) == index["N"]


class TestSearchGuides:
    def test_search_returns_results(self):
        results = search_guides("battery", top_n=5)
        assert isinstance(results, list)

    def test_search_result_structure(self):
        results = search_guides("atmosphere", top_n=3)
        for doc, score in results:
            assert isinstance(doc, dict)
            assert "title" in doc
            assert isinstance(score, (int, float))

    def test_search_empty_query(self):
        results = search_guides("", top_n=5)
        assert isinstance(results, list)


class TestDeduplication:
    def test_normalize_url_deduplication(self):
        url1 = "https://youtu.be/dQw4w9WgXcQ"
        url2 = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"
        assert normalize_url(url1) == normalize_url(url2)

    def test_github_url_deduplication(self):
        url1 = "https://github.com/user/repo/"
        url2 = "https://github.com/user/repo"
        assert normalize_url(url1) == normalize_url(url2)
