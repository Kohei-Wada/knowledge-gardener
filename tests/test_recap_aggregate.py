"""Tests for recap/recap_aggregate.py."""
from __future__ import annotations

import datetime as _dt
import json as _json
import os
import subprocess
import sys
import time
from pathlib import Path

from recap.aggregate.__main__ import aggregate_session, render_timeline, _durable_change

REPO_ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, state_home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(state_home)
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "recap.aggregate", *args],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )


def write_log(state_home: Path, date: _dt.date, sid8: str, lines: list[str]) -> Path:
    sessions = state_home / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    path = sessions / f"{date.isoformat()}-{sid8}.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def today_str() -> str:
    return _dt.date.today().isoformat()


# --- empty / missing inputs --------------------------------------------------

def test_missing_log_dir_returns_zero_sessions(tmp_path):
    res = run([], state_home=tmp_path)
    assert res.returncode == 0
    assert f"# Sessions on {today_str()}" in res.stdout
    assert "0 session(s) found" in res.stdout


def test_empty_log_file_produces_session_block(tmp_path):
    write_log(tmp_path, _dt.date.today(), "emptysid", [])
    res = run([], state_home=tmp_path)
    assert "1 session(s) found" in res.stdout
    assert "sid8: emptysid" in res.stdout
    assert "0 captured tool calls" in res.stdout


# --- single session ---------------------------------------------------------

def test_single_session_files_dedup(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "deadbeef",
        [
            "09:00 tool=Edit target=skills/garden-prune/SKILL.md [status=ok]",
            "09:05 tool=Write target=skills/garden-prune/SKILL.md [status=ok]",
            "09:10 tool=Edit target=skills/garden-water/SKILL.md [status=ok]",
        ],
    )
    res = run([], state_home=tmp_path)
    out = res.stdout
    assert "skills/garden-prune/SKILL.md (2 edits)" in out
    assert "skills/garden-water/SKILL.md (1 edit)" in out


def test_bash_highlights_dedup_and_cap(tmp_path):
    today = _dt.date.today()
    lines = [f"09:{i:02d} tool=Bash target=cmd{i % 3}" for i in range(15)]
    write_log(tmp_path, today, "bashsid1", lines)
    res = run([], state_home=tmp_path)
    out = res.stdout
    # 3 distinct commands, all within cap
    for i in range(3):
        assert f"cmd{i}" in out


def test_bash_highlights_capped_at_10(tmp_path):
    today = _dt.date.today()
    lines = [f"09:{i:02d} tool=Bash target=cmd{i:02d}" for i in range(20)]
    write_log(tmp_path, today, "bashsid2", lines)
    res = run([], state_home=tmp_path)
    bash_section = res.stdout.split("### Bash highlights", 1)[1].split("###", 1)[0]
    # 10 bullet lines starting with `- `
    bullets = [l for l in bash_section.splitlines() if l.startswith("- ")]
    assert len(bullets) == 10


def test_agent_subagents_collected(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "agentsid",
        [
            "10:00 tool=Agent target=Explore:find references",
            "10:05 tool=Agent target=Plan:design X",
            "10:10 tool=Agent target=Explore:second explore",
        ],
    )
    res = run([], state_home=tmp_path)
    out = res.stdout
    assert "Agent: 3 dispatch(es) — Explore, Plan" in out


def test_webio_counted(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "webiosid",
        [
            "11:00 tool=WebFetch target=https://example.com",
            "11:01 tool=WebSearch target=knowledge gardener",
            "11:02 tool=WebFetch target=https://b.test",
        ],
    )
    res = run([], state_home=tmp_path)
    assert "WebFetch/WebSearch: 3" in res.stdout


def test_mcp_counted_per_server(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "mcpsid12",
        [
            "12:00 tool=mcp__slack__slack_send target=foo",
            "12:01 tool=mcp__slack__slack_search target=bar",
            "12:02 tool=mcp__notion__notion_fetch target=baz",
        ],
    )
    res = run([], state_home=tmp_path)
    # Sorted alphabetically: notion before slack
    assert "MCP: notion(1), slack(2)" in res.stdout


