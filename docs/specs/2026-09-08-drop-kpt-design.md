# Drop KPT — Timeline-Only Recap — Design

- **Date**: 2026-09-08
- **Status**: Draft
- **Target release**: knowledge-gardener v0.22.0
- **Prior art**: [2026-05-30-recap-session-coalesce-design.md](2026-05-30-recap-session-coalesce-design.md) (the two-layer block this removes a layer from), [2026-05-30-garden-recap-two-layer-alignment-design.md](2026-05-30-garden-recap-two-layer-alignment-design.md) (the manual path that also carries a KPT)

## Problem

The recap block has carried two layers since v0.16.0: a mechanical `### Timeline` and a transcript-grounded `### KPT` (Keep / Problem / Try). Production use since 2026-05 — with the layer switched off on 2026-06-27 and switched back on on 2026-07-20 — establishes that the KPT layer does not pay for itself.

Measured on the user's vault on 2026-09-08:

- **Volume**: 928 KPT bullets over 9 days (337 Keep / 308 Problem / 283 Try), ~103 per day.
- **Human consumption**: zero. The user's own assessment: never once obtained an insight from a KPT. An audit on 2026-06-27 reached the same conclusion independently — 85% of `Try` bullets were Todos that go stale immediately, 15% of `Problem` bullets were the agent's own operational mistakes, no insight that reaches a human.
- **Downstream use**: of 108 non-MOC permanent notes in the vault, 7 reference a daily note at all. The KPT → permanent-note path is effectively unused, while planting itself runs healthily (61 notes in 70 days) sourced from conversation rather than from recap.

The root cause is a gap in the output contract, not prompt quality. Neither `auto_recap_prompt.md` nor `auto_recap_compose_prompt.md` says **whose** behaviour Keep / Problem / Try describe. Given a transcript, the natural reading is the agent's own conduct during the session, and that is what gets written:

```text
- Keep: 自分の誤りを2件その場で認め、実測で洗い直して報告した
- Keep: 裏取り未了の3点を隠さず PR 本文に明記したまま出した
```

This is a performance review of the tool, addressed to nobody. Constraining the subject would not save the layer: a recap is written at the moment the user already knows everything in it, so its novel information content is zero at birth and only decays.

The `### Timeline` layer does not share this problem. It is a factual activity log, and it is what makes a daily note worth keeping — it was the basis for reconstructing nine days of work in the session that produced this spec.

## Goal

The recap block carries **one layer: `### Timeline`**. `### KPT` is removed from generation, from the block machinery, from both CLIs, and from the `garden-recap` skill.

Non-goals:

- **No replacement for the `Try` carry-over.** Its loss is the point. Carry-over Todos accumulated unread (the vault records "未実行3件・未捕捉6件" on 2026-09-06); moving them to a task record would relocate the problem rather than solve it.
- **No new interpretation layer** under a different name.

## Approach (chosen: remove, not repair)

Two alternatives were considered and rejected:

1. **Constrain the subject in the prompt** (keep the schema, add "the subject is the material, not Claude's own conduct"). Cheapest change, but leaves the zero-novelty problem untouched — the reader already knows what happened. Rejected.
2. **Drop `Keep` only**, keeping `Problem` / `Try`. Cuts a third of the volume and preserves the machine-readable issue list. Rejected because the same "already known / goes stale" argument applies to `Problem` and `Try`, and a half-measure would need revisiting.

Removal is chosen. The Timeline already carries the facts, and the `Problem`/`Try` value observed in practice — reconstructing what was being worked on — is recoverable from the Timeline plus `git log`.

## Design

### Session heading

`block.topic_from_kpt` derives the session heading's topic from the first `Keep:` bullet:

```python
"## Session 06:18〜06:28  憶測でなく pi 762リクエスト / Claude Cod"
```

With `Keep` gone there is no topic source. Deriving one from the first Timeline bullet was rejected: the first bullet is what happened first, not what the session was about (in the example above the subject is a request-count analysis performed in the last two minutes). A misleading heading is worse than none.

**Headings become the time range alone**: `## Session 06:18〜06:28`.

Consequence: `daily_note.build_commit_subject` already handles `topic is None` by falling back to `water: {today} daily auto-recap ({marker_key})`. Callers pass `None`; that legacy form becomes the only commit subject. No change to `build_commit_subject` itself.

### Block machinery (`recap/autorecap/block.py`)

Remove:

- `_KPT_RE`
- `extract_kpt_section()`
- `topic_from_kpt()`
- the `kpt_section` parameter of `_new_block()` and `upsert_session_block()`, and the replace/insert branch that consumes it
- the `topic` parameter of `_render_header()`, `_new_block()`, and `upsert_session_block()`

