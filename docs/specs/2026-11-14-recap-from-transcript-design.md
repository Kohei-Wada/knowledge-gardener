# Recap From the Transcript — Design

- **Date**: 2026-11-14
- **Status**: Implemented
- **Supersedes**: [2026-05-18-session-capture-design.md](2026-05-18-session-capture-design.md) (the PostToolUse capture log), the CLI of [2026-05-20-recap-aggregator-design.md](2026-05-20-recap-aggregator-design.md)
- **Prior art**: [2026-11-14-recap-throttle-design.md](2026-11-14-recap-throttle-design.md)

## Problem

A `PostToolUse` hook ran on every tool call of every session to append one line to a per-day session log. The recap then read that log. But the Stop and SessionEnd hooks receive `transcript_path`, and the transcript already holds every tool call with its input, result and timestamp. The log repeated it, at the cost of a Python process per tool call, a second state format, and a parser for it.

## Design

The transcript is the only record of a session's activity.

### Reading tool calls — `recap/shared/tool_calls.py`

`read_tool_calls(transcript_path, date, vault)` returns the entries the capture log used to hold, `{"ts", "hhmm", "tool", "target", "status"}`:

- A call is a `tool_use` block in an assistant line paired by id with a `tool_result` block in a later user line. It is stamped with the **result's** timestamp, converted to local time, because the capture hook ran when the call finished.
- Results with `is_error` are left out, and so are calls with no result yet. `PostToolUse` never fired for failed or denied calls, so the log never held them either.
- Subagent calls are not in the parent transcript. They are read from `<transcript minus .jsonl>/subagents/*.jsonl` and merged by timestamp. The capture hook recorded them under the parent session.
- Only results whose local date is `date` count, which is what the per-day log file gave.
- A `tool_use` id counts once, however often its result line appears.
- The filters moved here unchanged: skipped tools, trivial Bash, `cd <dir> &&` stripping, target composition and truncation, `<private>` and secret redaction, and `Read` of a file under the vault becoming `ReadNote`.

`recap/shared/timeline.py` holds what was the pure part of `recap/aggregate`: `render_timeline`, `durable_change`, `duration_minutes`.

### Pass state — `recap/shared/pass_state.py`

The `HH:MM` cursor is replaced by a timestamp, and the two per-session files by one. `.last-recap-<sid8>`:

- **mtime** — when the last pass started (throttle; set even when the pass fails).
- **content** — when the last pass that wrote read the transcript (epoch seconds). Tool calls and turns stamped after it are not in any block yet.

A pass runs only if the transcript has an entry after that time. The new slice of the mechanical Timeline and of the conversation is cut at the same timestamp, so the one-minute overlap the cursor needed is gone, and so is the prompt sentence about it.

### Manual recap

`recap.manual_recap` reads the transcript too. `--sid` is now optional: by default the CLI recaps the session it runs in, taking the id from `$CLAUDE_CODE_SESSION_ID` and finding `<CLAUDE_CONFIG_DIR or ~/.claude>/projects/*/<session id>*.jsonl`. `--transcript` overrides the lookup. The `garden-recap` skill drops its "identify the session" step and falls back to recollection when the CLI exits 3.

`CLAUDE_CODE_SESSION_ID` is present in the Bash tool's environment on Claude Code 2.1.318; this was measured, not found in the docs. If it goes away the CLI exits 2 with a message and the skill falls back.

### Removed

- The `PostToolUse` hook and `recap/capture/`.
- `recap/aggregate/`: the log parser and the `python -m recap.aggregate` CLI. Its only caller was the skill step above. The summary fields only its human-readable output used (`file_counts`, `bash_highlights`, `agent_subagents`, `webio_count`, `mcp_servers`, `errors`, `other_count`) went with it.
- `recap/shared/cursor.py`, `session_log_path`, `cursor_path`, `RecapContext.since`.

Existing `sessions/<date>-<sid8>.log` and `<sid8>.cursor` files are no longer read or written. Nothing deletes them.

## Gate

For every (day, session) on the development machine that has both a capture log and a transcript — 89 of them, 2026-10-07 to 2026-11-14, 1 to 940 log lines, 11 with subagent transcripts — the mechanical Timeline rendered from the log was compared with the one rendered from the transcript:

| Result | Sessions |
| --- | --- |
| Identical Timeline | 87 |
| Same calls, one call one minute later | 2 |
| Any call missing or extra | 0 |

Referenced notes and the durable-change signal were equal in all 89.

The two differences are one Bash call each. The capture hook logged `00:08` and `09:50`; the transcript stamps the results `00:09:00.000` and `09:51:00.000`, 5.5 s after their `tool_use` lines at `:54`. The call finished within seconds of a minute boundary and the two clocks fell on different sides of it. Why those two result stamps are whole minutes is not known.

## Not changed

- Marker and lock files are never cleaned up; one small pair per session accumulates under `sessions/`, as the marker and cursor did before.
- A `Stop` that fires while a background subagent is still running recaps what is in the transcript so far; the rest is picked up by a later pass.
