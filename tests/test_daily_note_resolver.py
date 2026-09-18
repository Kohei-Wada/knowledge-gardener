"""Unit tests for the class-based internals of the auto_recap hook (split modules)."""
from __future__ import annotations

import json
import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from recap.autorecap import context as recap_context  # noqa: E402
from recap.autorecap import daily_note  # noqa: E402
from recap.autorecap import daily_note_resolver  # noqa: E402
from recap.autorecap import session_aggregator  # noqa: E402


def test_recap_context_from_hook_returns_none_when_env_unset(monkeypatch):
    monkeypatch.delenv("KG_AUTO_RECAP", raising=False)
    ctx = recap_context.RecapContext.from_hook('{"session_id": "abcd1234ef"}', dict_env={})
    assert ctx is None


def test_recap_context_from_hook_builds_facts(monkeypatch, tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    env = {"KG_AUTO_RECAP": "1", "KG_VAULT": str(vault)}
    ctx = recap_context.RecapContext.from_hook('{"session_id": "abcd1234efgh"}', dict_env=env)
    assert ctx is not None
    assert ctx.sid8 == "abcd1234"
    assert ctx.vault == vault
    assert len(ctx.today_str) == 10  # YYYY-MM-DD


def test_session_aggregator_returns_none_when_no_sessions(monkeypatch, tmp_path):
    monkeypatch.setattr(session_aggregator, "_run_aggregator_json", lambda sid8, since=None: None)
    ctx = recap_context.RecapContext(
        sid8="abcd1234", vault=tmp_path, today_str="2026-05-29", since=None, transcript_path=None
    )
    agg = session_aggregator.SessionAggregator(ctx).aggregate()
    assert agg is None


def test_session_aggregator_parses_window(monkeypatch, tmp_path):
    fake_session = {
        "first_hhmm": "09:00",
        "last_hhmm": "09:30",
        "entry_count": 5,
        "duration_min": 30,
        "durable_change": True,
        "timeline": ["- 09:00  Edit a.md", "- 09:30  Bash: git commit"],
    }
    monkeypatch.setattr(session_aggregator, "_run_aggregator_json", lambda sid8, since=None: fake_session)
    ctx = recap_context.RecapContext(
        sid8="abcd1234", vault=tmp_path, today_str="2026-05-29", since=None, transcript_path=None
    )
    agg = session_aggregator.SessionAggregator(ctx).aggregate()
    assert agg is not None
    assert agg.start_hhmm == "09:00"
    assert agg.end_hhmm == "09:30"
    assert agg.entry_count == 5
    assert agg.duration_min == 30
    assert agg.durable_change is True
    assert agg.timeline == ["- 09:00  Edit a.md", "- 09:30  Bash: git commit"]


def _ctx_with_vault(tmp_path):
    vault = tmp_path / "vault"
    (vault / "04_DailyNotes").mkdir(parents=True)
    ctx = recap_context.RecapContext(
        sid8="abcd1234", vault=vault, today_str="2026-05-29", since=None, transcript_path=None
    )
    return ctx, vault


def test_resolver_pre_resolve_hits_via_env(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.setenv("KG_DAILY_FOLDER", "04_DailyNotes")
    monkeypatch.setenv("KG_DAILY_FILENAME", "2026-05-29.md")
    r = daily_note_resolver.DailyNoteResolver(ctx)
    pre = r.pre_resolve()
    assert pre is not None
    assert pre.path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert r.pre_resolved is True


def test_resolver_pre_resolve_misses_without_env_or_cache(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.setattr(daily_note_resolver, "read_discovery_cache", lambda h: None)
    r = daily_note_resolver.DailyNoteResolver(ctx)
    assert r.pre_resolve() is None
    assert r.pre_resolved is False


def test_resolver_resolve_from_discovery(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    r = daily_note_resolver.DailyNoteResolver(ctx)
    claude_out = (
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "insert_before:\n"
        "<!-- /kg-discovery -->\n"
    )
    res = r.resolve_from_discovery(claude_out)
    assert res is not None
    assert res.path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert res.insert_before == ""


def test_resolver_persist_cache_writes_on_miss(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.setattr(daily_note_resolver, "read_discovery_cache", lambda h: None)
    monkeypatch.setattr(daily_note_resolver, "compute_readme_hash", lambda v: "deadbeef")
    written = {}
    monkeypatch.setattr(daily_note_resolver, "write_discovery_cache", lambda h, d: written.update({"hash": h, "discovery": d}))
    r = daily_note_resolver.DailyNoteResolver(ctx)
    r.pre_resolve()  # miss → pre_resolved False
    r.resolve_from_discovery(
        "<!-- kg-discovery -->\nfolder: 04_DailyNotes\nfilename: 2026-05-29.md\nfilename_pattern: {date}.md\n<!-- /kg-discovery -->\n"
    )
    r.persist_cache()
    assert written["hash"] == "deadbeef"
    assert written["discovery"]["folder"] == "04_DailyNotes"


def _apply(note, sid8="abcd1234", *, start="09:00", end="09:30",
           timeline=None, insert_before=""):
    return note.apply_block(
        sid8, start_hhmm=start, end_hhmm=end,
        timeline_bullets=timeline if timeline is not None else ["- 09:00  Edit a.md"],
        insert_before=insert_before,
    )


def test_daily_note_apply_block_writes_file(tmp_path):
    vault = tmp_path / "vault"
    folder = vault / "04_DailyNotes"
    folder.mkdir(parents=True)
    daily_path = folder / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path)
    changed = _apply(note)
    assert changed is True
    text = daily_path.read_text()
    assert "<!-- kg-recap-sid:abcd1234 -->" in text
    assert "### Timeline" in text
    assert "- 09:00  Edit a.md" in text
    assert "### KPT" not in text


def test_daily_note_apply_block_noop_when_identical(tmp_path):
    vault = tmp_path / "vault"
    folder = vault / "04_DailyNotes"
    folder.mkdir(parents=True)
    daily_path = folder / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path)
    # First apply creates the block; a second identical apply is a true no-op.
    assert _apply(note) is True
    assert _apply(note) is False


def test_daily_note_apply_block_cleans_tmp_on_replace_failure(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    folder = vault / "04_DailyNotes"
    folder.mkdir(parents=True)
    daily_path = folder / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path)

    def boom(src, dst):
        raise OSError("cross-device move")

    monkeypatch.setattr(daily_note.os, "replace", boom)
    assert _apply(note) is False
    assert not daily_path.exists()
    # the temp file must not be left behind in the vault
    assert list(folder.glob("*.tmp")) == []


def test_daily_note_has_repo_false_when_no_git(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    daily_path = vault / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path)
    assert note.has_repo is False


def test_resolver_persist_cache_noop_on_hit(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.setenv("KG_DAILY_FOLDER", "04_DailyNotes")
    monkeypatch.setenv("KG_DAILY_FILENAME", "2026-05-29.md")
    monkeypatch.setattr(daily_note_resolver, "compute_readme_hash", lambda v: "deadbeef")
    written = {}
    monkeypatch.setattr(daily_note_resolver, "write_discovery_cache", lambda h, d: written.update({"called": True}))
    r = daily_note_resolver.DailyNoteResolver(ctx)
    assert r.pre_resolve() is not None  # hit → pre_resolved True
    r.persist_cache()
    assert written == {}  # no write on the hit path


# --- daily-note template seeding -------------------------------------------


def _vault_with_template(tmp_path, body="---\ntitle: {{date}}\ndate: {{date}}\n---\n"):
    vault = tmp_path / "vault"
    (vault / "04_DailyNotes").mkdir(parents=True)
    tmpl = vault / "99_Templates" / "daily_note_template.md"
    tmpl.parent.mkdir(parents=True)
    tmpl.write_text(body, encoding="utf-8")
    return vault, tmpl


def test_daily_note_seeds_from_template_when_file_absent(tmp_path):
    vault, tmpl = _vault_with_template(tmp_path)
    daily_path = vault / "04_DailyNotes" / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path, template=tmpl, today_str="2026-05-29")
    assert _apply(note) is True
    text = daily_path.read_text()
    assert text.startswith("---\ntitle: 2026-05-29\ndate: 2026-05-29\n---\n")
    assert "<!-- kg-recap-sid:abcd1234 -->" in text


def test_daily_note_does_not_reseed_an_existing_file(tmp_path):
    vault, tmpl = _vault_with_template(tmp_path)
    daily_path = vault / "04_DailyNotes" / "2026-05-29.md"
    daily_path.write_text("## Session 08:00〜08:10\n", encoding="utf-8")
    note = daily_note.DailyNote(vault, daily_path, template=tmpl, today_str="2026-05-29")
    assert _apply(note) is True
    text = daily_path.read_text()
    assert "title: 2026-05-29" not in text
    assert text.startswith("## Session 08:00〜08:10\n")


def test_daily_note_falls_back_to_empty_seed_when_template_missing(tmp_path):
    vault, tmpl = _vault_with_template(tmp_path)
    tmpl.unlink()
    daily_path = vault / "04_DailyNotes" / "2026-05-29.md"
    note = daily_note.DailyNote(vault, daily_path, template=tmpl, today_str="2026-05-29")
    assert _apply(note) is True
    text = daily_path.read_text()
    assert "title:" not in text
    assert "<!-- kg-recap-sid:abcd1234 -->" in text


# --- template discovery -----------------------------------------------------


def test_parse_discovery_reads_template_key():
    d = daily_note_resolver.parse_discovery(
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "template: 99_Templates/daily_note_template.md\n"
        "<!-- /kg-discovery -->\n"
    )
    assert d["template"] == "99_Templates/daily_note_template.md"


def test_resolve_from_discovery_returns_template_path(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    tmpl = vault / "99_Templates" / "daily_note_template.md"
    tmpl.parent.mkdir(parents=True)
    tmpl.write_text("---\ndate: {{date}}\n---\n", encoding="utf-8")
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.delenv("KG_DAILY_TEMPLATE", raising=False)
    r = daily_note_resolver.DailyNoteResolver(ctx)
    target = r.resolve_from_discovery(
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "template: 99_Templates/daily_note_template.md\n"
        "<!-- /kg-discovery -->\n"
    )
    assert target is not None
    assert target.template == tmpl


def test_template_that_is_not_a_file_resolves_to_none(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.delenv("KG_DAILY_TEMPLATE", raising=False)
    r = daily_note_resolver.DailyNoteResolver(ctx)
    target = r.resolve_from_discovery(
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "template: 99_Templates/nope.md\n"
        "<!-- /kg-discovery -->\n"
    )
    assert target is not None
    assert target.template is None


def test_env_template_overrides_discovery(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    override = vault / "99_Templates" / "override.md"
    override.parent.mkdir(parents=True)
    override.write_text("x\n", encoding="utf-8")
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.setenv("KG_DAILY_TEMPLATE", "99_Templates/override.md")
    r = daily_note_resolver.DailyNoteResolver(ctx)
    target = r.resolve_from_discovery(
        "<!-- kg-discovery -->\n"
        "folder: 04_DailyNotes\n"
        "filename: 2026-05-29.md\n"
        "template: 99_Templates/daily_note_template.md\n"
        "<!-- /kg-discovery -->\n"
    )
    assert target is not None
    assert target.template == override


def test_pre_resolve_takes_template_from_cache(monkeypatch, tmp_path):
    ctx, vault = _ctx_with_vault(tmp_path)
    tmpl = vault / "99_Templates" / "daily_note_template.md"
    tmpl.parent.mkdir(parents=True)
    tmpl.write_text("---\ndate: {{date}}\n---\n", encoding="utf-8")
    monkeypatch.delenv("KG_DAILY_FOLDER", raising=False)
    monkeypatch.delenv("KG_DAILY_FILENAME", raising=False)
    monkeypatch.delenv("KG_DAILY_TEMPLATE", raising=False)
    monkeypatch.setattr(daily_note_resolver, "compute_readme_hash", lambda v: "deadbeef")
    monkeypatch.setattr(
        daily_note_resolver,
        "read_discovery_cache",
        lambda h: {
            "folder": "04_DailyNotes",
            "filename_pattern": "{date}.md",
            "insert_before": "",
            "template": "99_Templates/daily_note_template.md",
        },
    )
    r = daily_note_resolver.DailyNoteResolver(ctx)
    target = r.pre_resolve()
    assert target is not None
    assert target.path == vault / "04_DailyNotes" / "2026-05-29.md"
    assert target.template == tmpl


def test_discovery_cache_rejects_previous_schema_version(tmp_path, monkeypatch):
    """An entry written before the current key set must not be served.

    Tracks the constant rather than a literal: adding a discovery key leaves the
    README hash untouched, so bumping the schema is the only thing that retires
    entries predating the key.
    """
    cache = tmp_path / "cache.json"
    stale = json.dumps({
        "schema": daily_note_resolver._CACHE_SCHEMA_VERSION - 1,
        "readme_hash": "deadbeef",
        "folder": "04_DailyNotes",
        "filename_pattern": "{date}.md",
    })
    cache.write_text(stale, encoding="utf-8")
    monkeypatch.setattr(daily_note_resolver, "discovery_cache_path", lambda h: cache)
    assert daily_note_resolver.read_discovery_cache("deadbeef") is None


def test_discovery_cache_roundtrips_template(tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    monkeypatch.setattr(daily_note_resolver, "discovery_cache_path", lambda h: cache)
    daily_note_resolver.write_discovery_cache(
        "deadbeef",
        {
            "folder": "04_DailyNotes",
            "filename_pattern": "{date}.md",
            "template": "99_Templates/daily_note_template.md",
        },
    )
    got = daily_note_resolver.read_discovery_cache("deadbeef")
    assert got is not None
    assert got["template"] == "99_Templates/daily_note_template.md"
