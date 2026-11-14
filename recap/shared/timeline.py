"""The mechanical Timeline: tool calls grouped by minute, noise collapsed."""
from __future__ import annotations

import re
from collections import Counter, OrderedDict

from .tool_calls import READ_NOTE_TOOL

FILE_TOOLS = frozenset({"Edit", "Write", "NotebookEdit"})
WEB_TOOLS = frozenset({"WebFetch", "WebSearch"})
# ReadNote surfaces as `referenced_notes`, never as Timeline activity — consulting
# a note is context for the day, not a step in it.
NOISE_TOOLS = frozenset({"StructuredOutput", READ_NOTE_TOOL})
_COMMIT_PUSH_RE = re.compile(r"\bgit\s+(commit|push)\b")


def durable_change(entries: list[dict]) -> bool:
    for e in entries:
        tool = e["tool"]
        if tool in FILE_TOOLS or tool == "Agent":  # any Agent dispatch may have caused a change; can't inspect inside
            return True
        if tool == "Bash" and _COMMIT_PUSH_RE.search(e["target"] or ""):
            return True
    return False


def _summarize_minute(entries: list[dict]) -> str:
    file_counts: OrderedDict[tuple[str, str], int] = OrderedDict()
    file_err: dict[tuple[str, str], bool] = {}
    rest: list[str] = []           # Bash / Agent — itemized, in encounter order
    web = 0                        # WebFetch + WebSearch — collapsed
    mcp: Counter[str] = Counter()
    misc: Counter[str] = Counter()  # read-only nav + unknown tools — collapsed by name
    for e in entries:
        tool, target = e["tool"], (e["target"] or "?")
        err = " [err]" if e["status"] == "err" else ""
        # err is propagated only for itemized tools (Bash/Agent/file edits);
        # collapsed-count tools (Web/nav/misc) omit it.
        if tool in NOISE_TOOLS:
            continue
        if tool in FILE_TOOLS:
            key = (tool, target)
            file_counts[key] = file_counts.get(key, 0) + 1
            if e["status"] == "err":
                file_err[key] = True
        elif tool == "Bash":
            rest.append(f"Bash: {target}{err}")
        elif tool == "Agent":
            sub = target.split(":", 1)[0] if ":" in target else target
            rest.append(f"Agent→{sub}{err}")
        elif tool in WEB_TOOLS:
            web += 1
        elif tool.startswith("mcp__"):
            parts = tool.split("__", 2)
            mcp[parts[1] if len(parts) >= 2 else "mcp"] += 1
        else:
            misc[tool] += 1
    chunks = [
        f"{tool} {path}" + (f" ×{n}" if n > 1 else "") + (" [err]" if file_err.get((tool, path)) else "")
        for (tool, path), n in file_counts.items()
    ]
    chunks.extend(rest)
    if web:
        chunks.append(f"Web×{web}")
    chunks.extend(
        (f"{tool}×{n}" if n > 1 else tool) for tool, n in sorted(misc.items())
    )
    chunks.extend(f"MCP {server}×{n}" for server, n in sorted(mcp.items()))
    return ", ".join(chunks)


def render_timeline(entries: list[dict]) -> list[str]:
    by_min: OrderedDict[str, list[dict]] = OrderedDict()
    for e in entries:
        by_min.setdefault(e["hhmm"], []).append(e)
    out: list[str] = []
    for hhmm, es in by_min.items():
        summary = _summarize_minute(es)
        if summary:
            out.append(f"- {hhmm}  {summary}")
    return out


def duration_minutes(start: str | None, end: str | None) -> int:
    if not start or not end:
        return 0

    def m(hhmm: str) -> int:
        h, mm = hhmm.split(":")
        return int(h) * 60 + int(mm)

    delta = m(end) - m(start)
    if delta < 0:
        delta += 24 * 60
    return delta
