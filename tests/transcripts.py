"""Build Claude Code transcript fixtures for the recap tests."""
from __future__ import annotations

import datetime as _dt
import itertools
import json
from pathlib import Path

_ids = itertools.count(1)


def _iso(when: _dt.datetime) -> str:
    return when.astimezone(_dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def tool_call(tool: str, tool_input: dict, when: _dt.datetime, *, result=None,
              is_error: bool = False, use_id: str | None = None) -> list[str]:
    """The two transcript lines of one tool call whose result arrived at `when`."""
    use_id = use_id or f"toolu_{next(_ids):06d}"
    use = {
        "type": "assistant",
        "timestamp": _iso(when - _dt.timedelta(milliseconds=1)),
        "message": {"role": "assistant",
                    "content": [{"type": "tool_use", "id": use_id, "name": tool, "input": tool_input}]},
    }
    res = {
        "type": "user",
        "timestamp": _iso(when),
        "message": {"role": "user",
                    "content": [{"type": "tool_result", "tool_use_id": use_id, "content": "ok", "is_error": is_error}]},
    }
    if result is not None:
        res["toolUseResult"] = result
    return [json.dumps(use), json.dumps(res)]


def _input_for(tool: str, target: str, vault: Path | None) -> tuple[str, dict]:
    if tool in ("Edit", "Write", "NotebookEdit"):
        return tool, {"file_path": target}
    if tool == "Bash":
        return tool, {"command": target}
    if tool == "WebSearch":
        return tool, {"query": target}
    if tool == "WebFetch":
        return tool, {"url": target}
    if tool == "Agent":
        sub, _, desc = target.partition(":")
        return tool, {"subagent_type": sub, "description": desc}
    if tool == "ReadNote":
        return "Read", {"file_path": str(vault / target)}
    return tool, {}


def lines_for(entries: list[str], vault: Path | None = None) -> list[str]:
    """Transcript lines for `"<HH:MM|now> tool=<Tool> target=<target>"` entries.

    `HH:MM` is today at that local time; `now` is the current moment, for
    entries that must count as new activity after an earlier pass.
    """
    out: list[str] = []
    now = _dt.datetime.now().astimezone()
    for i, entry in enumerate(entries):
        stamp, rest = entry.split(" ", 1)
        tool, _, target = rest.partition(" target=")
        tool = tool.removeprefix("tool=")
        if stamp == "now":
            when = _dt.datetime.now().astimezone()
        else:
            h, m = stamp.split(":")
            when = now.replace(hour=int(h), minute=int(m), second=0, microsecond=i * 1000)
        name, tool_input = _input_for(tool, target, vault)
        out.extend(tool_call(name, tool_input, when))
    return out


def write_transcript(path: Path, entries: list[str], vault: Path | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(lines_for(entries, vault)) + "\n")
    return path
