"""User-facing error helpers.

This mirrors ``utils/error.ts`` from the Tauri version.
"""

from __future__ import annotations


def get_user_facing_error(error: object) -> str:
    """Return a human-readable error string from *error*.

    Tries ``str``, ``Exception.args``, and a dict-like ``message`` attribute
    before falling back to a generic message.
    """
    if isinstance(error, str) and error.strip():
        return error.strip()

    if isinstance(error, Exception):
        msg = str(error).strip()
        if msg:
            return msg

    if hasattr(error, "message"):
        msg = str(getattr(error, "message", "")).strip()
        if msg:
            return msg

    return "下载过程中发生未知错误，请稍后再试。"
