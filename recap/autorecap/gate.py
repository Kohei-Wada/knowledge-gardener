from __future__ import annotations

from typing import Mapping

DEFAULT_MIN_CALLS = 5
DEFAULT_MIN_MINUTES = 5
DEFAULT_INTERVAL_MINUTES = 30


def _int_env(env: Mapping[str, str], key: str, default: int) -> int:
    try:
        return int(env.get(key, ""))
    except (TypeError, ValueError):
        return default


def is_substantive(durable_change: bool, entry_count: int, duration_min: int,
                   env: Mapping[str, str]) -> bool:
    """Lenient gate: durable change OR activity above a floor warrants an LLM upgrade of the Timeline."""
    if durable_change:
        return True
    min_calls = _int_env(env, "KG_RECAP_MIN_CALLS", DEFAULT_MIN_CALLS)
    min_minutes = _int_env(env, "KG_RECAP_MIN_MINUTES", DEFAULT_MIN_MINUTES)
    return entry_count >= min_calls or duration_min >= min_minutes


def recap_interval_seconds(env: Mapping[str, str]) -> int:
    """Minimum gap between two Stop-hook passes of one session."""
    return max(0, _int_env(env, "KG_RECAP_INTERVAL_MINUTES", DEFAULT_INTERVAL_MINUTES)) * 60
