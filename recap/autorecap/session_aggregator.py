from __future__ import annotations

import dataclasses
import datetime as _dt

from ..aggregate.__main__ import aggregate_session
from ..shared.paths import session_log_path
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


class SessionAggregator:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx

    def aggregate(self) -> Aggregation | None:
        today = _dt.date.today()
        log_path = session_log_path(self._ctx.sid8, today)
        if not log_path.is_file():
            return None
        s = aggregate_session(log_path, today)  # whole session; the caller cuts the new slice
        start = s.get("first_hhmm")
        end = s.get("last_hhmm")
        if not start or not end or not s.get("entry_count"):
            return None  # empty / fully-filtered window -> no-op
        return Aggregation(
            start_hhmm=start,
            end_hhmm=end,
            durable_change=bool(s.get("durable_change")),
            entry_count=int(s.get("entry_count") or 0),
            duration_min=int(s.get("duration_min") or 0),
            timeline=list(s.get("timeline") or []),
            referenced_notes=list(s.get("referenced_notes") or []),
        )
