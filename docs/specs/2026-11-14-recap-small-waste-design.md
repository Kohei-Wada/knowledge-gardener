# Auto-Recap: Bugs and Small Waste — Design

- **Date**: 2026-11-14
- **Status**: Implemented
- **Prior art**: [2026-11-14-recap-throttle-design.md](2026-11-14-recap-throttle-design.md)

Four small defects found while reading the auto-recap source for the pass schedule.

## 1. The discovery cache dropped `references_section`

`parse_discovery` reads `references_section` and `pre_resolve_daily_path` looks it up in the cached entry, but `write_discovery_cache` never stored it and `read_discovery_cache` never returned it. The "notes consulted today" section was therefore written only by the one pass that ran discovery, and never again until the README changed.

Both functions now carry the key. `_CACHE_SCHEMA_VERSION` goes 3 → 4, so each machine runs discovery once more and caches the heading.

## 2. The aggregator ran as a subprocess

`SessionAggregator` ran `python -m recap.aggregate --json` and parsed its stdout, while `recap.manual_recap` imports `aggregate_session` from the same module. `SessionAggregator` now calls it directly. The `recap.aggregate` CLI is unchanged.

## 3. `{{EXISTING_DAILY}}` was read for nothing

The compose prompt has no `{{EXISTING_DAILY}}` placeholder, yet every pass read the whole daily note for it. The discovery prompt has the placeholder, but on that path the note's location is not known yet, so it always received `(file does not exist yet)`. The substitution and the discovery prompt's section are removed. The README is likewise loaded only for the discovery prompt, the only one that embeds it.

## 4. Two rules for the state directory

`shared/paths` honours `XDG_STATE_HOME`; `shared/hook_io.LOG_FILE` was fixed to `~/.local/state` at import time. `auto-recap.log` now lives in `kg_state_dir()` with the session logs. On a machine that sets `XDG_STATE_HOME` the log moves there; the old file is left where it is.
