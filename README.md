# knowledge-gardener

A Claude Code plugin for **tending a long-term knowledge base** from inside your coding sessions.

## What It Does

Decides **when** to capture, update, link, or prune durable knowledge in your external vault (Obsidian, a plain markdown folder, anything with a README). Defers **how** — note format, filename rules, link syntax, frontmatter, folder layout — to the vault's own README. This separation is the whole point.

> The vault is the source of truth for **how**.
> This plugin is the source of truth for **when**.

## Why This Exists

Most "Obsidian-for-Claude" plugins hardcode a note format (PARA, Zettelkasten with Luhmann IDs, daily-note schemas, etc.). That makes them useful only if your vault matches the plugin's assumptions. The moment your vault has its own README spelling out conventions, those plugins fight you.

`knowledge-gardener` flips it: the **plugin reads your vault's README** before each operation and applies whatever conventions are documented there. Bring your own format.

## Installation

Inside Claude Code:

```
/plugin marketplace add Kohei-Wada/knowledge-gardener
/plugin install knowledge-gardener@knowledge-gardener
```

Set the vault path in your shell:

```bash
export KG_VAULT=~/path/to/your/vault
export KG_BLOG_REPO=~/path/to/your/blog/repo   # only needed for garden-harvest
```

Restart your Claude Code session.

### Vault Prerequisites

Your vault MUST have a `README.md` that documents at least:

- **Folder layout** — where do different kinds of notes go?
- **Filename rules** — kebab-case? Luhmann ID? date prefix?
- **Link syntax** — `[[wikilink]]`, `[md](rel-path.md)`, or both?
- **Frontmatter schema** — required fields, if any
- **Tag namespace** — any constraints

The README can live at either:

- `$KG_VAULT/README.md` — vault root (most specific, wins on conflict), or
- `$KG_VAULT/../README.md` — parent directory (common when the vault is a subdirectory of a git repo, e.g. `Obsidian/vault/`)

`garden-plant` reads both and merges; folder-scoped READMEs (e.g. `$KG_VAULT/06_People/README.md`) are also consulted when relevant.

If no README is found in either location, `garden-plant` will refuse to write and tell you what's missing. That's intentional: silent defaults are how vaults end up inconsistent.

## How It Works

1. **You converse with Claude as normal.**
2. **A durable insight surfaces** — a decision, a lesson, a workflow, a reference worth remembering.
3. **Claude proposes a note** — path, content, and rationale — formatted per your vault's README.
4. **You approve.** Claude writes the file. (Or skip the approval step by saying "save this to my vault".)
5. **You commit on your own cadence.** The plugin never auto-commits or pushes.

## What's Inside

### Skills

