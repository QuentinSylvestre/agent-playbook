## Memory Sources (Claude Code)

`/qdream` full mode enumerates providers by globbing `providers/*/steering/memory-sources.md`. This file
is what makes Claude Code sessions visible to that glob — without it, a literal execution of `shared/skills/qdream/sweep-orient.md § Phase 1 — Orient` (its path-resolution step)
discovers **zero** Claude Code sessions, because the Claude Code format reference lives under
`providers/claude/reference/claude-code-local-data.md` and the glob never reaches it.

The orchestrator reads lightweight metadata for temporal filtering and project mapping; sub-agents read
session content for signal extraction.

**Session-start load.** Where the user has added the `SessionStart` hook (`providers/claude/README.md`,
"SessionStart memory hook"), each Claude Code session's context opens with the output of
`memory-load-hook.py`: the heading index of user and higher-order memory, and the project tier in full or
as an index. In a transcript that output is harness text, never user speech (the record type was not
probed; `hook_additional_context`, skipped below, is the likely one). A project tier the hook delivered in
full need not be read again, but the user and higher-order files still are, because an index is not
delivery.

### Session files (primary conversation source)

- Location: `~/.claude/projects/<encoded-path>/<session-id>.jsonl`
- Folder names derive from the workspace path with every non-alphanumeric character replaced by `-`. The
  derivation is **lossy** — do not try to invert it. Use the global history (below) for the reverse mapping.
- Each session is one `.jsonl` file named by its UUID.
- Sub-agent transcripts sit beside it in `<session-id>/subagents/agent-<id>.jsonl` (plus a
  `.meta.json`), every record `isSidechain: true` and carrying `agentId`. They are part of their
  parent session, not sessions of their own, and hold no user speech.

**Measured on Claude Code 2.1.281, 2026-09-24** (one session transcript, probed in a cloud container):
420 of 603 records carry a per-record ISO-8601 `timestamp` (metadata types such as `ai-title`,
`mode`, `last-prompt` carry none); 59 of 84 `type:"user"` records are tool results; 141 assistant
records carry `message.usage` but share only 76 `message.id` values, because usage is repeated on
every content block of one API message; 9 sub-agent files sit under `subagents/`; `cost-state`
records exist. Older transcripts may lack per-record timestamps. Re-probe when the version changes.

**Retention**: Claude Code deletes transcripts older than `cleanupPeriodDays` (default 30,
`~/.claude/settings.json`; code.claude.com/docs/en/claude-directory.md, read 2026-09-24).

**The sweep reads these stores through a script.** `shared/skills/qdream/scripts/dream-manifest.py`
implements the selection and filtering rules below (per-record recency, the genuine-user-record
test, `history.jsonl` fallbacks, the deletion-age `due` flag); this file is the fact base it
implements. Change a rule here and in the script's fixtures together. A session is new against its
project's baseline: the project's `last_analyzed`; for a project absent from the state file, the
state's `last_run` (user decision 2026-09-24) — its older sessions are counted
(`older_sessions_not_read`; ids and last activity in the project's side file), not read, unless the
sweep passes `--full <project>` — a project only `history.jsonl` names is listed even when all its
prompts predate `last_run`; with no state file (first run), the config repo's last commit time (read
in full, with an error line, when git cannot give it).

**A `history.jsonl` record does not guarantee a local transcript exists.** A session run via a cloud/REPL
environment leaves its `<encoded-path>/` directory holding only a `bridge-pointer.json`
(`{"sessionId": "...", "environmentId": "...", "source": "repl"}`) instead of a `<session-id>.jsonl` — or,
less often, no slug directory at all even though `history.jsonl` records real prompt text and a `sessionId`
for that project. Measured across a full sweep: this pattern recurred across multiple distinct projects.
When a sub-agent hits this — `<encoded-path>/` absent, or present with only `bridge-pointer.json` — do
**not** report "no sessions found". Fall back to `history.jsonl`'s `display` field for that project/session,
which carries verbatim user-prompt text but **no assistant-side content** (no tool calls, no agent
reasoning). Explicitly disclose this as a coverage gap in the sub-agent's return (Tasks 1/2 are
correspondingly degraded — archetype matching in particular relies on assistant behavior that is
unavailable here) rather than silently treating the missing transcript as a clean negative result.
The manifest script lists such a session with `kind: history_only` and a coverage-gap line.

#### Forks and background handoffs