def test_errors_counted(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "errsid12",
        [
            "13:00 tool=Edit target=a.md [status=ok]",
            "13:01 tool=Edit target=b.md [status=err]",
            "13:02 tool=Edit target=c.md [status=err]",
            "13:03 tool=Bash target=git push [status=err]",
        ],
    )
    res = run([], state_home=tmp_path)
    assert "Errors: 3" in res.stdout


def test_duration_calculation(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "duration",
        [
            "09:00 tool=Edit target=a.md",
            "10:30 tool=Edit target=b.md",
        ],
    )
    res = run([], state_home=tmp_path)
    assert "Duration: 90m, 2 captured tool calls" in res.stdout


# --- multi-session ----------------------------------------------------------

def test_default_selects_latest(tmp_path):
    today = _dt.date.today()
    p1 = write_log(tmp_path, today, "oldold12", ["09:00 tool=Edit target=old.md"])
    time.sleep(0.05)
    p2 = write_log(tmp_path, today, "newnew12", ["10:00 tool=Edit target=new.md"])
    # ensure p2 has the later mtime
    os.utime(p2, (time.time(), time.time()))
    res = run([], state_home=tmp_path)
    assert "1 session(s) found" in res.stdout
    assert "newnew12" in res.stdout
    assert "oldold12" not in res.stdout


def test_all_includes_every_session(tmp_path):
    today = _dt.date.today()
    write_log(tmp_path, today, "sessionA", ["09:00 tool=Edit target=a.md"])
    write_log(tmp_path, today, "sessionB", ["10:00 tool=Edit target=b.md"])
    res = run(["--all"], state_home=tmp_path)
    assert "2 session(s) found" in res.stdout
    assert "sessionA" in res.stdout
    assert "sessionB" in res.stdout


def test_sid_selects_specific(tmp_path):
    today = _dt.date.today()
    write_log(tmp_path, today, "want1234", ["09:00 tool=Edit target=want.md"])
    write_log(tmp_path, today, "skip5678", ["10:00 tool=Edit target=skip.md"])
    res = run(["--sid", "want1234"], state_home=tmp_path)
    assert "1 session(s) found" in res.stdout
    assert "want1234" in res.stdout
    assert "skip5678" not in res.stdout


def test_sid_nonexistent_returns_zero(tmp_path):
    today = _dt.date.today()
    write_log(tmp_path, today, "existing", ["09:00 tool=Edit target=a.md"])
    res = run(["--sid", "noexist1"], state_home=tmp_path)
    assert "0 session(s) found" in res.stdout


# --- date selection ---------------------------------------------------------

def test_explicit_date(tmp_path):
    yesterday = _dt.date.today() - _dt.timedelta(days=1)
    write_log(tmp_path, yesterday, "yest1234", ["09:00 tool=Edit target=y.md"])
    res = run(["--date", yesterday.isoformat()], state_home=tmp_path)
    assert yesterday.isoformat() in res.stdout
    assert "yest1234" in res.stdout


def test_invalid_date_exits_nonzero(tmp_path):
    res = run(["--date", "not-a-date"], state_home=tmp_path)
    assert res.returncode != 0


# --- robustness -------------------------------------------------------------

def test_malformed_lines_dropped(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "malforme",
        [
            "this is garbage",
            "09:00 tool=Edit target=ok.md",
            "11:00 random line",
            "10:30 tool=Bash target=git status",
        ],
    )
    res = run([], state_home=tmp_path)
    out = res.stdout
    assert "ok.md" in out
    assert "git status" in out
    assert "2 captured tool calls" in out  # garbage lines excluded


