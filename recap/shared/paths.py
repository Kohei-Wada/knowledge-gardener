"""Shared path helpers for knowledge-gardener machine-local state.

Used by:
- recap/capture/ (PostToolUse hook — writes session log entries)
- recap/aggregate/ (reads session logs)
- recap/autorecap/ (reads session log, writes throttle marker)

All three previously duplicated the XDG_STATE_HOME resolution and the
"<state>/knowledge-gardener/sessions/" path construction. Centralized here
so future changes (e.g. moving sessions/ to data/ per XDG, or adding
encryption) happen in one place.

Plain stdlib only (no third-party deps), since the capture hook runs inside a
synchronous PostToolUse hook and the auto-recap hook runs inside a Stop hook
— neither can afford an import-time pip dependency.
"""
from __future__ import annotations

import datetime as _dt
import os
import pathlib


def state_home() -> pathlib.Path:
    """Resolve $XDG_STATE_HOME with the standard ~/.local/state fallback."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return pathlib.Path(base)


def kg_state_dir() -> pathlib.Path:
    """Root of knowledge-gardener's machine-local state tree."""
    return state_home() / "knowledge-gardener"


def sessions_dir() -> pathlib.Path:
    """Where per-session capture logs live."""
    return kg_state_dir() / "sessions"


def session_log_path(sid8: str, date: _dt.date | None = None) -> pathlib.Path:
    """Path to one session's capture log: `<sessions>/<YYYY-MM-DD>-<sid8>.log`."""
    d = (date or _dt.date.today()).isoformat()
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f"{d}-{safe_sid}.log"


def last_recap_marker(sid8: str) -> pathlib.Path:
    """Path to the per-session throttle marker; its mtime is when the last pass started."""
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f".last-recap-{safe_sid}"


def recap_lock_path(sid8: str) -> pathlib.Path:
    """Path to the per-session lock that keeps two passes from overlapping."""
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f".recap-{safe_sid}.lock"


def cursor_path(sid8: str) -> pathlib.Path:
    """Path to the per-session recap cursor file.

    Holds a single HH:MM line — the last log entry included in the most
    recent successfully-written block; scopes the next pass's new slice. Its
    mtime is when that pass read the log, so a log newer than it has activity
    no block covers yet.
    """
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f"{safe_sid}.cursor"


def discovery_cache_dir() -> pathlib.Path:
    """Where auto-recap caches per-vault README-driven discovery results."""
    return kg_state_dir() / "discovery"


def discovery_cache_path(readme_hash: str) -> pathlib.Path:
    """Path to one vault's cached discovery, keyed by README content hash.

    The hash uniquely identifies a README revision; when the README changes
    the hash changes, naturally invalidating the cache without any TTL.
    """
    safe = "".join(c for c in readme_hash if c.isalnum())[:64] or "unknown"
    return discovery_cache_dir() / f"{safe}.json"
