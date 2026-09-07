"""Subprocess-based tests for recap/auto_recap.py.

These tests mock the headless `claude` binary via $KG_AUTO_RECAP_CLAUDE_CMD,
pointing it at a small shell script that prints a canned recap block. The
real Claude is never invoked.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# Neutral layout the test vault uses (created by make_vault). Names are
# intentionally generic — knowledge-gardener is format-agnostic, so the test
# vault must not assume any real-world vault's folder naming.
DAILY_FOLDER_REL = "daily"


def happy_env(vault: Path, fake_claude: Path) -> dict[str, str]:
    """Env vars needed for a happy-path auto-recap run against the test vault."""
    return {
        "KG_AUTO_RECAP": "1",
        "KG_VAULT": str(vault),
        "KG_AUTO_RECAP_CLAUDE_CMD": str(fake_claude),
        "KG_DAILY_FOLDER": DAILY_FOLDER_REL,
    }


def make_fake_claude(
    tmp_path: Path,
    output: str,
    exit_code: int = 0,
    sleep: float = 0.0,
    record_prompt_to: Path | None = None,
) -> Path:
    """Create a fake `claude` binary that ignores its args and prints `output`.

    When `record_prompt_to` is given, the script also writes stdin (the prompt
    that `auto_recap.py` pipes into `claude -p`) to that path so tests can
    assert which prompt template was used.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    script = tmp_path / "fake_claude.sh"
    body = "#!/usr/bin/env bash\n"
    if record_prompt_to is not None:
        body += f"cat > {record_prompt_to.as_posix()!r}\n"
    if sleep:
        body += f"sleep {sleep}\n"
    # use printf to preserve exact content
    body += "cat <<'KGEOF'\n" + output + "\nKGEOF\n"
    body += f"exit {exit_code}\n"
    script.write_text(body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return script


def make_vault(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Set up a minimal vault with README + daily-notes folder. Returns (vault, daily_folder, repo_root).

    Folder names here are deliberately neutral (no real-world vault layout
    references); auto-recap learns the layout from env vars (KG_DAILY_FOLDER)
    so it never needs to know names like '04_DailyNotes'.
    """
    repo = tmp_path / "vault-repo"
    vault = repo / "vault"
    daily = vault / DAILY_FOLDER_REL
    repo.mkdir()
    vault.mkdir()
    daily.mkdir()
    (vault / "README.md").write_text(
        textwrap.dedent(
            f"""\
            # Vault README

            ## Conventions
            - Daily notes live in `{DAILY_FOLDER_REL}/`, filename `YYYY-MM-DD.md`.
            """
        )
    )
    # git init so commit/push path is exercised (we'll skip push via env)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=repo, check=True)
    # initial commit so the working tree is well-formed
    (repo / ".gitkeep").write_text("")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
    return vault, daily, repo


def write_session_log(state_home: Path, sid8: str, lines: list[str]) -> Path:
    sessions = state_home / "knowledge-gardener" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    today = _dt.date.today().isoformat()
    p = sessions / f"{today}-{sid8}.log"
    p.write_text("\n".join(lines) + "\n")
    return p


def run_hook(payload: dict, *, env_extra: dict[str, str], state_home: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["XDG_STATE_HOME"] = str(state_home)
    env["HOME"] = str(state_home.parent / "fakehome")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    env["KG_AUTO_RECAP_NO_PUSH"] = "1"  # never push during tests
    env["PYTHONPATH"] = str(REPO_ROOT)
    for k, v in env_extra.items():
        env[k] = v
    return subprocess.run(
        [sys.executable, "-m", "recap.autorecap"],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        env=env,
        timeout=30,
        check=False,
    )


def assert_continue(stdout: str) -> None:
    obj = json.loads(stdout.strip().splitlines()[-1])
    assert obj.get("continue") is True
    assert obj.get("suppressOutput") is True


TIMELINE_BODY = "### Timeline\n\n- 11:00–11:05 a/b.py を編集\n"


def _canned_recap_with_discovery(folder=DAILY_FOLDER_REL, filename=None,
                               filename_pattern="{date}.md", insert_before=""):
    """Build a canned Claude output: kg-discovery block + ### Timeline section.

    The new (cold-cache) contract: Claude returns discovery metadata followed
    by a `### Timeline` activity log. Python assembles the block markers and
    header around them.
    """
    if filename is None:
        filename = f"{_dt.date.today().isoformat()}.md"
    return (
        "<!-- kg-discovery -->\n"
        f"folder: {folder}\nfilename: {filename}\n"
        f"filename_pattern: {filename_pattern}\ninsert_before: {insert_before}\n"
        "<!-- /kg-discovery -->\n" + TIMELINE_BODY
    )


def _canned_recap_timeline_only():
    """Canned output with NO kg-discovery block — the warm-cache compose path."""
    return TIMELINE_BODY


CANNED_RECAP = _canned_recap_with_discovery()


# --- opt-in gate -------------------------------------------------------------

def test_no_op_when_env_unset(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={"KG_VAULT": str(vault)},  # KG_AUTO_RECAP NOT set
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_no_vault(tmp_path):
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={"KG_AUTO_RECAP": "1"},  # KG_VAULT unset
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


def test_no_op_when_no_session_log(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    fake = make_fake_claude(tmp_path, CANNED_RECAP)
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


# --- discovery / env-var configuration --------------------------------------

def test_writes_via_discovery_when_env_unset(tmp_path):
    """With KG_DAILY_FOLDER unset, Claude's kg-discovery block drives the write."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    env = happy_env(vault, fake)
    # remove both env keys so only the kg-discovery block can resolve the path
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists(), "discovery-driven write should have created the daily note"


def test_no_op_when_env_unset_and_no_discovery(tmp_path):
    """No env override and no kg-discovery block → no-op (never guess a folder)."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap_timeline_only())
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_daily_folder_path_invalid(tmp_path):
    """When KG_DAILY_FOLDER points at a missing path, auto-recap degrades to no-op."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, CANNED_RECAP)
    env = happy_env(vault, fake)
    env["KG_DAILY_FOLDER"] = "nonexistent-folder"
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_logs_hint_when_discovery_prefixes_vault_basename(tmp_path):
    """When discovery emits folder=<vault.basename>/<sub>, log a diagnostic hint.

    Reproduces the failure mode where a tree-format README's top node (which
    represents the vault root itself) is mistakenly included as a path prefix,
    producing a doubled path that does not exist. Auto-recap stays a no-op,
    but the log gains a hint line so the user can clarify their README or
    the discovery prompt.
    """
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    bad_folder = f"{vault.name}/{DAILY_FOLDER_REL}"
    fake = make_fake_claude(
        tmp_path,
        _canned_recap_with_discovery(folder=bad_folder),
    )
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]  # force the discovery path
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()
    log_path = (
        tmp_path / "fakehome" / ".local" / "state" / "knowledge-gardener" / "auto-recap.log"
    )
    log_content = log_path.read_text(encoding="utf-8")
    assert "daily folder does not exist" in log_content
    assert "hint:" in log_content
    assert vault.name in log_content


def test_env_override_wins_over_discovery(tmp_path):
    """When both env KG_DAILY_FOLDER and kg-discovery folder are set, env wins."""
    vault, _, _ = make_vault(tmp_path)
    # second folder the env will point to (different from the one Claude discovers)
    alt = vault / "alt-daily"
    alt.mkdir()
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    # Claude discovers DAILY_FOLDER_REL ("daily") but env points at "alt-daily"
    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery(folder=DAILY_FOLDER_REL))
    env = happy_env(vault, fake)
    env["KG_DAILY_FOLDER"] = "alt-daily"
    # the discovery's filename still drives the filename (no KG_DAILY_FILENAME set)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    today = _dt.date.today().isoformat()
    assert (alt / f"{today}.md").exists(), "env override should have placed the note under alt-daily"
    assert not (vault / DAILY_FOLDER_REL / f"{today}.md").exists()