A fork or background handoff writes a new transcript that carries the earlier history under the same
record `uuid`s, so two files hold the same turns and a sweep would count one correction twice.
**Measured on Claude Code 2.1.281, 2026-09-28**: the 943 shared records keep identical `timestamp`
values and every copied record carries a rewritten `sessionId`, so the manifest matches copies by
record `uuid`. It applies this rule per project, over that project's selected transcripts, keyed by
transcript file so a file is never a fork of itself (the full contract is `dream-manifest.py --help`):

- Keeper order is most records first, then the smaller session id, then the smaller file path. Each
  record is kept by the first transcript in that order that holds it, so a chain of forks keeps every
  record once.
- A fork is dropped only when it has no unshared conversation turn (a turn without a record `uuid`
  counts as its own). It is left out of `sessions[]` and named in its project's `fork_collapsed`
  (`dropped`; `kept`, the session holding most of its records; `shared_records`).
- A partial fork keeps its own turns: its `boundary` moves to its first unshared conversation turn.
  After that boundary, a shared record is left out of its stripped file only when its keeper shows it
  after the keeper's own boundary; a header line counts them.
- A session whose every record is held by a transcript ranking before it in keeper order, outside
  the project's selected sessions (another project's, or one not selected this sweep), is kept, so no
  user turn is dropped, and its project's `errors[]` names the pair.
- One session id with two transcript files: a file whose every record is in the other is not listed,
  and `errors[]` names both files; two files that each hold turns of their own are both listed, the
  second with its own stripped file (`<base>-2.txt`), and `errors[]` says so.

Its fixtures are `claude-fork-*` under `shared/skills/qdream/scripts/fixtures/dream-manifest/`; change
the rule here and there together.

### Global history — the authoritative path mapping

- Location: `~/.claude/history.jsonl`
- One entry per user prompt: `{"display": "...", "timestamp": <unix-ms>, "project": "<verbatim workspace path>", "sessionId": "..."}`
- `project` carries the real path verbatim, so this is the reliable source for project discovery and for
  mapping an encoded folder name back to a workspace. `sessionId` is absent on some early entries.

### Native project memory — `~/.claude/projects/<slug>/memory/`

Claude Code keeps its **own** per-project memory here, in its own format. It is not a playbook memory
file, it is never committed, and no playbook read path sees it — so a durable entry written there
reaches a committed memory file only through the `/qdream` harvest
(`shared/skills/qdream/sweep-gather.md § GAT-NATIVE`). This section is that harvest's discovery path.

Layout — an index plus one file per entry:

- `memory/MEMORY.md` — a title line, then one markdown-link line per entry:
  `- [<link text>](<entry-file>.md) — <gloss>`
- `memory/<entry-file>.md` — YAML frontmatter (`name`, `description`, `metadata.type`), then an
  **unlabeled instruction body** (the actionable rule — neither `Why` nor `How to apply`), then
  `**Why:**` and `**How to apply:**` paragraphs.

#### Slug → workspace resolution

**Never invert the folder-name encoding.** It is lossy (every non-alphanumeric character becomes `-`),
so the inverse is a guess. Resolve forward instead, and match the result against the store:

1. **Join through `history.jsonl`.** List the `<session-id>.jsonl` files in `~/.claude/projects/<slug>/`
   and find a `~/.claude/history.jsonl` record with a matching `sessionId`. Its `project` field carries
   the workspace path **verbatim**. (`sessionId` is absent on some early records — try another session
   file.) When `/qdream` already handed you this project's Claude Code session paths, that join is
   **already done**: their parent directory *is* the slug directory.
2. **Fallback — forward-encode, never inverse.** With no usable `sessionId`, apply the *forward*
   encoding to each distinct `project` value in `history.jsonl` and keep the values that produce
   `<slug>`. If two or more distinct **existing** paths collide on one slug, that is the encoding's
   lossiness showing: skip the directory and report it. Do not guess.
3. **Resolve the store.** Run `store-resolver.py find <path>` on the resolved path, exactly as
   `shared/skills/qdream/memory-rules.md § Resolution contract` step 1 does. Exit 0 names the store;
   exit 3 (none) is a non-match.

**A non-match is normal and is skipped quietly** — never an error, never a warning. A meaningful
share of `history.jsonl` records name workspaces this machine's store cannot match — a different user
profile (case-folding does not rescue it) or a UNC path, for example — and a harvest that treated
each as a fault would produce a warning storm over an entirely healthy state.

#### Native → playbook mapping

The translation table below is the one Phase 4 of `260815-1511_WORKSPACE_LOCAL_MEMORY_AND_PLAN_STORE`
applied by hand when it migrated `widget-service`, **plus the two judgement calls that migration had to make
because the table did not cover them**. It is reproduced here rather than cited, so it survives that
plan's rename at archive. Destination format:
`shared/skills/qdream/memory-rules.md § Memory File Format`.

