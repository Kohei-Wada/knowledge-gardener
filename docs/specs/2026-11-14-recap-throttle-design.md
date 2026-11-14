# Auto-Recap Pass Schedule — Design

- **Date**: 2026-11-14
- **Status**: Implemented
- **Prior art**: [2026-05-20-auto-recap-design.md](2026-05-20-auto-recap-design.md) (the Stop hook this reschedules), [2026-05-30-recap-session-coalesce-design.md](2026-05-30-recap-session-coalesce-design.md) (one block per session)

## Problem

The Stop hook did the whole job — compose with headless `claude -p`, write, commit, push — on almost every Stop. Measured on the user's machines, 2026-11-01 to 2026-11-14:

- 961 headless calls on one machine, about 44k input tokens each for about 1k of output. On a second machine: 357 calls, median 41.5k input tokens.
- 2,344 of the vault's 2,409 commits were auto-recap commits, each with its own push.
- 4,890 of 5,328 transcripts under `~/.claude/projects` were these headless sessions.
- `auto-recap.log` held 802 `git commit failed ... (no files to check)` lines.

Causes:

1. **The gate judged the whole session.** After one Edit or five tool calls every later Stop was "substantive" and called the LLM. The only brake was a 60 s debounce.
2. **Each call regenerated the whole Timeline from a partial view.** It received the transcript since the cursor only, so earlier bullets were rebuilt from the mechanical log and lost their "why".
3. **`claude -p` started with the user's full setup**: plugins, SessionStart injections, MCP servers, tools, CLAUDE.md. A prompt of `Reply with exactly: OK` cost 37.7k input tokens.
4. **A Stop with nothing new still tried to commit.** The vault's pre-commit hook runs `markdownlint --fix`, which inserts a blank line after `### Timeline`. The committed note therefore differs from what `upsert_session_block` renders, so a Stop with no new activity rewrote the raw block, the fixer restored the committed text, and `git commit` found nothing to commit. Reproduced in a scratch vault with the released code.

## Goal

A session costs a handful of LLM calls and commits, not one per Stop, and the Timeline keeps what earlier passes wrote.

## Design

### Passes

A **pass** composes (LLM), writes the block, commits and pushes. Nothing else touches the vault.

| Trigger | Runs a pass when |
| --- | --- |
| `Stop` | the session is substantive, has activity no block covers, and no pass started within `KG_RECAP_INTERVAL_MINUTES` (default 30) |
| `SessionEnd` | the session has activity no block covers (the interval is ignored) |

- A non-substantive Stop returns without marking the throttle, so the first substantive Stop writes at once.
- A session that ends without becoming substantive gets the mechanical Timeline from the final pass, without an LLM call. Before this change every non-substantive Stop wrote and committed it.
- The 60 s debounce is gone; the interval replaces it.

State, per session, under `$XDG_STATE_HOME/knowledge-gardener/sessions/`:

- `.last-recap-<sid8>` — mtime is when the last pass **started**. Throttles Stop passes, including failed ones, so a broken `claude` is not retried on every Stop.
- `<sid8>.cursor` — the last `HH:MM` a written block covers; its mtime is back-dated to when that pass read the log. A session log newer than it has uncovered activity. Kept apart from the throttle marker on purpose: a Stop pass that is killed mid-flight has marked the throttle but covered nothing, and the final pass must still run.
- `.recap-<sid8>.lock` — `flock`. A Stop pass that finds it held gives up; the final pass waits, so it composes on top of what the in-flight pass wrote.

### SessionEnd

Measured on Claude Code 2.1.318 with a probe plugin (a hook that logs its payload and detaches a child that writes again after 8–20 s):

| Exit | SessionEnd fires | `reason` | Detached child survives |
| --- | --- | --- | --- |
| `/exit` | yes | `prompt_input_exit` | yes |
| Ctrl-D twice | yes | `prompt_input_exit` | yes |
| `/clear` | yes, for the old session id | `clear` | yes |
| closing the terminal pane or workspace (herdr) | yes | `other` | yes |
| `kill -TERM`, `kill -INT` | yes | `other` | yes |
| `kill -HUP` | yes in 3 of 4 runs | `other` | yes |
| `kill -KILL` | no | — | — |

The payload carries `session_id` and `transcript_path`. The hook's budget is about 1.5 s, so `recap.autorecap --final` only starts `recap.autorecap --final-worker` in a new session (`setsid`) with the payload on stdin and returns.

Closing a pane fires the hook, so there is no catch-up path for sessions that ended without one. `kill -9` and crashes lose the activity after the last pass unless the session is resumed the same day.

### Previous Timeline in the prompt

The compose prompt gets `{{PREVIOUS_TIMELINE}}`: the bullets the note holds for this session. The mechanical Timeline and the transcript are then cut to the new slice (from the cursor minute on; the minute itself is repeated rather than risk losing turns that landed in it after the pass). The model is told to carry earlier bullets over and extend them.

When the note has no block yet — first pass, new day, cold discovery cache — the whole session's mechanical Timeline and the whole day's transcript are sent, as before.

A mechanical Timeline replaces what is in the note only when there is nothing composed to lose: no block yet, or a block whose bullets are all mechanical ones. A failed compose on a later pass keeps the note as it is and leaves the cursor alone, so the next pass retries the same slice.

### Lean headless call

Input tokens for `Reply with exactly: OK`, `usage` from `--output-format json`, OAuth login:

| Flags | Input tokens |
| --- | --- |
| none (before) | 37,700 |
| `--model sonnet` | 37,541 |
| `--strict-mcp-config` | 33,799 |
| `--disable-slash-commands` | 32,881 |
| `--setting-sources ""` | 31,713 |
| `--system-prompt …` | 35,116 |
| `--tools ""` | 71,540 |
| `--tools "" --strict-mcp-config --disable-slash-commands --system-prompt … --setting-sources ""` | 4,888 |
| `--safe-mode` | 16,975 |
| `--safe-mode --tools "" --system-prompt …` | **567** |
| `--bare` | fails: `Not logged in` |

Adding `--strict-mcp-config`, `--disable-slash-commands` or `--setting-sources ""` to the `--safe-mode` set changes nothing, so they are left out. `--no-session-persistence` is added so the calls stop piling up as transcripts. The child runs with `KG_AUTO_RECAP=0`; under `--safe-mode` its hooks do not run anyway.

Real calls against a scratch vault: 2,787 input tokens for a first pass with README discovery, 1,546–1,794 for compose passes, against 37,273 for the same kind of pass with the released code.

`KG_AUTO_RECAP_MODEL` picks the model, default `sonnet`: the task is a short summary, and the calls used to inherit the session's default model (Opus in the measurements above).

### No empty commits

`commit_and_push` stops after `git add` when the note has no staged change against `HEAD`.

## Not changed

- Day rollover: a pass only looks at today's session log, so activity between the last pass and midnight is not recapped if the session ends the next day.
- The README-driven daily-note discovery.
