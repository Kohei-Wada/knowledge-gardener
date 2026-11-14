#!/usr/bin/env python3
"""Manual recap CLI — drive the kg-recap-sid block from garden-recap.

Unlike the Stop hook (recap.autorecap), this is invoked interactively by the
garden-recap skill, so there is no headless claude call. It reads the same
transcript and reuses the same aggregator, block surgery, daily-note writer
and pass marker as auto-recap, so manual and auto recaps converge on one block.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import difflib
import os
import pathlib
import sys
import time

from ..autorecap.block import extract_timeline_bullets, upsert_session_block
from ..autorecap.daily_note import DailyNote
from ..autorecap.session_aggregator import aggregate_transcript
from ..shared.pass_state import mark_covered


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Update the per-session recap block (manual garden-recap path)."
    )
    p.add_argument("--sid", default="", help="Session id (or its first 8 characters) to recap. Default: $CLAUDE_CODE_SESSION_ID, the session running this command.")
    p.add_argument("--transcript", default="", help="Path to the session's transcript. Default: found by session id under the Claude Code projects directory.")
    p.add_argument("--daily-path", required=True, help="Absolute path to today's daily note (resolved by the skill).")
    p.add_argument("--timeline-file", default="", help="File with the assistant-authored ### Timeline section. Omitted -> deterministic filtered timeline.")
    p.add_argument("--insert-before", default="", help="Heading to insert a NEW block before (default: append at EOF).")
    p.add_argument("--dry-run", action="store_true", help="Print the daily-note diff and exit without writing.")
    p.add_argument("--no-commit", action="store_true", help="Write the file but skip git commit/push.")
    return p.parse_args(argv)


def find_transcript(session: str) -> pathlib.Path | None:
    """Newest `<projects>/*/<session>*.jsonl`; `session` may be a full id or its sid8."""
    config = pathlib.Path(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude").expanduser()
    found = sorted((config / "projects").glob(f"*/{session}*.jsonl"), key=lambda p: p.stat().st_mtime)
    return found[-1] if found else None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    vault = os.environ.get("KG_VAULT")
    if not vault:
        sys.stderr.write("KG_VAULT unset\n")
        return 2

    session = args.sid or os.environ.get("CLAUDE_CODE_SESSION_ID") or ""
    if not session:
        sys.stderr.write("no --sid and CLAUDE_CODE_SESSION_ID unset — cannot tell which session to recap\n")
        return 2
    sid8 = session[:8]
    transcript = pathlib.Path(args.transcript) if args.transcript else find_transcript(session)
    if transcript is None or not transcript.is_file():
        sys.stderr.write(f"no transcript for session {session} — nothing to recap\n")
        return 3
    started = time.time()
    agg = aggregate_transcript(transcript, _dt.date.today(), pathlib.Path(vault))
    if agg is None:
        sys.stderr.write("session has no material tool calls today — nothing to recap\n")
        return 3

    start, end = agg.start_hhmm, agg.end_hhmm
    timeline = agg.timeline
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
        existing, sid8, start_hhmm=start, end_hhmm=end,
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
        sid8, start_hhmm=start, end_hhmm=end,
        timeline_bullets=timeline, insert_before=args.insert_before,
    )
    if changed and not args.no_commit and note.has_repo:
        note.commit(sid8)
    mark_covered(sid8, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
