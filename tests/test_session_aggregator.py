import datetime as dt
from pathlib import Path
import pytest
from recap.autorecap.context import RecapContext
from recap.autorecap.session_aggregator import SessionAggregator


def _ctx(sid8, since=None):
    return RecapContext(sid8=sid8, vault=Path("/tmp"),
                        today_str=dt.date.today().isoformat(),
                        since=since, transcript_path=None)


def test_aggregation_carries_signals(tmp_path, monkeypatch):
    sessions = tmp_path / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True)
    today = dt.date.today().isoformat()
    (sessions / f"{today}-aaaaaaaa.log").write_text(
        "10:00 tool=Edit target=a.md\n10:01 tool=Bash target=git commit -m x\n"
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    agg = SessionAggregator(_ctx("aaaaaaaa")).aggregate()
    assert agg is not None
    assert agg.durable_change is True
    assert agg.entry_count == 2
    assert agg.start_hhmm == "10:00"
    assert agg.end_hhmm == "10:01"
    assert agg.timeline[0].startswith("- 10:00")


def test_aggregation_none_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert SessionAggregator(_ctx("nolog123")).aggregate() is None


def test_aggregate_covers_the_whole_session_ignoring_cursor(tmp_path, monkeypatch):
    sessions = tmp_path / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True)
    today = dt.date.today().isoformat()
    (sessions / f"{today}-abcd1234.log").write_text(
        "09:00 tool=Edit target=a.py\n09:30 tool=Edit target=b.py\n"
    )
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    agg = SessionAggregator(_ctx("abcd1234", since="09:20")).aggregate()
    assert agg.timeline == ["- 09:00  Edit a.py", "- 09:30  Edit b.py"]
