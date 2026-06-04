import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

BOT_TOKEN: str = os.environ.get("BOT_TOKEN", "")

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
AI_MODEL: str = os.environ.get("AI_MODEL", "claude-haiku-4-5")
