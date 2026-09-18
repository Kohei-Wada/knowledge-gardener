"""Day-level "notes consulted today" section.

A session that reads a note in the vault consulted knowledge that already
existed. The created-notes section only covers notes born today, so a
procedure written three months ago and re-used today leaves no trace in the
journal. This section is that trace.

Mechanical by construction: the entries come from captured Read calls, never
from a judgement about what mattered. Anything whose link is already somewhere
in the note is skipped, which both de-duplicates across sessions and drops
notes today's created-notes section already lists.

The heading is not ours to choose — the vault README declares it, and with no
declaration nothing is written.
"""

from __future__ import annotations

import os
import pathlib
import re

# Machine-written sections go above the per-session logs; the first session
# block is the anchor, matched as either the marker or a bare heading.
_FIRST_BLOCK_RE = re.compile(r"^(<!--\s*kg-recap-sid:|## Session\b)", re.MULTILINE)


def link_for(note_rel: str, daily_rel_dir: str) -> str:
    """Markdown link target from the daily note's folder to a vault-relative note."""
    rel = os.path.relpath(note_rel, daily_rel_dir or ".")
    return rel.replace(os.sep, "/")


def _title_of(note_rel: str) -> str:
    return pathlib.PurePosixPath(note_rel).stem


def upsert_references(note_text: str, heading: str, note_rels: list[str],
                      daily_rel_dir: str) -> str:
    """Add a bullet per note under `heading`, creating the section if absent.

    Append-only: existing bullets are never reordered or removed, and a note
    whose link already appears anywhere in the text is not added again.
    """
    heading = heading.strip()
    if not heading or not note_rels:
        return note_text

    bullets = []
    for rel in note_rels:
        target = link_for(rel, daily_rel_dir)
        if f"]({target})" in note_text:
            continue
        bullets.append(f"- [{_title_of(rel)}]({target})")
    if not bullets:
        return note_text

    section_re = re.compile(
        rf"^{re.escape(heading)}[ \t]*\n(.*?)(?=^## |^<!-- kg-recap-sid:|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = section_re.search(note_text)
    if m:
        body = m.group(1).rstrip("\n")
        # a lone placeholder dash is replaced rather than left above real entries
        if body.strip() == "-":
            body = ""
        merged = "\n".join(filter(None, [body, "\n".join(bullets)]))
        return note_text[: m.start(1)] + merged + "\n\n" + note_text[m.end(1):]

    section = heading + "\n\n" + "\n".join(bullets) + "\n"
    anchor = _FIRST_BLOCK_RE.search(note_text)
    if anchor:
        return note_text[: anchor.start()] + section + "\n" + note_text[anchor.start():]
    sep = "" if note_text.endswith("\n") or not note_text else "\n"
    return note_text + sep + "\n" + section
