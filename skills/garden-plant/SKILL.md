---
name: garden-plant
description: Use when a reusable insight, decision, lesson, or piece of durable knowledge surfaces in conversation and should be captured to the user's long-term vault - proposes a new note formatted per the vault's own README conventions
---

# Garden Plant (Capture)

Plant new knowledge in the user's vault. Decides **when** something is worth capturing and **proposes** a note. The vault's README decides **how** the note is structured.

## When to Use

Capture when the content is **durable, generalizable, and not already in the vault**:

- A decision or principle the user adopts ("from now on we...", "the rule is...", "I prefer X because Y")
- A non-obvious conclusion reached after deliberation
- A reusable workflow / process / recipe / config the user explains or develops
- A lesson learned from an incident, failure, or surprise
- An architectural choice with reasoning attached
- A pointer/reference the user calls out as worth remembering ("this dashboard is what oncall watches", "bugs go in Linear project FOO")
- The user explicitly says so: "vault に書いて", "メモっといて", "save this", "capture this", "remember this in my notes"

## When NOT to Use

Do **not** capture, and route elsewhere or do nothing:

| Content type | Where it belongs |
|--------------|------------------|
| Per-project context, "we're working on X right now" | auto-memory (`~/.claude/projects/<p>/memory/`) |
| Per-person behavioral data | supernemawashi profile |
| In-progress task state | TaskCreate / plan |
| Pure conversation context, scratch reasoning | nowhere — let it pass |
| Something already in the vault | skip (verify via search before writing) |
| Sensitive info user hasn't asked to save | skip — ask first if you think it's worth saving |

If unsure, **propose** before writing. Never write to the vault silently when the user hasn't explicitly asked.

## Process

### Step 1: Pre-flight Setup

Follow [Pre-flight Setup](../using-knowledge-gardener/SKILL.md#pre-flight-setup-shared-by-all-operational-skills) in `using-knowledge-gardener` to resolve `$KG_VAULT` and load vault conventions.

From the conventions, extract for this skill (don't invent any you can't find documented or modeled):

- Folder layout — where does this kind of note belong?
- Filename rules — kebab-case? Luhmann ID? date-prefix? something else?
- Frontmatter schema — required fields, allowed values
- Link syntax — `[[wikilink]]`, `[text](path.md)`, or both
- Tag namespace — what tags exist? are they constrained?
- Pre-commit / lint rules — anything the vault enforces (e.g. "no wikilinks", "all internal links must resolve")

### Step 2: Check for Duplicates

Before proposing a new note, look for existing coverage. **Prefer `garden-survey`** — it knows the vault's exclusion conventions, parses frontmatter for tags, and returns a stable structured format that's easy to act on. Pass it the candidate keywords and any obvious tag from your draft (e.g. `context/work`).

Inline fallback when `garden-survey` is not available:

```bash
# Substitute --exclude-dir with the vault's non-content folder names (read from the README).
grep -rli "<keyword>" "$KG_VAULT" --include='*.md' \
  --exclude-dir=<archive-folder> --exclude-dir=<templates-folder> --exclude-dir=<assets-folder>
```

If something close exists, **prefer routing to `garden-water` (update) over creating a duplicate** — surface the candidate to the user, then hand off to `garden-water` for the actual edit if they confirm.

### Step 3: Draft the Note

Compose the note **using the conventions extracted in Step 1**. The body itself should:

- Lead with the rule, fact, or decision in one sentence.
- For rules/decisions: include a **Why** line (motivation) and a **How to apply** line (when it kicks in). The "why" is what lets future-you judge edge cases.
- Cite sources when relevant — the conversation that produced it, an incident, a Slack message, a PR.
- Link to related existing notes per the vault's link syntax.
- Stay concise. Notes age; bloat ages worse.

### Step 4: Propose, Don't Commit

Follow [Common: Propose, Don't Commit](../using-knowledge-gardener/SKILL.md#common-propose-dont-commit). For this skill, show:

1. The proposed path (e.g. `$KG_VAULT/principles/use-real-db-in-tests.md`).
2. The full note content.
3. A one-line rationale: "Capturing because this looks like a durable principle, not project-scoped."

Trigger phrases that count as implicit approval: "save this to my vault" / "vault に書いといて" / "メモっといて".

### Step 5: Write the Note

After approval, write the file to the proposed path.

### Step 6: Lint, Commit, Push

Follow [Common: Lint, Commit, Push](../using-knowledge-gardener/SKILL.md#common-lint-commit-push). Commit subject verb for this skill: `plant:`. See examples below.

### Commit Subject Examples

| Operation | Commit subject |
|-----------|----------------|
| New reference note | `plant: sqlite3-csv-import 手順を整理` |
| New permanent note | `plant: 冗長性ゼロのデータは圧縮できない` |
| New MOC | `plant: ssh-MOC` |
| New note split from one insight | `plant: rsync --delete の事故パターン` |

Keep the subject under ~60 chars; put detail in the commit body if needed.

## Edge Cases

- **No README found anywhere** (`$KG_VAULT/README.md` and `$KG_VAULT/../README.md` both missing): stop. Tell the user "no README found at `$KG_VAULT/README.md` or its parent — knowledge-gardener needs the vault to document its own conventions before it can write notes safely". Offer to help author a minimal README if they want.
- **README is empty / has no convention info**: same as above. Don't paper over with defaults.
- **User wants to capture but vault has lint that would reject the draft**: surface the lint failure in the proposal and offer a fixed version, don't bypass.
- **Multiple files seem like the right home** (e.g. `principles/` vs `lessons/`): ask which.
- **Insight spans multiple atomic ideas**: propose splitting into atomic notes (per Zettelkasten norms) only if the vault README endorses atomicity. Otherwise mirror the vault's actual granularity.

## Key Principles

- **Format from vault, never from this skill.** If you find yourself writing a default filename pattern or a default frontmatter schema in this skill, that's the bug. Read the README again.
- **Propose by default, write on confirmation.** The vault is the user's brain. Don't write to it without consent.
- **One atomic idea per note, if the vault's conventions agree.** Don't pile multiple insights into one file just because they came from one conversation.
- **Quote the path.** Always show the absolute or `$KG_VAULT`-relative path so the user can open it themselves.
- **Never bypass vault lints / pre-commit checks.** They exist for a reason. If they reject, fix the note.
