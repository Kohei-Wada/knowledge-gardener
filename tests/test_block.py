import pytest

from recap.autorecap.block import upsert_session_block, extract_timeline_bullets

LEGACY_KPT = "### KPT\n- Keep: a\n- Problem: b\n- Try: c"


def test_create_block_writes_timeline_only():
    out = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    assert "<!-- kg-recap-sid:abc12345 -->" in out
    assert "## Session 09:00〜09:05" in out
    assert "### Timeline" in out
    assert "- 09:00  Edit a.py" in out
    assert "### KPT" not in out


def test_header_carries_no_topic():
    out = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    # exactly the range, nothing appended after it
    assert "\n## Session 09:00〜09:05\n" in out


def test_topic_keyword_is_rejected():
    with pytest.raises(TypeError):
        upsert_session_block(
            "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
            timeline_bullets=[], topic="nope",
        )


def test_kpt_section_keyword_is_rejected():
    with pytest.raises(TypeError):
        upsert_session_block(
            "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
            timeline_bullets=[], kpt_section=LEGACY_KPT,
        )


def test_update_replaces_timeline_and_extends_end():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:06", end_hhmm="09:10",
        timeline_bullets=["- 09:06  Edit b.py"],
    )
    assert second.count("<!-- kg-recap-sid:abc12345 -->") == 1
    assert "## Session 09:00〜09:10" in second   # start preserved, end extended
    assert "- 09:06  Edit b.py" in second
    assert "- 09:00  Edit a.py" not in second   # caller owns the whole list


def test_reapplying_identical_inputs_is_a_byte_level_noop():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    assert second == first


def test_earlier_incoming_start_wins():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="14:41", end_hhmm="14:47",
        timeline_bullets=["- 14:41  Edit a.py"],
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="12:20", end_hhmm="14:47",
        timeline_bullets=["- 12:20  Bash: x", "- 14:41  Edit a.py"],
    )
    assert "## Session 12:20〜14:47" in second


def test_later_end_wins_over_existing():
    first = upsert_session_block(
        "", "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    second = upsert_session_block(
        first, "abc12345", start_hhmm="10:00", end_hhmm="10:05",
        timeline_bullets=["- 10:00  Edit b.py"],
    )
    assert "## Session 09:00〜10:05" in second


def test_other_session_block_is_untouched():
    other = (
        "<!-- kg-recap-sid:zzz99999 -->\n"
        "## Session 08:00〜08:10  keep me\n\n"
        "### Timeline\n- 08:00  Bash: ls\n"
        "<!-- /kg-recap-sid:zzz99999 -->\n"
    )
    out = upsert_session_block(
        other, "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"],
    )
    assert "<!-- kg-recap-sid:zzz99999 -->" in out
    assert "## Session 08:00〜08:10  keep me" in out
    assert "<!-- kg-recap-sid:abc12345 -->" in out


def test_legacy_hhmm_suffixed_marker_does_not_collide():
    legacy = (
        "<!-- kg-recap-sid:abc12345-0900 -->\n"
        "## Session 09:00〜09:05  legacy\n\n"
        "### Timeline\n- 09:00  Bash: ls\n"
        "<!-- /kg-recap-sid:abc12345-0900 -->\n"
    )
    out = upsert_session_block(
        legacy, "abc12345", start_hhmm="10:00", end_hhmm="10:05",
        timeline_bullets=["- 10:00  Edit a.py"],
    )
    assert "<!-- kg-recap-sid:abc12345-0900 -->" in out   # legacy block intact
    assert "<!-- kg-recap-sid:abc12345 -->" in out        # new bare block added
    assert out.count("### Timeline") == 2


def test_insert_before_anchor_places_block_above_heading():
    existing = "intro\n\n## 関連リンク\n- x\n"
    out = upsert_session_block(
        existing, "abc12345", start_hhmm="09:00", end_hhmm="09:05",
        timeline_bullets=["- 09:00  Edit a.py"], insert_before="## 関連リンク",
    )
    assert out.index("<!-- kg-recap-sid:abc12345 -->") < out.index("## 関連リンク")


def test_pre_existing_kpt_in_an_old_block_is_left_in_place():
    """A block written by <=v0.21.0 still has a KPT and a topic in its heading.
    Upserting rewrites the heading without the topic and refreshes the Timeline;
    the stale KPT text is not parsed and not removed (the vault migration does that)."""
    old = (
        "<!-- kg-recap-sid:abc12345 -->\n"
        "## Session 09:00〜09:05  old topic\n\n"
        "### Timeline\n- 09:00  Edit a.py\n\n"
        f"{LEGACY_KPT}\n"
        "<!-- /kg-recap-sid:abc12345 -->\n"
    )
    out = upsert_session_block(
        old, "abc12345", start_hhmm="09:00", end_hhmm="09:30",
        timeline_bullets=["- 09:30  Edit b.py"],
    )
    assert "## Session 09:00〜09:30" in out
    assert "old topic" not in out           # topic dropped from the rewritten header
    assert "- 09:30  Edit b.py" in out      # timeline refreshed
    assert "- Keep: a" in out               # stale KPT untouched


def test_extract_timeline_bullets_returns_none_without_a_section():
    assert extract_timeline_bullets("no timeline here") is None


def test_extract_timeline_bullets_reads_bullets():
    out = extract_timeline_bullets("### Timeline\n\n- 09:00–09:05 やった\n- 09:05–09:10 もっとやった\n")
    assert out == ["- 09:00–09:05 やった", "- 09:05–09:10 もっとやった"]


def test_extract_timeline_bullets_empty_section_yields_empty_list():
    assert extract_timeline_bullets("### Timeline\n\n### Other\n- x") == []


def test_extract_timeline_bullets_does_not_leak_following_section():
    # malformed output: empty Timeline directly followed by another heading, no blank line
    assert extract_timeline_bullets("### Timeline\n### Other\n- x") == []
