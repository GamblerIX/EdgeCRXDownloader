"""Extension ID extraction, input parsing, and formatting utilities.

This module mirrors the logic in the Tauri version's ``utils/extension.ts``.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Optional

# --- Patterns ----------------------------------------------------------------

DIRECT_ID_PATTERN = re.compile(r"^[a-z]{32}$")
STORE_URL_PATTERN = re.compile(
    r"microsoftedge\.microsoft\.com/addons/detail/[^/]+/([a-z]{32})", re.IGNORECASE
)


# --- Data structures ----------------------------------------------------------

@dataclass
class DownloadInputPayload:
    """A single line of user input."""

    line_number: int
    value: str


# --- Public API ---------------------------------------------------------------

def extract_extension_id(value: str) -> Optional[str]:
    """Return the 32-char extension ID from *value*, or ``None``.

    Accepts either a bare 32-character ID or an Edge store detail URL.
    """
    normalized = value.strip().lower()
    if not normalized:
        return None

    if DIRECT_ID_PATTERN.match(normalized):
        return normalized

    match = STORE_URL_PATTERN.search(normalized)
    if match:
        return match.group(1)

    return None


def parse_extension_inputs(raw: str) -> list[DownloadInputPayload]:
    """Split multi-line *raw* text into individual input payloads."""
    results: list[DownloadInputPayload] = []
    for index, line in enumerate(raw.splitlines()):
        stripped = line.strip()
        if stripped:
            results.append(DownloadInputPayload(line_number=index + 1, value=stripped))
    return results


def format_bytes(value: float) -> str:
    """Format a byte count into a human-readable string (B / KB / MB / GB)."""
    if not math.isfinite(value) or value <= 0:
        return "0 B"

    units = ("B", "KB", "MB", "GB")
    unit_index = 0
    size = float(value)

    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024
        unit_index += 1

    digits = 0 if (size >= 100 or unit_index == 0) else 1
    return f"{size:.{digits}f} {units[unit_index]}"


def format_percent(downloaded: float, total: Optional[float] = None) -> str:
    """Format a download progress fraction as a percentage string."""
    if not total or total <= 0:
        return "..."

    percent = max(0.0, min(100.0, (downloaded / total) * 100))
    digits = 0 if percent >= 10 else 1
    return f"{percent:.{digits}f}%"
