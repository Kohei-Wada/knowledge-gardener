#!/usr/bin/env python3
"""Phase 3 of issue #1 — Stop and SessionEnd hooks that silently write
today's session block to the vault's daily note via headless Claude.

Opt-in: requires KG_AUTO_RECAP=1 in the environment. When unset (or any
other value), the hook is a fast no-op. See
docs/specs/2026-05-20-auto-recap-design.md for the design rationale and
docs/specs/2026-11-14-recap-throttle-design.md for the pass schedule.
"""
from __future__ import annotations

import contextlib
import fcntl
import os
import pathlib
import shutil
import subprocess
import sys
import time
import traceback

from ..shared.hook_io import DEFAULT_TIMEOUT, emit_continue, log
from ..shared.conventions import convention_files
from ..shared.fs import plugin_root, read_text
from ..shared.paths import recap_lock_path
from ..shared.pass_state import covered_until, last_pass_started, mark_covered, mark_pass_started
from .context import RecapContext
from .session_aggregator import SessionAggregator
from .daily_note_resolver import DailyNoteResolver
from .daily_note import DailyNote
from .gate import is_substantive, recap_interval_seconds
from .transcript import slice_transcript
from .block import escape_inline_tags, existing_timeline_bullets, extract_timeline_bullets

DEFAULT_MODEL = "sonnet"
_SYSTEM_PROMPT = "You are knowledge-gardener's auto-recap writer. Follow the user message exactly."
_FINAL_FLAG = "--final"
_FINAL_WORKER_FLAG = "--final-worker"


def load_vault_context(vault: pathlib.Path) -> str:
    """Return the convention docs (READMEs + linked docs) used for daily-note discovery.

    The daily-note folder and filename are not pre-resolved here — they are
    discovered by Claude from the README inside the same prompt that composes
    the recap block (see parse_discovery / main).
    """
    readme_parts: list[str] = []
    for candidate in convention_files(vault):
        readme_parts.append(f"--- {candidate} ---\n{read_text(candidate)}")
    return "\n\n".join(readme_parts) or "(no README found)"


