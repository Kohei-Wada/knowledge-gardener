#!/usr/bin/env python3
"""PostToolUse hook — append a one-line evidence entry per material tool call.

See docs/specs/2026-05-18-session-capture-design.md for the design rationale.
The hook is best-effort: it must never block Claude Code, and any failure
silently degrades to "skip this entry" while still emitting the continue payload.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys

from ..shared.paths import session_log_path

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
# under this synthetic tool name so the aggregator can tell them apart.
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


def _vault_relative(file_path: str) -> str | None:
    """`file_path` as a vault-root-relative path, or None if it is outside the vault.

    Resolves symlinks on both sides so a vault reached through a link still matches.
    """
    vault = os.environ.get("KG_VAULT")
    if not vault or not file_path:
        return None
    try:
        root = pathlib.Path(vault).expanduser().resolve()
        target = pathlib.Path(file_path).expanduser().resolve()
        rel = target.relative_to(root)
    except (ValueError, OSError, RuntimeError):
        return None
    return str(rel) if rel.parts else None


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


def _status(tool_response: dict) -> str | None:
    if not isinstance(tool_response, dict):
        return None
    if tool_response.get("success") is False:
        return "err"
    if tool_response.get("is_error") is True:
        return "err"
    if tool_response.get("error"):
        return "err"
    if tool_response.get("success") is True:
        return "ok"
    return None


def _strip_cd_prefix(command: str) -> str:
    """Drop leading `cd <dir> &&` / `cd <dir> ;` wrappers so the meaningful
    command — not the long repo path — is what gets stored and shown. A bare
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


def _log_path(session_id: str) -> pathlib.Path:
    return session_log_path(session_id or "")


def _write_line(path: pathlib.Path, line: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return
    try:
        # 0600 on creation
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    except OSError:
        return
    try:
        os.write(fd, line.encode("utf-8", errors="replace"))
    except OSError:
        pass
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def _emit_continue() -> None:
    sys.stdout.write('{"continue": true, "suppressOutput": true}\n')
    sys.stdout.flush()


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        _emit_continue()
        return

    payload: dict
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        _emit_continue()
        return

    if not isinstance(payload, dict):
        _emit_continue()
        return

    tool_name = payload.get("tool_name") or "?"

    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}

    note_rel = None
    if tool_name == "Read":
        note_rel = _vault_relative(tool_input.get("file_path") or "")

    if tool_name in ALWAYS_SKIP and note_rel is None:
        _emit_continue()
        return

    if tool_name == "Bash":
        head = _bash_head(tool_input.get("command") or "")
        if head in BASH_TRIVIAL:
            _emit_continue()
            return

    if note_rel is not None:
        tool_name, target = READ_NOTE_TOOL, note_rel
    else:
        try:
            target = _compose_target(tool_name, tool_input)
        except Exception:
            target = "?"
    target = _privacy_strip(target)

    status = _status(payload.get("tool_response"))
    suffix = f" [status={status}]" if status else ""

    hhmm = _dt.datetime.now().strftime("%H:%M")
    line = f"{hhmm} tool={tool_name} target={target}{suffix}\n"

    try:
        _write_line(_log_path(payload.get("session_id") or ""), line)
    except OSError:
        pass

    _emit_continue()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        _emit_continue()
