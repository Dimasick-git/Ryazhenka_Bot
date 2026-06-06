import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

# Telegram bot token format: <bot_id>:<hash> where bot_id is numeric digits
_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]{35,}$")

def is_valid_token(token: str) -> bool:
    return bool(token and _TOKEN_RE.match(token))

try:
    ADMIN_IDS: list[int] = [int(x) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip()]
except Exception:
    ADMIN_IDS = []

GITHUB_TOKEN: str = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO: str = os.environ.get("GITHUB_REPO", "")

try:
    SYNC_INTERVAL_SECONDS: int = int(os.environ.get("SYNC_INTERVAL_SECONDS", "3600"))
except Exception:
    SYNC_INTERVAL_SECONDS = 3600

ALLOWED_DOMAINS = ["github.com", "rentry.org", "github.io", "gamebrew.org", "gbatemp.net"]

ANTHROPIC_API_KEY: str = os.environ.get("ANTHROPIC_API_KEY", "")
# Model used for AI answers (override via env var to switch tiers)
AI_MODEL: str = os.environ.get("AI_MODEL", "claude-haiku-4-5-20251001")
