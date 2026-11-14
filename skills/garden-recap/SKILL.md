---
name: garden-recap
description: Use when the user wants to wrap up the current Claude Code session by writing what was worked on to today's daily note in the vault, so the next session can pick up context. Drives recap.manual_recap to upsert the per-session Timeline recap block.
---

# Garden Recap (Session Wrap-up)

Capture the current session's work — what happened (Timeline) — into today's daily note. Designed to be invoked **before** the user ends a session so future sessions (today or later) can recover context without re-reading the entire transcript.

The normal path **drives the `recap.manual_recap` CLI** instead of hand-editing the daily note. The CLI reads this session's transcript and upserts a per-session `kg-recap-sid:{sid8}` block — a `### Timeline` the CLI replaces wholesale on each run — the SAME block the auto-recap hooks maintain. Manual and auto recaps therefore converge on one block per session.

## When to Use

- User says: "ここまで daily にまとめて" / "wrap up" / "今日の作業まとめて" / "recap this session" / "session を切る前に記録"
- About to switch tasks and want a clean handoff point
- End of a productive working block where context is worth preserving

## When NOT to Use

- A single durable insight needs capturing → `garden-plant` (atomic note, not daily journal entry)
- Updating a specific existing note → `garden-water`
- Just searching → `garden-survey`
- The session was trivial (read-only exploration, no outcomes): skip — don't pollute the daily note with empty recaps

## Process

The normal flow is three steps: resolve the daily note, preview, apply. The CLI finds the session's transcript, builds the Timeline from its tool calls, upserts the block and commits — this skill does NOT hand-edit the daily note in the normal path. (A recollection fallback is preserved under Step 2 for the case where the CLI finds nothing to read.)

### Step 1: Pre-flight Setup

Follow [Pre-flight Setup](../using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills) in `using-knowledge-gardener` to resolve `$KG_VAULT` and load vault conventions. Additionally read the **daily-note template** wherever the README points to it.

From the conventions + template, extract for this skill (at minimum):

- Where daily notes live (folder).
- How daily notes are named (filename convention).
- What the daily-note template looks like — sections, frontmatter, default tags.
- What language note bodies are written in.
- The vault's link syntax.

If any of these are not discoverable from the README or templates, stop and ask the user. Do not invent defaults.

Format today's date per the filename convention and build the absolute daily-note path under the daily-note folder. Hold onto this path — Step 2 / Step 3 pass it to the CLI as `--daily-path`. The CLI only **appends** the `kg-recap-sid` recap block; it does **not** seed the daily-note template. So if today's note does not exist yet, create it from the template first (Write tool) so it carries the vault's frontmatter/sections, then run the CLI.

### Step 2: Preview (Propose, Don't Commit)

With the daily-note path from Step 1, preview the upsert:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m recap.manual_recap \
  --daily-path <abs daily path> --dry-run
