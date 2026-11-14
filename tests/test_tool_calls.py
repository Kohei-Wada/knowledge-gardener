"""Tests for recap/shared/tool_calls.py."""
from __future__ import annotations

import datetime as _dt
import json

from recap.shared.tool_calls import read_tool_calls
from tests.transcripts import tool_call

TODAY = _dt.date.today()
NOON = _dt.datetime.combine(TODAY, _dt.time(12, 0)).astimezone()


def _read(tmp_path, *calls, vault=None, name="t.jsonl"):
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(line for call in calls for line in call) + "\n", encoding="utf-8")
    return read_tool_calls(path, TODAY, vault)


def _one(tmp_path, tool, tool_input, **kw):
    entries = _read(tmp_path, tool_call(tool, tool_input, NOON, **kw))
    assert len(entries) == 1
    return entries[0]


# --- baseline shape ----------------------------------------------------------

def test_edit_uses_short_path_and_result_time(tmp_path):
    e = _one(tmp_path, "Edit", {"file_path": "/home/u/repo/skills/garden-prune/SKILL.md"},
             result={"success": True})
    assert e["tool"] == "Edit"
    assert e["target"] == "garden-prune/SKILL.md"
    assert e["status"] == "ok"
    assert e["hhmm"] == "12:00"
    assert e["ts"] == NOON.timestamp()


def test_bash_command_truncated(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "git log --oneline " + "x" * 200})
    assert e["target"].endswith("…")
    assert len(e["target"]) == 80


def test_agent_includes_subagent_and_desc(tmp_path):
    e = _one(tmp_path, "Agent", {"subagent_type": "Explore", "description": "find references to KG_VAULT"})
    assert e["target"] == "Explore:find references to KG_VAULT"


def test_mcp_tool_with_arg(tmp_path):
    e = _one(tmp_path, "mcp__claude_ai_Slack__slack_send_message", {"channel": "C123", "text": "hello"})
    assert e["target"] == "claude_ai_Slack:slack_send_message channel=C123"


def test_unknown_tool_target_question(tmp_path):
    e = _one(tmp_path, "WhateverTool", {})
    assert (e["tool"], e["target"]) == ("WhateverTool", "?")


def test_newline_in_target_replaced(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "git status\ngit diff"})
    assert e["target"] == "git status␤git diff"


# --- filter ------------------------------------------------------------------

def test_always_skip_drops(tmp_path):
    calls = [tool_call(t, {}, NOON) for t in
             ("Read", "TodoWrite", "TaskUpdate", "Skill", "AskUserQuestion", "ScheduleWakeup")]
    assert _read(tmp_path, *calls) == []


def test_bash_trivial_skipped(tmp_path):
    calls = [tool_call("Bash", {"command": c}, NOON) for c in ("ls -la", "cat foo.txt", "grep -r x .")]
    assert _read(tmp_path, *calls) == []


def test_bash_cd_prefix_still_evaluates_head(tmp_path):
    assert _read(tmp_path, tool_call("Bash", {"command": "cd /repo && ls -la"}, NOON)) == []


def test_bash_cd_prefix_stripped_so_real_command_survives(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "cd /very/long/repo/path && git commit -m x"})
    assert e["target"] == "git commit -m x"


def test_bash_bare_cd_is_kept(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "cd /repo"})
    assert e["target"] == "cd /repo"


def test_failed_and_denied_calls_are_left_out(tmp_path):
    entries = _read(
        tmp_path,
        tool_call("Bash", {"command": "pytest"}, NOON, is_error=True),
        tool_call("Bash", {"command": "make"}, NOON),
    )
    assert [e["target"] for e in entries] == ["make"]


def test_call_without_a_result_yet_is_left_out(tmp_path):
    done = tool_call("Bash", {"command": "make"}, NOON)
    pending = tool_call("Bash", {"command": "sleep 100"}, NOON)[:1]
    assert [e["target"] for e in _read(tmp_path, done, pending)] == ["make"]