def compose_prompt(template: str, substitutions: dict[str, str]) -> str:
    out = template
    for k, v in substitutions.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def call_claude(prompt: str, timeout: int) -> str | None:
    cmd_name = os.environ.get("KG_AUTO_RECAP_CLAUDE_CMD", "claude")
    cmd_path = shutil.which(cmd_name) or cmd_name
    model = os.environ.get("KG_AUTO_RECAP_MODEL") or DEFAULT_MODEL
    try:
        proc = subprocess.run(
            # No customizations, tools or transcript: the call is one prompt in, one Timeline out.
            [cmd_path, "-p", "--safe-mode", "--tools", "", "--no-session-persistence",
             "--system-prompt", _SYSTEM_PROMPT, "--model", model],
            input=prompt,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            env={**os.environ, "KG_AUTO_RECAP": "0"},
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        log(f"claude invocation failed: {e!r}")
        return None
    if proc.returncode != 0:
        log(f"claude exit={proc.returncode} stderr={proc.stderr[:300]!r}")
        return None
    return proc.stdout


@contextlib.contextmanager
def _session_lock(sid8: str, *, wait: bool):
    """Yield True while holding the session's pass lock, False when another pass holds it."""
    path = recap_lock_path(sid8)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        f = path.open("w")
    except OSError:
        yield True
        return
    with f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX if wait else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            yield False
            return
        yield True


class AutoRecap:
    def __init__(self, ctx: RecapContext, *, final: bool = False) -> None:
        self._ctx = ctx
        self._final = final

    def run(self) -> None:
        # The final pass waits for a Stop pass still in flight; a Stop pass yields to any other.
        with _session_lock(self._ctx.sid8, wait=self._final) as held:
            if held:
                self._run_pass()

    def _throttled(self) -> bool:
        last = last_pass_started(self._ctx.sid8)
        return last is not None and time.time() - last < recap_interval_seconds(os.environ)

    def _run_pass(self) -> None:
        ctx = self._ctx

        if not self._final and self._throttled():
            return

        covered = covered_until(ctx.sid8)
        started = time.time()
        agg = SessionAggregator(ctx).aggregate()
        if agg is None:
            return
        if covered is not None and not agg.entries_after(covered):
            return  # no activity since the last written pass

        substantive = is_substantive(agg.durable_change, agg.entry_count, agg.duration_min, os.environ)
        if not substantive and not self._final:
            return  # leaves the throttle alone, so the first substantive Stop writes at once

        resolver = DailyNoteResolver(ctx)
        pre = resolver.pre_resolve()

        # Path resolution. A non-substantive session needs a pre-resolved
        # path (env/warm cache) — we never spend an LLM discovery call for it.
        if pre is not None:
            target = pre
        elif not substantive:
            log("no pre-resolved daily path and non-substantive session -> skip (cache warms on a substantive Stop)")
            return
        else:
            target = None  # resolved from discovery after the LLM call

        mark_pass_started(ctx.sid8, started)

        previous: list[str] = []
        if target is not None and target.path.is_file():
            previous = existing_timeline_bullets(target.path.read_text(encoding="utf-8"), ctx.sid8)
        mechanical = {escape_inline_tags(b) for b in agg.timeline}
        previous_is_composed = any(b not in mechanical for b in previous)
        since = covered if previous else None

        timeline_bullets: list[str] | None = None

        if substantive:
            tslice = slice_transcript(ctx.transcript_path, since, ctx.today_str)
            new_slice = agg.timeline_after(since) if since is not None else agg.timeline

            if pre is not None:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_compose_prompt.md"
            else:
                tmpl_path = plugin_root() / "recap" / "autorecap" / "prompts" / "auto_recap_prompt.md"
            if not tmpl_path.is_file():
                log(f"prompt template missing: {tmpl_path}")
                return
            prompt = compose_prompt(tmpl_path.read_text(encoding="utf-8"), {
                "TODAY": ctx.today_str,
                "VAULT_README": load_vault_context(ctx.vault) if pre is None else "",
                "PREVIOUS_TIMELINE": "\n".join(previous) or "(none: this is the first pass for the session)",
                "TIMELINE": "\n".join(new_slice) or "(no new tool activity)",
                "TRANSCRIPT_SLICE": tslice or "(transcript unavailable)",
            })
            timeout = int(os.environ.get("KG_AUTO_RECAP_TIMEOUT", str(DEFAULT_TIMEOUT)))
            out = call_claude(prompt, timeout=timeout)
            if out:
                if pre is None:
                    resolved = resolver.resolve_from_discovery(out)
                    if resolved is None:
                        return
                    target = resolved
                timeline_bullets = extract_timeline_bullets(out) or None
            elif pre is None:
                log("claude failed and no pre-resolved daily path -> skip")
                return

        if timeline_bullets is None:
            if previous_is_composed:
                log("no composed Timeline this pass -> keeping the one in the note")
                return
            timeline_bullets = agg.timeline  # nothing composed to lose: write the mechanical log

        note = DailyNote(
            ctx.vault, target.path, template=target.template, today_str=ctx.today_str
        )
        if not note.apply_block(
            ctx.sid8, start_hhmm=agg.start_hhmm, end_hhmm=agg.end_hhmm,
            timeline_bullets=timeline_bullets, insert_before=target.insert_before,
        ):
            mark_covered(ctx.sid8, started)
            return

        note.apply_references(target.references_section, agg.referenced_notes, vault=ctx.vault)

        if not note.has_repo:
            log("vault not in a git repo - skipping commit")
            mark_covered(ctx.sid8, started)
            return
        note.commit(ctx.sid8)
        mark_covered(ctx.sid8, started)
        if substantive:
            resolver.persist_cache()


def _spawn_final_worker(raw: str) -> None:
    """Hand the final pass to a detached process: SessionEnd gives a hook about 1.5 s."""
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", "recap.autorecap", _FINAL_WORKER_FLAG],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        proc.stdin.write(raw)
        proc.stdin.close()
    except OSError as e:
        log(f"final pass spawn failed: {e!r}")


def main() -> None:
    try:
        raw = sys.stdin.read()
    except Exception:
        emit_continue()
        return

    ctx = RecapContext.from_hook(raw, os.environ)
    if ctx is None:
        emit_continue()
        return

    args = sys.argv[1:]
    if _FINAL_FLAG in args:
        _spawn_final_worker(raw)
        emit_continue()
        return

    try:
        AutoRecap(ctx, final=_FINAL_WORKER_FLAG in args).run()
    except Exception:
        log("uncaught: " + traceback.format_exc().splitlines()[-1])
    finally:
        emit_continue()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("uncaught: " + traceback.format_exc().splitlines()[-1])
        emit_continue()
