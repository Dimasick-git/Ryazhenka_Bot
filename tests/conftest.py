"""pytest configuration: ensure required data files exist before tests run."""
import json
import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def ensure_bot_settings():
    """Create bot_settings.json with defaults if absent (mirrors storage.load_settings logic)."""
    path = "bot_settings.json"
    defaults = {"auto_resolve_and_add": True, "yt_prune_removed": True, "yt_keep_limit": 50}
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(defaults, f, ensure_ascii=False, indent=2)