def test_insert_before_anchor_places_block_above_heading(tmp_path):
    """KG_DAILY_INSERT_BEFORE makes the recap block land above the named heading."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    today = _dt.date.today().isoformat()
    # pre-seed the daily note with a trailing section the anchor should land above
    (daily / f"{today}.md").write_text(
        "## Existing top\n\nsome body\n\n## Carry over\n\n- left for tomorrow\n",
        encoding="utf-8",
    )
    fake = make_fake_claude(tmp_path, _canned_recap_timeline_only())
    env = happy_env(vault, fake)
    # Pre-resolve the path (folder+filename) so the env insert_before anchor is
    # honoured via the warm path rather than discovery.
    env["KG_DAILY_FILENAME"] = f"{today}.md"
    env["KG_DAILY_INSERT_BEFORE"] = "## Carry over"
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    content = (daily / f"{today}.md").read_text(encoding="utf-8")
    block_idx = content.index("<!-- kg-recap-sid:testabcd -->")
    anchor_idx = content.index("## Carry over")
    assert block_idx < anchor_idx, "recap block should land before the anchor heading"
    assert "left for tomorrow" in content, "anchor section content must survive"


# --- happy path --------------------------------------------------------------

def test_writes_session_block_on_happy_path(tmp_path):
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd",
                      ["09:00 tool=Edit target=a.md", "09:05 tool=Bash target=git commit -m x"])
    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=happy_env(vault, fake), state_home=state)
    assert res.returncode == 0
    content = (daily / f"{_dt.date.today().isoformat()}.md").read_text()
    assert "<!-- kg-recap-sid:testabcd -->" in content
    assert "### Timeline" in content
    assert "11:00–11:05 a/b.py を編集" in content   # AI timeline upgraded from canned output
    assert "<!-- /kg-recap-sid:testabcd -->" in content


def test_idempotent_replaces_existing_block(tmp_path):
    """Two substantive runs over the SAME window (cursor + debounce cleared) →
    the AI Timeline is replaced, not duplicated."""
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake1 = make_fake_claude(tmp_path / "v1", _canned_recap_with_discovery())
    env = happy_env(vault, fake1)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)

    # second run with a different AI timeline but same sid → should REPLACE it
    timeline2 = "### Timeline\n\n- 11:00–11:05 更新後のタイムライン\n"
    updated = (
        "<!-- kg-discovery -->\n"
        f"folder: {DAILY_FOLDER_REL}\nfilename: {_dt.date.today().isoformat()}.md\n"
        "filename_pattern: {date}.md\ninsert_before: \n"
        "<!-- /kg-discovery -->\n" + timeline2
    )
    fake2 = make_fake_claude(tmp_path / "v2", updated)
    # bypass debounce by clearing marker; also clear cursor so the aggregator
    # re-processes the full log over the same window.
    sessions = state / "knowledge-gardener" / "sessions"
    (sessions / ".last-recap-testabcd").unlink(missing_ok=True)
    (sessions / "testabcd.cursor").unlink(missing_ok=True)

    env["KG_AUTO_RECAP_CLAUDE_CMD"] = str(fake2)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    content = (daily / f"{_dt.date.today().isoformat()}.md").read_text()
    # one block, second Timeline replaced the first, not duplicated
    assert content.count("<!-- kg-recap-sid:testabcd -->") == 1
    assert "更新後のタイムライン" in content
    assert "11:00–11:05 a/b.py を編集" not in content


# --- error handling ---------------------------------------------------------

def test_llm_success_uses_ai_timeline(tmp_path):
    """When the LLM returns a ### Timeline section, its bullets replace the
    deterministic timeline in the written block."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    today = _dt.date.today().isoformat()
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    # Canned output includes TIMELINE_BODY → AI timeline should be used.
    fake = make_fake_claude(tmp_path, TIMELINE_BODY)
    env = happy_env(vault, fake)
    env["KG_DAILY_FILENAME"] = f"{today}.md"
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    content = (daily / f"{today}.md").read_text()
    assert "11:00–11:05 a/b.py を編集" in content   # AI timeline used
    assert "### KPT" not in content


