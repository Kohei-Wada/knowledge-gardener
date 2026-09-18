"""Subprocess-based tests for recap/capture.py.

Runs the script as a child process with a JSON payload on stdin and a temp
$XDG_STATE_HOME, asserting the side-effect log file matches expectations.
This mirrors how Claude Code invokes the hook.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_capture(payload: dict | None, *, tmp_path: Path, raw: str | None = None) -> tuple[str, str, Path]:
    """Run capture.py with payload on stdin. Returns (stdout, stderr, log_dir)."""
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(tmp_path)
    env["PYTHONPATH"] = str(REPO_ROOT)
    body = raw if raw is not None else (json.dumps(payload) if payload is not None else "")
    proc = subprocess.run(
        [sys.executable, "-m", "recap.capture"],
        input=body,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    log_dir = tmp_path / "knowledge-gardener" / "sessions"
    return proc.stdout, proc.stderr, log_dir


def read_today_log(log_dir: Path, sid8: str = "testsess") -> str:
    today = _dt.date.today().isoformat()
    path = log_dir / f"{today}-{sid8}.log"
    return path.read_text() if path.exists() else ""


def assert_continue(stdout: str) -> None:
    """Every successful hook invocation must emit a continue-true payload to stdout."""
    assert stdout.strip(), "hook emitted no stdout"
    obj = json.loads(stdout.strip().splitlines()[-1])
    assert obj.get("continue") is True
    assert obj.get("suppressOutput") is True


# --- baseline shape ----------------------------------------------------------

def test_edit_writes_short_path(tmp_path):
    payload = {
        "session_id": "testsess-uuid",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/home/u/repo/skills/garden-prune/SKILL.md"},
        "tool_response": {"success": True},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "tool=Edit" in log
    assert "target=garden-prune/SKILL.md" in log
    assert "[status=ok]" in log


def test_bash_command_truncated(tmp_path):
    long_cmd = "git log --oneline " + "x" * 200
    payload = {
        "session_id": "testsess",
        "tool_name": "Bash",
        "tool_input": {"command": long_cmd},
        "tool_response": {},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "tool=Bash" in log
    assert "…" in log  # truncated


def test_agent_includes_subagent_and_desc(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Agent",
        "tool_input": {"subagent_type": "Explore", "description": "find references to KG_VAULT"},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "target=Explore:find references to KG_VAULT" in log


def test_mcp_tool_with_arg(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "mcp__claude_ai_Slack__slack_send_message",
        "tool_input": {"channel": "C123", "text": "hello"},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "claude_ai_Slack:slack_send_message" in log
    assert "channel=C123" in log


def test_unknown_tool_target_question(tmp_path):
    payload = {"session_id": "testsess", "tool_name": "WhateverTool", "tool_input": {}}
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "tool=WhateverTool" in log
    assert "target=?" in log


# --- filter ------------------------------------------------------------------

def test_always_skip_drops(tmp_path):
    for tool in ("Read", "TodoWrite", "TaskUpdate", "Skill", "AskUserQuestion", "ScheduleWakeup"):
        payload = {"session_id": "testsess", "tool_name": tool, "tool_input": {}}
        stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
        assert_continue(stdout)
        assert read_today_log(log_dir) == "", f"{tool} should be skipped but produced output"


def test_bash_trivial_skipped(tmp_path):
    for cmd in ("ls -la", "pwd", "echo hi", "rg foo", "wc -l file"):
        payload = {"session_id": "testsess", "tool_name": "Bash", "tool_input": {"command": cmd}}
        stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
        assert_continue(stdout)
    # nothing should be logged
    assert read_today_log(log_dir) == ""


def test_bash_cd_prefix_still_evaluates_head(tmp_path):
    # `cd /tmp && ls` → head is `ls` → trivial → skip
    payload = {"session_id": "testsess", "tool_name": "Bash", "tool_input": {"command": "cd /tmp && ls"}}
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    assert read_today_log(log_dir) == ""


def test_bash_cd_prefix_then_real_command_captured(tmp_path):
    payload = {"session_id": "testsess", "tool_name": "Bash", "tool_input": {"command": "cd /tmp && git push"}}
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    assert "tool=Bash" in read_today_log(log_dir)


# --- status ------------------------------------------------------------------

def test_status_err_explicit(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/y.md"},
        "tool_response": {"success": False, "error": "no such file"},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    assert "[status=err]" in read_today_log(log_dir)


def test_status_omitted_when_unknown(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Edit",
        "tool_input": {"file_path": "/x/y.md"},
        "tool_response": {},
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "[status=" not in log


# --- privacy -----------------------------------------------------------------

def test_private_tag_redacted(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Bash",
        "tool_input": {"command": "echo <private>shh</private> hello"},
    }
    # NB: `echo` is trivial → skipped. Use a non-trivial leading verb.
    payload["tool_input"]["command"] = "curl -d <private>shh</private> https://example"
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "[REDACTED]" in log
    assert "shh" not in log


def test_secret_pattern_redacted(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Bash",
        "tool_input": {"command": "curl -H 'api_key=ABCDEF1234567890ABCD' https://x"},  # gitleaks:allow
    }
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "[REDACTED]" in log
    assert "ABCDEF1234567890" not in log


# --- defensive ---------------------------------------------------------------

def test_malformed_stdin_does_not_crash(tmp_path):
    stdout, stderr, log_dir = run_capture(None, tmp_path=tmp_path, raw="not json {")
    assert_continue(stdout)
    assert stderr == ""
    assert not (log_dir.exists() and any(log_dir.iterdir()))


def test_empty_stdin_does_not_crash(tmp_path):
    stdout, stderr, log_dir = run_capture(None, tmp_path=tmp_path, raw="")
    assert_continue(stdout)
    assert stderr == ""


def test_missing_session_id_uses_unknown(tmp_path):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": "/a/b.md"}}
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    today = _dt.date.today().isoformat()
    assert (log_dir / f"{today}-unknown.log").exists()


def test_tool_input_not_dict_is_tolerated(tmp_path):
    payload = {"session_id": "testsess", "tool_name": "Edit", "tool_input": "garbage"}
    stdout, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "tool=Edit" in log
    assert "target=?" in log


def test_log_dir_creation_failure_does_not_crash(tmp_path):
    # XDG_STATE_HOME pointing at an existing file → mkdir will fail
    blocker = tmp_path / "block"
    blocker.write_text("x")
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(blocker)  # not a directory
    env["PYTHONPATH"] = str(REPO_ROOT)
    payload = {"session_id": "testsess", "tool_name": "Edit", "tool_input": {"file_path": "/a/b.md"}}
    proc = subprocess.run(
        [sys.executable, "-m", "recap.capture"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert proc.returncode == 0
    obj = json.loads(proc.stdout.strip().splitlines()[-1])
    assert obj["continue"] is True


def test_writes_0600_mode(tmp_path):
    payload = {"session_id": "testsess", "tool_name": "Edit", "tool_input": {"file_path": "/a/b.md"}}
    _, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    today = _dt.date.today().isoformat()
    f = log_dir / f"{today}-testsess.log"
    assert f.exists()
    assert (f.stat().st_mode & 0o777) == 0o600


# --- output shape ------------------------------------------------------------

def test_log_line_format_minimal(tmp_path):
    payload = {"session_id": "testsess", "tool_name": "Write", "tool_input": {"file_path": "/x/y/foo.txt"}}
    _, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    log = read_today_log(log_dir).strip()
    # HH:MM tool=Write target=y/foo.txt
    parts = log.split(" ", 3)
    assert len(parts) >= 3
    assert ":" in parts[0]
    assert parts[1] == "tool=Write"
    assert parts[2].startswith("target=")


def test_newline_in_target_replaced(tmp_path):
    payload = {
        "session_id": "testsess",
        "tool_name": "Bash",
        "tool_input": {"command": "git commit -m 'line1\nline2'"},
    }
    _, _, log_dir = run_capture(payload, tmp_path=tmp_path)
    log = read_today_log(log_dir)
    # One log entry, no embedded newline
    assert log.count("\n") == 1
    assert "␤" in log


def test_bash_cd_prefix_stripped_so_real_command_survives(tmp_path):
    # A long `cd <repo path> &&` prefix must not eat the 80-char truncation
    # budget — the stored target is the meaningful command, not the path.
    long_path = "/home/kohei/ghq/github.com/Kohei-Wada/knowledge-gardener"
    cmd = f"cd {long_path} && gh issue list --state open --limit 50"
    _, _, log_dir = run_capture(
        {"session_id": "testsess", "tool_name": "Bash", "tool_input": {"command": cmd}},
        tmp_path=tmp_path,
    )
    line = read_today_log(log_dir)
    assert "target=gh issue list --state open" in line
    assert long_path not in line


def test_bash_without_cd_prefix_unchanged(tmp_path):
    _, _, log_dir = run_capture(
        {"session_id": "testsess", "tool_name": "Bash", "tool_input": {"command": "git commit -m x"}},
        tmp_path=tmp_path,
    )
    assert "target=git commit -m x" in read_today_log(log_dir)


def test_bash_cd_prefix_does_not_eat_command_starting_with_cd(tmp_path):
    # The `cd ` guard requires a trailing space, so a command whose name merely
    # starts with "cd" (e.g. `cdburn`) is NOT mistaken for a cd wrapper.
    _, _, log_dir = run_capture(
        {"session_id": "testsess", "tool_name": "Bash",
         "tool_input": {"command": "cd /tmp && cdburn --foo"}},
        tmp_path=tmp_path,
    )
    assert "target=cdburn --foo" in read_today_log(log_dir)


# --- vault reads -------------------------------------------------------------

def _vault_read_payload(note: Path) -> dict:
    return {"session_id": "testsess", "tool_name": "Read", "tool_input": {"file_path": str(note)}}


def test_read_inside_vault_is_logged_as_readnote(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "03_PermanentNotes" / "foo.md"
    note.parent.mkdir(parents=True)
    note.write_text("x")
    monkeypatch.setenv("KG_VAULT", str(vault))

    stdout, _, log_dir = run_capture(_vault_read_payload(note), tmp_path=tmp_path)
    assert_continue(stdout)
    log = read_today_log(log_dir)
    assert "tool=ReadNote" in log
    # full vault-relative path, not the shortened parent/name form
    assert "target=03_PermanentNotes/foo.md" in log


def test_read_outside_vault_is_still_skipped(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    outside = tmp_path / "elsewhere" / "notes.md"
    outside.parent.mkdir(parents=True)
    outside.write_text("x")
    monkeypatch.setenv("KG_VAULT", str(vault))

    stdout, _, log_dir = run_capture(_vault_read_payload(outside), tmp_path=tmp_path)
    assert_continue(stdout)
    assert read_today_log(log_dir) == ""


def test_read_without_kg_vault_is_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("KG_VAULT", raising=False)
    note = tmp_path / "foo.md"
    note.write_text("x")
    stdout, _, log_dir = run_capture(_vault_read_payload(note), tmp_path=tmp_path)
    assert_continue(stdout)
    assert read_today_log(log_dir) == ""