| Source element | Destination |
|---|---|
| index file's **title** line (`# Project Memory — <name>`) | the destination file's title line. **Judgement call 1**: the table never listed the title, and it is source content that would otherwise be silently lost — carry it |
| index line's **link text** *and* its **gloss** (`- [<link text>](<file>) — <gloss>`) | the entry `###` heading, link text **plus** gloss, joined as written. **Judgement call 2**: the table said link text only, which strands the gloss with no destination — and the `description:` row below measures against "link text + gloss", so the table already assumed the joined form |
| frontmatter `description:` | **compare against the assembled heading first.** If it carries no information the heading lacks, discard it and say so; otherwise append the residue to the lead paragraph. (Measured on `widget-service`: it differed by two words, both already carried — discarded) |
| frontmatter `name:` | recorded **inside `Source`** as the legacy native ID — it is a stable identifier and the playbook format has no field for one |
| **unlabeled instruction body** | the entry's lead paragraph, **verbatim** |
| `**Why:**` / `**How to apply:**` bodies | the same-named fields, **verbatim** |
| `metadata.type` | `feedback` → `## Feedback`, `decision` → `## Decision`, `pattern` → `## Pattern`. **Any other or absent value halts and asks** (closed-set fallback, `shared/AGENTS.md § SKILL.md Authoring`) |

**`type: project` / `type: user` / `type: reference` are real, recurring out-of-set values** — not malformed
data. Claude Code's own memory writer uses these as scope markers distinct from the playbook's
`feedback`/`decision`/`pattern` taxonomy, and this halt has fired independently across multiple projects,
each time stranding real content (project architecture notes, known-issues logs, deliverable-location
facts) with no path forward. **Do not silently re-halt on the same entry sweep after sweep.** A halted
entry's translation ambiguity is a one-time decision, not a recurring discovery — surface it once at
Phase 4b for the user to assign a type/target, rather than leaving it to be independently re-discovered
(and re-reported as a fresh gap) by every future sweep.

Two fields have no source element and are not invented:

- **`Source`** — write the native file path, the legacy native ID from `name:`, and the harvesting
  sweep, so the conversion is auditable. This line is also the harvest's already-harvested key
  (`shared/skills/qdream/memory-rules.md § Native-memory harvest dedup`), so it is not optional.
- **`Verified`** — **omit the field.** No verification event occurred, and dating one would assert a
  check nobody ran. (`memory-rules.md`'s "omit rather than guess" governs the *annotation*; the reason
  to omit the whole field here is the absent event.)

Keep multi-sentence bodies verbatim — the one-sentence `Why` / `How to apply` shape is a template, not
a validator.

### Metadata fields used by dream

| Field | Purpose |
|---|---|
| `cwd` (session jsonl) | Project discovery — the session's workspace |
| `project` (history.jsonl) | Project discovery and slug mapping — verbatim workspace path |
| `timestamp` (session jsonl) | Temporal filtering — per record, ISO-8601; a session is new when a genuine record is newer than `last_analyzed`, compared as instants, never as strings |
| `timestamp` (history.jsonl) | Fallback dating — Unix milliseconds; dates a record that has no `timestamp` of its own |
| `type` (session jsonl) | Message-kind discrimination (see below) |

File mtime is never recency evidence: a resumed session's mtime post-dates old turns, and a copied
file's mtime says nothing. It is used for one thing only — the deletion-age `due` flag, because
retention deletes by age.

**Sub-agent discrimination**: since at least 2.1.281, sub-agent transcripts are separate files under
`<session-id>/subagents/` (above), and older builds kept sub-agent turns inline with
`isSidechain: true`. Either way the discriminator is `isSidechain: true`: such a record is never user
speech and never makes a session new. There is no `parent_session_id` analogue. The `subagents/`
files still count for project discovery, since a project exists however it was worked on.

### Session content filtering

When sub-agents read `.jsonl` session files for signal extraction:

- **Focus on**: `"type":"user"` (user messages) and `"type":"assistant"` (agent responses). Assistant
  content is an array of blocks; text is `{"type":"text","text":"..."}`.
- **Skip**: every metadata type — `mode`, `bridge-session`, `last-prompt`, `file-history-snapshot`,
  `permission-mode`, `hook_success`, `hook_additional_context`, `deferred_tools_delta`,
  `agent_listing_delta`, `skill_listing`, `task_reminder`, `command_permissions`,
  `compact_file_reference`, `edited_text_file`, `mcp_instructions_delta`, `queue-operation`, `file`,
  and (2.1.281) `attachment` (except a human `queued_command`, below), `system`, `cost-state`,
  `atis-latch`.
