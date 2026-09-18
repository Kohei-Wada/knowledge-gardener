from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import sys
import typing

from ..shared.fs import _resolve_under_vault
from ..shared.paths import discovery_cache_path
from ..shared.hook_io import log
from .context import RecapContext


class DailyTarget(typing.NamedTuple):
    """Everything the writer needs about today's daily note."""

    path: pathlib.Path
    insert_before: str
    template: pathlib.Path | None
    references_section: str = ""

# --- Discovery cache --------------------------------------------------------
#
# The vault README is the source of truth for daily-note folder/filename/etc.
# The auto-recap discovery step asks Claude to translate that README into
# concrete kg-discovery values on every Stop hook — but the README is stable
# across most sessions. We cache the discovery result keyed by a hash of the
# README content(s) so unchanged READMEs skip the discovery LLM work and the
# compose-only prompt can be used instead. README edits change the hash and
# naturally invalidate the cache; no TTL needed.
#
# Adding a discovery key does NOT change the README hash, so a machine keeps
# serving an entry written before the key existed and the new value stays
# empty forever — silently, on every machine but the one you tested on. Bump
# the schema whenever the set of keys changes; that forces exactly one fresh
# discovery per machine.
#   2 -> 3: references_section (v0.25.0)

_CACHE_SCHEMA_VERSION = 3
_FILENAME_DATE_PLACEHOLDER = "{date}"


def _read_readme_bytes(vault: pathlib.Path) -> bytes:
    """Concatenate $KG_VAULT/README.md and $KG_VAULT/../README.md (if present)."""
    parts: list[bytes] = []
    for candidate in (vault / "README.md", vault.parent / "README.md"):
        try:
            parts.append(candidate.read_bytes())
        except OSError:
            continue
        parts.append(b"\x00")  # separator so two empty files don't collide with one
    return b"".join(parts)


def compute_readme_hash(vault: pathlib.Path) -> str | None:
    """SHA-256 of the vault's README content(s). None if no README is readable."""
    data = _read_readme_bytes(vault)
    if not data:
        return None
    return hashlib.sha256(data).hexdigest()


def read_discovery_cache(readme_hash: str) -> dict[str, str] | None:
    """Return cached discovery values or None on miss / corruption.

    Only returns a dict when both `folder` and `filename_pattern` are present
    and non-empty (the minimum to skip the discovery LLM call). All other
    failure modes (missing file, JSON error, schema mismatch) return None so
    the caller falls back to the full discovery path.
    """
    path = discovery_cache_path(readme_hash)
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        log(f"discovery cache corrupted, ignoring: {path}")
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != _CACHE_SCHEMA_VERSION:
        return None
    if data.get("readme_hash") != readme_hash:
        return None
    folder = (data.get("folder") or "").strip()
    pattern = (data.get("filename_pattern") or "").strip()
    if not folder or not pattern:
        return None
    return {
        "folder": folder,
        "filename_pattern": pattern,
        "insert_before": (data.get("insert_before") or "").strip(),
        "template": (data.get("template") or "").strip(),
    }


def write_discovery_cache(readme_hash: str, discovery: dict[str, str]) -> None:
    """Persist discovery values for future cache hits. Best-effort."""
    folder = (discovery.get("folder") or "").strip()
    pattern = (discovery.get("filename_pattern") or "").strip()
    if not folder or not pattern:
        return  # nothing useful to cache
    payload = {
        "schema": _CACHE_SCHEMA_VERSION,
        "readme_hash": readme_hash,
        "folder": folder,
        "filename_pattern": pattern,
        "insert_before": (discovery.get("insert_before") or "").strip(),
        "template": (discovery.get("template") or "").strip(),
        "discovered_at": _dt.datetime.now().isoformat(timespec="seconds"),
    }
    path = discovery_cache_path(readme_hash)
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"discovery cache write failed: {e!r}")


def substitute_date(pattern: str, today_str: str) -> str:
    """Replace the literal {date} placeholder in a cached filename pattern."""
    if not pattern:
        return ""
    return pattern.replace(_FILENAME_DATE_PLACEHOLDER, today_str)


# --- end discovery cache ----------------------------------------------------


_DISCOVERY_BLOCK_RE = re.compile(
    r"<!--\s*kg-discovery\s*-->(.*?)<!--\s*/kg-discovery\s*-->",
    re.DOTALL | re.IGNORECASE,
)
_DISCOVERY_LINE_RE = re.compile(
    r"^\s*(folder|filename|filename_pattern|insert_before|template|references_section)\s*:\s*(.*?)\s*$",
    re.IGNORECASE,
)


def parse_discovery(claude_output: str) -> dict[str, str]:
    """Pull the kg-discovery block out of Claude's output as a dict.

    Returns {} on missing/malformed block. Keys present in the returned dict
    are exactly those Claude emitted with a non-empty value, lowercase.
    Supported keys: 'folder', 'filename', 'filename_pattern', 'insert_before',
    'template', 'references_section'.
    """
    m = _DISCOVERY_BLOCK_RE.search(claude_output)
    if not m:
        return {}
    out: dict[str, str] = {}
    for raw in m.group(1).splitlines():
        lm = _DISCOVERY_LINE_RE.match(raw)
        if not lm:
            continue
        key = lm.group(1).lower()
        val = lm.group(2).strip()
        if val:
            out[key] = val
    return out


