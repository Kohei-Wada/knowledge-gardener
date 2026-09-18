from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys

from ..shared.fs import plugin_root
from ..shared.hook_io import log
from .context import RecapContext


def _run_aggregator_json(sid8: str, since: str | None) -> dict | None:
    root = plugin_root()
    if not (root / "recap" / "aggregate" / "__main__.py").is_file():
        return None
    args = [sys.executable, "-m", "recap.aggregate", "--sid", sid8, "--json"]
    if since:
        args += ["--since", since]
    env = {**os.environ, "PYTHONPATH": str(root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=30,
                              check=False, env=env, cwd=str(root))
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"aggregator failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"aggregator exit={proc.returncode} stderr={proc.stderr[:200]!r}")
        return None
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        log("aggregator JSON parse failed")
        return None
    sessions = payload.get("sessions") or []
    if not sessions:
        return None
    return sessions[0]


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
        s = _run_aggregator_json(self._ctx.sid8, since=None)  # whole-session: Timeline is regenerated & replaced each Stop
        if not s:
            return None
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
