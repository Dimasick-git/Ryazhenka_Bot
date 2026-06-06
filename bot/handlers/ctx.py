"""Shared in-memory dialog context — used by search and callback handlers."""
import heapq
import time

# key -> doc  (TTL: 1h, max 500 entries)
DIALOG_CTX: dict = {}
DIALOG_CTX_TIME: dict = {}


def _cleanup_dialog_ctx() -> None:
    now = time.time()
    stale = [k for k, v in DIALOG_CTX_TIME.items() if now - v > 3600]
    for k in stale:
        DIALOG_CTX.pop(k, None)
        DIALOG_CTX_TIME.pop(k, None)
    overflow = len(DIALOG_CTX) - 500
    if overflow > 0:
        oldest_keys = heapq.nsmallest(overflow, DIALOG_CTX_TIME, key=DIALOG_CTX_TIME.__getitem__)
        for k in oldest_keys:
            DIALOG_CTX.pop(k, None)
            DIALOG_CTX_TIME.pop(k, None)