def test_llm_failure_writes_deterministic_timeline(tmp_path):
    """When the LLM fails but the daily path is pre-resolved, the deterministic
    Timeline is still written (no KPT on failure)."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    today = _dt.date.today().isoformat()
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, "", exit_code=2)
    env = happy_env(vault, fake)
    # Pre-resolve the daily path so the LLM failure does not block the write.
    env["KG_DAILY_FILENAME"] = f"{today}.md"
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    assert_continue(res.stdout)
    note = daily / f"{today}.md"
    assert note.exists()
    content = note.read_text()
    assert "### Timeline" in content      # deterministic timeline still written
    assert "a.md" in content             # deterministic timeline carries real bullets, not just a heading
    assert "### KPT" not in content       # no KPT on LLM failure


def test_no_op_when_claude_nonzero_exit(tmp_path):
    """LLM failure with NO pre-resolved path (cold-cache, no KG_DAILY_FILENAME) → no-op."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, "", exit_code=2)
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra=happy_env(vault, fake),  # happy_env has KG_DAILY_FOLDER but not KG_DAILY_FILENAME
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)
    today = _dt.date.today().isoformat()
    assert not (daily / f"{today}.md").exists()


def test_no_op_when_claude_binary_missing(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    res = run_hook(
        {"session_id": "testabcd-uuid"},
        env_extra={
            **happy_env(vault, Path("/nonexistent/path/to/claude")),
        },
        state_home=state,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


def test_malformed_stdin_does_not_crash(tmp_path):
    env = os.environ.copy()
    env["KG_AUTO_RECAP"] = "1"
    env["XDG_STATE_HOME"] = str(tmp_path / "state")
    env["HOME"] = str(tmp_path / "home")
    Path(env["HOME"]).mkdir(parents=True, exist_ok=True)
    env["PYTHONPATH"] = str(REPO_ROOT)
    res = subprocess.run(
        [sys.executable, "-m", "recap.autorecap"],
        input="not json {",
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
        check=False,
    )
    assert res.returncode == 0
    assert_continue(res.stdout)


# --- debounce ---------------------------------------------------------------

def test_debounce_skips_rapid_reinvocation(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    canned = _canned_recap_with_discovery()
    fake = make_fake_claude(tmp_path, canned)
    env = happy_env(vault, fake)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    today = _dt.date.today().isoformat()

    # immediate re-invocation → debounce should skip
    time.sleep(0.1)
    # alter the fake output so we can detect if it ran
    fake2 = make_fake_claude(tmp_path / "v2", canned.replace("a/b.py を編集", "should not appear"))
    env["KG_AUTO_RECAP_CLAUDE_CMD"] = str(fake2)
    run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)

    content = (daily / f"{today}.md").read_text()
    assert "should not appear" not in content
    assert "a/b.py を編集" in content


# --- git commit -------------------------------------------------------------

def test_commit_subject_uses_the_marker_key_form(tmp_path):
    """With no topic source left, every commit subject takes the legacy
    `water: {today} daily auto-recap ({marker_key})` form."""
    vault, daily, repo = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "subjfrm1"
    write_session_log(state, sid8, ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    run_hook(
        {"session_id": sid8 + "-uuid"},
        env_extra=happy_env(vault, fake),
        state_home=state,
    )
    proc = subprocess.run(
        ["git", "log", "-1", "--pretty=%s"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )
    today = _dt.date.today().isoformat()
    assert proc.stdout.strip() == f"water: {today} daily auto-recap ({sid8})"


# --- per-Stop block accumulation --------------------------------------------

def test_two_stops_coalesce_into_one_block(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "twostops"
    today = _dt.date.today()
    write_session_log(state, sid8, ["09:00 tool=Edit target=a.md"])
    fake1 = make_fake_claude(tmp_path / "f1", _canned_recap_with_discovery())
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake1), state_home=state)

    sessions = state / "knowledge-gardener" / "sessions"
    with (sessions / f"{today.isoformat()}-{sid8}.log").open("a") as fh:
        fh.write("10:30 tool=Edit target=b.md\n")
    (sessions / f".last-recap-{sid8}").unlink(missing_ok=True)
    fake2 = make_fake_claude(tmp_path / "f2", _canned_recap_timeline_only())
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake2), state_home=state)

    text = (daily / f"{today.isoformat()}.md").read_text()
    # One block (replace semantics): open + close markers appear exactly once each.
    assert text.count(f"<!-- kg-recap-sid:{sid8} -->") == 1
    assert text.count(f"<!-- /kg-recap-sid:{sid8} -->") == 1
    # Second stop's canned output has TIMELINE_BODY → AI timeline replaces deterministic;
    # the block carries the latest whole-session Timeline from the LLM output.
    assert "11:00–11:05 a/b.py を編集" in text
    assert "### KPT" not in text
    assert (sessions / f"{sid8}.cursor").read_text().strip() == "10:30"


def test_topicless_then_substantive_keeps_timeline(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "topicles"
    today = _dt.date.today()
    # warm path needs folder + filename resolved
    env_common = {"KG_DAILY_FILENAME": f"{today.isoformat()}.md"}
    # Stop 1: non-substantive (2 read-only calls) → Timeline-only, no topic, no claude
    write_session_log(state, sid8, ["09:00 tool=mcp__Notion__notion-fetch target=x",
                                    "09:00 tool=WebSearch target=y"])
    fake1 = make_fake_claude(tmp_path / "f1", "no timeline section here")
    run_hook({"session_id": sid8 + "-uuid"},
             env_extra={**happy_env(vault, fake1), **env_common}, state_home=state)
    note = daily / f"{today.isoformat()}.md"
    assert "### Timeline" in note.read_text()
    # Stop 2: substantive (Edit); must NOT eat the Timeline heading
    sessions = state / "knowledge-gardener" / "sessions"
    with (sessions / f"{today.isoformat()}-{sid8}.log").open("a") as fh:
        fh.write("10:00 tool=Edit target=a.md\n")
    (sessions / f".last-recap-{sid8}").unlink(missing_ok=True)
    fake2 = make_fake_claude(tmp_path / "f2", _canned_recap_timeline_only())
    run_hook({"session_id": sid8 + "-uuid"},
             env_extra={**happy_env(vault, fake2), **env_common}, state_home=state)
    text = note.read_text()
    assert "### Timeline" in text                         # heading survived the update
    # Second stop's canned output has TIMELINE_BODY → AI timeline replaces deterministic.
    assert "11:00–11:05 a/b.py を編集" in text
    assert "### KPT" not in text
    assert text.count(f"<!-- kg-recap-sid:{sid8} -->") == 1


def test_nonsubstantive_stop_appends_timeline_without_calling_claude(tmp_path):
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "readonly"
    today = _dt.date.today().isoformat()
    write_session_log(state, sid8,
                      ["09:00 tool=mcp__Notion__notion-fetch target=x",
                       "09:00 tool=WebSearch target=y"])
    fake = make_fake_claude(tmp_path, "SHOULD_NOT_APPEAR")
    env = happy_env(vault, fake)
    # A non-substantive window never spends an LLM discovery call, so it needs a
    # pre-resolved path (folder+filename) for the Timeline-only write to land.
    env["KG_DAILY_FILENAME"] = f"{today}.md"
    res = run_hook({"session_id": sid8 + "-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    note = daily / f"{today}.md"
    assert note.exists()
    content = note.read_text()
    assert "### Timeline" in content
    assert "SHOULD_NOT_APPEAR" not in content
    assert "### KPT" not in content


def test_rerun_same_window_is_idempotent(tmp_path):
    """Stop hook re-runs with no new activity → no duplicate marker in the daily."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "idemp012"
    today = _dt.date.today()

    write_session_log(state, sid8, ["11:00 tool=Edit target=c.md"])
    fake = make_fake_claude(tmp_path / "fake", _canned_recap_with_discovery())
    # First run.
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)
    # Clear debounce to force the second run through the pipeline.
    sessions = state / "knowledge-gardener" / "sessions"
    (sessions / f".last-recap-{sid8}").unlink(missing_ok=True)
    # Second run with no new log activity → cursor at 11:00 → aggregator
    # filters everything out → no-op. The daily must not gain a duplicate.
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)

    daily_path = daily / f"{today.isoformat()}.md"
    text = daily_path.read_text()
    # Bare marker appears exactly twice (one open + one close), not four.
    assert text.count(f"kg-recap-sid:{sid8}") == 2
    # AI timeline from canned output appears exactly once (idempotent replace).
    assert text.count("11:00–11:05 a/b.py を編集") == 1


# --- discovery cache --------------------------------------------------------


def _readme_hash_for(vault: Path) -> str:
    """Mirror auto_recap.compute_readme_hash for tests (stdlib only, no import)."""
    import hashlib
    parts: list[bytes] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        if candidate.is_file():
            parts.append(candidate.read_bytes())
            parts.append(b"\x00")
    return hashlib.sha256(b"".join(parts)).hexdigest()


def _cache_path_for(state_home: Path, readme_hash: str) -> Path:
    return state_home / "knowledge-gardener" / "discovery" / f"{readme_hash}.json"


def test_miss_path_writes_discovery_cache(tmp_path):
    """On a cache miss the full prompt is used and the resulting discovery is cached."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])
    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]  # force the discovery path
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0
    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists()

    cache_path = _cache_path_for(state, _readme_hash_for(vault))
    assert cache_path.is_file(), "discovery cache should be written on miss-path success"
    cached = json.loads(cache_path.read_text())
    assert cached["folder"] == DAILY_FOLDER_REL
    assert cached["filename_pattern"] == "{date}.md"
    assert cached["readme_hash"] == _readme_hash_for(vault)


def test_hit_path_uses_compose_only_prompt(tmp_path):
    """A pre-existing cache entry routes the hook through the compose-only prompt."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])

    # Pre-seed the cache so pre_resolve_daily_path succeeds without an LLM call.
    readme_hash = _readme_hash_for(vault)
    cache_path = _cache_path_for(state, readme_hash)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({
        "schema": 1,
        "readme_hash": readme_hash,
        "folder": DAILY_FOLDER_REL,
        "filename_pattern": "{date}.md",
        "insert_before": "",
        "discovered_at": "2026-01-01T00:00:00",
    }))

    # Compose-only fake: returns just a ### Timeline section, no kg-discovery metadata.
    recorded = tmp_path / "claude-prompt.txt"
    fake = make_fake_claude(
        tmp_path,
        _canned_recap_timeline_only(),
        record_prompt_to=recorded,
    )
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]  # would otherwise short-circuit before cache lookup
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0

    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists()

    prompt_text = recorded.read_text(encoding="utf-8")
    assert "## Discovery rules" not in prompt_text, (
        "compose-only prompt must not contain the discovery rules section"
    )
    assert "Vault README" not in prompt_text, (
        "compose-only prompt must not embed the vault README"
    )
    # The compose prompt no longer carries a marker; it carries the {{...}}-
    # substituted TODAY / TIMELINE / TRANSCRIPT_SLICE inputs (the reduced
    # placeholder set — no DAILY_TEMPLATE, PRIOR_KPT, or VAULT_README).
    assert "kg-recap-sid" not in prompt_text
    assert "- 09:00  Edit a.md" in prompt_text


def test_readme_change_invalidates_cache(tmp_path):
    """Editing the README produces a new hash; the old cache entry is bypassed."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])

    # Cache keyed by a stale hash (the README's current hash gets a different file).
    stale_hash = "0" * 64
    stale_cache = _cache_path_for(state, stale_hash)
    stale_cache.parent.mkdir(parents=True, exist_ok=True)
    stale_cache.write_text(json.dumps({
        "schema": 1,
        "readme_hash": stale_hash,
        "folder": "stale-folder",  # would resolve to a non-existent path
        "filename_pattern": "{date}.md",
        "insert_before": "",
        "discovered_at": "2026-01-01T00:00:00",
    }))

    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0

    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists(), "miss-path discovery should have written the daily note"
    fresh_cache = _cache_path_for(state, _readme_hash_for(vault))
    assert fresh_cache.is_file(), "a new cache entry keyed by the current README hash should exist"
    # Stale entry left in place — pruning stale hashes is out of scope; no harm done.
    assert stale_cache.is_file()


def test_corrupted_cache_falls_back_to_discovery(tmp_path):
    """A malformed cache JSON does not crash the hook; it falls back to the miss path."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    write_session_log(state, "testabcd", ["09:00 tool=Edit target=a.md"])

    cache_path = _cache_path_for(state, _readme_hash_for(vault))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text("{not json")

    fake = make_fake_claude(tmp_path, _canned_recap_with_discovery())
    env = happy_env(vault, fake)
    del env["KG_DAILY_FOLDER"]
    res = run_hook({"session_id": "testabcd-uuid"}, env_extra=env, state_home=state)
    assert res.returncode == 0

    today = _dt.date.today().isoformat()
    assert (daily / f"{today}.md").exists()
    # cache file was overwritten with a valid entry on the miss-path success
    cached = json.loads(cache_path.read_text())
    assert cached.get("readme_hash") == _readme_hash_for(vault)


# --- end discovery cache ----------------------------------------------------


def test_legacy_bare_sid_block_left_untouched(tmp_path):
    """A daily note that already contains a legacy <!-- kg-recap-sid:abc12345 --> block
    (without HHMM suffix) must not be matched, replaced, or collided with by the new code."""
    vault, daily, _ = make_vault(tmp_path)
    state = tmp_path / "state"
    sid8 = "leg00001"
    today = _dt.date.today()
    daily_path = daily / f"{today.isoformat()}.md"
    # Seed two legacy blocks:
    #  - a bare block under a DIFFERENT sid (must stay untouched), and
    #  - an HHMM-suffixed block under the SAME sid we're about to write under
    #    (the (?![-\w]) guard must not let the new bare marker collide with it).
    legacy_block = (
        "<!-- kg-recap-sid:oldlegcy -->\n"
        "## Session legacy 〜 do not touch\n"
        "legacy body\n"
        "<!-- /kg-recap-sid:oldlegcy -->\n"
        f"<!-- kg-recap-sid:{sid8}-1400 -->\n"
        "## Session 14:00 〜 legacy suffixed\n"
        "legacy suffixed body\n"
        f"<!-- /kg-recap-sid:{sid8}-1400 -->\n"
    )
    daily_path.write_text(legacy_block, encoding="utf-8")

    write_session_log(state, sid8, ["14:00 tool=Edit target=d.md"])
    fake = make_fake_claude(tmp_path / "fake", _canned_recap_with_discovery())
    run_hook({"session_id": sid8 + "-uuid"}, env_extra=happy_env(vault, fake), state_home=state)

    text = daily_path.read_text()
    assert "kg-recap-sid:oldlegcy" in text  # legacy (other sid) preserved
    assert f"kg-recap-sid:{sid8}-1400" in text  # legacy suffixed block preserved
    assert "legacy suffixed body" in text
    # the NEW bare-sid8 block is created beside the legacy suffixed one
    assert f"<!-- kg-recap-sid:{sid8} -->" in text
