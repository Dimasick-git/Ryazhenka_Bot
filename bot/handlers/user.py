"""Backward-compatible re-export shim. New code should import from the sub-modules directly."""
from .ctx import DIALOG_CTX, DIALOG_CTX_TIME, _cleanup_dialog_ctx
from .search import router, _register_guide_meta, _perform_search
from .discovery import compute_ratings as _compute_ratings

__all__ = [
    "router",
    "DIALOG_CTX",
    "DIALOG_CTX_TIME",
    "_cleanup_dialog_ctx",
    "_register_guide_meta",
    "_perform_search",
    "_compute_ratings",
]
