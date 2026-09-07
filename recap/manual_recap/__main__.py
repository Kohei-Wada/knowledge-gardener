#!/usr/bin/env python3
"""Manual recap CLI — drive the kg-recap-sid block from garden-recap.

Unlike the Stop hook (recap.autorecap), this is invoked interactively by the
garden-recap skill, so there is no headless claude call. It reuses the same
aggregator, block surgery, daily-note writer, and cursor as auto-recap, so
manual and auto recaps converge on one block.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import os
import pathlib
import sys

from ..aggregate.__main__ import aggregate_session, list_logs_for_date, select_logs
from ..autorecap.block import extract_timeline_bullets, upsert_session_block
from ..autorecap.daily_note import DailyNote
from ..shared.cursor import write_cursor


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update the per-session recap block (manual garden-recap path)."
    )
    p.add_argument("--sid", required=True, help="Session sid8 to recap.")
    p.add_argument("--daily-path", required=True, help="Absolute path to today's daily note (resolved by the skill).")
    p.add_argument("--timeline-file", default="", help="File with the assistant-authored ### Timeline section. Omitted -> deterministic filtered timeline.")
    p.add_argument("--insert-before", default="", help="Heading to insert a NEW block before (default: append at EOF).")
    p.add_argument("--dry-run", action="store_true", help="Print the daily-note diff and exit without writing.")
    p.add_argument("--no-commit", action="store_true", help="Write the file but skip git commit/push.")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    vault = os.environ.get("KG_VAULT")
    if not vault:
        sys.stderr.write("KG_VAULT unset\n")
        return 2

    today = _dt.date.today()
    selected = select_logs(list_logs_for_date(today), today, args.sid, False)
    if not selected:
        sys.stderr.write(f"no session log for sid {args.sid} on {today.isoformat()} — nothing to recap\n")
        return 3
    agg = aggregate_session(selected[0], today)
    if not agg.get("entry_count"):
        sys.stderr.write("session has no captured tool calls — nothing to recap\n")
        return 3

    start, end = agg["first_hhmm"], agg["last_hhmm"]
    timeline = agg["timeline"]
    if args.timeline_file:
        try:
            authored = pathlib.Path(args.timeline_file).read_text(encoding="utf-8")
        except OSError as e:
            sys.stderr.write(f"cannot read --timeline-file: {e}\n")
            return 2
        bullets = extract_timeline_bullets(authored)
        if bullets:
            timeline = bullets
    daily_path = pathlib.Path(args.daily_path)
    existing = daily_path.read_text(encoding="utf-8") if daily_path.is_file() else ""
    new = upsert_session_block(
        existing, args.sid, start_hhmm=start, end_hhmm=end,
        timeline_bullets=timeline, insert_before=args.insert_before,
    )

    if args.dry_run:
        diff = difflib.unified_diff(
            existing.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=str(daily_path), tofile=f"{daily_path} (new)",
        )
        sys.stdout.write("".join(diff))
        return 0

    note = DailyNote(pathlib.Path(vault), daily_path)
    changed = note.apply_block(
        args.sid, start_hhmm=start, end_hhmm=end,
        timeline_bullets=timeline, insert_before=args.insert_before,
    )
    if changed and not args.no_commit and note.has_repo:
        note.commit(args.sid)
    write_cursor(args.sid, end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
