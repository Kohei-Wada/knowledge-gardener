from __future__ import annotations

import dataclasses
import datetime as _dt
import pathlib

from ..shared.timeline import durable_change, duration_minutes, render_timeline
from ..shared.tool_calls import READ_NOTE_TOOL, read_tool_calls
from .context import RecapContext


@dataclasses.dataclass(frozen=True)
class Aggregation:
    start_hhmm: str
    end_hhmm: str
    durable_change: bool
    entry_count: int
    duration_min: int
    timeline: list[str]
    referenced_notes: list[str]
    entries: list[dict]

    def entries_after(self, ts: float) -> list[dict]:
        return [e for e in self.entries if e["ts"] > ts]

    def timeline_after(self, ts: float) -> list[str]:
        return render_timeline(self.entries_after(ts))


def aggregate_transcript(transcript_path: str | pathlib.Path | None, date: _dt.date,
                         vault: pathlib.Path | None) -> Aggregation | None:
    """Whole-session view of `date` from the transcript; None when it holds no material tool call."""
    entries = read_tool_calls(transcript_path, date, vault)
    if not entries:
        return None
    start, end = entries[0]["hhmm"], entries[-1]["hhmm"]
    referenced = dict.fromkeys(e["target"] for e in entries if e["tool"] == READ_NOTE_TOOL and e["target"])
    return Aggregation(
        start_hhmm=start,
        end_hhmm=end,
        durable_change=durable_change(entries),
        entry_count=len(entries),
        duration_min=duration_minutes(start, end),
        timeline=render_timeline(entries),
        referenced_notes=list(referenced),
        entries=entries,
    )


class SessionAggregator:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def aggregate(self) -> Aggregation | None:
        return aggregate_transcript(self._ctx.transcript_path, _dt.date.today(), self._ctx.vault)
