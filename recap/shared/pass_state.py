"""Per-session pass state, kept in one marker file.

Its mtime is when the last pass started, whether or not it wrote anything:
that throttles Stop passes. Its content is when the last pass that did write
read the transcript: tool calls stamped after it are not in any block yet.
The two differ after a pass that failed or was killed mid-flight.
"""
from __future__ import annotations

import os

from .hook_io import log
from .paths import last_recap_marker


def last_pass_started(sid8: str) -> float | None:
    try:
        return last_recap_marker(sid8).stat().st_mtime
    except OSError:
        return None


def covered_until(sid8: str) -> float | None:
    try:
        return float(last_recap_marker(sid8).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def mark_pass_started(sid8: str, started: float) -> None:
    marker = last_recap_marker(sid8)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.touch()
        os.utime(marker, (started, started))
    except OSError as e:
        log(f"pass marker write failed: {e!r}")


def mark_covered(sid8: str, started: float) -> None:
    marker = last_recap_marker(sid8)
    try:
        marker.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        marker.write_text(f"{started}\n", encoding="utf-8")
        os.utime(marker, (started, started))
    except OSError as e:
        log(f"pass marker write failed: {e!r}")
