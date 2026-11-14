"""Shared path helpers for knowledge-gardener machine-local state.

Plain stdlib only (no third-party deps): everything here runs inside hooks,
which cannot afford an import-time pip dependency.
"""
from __future__ import annotations

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
    """Where per-session pass state (throttle marker, lock) lives."""
    return kg_state_dir() / "sessions"


def last_recap_marker(sid8: str) -> pathlib.Path:
    """Path to the per-session pass marker (see shared/pass_state.py)."""
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f".last-recap-{safe_sid}"


def recap_lock_path(sid8: str) -> pathlib.Path:
    """Path to the per-session lock that keeps two passes from overlapping."""
    safe_sid = (sid8 or "unknown")[:8] or "unknown"
    return sessions_dir() / f".recap-{safe_sid}.lock"


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