- **Skip `!` shell-mode records.** A user block starting `<bash-input>`, `<bash-stdout>` or
  `<bash-stderr>` is the shell command and its output, not speech — and output can carry secrets. Harness
  text is judged **per content block**: a user block after an `[Request interrupted by user]` block is
  still speech, and `<command-name>` renders as a command only when the text starts with the command tags.
- **Skip tool results.** A `type:"user"` record whose `message.content` holds only `tool_result` blocks is
  tool output, not the user (59 of 84 user records in the 2.1.281 probe), and its `tool_result` text is
  never read — including the `The user answered: …` framing of an `AskUserQuestion` result. The one
  exception is that result's structured `toolUseResult.answers` (next bullet). Assistant content keeps
  only `text` blocks — `thinking` and `tool_use` blocks are not speech.
- **Keep two channels of user speech that are not text blocks** (`dream-manifest.py`
  `claude_dialog_texts`; measured 2026-09-28 across the local store: 281 answer records, 37 human
  `queued_command` attachments out of 734):
  - **`AskUserQuestion` answers.** A `type:"user"` record whose `toolUseResult` is an object holding a
    `questions` list and an `answers` object (question text → answer text). Each answer whose question
    text appears in `questions` is one user turn, rendered `[user:answer] Q: <question> → A: <answer>`,
    one line per question, at the record's line. Read `toolUseResult.answers` only. All 281 measured
    records answered an `AskUserQuestion` call and every key matched a question; requiring the match
    keeps another tool's result that merely has an `answers` key out.
  - **Mid-turn messages.** A `type:"attachment"` record whose `attachment.type` is `queued_command` and
    whose `attachment.origin.kind` is `human`, rendered `[user:mid-turn] <prompt>`. `attachment.prompt`
    is a string, or a list of content blocks (text kept, image blocks dropped). `origin` is the
    discriminator, not `commandMode`: peer messages and subagent hand-backs also carry
    `commandMode: "prompt"`, and task notifications carry a null `origin`. `humanTurn: true` only ever
    appeared beside a human `origin`, so it is not tested. Never parse the `<system-reminder>` ("The
    user sent a new message while you were working") the same message is rendered as: it is harness
    text; the attachment's `prompt` is the source.
  - Both channels keep every exclusion in this file (`isMeta`, `isSidechain`, `isCompactSummary`, a
    non-human `origin`), and a shape that is not certainly human is dropped. Each counts as a user turn
    for recency and for the boundary, exactly like a typed prompt.
- **Title**: first `{"type":"ai-title","aiTitle":"..."}` line; fall back to the first `type:"user"` message
  truncated to 80 chars, then to the session UUID.
- **Dating**: use each record's own `timestamp`. A record without one (older builds) takes the timestamp
  of the `history.jsonl` prompt with the same `sessionId` and the same normalized text (or a common
  prefix of at least 20 characters — history shortens pasted content); if neither exists the session's new
  turns cannot be located, so the whole session is read (`boundary: unknown`).
- **Token usage** (cost records): `message.usage` repeats on every content block of one API message, so
  sum it once per `message.id`, across the session file and its `subagents/*.jsonl`.

### Skill invocations are NOT expanded into the transcript

Unlike kiro-cli — where a slash command is persisted as a user record containing the whole expanded
`SKILL.md` body — Claude Code records the user's literal typed invocation (e.g. `/qdream`, wrapped in
`<command-name>`/`<command-args>` tags) and carries skill content out of band.

**But a `type:"user"` record is genuine user speech only if `isMeta` is absent or false.** Claude Code
persists harness-authored text in user-role records carrying `isMeta: true` — expanded `SKILL.md` bodies,
the rendered stdout of a local slash command (a `/context` report lands as a 13 KB `type:"user"` record),
and `<local-command-caveat>` blocks. A meaningful share of text-bearing `type:"user"` records carry the
flag. **Skip every `isMeta: true` record.**