def test_state_home_pointing_at_file(tmp_path):
    blocker = tmp_path / "block"
    blocker.write_text("x")
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(blocker)
    env["PYTHONPATH"] = str(REPO_ROOT)
    res = subprocess.run(
        [sys.executable, "-m", "recap.aggregate"],
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert res.returncode == 0
    assert "0 session(s) found" in res.stdout


# --- --since filtering ------------------------------------------------------

def test_since_filters_entries_strictly_greater(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "sincetst",
        [
            "09:00 tool=Edit target=a.py",
            "09:05 tool=Edit target=b.py",
            "09:10 tool=Edit target=c.py",
        ],
    )
    res = run(["--sid", "sincetst", "--since", "09:05"], state_home=tmp_path)
    assert res.returncode == 0, res.stderr
    # 09:00 and 09:05 dropped (strict >), only 09:10 remains.
    assert "c.py" in res.stdout
    assert "a.py" not in res.stdout
    assert "b.py" not in res.stdout
    assert "Session 09:10 - 09:10" in res.stdout


def test_since_excludes_equal_hhmm(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "equaltst",
        [
            "10:00 tool=Edit target=a.py",
            "10:00 tool=Edit target=b.py",
            "10:01 tool=Edit target=c.py",
        ],
    )
    res = run(["--sid", "equaltst", "--since", "10:00"], state_home=tmp_path)
    assert "a.py" not in res.stdout
    assert "b.py" not in res.stdout
    assert "c.py" in res.stdout


def test_since_filter_empty_yields_zero_sessions(tmp_path):
    today = _dt.date.today()
    write_log(
        tmp_path,
        today,
        "emptyflt",
        [
            "09:00 tool=Edit target=a.py",
        ],
    )
    res = run(["--sid", "emptyflt", "--since", "23:59"], state_home=tmp_path)
    # The selected log still exists, but after filtering nothing remains.
    # render() reports the session with 0 entries — auto_recap.py checks for
    # `0 session(s) found` OR an aggregator session with zero entries; treat
    # both as no-op. This test pins the zero-entry path.
    assert "0 captured tool calls" in res.stdout
    assert "Session --:-- - --:--" in res.stdout


def test_since_malformed_returns_exit_2(tmp_path):
    today = _dt.date.today()
    write_log(tmp_path, today, "badsince", ["09:00 tool=Edit target=a.py"])
    res = run(["--sid", "badsince", "--since", "9:00"], state_home=tmp_path)
    assert res.returncode == 2
    assert "invalid --since" in res.stderr
    res = run(["--sid", "badsince", "--since", "garbage"], state_home=tmp_path)
    assert res.returncode == 2


# --- cursor path helper -----------------------------------------------------

def test_cursor_path_under_sessions_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    # Re-import the module function fresh — kg_paths reads env at call time,
    # not at import time.
    sys.path.insert(0, str(REPO_ROOT))
    import importlib
    from recap.shared import paths as kg_paths
    importlib.reload(kg_paths)
    p = kg_paths.cursor_path("abc12345")
    assert p == tmp_path / "knowledge-gardener" / "sessions" / "abc12345.cursor"


# --- durable_change ----------------------------------------------------------


def test_durable_change_true_on_edit(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text("09:00 tool=Edit target=a.md\n")
    agg = aggregate_session(p, _dt.date(2026, 5, 30))
    assert agg["durable_change"] is True


def test_durable_change_true_on_git_commit(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text("09:00 tool=Bash target=git commit -m x\n")
    agg = aggregate_session(p, _dt.date(2026, 5, 30))
    assert agg["durable_change"] is True


def test_durable_change_false_on_reads_only(tmp_path):
    p = tmp_path / "2026-05-30-aaaaaaaa.log"
    p.write_text(
        "09:00 tool=mcp__Notion__notion-fetch target=x\n"
        "09:01 tool=WebSearch target=y\n"
    )
    agg = aggregate_session(p, _dt.date(2026, 5, 30))
    assert agg["durable_change"] is False


# --- render_timeline ---------------------------------------------------------

def test_render_timeline_groups_by_minute_and_collapses_edits(tmp_path):
    entries = [
        {"hhmm": "10:22", "tool": "Edit", "target": "auto_recap.py", "status": "ok"},
        {"hhmm": "10:22", "tool": "Edit", "target": "auto_recap.py", "status": "ok"},
        {"hhmm": "10:22", "tool": "Write", "target": "relay.yml", "status": "ok"},
        {"hhmm": "10:47", "tool": "Bash", "target": "git commit -m deploy", "status": "ok"},
    ]
    lines = render_timeline(entries)
    assert lines == [
        "- 10:22  Edit auto_recap.py ×2, Write relay.yml",
        "- 10:47  Bash: git commit -m deploy",
    ]


def test_render_timeline_marks_errors():
    entries = [{"hhmm": "11:00", "tool": "Bash", "target": "pytest", "status": "err"}]
    assert render_timeline(entries) == ["- 11:00  Bash: pytest [err]"]


def test_render_timeline_empty():
    assert render_timeline([]) == []


def test_render_timeline_marks_file_tool_errors():
    entries = [{"hhmm": "12:00", "tool": "Edit", "target": "a.py", "status": "err"}]
    assert render_timeline(entries) == ["- 12:00  Edit a.py [err]"]


# --- timeline filter (deterministic noise reduction) -------------------------


def _entries(*rows):
    # rows: (hhmm, tool, target)
    return [{"hhmm": h, "tool": t, "target": g, "status": None} for h, t, g in rows]


def test_structured_output_dropped():
    out = render_timeline(_entries(
        ("11:00", "StructuredOutput", ""),
        ("11:00", "StructuredOutput", ""),
        ("11:00", "Bash", "ls"),
    ))
    assert out == ["- 11:00  Bash: ls"]


def test_web_calls_collapsed():
    out = render_timeline(_entries(
        ("11:00", "WebSearch", "q1"),
        ("11:00", "WebFetch", "https://a"),
        ("11:00", "WebFetch", "https://b"),
    ))
    assert out == ["- 11:00  Web×3"]


def test_readonly_nav_collapsed_by_tool():
    out = render_timeline(_entries(
        ("11:00", "Read", "a.py"),
        ("11:00", "Read", "b.py"),
        ("11:00", "Grep", "foo"),
    ))
    assert out == ["- 11:00  Grep, Read×2"]


def test_minute_with_only_noise_is_skipped():
    out = render_timeline(_entries(
        ("11:00", "StructuredOutput", ""),
        ("11:01", "Edit", "a.py"),
    ))
    assert out == ["- 11:01  Edit a.py"]


def test_bash_agent_edit_preserved():
    out = render_timeline(_entries(
        ("11:00", "Edit", "a.py"),
        ("11:00", "Bash", "git status"),
        ("11:00", "Agent", "Explore:look around"),
    ))
    assert out == ["- 11:00  Edit a.py, Bash: git status, Agent→Explore"]


# --- --json mode -------------------------------------------------------------


def test_json_mode_emits_durable_and_timeline(tmp_path, monkeypatch):
    sessions = tmp_path / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "2026-05-30-aaaaaaaa.log").write_text("10:00 tool=Edit target=a.md\n")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    from recap.aggregate.__main__ import main
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--date", "2026-05-30", "--sid", "aaaaaaaa", "--json"])
    assert rc == 0
    payload = _json.loads(buf.getvalue())
    s = payload["sessions"][0]
    assert s["durable_change"] is True
    assert s["timeline"] == ["- 10:00  Edit a.md"]
    assert s["first_hhmm"] == "10:00"


def test_readnote_becomes_referenced_notes_and_stays_out_of_the_timeline(tmp_path):
    log = tmp_path / "2026-09-18-abc12345.log"
    log.write_text(
        "10:00 tool=ReadNote target=03_PermanentNotes/foo.md\n"
        "10:00 tool=ReadNote target=03_PermanentNotes/foo.md\n"
        "10:01 tool=ReadNote target=02_ReferenceNotes/bar.md\n"
        "10:02 tool=Bash target=git status\n"
    )
    agg = aggregate_session(log, _dt.date(2026, 9, 18))
    assert agg["referenced_notes"] == ["03_PermanentNotes/foo.md", "02_ReferenceNotes/bar.md"]
    assert not any("ReadNote" in line for line in agg["timeline"])
    assert any("git status" in line for line in agg["timeline"])
