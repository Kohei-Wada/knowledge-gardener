"""Tests for the day-level "notes consulted today" section."""
from __future__ import annotations

from recap.autorecap.references import link_for, upsert_references

HEADING = "## 今日参照したノート"
DAILY_DIR = "04_DailyNotes"

FRONTMATTER = "---\ntitle: 2026-09-18\n---\n\n"
BLOCK = "<!-- kg-recap-sid:abc12345 -->\n## Session 10:00〜10:30\n\n### Timeline\n\n- 10:00  Bash: ls\n<!-- /kg-recap-sid:abc12345 -->\n"


def test_link_is_relative_to_the_daily_folder():
    assert link_for("03_PermanentNotes/foo.md", DAILY_DIR) == "../03_PermanentNotes/foo.md"


def test_section_is_created_above_the_first_session_block():
    out = upsert_references(FRONTMATTER + BLOCK, HEADING, ["03_PermanentNotes/foo.md"], DAILY_DIR)
    assert out.index(HEADING) < out.index("<!-- kg-recap-sid:")
    assert "- [foo](../03_PermanentNotes/foo.md)" in out


def test_second_session_appends_under_the_same_heading():
    first = upsert_references(FRONTMATTER + BLOCK, HEADING, ["03_PermanentNotes/a.md"], DAILY_DIR)
    second = upsert_references(first, HEADING, ["02_ReferenceNotes/b.md"], DAILY_DIR)
    assert second.count(HEADING) == 1
    assert "- [a](../03_PermanentNotes/a.md)" in second
    assert "- [b](../02_ReferenceNotes/b.md)" in second


def test_a_link_already_in_the_note_is_not_added_again():
    """Covers both re-reading a note and one the created-notes section already lists."""
    created = FRONTMATTER + "## 今日作成したノート\n\n- [foo](../03_PermanentNotes/foo.md) — gist\n\n" + BLOCK
    out = upsert_references(created, HEADING, ["03_PermanentNotes/foo.md"], DAILY_DIR)
    assert out == created


def test_no_heading_declared_is_a_no_op():
    text = FRONTMATTER + BLOCK
    assert upsert_references(text, "", ["03_PermanentNotes/foo.md"], DAILY_DIR) == text


def test_no_notes_is_a_no_op():
    text = FRONTMATTER + BLOCK
    assert upsert_references(text, HEADING, [], DAILY_DIR) == text


def test_placeholder_dash_is_replaced():
    text = FRONTMATTER + HEADING + "\n\n-\n\n" + BLOCK
    out = upsert_references(text, HEADING, ["03_PermanentNotes/foo.md"], DAILY_DIR)
    assert "\n-\n" not in out
    assert "- [foo](../03_PermanentNotes/foo.md)" in out


def test_session_blocks_are_left_untouched():
    out = upsert_references(FRONTMATTER + BLOCK, HEADING, ["03_PermanentNotes/foo.md"], DAILY_DIR)
    assert BLOCK in out