| Skill | What it does |
|-------|-------------|
| `using-knowledge-gardener` | Entry point — routes requests, declares the format contract |
| `garden-plant` | **(implemented)** Capture a new durable insight as a vault note |
| `garden-survey` | **(implemented)** Read-only search/listing primitive (text, tag, frontmatter, folder). Used directly and by other skills |
| `garden-water` | **(implemented)** Update an existing note — append content, add a link, fix a tag or frontmatter field. Minimal-diff edits |
| `garden-recap` | **(implemented)** Wrap up a session by writing what was worked on to today's daily note, so the next session can pick up context |
| `garden-connect` | **(implemented)** Link an existing MOC and an existing child note — atomic graph-edge insertion, bi-directional by default |
| `garden-prune` | **(implemented)** Remove a named note — archive by default (git mv into the vault's archive folder), hard-delete only on explicit request. Surfaces inbound-link warnings; cleanup goes through garden-water |
| `garden-harvest` | **(implemented)** Turn mature vault knowledge into a published blog post — gather permanent notes, shape in dialogue (no stored draft), mask PII, emit into the blog repo (`KG_BLOG_REPO`) per that repo's conventions; commits, never pushes |

### Session Capture (Phase 1)

Starting in `v0.8.0`, knowledge-gardener ships a `PostToolUse` hook that records a one-line evidence entry per material tool call to:

```
$XDG_STATE_HOME/knowledge-gardener/sessions/<YYYY-MM-DD>-<sid8>.log
```

Default location: `~/.local/state/knowledge-gardener/sessions/`. Modes `0700` (dir) / `0600` (file).

What gets recorded:

- File-mutating tools (`Edit`, `Write`, `NotebookEdit`)
- Non-trivial `Bash` (after stripping `cd <dir> &&` prefixes; trivial commands like `ls`, `pwd`, `cat`, `grep`, `rg`, `wc`, `sort`, `date`, etc. are filtered)
- `Agent` dispatches (subagent type + short description)
- `WebFetch` / `WebSearch` (URL or query)
- MCP tool calls (`mcp__<server>__<name>` + one identifying argument)

What is skipped:

- Read-only tools (`Read`, `ToolSearch`, `AskUserQuestion`, …)
- Internal task plumbing (`TodoWrite`, `TaskCreate`, `TaskUpdate`, …)
- Trivial shell commands

Privacy at the edge: `<private>...</private>` blocks and `<key>=<value>` shapes for `api_key` / `secret` / `token` / `password` / `auth` are replaced with `[REDACTED]` before any byte hits disk.

Since `v0.9.0`, `garden-recap` reads these logs via `recap/aggregate/` and uses them as the inventory source instead of relying solely on Claude's recollection. Falls back to recollection when no logs exist.

### Auto-Recap (Phase 3, opt-in)

`v0.10.0` adds a `Stop` hook that **silently writes today's session block to the daily note** with no user action. It is **opt-in via env var**:

```bash
export KG_AUTO_RECAP=1
# Optional explicit overrides — usually NOT needed. When unset, the daily
# folder / filename / insertion anchor are auto-discovered by Claude from
# the vault README at each Stop event.
export KG_DAILY_FOLDER='<folder-relative-to-KG_VAULT>'              # override discovery
export KG_DAILY_FILENAME='<filename for today, e.g. 2026-05-21.md>'  # override discovery
export KG_DAILY_INSERT_BEFORE='## <heading the block must precede>' # override discovery; default = append at EOF
# Substance gate — controls when the Timeline is regenerated by the LLM
export KG_RECAP_MIN_CALLS=5    # tool-call threshold (default 5)
export KG_RECAP_MIN_MINUTES=5  # duration threshold in minutes (default 5)
```

When set, every Claude "stop" event triggers `recap/autorecap/` which spawns headless `claude -p` with the session log + vault README. The script maintains **one coalesced block per session** (keyed by `kg-recap-sid:{sid8}`) in today's daily note, containing a single `### Timeline` — a mechanical activity log, upgraded to a readable one by the LLM on "substantive" Stops.

A Stop is substantive if it produced a durable change (Edit/Write, git commit/push, Agent dispatch), OR tool-call count >= `KG_RECAP_MIN_CALLS`, OR duration >= `KG_RECAP_MIN_MINUTES`. Non-substantive Stops write the deterministic Timeline only and spend no LLM call.

The script writes / updates the block in the daily note and `git commit && git push`. The `kg-discovery` block (naming the daily folder, today's filename, and optional insertion anchor) is derived from the vault README at each Stop event.

This is the **format-agnostic** path: the script never assumes folder names like `04_DailyNotes` — Claude reads the vault README at every Stop event and adapts. The env-var overrides exist for users who want to skip discovery or whose README doesn't document a daily-note convention. If both discovery and env are absent, auto-recap silently degrades to a no-op (it never guesses a folder).

The hook is registered with `async: true` so it runs fire-and-forget — Claude returns control to you immediately while the recap composes in the background (typically 10-60s). Failure modes (no claude binary, network error, malformed Claude output, etc.) all silently degrade. Diagnostics land in `~/.local/state/knowledge-gardener/auto-recap.log`.

Default-off so OSS installs don't surprise users with auto-commits to their vault. Single-user private vault: turn it on. Shared / public vault: leave it off and use `garden-recap` manually.

Spec: [`docs/specs/2026-05-18-session-capture-design.md`](docs/specs/2026-05-18-session-capture-design.md) (writer / Phase 1), [`docs/specs/2026-05-20-recap-aggregator-design.md`](docs/specs/2026-05-20-recap-aggregator-design.md) (consumer / Phase 2), [`docs/specs/2026-05-20-auto-recap-design.md`](docs/specs/2026-05-20-auto-recap-design.md) (auto-write / Phase 3).

### What Counts as "Durable"

`garden-plant` captures things like:

- Decisions and principles ("from now on we...", "the rule is...")
- Non-obvious conclusions reached after deliberation
- Reusable workflows, recipes, and configs
- Lessons learned from incidents or surprises
- Architectural choices with reasoning
- Pointers to external resources (dashboards, ticket systems)

It explicitly does **not** capture:

- Per-project task state (use Claude Code's built-in auto-memory)
- Per-person behavioral notes (use [supernemawashi](https://github.com/Kohei-Wada/supernemawashi))
- Conversation context or in-progress reasoning
- Anything already in the vault

## Philosophy

- **Format is data, not code.** Conventions live in the vault, not in the plugin. Change conventions → no plugin change needed.
- **Propose, don't commit.** The vault is your brain. Writes need consent.
- **Fail loudly on missing convention.** Better to stop and ask than to invent a default that drifts from the rest of the vault.
- **Never bypass vault lints.** If your vault has pre-commit checks, they win.
- **Atomic where the vault is atomic.** Mirror the vault's granularity instead of imposing one.

## Coexistence with Other Skill Libraries

| Library | Domain |
|---------|--------|
| [superpowers](https://github.com/obra/superpowers) | Software engineering workflows |
| [supernemawashi](https://github.com/Kohei-Wada/supernemawashi) | Interpersonal communication & per-person profiles |
| **knowledge-gardener** | Long-term, format-agnostic vault curation |
| Claude Code auto-memory | Per-project short-term memory |

They do not overlap. `knowledge-gardener` is specifically for knowledge that should outlive a single project or conversation.

## Requirements

- [Claude Code](https://claude.ai/code)
- A markdown vault (folder of `.md` files) with a `README.md` that documents its own conventions
- `KG_VAULT` env var set to the vault root

## Contributing

Issues and PRs welcome at [github.com/Kohei-Wada/knowledge-gardener](https://github.com/Kohei-Wada/knowledge-gardener).

## License

MIT
