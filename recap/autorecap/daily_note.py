from __future__ import annotations

import datetime as _dt
import os
import pathlib
import subprocess

from ..shared.hook_io import log
from .block import upsert_session_block
from .references import upsert_references

_DATE_PLACEHOLDER = "{{date}}"


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
    code, _, err = run_git(
        ["commit", "-m", subject],
        repo_root,
    )
    if code != 0:
        log(f"git commit failed: {err[:200]!r}")
        return
    if os.environ.get("KG_AUTO_RECAP_NO_PUSH") == "1":
        log(f"push skipped (KG_AUTO_RECAP_NO_PUSH=1) for {today} {marker_key}")
        return
    code, _, err = run_git(["push"], repo_root)
    if code != 0:
        log(f"git push failed: {err[:200]!r}")


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
        new = upsert_session_block(
            existing, sid8, start_hhmm=start_hhmm, end_hhmm=end_hhmm,
            timeline_bullets=timeline_bullets, insert_before=insert_before,
        )
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
        new = upsert_references(existing, heading, note_rels, daily_rel_dir)
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

    def commit(self, marker_key: str) -> None:
        if self._repo_root is None:
            return
        commit_and_push(self._repo_root, self._daily_path, marker_key)
