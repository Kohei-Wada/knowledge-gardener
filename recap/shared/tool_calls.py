"""Material tool calls of one session, read from its Claude Code transcript.

The transcript already records every tool call, so nothing is captured while
the session runs. A subagent's calls are not in the parent transcript; they
sit in `<transcript minus .jsonl>/subagents/*.jsonl` and are read too.

An entry is one completed call: `{"ts", "hhmm", "tool", "target", "status"}`,
stamped with the local time its result arrived. Calls that failed or were
denied are left out, as are navigation and plumbing tools and trivial shell
commands. Secrets are redacted before a target leaves this module.
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re

ALWAYS_SKIP = frozenset({
    "Read",
    "TodoWrite",
    "TaskCreate", "TaskUpdate", "TaskGet", "TaskList", "TaskOutput", "TaskStop",
    "Skill",
    "AskUserQuestion",
    "ToolSearch",
    "ScheduleWakeup",
    "ShareOnboardingGuide",
})

# `Read` is skipped as navigation noise, with one exception: reading a note
# inside the vault is consulting knowledge, not navigating. Those are re-emitted
# under this synthetic tool name so the Timeline can tell them apart.
READ_NOTE_TOOL = "ReadNote"

BASH_TRIVIAL = frozenset({
    "ls", "pwd", "cat", "head", "tail", "find", "echo",
    "which", "type", "grep", "rg", "wc", "sort", "uniq",
    "date", "printf", "true", "false",
})

TARGET_MAX = 80
ELLIPSIS = "…"
NEWLINE_SUB = "␤"

_PRIVATE_RE = re.compile(r"<private>.*?</private>", re.DOTALL | re.IGNORECASE)
_SECRET_RE = re.compile(
    r"(api[_-]?key|secret|token|password|passwd|auth)\s*[:=]\s*['\"]?[A-Za-z0-9_\-./+=]{16,}",
    re.IGNORECASE,
)


def _truncate(s: str, limit: int = TARGET_MAX) -> str:
    s = s.replace("\n", NEWLINE_SUB).replace("\r", NEWLINE_SUB)
    if len(s) > limit:
        s = s[: limit - 1] + ELLIPSIS
    return s


def _privacy_strip(s: str) -> str:
    s = _PRIVATE_RE.sub("[REDACTED]", s)
    s = _SECRET_RE.sub(r"\1=[REDACTED]", s)
    return s


def _short_path(path: str) -> str:
    p = pathlib.PurePosixPath(path)
    if p.parent.name:
        return f"{p.parent.name}/{p.name}"
    return p.name


def _vault_relative(file_path: str, vault: pathlib.Path | None) -> str | None:
    """`file_path` as a vault-root-relative path, or None if it is outside the vault.

    Resolves symlinks on both sides so a vault reached through a link still matches.
    """
    if vault is None or not file_path:
        return None
    try:
        root = vault.expanduser().resolve()
        target = pathlib.Path(file_path).expanduser().resolve()
        rel = target.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return None
    return str(rel) if rel.parts else None


def _strip_cd_prefix(command: str) -> str:
    """Drop leading `cd <dir> &&` / `cd <dir> ;` wrappers so the meaningful
    command — not the long repo path — is what gets shown. A bare
    `cd <dir>` with nothing after is kept as-is."""
    s = command.strip()
    while s.startswith("cd "):
        rest = s[3:].lstrip()
        parts = rest.split(None, 1)
        if len(parts) < 2:
            return s
        tail = parts[1].lstrip()
        if tail.startswith("&&"):
            s = tail[2:].lstrip()
            continue
        if tail.startswith(";"):
            s = tail[1:].lstrip()
            continue
        break
    return s


def _bash_head(command: str) -> str:
    """Pick the verb that decides triviality, skipping leading `cd <dir> &&` wrappers."""
    s = _strip_cd_prefix(command)
    return s.split(None, 1)[0] if s else ""


def _compose_target(tool_name: str, tool_input: dict) -> str:
    if tool_name in {"Edit", "Write", "NotebookEdit"}:
        fp = tool_input.get("file_path") or "?"
        return _short_path(fp) if fp != "?" else "?"
    if tool_name == "Bash":
        cmd = _strip_cd_prefix((tool_input.get("command") or "").strip())
        return _truncate(cmd) if cmd else "?"
    if tool_name == "Agent":
        subagent = tool_input.get("subagent_type") or "general-purpose"
        desc = (tool_input.get("description") or "").strip()
        return _truncate(f"{subagent}:{desc}") if desc else subagent
    if tool_name in {"WebFetch", "WebSearch"}:
        v = tool_input.get("url") or tool_input.get("query") or "?"
        return _truncate(str(v))
    if tool_name.startswith("mcp__"):
        parts = tool_name.split("__", 2)
        # mcp__<server>__<name>
        if len(parts) >= 3:
            label = f"{parts[1]}:{parts[2]}"
        else:
            label = tool_name
        # opportunistic first identifying arg
        for k in ("name", "id", "key", "path", "query", "channel", "title"):
            if k in tool_input:
                label = f"{label} {k}={tool_input[k]}"
                break
        return _truncate(label)
    return "?"


def _status(tool_result) -> str | None:
    if not isinstance(tool_result, dict):
        return None
    if tool_result.get("success") is False:
        return "err"
    if tool_result.get("is_error") is True:
        return "err"
    if tool_result.get("error"):
        return "err"
    if tool_result.get("success") is True:
        return "ok"
    return None


def _entry(tool_name: str, tool_input: dict, tool_result, when: _dt.datetime,
           vault: pathlib.Path | None) -> dict | None:
    note_rel = None
    if tool_name == "Read":
        note_rel = _vault_relative(tool_input.get("file_path") or "", vault)
    if tool_name in ALWAYS_SKIP and note_rel is None:
        return None
    if tool_name == "Bash" and _bash_head(tool_input.get("command") or "") in BASH_TRIVIAL:
        return None
    if note_rel is not None:
        tool_name, target = READ_NOTE_TOOL, note_rel
    else:
        try:
            target = _compose_target(tool_name, tool_input)
        except Exception:
            target = "?"
    return {
        "ts": when.timestamp(),
        "hhmm": when.strftime("%H:%M"),
        "tool": tool_name,
        "target": _privacy_strip(target),
        "status": _status(tool_result),
    }


def _local_time(ts: str) -> _dt.datetime | None:
    try:
        when = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=_dt.timezone.utc)
    return when.astimezone()


def _calls_in(path: pathlib.Path, date: _dt.date, vault: pathlib.Path | None,
              seen: set[str]) -> list[dict]:
    out: list[dict] = []
    uses: dict[str, tuple[str, dict]] = {}
    try:
        f = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return out
    with f:
        for line in f:
            if '"tool_' not in line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(d, dict):
                continue
            content = (d.get("message") or {}).get("content")
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "tool_use":
                    tool_input = block.get("input")
                    uses[block.get("id") or ""] = (
                        block.get("name") or "?",
                        tool_input if isinstance(tool_input, dict) else {},
                    )
                elif block.get("type") == "tool_result":
                    use_id = block.get("tool_use_id") or ""
                    if use_id not in uses or use_id in seen or block.get("is_error"):
                        continue
                    when = _local_time(d.get("timestamp") or "")
                    if when is None or when.date() != date:
                        continue
                    seen.add(use_id)
                    name, tool_input = uses[use_id]
                    entry = _entry(name, tool_input, d.get("toolUseResult"), when, vault)
                    if entry is not None:
                        out.append(entry)
    return out


def read_tool_calls(transcript_path: str | pathlib.Path | None, date: _dt.date,
                    vault: pathlib.Path | None = None) -> list[dict]:
    """The session's material tool calls on `date`, subagents included, oldest first."""
    if not transcript_path:
        return []
    main = pathlib.Path(transcript_path)
    files = [main, *sorted((main.with_suffix("") / "subagents").glob("*.jsonl"))]
    seen: set[str] = set()
    entries: list[dict] = []
    for path in files:
        entries.extend(_calls_in(path, date, vault, seen))
    entries.sort(key=lambda e: e["ts"])
    return entries