def _validate_daily_path(
    vault: pathlib.Path, folder_raw: str, filename: str, *, context: str
) -> pathlib.Path | None:
    """Shared sanity checks for a resolved (folder, filename) pair.

    Logs the same diagnostic hint shape as the older inline version when a
    directory-tree-style README's vault-root node is mistakenly carried into
    the folder value. `context` distinguishes the call site in the log
    ("discovery" vs "pre-resolve") so the user can tell which path failed.
    """
    folder = _resolve_under_vault(vault, folder_raw)
    if folder is None or not filename:
        return None
    if not folder.is_dir():
        log(f"daily folder does not exist ({context}): {folder}")
        first = folder_raw.lstrip("/").split("/", 1)[0]
        if first and first == vault.name:
            log(
                f"hint: {context} folder {folder_raw!r} begins with the vault's "
                f"basename {vault.name!r}; discovery may have included a "
                f"directory-tree root node that already corresponds to $KG_VAULT"
            )
        return None
    if "/" in filename or filename.startswith("."):
        log(f"refusing suspicious daily filename ({context}): {filename!r}")
        return None
    return folder / filename


def resolve_template(vault: pathlib.Path, raw: str | None) -> pathlib.Path | None:
    """Resolve the seed template for a brand-new daily note.

    KG_DAILY_TEMPLATE overrides the discovered value. Anything that is not a
    readable file resolves to None, which makes seeding a no-op rather than an
    error — the recap block is always worth more than the frontmatter.
    """
    candidate = (os.environ.get("KG_DAILY_TEMPLATE") or raw or "").strip()
    path = _resolve_under_vault(vault, candidate)
    if path is None:
        return None
    if not path.is_file():
        log(f"daily template not a file, seeding disabled: {path}")
        return None
    return path


def resolve_daily_path(vault: pathlib.Path, discovery: dict[str, str]) -> DailyTarget | None:
    """Resolve today's daily note from env override or Claude discovery.

    Env precedence: KG_DAILY_FOLDER + KG_DAILY_FILENAME (if set) override
    Claude's discovery. When env is unset, discovery values are used. When
    neither yields a usable folder + filename, returns None (caller no-ops).
    """
    folder_raw = os.environ.get("KG_DAILY_FOLDER") or discovery.get("folder", "")
    filename = (os.environ.get("KG_DAILY_FILENAME") or discovery.get("filename") or "").strip()
    path = _validate_daily_path(vault, folder_raw, filename, context="discovery")
    if path is None:
        return None
    return DailyTarget(
        path=path,
        insert_before=discovery.get("insert_before", ""),
        template=resolve_template(vault, discovery.get("template")),
        references_section=discovery.get("references_section", ""),
    )


def pre_resolve_daily_path(
    vault: pathlib.Path,
    cached: dict[str, str] | None,
    today_str: str,
) -> DailyTarget | None:
    """Try to resolve today's daily note from env + discovery cache only.

    Returns a DailyTarget when both folder and filename can be determined
    without an LLM discovery call; returns None to signal the caller should
    fall back to the full discovery prompt.
    """
    env_folder = os.environ.get("KG_DAILY_FOLDER")
    env_filename = os.environ.get("KG_DAILY_FILENAME")
    env_insert = os.environ.get("KG_DAILY_INSERT_BEFORE")

    folder_raw = (env_folder or (cached.get("folder") if cached else "") or "").strip()
    if env_filename:
        filename = env_filename.strip()
    elif cached:
        filename = substitute_date(cached.get("filename_pattern", ""), today_str)
    else:
        filename = ""
    insert_before = (env_insert or (cached.get("insert_before") if cached else "") or "").strip()

    if not folder_raw or not filename:
        return None
    daily_path = _validate_daily_path(vault, folder_raw, filename, context="pre-resolve")
    if daily_path is None:
        return None
    return DailyTarget(
        path=daily_path,
        insert_before=insert_before,
        template=resolve_template(vault, cached.get("template") if cached else ""),
        references_section=(cached.get("references_section", "") if cached else ""),
    )


class DailyNoteResolver:
    def __init__(self, ctx: RecapContext) -> None:
        self._ctx = ctx
        self._readme_hash = compute_readme_hash(ctx.vault)
        self._cached = (
            read_discovery_cache(self._readme_hash) if self._readme_hash else None
        )
        self._discovery: dict[str, str] = {}
        self.pre_resolved = False

    def pre_resolve(self) -> DailyTarget | None:
        pre = pre_resolve_daily_path(self._ctx.vault, self._cached, self._ctx.today_str)
        self.pre_resolved = pre is not None
        return pre

    def resolve_from_discovery(self, claude_output: str) -> DailyTarget | None:
        self._discovery = parse_discovery(claude_output)
        target = resolve_daily_path(self._ctx.vault, self._discovery)
        if target is None:
            log("could not resolve daily-note path (no env override and no discovery from README)")
            return None
        return target

    def persist_cache(self) -> None:
        if (
            not self.pre_resolved
            and self._readme_hash
            and self._discovery.get("folder")
            and self._discovery.get("filename_pattern")
        ):
            write_discovery_cache(self._readme_hash, self._discovery)
