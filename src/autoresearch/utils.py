"""Shared utilities for autoresearch."""

from __future__ import annotations

import re


def parse_duration(duration: str) -> int:
    """Parse a duration string like '10m', '1h', '60s' to seconds.

    Supported formats: 10m, 5min, 1h, 2hr, 60s, 30sec, or bare number (treated as minutes).
    Returns 600 (10 minutes) if the string is empty or unparseable.
    """
    duration = duration.strip().lower()
    match = re.fullmatch(r"(\d+)\s*(min|m|hr|h|sec|s)?", duration)
    if not match:
        return 600
    value = int(match.group(1))
    if value <= 0:
        return 600
    unit = match.group(2) or "m"
    if unit in ("h", "hr"):
        return value * 3600
    if unit in ("s", "sec"):
        return value
    return value * 60
