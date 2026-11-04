"""Locate the documents that hold a vault's conventions.

The vault README (and its parent-directory README) may split conventions out
into local markdown docs it links to. Those docs are followed one hop, so a
README can stay an index without hiding rules from the auto-recap prompt.
"""
from __future__ import annotations

import pathlib
import re

_MD_LINK = re.compile(r"\]\(([^)\s#]+\.md)(?:#[^)\s]*)?\)")


def _readmes(vault: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in (vault / "README.md", vault.parent / "README.md") if p.is_file()]


def _linked_docs(readme: pathlib.Path) -> list[pathlib.Path]:
    try:
        text = readme.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    root = readme.parent.resolve()
    out: list[pathlib.Path] = []
    for target in _MD_LINK.findall(text):
        if "://" in target:
            continue
        path = (readme.parent / target).resolve()
        if path.is_file() and path.is_relative_to(root):
            out.append(path)
    return out


def convention_files(vault: pathlib.Path) -> list[pathlib.Path]:
    """READMEs first, then the local .md docs they link to, deduplicated."""
    readmes = _readmes(vault)
    seen = {p.resolve() for p in readmes}
    files = list(readmes)
    for readme in readmes:
        for doc in _linked_docs(readme):
            if doc not in seen:
                seen.add(doc)
                files.append(doc)
    return files