```

The CLI recaps the session it runs in: it takes the session id from `$CLAUDE_CODE_SESSION_ID`, finds that session's transcript under the Claude Code projects directory, and builds the Timeline from the tool calls recorded there (subagent calls included). You do not assemble it by hand. (To recap another session pass `--sid <session id or its first 8 characters>`; if the transcript lives somewhere unusual pass `--transcript <path>`. If you want a hand-authored, richer Timeline instead of the deterministic one, write it to a temp file and pass `--timeline-file` here and in Step 3 — rarely needed.)

`--dry-run` prints a unified diff of the daily note and writes nothing.

- Exit code **0** → show that diff to the user with the one-line rationale: "Capturing today's session into the per-session recap block so the next session can pick up context." Continue to **Step 3** on approval. Trigger phrases that count as implicit approval: "wrap up and write it" / "ここまでまとめて書いて".
- Exit code **3** (no transcript found, or no material tool calls today) or **2** with `CLAUDE_CODE_SESSION_ID unset` → the Timeline path cannot run; fall back to the **No-transcript fallback** below, then **STOP** (do not run `recap.manual_recap` again).

#### No-transcript fallback (recollection)

Only for the case where the CLI found nothing to read. This is the older free-form, template-driven recap: you hand-edit today's daily note from recollection + `git log`, exactly as before the Timeline CLI existed.

1. **Inventory from recollection + git** (don't make things up — only record what you can support from the conversation, file state, or `git log`):
   - **Time range**: session start (conversation start / the user's first substantive message) → `date` for "now".
   - **Outcomes**: what was decided / built / fixed / shipped this session? One sentence each.
   - **Files touched**: for each repo touched (identify from the conversation) run `git log --since='<session-start>' --oneline --author='<git user>'` (or `git log --since=<today-00:00> --oneline`); use `git diff --stat` for not-yet-committed work. Aggregate as a short list with one-line descriptions.
   - **New notes planted today**: query the vault for `date: <today>` frontmatter, or `git -C "$KG_VAULT/.." log --since=<today-00:00> --name-only`, to find newly-added notes.
   - **Decisions / principles surfaced** and **open follow-ups**: always from conversation context (the log records actions, not reasoning).
   - Cap each list to roughly the most-significant ~5 items. A recap is a summary, not a transcript.
2. **Locate today's daily note** (the path resolved in Step 1):
   - **Exists** → **append**. Read the file in full with the Read tool (not `Bash head/cat`, which doesn't count toward the Edit tool's per-file read tracking).
   - **Missing** → **new file**. Load the daily-note template as scaffold.
3. **Draft into the template's structure.** The daily-note template is the structure — fill each section it defines with content from your inventory. Don't invent sections it doesn't define. Write in the README's declared language and link syntax. For an append, do NOT overwrite earlier content: apply the README's multi-session convention if documented; otherwise integrate new bullets into the existing template sections without restructuring.
4. **Propose, don't commit.** Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit): show the target path, the diff (append) or full draft (new file), and the one-line rationale "Capturing today's session so the next one can pick up context." Trigger phrases "wrap up and write it" / "ここまでまとめて書いて" count as approval.
5. **Apply.** New note → **Write tool**; append → **Edit tool** (Read the file first; anchor on a stable template header rather than a long block markdownlint may have rewritten).
6. **Lint, commit, push.** Follow [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push). Subject: new note → `plant: <date> daily (session recap)`; append → `water: <date> daily session recap`. `<date>` matches the daily-note filename format. Don't `--no-verify`.

**Then STOP** — the fallback case is done here.

### Step 3: Apply on Approval

Re-run the SAME command **without** `--dry-run`:

```bash
PYTHONPATH="${CLAUDE_PLUGIN_ROOT}" python3 -m recap.manual_recap \
  --daily-path <abs daily path>
```

The CLI writes the Timeline block (replacing the Timeline section wholesale each run — the caller owns the full bullet list), commits (`water: <date> daily auto-recap (<sid8>)`), and records that the session is recapped up to now, so the next auto pass only adds what comes after. (`--timeline-file` is optional; omitting it falls back to the deterministic filtered timeline built from the transcript, as described in Step 2.)

Don't `--no-verify` and don't hand-edit the block afterward. If you need a different insertion point for a brand-new block, pass `--insert-before <heading>` (default appends at EOF); to write without committing, pass `--no-commit`.

## Edge Cases

- **No daily-note convention documented**: the vault README doesn't tell you where daily notes go or how they're named → stop and ask the user; do not invent a location.
- **Daily folder doesn't exist** (vault layout differs from expectation): stop and surface the gap. Suggest the user pick the correct folder or update the README.
- **Nothing to read** (the dry run exits 3, or 2 because the session id is unknown): take the **No-transcript fallback (recollection)** under Step 2, then stop. Don't try to force the CLI.
- **Block already exists for this session** (earlier manual recap, or an auto pass already ran): re-running is safe — the CLI replaces the Timeline wholesale with the freshly aggregated (or `--timeline-file`-authored) bullet list each time. Review the `--dry-run` diff before applying; if you authored a Timeline via `--timeline-file` earlier, re-pass it or that content is lost on the next run.
- **Session inventory turns up nothing meaningful**: tell the user "nothing significant to recap" rather than padding the daily note with filler. Better to skip than to write noise.
- **Pre-commit fails inside the CLI commit** (e.g. broken link in the Timeline): fix the link via `--timeline-file` and re-run Step 3. Don't `--no-verify`.

## Key Principles

- **Evidence over recollection.** "What happened" comes from the Timeline / `git log` / actual conversation, not paraphrased memory. The CLI's Timeline is built from the tool calls in the transcript, so the factual layer is mechanically grounded.
- **The CLI owns the whole Timeline, not just new bullets.** `upsert_session_block` replaces the `### Timeline` section wholesale on every run — the caller supplies the complete bullet list, not a delta. If you author a rich Timeline via `--timeline-file`, re-pass that file on every later run for the same session; omitting it lets the deterministic aggregation overwrite your authored content.
- **One block per session.** Manual and auto recaps target the same `kg-recap-sid:{sid8}` block, so a session never ends up with two competing recaps.
- **One commit per recap.** The CLI makes exactly one `water:` commit. The daily note may collect multiple sessions, but each recap is its own commit so history stays readable.
- **Future-you reads this.** Write the Timeline so that next session opens the daily note and immediately knows what happened today without re-reading the transcript.
- **Atomic, like the rest of the gardener.** Don't bundle "today's recap + tag fix + new permanent note" into one operation. Recap is one operation.
