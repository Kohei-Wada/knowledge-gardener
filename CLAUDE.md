# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

knowledge-gardener is a Claude Code skill library (plugin) that decides **when** to capture, update, link, or prune long-term knowledge in the user's external vault. It is intentionally **format-agnostic**: the vault's own README owns the "how" (note structure, filenames, link syntax, tags, folder layout); this plugin owns only the "when".

## Architecture

- **Plugin type**: Claude Code skill library (same pattern as [supernemawashi](https://github.com/Kohei-Wada/supernemawashi) and [superpowers](https://github.com/obra/superpowers))
- **Skills**: Markdown files in `skills/<skill-name>/SKILL.md` with YAML frontmatter
- **Hooks**:
  - `SessionStart` injects `using-knowledge-gardener` into every session
  - `PostToolUse` (Phase 1 of issue #1) runs `recap/capture/` to append a one-line evidence entry per material tool call to `$XDG_STATE_HOME/knowledge-gardener/sessions/<date>-<sid8>.log` — best-effort, never blocks Claude
  - `Stop` and `SessionEnd` (Phase 3 of issue #1, **opt-in via `KG_AUTO_RECAP=1`**; Stop registered with `async: true`) run `recap/autorecap/` to silently maintain one coalesced block per session (keyed by bare `kg-recap-sid:{sid8}`) in today's daily note, containing a single `### Timeline`. Work happens in **passes** (compose via headless `claude -p`, write, commit, push): the first substantive Stop runs one at once, later Stops at most once per `KG_RECAP_INTERVAL_MINUTES` (default 30) and only when the session log is newer than the last written pass, and `SessionEnd` (`recap.autorecap --final`, which detaches a worker and returns) runs the last one ignoring the interval. Between passes a Stop does nothing to the vault. A session is substantive once it produced a durable change (Edit/Write, git commit/push, Agent dispatch), OR tool-call count >= `KG_RECAP_MIN_CALLS` (default 5), OR duration >= `KG_RECAP_MIN_MINUTES` (default 5); a session that ends without becoming substantive gets the deterministic noise-filtered Timeline (StructuredOutput dropped, Web×N collapsed, read-only nav collapsed) from the final pass and spends no LLM call. Each compose call receives the Timeline already in the note and is asked to keep and extend it; a failed compose keeps the composed Timeline in the note, and the deterministic one is written only when there is no composed one to lose. Only the cold-cache case (no resolvable daily path) skips. The headless call is lean (`--safe-mode --tools "" --no-session-persistence --system-prompt … --model $KG_AUTO_RECAP_MODEL`, default `sonnet`) and runs with `KG_AUTO_RECAP=0` so it cannot recurse. See `docs/specs/2026-11-14-recap-throttle-design.md`. Fire-and-forget — Claude returns control to the user immediately while the recap composes in the background. Default-off so OSS installs don't surprise users with auto-commits. Since `v0.24.0` a daily note the hook creates is seeded from the vault's daily-note template (discovered as `template:` from the README, or `KG_DAILY_TEMPLATE`) with `{{date}}` substituted, so an auto-created note is not born without frontmatter; an existing note is never re-seeded. Since `v0.23.0` the heading names the writing machine (`## Session 11:27〜12:10  @mac` — short hostname, or `KG_RECAP_HOST`); the sid marker stays host-free because it is the upsert key and a host-qualified one would orphan existing blocks.
- **Vault location**: Resolved from `KG_VAULT` env var at runtime; not stored in this repo
- **Session log location**: `$XDG_STATE_HOME/knowledge-gardener/sessions/` (fallback `~/.local/state/`). Machine-local derived state, not vault content. `garden-recap` consumes these logs via `recap/aggregate/` since `v0.9.0` (Phase 2); falls back to recollection when no logs exist. Since `v0.10.0` (Phase 3) the `Stop` hook can silently auto-write the same recap when `KG_AUTO_RECAP=1` (orchestrator at `recap/autorecap/`). Since `v0.17.0`, the manual `garden-recap` skill reuses the same `kg-recap-sid` block via `recap.manual_recap` CLI (no headless claude — the CLI aggregates the deterministic Timeline itself; optionally overridden via `--timeline-file`), so manual wrap-ups coalesce with the auto block rather than creating a separate entry.

## Skills

The user-facing skill list (purposes, status) lives in [README.md](README.md#skills) — see it there to avoid drift. Maintainer-relevant detail:

- Entry point: `using-knowledge-gardener` (declares variables, the format contract, common workflow steps).
- Operational skills: `garden-plant` (C), `garden-survey` (R), `garden-water` (U), `garden-prune` (D), plus `garden-connect` (link edges), `garden-recap` (session wrap-up), and `garden-harvest` (publish knowledge into the blog repo via `KG_BLOG_REPO`; commit-not-push).
- Each operational SKILL.md references the canonical "Pre-flight Setup" and "Common Workflow Steps" sections inside `using-knowledge-gardener` rather than duplicating them.

## Key Conventions

- **Format-agnostic**: skills MUST read the vault's README for conventions before writing. Never hardcode filename rules, frontmatter schemas, link syntax, or folder layout in a skill.
- **Propose, don't commit by default**: writes are proposed and confirmed unless the user explicitly asked to save.
- **Vault path comes from env**: `KG_VAULT`. Skills must fail loudly if unset, not invent a default.
- **No vault data in this repo**: the user's knowledge stays on their machine. This repo ships only program (skills + hooks).
- All documentation and skill files are written in English.
