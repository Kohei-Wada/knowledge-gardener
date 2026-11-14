import datetime as dt
from pathlib import Path

from recap.autorecap.context import RecapContext
from recap.autorecap.session_aggregator import SessionAggregator
from tests.transcripts import write_transcript


def _ctx(transcript, vault=Path("/tmp")):
    return RecapContext(sid8="aaaaaaaa", vault=vault, today_str=dt.date.today().isoformat(),
                        transcript_path=str(transcript) if transcript else None)


def test_aggregation_carries_signals(tmp_path):
    t = write_transcript(tmp_path / "t.jsonl",
                         ["10:00 tool=Edit target=a.md", "10:01 tool=Bash target=git commit -m x"])
    agg = SessionAggregator(_ctx(t)).aggregate()
    assert agg is not None
    assert agg.durable_change is True
    assert agg.entry_count == 2
    assert agg.start_hhmm == "10:00"
    assert agg.end_hhmm == "10:01"
    assert agg.duration_min == 1
    assert agg.timeline[0].startswith("- 10:00")


def test_aggregation_none_without_a_transcript_or_tool_calls(tmp_path):
    assert SessionAggregator(_ctx(None)).aggregate() is None
    assert SessionAggregator(_ctx(tmp_path / "missing.jsonl")).aggregate() is None
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    assert SessionAggregator(_ctx(empty)).aggregate() is None


def test_timeline_after_cuts_at_a_timestamp(tmp_path):
    t = write_transcript(tmp_path / "t.jsonl",
                         ["09:00 tool=Edit target=a.py", "09:30 tool=Edit target=b.py"])
    agg = SessionAggregator(_ctx(t)).aggregate()
    assert agg.timeline == ["- 09:00  Edit a.py", "- 09:30  Edit b.py"]
    cut = agg.entries[0]["ts"]
    assert agg.timeline_after(cut) == ["- 09:30  Edit b.py"]
    assert agg.entries_after(agg.entries[-1]["ts"]) == []


def test_read_inside_the_vault_becomes_a_referenced_note(tmp_path):
    vault = tmp_path / "vault"
    (vault / "notes").mkdir(parents=True)
    t = write_transcript(tmp_path / "t.jsonl",
                         ["09:00 tool=ReadNote target=notes/foo.md", "09:00 tool=ReadNote target=notes/foo.md",
                          "09:01 tool=Edit target=a.md"], vault)
    agg = SessionAggregator(_ctx(t, vault)).aggregate()
    assert agg.referenced_notes == ["notes/foo.md"]
    assert not any("ReadNote" in line for line in agg.timeline)
