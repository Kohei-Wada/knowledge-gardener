from __future__ import annotations

import datetime as _dt
import os
import pathlib
import subprocess
from typing import Callable

from ..shared.hook_io import log
from .block import copy_session_blocks, upsert_session_block
from .references import upsert_references

_DATE_PLACEHOLDER = "{{date}}"
_MAX_REBASE_STEPS = 50

# (vault-relative path, base text, our text) -> merged text, or None when the
# conflict is not ours to resolve.
Resolver = Callable[[str, str, str], "str | None"]


def build_commit_subject(today: str, marker_key: str) -> str:
    """Compose the auto-recap commit subject line: `water: {today} daily auto-recap ({marker_key})`."""
    return f"water: {today} daily auto-recap ({marker_key})"


def run_git(args: list[str], cwd: pathlib.Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)
    return proc.returncode, proc.stdout, proc.stderr


def commit_and_push(
    repo_root: pathlib.Path,
    daily_path: pathlib.Path,
    marker_key: str,
    resolve: Resolver | None = None,
) -> None:
    rel = daily_path.relative_to(repo_root) if str(daily_path).startswith(str(repo_root)) else daily_path
    # pre-commit (best-effort)
    if (repo_root / ".pre-commit-config.yaml").is_file():
        try:
            subprocess.run(
                ["pre-commit", "run", "--files", str(rel)],
                cwd=repo_root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            log(f"pre-commit failed: {e!r}")
    code, _, err = run_git(["add", str(rel)], repo_root)
    if code != 0:
        log(f"git add failed: {err[:200]!r}")
        return
    today = _dt.date.today().isoformat()
    subject = build_commit_subject(today, marker_key)
    # Path-limited: the vault is shared, so the index can hold files staged by
    # the user's own session. A bare `git commit` would sweep those in.
    code, _, err = run_git(
        ["commit", "-m", subject, "--", str(rel)],
        repo_root,
    )
    if code != 0:
        log(f"git commit failed: {err[:200]!r}")
        return
    if os.environ.get("KG_AUTO_RECAP_NO_PUSH") == "1":
        log(f"push skipped (KG_AUTO_RECAP_NO_PUSH=1) for {today} {marker_key}")
        return
    _push_with_rebase(repo_root, resolve)


def _push_with_rebase(repo_root: pathlib.Path, resolve: Resolver | None = None,
                      attempts: int = 3) -> None:
    """Push, rebasing onto the remote when another machine pushed first.

    The same vault is recapped from several machines, so a rejected push is
    routine rather than exceptional. Without the retry the commit stays local
    and the next session inherits a diverged branch.
    """
    err = ""
    for _ in range(attempts):
        code, _, err = run_git(["push"], repo_root)
        if code == 0:
            return
        code, _, rebase_err = run_git(["pull", "--rebase"], repo_root)
        if code != 0 and not (resolve and _resolve_rebase(repo_root, resolve)):
            # Never leave the vault half-rebased for the next session to find.
            run_git(["rebase", "--abort"], repo_root)
            log(f"git pull --rebase failed, push abandoned: {rebase_err[:200]!r}")
            return
    log(f"git push failed after {attempts} attempts: {err[:200]!r}")


def _rebase_in_progress(repo_root: pathlib.Path) -> bool:
    for name in ("rebase-merge", "rebase-apply"):
        code, out, _ = run_git(["rev-parse", "--git-path", name], repo_root)
        if code == 0 and (repo_root / out.strip()).exists():
            return True
    return False


def _resolve_rebase(repo_root: pathlib.Path, resolve: Resolver) -> bool:
    """Finish a conflicted rebase by merging each conflicted daily note.

    Another machine creating or recapping the same daily note makes every
    rebase conflict on it (both sides add the file), so aborting would strand
    the commit for good: each later recap stacks on the same conflict. Stage 2
    is the remote's note, stage 3 ours. Returns False, leaving the rebase for
    the caller to abort, on any conflict `resolve` does not claim.
    """
    for _ in range(_MAX_REBASE_STEPS):
        if not _rebase_in_progress(repo_root):
            return True
        code, out, diff_err = run_git(["diff", "--name-only", "--diff-filter=U"], repo_root)
        if code != 0:
            log(f"conflict check failed: {diff_err[:200]!r}")
            return False
        for rel in out.split("\n"):
            if not rel:
                continue
            code_b, base, _ = run_git(["show", f":2:{rel}"], repo_root)
            code_o, ours, _ = run_git(["show", f":3:{rel}"], repo_root)
            merged = resolve(rel, base, ours) if code_b == 0 and code_o == 0 else None
            if merged is None:
                log(f"rebase conflict not resolvable automatically: {rel}")
                return False
            try:
                (repo_root / rel).write_text(merged, encoding="utf-8")
            except OSError as e:
                log(f"conflict write failed: {e!r}")
                return False
            if run_git(["add", rel], repo_root)[0] != 0:
                return False
            log(f"rebase conflict resolved by re-applying recap blocks: {rel}")
        code, _, err = run_git(["-c", "core.editor=true", "rebase", "--continue"], repo_root)
        if code == 0:
            continue
        # a failed diff also prints nothing, so its exit code decides, not its output
        diff_code, unmerged, diff_err = run_git(["diff", "--name-only", "--diff-filter=U"], repo_root)
        if diff_code != 0:
            log(f"conflict check after rebase --continue failed: {diff_err[:200]!r}")
            return False
        if unmerged:
            continue  # the next replayed commit stopped on a conflict
        # our blocks were already on the remote: the replayed commit is empty
        if run_git(["diff", "--cached", "--quiet"], repo_root)[0] == 0:
            skip_code, _, skip_err = run_git(["rebase", "--skip"], repo_root)
            if skip_code == 0:
                continue
            log(f"git rebase --skip failed: {skip_err[:200]!r}")
            return False
        log(f"git rebase --continue failed: {err[:200]!r}")
        return False
    return not _rebase_in_progress(repo_root)


def find_repo_root(start: pathlib.Path) -> pathlib.Path | None:
    p = start.resolve()
    for cand in [p, *p.parents]:
        if (cand / ".git").exists():
            return cand
    return None


class DailyNote:
    def __init__(
        self,
        vault: pathlib.Path,
        daily_path: pathlib.Path,
        *,
        template: pathlib.Path | None = None,
        today_str: str = "",
    ) -> None:
        self._daily_path = daily_path
        self._repo_root = find_repo_root(vault)
        self._template = template
        self._today_str = today_str
        self._insert_before = ""
        self._replays: list[Callable[[str], str]] = []

    def _seed(self) -> str:
        """Initial body for a daily note that does not exist yet.

        The vault README names the template; we only substitute the {{date}}
        placeholder. Any failure degrades to an empty seed so a missing or
        unreadable template never costs a recap.
        """
        if self._template is None:
            return ""
        try:
            body = self._template.read_text(encoding="utf-8")
        except OSError as e:
            log(f"daily template unreadable, seeding empty: {e!r}")
            return ""
        return body.replace(_DATE_PLACEHOLDER, self._today_str)

    @property
    def has_repo(self) -> bool:
        return self._repo_root is not None

    def apply_block(self, sid8: str, *, start_hhmm: str, end_hhmm: str,
                    timeline_bullets: list[str], insert_before: str) -> bool:
        existing = (
            self._daily_path.read_text(encoding="utf-8")
            if self._daily_path.exists()
            else self._seed()
        )
        def replay(text: str) -> str:
            return upsert_session_block(
                text, sid8, start_hhmm=start_hhmm, end_hhmm=end_hhmm,
                timeline_bullets=timeline_bullets, insert_before=insert_before,
            )

        self._insert_before = insert_before
        self._replays = [replay]
        new = replay(existing)
        if new == existing:
            return False
        tmp = self._daily_path.with_suffix(self._daily_path.suffix + ".tmp")
        try:
            self._daily_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(new, encoding="utf-8")
            os.replace(tmp, self._daily_path)  # atomic
        except OSError as e:
            log(f"daily write failed: {e!r}")
            try:
                tmp.unlink(missing_ok=True)  # don't leave an orphaned .tmp in the vault
            except OSError:
                pass
            return False
        return True

    def apply_references(self, heading: str, note_rels: list[str], *,
                         vault: pathlib.Path) -> bool:
        """Record notes consulted this session. No-op unless the vault declares a heading."""
        if not heading or not note_rels or not self._daily_path.exists():
            return False
        try:
            existing = self._daily_path.read_text(encoding="utf-8")
            daily_rel_dir = str(self._daily_path.parent.relative_to(vault))
        except (OSError, ValueError) as e:
            log(f"references skipped: {e!r}")
            return False
        def replay(text: str) -> str:
            return upsert_references(text, heading, note_rels, daily_rel_dir)

        self._replays.append(replay)
        new = replay(existing)
        if new == existing:
            return False
        tmp = self._daily_path.with_suffix(self._daily_path.suffix + ".tmp")
        try:
            tmp.write_text(new, encoding="utf-8")
            os.replace(tmp, self._daily_path)
        except OSError as e:
            log(f"references write failed: {e!r}")
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            return False
        return True

    def _resolve_conflict(self, rel: str, base: str, ours: str) -> str | None:
        if "kg-recap-sid:" not in ours:
            return None
        merged = copy_session_blocks(base, ours, self._insert_before)
        if self._repo_root is not None and (self._repo_root / rel).resolve() == self._daily_path.resolve():
            # what this run wrote, applied again on top of the remote's note
            for replay in self._replays:
                merged = replay(merged)
        return merged

    def commit(self, marker_key: str) -> None:
        if self._repo_root is None:
            return
        commit_and_push(self._repo_root, self._daily_path, marker_key, self._resolve_conflict)
