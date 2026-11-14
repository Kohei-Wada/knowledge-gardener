import datetime as _dt
import json
import time
import pytest
from recap.autorecap.transcript import slice_transcript


@pytest.fixture(autouse=True)
def _utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    time.tzset()


def _line(typ, ts, content):
    return json.dumps({"type": typ, "timestamp": ts, "message": {"role": typ, "content": content}})


def _epoch(ts):
    return _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def test_returns_empty_for_missing_path():
    assert slice_transcript(None, 0.0, "2026-05-30") == ""
    assert slice_transcript("/nonexistent.jsonl", 0.0, "2026-05-30") == ""


def test_keeps_only_turns_stamped_after_since(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([
        _line("user", "2026-05-30T08:00:00.000Z", "before window"),
        _line("user", "2026-05-30T09:00:00.000Z", "at the cut"),
        _line("user", "2026-05-30T09:00:00.500Z", "after window"),
        _line("assistant", "2026-05-30T10:01:00.000Z", [{"type": "text", "text": "reply"}]),
    ]) + "\n")
    out = slice_transcript(str(p), _epoch("2026-05-30T09:00:00.000Z"), "2026-05-30")
    assert "before window" not in out
    assert "at the cut" not in out
    assert "after window" in out
    assert "reply" in out


def test_drops_thinking_and_tooluse_blocks(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join([
        _line("assistant", "2026-05-30T10:00:00.000Z",
              [{"type": "thinking", "thinking": "secret"},
               {"type": "tool_use", "name": "Bash", "input": {}},
               {"type": "text", "text": "visible"}]),
    ]) + "\n")
    out = slice_transcript(str(p), None, "2026-05-30")
    assert "secret" not in out
    assert "visible" in out


def test_ignores_other_date(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text(_line("user", "2026-05-29T10:00:00.000Z", "yesterday") + "\n")
    assert slice_transcript(str(p), None, "2026-05-30") == ""


def test_char_cap_keeps_most_recent(tmp_path):
    p = tmp_path / "t.jsonl"
    lines = [_line("user", f"2026-05-30T10:0{i}:00.000Z", f"msg{i}" * 100) for i in range(5)]
    p.write_text("\n".join(lines) + "\n")
    out = slice_transcript(str(p), None, "2026-05-30", char_cap=300)
    assert len(out) <= 300
    assert "msg4" in out
    assert "msg0" not in out


def test_malformed_lines_skipped(tmp_path):
    p = tmp_path / "t.jsonl"
    p.write_text("not json\n" + _line("user", "2026-05-30T10:00:00.000Z", "ok") + "\n")
    assert "ok" in slice_transcript(str(p), None, "2026-05-30")
