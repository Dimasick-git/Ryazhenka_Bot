from .user import router as user_router
from .admin import router as admin_router
from .callbacks import router as callbacks_router
from .inline import router as inline_router
from .quiz import quiz_router

__all__ = ["user_router", "admin_router", "callbacks_router", "inline_router", "quiz_router"]
