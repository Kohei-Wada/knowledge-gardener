"""Convention documents: the vault READMEs plus the local docs they link to."""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from recap.autorecap import daily_note_resolver  # noqa: E402
from recap.autorecap.__main__ import load_vault_context  # noqa: E402
from recap.shared.conventions import convention_files  # noqa: E402


def _layout(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    vault = repo / "vault"
    (repo / "docs").mkdir(parents=True)
    vault.mkdir()
    return vault


def test_readmes_only_when_nothing_is_linked(tmp_path):
    vault = _layout(tmp_path)
    (vault / "README.md").write_text("# vault\n")
    (vault.parent / "README.md").write_text("# repo\n")
    assert convention_files(vault) == [vault / "README.md", vault.parent / "README.md"]


def test_follows_relative_md_links_one_hop(tmp_path):
    vault = _layout(tmp_path)
    docs = vault.parent / "docs"
    (vault.parent / "README.md").write_text(
        "See [daily](docs/daily-notes.md#sections) and [tags](./docs/tagging.md).\n"
        "Again [daily](docs/daily-notes.md).\n"
    )
    (docs / "daily-notes.md").write_text("Nested [x](nested.md).\n")
    (docs / "tagging.md").write_text("tags\n")
    (docs / "nested.md").write_text("nested\n")
    assert convention_files(vault) == [
        vault.parent / "README.md",
        docs / "daily-notes.md",
        docs / "tagging.md",
    ]


def test_skips_urls_missing_files_and_non_markdown(tmp_path):
    vault = _layout(tmp_path)
    docs = vault.parent / "docs"
    (docs / "vocab.txt").write_text("x\n")
    (vault.parent / "README.md").write_text(
        "[web](https://example.com/a.md) [gone](docs/gone.md) [txt](docs/vocab.txt)\n"
    )
    assert convention_files(vault) == [vault.parent / "README.md"]


def test_skips_links_outside_the_readme_directory(tmp_path):
    vault = _layout(tmp_path)
    (tmp_path / "outside.md").write_text("secret\n")
    (vault.parent / "README.md").write_text("[out](../outside.md)\n")
    assert convention_files(vault) == [vault.parent / "README.md"]


def test_linked_doc_is_part_of_the_vault_context(tmp_path):
    vault = _layout(tmp_path)
    (vault.parent / "README.md").write_text("[daily](docs/daily-notes.md)\n")
    (vault.parent / "docs" / "daily-notes.md").write_text("Daily notes live in `daily/`.\n")
    assert "Daily notes live in `daily/`." in load_vault_context(vault)


def test_editing_a_linked_doc_changes_the_cache_hash(tmp_path):
    vault = _layout(tmp_path)
    doc = vault.parent / "docs" / "daily-notes.md"
    (vault.parent / "README.md").write_text("[daily](docs/daily-notes.md)\n")
    doc.write_text("v1\n")
    before = daily_note_resolver.compute_readme_hash(vault)
    doc.write_text("v2\n")
    assert daily_note_resolver.compute_readme_hash(vault) != before