`_HEADER_RE` keeps its third capture group so existing headings with a topic still parse; on upsert the topic is dropped from the rewritten header. Existing notes are migrated separately (see below), so this only affects a block written before the upgrade and updated after it.

Spacing normalisation (`\n+(### )` → `\n\n\1`) stays — Timeline is still a `###` subheading.

### Prompts

Both prompts survive — they are the two path variants, not a Timeline one and a KPT one. `auto_recap_prompt.md` runs when the daily-note path is unknown and must be discovered from the vault README; `auto_recap_compose_prompt.md` runs on the warm-cache path where the path is already resolved. Each currently emits a Timeline **and** a KPT; each loses the KPT.

- `recap/autorecap/prompts/auto_recap_prompt.md` — the output contract emits the `kg-discovery` block followed by `### Timeline` only.
- `recap/autorecap/prompts/auto_recap_compose_prompt.md` — the output contract emits `### Timeline` only.

In both: the "How to revise the KPT" section, the KPT lines of the output contract, the per-category bullet cap, the `{{PRIOR_KPT}}` input, and the `{{DAILY_TEMPLATE}}` input (present only to convey the KPT structure) are removed. The Timeline rules and the facts-only rules are untouched.

### Auto-recap entry point (`recap/autorecap/__main__.py`)

Remove the `prior_kpt` extraction, the `PRIOR_KPT` and `DAILY_TEMPLATE` template variables (and the now-unused `load_vault_context` template return), the `extract_kpt_section` call on the model output and its "missing ### KPT" warning, and the `topic` local. `apply_block` and `commit` are called without `topic` / `kpt_section`.

The substance gate keeps its current meaning: it decides whether a Stop is substantive enough to invoke the model. With KPT gone it now gates Timeline regeneration only.

### Manual recap (`recap/manual_recap/__main__.py`)

`--kpt-file` is removed (it is currently `required=True`), along with its read, its empty check, and the `topic_from_kpt` call. The CLI upserts the Timeline for the session and commits.

This is a breaking CLI change. The only caller is `skills/garden-recap`, updated in the same change.

### Skill (`skills/garden-recap/SKILL.md`)

The flow drops from four steps to three: identify the session, preview, apply. "Step 3: Author the KPT" is removed, as are the `KPT_FILE` mktemp/Write instructions and the `--kpt-file` argument in both the dry-run and apply invocations. The "Key Principles" entries about authoring and preserving a KPT go with it.

### Package README

The "Substance gate" section describes the gate as controlling KPT regeneration. Reworded to Timeline regeneration; the two-layer description becomes one layer.

## Vault-side change (separate repository, separate PR)

`Kohei-Wada/Obsidian` declares the KPT contract and stores 149 daily notes that use it.

- `README.md` — the "Recap structure (KPT)" bullet is rewritten for a Timeline-only block. The rule that `Try` must never be omitted (`- (なし)`) is deleted.
- `vault/99_Templates/daily_note_template.md` — the `## KPT` section is removed.
- `vault/04_DailyNotes/*.md` — the `### KPT` section is stripped from all 149 notes.

The bulk strip runs as a script that prints a full diff first and is applied only after review. Git history retains the removed content. The vault's pre-commit hooks (markdownlint, lychee link check) must pass unmodified.

Ordering: knowledge-gardener ships first and is released; the vault change follows. Between the two, a daily note written by the new version simply has no KPT section while older notes still do — both are readable, so no flag day is required.

## Testing

`recap/` is covered by pytest. TDD: existing KPT assertions are inverted first (assert that no `### KPT` section is emitted, that `upsert_session_block` rejects an unexpected keyword), confirmed red, then the implementation removes the layer.

Specific coverage to keep or add:

- `upsert_session_block` remains **byte-idempotent** when re-applied with identical inputs.
- A block written by the previous version (Timeline + KPT + a topic in its heading) is upserted correctly: Timeline updated, heading rewritten without the topic. The stale KPT text is left in place rather than half-parsed — the vault-side migration removes it.
- Timeline append-with-dedup and the legacy `{sid8}-{HHMM}` non-collision guard are unaffected.
- `recap.manual_recap` runs without `--kpt-file` and fails cleanly if one is passed.

## Risks

- **Breaking CLI change** in `recap.manual_recap`. Contained: the sole caller is the skill in this repo, updated together.
- **Loss of the carry-over.** Accepted as the goal, and recorded in the vault as the vault note 「自分の振り返りは予定でなく問題で発火する」. The limitation that event-triggered review cannot catch problems that never announce themselves is addressed by monitoring, not by recap.
- **Irreversible vault edit.** Mitigated by the diff-then-apply script and by git history.
