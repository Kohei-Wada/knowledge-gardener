from __future__ import annotations

import contextlib
import datetime as _dt
import io
import subprocess
from pathlib import Path

import pytest

from recap.manual_recap.__main__ import main


def _sessions(state: Path) -> Path:
    d = state / "knowledge-gardener" / "sessions"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_log(state: Path, sid: str, lines: list[str]) -> Path:
    today = _dt.date.today().isoformat()
    p = _sessions(state) / f"{today}-{sid}.log"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _setup(tmp_path: Path, monkeypatch, *, git: bool = False) -> tuple[Path, Path, Path]:
    vault = tmp_path / "vault"
    daily_folder = vault / "04_DailyNotes"
    daily_folder.mkdir(parents=True)
    daily_path = daily_folder / f"{_dt.date.today().isoformat()}.md"
    state = tmp_path / "state"
    monkeypatch.setenv("KG_VAULT", str(vault))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
    if git:
        for cmd in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"]):
            subprocess.run(["git", *cmd], cwd=vault, check=True)
        (vault / ".gitkeep").write_text("")
        subprocess.run(["git", "add", "-A"], cwd=vault, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=vault, check=True)
    return vault, daily_path, state


def test_create_block_when_absent(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily), "--no-commit"])
    assert rc == 0
    text = daily.read_text()
    assert "<!-- kg-recap-sid:manual01 -->" in text
    assert "### Timeline" in text
    assert "- 09:00  Edit a.md" in text
    assert (state / "knowledge-gardener" / "sessions" / "manual01.cursor").read_text().strip() == "09:05"


def test_updates_an_existing_pre_upgrade_block(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    daily.write_text(
        "<!-- kg-recap-sid:manual01 -->\n"
        "## Session 09:00〜09:00  auto topic\n\n"
        "### Timeline\n- 09:00  Bash: ls\n\n"
        "### KPT\n- Keep: auto が書いた\n"
        "<!-- /kg-recap-sid:manual01 -->\n",
        encoding="utf-8",
    )
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md", "09:30 tool=Write target=b.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily), "--no-commit"])
    assert rc == 0
    text = daily.read_text(encoding="utf-8")
    assert text.count("<!-- kg-recap-sid:manual01 -->") == 1
    assert "auto topic" not in text          # topic dropped on rewrite
    assert "- Keep: auto が書いた" in text    # stale KPT left for the vault migration


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--sid", "manual01", "--daily-path", str(daily), "--dry-run"])
    assert rc == 0
    out = buf.getvalue()
    assert "kg-recap-sid:manual01" in out
    assert "### Timeline" in out
    assert not daily.exists()
    assert not (state / "knowledge-gardener" / "sessions" / "manual01.cursor").exists()


def test_empty_session_returns_nonzero(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    rc = main(["--sid", "nolog999", "--daily-path", str(daily), "--no-commit"])
    assert rc == 3
    assert not daily.exists()


def test_legacy_hhmm_block_not_collided(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    daily.write_text(
        "<!-- kg-recap-sid:manual01-1400 -->\n## Session 14:00 〜 legacy\nbody\n"
        "<!-- /kg-recap-sid:manual01-1400 -->\n",
        encoding="utf-8",
    )
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily), "--no-commit"])
    assert rc == 0
    text = daily.read_text()
    assert "kg-recap-sid:manual01-1400" in text
    assert text.count("<!-- kg-recap-sid:manual01 -->") == 1


def test_no_kg_vault_returns_usage_error(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    monkeypatch.delenv("KG_VAULT", raising=False)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily), "--no-commit"])
    assert rc == 2


def test_commits_when_repo_and_not_no_commit(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch, git=True)
    monkeypatch.setenv("KG_AUTO_RECAP_NO_PUSH", "1")
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily)])
    assert rc == 0
    subj = subprocess.run(["git", "log", "-1", "--pretty=%s"], cwd=vault,
                          capture_output=True, text=True, check=True).stdout.strip()
    assert subj == f"water: {_dt.date.today().isoformat()} daily auto-recap (manual01)"


def test_authored_timeline_file_overrides_mechanical(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"])
    timeline_file = tmp_path / "timeline.md"
    timeline_file.write_text("### Timeline\n- 09:00–09:10 設計\n", encoding="utf-8")
    rc = main(["--sid", "manual01", "--daily-path", str(daily),
               "--timeline-file", str(timeline_file), "--no-commit"])
    assert rc == 0
    content = daily.read_text(encoding="utf-8")
    assert "- 09:00–09:10 設計" in content
    assert "Bash: git commit" not in content   # deterministic bullet replaced by authored timeline


def test_no_timeline_file_falls_back_to_deterministic(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    _write_log(state, "manual01", ["09:00 tool=Edit target=a.md"])
    rc = main(["--sid", "manual01", "--daily-path", str(daily), "--no-commit"])
    assert rc == 0
    content = daily.read_text(encoding="utf-8")
    assert "### Timeline" in content


def test_kpt_file_argument_is_rejected(tmp_path, monkeypatch):
    vault, daily, state = _setup(tmp_path, monkeypatch)
    with pytest.raises(SystemExit):
        main(["--sid", "manual01", "--daily-path", str(daily), "--kpt-file", "/nope"])