def test_other_days_are_left_out(tmp_path):
    yesterday = NOON - _dt.timedelta(days=1)
    entries = _read(tmp_path, tool_call("Bash", {"command": "old"}, yesterday),
                    tool_call("Bash", {"command": "new"}, NOON))
    assert [e["target"] for e in entries] == ["new"]


def test_duplicated_result_lines_count_once(tmp_path):
    call = tool_call("Bash", {"command": "make"}, NOON)
    assert len(_read(tmp_path, call, call)) == 1


# --- status ------------------------------------------------------------------

def test_status_err_explicit(tmp_path):
    assert _one(tmp_path, "Bash", {"command": "make"}, result={"success": False})["status"] == "err"


def test_status_omitted_when_unknown(tmp_path):
    assert _one(tmp_path, "Bash", {"command": "make"}, result={"stdout": "x"})["status"] is None
    assert _one(tmp_path / "b", "Bash", {"command": "make"}, result="plain text")["status"] is None


# --- privacy -----------------------------------------------------------------

def test_private_tag_redacted(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "deploy <private>hunter2</private> now"})
    assert "hunter2" not in e["target"]
    assert "[REDACTED]" in e["target"]


def test_secret_pattern_redacted(tmp_path):
    e = _one(tmp_path, "Bash", {"command": "curl -H api_key=abcdefghijklmnopqrstuvwxyz012345 x"})
    assert "abcdefghijklmnop" not in e["target"]
    assert "api_key=[REDACTED]" in e["target"]


# --- robustness --------------------------------------------------------------

def test_missing_or_garbled_transcript(tmp_path):
    assert read_tool_calls(None, TODAY) == []
    assert read_tool_calls(tmp_path / "missing.jsonl", TODAY) == []
    path = tmp_path / "t.jsonl"
    good = tool_call("Bash", {"command": "make"}, NOON)
    path.write_text("\n".join(['not json "tool_use"', '["tool_use"]', *good,
                               json.dumps({"type": "user", "message": {"content": "tool_result"}})]) + "\n")
    assert [e["target"] for e in read_tool_calls(path, TODAY)] == ["make"]


def test_tool_input_not_dict_is_tolerated(tmp_path):
    e = _one(tmp_path, "Bash", "not a dict")
    assert e["target"] == "?"


# --- vault reads -------------------------------------------------------------

def test_read_inside_vault_becomes_readnote(tmp_path):
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    entries = _read(tmp_path, tool_call("Read", {"file_path": str(vault / "notes" / "foo.md")}, NOON),
                    vault=vault)
    assert [(e["tool"], e["target"]) for e in entries] == [("ReadNote", "notes/foo.md")]


def test_read_outside_vault_is_still_skipped(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    assert _read(tmp_path, tool_call("Read", {"file_path": "/etc/hosts"}, NOON), vault=vault) == []


def test_read_without_a_vault_is_skipped(tmp_path):
    assert _read(tmp_path, tool_call("Read", {"file_path": "/x/notes/foo.md"}, NOON)) == []


# --- subagents ---------------------------------------------------------------

def test_subagent_calls_are_merged_in_time_order(tmp_path):
    main = tmp_path / "sess.jsonl"
    sub = tmp_path / "sess" / "subagents" / "agent-a1.jsonl"
    sub.parent.mkdir(parents=True)
    t = lambda minutes: NOON + _dt.timedelta(minutes=minutes)  # noqa: E731
    main.write_text("\n".join([*tool_call("Bash", {"command": "first"}, t(0)),
                               *tool_call("Agent", {"subagent_type": "Explore", "description": "look"}, t(3))]) + "\n")
    sub.write_text("\n".join(tool_call("Bash", {"command": "inside the subagent"}, t(1))) + "\n")
    (sub.parent / "agent-a1.meta.json").write_text("{}")
    entries = read_tool_calls(main, TODAY)
    assert [e["target"] for e in entries] == ["first", "inside the subagent", "Explore:look"]
