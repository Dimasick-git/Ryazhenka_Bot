from .search import router as search_router
from .discovery import router as discovery_router
from .social import router as social_router
from .info import router as info_router
from .admin import router as admin_router
from .callbacks import router as callbacks_router
from .inline import router as inline_router
from .quiz import quiz_router

# Legacy alias — handlers registered on this router come from search.py
from .user import router as user_router

__all__ = [
    "search_router",
    "discovery_router",
    "social_router",
    "info_router",
    "user_router",
    "admin_router",
    "callbacks_router",
    "inline_router",
    "quiz_router",
]
