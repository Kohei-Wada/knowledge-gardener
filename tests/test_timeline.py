"""Tests for recap/shared/timeline.py."""
from __future__ import annotations

from recap.shared.timeline import durable_change, duration_minutes, render_timeline


def _entries(*rows):
    # rows: (hhmm, tool, target)
    return [{"hhmm": h, "tool": t, "target": g, "status": None} for h, t, g in rows]


def test_durable_change_true_on_edit():
    assert durable_change(_entries(("09:00", "Edit", "a.md"))) is True


def test_durable_change_true_on_git_commit():
    assert durable_change(_entries(("09:00", "Bash", "git commit -m x"))) is True


def test_durable_change_true_on_agent_dispatch():
    assert durable_change(_entries(("09:00", "Agent", "Explore:look"))) is True


def test_durable_change_false_on_reads_only():
    assert durable_change(_entries(("09:00", "mcp__Notion__notion-fetch", "x"),
                                   ("09:01", "WebSearch", "y"))) is False


def test_duration_minutes():
    assert duration_minutes("09:00", "09:30") == 30
    assert duration_minutes("23:50", "00:10") == 20
    assert duration_minutes(None, "09:00") == 0


def test_readnote_stays_out_of_the_timeline():
    assert render_timeline(_entries(("10:00", "ReadNote", "notes/foo.md"))) == []


# --- render_timeline ---------------------------------------------------------

def test_render_timeline_groups_by_minute_and_collapses_edits():
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