`isMeta` is necessary but not sufficient: compaction summaries (`"This session is being continued…"`) and
task-notification blocks also arrive as `type:"user"` with `isMeta` absent — judge those on content.
2.1.281 also stamps user records with `origin.kind`: `human` for typed prompts, `task-notification`
and `peer` (another session's message, also `isMeta: true`) for harness text. A
positional heuristic ("skip the record after a `system`/`local_command` line") is **not** a substitute: it
matches 9 records, misses 208 of the 213, and false-positives on real user speech.

So the skill-text-laundering hazard documented in `shared/skills/qdream/sweep-gather.md § GAT-SESSIONS` **does**
reach this provider, by a different route. Do not skip the check for kiro-cli sources in the same sweep.

### The sweep's own session

The running session's id is in the `CLAUDE_CODE_SESSION_ID` environment variable, visible to the
shell tool (measured on Claude Code 2.1.281, Windows, 2026-09-24; inside a sub-agent it holds the
parent session's id). Its transcript is `~/.claude/projects/<encoded-path>/<id>.jsonl`, found by the
id (glob `~/.claude/projects/*/<id>.jsonl`), never by guessing the encoded path. The sweep passes the id
to `dream-manifest.py manifest --exclude-session <id>` (`shared/skills/qdream/sweep-orient.md § ORI-DISCOVER`)
and the transcript to `dream-manifest.py baseline --session <path> --by-role` for the cost record's
`tokens` and `tokens_by_role` (`shared/skills/qdream/sweep-decide-apply.md § APP-STATE`). `--by-role`
counts the session file as `orchestrator` and sorts each sub-agent transcript by the marker its brief
carries, tested in this order on its first non-blank line: `Dream Phase Agent Brief` is `orchestrator` (a
phase agent's cost is the orchestrator's), `Dream Drafter Brief` is `drafter`, `Dream Verifier Brief` is
`verifier`, `Dream Sub-agent Brief` is `task4`; the whole text is then tested for the verifier and task4
markers only, so a phase or drafter marker below the first line is a mention. Only a transcript with no
marker falls back: `Cross-validation` or `verifier` is `verifier` (older transcripts), anything else
`other`. It also prints a `peak context <role>: P` line per role: the largest input plus cache tokens of
one call among that role's transcripts, the session file's included under `orchestrator`. After those,
`peak context orchestrator (session): P` is the session file alone, and `peak context <role> <agent-file
name>: P` lines give each phase agent's (role `orchestrator`) and each drafter's own peak, the largest
first, at most 8 per role (the rest on one `peak context <role> (more): N agent(s) not listed, largest P`
line). The acceptance figure "peak context for the orchestrator and every phase agent" reads the
`(session)` line and the `orchestrator <agent-file name>` lines. When the variable is
unset, omit them and say so in the Report.

### Dispatch model routing

Concrete models for the roles of `shared/skills/qdream/sweep-orient.md § ORI-ROUTE`. Claude Code sets
a dispatch's model through the Agent tool's `model` parameter (values include `sonnet`, `opus` and `haiku`;
omitted, the dispatch inherits the orchestrator's model — measured on 2.1.281, 2026-09-24). Recommendation, shown when
`model_routing["claude"]` is empty:

| Role | Recommended | Why |
|---|---|---|
| `task4` | the orchestrator's own model (omit `model`) | The per-project agent: session analysis and classification against governance are judgment |
| `verifier` | the orchestrator's own model (omit `model`) | Refutation is judgment; a weak verifier rubber-stamps |
| `drafter` | `sonnet` | Drafting the exact proposal text from verified findings is bounded writing, not refutation |

Store the name the user confirmed (`sonnet`, for example, or the orchestrator's model id when inherited); the
`baseline` output names models by full id (for example `claude-sonnet-5`).

Every child (`task4`, `verifier`, `drafter`) runs as agent type `qdream-reader`
(`providers/claude/agents/qdream-reader.md`, deployed to `~/.claude/agents/`), whose only tools are Read, Grep
and Glob; the role's model is still set per dispatch through `model`. A child launched as a type with Bash
can follow the auto-mode advice to read files with `sed` or `cat`, and `extract` then refuses its return
(observed 2026-10-21: 4 refusals in one Gather phase).

Every phase agent runs as agent type `qdream-phase` (`providers/claude/agents/qdream-phase.md`), whose tools
are Read, Grep, Glob, Bash, Write and Agent; its frontmatter hook refuses any Bash command but one qdream
script call, any write outside the work folder's `handoff/`, and any child type but `qdream-reader`
(`providers/claude/reference/claude-code-local-data.md`, Native agent store).

### Deep format reference

Fuller detail — the complete message-type table, the live-session/status files under `~/.claude/sessions/`,
hook behaviour, and the kiro-cli comparison table — is in `providers/claude/reference/claude-code-local-data.md`.
It is an on-demand reference, not deployed into any session (indexed from `memory/topics/kiro-cli.md`): a
kiro session that mines or recovers Claude Code sessions (a `/qdream` sweep, a cross-harness handoff) reads
it there when that need arises. This file is the Claude-provider entry point that makes provider discovery
find Claude Code at all; that file is the depth behind it.
