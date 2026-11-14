from __future__ import annotations

import datetime as _dt
import json
import pathlib


def _epoch_and_date(ts: str) -> tuple[float, str] | None:
    """UTC ISO ('...Z') → (epoch seconds, local YYYY-MM-DD). None if unparseable."""
    try:
        dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.timestamp(), dt.astimezone().date().isoformat()


def _text_of(content) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append((b.get("text") or "").strip())
        return "\n".join(t for t in out if t)
    return ""


def slice_transcript(transcript_path: str | None, since: float | None,
                     today_str: str, char_cap: int = 16000) -> str:
    """Plain-text user/assistant turns for `today_str` stamped after `since` (epoch seconds).

    Best-effort: returns "" on any missing/unreadable/garbled input. Drops
    thinking and tool_use/tool_result blocks (mechanical, already in Timeline).
    Truncates oldest-first to honour char_cap.
    """
    if not transcript_path:
        return ""
    p = pathlib.Path(transcript_path)
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    chunks: list[str] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict) or d.get("type") not in ("user", "assistant"):
            continue
        stamp = _epoch_and_date(d.get("timestamp") or "")
        if stamp is None:
            continue
        epoch, date = stamp
        if date != today_str:
            continue
        if since is not None and epoch <= since:
            continue
        text = _text_of((d.get("message") or {}).get("content"))
        if text:
            chunks.append(f"{d['type'].upper()}: {text}")
    joined = "\n\n".join(chunks)
    if len(joined) > char_cap:
        joined = joined[-char_cap:]  # keep most recent
    return joined
