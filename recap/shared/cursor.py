"""Per-session recap cursor I/O.

The cursor holds a single HH:MM line — the last log entry included in the most
recent successfully-written recap block. Split out of the former
recap/recap_common.py grab-bag.
"""
from __future__ import annotations

import os
import re

from .hook_io import log
from .paths import cursor_path

SINCE_RE = re.compile(r"^\d{2}:\d{2}$")


def read_cursor(sid8: str) -> str | None:
    p = cursor_path(sid8)
    try:
        text = p.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not SINCE_RE.match(text):
        log(f"ignoring malformed cursor at {p}: {text!r}")
        return None
    return text


def write_cursor(sid8: str, hhmm: str, covered_at: float | None = None) -> None:
    """Record the last entry a block covers. `covered_at` back-dates the file
    to when the log was read, so entries captured during the pass stay uncovered."""
    p = cursor_path(sid8)
    try:
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        p.write_text(hhmm + "\n", encoding="utf-8")
        if covered_at is not None:
            os.utime(p, (covered_at, covered_at))
    except OSError as e:
        log(f"cursor write failed: {e!r}")


def covered_at(sid8: str) -> float | None:
    """When the last successful pass read the log; None before the first one."""
    try:
        return cursor_path(sid8).stat().st_mtime
    except OSError:
        return None
