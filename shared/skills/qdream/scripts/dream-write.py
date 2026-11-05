#!/usr/bin/env python3
"""dream-write.py -- the /qdream full sweep's write side.

The only script that writes memory files, the state file and the journal,
or runs `git commit` / `git push`. Every subcommand first runs the guard
self-check, then writes only inside its allowlist. dream-sweep.py writes
the work folder's read-side outputs; this script writes the rest.

Binding rule (plan D27). Every subcommand requires --snapshot-sha <sha256>
(the value `dream-sweep.py dirty` printed; missing or different is exit 3):
dirty-at-orient.json is read only through dream-sweep.py load_bound. The
other orchestrator-held roots are decisions.json (--decisions-sha),
push-plan.json (--push-plan-sha, the sha `push --plan` prints) and the guard
digest (the bound snapshot's, or --guard-digest after `guard --rebaseline`).
A root is a value the orchestrator holds, which a script compares with what it
reads; a script cannot tell who passed it. A phase agent can pass any
--guard-digest (it is checked only against the scripts on disk), so the
orchestrator's own recompute of the digest (sweep-handoff.md, loop step 7) is
the control. Likewise decisions.json is the orchestrator's file: the scripts
check its `option` and `variant` against the D28 table, the answer and the
op, not who wrote them.
Every other work-folder file a subcommand trusts is rebuilt from or checked
against them: commit candidates by path (the write allowlist, whose
manifest-named files must be Orient candidates, or an Applied governance
file that still passes the hash --record check), the working map against
the seed and applied-ops.json, the seed against the journal Orient backed
up, push --repos against the bound plan and the upstream re-derived from
git, state apply's date from manifest snapshot_at (checked against the
snapshot's).

Subcommands:
  memedit --ops <handoff/ops/<f>.json | sweep/<f>.json> [--dry-run]
          [--decisions <handoff/decisions.json> --decisions-sha <sha256>]
      Applies memory-file ops (Ops below) in file order, per op: (1) a
      rename or removal is recorded in sweep/working-map.json, (2) the whole
      map is written to memory/.dream-journal.jsonl (temp file, fsync,
      os.replace; its sha recorded in hashes.json), (3) {id, file, pre_sha,
      post_sha, status: pending} goes to sweep/applied-ops.json, (4) the
      file is written (temp file, fsync, os.replace), (5) its sha256 goes to
      sweep/hashes.json, (6) the op is marked done. A re-run skips a done
      op; a pending op whose file holds post_sha completes (5)-(6), one
      whose file holds pre_sha is applied again; anything else is exit 3
      naming the op. A recorded op is matched only by the same op: the
      record keeps its ops file (path under the work folder) and a digest of
      the op, and a different op under a recorded id (another ops file, or
      the same file with a changed op) is exit 3 naming both, nothing
      written (an id also keys the working-map record and the decision
      count, so a reused id can be neither run nor skipped). All ops for one file are validated before any write to
      it: one failed op means nothing is written to that file. The map
      lives in sweep/working-map.json; the first run seeds it from
      handoff/working-map-seed.json (landed rename pairs only) and refuses
      when the journal is non-empty and no seed exists. Every flush keeps
      the records of the journal Orient found (the backed-up copy: the
      removes and unlanded renames of a crashed sweep as well as the landed
      renames) ahead of the map's own, so a second crash cannot lose what
      recovery has not resolved; only `state apply` clears the journal. The journal passes
      an in-script grammar check on every flush (the verify-dream-journal
      grammar) and the real validator (verify-dream-journal.py, run by
      this interpreter with -I on every platform) after the last flush of a run and on
      every later run until it has passed (applied-ops.json
      journal_validation: pending, failed, passed; exit 3 while it is not
      passed, also for a run that skips every done op). A file with a done
      op whose sha256 is none of the shas this sweep recorded for it (the
      last hashes.json record, the post_sha of a pending op) was edited by
      another writer since: it is still written, marked foreign-edit and
      never committed. --dry-run prints per-file op counts only.
  Every write subcommand (all but memedit --dry-run) holds an exclusive
  lock file, sweep/write.lock (O_EXCL, removed in `finally`), for its run:
  a lock that exists is exit 3, reported as held or, when older than
  LOCK_STALE_SECONDS, as stale (ask the user to check that no run is alive
  and to remove the file); one exception: the file records the owner's pid,
  and a lock whose pid no longer runs (a harness kill skips `finally`) is
  removed and the run goes on. The check answers "dead" only on a clear no
  (pid_alive: a pid outside 1..2**31-1 is a corrupt lock and counts as
  alive); an unreadable lock or one without a pid is never reclaimed. Only
  the holder of sweep/write.lock.reclaim (created O_EXCL, removed when it has
  decided) removes a dead lock, and only after reading it again: a run that
  finds that file is exit 3 (one left by a killed run is reported, never
  broken).
  hash --record --decisions <handoff/decisions.json> --decisions-sha <sha256> <path>...
      Records the sha256 of governance files edited at [APP-ADJUDICATE],
      once per file after its last Applied item and blast-site edit. Each
      file must equal its Orient content (the blob at the recorded HEAD;
      the file clean at Orient) with every Applied edit naming it replayed
      in decisions.json order: `current_text` (exactly one occurrence)
      replaced by `new_text`; `current_text: null` inserts `new_text`
      before the next heading of the same or higher level after the line
      equal to `after_heading` (or at the end of the file); a file absent
      at Orient must equal its single edit's `new_text`. Any other
      difference refuses the record (exit 3, the others still recorded).
  state migrate
  state ledger --inputs <handoff/<f>.json>
  state apply --inputs <handoff/state-inputs.json>
              --decisions <handoff/decisions.json> --decisions-sha <sha256>
      migrate: the [ORI-STATE] v1/v2 -> v3 additive migration (a v3 file and
      an absent file are left alone). ledger: appends the new
      `episodic_ledger` records of the inputs file's `records`, skipping a
      record whose episode key is already present, and prints the 1-based
      indices. apply: every [APP-STATE] rule (APP-STATE below). Each write:
      the new state goes to a temp file beside the live one in the live
      file's own serialization, the live file is copied to
      sweep/state-before.json, verify-dream-state.py (run by this
      interpreter with -I on every platform) runs on the temp file with the
      copy as its ledger baseline, and only a PASS is followed by the write-ahead record
      {pre_sha, post_sha, status: pending} in sweep/state-pending.json and
      os.replace. A FAIL, a launch failure or a timeout leaves the live file
      untouched (exit 3). After the swap: the hash record, the journal clear
      (apply only: written empty, its sha recorded), status done. A state
      file that is none of the shas this sweep recorded for it (the last
      hashes.json record, the post_sha of a state-pending.json record) was
      edited by another writer: the write goes through and the record is
      marked foreign-edit (kept in state-pending.json across a stop). A re-run:
      a live sha equal to post_sha completes only the hash and the clear,
      equal to pre_sha applies again, anything else is exit 3; a done apply
      whose sha still matches is a no-op.
  commit --repos <repo>... --usage-line <text> [--subject <repo>=<text>]...
         --decisions <handoff/decisions.json> --decisions-sha <sha256>
      Commits, per repo and by pathspec, the hashes.json files that are a
      memory or state target of the write allowlist or an Applied
      governance file still equal to its Orient content with the Applied
      edits (never the journal; decided by path, never by the record), that
      were clean at Orient (or absent at Orient and created
      by this sweep), are not foreign-edit, still hold their recorded
      sha256 and, if untracked, are in the bound decisions.json's `track` list
      (the git-tracking answers: commit takes no path from its caller). Lists
      every other file with its reason. A --repos entry that is not the top of
      a git repository refuses the whole command before any commit (exit 3). Before committing: HEAD on a branch, no rebase, merge,
      cherry-pick or revert in progress, no index.lock; the credential scan
      (CREDENTIAL_PATTERNS) over `git diff HEAD` of the tracked paths and
      the whole content of the others. A pending record precedes `git
      commit -m <subject> -m <body> -- <paths>`; after it the parent and
      the path set are verified. Repos are independent: a refusal or a
      failed commit is recorded in sweep/commits.json and the run goes on
      (exit 3 at the end). Each commit holds only the eligible paths that
      differ from HEAD plus the untracked `track` ones, and that set is the
      record's `paths`: a write after a sweep commit commits again (a second
      sweep commit in commits.json) with just what it changed, and a re-run
      with nothing changed makes no commit ("already committed", never an
      empty commit). A re-run also adopts a commit a crash left pending
      (when none matches and the files already equal HEAD, the lost commit
      is reported as failed, exit 3). No trailer of
      any kind; hooks run. Prints each repo's last five subjects.
  push --plan --decisions-sha <sha256> [--decisions <handoff/decisions.json>]
  push --repos <repo>... --push-plan-sha <sha256>
      --plan (orchestrator only, read-only toward git) writes
      sweep/push-plan.json and prints its sha256 (`push-plan sha256:`): per
      committed repo the branch, upstream and `git rev-list @{u}..HEAD`,
      each sha marked sweep or foreign (a foreign commit made between the
      Orient HEAD and HEAD first; the credential scan over every listed
      diff, a hit in a sweep commit also making the repo not pushable), and
      the outbound check: every sweep commit lies between the
      Orient HEAD and HEAD and its paths equal its recorded set and pass the
      commit candidate rule, and every decisions sha recorded in
      applied-ops.json and hashes.json equals --decisions-sha. --repos reads
      the plan bound to --push-plan-sha, re-derives the upstream (branch,
      remote, merge ref) and refuses any difference, refuses a repo whose
      HEAD or list differs from the plan, reports "already pushed" when the
      upstream holds HEAD, and runs `git push <remote> <sha>:<merge ref>`;
      results go to sweep/push-results.json (never read back).
  ops --step <STEP-ID> --snapshot-sha <sha256> [--guard-digest <sha256>]
      Writes handoff/ops/<step-id, lower case>-generated.json, the memedit ops of
      handoff/ops-plan/<STEP-ID>.json (`dream-sweep.py handoff schema
      ops-plan/<STEP-ID>.json`). A `new` item (a task4 return's label and an
      index into its memory_proposals) becomes an insert of that proposal
      rendered in the memory-rules.md Memory File Format template (Verified:
      the manifest snapshot_at date, actor sweep) at the end of its type
      section of the target file (`file`, else the label's memory file for
      target project, <config repo>/memory/MEMORY.md for target user); a
      `usage_bump` item names one existing entry. Op ids are
      <step id, lower case>-NNN, with no decision_id. Exit 3, nothing
      written, unless every item passes: the proposal's verdict (bound to its
      data file as `aggregate` binds it) is confirmed; its type,
      heading, why, how_to_apply and source are one-line strings, the heading
      at most 200 characters, the source without `|`, no free-text field
      holding a `**<Field>**:` marker or starting with `###`; the file is in
      the write allowlist and readable, in the tier the proposal's target names
      (user: the config repo's memory/MEMORY.md or memory/topics/*.md; project:
      the label's own memory file, or for a project without one the store file
      Orient bound for it, created first by a skeleton create), holds the type
      section and not the heading (a
      merge into an existing entry is an agent-written replace op); a
      usage_bump heading is exactly one entry; no op needs a decision
      (needs_decision: no human: actor or guarded line added); an op id that
      applied-ops.json records with another op is refused, one recorded with
      the same op is generated again. No Source-append op exists. Takes no
      write.lock (it writes no memory file). Prints the file's sha256.
      The generated file never shares a name with a hand-written
      ops/<STEP-ID>.json (the suffix differs, so no case-insensitive match
      either); a file already there with other content is refused, with the
      same content it is left as is. `ops` records each generated op's digest
      in sweep/ops-generated.json; `memedit` refuses an autonomous (no
      decision_id) insert into a MEMORY.md or a config repo topic file other
      than improvement-signals.md unless that digest is recorded, except an
      `[improvement_signal]` entry under `## Pattern` of a project's
      MEMORY.md; an autonomous replace neither drops nor adds that prefix; an
      autonomous create of a MEMORY.md or a config repo topic file holds
      only an optional first-line title, `# Project Memory — <store name
      without its hash>` or `# Topic memory — <stem>`, and the headings
      `## Feedback`, `## Decision`, `## Pattern`, `## Declined` written
      exactly, each once (a MEMORY.md has all four).
  --selftest [--work <dir>] [--jobs N] [--case <name>]... [--list]
      Runs the cases under fixtures/dream-write/ in N worker processes
      (default 4; --jobs 1 runs them in this process), printing results in
      case order. --case (repeatable) runs only the named cases (exit 2 on an
      unknown name); --list prints the case names.

Guard self-check. Before any write every subcommand compares the guard
digest of the scripts directory (dream-sweep.py guard_files/guard_digest,
untracked files included) with the bound snapshot's guard_digest, or with
--guard-digest when given; a difference is exit 3 naming the changed
scripts (from sweep/guard-hashes.json, used for the names only; a phase
agent then writes a `guard-changed` needs-decision). The digest passed is
checked against the scripts on disk and no further (see Binding rule). Run as a script, both
this file and dream-sweep.py drop their own directory and '' from sys.path
before any other import and refuse PYTHONPATH/PYTHONHOME without -I, so a
planted module is never imported.

Path allowlist (by realpath; a link or junction at the target or in a
directory between the target and its repository or project root is
refused): a memory/MEMORY.md the manifest names (or the would-be one of a
confirmed project without one, resolved as dream-sweep.py candidate_files
resolves it), <config repo>/memory/topics/*.md, memory/HIGHER_ORDER.md,
memory/.dream-state.json, memory/.dream-journal.jsonl, and the work folder.

Ops (an ops file is {"ops": [...]}; every op has an `id`, unique within its
file and across the sweep (a recorded id is reusable only by the same op: see
memedit), an `op`, an absolute `file`, and optionally `section` (a type section, narrowing the
heading match) and `decision_id`):
  delete {heading, class}      class: a removal class of memory-rules.md
                               (REMOVAL_CLASSES), or `node` in
                               HIGHER_ORDER.md (no map record)
  replace {heading, text}      text: the whole entry, `### ` line first;
                               a changed heading is a rename
  insert {section, text}       a new entry at the end of an existing type
                               section
  append_lines {heading, lines}
  create {text}                the file must be absent
  usage_bump {heading}         **Usage**: N -> N+1, or a new **Usage**: 1
  declined_add {row}           a `- "<heading>" — declined ...` row under
                               ## Declined (the section is added when absent)
  Targets resolve through dream-manifest.py parse_entries rules (fence-aware,
  inside a type section, exactly one match). ## Declined is preserved byte
  for byte except by declined_add; BOM and line endings are preserved.
  User-gated ops carry `decision_id` and need --decisions/--decisions-sha:
  declined_add, every delete of class USER_GATED_CLASSES, `pruned` in the
  config repo's memory/MEMORY.md, a HIGHER_ORDER.md node delete, any op but
  usage_bump on an entry whose Verified names a `human:` actor, and any op
  whose new text adds a `human:` Verified actor. An op without decision_id
  (autonomous) is refused in each of those cases, with two exceptions for an
  entry whose Verified names a `human:` actor: the `pruned` delete of a
  project memory file's entry (the Size check, outside <config repo>/memory/)
  and a `replace` that only sets or changes the entry's `Outcome:` field (a
  field is `**Outcome**: recurred|not-recurred <YYYY-MM-DD>` and nothing more,
  alone on its line or after a `|` on its own metadata line, as in
  `**Usage**: 3 | **Outcome**: ...`; never on the Source/Verified line, which
  verify-memory fails). An exception lifts only the refusal of
  a human-attested entry: no autonomous op, under any exception, adds a
  `human:` actor line that the entry did not already hold. An
  autonomous op also needs a decision when it deletes an entry holding a
  non-terminal Governance-conflict record, deletes in HIGHER_ORDER.md, or
  writes an `Affirmed` or `Governance-conflict` line the entry does not
  already hold. With --decisions every op must name a decision_id.
  D28 (D28_TABLE): an op with decision_id is allowed only when the item's
  `kind` and option (its `option`, else its `answer`, normalized: casefold,
  runs of space, `-` and `_` one space) authorize its op type in the table
  (a `variant` field swaps the slots of some options: D28_VARIANTS), the op names the
  item's `file` (`to_file` for a budget-move insert) and `heading` (a
  delete, replace or append_lines by heading; a declined_add row starts
  `- "<heading>"`; an insert or create writes that heading, except a
  harvest-merge Keep both), a replace or insert text and an append_lines
  text equal the item's `shown_text`, a create writes one entry equal to
  it, a node delete cites a `node` item (and only it) and, like that item,
  names memory/HIGHER_ORDER.md, any `human:` actor
  line in the new text appears in `shown_text`, and the decision's ops
  (this ops file plus applied-ops.json, by op id) fit the slots its option
  authorizes, one op per slot. A replace or append_lines is also checked
  against the entry it rewrites: a conflict answer other than Delete entry
  writes only the entry's `Governance-conflict` and `Governance-conflict-quote`
  lines (a replace equals the old entry once both lose those lines; an
  append_lines holds only such lines), and a re-date (a human-expiry Keep or
  Re-date-as-sweep; a stale Keep with variant expiry-only) changes only the
  `Verified` value on its Source line and drops `Stale-after` / `Stale-when`
  lines, never adding or changing one. push --plan's recorded-op check keeps
  no text, so these shape checks are memedit's alone.

handoff/decisions.json (written by the orchestrator; its sha256 travels in
the phase brief): {"items": [{"id", "kind", "answer", "option"?, "variant"?,
  "gate_text", "target_file"?, "current_text"? (str|null), "new_text"?,
  "after_heading"?, "create"? (true: a new governance file),
  "blast_edits"?: [{"path", "heading", "current_text", "new_text", "after_heading"?}],
  "for_conflict"? (null, or the id of the `conflict` item whose `Update
  governance` option this governance item drafts),
  "skip_item"? (true only: the orchestrator turned an Applied governance or
  retirement item into option `Skip` at the Failure gate, `Skip item`; it is
  no rejected lesson, so the Apply phase agent writes none for it, like `for_conflict`),
  "file"?, "heading"?, "shown_text"?, "to_file"?,
  "project"? (manifest project path or "user memory")}],
  "track"?: [absolute path, ...]}
  `track` lists the files the git-tracking question was answered yes for
  (absolute, inside the config repository or a manifest project root); it
  is the only source of `commit`'s untracked files. `answer` is the user's
  words, verbatim; `option` is the gate option they
  chose (the orchestrator maps the answer to it). The scripts match on the
  option, normalized as above; without `option` the answer is normalized
  instead. Every `kind` is a D28_TABLE key (memory-proposal, stale,
  stale-salvage, subsumed, budget-move, budget-delete, node, harvest-merge,
  governance, retirement, conflict, duplicate, human-expiry) and the option
  one of its kind's options; a `variant` is one of D28_VARIANTS (memory-
  proposal `merge-downgrade`: a Save or Edit the verifier downgraded to a
  merge or update replaces the named existing entry; stale `expiry-only`:
  Keep on a user-memory item replaces it with the re-dated entry;
  governance or retirement `promotes`: Apply deletes the promoted source
  entry, class promotion-removal, in the `file` and `heading` the item names;
  the item must also carry the governance edit it promoted into (`target_file`,
  `new_text`) and `gate_text`, the proposal as shown, which holds the
  `Also removes memory entry:` line `gate` rendered for it). An `option` that differs from the answer is accepted unless the
  normalized answer is itself another option of the kind.
  Anything else refuses the whole file, in `dream-sweep.py handoff check
  decisions.json` (item_problems, the same code, which also needs `file`,
  `heading`, `shown_text` and `to_file` on an item whose option authorizes a
  memory op) and again in every script that loads it. A governance edit is a
  governance or retirement item answered `Apply` with target_file; a path is
  repo-relative (config repo) or absolute, and writes only a governance or
  skill text file: a `.md` file inside the config repository or, as an
  absolute path, under a manifest project root (a project-repo promotion
  target); never a path with a `memory` or `.git` component, a memory file
  the Resolution contract places, a script or any non-`.md` file. Each blast
  edit's path is the item's target_file or a hit of the item's blast output
  (handoff/drafts.json, by item id, names it). An Applied item is checked
  whole at the gate (handoff check) and at every load: it needs target_file
  and new_text and a placeable current_text on it and on each blast edit:
  non-empty, with a null after_heading, or null with an after_heading (a
  heading line). A target_file absent at Orient (the bound snapshot) is
  written only as `create: true` with current_text and after_heading null
  (the gate shows "New file: <path>" and the whole new_text); `create: true`
  on a file that existed, on a blast edit, or with an anchor is refused, and so
  is a blast edit whose path is absent at Orient. A path is also refused when
  a component holds a ':' (beyond a leading drive letter: an NTFS alternate
  data stream) or ends in a dot or a space (Windows ignores them). A `conflict`
  answered other than `Update governance` leaves its derived governance item
  unpresented: it is recorded as option `Skip` with `for_conflict` set. An item that authorizes a memory
  op names `file`, `heading` and, for a written text, `shown_text` (the text
  the gate showed); a budget-move names the insert's `to_file`; a duplicate's
  `file` is the copy to delete (class pruned); a node Keep node writes the one
  line `**Affirmed**: <date>` to HIGHER_ORDER.md; a conflict Delete entry
  deletes with class `Delete entry`; a human-expiry (Keep, Re-date-as-sweep or
  Defer) names the entry's `file` and `heading` and, for Keep and
  Re-date-as-sweep, the re-dated entry as `shown_text`: each authorizes one
  replace of that entry and nothing else (Defer authorizes nothing; no
  option authorizes a delete). `kind` subsumed, stale or stale-salvage
  answered Defer with a `project` sets that project's quiet counter to 4 in
  `state apply`.

handoff/state-inputs.json: the dream-sweep.py HANDOFF_SCHEMAS keys
(decisions_sha, rejected_lessons, outcome_tags, cost_record) plus optional
episodic_ledger. (human_expiries is not an input: APP-ADJUDICATE executes a
human-attested expiry as an in-place Verified edit, and APP-STATE writes
nothing to the state file for it; an extra key in the file is ignored.) cost_record {} appends no
record. The sweep's date for every dated write is manifest snapshot_at,
never a date in this file (D27). outcome_tags
items with `outcome` update the record with the same target and applied
date; the others open a record unless one is open for the target.

APP-STATE (computed from the work folder, never passed): last_run =
manifest snapshot_at; per confirmed project (dispatch.json `confirmed`): a
manifest status `removed` is an acknowledged removal (projects,
quiet_sweeps.projects and its deferred_sessions dropped); coverage.json
stamp -> last_analyzed = snapshot_at under the state key; a new project not
stamped -> new_project_baseline.since (null: earliest first_activity minus
one second, else 1970-01-01T00:00:00Z); deferred sessions of stamped
projects -> deferred_sessions, then watermarks_to_clear deleted; quiet
counters: 0 when countverify.json says checked, else the manifest value + 1,
4 on a Defer (decisions.json); user memory 0 only when every user-memory
file was dispatched and checked; model_routing from handoff/orient.json;
rejected_lessons pruned (skipped 60 days, refuted 180) and appended, a
`skipped` one only if the governance or retirement item(s) of decisions.json
its target names include a plain Skip (an Applied, Deferred, for_conflict or
skip_item item rejects no lesson; exit 3 otherwise); a lesson no item names
(a verifier-refuted one, an in-session signal Skip) is appended unchecked;
cost_records capped at 20 (the oldest `sweep` record dropped). Episode key
of a ledger record (whitespace-collapsed, case-folded; the free-text `what`
and `when` are not part of it): its `outcome` (the record has no kind field,
so the outcome stands for the record kind), its sorted session ids (found in
`where` and support_set) and its `where`, or, without a session id, its
`outcome`, `where` and sorted support_set (user decision 2026-10-14, "1a").

Records (rewritable outputs, dream-sweep.py replace_in_work):
  hashes.json      the dream-sweep.py docstring format, plus
                   created_by_sweep (bool).
  applied-ops.json {"version": 1, "ops": {"<id>": {"op", "file", "pre_sha",
                   "post_sha", "status": pending|done, "decision_id",
                   "decisions_sha", "foreign", "created", "heading", "class", "map",
                   "ops_file", "digest"}},
                   "journal_validation": pending|failed|passed (absent until
                   a run writes the journal)}
  working-map.json {"version": 1, "records": [{"id", "record": {"rename"|
                   "remove": [..., ...]}}]}
  state-pending.json {"version": 1, "ops": {"migrate"|"ledger"|"apply":
                   {"pre_sha", "post_sha", "status", "at", "foreign"}},
                   "journal_cleared": <time>, written by every state apply path
                   that clears the journal}
  write.lock       {"pid", "at"}, present only while a write subcommand runs
  commits.json     {"version": 1, "repos": {"<repo>": {"orient_head",
                   "commits": [{"status", "recorded_head", "paths",
                   "subject", "sha" (done only)}], "listed", "outcome"}}}
  push-plan.json   {"version": 1, "decisions_sha", "repos": {...}}, never
                   rewritten after --plan (it is bound by its sha)
  push-results.json {"version": 1, "pushed": {"<repo>": {"sha", "ref",
                   "result"}}}

Exit codes: 0 ok, 2 usage, 3 precondition failure (named); an OSError or a
git timeout is exit 3 on one line; any other exception is a bug (exit 1).
Every git command runs as `git --no-optional-locks -c core.fsmonitor=false`;
the write-side ones (git_run) run the git that shutil.which found, with
stdin closed and GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never, and the
credential-scan diffs with --no-textconv.
This script never creates a branch and never runs reset, --amend, revert,
stash, checkout, restore, a force push or --no-verify. A config-repo commit is
refused unless HEAD is the engine branch (`engine_branch=` in the pointer file,
default local-improvements): engine commits never land on main. Python 3.8+, stdlib only.
Canonical rules: memory-rules.md (Memory File Format, the working map and
the crash-recovery journal, State File Format), sweep-orient.md
[ORI-STATE], sweep-synthesize.md [SYN-WRITE] [SYN-HIGHERORDER],
sweep-decide-apply.md [APP-ADJUDICATE] [APP-STATE].
"""

# Planted-module refusal (plan D27, review S5), before any other import: a
# module planted in the scripts directory or the current directory is never
# imported, with or without -I. Run as a script, Python puts the script's
# directory first on sys.path, ahead of the standard library; that entry and
# any '' entry are dropped. PYTHONPATH and PYTHONHOME (honoured without -I or
# -E) can do the same and are refused. nt/posix are built in, so reading the
# environment imports nothing from sys.path. (The same block as dream-sweep.py.)
import sys

if __name__ == "__main__":
    def _harden_sys_path():
        flags = sys.flags
        env = __import__("nt" if "nt" in sys.builtin_module_names else "posix").environ
        if not (flags.isolated or flags.ignore_environment):
            for k, v in env.items():
                name = (k.decode("latin-1") if isinstance(k, bytes) else k).upper()
                if name in ("PYTHONPATH", "PYTHONHOME") and v:
                    sys.stderr.write("precondition failed: %s is set; run with -I (or unset "
                                     "it): a module on it could shadow the standard library\n"
                                     % name)
                    sys.exit(3)
        if not (flags.isolated or getattr(flags, "safe_path", False)) and sys.path:
            del sys.path[0]
        sys.path[:] = [p for p in sys.path if p not in ("", ".")]
        import os as _os
        drop = {_os.path.normcase(_os.path.realpath(x)) for x in (
            _os.path.dirname(_os.path.abspath(__file__)), _os.getcwd())}
        sys.path[:] = [p for p in sys.path
                       if _os.path.normcase(_os.path.realpath(p)) not in drop]
    _harden_sys_path()

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import types
from pathlib import Path

# No bytecode near the skill directory: Kiro deploys qdream as a copy, and a
# stray .pyc there reads as drift.
sys.dont_write_bytecode = True

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

HERE = Path(os.path.realpath(__file__)).parent


def _load_sweep_module():
    """dream-sweep.py (which compiles dream-manifest.py), compiled from its
    source: never through a bytecode cache, never via sys.path."""
    path = HERE / "dream-sweep.py"
    with open(str(path), "rb") as fh:
        src = fh.read()
    mod = types.ModuleType("dream_sweep")
    mod.__file__ = str(path)
    code = compile(src, str(path), "exec", dont_inherit=True)
    exec(code, mod.__dict__)
    return mod


# --- venv guard stub: identical in every qdream script (venv-selfcheck.py --selftest compares them) ---
def _require_venv(script):
    """plan 261016 Phase 5: exit 2, "guard did not run: venv missing", unless this process runs in the
    dedicated venv. A run's first action: it loads only venv-selfcheck.py (by path, no bytecode cache,
    stdlib only) before any other sibling script is imported, so a broken sibling cannot hide the guard;
    if even that load fails it exits 2 with "venv self-check unavailable". The check itself lives only in
    venv-selfcheck.py. Not called at import: the hook imports some of these files."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "venv-selfcheck.py")
    name = os.path.basename(script or __file__)
    saved = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec = importlib.util.spec_from_file_location("venv_selfcheck", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    except Exception as exc:
        sys.stderr.write("%s: guard did not run: venv self-check unavailable (%s: %s)\n"
                         % (name, type(exc).__name__, exc))
        sys.exit(2)
    finally:
        sys.dont_write_bytecode = saved
    mod.require(script or __file__)
# --- end venv guard stub ---


if __name__ == "__main__":
    _require_venv(__file__)

ds = _load_sweep_module()
dm = ds.dm

Precond, Usage, LoadError = ds.Precond, ds.Usage, ds.LoadError
EXIT_OK, EXIT_USAGE, EXIT_PRECOND = 0, 2, 3
VALIDATOR_TIMEOUT = 180

HASHES = "sweep/hashes.json"
APPLIED = "sweep/applied-ops.json"
WMAP = "sweep/working-map.json"
STATE_BEFORE = "sweep/state-before.json"
STATE_PENDING = "sweep/state-pending.json"
COMMITS = "sweep/commits.json"
PUSH_PLAN = "sweep/push-plan.json"
PUSH_RESULTS = "sweep/push-results.json"
GENERATED = "sweep/ops-generated.json"
SEED = "handoff/working-map-seed.json"

REMOVAL_CLASSES = ("demoted", "pruned", "stale-entry deletion", "promotion-removal",
                   "[improvement_signal] promotion-removal", "subsumption removal",
                   "Delete entry", "expired_signal")
USER_GATED_CLASSES = ("promotion-removal", "[improvement_signal] promotion-removal",
                      "subsumption removal", "Delete entry")
NODE_CLASS = "node"
SIGNAL_PREFIX = "[improvement_signal]"
SKELETON_SECTIONS = ("## Feedback", "## Decision", "## Pattern", "## Declined")
FQ_PREFIXES = ("user memory § ", "project memory (")
OP_TYPES = ("delete", "replace", "insert", "append_lines", "create", "usage_bump",
            "declined_add")
OP_FIELDS = {"delete": ("heading", "class"), "replace": ("heading", "text"),
             "insert": ("section", "text"), "append_lines": ("heading", "lines"),
             "create": ("text",), "usage_bump": ("heading",), "declined_add": ("row",)}
OP_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}\Z")
# D28 decision-to-op authorization: the table in plan
# 261012_QDREAM_PHASE_AGENTS_SHIPPED_SCRIPTS_AND_GATE_DRAFTER.md, "## 9)
# Implementation Divergences from Plan", "D28 authorization table" (signed
# off by the user on 2026-10-13; the `human-expiry` row closed to the gate's
# three options on 2026-10-15; the rows of Amendment 2, 2026-10-15, are the
# merge-downgrade and Edit memory-proposal answers, the governance-
# contradiction answers, the expiry-only stale Keep, subsumed Keep, node Keep
# node, the promoting Apply, conflict Delete entry and the kind `duplicate`).
# Gate item `kind` -> {normalized option: the ops that option authorizes},
# each op a slot of the op types that may fill it; one op per slot, so the
# count is limited. An option is matched after norm_opt (casefold; runs of
# space, `-` and `_` are one space), on the item's `option`, which the
# orchestrator writes next to the user's verbatim `answer`. A kind not in
# this table, or an option outside the kind's options, is refused when
# decisions.json is loaded.
norm_opt = ds.norm_opt
_AR = (("append_lines", "replace"),)
_D28 = {
    "memory-proposal": {
        "Save": (("insert", "create"),), "Edit": (("insert", "create"),),
        "Skip": (("declined_add",),),
        "record with an explicit override note": (("insert",),),
        "drop": (("declined_add",),), "propose a governance update": ()},
    "stale": {"Delete": (("delete",),), "Keep": (), "Defer": ()},
    "stale-salvage": {"Rewrite": (("replace",),), "Delete": (("delete",),), "Keep": (),
                      "Defer": ()},
    "subsumed": {"Remove": (("delete",),), "Keep": _AR, "Defer": ()},
    "budget-move": {"Move": (("delete",), ("insert",)), "Keep": (), "Defer": ()},
    "budget-delete": {"Delete": (("delete",),), "Keep": (), "Defer": ()},
    "node": {"Remove node": (("delete",),), "Keep node": (("append_lines",),), "Defer": ()},
    "harvest-merge": {"Merge": (("replace",),), "Keep both": (("insert",),),
                      "Keep harvested": (("replace",),), "Keep existing": ()},
    "governance": {"Apply": (), "Skip": ()},
    "retirement": {"Apply": (), "Skip": ()},
    "conflict": {"Keep entry": _AR, "Update governance": _AR, "Delete entry": (("delete",),),
                 "Defer": _AR},
    "duplicate": {"Delete copy": (("delete",),), "Keep both": (), "Defer": ()},
    "human-expiry": {"Keep": (("replace",),), "Re-date-as-sweep": (("replace",),),
                     "Defer": ()},
}
D28_TABLE = {k: {norm_opt(o): s for o, s in v.items()} for k, v in _D28.items()}
# An item's `variant` (a field the gate writes) swaps the slots of some of the
# kind's options: a Save the verifier downgraded to a merge or update replaces
# the named existing entry; Keep on an expiry-only user-memory stale item
# replaces it with the re-dated entry; an Apply that promotes a memory entry
# deletes its source entry. Any other variant of a kind is refused.
D28_VARIANTS = {
    ("memory-proposal", "merge-downgrade"): {"save": (("replace",),), "edit": (("replace",),)},
    ("stale", "expiry-only"): {"keep": (("replace",),)},
    ("governance", "promotes"): {"apply": (("delete",),)},
    ("retirement", "promotes"): {"apply": (("delete",),)},
}
# Delete classes the rows that name one accept.
PROMOTION_CLASSES = ("promotion-removal", "[improvement_signal] promotion-removal")
AFFIRMED_RE = re.compile(r"\*\*Affirmed\*\*: \d{4}-\d{2}-\d{2}\Z")
GOVERNANCE_KINDS = ("governance", "retirement")
# Defer on these kinds sets the project's quiet counter to 4 (state apply).
DEFER_QUIET_KINDS = ("subsumed", "stale", "stale-salvage")
TRAILER_RE = re.compile(r"(?im)^\s*(co-authored-by|signed-off-by|claude-session|generated with)\b")
HUMAN_RE = re.compile(r"\*\*Verified\*\*:[^\n]*\(\s*human:")
USAGE_RE = re.compile(r"^(\*\*Usage\*\*:\s*)(\d+)")
# The entry's Source line (memory-entries.py's rule): where usage_bump puts a new **Usage**: 1.
SOURCE_RE = dm.memory_entries().SOURCE_RE
EOL_RE = re.compile(r"\r\n|\n|\r")
SESSION_TOKEN_RE = re.compile(
    r"\b([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|sess_[0-9a-f-]{8,})\b")
SKIPPED_DAYS, REFUTED_DAYS = 60, 180
COST_RECORDS_MAX = 20

# Credential patterns (plan D23), shared by memedit and commit. A hit
# reports `path:line` and the pattern name only, never any part of the
# match (memory-rules.md, "Report the pattern, never the match").
CREDENTIAL_PATTERNS = (
    ("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}")),
    ("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{8,}")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+")),
    ("discord-webhook", re.compile(
        r"https://(?:ptb\.|canary\.)?discord(?:app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("url-credentials", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    # A quote may sit between the key and the colon, and before the value
    # (JSON); the value's 8 characters follow that quote, not include it. Each
    # quote may be backslash-escaped (JSON inside a JSON string, as a JSONL
    # line holds it: \"password\": \"...\").
    ("generic-secret", re.compile(
        r"(?i)(?:password|passwd|secret|api[_-]?key|token)(?:\\*[\"'])?\s*[:=]\s*"
        r"(?:\\*[\"'])?(?!\\*[\"'])\S{8,}")),
    ("teams-webhook", re.compile(
        r"https://(?:[A-Za-z0-9-]+\.)*(?:webhook|outlook)\.office(?:365)?\.com"
        r"/webhook[A-Za-z0-9]*/[A-Za-z0-9@/_.-]{8,}")),
    ("teams-webhook", re.compile(
        r"https://[A-Za-z0-9.-]*logic\.azure\.com(?::\d+)?/workflows/[A-Za-z0-9]{8,}/\S+")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]*)?")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}")),
    ("stripe-key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{30,}")),
    ("azure-storage-key", re.compile(r"AccountKey=[A-Za-z0-9+/]{20,}")),
    # A same-line run of token characters (RFC 6750 b64token) of 20 or more that
    # holds a digit: prose after the word ("Bearer authentication is ...") and a
    # token on the next line are not a credential.
    ("bearer-token", re.compile(
        r"(?i)\bBearer[ \t]+(?=[A-Za-z0-9._~+/=-]*[0-9])[A-Za-z0-9._~+/=-]{20,}")),
)


class Crash(BaseException):
    """Selftest only: an injected stop at a named persist point."""


def _crash(ctx, point):
    if getattr(ctx, "crash_after", None) == point:
        raise Crash(point)


def scan_text(text, first_line=1):
    """-> [(line number, pattern name)], one per pattern name per line."""
    hits = []
    for i, line in enumerate(EOL_RE.split(text)):
        seen = set()
        for name, rx in CREDENTIAL_PATTERNS:
            if name not in seen and rx.search(line):
                seen.add(name)
                hits.append((first_line + i, name))
    return hits


def ascii_safe(s, n=120):
    return " ".join(str(s).split())[:n]


# --------------------------------------------------------------------------
# Run context, guard, allowlist
# --------------------------------------------------------------------------

class Run:
    """A write-side run: the Orient snapshot is read only bound to
    --snapshot-sha (D27; missing is exit 3), and the manifest must carry the
    snapshot's snapshot_at."""

    def __init__(self, ctx, args):
        self.ctx = ctx
        self.work, self.man = ds.open_work(ctx)
        self.dirty = ds.load_dirty(self.work, args.snapshot_sha, required=True)
        self.repo = Path(self.dirty["repo"])
        # The manifest's user-memory files must belong to this config repo
        # (check_config_repo refuses otherwise).
        ds.check_config_repo(str(self.repo), self.work, self.man)
        if self.man.get("snapshot_at") != self.dirty.get("snapshot_at"):
            raise Precond("refused: manifest.json snapshot_at %r is not the Orient snapshot's "
                          "(%r)" % (ascii_safe(self.man.get("snapshot_at"), 40),
                                    ascii_safe(self.dirty.get("snapshot_at"), 40)))
        self.guard_digest = getattr(args, "guard_digest", None)
        self.now = dm.iso(ctx.now)
        self.notes = []

    @property
    def state_path(self):
        return self.repo / "memory" / ".dream-state.json"

    @property
    def journal_path(self):
        return self.repo / "memory" / ".dream-journal.jsonl"


LOCK = "sweep/write.lock"
LOCK_STALE_SECONDS = 900
# The largest pid any platform here hands out (a signed 32-bit value); a lock
# naming another number is corrupt, never a dead owner.
PID_MAX = 2 ** 31 - 1
# Beside the lock while a run decides whether the lock's owner is dead
# (reclaim_stale_lock): created O_EXCL, so one run at a time may remove a lock.
RECLAIM_SUFFIX = ".reclaim"


def lock_refusal(run, path):
    """The Precond text for a lock that exists: held (young) or stale (older
    than LOCK_STALE_SECONDS, the longest a subcommand runs: validator and git
    timeouts). A stale lock is reported, never broken."""
    at, pid = None, "?"
    try:
        with open(str(path), "rb") as fh:
            rec = json.loads(fh.read().decode("utf-8"))
        at, pid = dm.parse_time(rec.get("at")), rec.get("pid", "?")
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    age = (dm.parse_time(run.now) - at).total_seconds() if at is not None else None
    if age is not None and age > LOCK_STALE_SECONDS:
        return ("%s is stale (written %d s ago by pid %s, older than %d s): a dream-write.py "
                "run may have been killed; ask the user to check that none is running and to "
                "remove the file. Nothing written"
                % (LOCK, age, ascii_safe(pid, 20), LOCK_STALE_SECONDS))
    return ("%s is held by another dream-write.py run (pid %s): wait for it to end. Nothing "
            "written" % (LOCK, ascii_safe(pid, 20)))


def pid_alive(pid):
    """True when a process with this pid exists. Windows: OpenProcess and the
    exit code (STILL_ACTIVE); access denied means it exists. POSIX: signal 0
    (PermissionError means it exists). Any doubt answers True: a lock is only
    reclaimed on a clear no. A pid outside 1..PID_MAX (or not an int) is no
    pid of any process: it is a corrupt lock, answered True (Windows wraps a
    c_uint32 argument silently, and os.kill raises OverflowError for it)."""
    if not isinstance(pid, int) or isinstance(pid, bool) or not 1 <= pid <= PID_MAX:
        return True
    try:
        if os.name == "nt":
            import ctypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            k32.OpenProcess.restype = ctypes.c_void_p
            k32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
            k32.GetExitCodeProcess.argtypes = (ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32))
            k32.CloseHandle.argtypes = (ctypes.c_void_p,)
            h = k32.OpenProcess(0x1000, 0, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER: no such pid
            try:
                code = ctypes.c_uint32()
                if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                    return True
                return code.value == 259  # STILL_ACTIVE
            finally:
                k32.CloseHandle(h)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
    except (OverflowError, ValueError, OSError, ImportError, AttributeError):
        return True
    return True


def dead_owner(run, path):
    """-> the pid recorded in the lock file at `path` when no process with it
    exists (the run was killed: a harness kill skips `finally`), else None. An
    unreadable lock, or one without an integer pid, is never dead."""
    try:
        with open(str(path), "rb") as fh:
            pid = json.loads(fh.read().decode("utf-8")).get("pid")
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not isinstance(pid, int) or isinstance(pid, bool) or not 1 <= pid <= PID_MAX:
        return None
    alive = getattr(run.ctx, "pid_alive", None) or pid_alive
    return None if alive(pid) else pid


def reclaim_stale_lock(run, path, pid):
    """Removes the lock at `path` that this run saw owned by the dead `pid`.
    Only the holder of a reclaim mutex (`<lock>.reclaim`, created O_EXCL) may
    remove a lock, so two runs that both saw the dead lock never both act on
    it: a run that finds the mutex taken is refused. Under the mutex the lock
    is read again and removed only if it still names `pid` as a dead owner;
    a lock another run has since created (a live owner) is left alone, and
    the run is refused. Nothing is moved or restored, so there is no window in
    which the lock path is empty while a live lock is set aside. The mutex is
    removed when the decision is made; one left by a killed run is reported,
    never broken. The caller then creates the lock with O_EXCL as usual."""
    mutex = str(path) + RECLAIM_SUFFIX
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        os.close(os.open(mutex, flags, 0o600))
    except FileExistsError:
        raise Precond("%s%s exists: another dream-write.py run is removing a dead lock, or one "
                      "was killed doing so; wait for it, or ask the user to check that none is "
                      "running and to remove the file. Nothing written" % (LOCK, RECLAIM_SUFFIX))
    try:
        if not os.path.lexists(str(path)):
            return  # a run that held the mutex before us removed it; the O_EXCL retry decides
        if dead_owner(run, path) != pid:
            raise Precond(lock_refusal(run, path))
        os.unlink(str(path))
        run.notes.append("%s: removed the lock of pid %d, which no longer runs (killed)"
                         % (LOCK, pid))
    finally:
        with contextlib.suppress(OSError):
            os.unlink(mutex)


@contextlib.contextmanager
def write_lock(run):
    """An exclusive lock file for the run of one write subcommand (P7): created
    with O_EXCL, removed in `finally`, so two writers of applied-ops.json,
    hashes.json and commits.json never interleave. The file records the
    owner's pid: a harness that kills the process skips `finally`, so a lock
    whose pid no longer runs is removed and the run goes on (a lock of a live
    pid, or one with no readable pid, is refused as before)."""
    path = run.work / LOCK
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(path), flags, 0o600)
    except FileExistsError:
        dead = dead_owner(run, path)
        if dead is None:
            raise Precond(lock_refusal(run, path))
        reclaim_stale_lock(run, path, dead)
        try:
            fd = os.open(str(path), flags, 0o600)
        except FileExistsError:
            raise Precond(lock_refusal(run, path))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(json.dumps({"pid": os.getpid(), "at": run.now}).encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        yield
    finally:
        with contextlib.suppress(OSError):
            os.unlink(str(path))


def guard_check(run):
    """Exit 3 when the guard digest of the scripts differs from the one the
    orchestrator holds (D27): --guard-digest when given (the digest `guard
    --rebaseline` printed), else the bound Orient snapshot's guard_digest.
    sweep/guard-hashes.json only names the changed scripts in the message."""
    want = run.guard_digest
    if want is not None:
        want = want.strip().lower()
        if not ds.SHA256_RE.match(want):
            raise Usage("--guard-digest takes a 64-hex sha256")
    else:
        want = run.dirty.get("guard_digest")
        if not isinstance(want, str) or not ds.SHA256_RE.match(want):
            raise Precond("the Orient snapshot holds no guard digest")
    files = ds.guard_files(getattr(run.ctx, "scripts_dir", None))
    if ds.guard_digest(files) != want:
        gh = ds.load_json(run.work / ds.GUARD_HASHES)
        old = (gh.get("files") if isinstance(gh, dict) else None) or {}
        names = sorted(k for k in set(files) | set(old) if files.get(k) != old.get(k))
        raise Precond("guard scripts changed since Orient: %s; nothing written (a phase agent "
                      "writes a guard-changed needs-decision)" % (", ".join(names) or "?"))


def _real(p):
    return ds.nk(os.path.realpath(str(p)))


def store_repo_failed(run):
    """-> why, when the store repo cannot be used for writes, else None: the manifest reported it unreadable
    (a line of top-level errors[] opening with dm.STORE_REPO_UNREADABLE, so a manifest taken while it was
    unreadable is honoured even if it reads again now), or a scan of it fails now, a store repo missing from
    this machine included (the reason then opens with the resolver's MISSING_ROOT)."""
    for e in run.man.get("errors") or []:
        if isinstance(e, str) and e.startswith(dm.STORE_REPO_UNREADABLE):
            return e[len(dm.STORE_REPO_UNREADABLE):].split(";")[0].strip() or "unreadable"
    st, _valid, _invalid, why = dm.resolver().scan_stores()
    if st != "ok":
        return why or "unreadable"
    return None


def allowed_targets(run):
    """-> ({realpath key: (kind, anchor)}, topics dir realpath key).

    A project's memory file is a target only under the store repo: the sweep never writes an in-workspace
    copy (memory-rules.md § Resolution contract). While the store repo is missing or unreadable
    (store_repo_failed), such a copy is listed with kind "store-unreadable" and the reason as its anchor, so
    check_target's refusal names the cause; otherwise it is not listed at all. A file under the store repo is
    unaffected."""
    out = {}
    failed = store_repo_failed(run)
    store_root = dm.resolver().store_repo_root()
    repo = run.repo
    mem = repo / "memory"
    for name, kind in (("MEMORY.md", "memory"), ("HIGHER_ORDER.md", "memory"),
                       (".dream-state.json", "state"), (".dream-journal.jsonl", "journal")):
        out[_real(mem / name)] = (kind, repo)
    for path, proj in run.man["projects"].items():
        mf = proj.get("memory_file") if isinstance(proj, dict) else None
        if isinstance(mf, str):
            if Path(mf).name != "MEMORY.md" or Path(mf).parent.name != "memory":
                continue
            if not dm.is_inside(mf, store_root):
                if failed is not None and dm.is_inside(mf, path):
                    out.setdefault(_real(mf), ("store-unreadable", failed))
                continue    # an in-workspace copy (or a file elsewhere) is never a target
            out.setdefault(_real(mf), ("memory", store_root))
        elif isinstance(proj, dict) and proj.get("status") != "removed" \
                and os.path.isdir(str(path)):
            kind, sdir, _why = ds.store_for(repo, path)
            if kind != "store":
                continue    # no store (none) or the store repo cannot be read (failed): no target
            # The anchor is the tree the file may sit under: the store repo.
            anchor = dm.resolver().store_repo_root()
            out.setdefault(_real(sdir / "memory" / "MEMORY.md"), ("memory", anchor))
            # the STORE file the first write may create (ensure_store); committed with the file
            # kind "store": committable (commit_refusal) but never a memedit target (check_target "memory")
            out.setdefault(_real(sdir / dm.resolver().STORE_FILE), ("store", anchor))
    for f in ds.user_memory_detail(run.work, run.man).get("files") or []:
        if isinstance(f, str) and Path(f).name == "MEMORY.md" and _real(Path(f).parent) == \
                _real(mem):
            out.setdefault(_real(f), ("memory", repo))
    # manifest.json is not bound (review S11): a target it alone names must
    # also be a candidate of the bound Orient snapshot. The config repo's
    # fixed files and topics/*.md hang off the snapshot's own repo.
    cands = {_real(c) for c in run.dirty.get("candidates") or {}}
    fixed = {_real(mem / n) for n in ("MEMORY.md", "HIGHER_ORDER.md", ".dream-state.json",
                                      ".dream-journal.jsonl")}
    out = {k: v for k, v in out.items() if k in fixed or k in cands}
    return out, _real(mem / "topics")


def check_target(run, path, want=None):
    """-> (kind, native path) of an allowed target, else Precond."""
    if not isinstance(path, str) or not os.path.isabs(path):
        raise Precond("refused: %r is not an absolute path" % ascii_safe(path))
    allowed, topics = allowed_targets(run)
    rk = _real(path)
    hit = allowed.get(rk)
    if hit is None:
        p = Path(os.path.realpath(path))
        if ds.nk(p.parent) == topics and p.suffix == ".md":
            hit = ("memory", run.repo)
    if hit is None:
        raise Precond("refused: %s is outside the write allowlist" % path)
    kind, anchor = hit
    if kind == "store-unreadable":
        if str(anchor).startswith(dm.resolver().MISSING_ROOT):
            raise Precond("refused: %s, so %s, a copy of the project's memory outside the store repo, is not "
                          "written (the sweep writes project memory only in the store repo); clone it, then run "
                          "the write again" % (anchor, path))
        raise Precond("refused: the store repo cannot be read (%s), so %s, a copy of the project's memory "
                      "outside the store repo, may be stale and is not written; resolve it with /qconfig-sync, then "
                      "run the write again" % (anchor, path))
    if want is not None and kind != want:
        raise Precond("refused: %s is a %s target, not %s" % (path, kind, want))
    probe, where = Path(path), anchor
    if ds.nk(anchor) == ds.nk(run.repo):
        # User memory sits behind the config repo's one sanctioned `memory` link (ds.memory_link): check
        # the mapped path under the link's target, so any other link on the way is still refused.
        real = ds.memory_link(run.repo)
        mapped = Path(ds.via_memory_link(path))
        if real is not None and mapped != probe:
            probe, where = mapped, real
    link = ds._link_on_path(where, probe)
    if link is not None:
        raise Precond("refused: %s is reached through a link (%s)" % (path, link))
    if not dm.is_inside(str(probe), where):
        raise Precond("refused: %s is not under %s" % (path, where))
    return kind, ds.native(path)


def store_operation(sroot):
    """The git operation the store repo `sroot` is stopped in (its .git marker name), or None. Read from the
    files git leaves in .git, so it needs no git call (the store repo is never a linked worktree)."""
    g = os.path.join(str(sroot), ".git")
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if os.path.lexists(os.path.join(g, name)):
            return name
    return None


def refuse_mid_operation(ops):
    """Refuse before the first write when any op's file is in the store repo and the store repo is stopped
    mid-operation: the edit would land in a conflicted working tree, and the user's `rebase --continue` or
    `--abort` would then fold it into the resolution or drop it. The commit step refuses too (in_progress);
    this stops the write itself."""
    sroot = dm.resolver().store_repo_root()
    if not any(dm.is_inside(o["file"], str(sroot)) for o in ops):
        return
    busy = store_operation(sroot)
    if busy:
        raise Precond("refused: the store repo %s is stopped mid-operation (%s present); a memory write now would "
                      "land in its conflicted working tree. Finish it (/qconfig-sync Step 2b), then run the write "
                      "again" % (sroot, busy))


def ensure_store(run, path):
    """plan 261016 Phase 5, first writes. A memory file in the store repo whose store does not exist yet is
    the first write that needs it: the store resolver creates the store (find_or_create writes the STORE
    file and nothing else, no git) for the one manifest project that resolves to that directory; refused
    when the store repo cannot be read (the real cause is named, since no project can then be matched) or
    when the directory names no such project. Then the file's folder is made, here and for a store that
    already exists but holds no memory/ yet. Any other file is left alone."""
    mem = Path(path)
    if mem.name != "MEMORY.md" or mem.parent.name != "memory":
        return
    sdir = mem.parent.parent
    R = dm.resolver()
    if ds.nk(sdir.parent) != ds.nk(R.store_repo_root()):
        return
    if sdir.name == R.USER_DIR:
        mem.parent.mkdir(parents=True, exist_ok=True)   # user-tier memory: the reserved user/, never a store
        return
    if not os.path.isfile(str(sdir / R.STORE_FILE)):
        scan, _valid, _invalid, why = R.scan_stores()
        if scan != "ok":
            raise Precond("refused: the store repo cannot be read (%s), so the new store %s cannot be created or "
                          "matched to a project; resolve it with /qconfig-sync, then run the write again"
                          % (why, sdir))
        for proj, rec in run.man["projects"].items():
            if not isinstance(rec, dict) or rec.get("status") == "removed" or not os.path.isdir(str(proj)):
                continue
            kind, where, _why = ds.store_for(run.repo, proj)
            if kind != "store" or where is None or ds.nk(where) != ds.nk(sdir):
                continue
            made = R.find_or_create(str(proj), "memory")
            if made.status in ("found", "created") and made.path is not None and ds.nk(made.path) == ds.nk(sdir):
                break
            raise Precond("refused: the store for %s could not be created (%s: %s)"
                          % (proj, made.status, made.reason or "no reason given"))
        else:
            raise Precond("refused: %s is a new store in the store repo, but no project of the manifest "
                          "resolves to it" % sdir)
    mem.parent.mkdir(parents=True, exist_ok=True)


def record_store_file(run, path):
    """plan 261016 Phase 5 review F4. The STORE file ensure_store created is a file the sweep wrote, so it is
    recorded like the memory file beside it (created_by_sweep) and the closing commit takes it by pathspec.
    Recorded only when the Orient snapshot saw it absent, so a store that already existed is not claimed;
    idempotent, and run again on a resumed op, so a stop between the creation and the record is repaired."""
    mem = Path(path)
    if mem.name != "MEMORY.md" or mem.parent.name != "memory":
        return
    R = dm.resolver()
    sdir = mem.parent.parent
    store = sdir / R.STORE_FILE
    if ds.nk(sdir.parent) != ds.nk(R.store_repo_root()) or not os.path.isfile(str(store)):
        return
    if orient_record(run, str(store))[0] != "absent":
        return
    record_hash(run, str(store), "memory", "memedit", created=True)


def atomic_write(path, data):
    """temp file in the same directory, fsync, os.replace with a bounded
    retry on a Windows sharing violation."""
    target = Path(path)
    if os.path.islink(str(target)) or ds._isjunction(target):
        raise Precond("refused: %s is a link" % target)
    mode = 0o644
    if os.path.isfile(str(target)):
        mode = os.stat(str(target)).st_mode & 0o777
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) \
        | getattr(os, "O_BINARY", 0)
    tmp = None
    for _ in range(20):
        cand = target.parent / (".%s.%s.tmp" % (target.name, os.urandom(6).hex()))
        try:
            fd = os.open(str(cand), flags, mode)
        except FileExistsError:
            continue
        tmp = cand
        break
    if tmp is None:
        raise Precond("could not create a temp file beside %s" % target)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        _replace(tmp, target)
        tmp = None
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(str(tmp))


def _replace(src, dst):
    for attempt in range(10):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError as e:
            if getattr(e, "winerror", None) not in (5, 32) or attempt == 9:
                raise
            time.sleep(0.05 * (attempt + 1))


def temp_beside(path, data):
    target = Path(path)
    fd, tmp = ds._temp_beside(target)
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    return tmp


# --------------------------------------------------------------------------
# Records
# --------------------------------------------------------------------------

def load_rec(run, rel, default):
    p = run.work / rel
    if not os.path.lexists(str(p)):
        return json.loads(json.dumps(default))
    obj = ds.load_json(p)
    if not isinstance(obj, dict):
        raise Precond("%s is unreadable" % rel)
    return json.loads(json.dumps(obj))


def save_rec(run, rel, obj):
    ds.put(run.work, rel, ds.dumps(obj))


def hash_records(run):
    h = load_rec(run, HASHES, {"version": 1, "files": {}})
    if not isinstance(h.get("files"), dict):
        raise Precond("%s has no files object" % HASHES)
    return h


def find_hash(h, path):
    k = ds.nk(path)
    for p, rec in h["files"].items():
        if ds.nk(p) == k:
            return p, rec
    return None, None


def record_hash(run, path, kind, by, decisions_sha=None, foreign=None, created=None):
    h = hash_records(run)
    old_key, prev = find_hash(h, path)
    prev = prev or {}
    if old_key is not None:
        del h["files"][old_key]
    rec = {"sha256": ds.sha256_file(path), "kind": kind, "by": by, "at": run.now,
           "foreign_edit": bool(prev.get("foreign_edit")) if foreign is None
           else bool(foreign or prev.get("foreign_edit")),
           "decisions_sha": decisions_sha or prev.get("decisions_sha"),
           "created_by_sweep": bool(prev.get("created_by_sweep")) if created is None
           else bool(created or prev.get("created_by_sweep"))}
    h["files"][ds.native(path)] = rec
    save_rec(run, HASHES, h)
    return rec


def orient_record(run, path):
    """-> (orient sha256 | "absent" | None (unknown), how)."""
    k = ds.nk(path)
    for c, rec in (run.dirty.get("candidates") or {}).items():
        if ds.nk(c) == k and isinstance(rec, dict):
            return rec.get("sha256"), "candidate"
    top = ds.toplevel(path)
    if top is None:
        return None, "not-a-repo"
    info = repo_snapshot(run, top)
    if info is None or info.get("porcelain") is None or not info.get("head"):
        return None, "no snapshot of its repo"
    rel = ds.rel_in(top, path)
    if porcelain_covers(info["porcelain"], rel):
        return None, "dirty at Orient"
    return ds.orient_blob_sha(top, info["head"], rel), "blob"


def repo_snapshot(run, top):
    for r, info in (run.dirty.get("repos") or {}).items():
        if ds.nk(r) == ds.nk(top):
            return info
    return None


porcelain_covers = ds.porcelain_covers


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------

def load_decisions(run, given, sha, required=True):
    """-> (decisions.json object, sha) bound to sha (D24), or (None, None)."""
    if given is None and sha is None:
        if required:
            raise Usage("--decisions-sha is required")
        return None, None
    if sha is None:
        raise Usage("--decisions needs --decisions-sha")
    path = ds.handoff_path(run.work, given or "handoff/decisions.json")
    rel = os.path.relpath(str(path), str(run.work)).replace("\\", "/")
    obj = ds.load_bound(run.work, rel, sha, flag="--decisions-sha")
    if not isinstance(obj, dict) or not isinstance(obj.get("items"), list) \
            or not all(isinstance(i, dict) for i in obj["items"]):
        raise Precond("%s needs an items list of objects" % path.name)
    check_items(obj, path.name, gov_policy(run))
    return obj, sha.strip().lower()


def decision_item(dec, did):
    hits = [i for i in (dec or {}).get("items", []) if i.get("id") == did]
    return hits[0] if len(hits) == 1 else None


def option_of(item):
    """The item's normalized option: its `option` (what the orchestrator
    writes next to the verbatim `answer`), else the answer normalized."""
    return norm_opt(item["option"] if "option" in item else item.get("answer", ""))


def item_problems(dec, complete=False, policy=None):
    """-> [problem, ...] for decisions.json: every item has a unique id, a
    kind of the D28 table, a string answer, an `option` (when present) that
    is a string, a known `variant` and an option of its kind; ids are unique;
    `for_conflict`, when present, is null or the id of a `conflict` item;
    `skip_item`, when present, is true and sits on a governance or retirement
    item answered Skip;
    `track`, when present, is a list of absolute paths (inside the config
    repository or a manifest project root, given a policy). An Applied
    governance or retirement item writes only a governance or skill text
    file: its target_file and each blast edit's path pass
    ds.gov_path_problem (a .md file, no memory component, inside the
    repositories, and, given a policy, a blast hit of the item or its
    target_file). The policy (ds.GovPolicy) carries the repository context;
    without one only the syntactic rules apply.
    An Applied governance or retirement item is always checked whole (at the
    gate and at every load): it names `target_file` and `new_text` and a
    placeable current_text (non-empty, or null with an after_heading), as does
    each of its blast edits; a target absent at Orient (given a policy holding
    the snapshot) is written only as `create: true`, with current_text and
    after_heading null, and `create: true` is refused on a file that existed
    (ds.new_file_problem).
    With `complete` (the handoff check at the gate) an item whose option
    authorizes a memory op also names `file` and `heading`, `shown_text` for
    an op that writes text and `to_file` for a budget-move."""
    out, seen = [], set()
    out += track_problems(dec, policy)
    conflicts = {i.get("id") for i in dec["items"] if i.get("kind") == "conflict"}
    for n, it in enumerate(dec["items"], 1):
        iid, kind = it.get("id"), it.get("kind")
        if not isinstance(iid, str) or not iid or iid in seen:
            out.append("item %d has no unique id" % n)
            continue
        seen.add(iid)
        if kind not in D28_TABLE:
            out.append("item %s: unknown kind %r (D28 table)" % (iid, ascii_safe(kind, 40)))
            continue
        if not isinstance(it.get("answer"), str) or (
                "option" in it and not isinstance(it["option"], str)):
            out.append("item %s: answer and option must be strings" % iid)
            continue
        var = it.get("variant")
        if var is not None and (kind, var) not in D28_VARIANTS:
            out.append("item %s: %r is not a variant of %s" % (iid, ascii_safe(var, 40), kind))
            continue
        if option_of(it) not in D28_TABLE[kind]:
            out.append("item %s: %r is not a %s option (write the normalized option in "
                       "`option`: %s)" % (iid, ascii_safe(it.get("option", it["answer"]), 40),
                                          kind, ", ".join(sorted(D28_TABLE[kind]))))
            continue
        # `option` is the orchestrator's mapping of the user's words (a trust
        # root the scripts cannot check); an answer that is itself another
        # option of the kind contradicts it.
        said = norm_opt(it["answer"])
        if "option" in it and said != option_of(it) and said in D28_TABLE[kind]:
            out.append("item %s: option %r contradicts the answer %r (another %s option)"
                       % (iid, ascii_safe(it["option"], 40), ascii_safe(it["answer"], 40), kind))
            continue
        why = promotes_problem(it)
        if why:
            out.append("item %s: %s" % (iid, why))
            continue
        fc = it.get("for_conflict")
        if fc is not None and fc not in conflicts:
            out.append("item %s: for_conflict %r names no conflict item" % (iid,
                                                                          ascii_safe(fc, 40)))
            continue
        if "skip_item" in it and (it["skip_item"] is not True
                                  or kind not in GOVERNANCE_KINDS or option_of(it) != "skip"):
            out.append("item %s: skip_item is true only on a governance or retirement item "
                       "answered Skip" % iid)
            continue
        if kind in GOVERNANCE_KINDS and option_of(it) == "apply":
            bad = ds.gov_item_problems(it, policy)
            if bad:
                out += ["item %s: %s" % (iid, b) for b in bad]
                continue
        if not complete:
            continue
        slots = slots_of(it)
        types = {t for sl in slots for t in sl}
        need = []
        if types:
            need += ["file", "heading"]
        if types & {"insert", "replace", "append_lines", "create"}:
            need.append("shown_text")
        if kind == "budget-move":
            need.append("to_file")
        out += ["item %s: option %r needs %r" % (iid, option_of(it), f) for f in need
                if not (isinstance(it.get(f), str) and it[f].strip())]
    return out


def track_problems(dec, policy=None):
    """-> [problem, ...] for decisions.json's top-level `track` (the paths the
    git-tracking question answered yes for; `commit` reads it and takes no
    path from its caller): a list of absolute path strings, each inside the
    config repository, a manifest project root or the store repo (plan 261016 Phase 5: the first memory
    file of a new store sits there) when a policy is given. Only an allowlisted memory target is ever
    committed (commit_refusal), whatever the list names."""
    track = dec.get("track")
    if track is None:
        return []
    if not isinstance(track, list):
        return ["track must be a list of absolute paths"]
    out = []
    for i, t in enumerate(track):
        if not (isinstance(t, str) and t.strip() and os.path.isabs(t) and "\0" not in t):
            out.append("track[%d] is not an absolute path" % i)
        elif policy is not None and not any(dm.is_inside(t, r) for r in
                                            list(policy.roots) + [dm.resolver().store_repo_root()]):
            out.append("track[%d] is outside the config repository, the manifest's project "
                       "roots and the store repo" % i)
    return out


def gov_policy(run):
    """The repository context of a governance edit's path rules (ds.GovPolicy),
    with every memory target of the write allowlist as a memory file."""
    if getattr(run, "_gov_policy", None) is None:
        run._gov_policy = ds.GovPolicy.build(run.work, run.man, run.repo,
                                             extra_memfiles=set(allowed_targets(run)[0]),
                                             dirty=run.dirty)
    return run._gov_policy


def check_items(dec, name, policy=None):
    """Precond naming the first item_problems entry."""
    probs = item_problems(dec, policy=policy)
    if probs:
        raise Precond("refused: %s %s" % (name, probs[0]))


def slots_of(item):
    """-> the op slots the item's option authorizes (a tuple of op-type
    tuples), under its variant."""
    opt = option_of(item)
    var = D28_VARIANTS.get((item["kind"], item.get("variant")), {})
    return var[opt] if opt in var else D28_TABLE[item["kind"]][opt]


def fits(slots, types):
    """The op types fill distinct slots, one each (count-limited)."""
    if len(types) > len(slots):
        return False
    for perm in itertools.permutations(range(len(slots)), len(types)):
        if all(t in slots[i] for t, i in zip(types, perm)):
            return True
    return False


def _same_text(a, b):
    return isinstance(a, str) and isinstance(b, str) and \
        a.rstrip("\r\n") == b.rstrip("\r\n")


def text_heading(text):
    first = EOL_RE.split(text)[0] if isinstance(text, str) else ""
    return first[4:].strip() if first.startswith("### ") else None


def op_new_text(o):
    """The text an op writes (its heading excluded): for the human: check."""
    parts = [o.get("text"), o.get("row")]
    if isinstance(o.get("lines"), list):
        parts += o["lines"]
    return "\n".join(x for x in parts if isinstance(x, str))


def node_file(run):
    """The one file a node (a higher-order memory entry) lives in."""
    return run.repo / "memory" / "HIGHER_ORDER.md"


def user_tier(run, path):
    """path lies under <config repo>/memory/: user memory, its topic files and
    HIGHER_ORDER.md. A project's memory file, a store's included, does not."""
    return dm.is_inside(Path(ds.native(path)), Path(ds.native(run.repo / "memory")))


FIELD_RE = re.compile(r"(?m)^[ \t]*\*\*(?:Affirmed|Governance-conflict(?:-quote)?)\*\*:.*$")
NONTERMINAL_RE = re.compile(
    r"\*\*Governance-conflict\*\*:[^\n]*\b(?:rule-update-pending|deferred)\b")
# The `Outcome:` field's whole value grammar (memory-rules.md, Cross-type optional
# metadata): `recurred|not-recurred <date>`. A segment that is anything more is
# not a stamp, so nothing else can ride in it (N1: a `| **Verified**: ... (human:x)`
# tail on the line form was stripped with the field and so never compared).
OUTCOME_VAL = r"\*\*Outcome\*\*: (?:not-)?recurred \d{4}-\d{2}-\d{2}"
OUTCOME_RE = re.compile(
    r"[ \t]*\|[ \t]*" + OUTCOME_VAL + r"(?=[ \t]*(?:\||$))|^[ \t]*" + OUTCOME_VAL + r"[ \t]*$\n?",
    re.M)
# The `Governance-conflict` record of a conflict item (its answers write this and only this).
CONFLICT_RE = re.compile(r"[ \t]*\*\*Governance-conflict(?:-quote)?\*\*:")
STALE_FIELD_RE = re.compile(r"[ \t]*\*\*Stale-(?:after|when)\*\*:")
# The Source/Verified line of an entry up to the `Verified` value: `Verified` is
# `<date>[ (<actor>[, <method>])]` (memory-rules.md, Memory File Format).
VERIFIED_LINE_RE = re.compile(
    r"^(.*\*\*Verified\*\*:)[ \t]*\d{4}-\d{2}-\d{2}(?:[ \t]*\([^()|]*\))?[ \t]*$")


def outcome_stamp_only(old_body, new_text):
    """new_text is old_body with only its `Outcome:` field set or changed (the
    sweep's autonomous stamp): equal once both lose a field of the Outcome
    value grammar."""
    def strip(t):
        return OUTCOME_RE.sub("", EOL_RE.sub("\n", t)).rstrip("\r\n")
    return strip(old_body) == strip(new_text)


def guarded_lines(text):
    """The Affirmed and Governance-conflict lines of a text, stripped."""
    return {m.group(0).strip() for m in FIELD_RE.finditer(text or "")}


def human_lines(text):
    """The lines of a text that carry a `human:` Verified actor, stripped."""
    return {ln.strip() for ln in EOL_RE.split(text or "") if HUMAN_RE.search(ln)}


def _lines_without(text, rx):
    return [ln for ln in EOL_RE.split(text.rstrip("\r\n")) if not rx.match(ln)]


def conflict_field_only(old_body, o):
    """A conflict answer (not Delete entry) writes only the entry's
    Governance-conflict record: a replace is the old entry once both lose
    those lines; an append_lines is those lines alone."""
    if o["op"] == "append_lines":
        return all(CONFLICT_RE.match(ln) for ln in o["lines"])
    return _lines_without(o["text"], CONFLICT_RE) == _lines_without(old_body, CONFLICT_RE)


def redate_only(old_body, new_text):
    """new_text is old_body re-dated: only the `Verified` value (date and
    annotation, on its Source line) may differ, and `Stale-after` /
    `Stale-when` lines may go (never appear or change)."""
    def view(t):
        out = []
        for ln in EOL_RE.split(t.rstrip("\r\n")):
            if STALE_FIELD_RE.match(ln):
                continue
            m = VERIFIED_LINE_RE.match(ln)
            out.append(m.group(1) if m else ln)
        return out
    def stale(t):
        return {ln.strip() for ln in EOL_RE.split(t) if STALE_FIELD_RE.match(ln)}
    return view(old_body) == view(new_text) and stale(new_text) <= stale(old_body)


def promotes_problem(it):
    """-> None, or why a `promotes` item (a governance or retirement Apply that
    deletes its source entry) is not tied to the edit it promoted into: it
    carries the governance edit (`target_file`, `new_text`) and the proposal the
    user saw (`gate_text`, which DEC-GATE has name the source entry), and that
    proposal names the entry: its gate_text holds, as one line, the
    `Also removes memory entry:` line `dream-sweep.py gate` renders
    (promotes_line there: file and heading JSON-quoted)."""
    if it.get("variant") != "promotes" or option_of(it) != "apply":
        return None
    if not all(isinstance(it.get(f), str) and it[f].strip()
               for f in ("target_file", "new_text", "gate_text", "heading", "file")):
        return "a promotes item needs target_file, new_text, gate_text, file and heading"
    line = "Also removes memory entry: %s § %s" % (
        json.dumps(it["file"], ensure_ascii=False), json.dumps(it["heading"], ensure_ascii=False))
    if line not in re.split(r"\r?\n", it["gate_text"]):
        return "a promotes item's gate_text must name the entry it deletes (%s)" % ascii_safe(line, 120)
    return None


def shape_refusal(item, o, body):
    """The shape of an op that rewrites the entry `body` (None for an insert or
    create), for the answers whose gate showed less than a whole entry. -> None
    or the reason: a conflict answer other than Delete entry writes only the
    Governance-conflict record, and a re-date (a human-expiry Keep or
    Re-date-as-sweep, a stale Keep with variant expiry-only) changes only the
    Verified value and drops Stale-after / Stale-when lines."""
    if body is None or o["op"] not in ("replace", "append_lines"):
        return None
    kind, opt = item["kind"], option_of(item)
    if kind == "conflict" and opt != norm_opt("Delete entry") \
            and not conflict_field_only(body, o):
        return "a conflict answer writes only the Governance-conflict field"
    redate = (kind == "human-expiry" and opt in (norm_opt("Keep"), norm_opt("Re-date-as-sweep"))) \
        or (kind == "stale" and item.get("variant") == "expiry-only")
    if redate and o["op"] == "replace" and not redate_only(body, o["text"]):
        return "a re-date changes only the Verified value and drops Stale-after/Stale-when"
    return None


def authorize_op(run, item, o, body=None):
    """D28 per-op check of an op carrying the item's decision_id (the count
    is checked over all of the decision's ops by decision_counts). `body` is
    the entry a replace or append_lines rewrites. -> None, or the reason it is
    refused."""
    kind = item["kind"]
    types = {t for sl in slots_of(item) for t in sl}
    if o["op"] not in types:
        return "a %s item answered %r authorizes no %s" % (kind, item.get("answer"), o["op"])
    # A node is an entry of HIGHER_ORDER.md and nowhere else: its delete has no
    # map record, so aimed at another file it would delete an entry unseen.
    ho = _real(node_file(run))
    if kind == "node" and not (isinstance(item.get("file"), str) and
                               _real(repo_path(run, item["file"])) == ho):
        return "a node item names memory/HIGHER_ORDER.md only"
    if o["op"] == "delete" and o["class"] == NODE_CLASS and _real(o["file"]) != ho:
        return "a node delete targets memory/HIGHER_ORDER.md only"
    if item.get("variant") == "expiry-only" and not (
            isinstance(item.get("file"), str)
            and user_tier(run, repo_path(run, item["file"]))):
        return "an expiry-only item names a user-memory file only"
    if o["op"] == "delete":
        want = (PROMOTION_CLASSES if kind in GOVERNANCE_KINDS else
                ("Delete entry",) if kind == "conflict" else
                ("pruned",) if kind == "duplicate" else None)
        if want is not None and o["class"] not in want:
            return "a %s item's delete has class %s" % (kind, " or ".join(want))
    if kind == "node" and o["op"] == "append_lines" and not (
            isinstance(item.get("shown_text"), str)
            and AFFIRMED_RE.match(item["shown_text"].strip())):
        return "a node Keep node writes one **Affirmed**: <date> line"
    field = "to_file" if (kind == "budget-move" and o["op"] == "insert") else "file"
    want_file = item.get(field)
    if not isinstance(want_file, str) or ds.nk(repo_path(run, want_file)) != ds.nk(o["file"]):
        return "the item names another file (its %s)" % field
    heading = item.get("heading")
    if not isinstance(heading, str) or not heading.strip():
        return "the item names no heading"
    heading = heading.strip()
    shown = item.get("shown_text")
    if o["op"] in ("delete", "replace", "append_lines") and o["heading"].strip() != heading:
        return "the item names another heading"
    if o["op"] == "delete" and (o["class"] == NODE_CLASS) != (kind == "node"):
        return "a node delete needs a node item, and a node item a node delete"
    if o["op"] == "declined_add" and not o["row"].startswith('- "%s"' % heading):
        return "the Declined row is not for the item's heading"
    if o["op"] in ("replace", "insert") and not _same_text(o["text"], shown):
        return "its text is not the text the gate showed"
    if o["op"] == "append_lines" and not _same_text("\n".join(o["lines"]), shown):
        return "its lines are not the text the gate showed"
    if o["op"] in ("insert", "create") and kind != "harvest-merge" and \
            text_heading(shown if o["op"] == "create" else o["text"]) != heading:
        return "the entry it writes is not the item's heading"
    if o["op"] == "create":
        try:
            doc = Doc(o["text"].encode("utf-8"))
        except Precond as e:
            return str(e)
        entries, _s = spans(doc)
        c = doc.contents()
        if len(entries) != 1 or not _same_text(
                "\n".join(c[entries[0]["start"]:content_end(c, entries[0]["start"],
                                                            entries[0]["end"])]), shown):
            return "the file it creates is not one entry equal to the text the gate showed"
    why = shape_refusal(item, o, body)
    if why:
        return why
    for m in re.finditer(r"[^\n]*" + HUMAN_RE.pattern + r"[^\n]*", op_new_text(o)):
        if not (isinstance(shown, str) and m.group(0).strip() in shown):
            return "its text adds a human: actor the gate did not show"
    return None


def recorded_op_refusal(run, item, rec):
    """push --plan's re-check of an applied-ops.json record under the D28
    table: op type, file and heading (the record keeps no text; memedit
    checked it). -> None or the reason."""
    types = {t for sl in slots_of(item) for t in sl}
    if rec.get("op") not in types:
        return "a %s item answered %r authorizes no %s" % (item["kind"], item.get("answer"),
                                                          rec.get("op"))
    node_del = rec.get("op") == "delete" and rec.get("class") == NODE_CLASS
    if item["kind"] == "node" or node_del:
        if not isinstance(rec.get("file"), str) or _real(rec["file"]) != _real(node_file(run)):
            return "a node op targets memory/HIGHER_ORDER.md only"
    if rec.get("op") == "delete" and node_del != (item["kind"] == "node"):
        return "a node delete needs a node item, and a node item a node delete"
    want = item.get("to_file") if (item["kind"] == "budget-move" and rec.get("op") == "insert") \
        else item.get("file")
    if not isinstance(want, str) or not isinstance(rec.get("file"), str) or \
            ds.nk(repo_path(run, want)) != ds.nk(rec["file"]):
        return "the op's file is not the item's"
    if rec.get("op") in ("delete", "replace", "append_lines") and \
            str(rec.get("heading") or "").strip() != str(item.get("heading") or "").strip():
        return "the op's heading is not the item's"
    return None


def decision_counts(run, dec, ops, applied):
    """-> {op id: reason} for the ops whose decision is over its count: one
    decision authorizes only the ops its slots list, counted over this ops
    file and every op of applied-ops.json carrying the same decision_id
    (by op id, so a re-run never counts an op twice)."""
    by = {}
    for oid, rec in applied["ops"].items():
        if isinstance(rec, dict) and isinstance(rec.get("decision_id"), str):
            by.setdefault(rec["decision_id"], {})[oid] = rec.get("op")
    for o in ops:
        if isinstance(o.get("decision_id"), str):
            by.setdefault(o["decision_id"], {})[o["id"]] = o["op"]
    out = {}
    for did, members in by.items():
        item = decision_item(dec, did) if dec is not None else None
        if item is None:
            continue
        if not fits(slots_of(item), sorted(members.values())):
            for oid in members:
                out[oid] = "decision %s authorizes %d op(s), not these %d" % (
                    did, len(slots_of(item)), len(members))
    return out


def repo_path(run, p):
    return ds.native(p if os.path.isabs(p) else Path(run.repo) / p)


def applied_edits(run, dec):
    """-> {nk(path): [edit, ...]} of every Applied governance edit, in order."""
    out = {}
    for it in (dec or {}).get("items", []):
        if it.get("kind") not in GOVERNANCE_KINDS or option_of(it) != "apply":
            continue
        tf = it.get("target_file")
        if isinstance(tf, str) and ("new_text" in it):
            out.setdefault(ds.nk(repo_path(run, tf)), []).append(
                {"id": it.get("id"), "current_text": it.get("current_text"),
                 "new_text": it.get("new_text"), "after_heading": it.get("after_heading"),
                 "create": it.get("create") is True})
        for be in it.get("blast_edits") or []:
            if isinstance(be, dict) and isinstance(be.get("path"), str):
                out.setdefault(ds.nk(repo_path(run, be["path"])), []).append(
                    {"id": it.get("id"), "current_text": be.get("current_text"),
                     "new_text": be.get("new_text"), "after_heading": be.get("after_heading"),
                     "create": False})
    return out


# --------------------------------------------------------------------------
# Memory files: lines and entry spans
# --------------------------------------------------------------------------

BOM = b"\xef\xbb\xbf"


class Doc:
    """A memory file as [content, ending] pairs, BOM held aside."""

    def __init__(self, data):
        self.bom = data.startswith(BOM)
        raw = data[3:] if self.bom else data
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise Precond("not valid UTF-8 (a lossy read is never rewritten)")
        self.lines = []
        pos = 0
        for m in EOL_RE.finditer(text):
            self.lines.append([text[pos:m.start()], m.group(0)])
            pos = m.end()
        if pos < len(text):
            self.lines.append([text[pos:], ""])
        self.eol = next((e for _c, e in self.lines if e), "\n")

    def text(self):
        return "".join(c + e for c, e in self.lines)

    def data(self):
        return (BOM if self.bom else b"") + self.text().encode("utf-8")

    def contents(self):
        return [c for c, _e in self.lines]

    def insert(self, idx, new):
        if not new:
            return
        if idx == len(self.lines) and self.lines and self.lines[-1][1] == "":
            self.lines[-1][1] = self.eol
        self.lines[idx:idx] = [[c, self.eol] for c in new]


def walk(contents):
    """Entry and section spans by the parse_entries rules: -> (entries,
    sections); entry {heading, section, start, end}, section {name, start,
    end}; end exclusive."""
    entries, sections = [], []
    fence, section, cur, sec = None, None, None, None
    for i, line in enumerate(contents):
        if i == 0 and line.startswith("\ufeff"):
            # memory-entries.py drops a leading BOM: here a second one, Doc holding the first aside.
            line = line[1:]
        fm = dm.memory_entries().FENCE_RE.match(line)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        if line.startswith("# ") or line.startswith("## "):
            if cur is not None:
                cur["end"] = i
                entries.append(cur)
                cur = None
            if sec is not None:
                sec["end"] = i
                sections.append(sec)
                sec = None
            section = line.strip() if line.startswith("## ") else None
            if section is not None:
                sec = {"name": section, "start": i}
            continue
        if line.startswith("### "):
            if cur is not None:
                cur["end"] = i
                entries.append(cur)
                cur = None
            if section in dm.TYPE_SECTIONS:
                cur = {"heading": line[4:].strip(), "section": section, "start": i}
    n = len(contents)
    if cur is not None:
        cur["end"] = n
        entries.append(cur)
    if sec is not None:
        sec["end"] = n
        sections.append(sec)
    return entries, sections


def spans(doc):
    entries, sections = walk(doc.contents())
    want = [h for h, _b in dm.parse_entries(doc.text())]
    if [e["heading"] for e in entries] != want:
        raise OpError("span walker disagrees with parse_entries (not edited)")
    return entries, sections


def content_end(contents, start, end):
    j = end
    while j > start + 1 and not contents[j - 1].strip():
        j -= 1
    return j


def declined_blocks(doc):
    _e, sections = walk(doc.contents())
    return ["".join(c + e for c, e in doc.lines[s["start"]:s["end"]])
            for s in sections if s["name"] == "## Declined"]


def norm_section(s):
    s = " ".join(str(s).split())
    return s if s.startswith("## ") else "## " + s


def find_entry(doc, op):
    entries, _s = spans(doc)
    hits = [e for e in entries if e["heading"] == op["heading"].strip()]
    if op.get("section") is not None:
        sec = norm_section(op["section"])
        inside = [e for e in hits if e["section"] == sec]
        if hits and not inside:
            raise OpError("heading %r is not in %s" % (ascii_safe(op["heading"], 60), sec))
        hits = inside
    if not hits:
        raise OpError("heading %r not found in a type section" % ascii_safe(op["heading"], 60))
    if len(hits) > 1:
        raise OpError("heading %r is ambiguous (%d matches)" % (ascii_safe(op["heading"], 60),
                                                               len(hits)))
    return hits[0]


class OpError(Exception):
    pass


def entry_lines(text):
    """An entry's text -> its lines; the first must be a `### ` heading and
    no other line (outside fences) may be a heading."""
    lines = EOL_RE.split(text.rstrip("\r\n"))
    if not lines or not lines[0].startswith("### ") or not lines[0][4:].strip():
        raise OpError("an entry's text must start with a `### ` heading line")
    fence = None
    for ln in lines[1:]:
        fm = dm.memory_entries().FENCE_RE.match(ln)
        if fence:
            if fm and fm.group(1) == fence:
                fence = None
            continue
        if fm:
            fence = fm.group(1)
            continue
        if ln.startswith("#"):
            raise OpError("an entry's text holds a heading line after its first")
    return lines


def apply_op(doc, op):
    """Mutates doc for one op; OpError on a refusal. -> the entry it touched
    (for the human-attested check) or None."""
    kind = op["op"]
    c = doc.contents()
    if kind == "create":
        raise OpError("create runs on an absent file only")
    if kind == "declined_add":
        row = op["row"]
        if "\n" in row or "\r" in row or not row.startswith('- "'):
            raise OpError('a Declined row is one line starting with - "')
        _e, sections = walk(c)
        dec = [s for s in sections if s["name"] == "## Declined"]
        if len(dec) > 1:
            raise OpError("the file holds %d ## Declined sections" % len(dec))
        if not dec:
            new = ([""] if c and c[-1].strip() else []) + ["## Declined", "", row]
            doc.insert(len(doc.lines), new)
            return None
        s = dec[0]
        j = content_end(c, s["start"], s["end"])
        doc.insert(j, (["", row] if j == s["start"] + 1 else [row]))
        return None
    if kind == "insert":
        lines = entry_lines(op["text"])
        sec = norm_section(op["section"])
        if sec not in dm.TYPE_SECTIONS:
            raise OpError("%s is not a type section" % sec)
        entries, sections = spans(doc)
        hits = [s for s in sections if s["name"] == sec]
        if len(hits) != 1:
            raise OpError("%s appears %d times (insert needs exactly one)" % (sec, len(hits)))
        new_h = lines[0][4:].strip()
        if any(e["heading"] == new_h for e in entries):
            raise OpError("heading %r already exists" % ascii_safe(new_h, 60))
        s = hits[0]
        j = content_end(c, s["start"], s["end"])
        new = ([""] if c[j - 1].strip() else []) + lines
        if j == len(c) or (j < len(c) and c[j].strip()):
            new += [""] if j < len(c) else []
        doc.insert(j, new)
        return None
    e = find_entry(doc, op)
    j = content_end(c, e["start"], e["end"])
    if kind == "delete":
        del doc.lines[e["start"]:e["end"]]
    elif kind == "replace":
        lines = entry_lines(op["text"])
        new_h = lines[0][4:].strip()
        entries, _s = spans(doc)
        if new_h != e["heading"] and any(x["heading"] == new_h for x in entries):
            raise OpError("new heading %r already exists" % ascii_safe(new_h, 60))
        last_end = doc.lines[j - 1][1]
        doc.lines[e["start"]:j] = [[ln, doc.eol] for ln in lines]
        doc.lines[e["start"] + len(lines) - 1][1] = last_end
    elif kind == "append_lines":
        lines = op["lines"]
        if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines) or \
                any(x.startswith("#") or "\n" in x or "\r" in x for x in lines):
            raise OpError("lines must be single lines, none a heading")
        doc.insert(j, list(lines))
    elif kind == "usage_bump":
        fence, src = None, None
        for i in range(e["start"] + 1, j):
            ln = c[i]
            fm = dm.memory_entries().FENCE_RE.match(ln)
            if fence:
                if fm and fm.group(1) == fence:
                    fence = None
                continue
            if fm:
                fence = fm.group(1)
                continue
            m = USAGE_RE.match(ln)
            if m:
                doc.lines[i][0] = m.group(1) + str(int(m.group(2)) + 1) + ln[m.end():]
                return e
            if src is None and SOURCE_RE.match(ln):
                src = i
        doc.insert(src + 1 if src is not None else j, ["**Usage**: 1"])
    return e


def op_texts(op):
    parts = [op.get("heading"), op.get("text"), op.get("row")]
    if isinstance(op.get("lines"), list):
        parts += op["lines"]
    return "\n".join(str(p) for p in parts if isinstance(p, str))


def fq_target(run, path, heading):
    k = ds.nk(path)
    mem = run.repo / "memory"
    if k == ds.nk(mem / "MEMORY.md") or ds.nk(Path(path).parent) == ds.nk(mem / "topics"):
        return "user memory § %s" % heading
    for p, proj in run.man["projects"].items():
        mf = proj.get("memory_file") if isinstance(proj, dict) else None
        if isinstance(mf, str) and ds.nk(mf) == k:
            return "project memory (%s) § %s" % (proj.get("state_key") or p, heading)
    return None


def journal_problems(text):
    """The verify-dream-journal grammar (memory-rules.md § Crash-recovery
    journal), checked in-process on every flush."""
    probs = []
    for n, line in enumerate(text.split("\n"), 1):
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            probs.append("line %d is not JSON" % n)
            continue
        if not isinstance(obj, dict) or len(obj) != 1 or next(iter(obj)) not in ("rename",
                                                                                "remove"):
            probs.append("line %d: one key, rename or remove" % n)
            continue
        key, val = next(iter(obj.items()))
        if not (isinstance(val, list) and len(val) == 2 and all(
                isinstance(v, str) and v for v in val)):
            probs.append("line %d: a 2-element array of non-empty strings" % n)
            continue
        fq = val if key == "rename" else val[:1]
        if not all(v.startswith(FQ_PREFIXES) for v in fq):
            probs.append("line %d: target not fully qualified" % n)
        if key == "remove" and val[1] not in REMOVAL_CLASSES:
            probs.append("line %d: unknown removal class" % n)
    return probs


# --------------------------------------------------------------------------
# Validators
# --------------------------------------------------------------------------

def run_validator(run, kind, target, baseline=None):
    """-> (passed, output tail). passed is True on exit 0, False on exit 1, and None when the
    validator did not run: a launch failure, a timeout, any other exit code, a target that exists
    but is not a regular file, or (either kind) an exit 0 whose output is a SKIP line while the
    target exists, or has neither that validator's summary line nor a SKIP line. An exit 0 SKIP
    over a missing target stays a pass.
    ctx.validator, when set, replaces the launch: an attribute only the
    selftest sets (dm.Ctx has none; no CLI flag reaches it)."""
    hook = getattr(run.ctx, "validator", None)
    if hook is not None:
        return hook(kind, target, baseline)
    vdir = Path(getattr(run.ctx, "validator_dir", None) or getattr(run.ctx, "scripts_dir", None)
                or HERE)
    # plan 261016 Phases 13-14: both validators are one Python script on every platform, run by this
    # interpreter (the playbook venv) in isolated mode. Only the state validator takes a ledger
    # baseline (the journal has none: no caller passes one).
    script = vdir / ("verify-dream-%s.py" % kind)
    cmd = [sys.executable, "-I", str(script)]
    if kind == "state" and baseline is not None:
        cmd += ["--ledger-baseline", str(baseline)]
    cmd += [str(target)]
    if not script.is_file():
        return None, "validator %s not found" % script.name
    try:
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=VALIDATOR_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, "validator timed out after %d s" % VALIDATOR_TIMEOUT
    except OSError as e:
        return None, "validator could not launch: %s" % type(e).__name__
    out = r.stdout.decode("utf-8", "replace")
    fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("FAIL")]
    tail = "; ".join(fails[:3]) or " ".join(out.split())[-200:]
    # Both validators: exit 0 = pass, 1 = a finding, 2 (or anything else: a crash, a signal) = the
    # validator did not run (the "guard did not run" line of either script, or a usage error), which
    # must not read as a FAIL.
    if r.returncode not in (0, 1):
        return None, "validator exited %d: %s" % (r.returncode, tail)
    if os.path.lexists(str(target)) and not os.path.isfile(str(target)):
        # Either validator SKIPs a path that is not a regular file (exit 0); the file it was
        # asked to check is then unchecked, which is not a pass.
        return None, "%s path is not a regular file: %s" % (kind, target)
    if r.returncode == 0:
        lines = out.splitlines()
        skips = [ln.strip() for ln in lines if ln.startswith("SKIP:")]
        if skips and os.path.lexists(str(target)):
            # dream-write validates only files it has just written, so a SKIP over a file that
            # exists (an empty journal, say) means the validator did not check it.
            return None, "validator skipped an existing file: %s" % skips[0]
        # Each validator's summary line: "verify-dream-state: ok=N fail=M (schema vX)" and
        # "verify-dream-journal: ok=N fail=M warn=W". An exit 0 with neither it nor a SKIP line
        # (over a missing path) is not a verdict.
        if not skips and not any(ln.startswith("verify-dream-%s: ok=" % kind) for ln in lines):
            return None, "validator output not recognised (no summary or SKIP line): %s" % (
                tail or "(empty)")
    return r.returncode == 0, tail


# --------------------------------------------------------------------------
# memedit
# --------------------------------------------------------------------------

def load_ops(run, given):
    p = Path(given)
    if not p.is_absolute():
        p = run.work / given
    if not (dm.is_inside(p, run.work / "handoff" / "ops") or dm.is_inside(p, run.work / "sweep")):
        raise Precond("refused: --ops must name a file under handoff/ops/ or sweep/")
    if os.path.islink(str(p)) or not os.path.isfile(str(p)):
        raise Precond("%s is missing or a link" % given)
    obj = ds.load_json(p)
    ops = obj.get("ops") if isinstance(obj, dict) else None
    if not isinstance(ops, list) or not all(isinstance(o, dict) for o in ops):
        raise Precond("%s needs an ops list of objects" % given)
    ops = json.loads(json.dumps(ops))
    seen = set()
    for o in ops:
        oid = o.get("id")
        if not isinstance(oid, str) or not OP_ID_RE.match(oid):
            raise Precond("an op id %r is not an id" % ascii_safe(oid, 40))
        if oid in seen:
            raise Precond("op id %s is used twice" % oid)
        seen.add(oid)
        if o.get("op") not in OP_TYPES:
            raise Precond("op %s: unknown op %r" % (oid, ascii_safe(o.get("op"), 30)))
        for f in ("file",) + OP_FIELDS[o["op"]]:
            v = o.get(f)
            if f == "lines":
                ok = isinstance(v, list)
            else:
                ok = isinstance(v, str) and (v.strip() if f != "text" else v)
            if not ok:
                raise Precond("op %s: %s needs %r" % (oid, o["op"], f))
        if o["op"] == "delete" and o["class"] not in REMOVAL_CLASSES + (NODE_CLASS,):
            raise Precond("op %s: %r is not a removal class" % (oid, ascii_safe(o["class"], 40)))
        if (o["op"] == "delete" and o["class"] == NODE_CLASS
                and _real(o["file"]) != _real(node_file(run))):
            raise Precond("op %s: a node delete names a file other than "
                          "memory/HIGHER_ORDER.md" % oid)
        if "decision_id" in o and not isinstance(o["decision_id"], str):
            raise Precond("op %s: decision_id must be a string" % oid)
    return ops


def needs_decision(run, op, entry_body):
    """True when the op may be run only under a user decision. An autonomous
    op touches a `human:`-attested entry only for the Size-check prune of a
    project memory file and the `Outcome:` stamp, and never writes an
    `Affirmed` or `Governance-conflict` line it did not find in the entry."""
    if op["op"] == "declined_add":
        return True
    ho = _real(node_file(run))
    prune = False
    if op["op"] == "delete":
        if op["class"] in USER_GATED_CLASSES or op["class"] == NODE_CLASS:
            return True
        if _real(op["file"]) == ho:
            return True
        if op["class"] == "pruned" and ds.nk(op["file"]) == ds.nk(run.repo / "memory" /
                                                                   "MEMORY.md"):
            return True
        # An entry holding an unresolved governance adjudication is never
        # removed without its user.
        if entry_body is not None and NONTERMINAL_RE.search(entry_body):
            return True
        prune = op["class"] == "pruned" and not user_tier(run, op["file"])
    stamp = (op["op"] == "replace" and entry_body is not None
             and outcome_stamp_only(entry_body, op["text"]))
    # The two exemptions bypass only this refusal of a human-attested entry.
    if not stamp and not prune:
        if op["op"] != "usage_bump" and entry_body is not None and HUMAN_RE.search(entry_body):
            return True
    # New text that adds a human: actor needs a decision that showed it (S2),
    # under every exemption (N1): a human line the text holds that the old entry did not.
    if human_lines(op_new_text(op)) - human_lines(entry_body):
        return True
    old_lines = guarded_lines(entry_body) if op["op"] == "replace" else set()
    if guarded_lines(op_new_text(op)) - old_lines:
        return True
    return False


def orient_renames(run):
    """The rename records of the journal as Orient found it: the backup copy
    `dirty` took, checked against the sha in the bound snapshot (D27)."""
    b = (run.dirty.get("backup") or {}).get(".dream-journal.jsonl") or {}
    if b.get("sha256") in (None, "absent") or not b.get("copy"):
        return []
    p = run.work / "sweep" / "backup" / ".dream-journal.jsonl"
    if os.path.islink(str(p)) or not os.path.isfile(str(p)) or \
            ds.sha256_file(p) != b["sha256"]:
        raise Precond("refused: sweep/backup/.dream-journal.jsonl is not the journal the Orient "
                      "snapshot recorded")
    out = []
    for line in dm.read_text(p).splitlines():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and isinstance(obj.get("rename"), list):
            out.append(obj["rename"])
    return out


def seed_records(run):
    """The seed's records, or None without a seed. Each pair must be a rename
    of the Orient journal (checked against the bound snapshot, D27)."""
    seed = run.work / SEED
    if not os.path.lexists(str(seed)):
        return None
    _p, probs = ds.handoff_problems("working-map-seed.json", seed)
    if probs:
        raise Precond("refused: %s: %s" % (SEED, "; ".join(probs)))
    landed = orient_renames(run)
    records = []
    for i, pr in enumerate(ds.load_json(seed)["pairs"], 1):
        pair = pr.get("rename") if isinstance(pr, dict) else pr
        if not (isinstance(pair, list) and len(pair) == 2 and all(
                isinstance(x, str) and x.startswith(FQ_PREFIXES) for x in pair)):
            raise Precond("refused: %s pair %d is not a landed rename of two "
                          "fully-qualified targets" % (SEED, i))
        if list(pair) not in landed:
            raise Precond("refused: %s pair %d is not a rename record of the journal Orient "
                          "found" % (SEED, i))
        records.append({"id": "seed-%03d" % i, "record": {"rename": list(pair)}})
    return records


def init_map(run):
    """sweep/working-map.json, created on the first run from the seed."""
    if os.path.lexists(str(run.work / WMAP)):
        return load_rec(run, WMAP, {"version": 1, "records": []})
    records = seed_records(run)
    if records is None:
        records = []
        jp = run.journal_path
        if os.path.isfile(str(jp)) and dm.read_text(jp).strip():
            raise Precond("the journal is non-empty and %s does not exist: run [ORI-RECOVER] "
                          "and write the seed first" % SEED)
    wm = {"version": 1, "records": records}
    save_rec(run, WMAP, wm)
    return wm


def check_map(run, wm, applied, plans):
    """Every working-map record is backed (D27): a seed record rebuilt from
    the seed, or the map record of an op in applied-ops.json or in this
    run's plan, so no record reaches the journal from the map file alone."""
    backed = {r["id"]: r["record"] for r in seed_records(run) or []}
    for oid, rec in applied["ops"].items():
        if isinstance(rec, dict) and rec.get("map") is not None:
            backed[oid] = rec["map"]
    for plan in plans.values():
        for st in plan:
            if st["action"] == "apply" and st["map"] is not None:
                backed[st["op"]["id"]] = st["map"]
    for r in wm.get("records") or []:
        rid = r.get("id") if isinstance(r, dict) else None
        if rid is None or backed.get(rid) != r.get("record"):
            raise Precond("refused: %s record %s is backed by neither the seed nor an op; "
                          "nothing written" % (WMAP, ascii_safe(rid, 40)))


def orient_journal_records(run):
    """Every well-formed record of the journal as Orient found it (the backup
    copy `dirty` took, checked against the bound snapshot's sha, D27), in file
    order: the renames AND the removes of an earlier, crashed sweep. A torn or
    malformed line is dropped (the expected crash artifact; recovery already
    validated the journal). [] without a backup, and once `state apply` has
    started (it clears the journal, so nothing is left to carry): a write-ahead
    "apply" record, or the `journal_cleared` marker clear_journal writes on
    every path that clears the journal (the no-change and no-op paths leave no
    "apply" record)."""
    b = (run.dirty.get("backup") or {}).get(".dream-journal.jsonl") or {}
    if b.get("sha256") in (None, "absent") or not b.get("copy"):
        return []
    pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
    if "apply" in pend.get("ops", {}) or pend.get("journal_cleared"):
        return []
    p = run.work / "sweep" / "backup" / ".dream-journal.jsonl"
    if os.path.islink(str(p)) or not os.path.isfile(str(p)) or \
            ds.sha256_file(p) != b["sha256"]:
        raise Precond("refused: sweep/backup/.dream-journal.jsonl is not the journal the Orient "
                      "snapshot recorded")
    out = []
    for line in dm.read_text(p).splitlines():
        if line.strip() and not journal_problems(line):
            out.append(json.loads(line))
    return out


def journal_text(wm, prior=()):
    """The journal: the Orient journal's records first (a prior sweep's crash
    evidence that recovery has not resolved survives every flush; recovery
    never clears the journal, only `state apply` does), then every working-map
    record that is not already one of them."""
    recs = list(prior) + [r["record"] for r in wm["records"] if r["record"] not in prior]
    return "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n"
                   for r in recs)


def flush_journal(run, wm, point=None):
    """The whole map to the journal (temp file, fsync, os.replace), then its
    sha to hashes.json. A journal already holding exactly the map's text (a
    stop between the write and the hash record) only gets the record; any
    other journal that differs from the last recorded sha is refused."""
    jp = run.journal_path
    check_target(run, str(jp), "journal")
    text = journal_text(wm, orient_journal_records(run))
    probs = journal_problems(text)
    if probs:
        raise Precond("refused: the working map is not valid journal grammar: %s" % probs[0])
    data = text.encode("utf-8")
    if not (os.path.isfile(str(jp)) and open(str(jp), "rb").read() == data):
        _k, rec = find_hash(hash_records(run), jp)
        if rec is not None and ds.sha256_file(jp) != rec["sha256"]:
            raise Precond("the journal changed since this sweep last wrote it; nothing written")
        atomic_write(jp, data)
    if point:
        _crash(run.ctx, point)
    record_hash(run, str(jp), "journal", "memedit")


def cmd_memedit(args, ctx):
    run = Run(ctx, args)
    guard_check(run)
    if args.dry_run:
        return _memedit(run, args)
    with write_lock(run):
        return _memedit(run, args)


def _memedit(run, args):
    ops = load_ops(run, args.ops)
    dec, dsha = load_decisions(run, args.decisions, args.decisions_sha, required=False)
    if dec is not None:
        for o in ops:
            if o.get("decision_id") is None:
                raise Precond("refused: with --decisions every op names a decision_id (op %s "
                              "has none); autonomous ops run without --decisions" % o["id"])
    files = {}
    generated = load_rec(run, GENERATED, {"version": 1, "ops": {}})
    for o in ops:
        kind, nat = check_target(run, o["file"])
        if kind != "memory":
            raise Precond("op %s: %s is not a memory file" % (o["id"], o["file"]))
        o["file"] = nat
        why = unbound_insert(run, o, generated) or unbound_create(run, o)
        if why:
            raise Precond("refused: " + why)
        files.setdefault(ds.nk(nat), []).append(o)
    applied = load_rec(run, APPLIED, {"version": 1, "ops": {}})
    if not isinstance(applied.get("ops"), dict):
        raise Precond("%s has no ops object" % APPLIED)
    s = ds.Summary()
    if args.dry_run:
        s.add("memedit --dry-run: %d op(s) over %d file(s); nothing written"
              % (len(ops), len(files)))
        for _k, fops in files.items():
            s.add("%s: %d op(s)" % (fops[0]["file"], len(fops)))
        s.emit()
        return EXIT_OK
    refuse_mid_operation(ops)
    run.ops_label = ops_label(run, args.ops)
    run.op_digests = {o["id"]: op_digest(o) for o in ops}
    clash = reused_ids(applied, ops, run.ops_label, run.op_digests)
    if clash:
        raise Precond(clash)
    wm = init_map(run)
    over = decision_counts(run, dec, ops, applied)
    plans, refused = {}, []
    for k, fops in files.items():
        try:
            plans[k] = plan_file(run, fops, applied, dec, dsha, over)
        except OpError as e:
            refused.append("%s: %s" % (fops[0]["file"], e))
    check_map(run, wm, applied, plans)
    journal_written = False
    done = skipped = 0
    for k, plan in plans.items():
        for step in plan:
            if step["action"] == "skip":
                skipped += 1
                continue
            journal_written |= persist(run, step, applied, wm)
            done += 1
    # The validator runs after a run that wrote the journal and on every later
    # run until it has passed (P3): applied-ops.json keeps journal_validation
    # (pending, failed or passed), so a re-run that skips every done op cannot
    # exit 0 over a journal the validator never passed.
    if journal_written or applied.get("journal_validation") not in (None, "passed"):
        ok, tail = run_validator(run, "journal", run.journal_path)
        applied["journal_validation"] = "passed" if ok is True else "failed"
        save_rec(run, APPLIED, applied)
        if ok is not True:
            raise Precond("verify-dream-journal %s on the journal: %s"
                          % ("FAIL" if ok is False else "did not run", tail))
    s.add("memedit: %d op(s) applied, %d already done, %d file(s) refused"
          % (done, skipped, len(refused)))
    for r in refused:
        s.add("refused: %s" % r)
    s.add("working map: %d record(s)" % len(wm["records"]))
    for n in run.notes:
        s.add(n)
    s.emit()
    return EXIT_PRECOND if refused else EXIT_OK


def bound_file(run, path):
    """True for the memory files whose autonomous inserts `ops` alone
    generates: any MEMORY.md (the config repo's or a project's store file)
    and a config repo topic file other than improvement-signals.md.
    HIGHER_ORDER.md is not one (its nodes are hand-written inserts)."""
    p = Path(path)
    if p.name.lower() == "memory.md":
        return True
    return (ds.nk(p.parent) == ds.nk(run.repo / "memory" / "topics")
            and p.name.lower() != "improvement-signals.md")


def unbound_insert(run, o, generated):
    """-> a refusal text for an autonomous (no decision_id) insert into a
    bound_file that `ops` did not generate (its digest is not recorded in
    sweep/ops-generated.json), else None. The one hand-written autonomous
    insert the sweep prose allows into a bound file is an `[improvement_signal]`
    entry under `## Pattern` of a project's MEMORY.md (sweep-synthesize.md
    § SYN-PROMOTE); user-scope signals go to improvement-signals.md."""
    if o["op"] != "insert" or o.get("decision_id") is not None:
        return None
    if not bound_file(run, o["file"]):
        return None
    if (text_heading(o["text"]) or "").startswith(SIGNAL_PREFIX) \
            and Path(o["file"]).name.lower() == "memory.md" and not user_tier(run, o["file"]) \
            and norm_section(o["section"]).lower() == "## pattern":
        return None
    rec = (generated.get("ops") or {}).get(o["id"])
    if rec == op_digest(o):
        return None
    return ("op %s is an autonomous insert into %s that `dream-write.py ops` did not generate "
            "(its digest is not recorded in %s): list the entry in handoff/ops-plan/ and run "
            "`ops`, or give the insert a decision_id" % (o["id"], o["file"], GENERATED))


def skeleton_title(p):
    """The one title an autonomous create may carry: `# Project Memory — <the
    store directory's name without its -<hash> suffix>` for a MEMORY.md,
    `# Topic memory — <the file stem, hyphens as spaces>` for a topic file."""
    if p.name.lower() == "memory.md":
        return "# Project Memory \u2014 " + re.sub(r"-[0-9a-f]{6}\Z", "", p.parent.parent.name)
    return "# Topic memory \u2014 " + p.stem.replace("-", " ")


def unbound_create(run, o):
    """-> a refusal text for an autonomous (no decision_id) create of a
    MEMORY.md or a config repo topic file that holds more than a skeleton,
    else None. A skeleton is an optional first line skeleton_title, then
    the type-section headings `## Feedback`, `## Decision`, `## Pattern`,
    `## Declined` written exactly, each at most once; a MEMORY.md has all four
    (sweep-synthesize.md § SYN-WRITE Bootstrap). Entries reach the new file
    through `ops`; a decided create (Save) may carry one."""
    p = Path(o["file"])
    mem = p.name.lower() == "memory.md"
    if o["op"] != "create" or o.get("decision_id") is not None or not (
            mem or ds.nk(p.parent) == ds.nk(run.repo / "memory" / "topics")):
        return None
    seen = []
    for line in EOL_RE.split(o["text"]):
        s = line.rstrip()
        if not s:
            continue
        if s == skeleton_title(p) and not seen:
            seen.append("#")
            continue
        if s not in SKELETON_SECTIONS or s in seen:
            return ("op %s is an autonomous create of %s with content beyond the skeleton (%r): "
                    "create the title %r (optional) and the empty sections, each once, then add "
                    "entries through `dream-write.py ops`"
                    % (o["id"], o["file"], ascii_safe(s, 60), skeleton_title(p)))
        seen.append(s)
    if mem and not set(SKELETON_SECTIONS) <= set(seen):
        return ("op %s is an autonomous create of %s without all of %s"
                % (o["id"], o["file"], ", ".join(SKELETON_SECTIONS)))
    return None


def ops_label(run, given):
    """The ops file as applied-ops.json names it: its path under the work
    folder, with forward slashes."""
    p = Path(given)
    if not p.is_absolute():
        p = run.work / given
    return os.path.relpath(os.path.realpath(str(p)),
                           os.path.realpath(str(run.work))).replace("\\", "/")


def op_digest(o):
    """sha256 of the op as this run reads it (its id, its normalized file and
    every other field)."""
    return hashlib.sha256(json.dumps(o, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode("ascii")).hexdigest()


def reused_ids(applied, ops, label, digests):
    """-> a refusal text, or None. An op id is the key of its applied-ops.json
    record, of its working-map record and of its decision count, so the id of
    an op this sweep already recorded may be used again only by the SAME op
    (the same ops file and the same content: a crash re-run). A different op
    under a recorded id is refused, never skipped as done and never run beside
    it: the refusal names the recorded op and this one. A record written
    before the digest existed carries neither field and matches by id."""
    for o in ops:
        rec = applied["ops"].get(o["id"])
        if not isinstance(rec, dict) or "digest" not in rec:
            continue
        if rec.get("ops_file") != label or rec["digest"] != digests[o["id"]]:
            return ("refused: op id %s is already recorded (%s) from %s, and %s names a "
                    "different op under it (%s); op ids must be unique across all of the sweep's "
                    "ops files: give each new op an id with a per-file prefix (for example "
                    "`app-` for Apply's ops). Nothing written"
                    % (o["id"], rec.get("status"), ascii_safe(rec.get("ops_file"), 80),
                       ascii_safe(label, 80),
                       "same ops file, changed op" if rec.get("ops_file") == label
                       else "another ops file"))
    return None


def decision_gate(run, o, body, dec, over):
    """An op without decision_id must not need one (needs_decision); an op
    with one must be authorized by its item under the D28 table
    (authorize_op) and within the decision's count (`over`). OpError."""
    did = o.get("decision_id")
    if did is None:
        if needs_decision(run, o, body):
            raise OpError("op %s needs a user decision (decision_id)" % o["id"])
        return
    if dec is None:
        raise OpError("op %s carries decision_id %s but no bound --decisions was given"
                      % (o["id"], did))
    item = decision_item(dec, did)
    why = "it is not an item of decisions.json" if item is None else \
        (authorize_op(run, item, o, body) or over.get(o["id"]))
    if why:
        raise OpError("op %s: decision %s does not authorize it: %s" % (o["id"], did, why))


def plan_file(run, fops, applied, dec, dsha, over):
    """Validates every op of one file in memory -> the persist plan; OpError
    names the first op that fails (nothing is written to the file)."""
    path = fops[0]["file"]
    exists = os.path.isfile(path)
    data = open(path, "rb").read() if exists else None
    prior = [r for r in applied["ops"].values() if ds.nk(r.get("file", "")) == ds.nk(path)]
    first_touch = not prior
    foreign = any(r.get("foreign") for r in prior)
    created = any(r.get("created") for r in prior)
    if first_touch:
        osha, how = orient_record(run, path)
        cur = ds.sha256_file(path)
        if osha == "absent" and not exists:
            pass
        elif osha is None or cur != osha:
            foreign = True
    elif exists and any(r.get("status") == "done" for r in prior):
        # A later run (P1): the file must still be what this sweep last wrote.
        # Known shas: the last one recorded in hashes.json and the post_sha of a
        # pending op (a stop between the write and the hash record). Anything
        # else is another writer's edit: still written, marked, never committed.
        known = {r.get("post_sha") for r in prior if r.get("status") == "pending"}
        _k, hrec = find_hash(hash_records(run), path)
        if hrec is not None:
            known.add(hrec.get("sha256"))
        if ds.sha256_bytes(data) not in known:
            foreign = True
    plan = []
    cur_data = data
    for o in fops:
        rec = applied["ops"].get(o["id"])
        if rec is not None and rec.get("status") == "done":
            plan.append({"action": "skip", "op": o})
            continue
        cur_sha = ds.sha256_bytes(cur_data) if cur_data is not None else "absent"
        if rec is not None and rec.get("status") == "pending":
            if cur_sha == rec.get("post_sha"):
                plan.append({"action": "finish", "op": o, "rec": rec})
                continue
            if cur_sha != rec.get("pre_sha"):
                raise OpError("op %s is pending and the file holds neither its pre nor its "
                              "post sha" % o["id"])
        for _ln, name in scan_text(op_texts(o)):
            raise OpError("op %s: its text matches the credential pattern %s" % (o["id"], name))
        if o["op"] == "create":
            if cur_data is not None:
                raise OpError("op %s: create needs an absent file" % o["id"])
            decision_gate(run, o, None, dec, over)
            new = Doc(o["text"].encode("utf-8"))
            entry, map_rec = None, None
            osha, _how = orient_record(run, path)
            if osha == "absent":
                created, foreign = True, False
        else:
            if cur_data is None:
                raise OpError("op %s: %s does not exist" % (o["id"], path))
            try:
                new = Doc(cur_data)
            except Precond as e:
                raise OpError("op %s: %s" % (o["id"], e))
            before_declined = declined_blocks(new)
            entry, map_rec = None, None
            try:
                target = find_entry(new, o) if o["op"] in ("delete", "replace", "append_lines",
                                                           "usage_bump") else None
            except OpError as e:
                raise OpError("op %s: %s" % (o["id"], e))
            body = None
            if target is not None:
                c = new.contents()
                body = "\n".join(c[target["start"]:target["end"]])
            decision_gate(run, o, body, dec, over)
            try:
                apply_op(new, o)
            except OpError as e:
                raise OpError("op %s: %s" % (o["id"], e))
            if o["op"] != "declined_add" and declined_blocks(new) != before_declined:
                raise OpError("op %s would change ## Declined" % o["id"])
            if o["op"] == "delete" and o["class"] != NODE_CLASS:
                fq = fq_target(run, path, target["heading"])
                if fq is None:
                    raise OpError("op %s: no fully-qualified target for %s" % (o["id"], path))
                map_rec = {"remove": [fq, o["class"]]}
            elif o["op"] == "replace":
                new_h = EOL_RE.split(o["text"])[0][4:].strip()
                if o.get("decision_id") is None and bound_file(run, path) and \
                        target["heading"].startswith(SIGNAL_PREFIX) != new_h.startswith(SIGNAL_PREFIX):
                    raise OpError("op %s: an autonomous replace keeps an entry's %s heading prefix "
                                  "as it is (%r -> %r)" % (o["id"], SIGNAL_PREFIX,
                                                           ascii_safe(target["heading"], 60),
                                                           ascii_safe(new_h, 60)))
                if new_h != target["heading"]:
                    a, b = fq_target(run, path, target["heading"]), fq_target(run, path, new_h)
                    if a is not None and b is not None:
                        map_rec = {"rename": [a, b]}
        post = new.data()
        plan.append({"action": "apply", "op": o, "path": path, "pre_sha": cur_sha,
                     "post_sha": ds.sha256_bytes(post), "data": post, "map": map_rec,
                     "foreign": foreign, "created": created,
                     "decisions_sha": dsha if o.get("decision_id") else None})
        cur_data = post
    return plan


def persist(run, step, applied, wm):
    """The six-step persist order for one op. -> True when the journal was
    written."""
    o = step["op"]
    pt = "%s:" % o["id"]
    if step["action"] == "finish":
        rec = step["rec"]
        record_hash(run, rec["file"], "memory", "memedit", rec.get("decisions_sha"),
                    foreign=rec.get("foreign"), created=rec.get("created"))
        record_store_file(run, rec["file"])
        _crash(run.ctx, pt + "5")
        rec["status"] = "done"
        save_rec(run, APPLIED, applied)
        _crash(run.ctx, pt + "6")
        return False
    wrote_journal = False
    if step["map"] is not None:
        if not any(r.get("id") == o["id"] for r in wm["records"]):
            wm["records"].append({"id": o["id"], "record": step["map"]})
            save_rec(run, WMAP, wm)
        _crash(run.ctx, pt + "1")
        flush_journal(run, wm, pt + "journal-written")
        wrote_journal = True
        applied["journal_validation"] = "pending"
        _crash(run.ctx, pt + "2")
    applied["ops"][o["id"]] = {"op": o["op"], "file": step["path"], "pre_sha": step["pre_sha"],
                               "post_sha": step["post_sha"], "status": "pending",
                               "decision_id": o.get("decision_id"),
                               "decisions_sha": step["decisions_sha"],
                               "foreign": step["foreign"], "created": step["created"],
                               "heading": o.get("heading"), "class": o.get("class"),
                               "map": step["map"], "ops_file": run.ops_label,
                               "digest": run.op_digests[o["id"]]}
    save_rec(run, APPLIED, applied)
    _crash(run.ctx, pt + "3")
    check_target(run, step["path"], "memory")
    ensure_store(run, step["path"])
    atomic_write(step["path"], step["data"])
    _crash(run.ctx, pt + "4")
    record_hash(run, step["path"], "memory", "memedit", step["decisions_sha"],
                foreign=step["foreign"], created=step["created"])
    record_store_file(run, step["path"])
    _crash(run.ctx, pt + "5")
    applied["ops"][o["id"]]["status"] = "done"
    save_rec(run, APPLIED, applied)
    _crash(run.ctx, pt + "6")
    return wrote_journal


# --------------------------------------------------------------------------
# hash --record
# --------------------------------------------------------------------------

def orient_blob(top, head, rel):
    """-> bytes of rel at head, None when absent, False when git failed."""
    listed = ds.git_out(top, "ls-tree", "-z", "--end-of-options", head, "--", rel)
    if listed is None:
        return False
    rec = next((x for x in listed.split("\0") if x), None)
    if rec is None:
        return None
    meta = rec.split("\t", 1)[0].split()
    if len(meta) != 3 or meta[1] != "blob" or not ds.COMMIT_RE.match(meta[2]):
        return None
    data = ds.git_bytes(top, "cat-file", "blob", meta[2])
    return False if data is None else data


HEADING_RE = re.compile(r"^(#{1,6}) ")


def replay_edits(text, edits):
    """Orient text with the Applied edits replayed in order; OpError on a
    current_text that does not occur exactly once or a missing anchor."""
    for ed in edits:
        new = ed.get("new_text")
        if not isinstance(new, str):
            raise OpError("edit %s has no new_text" % ed.get("id"))
        cur = ed.get("current_text")
        if isinstance(cur, str):
            n = text.count(cur) if cur else 0
            if n != 1:
                raise OpError("edit %s: current_text occurs %d times" % (ed.get("id"), n))
            text = text.replace(cur, new, 1)
            continue
        anchor = ed.get("after_heading")
        if not isinstance(anchor, str) or not HEADING_RE.match(anchor):
            raise OpError("edit %s: current_text null needs an after_heading" % ed.get("id"))
        lines = text.splitlines(True)
        fence, at, level = None, None, len(HEADING_RE.match(anchor).group(1))
        idx = []
        for i, ln in enumerate(lines):
            body = ln.rstrip("\r\n")
            fm = dm.memory_entries().FENCE_RE.match(body)
            if fence:
                if fm and fm.group(1) == fence:
                    fence = None
                continue
            if fm:
                fence = fm.group(1)
                continue
            if body == anchor:
                idx.append(i)
            elif idx and at is None and len(idx) == 1:
                m = HEADING_RE.match(body)
                if m and len(m.group(1)) <= level:
                    at = i
        if len(idx) != 1:
            raise OpError("edit %s: after_heading occurs %d times" % (ed.get("id"), len(idx)))
        pos = sum(len(x) for x in lines[:at]) if at is not None else len(text)
        text = text[:pos] + new + text[pos:]
    return text


def governance_check(run, p, edits):
    """p's content equals its Orient content (the blob at the snapshot's
    HEAD, the file clean at Orient) with the Applied edits naming it
    replayed; OpError otherwise. A file absent at Orient is the target of
    exactly one edit, the item's `create: true` (the shape the user saw as
    "New file: <path>"); `create: true` on a file that existed is refused.
    -> True when p was absent at Orient. Used
    by hash --record and again by commit (D27: an Applied governance file is
    committed only when it still passes)."""
    mine = edits.get(ds.nk(p))
    if not mine:
        raise OpError("not the target of an item the user Applied")
    bad = ds.gov_path_problem(p, gov_policy(run))
    if bad:
        raise OpError("its path %s" % bad)
    top = ds.toplevel(p)
    info = repo_snapshot(run, top) if top else None
    if info is None or info.get("porcelain") is None or not info.get("head"):
        raise OpError("its repository has no usable Orient snapshot")
    rel = ds.rel_in(top, p)
    if porcelain_covers(info["porcelain"], rel):
        raise OpError("it was not clean at Orient")
    blob = orient_blob(top, info["head"], rel)
    if blob is False:
        raise OpError("git could not read its Orient blob")
    if blob is None:
        if len(mine) != 1:
            raise OpError("absent at Orient but the target of %d edits" % len(mine))
        if mine[0].get("create") is not True or mine[0].get("current_text") is not None \
                or mine[0].get("after_heading") is not None:
            raise OpError("absent at Orient, so only an Applied `create: true` (current_text "
                          "and after_heading null) may write it")
        expect = mine[0]["new_text"]
        if not isinstance(expect, str):
            raise OpError("its edit has no new_text")
        bom = False
    else:
        if any(e.get("create") is True for e in mine):
            raise OpError("a `create: true` edit, but the file existed at Orient")
        bom = blob.startswith(BOM)
        try:
            orient_text = (blob[3:] if bom else blob).decode("utf-8")
        except UnicodeDecodeError:
            raise OpError("its Orient content is not UTF-8")
        expect = replay_edits(orient_text, mine)
    want = (BOM if bom else b"") + expect.encode("utf-8")
    if not os.path.isfile(p):
        raise OpError("the file does not exist")
    with open(p, "rb") as fh:
        got = fh.read()
    if got != want:
        raise OpError("its content is not its Orient content with the Applied edits "
                      "(an unapproved edit, or an edit not yet made)")
    return blob is None


def cmd_hash(args, ctx):
    if not args.record:
        raise Usage("hash takes --record")
    run = Run(ctx, args)
    guard_check(run)
    with write_lock(run):
        return _hash(run, args)


def _hash(run, args):
    need_git()
    dec, dsha = load_decisions(run, args.decisions, args.decisions_sha)
    edits = applied_edits(run, dec)
    ok = ds.allowed_paths(run.work, run.man, run.repo)
    s = ds.Summary()
    refused, recorded = [], 0
    for given in args.paths:
        p = repo_path(run, given)
        try:
            if not ok(p):
                raise OpError("outside the config repo and the manifest's project roots")
            created = governance_check(run, p, edits)
        except OpError as e:
            refused.append("%s: %s" % (p, e))
            continue
        record_hash(run, p, "governance", "hash", dsha, created=created)
        recorded += 1
    s.add("hash --record: %d recorded, %d refused" % (recorded, len(refused)))
    for r in refused:
        s.add("refused: %s" % r)
    for n in run.notes:
        s.add(n)
    s.emit()
    return EXIT_PRECOND if refused else EXIT_OK


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

V2_KEYS = (("rejected_lessons", []), ("outcome_tags", []), ("episodic_ledger", []))
V3_KEYS = (("cost_records", []), ("model_routing", {}), ("deferred_sessions", {}),
           ("quiet_sweeps", {}))


# The serialization of a new state file, and of one no style reproduces:
# the live file's own (2-space indent, non-ASCII unescaped, trailing LF).
DEFAULT_STYLE = (2, False, "\n", "\n", False)


def json_style(raw):
    """-> (indent, ensure_ascii, eol, trailing, bom) reproducing raw, else a
    default (2, False, LF, LF)."""
    bom = raw.startswith(BOM)
    text = (raw[3:] if bom else raw).decode("utf-8")
    obj = json.loads(text)
    for indent in (2, 4, 1, 3, "\t", None):
        for ea in (False, True):
            s = json.dumps(obj, indent=indent, ensure_ascii=ea)
            for eol in ("\n", "\r\n"):
                body = s.replace("\n", eol)
                for trail in (eol, ""):
                    if body + trail == text:
                        return (indent, ea, eol, trail, bom)
    return DEFAULT_STYLE[:4] + (bom,)


def json_bytes(obj, style):
    indent, ea, eol, trail, bom = style
    s = json.dumps(obj, indent=indent, ensure_ascii=ea).replace("\n", eol) + trail
    return (BOM if bom else b"") + s.encode("utf-8")


def read_state(run):
    p = run.state_path
    check_target(run, str(p), "state")
    if not os.path.isfile(str(p)):
        return None, None, None
    with open(str(p), "rb") as fh:
        raw = fh.read()
    try:
        style = json_style(raw)
        obj = json.loads((raw[3:] if raw.startswith(BOM) else raw).decode("utf-8"))
    except ValueError:
        raise Precond("the state file is not JSON; nothing written")
    if not isinstance(obj, dict):
        raise Precond("the state file is not a JSON object")
    return obj, raw, style


def migrated(obj):
    """[ORI-STATE] additive migration; -> (new object, from version)."""
    v = obj.get("schema_version")
    if v == 3:
        return obj, 3
    if v not in (1, 2):
        raise Precond("state schema_version %r: only 1, 2 and 3 are known" % v)
    out = {}
    for k, val in obj.items():
        out[k] = 3 if k == "schema_version" else val
    for k, d in (V2_KEYS if v == 1 else ()) + V3_KEYS:
        if k not in out:
            out[k] = json.loads(json.dumps(d))
    return out, v


def state_foreign(run, pre_raw):
    """True when the live state file (pre_raw) is none of the shas this sweep
    recorded for it: the last hashes.json record, or the post_sha of any
    state-pending.json record (a stop between the swap and the hash record).
    Another writer's edit between two state subcommands (P1). Without a
    record the file has not been written by this sweep yet: the first write
    compares it with its Orient content, as memedit does for a memory file
    (a file Orient found absent that exists now, or one with no Orient record,
    is another writer's)."""
    if pre_raw is None:
        return False
    _k, rec = find_hash(hash_records(run), run.state_path)
    if rec is None:
        osha, _how = orient_record(run, str(run.state_path))
        known = {osha} if isinstance(osha, str) and osha != "absent" else set()
    else:
        known = {rec.get("sha256")}
    for r in load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})["ops"].values():
        if isinstance(r, dict):
            known.add(r.get("post_sha"))
    return ds.sha256_bytes(pre_raw) not in known


def state_swap(run, op_name, new_obj, style, pre_raw, decisions_sha=None, clear=False):
    """Validate before swap, write-ahead, os.replace, hash, (clear)."""
    p = run.state_path
    foreign = state_foreign(run, pre_raw)
    data = json_bytes(new_obj, style)
    pre_sha = ds.sha256_bytes(pre_raw) if pre_raw is not None else "absent"
    post_sha = ds.sha256_bytes(data)
    ds.put(run.work, STATE_BEFORE, pre_raw if pre_raw is not None else b"")
    tmp = temp_beside(p, data)
    try:
        ok, tail = run_validator(run, "state", tmp, run.work / STATE_BEFORE
                                 if pre_raw is not None else None)
        if ok is not True:
            raise Precond("verify-dream-state %s; the live state file is untouched: %s"
                          % ("FAIL" if ok is False else "did not run", tail))
        pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
        pend["ops"][op_name] = {"pre_sha": pre_sha, "post_sha": post_sha, "status": "pending",
                                "at": run.now, "foreign": foreign}
        save_rec(run, STATE_PENDING, pend)
        _crash(run.ctx, "state-%s:pending" % op_name)
        check_target(run, str(p), "state")
        _replace(tmp, p)
        tmp = None
    finally:
        if tmp is not None:
            with contextlib.suppress(OSError):
                os.unlink(str(tmp))
    _crash(run.ctx, "state-%s:replaced" % op_name)
    finish_state(run, op_name, decisions_sha, clear)
    return post_sha


def finish_state(run, op_name, decisions_sha, clear, foreign=False):
    """The hash record (and the journal clear) after a state write. The foreign
    flag is the caller's, or the one the write-ahead record kept across a stop."""
    pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
    mine = pend["ops"].get(op_name)
    foreign = bool(foreign or (isinstance(mine, dict) and mine.get("foreign")))
    # A write-ahead record whose pre_sha is "absent" means this write created the
    # file (a first run): record it as created, so `commit` can commit it.
    created = isinstance(mine, dict) and mine.get("pre_sha") == "absent"
    record_hash(run, str(run.state_path), "state", "state " + op_name, decisions_sha,
                foreign=foreign, created=created)
    if clear:
        clear_journal(run)
    pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
    if op_name in pend["ops"]:
        pend["ops"][op_name]["status"] = "done"
        save_rec(run, STATE_PENDING, pend)


def clear_journal(run):
    """Empties the journal, after writing the marker orient_journal_records
    reads: state-pending.json's `journal_cleared`. Every path of `state apply`
    that clears the journal (a state write, the no-change path, the finish of
    a stopped write and the no-op re-run) comes here, and only the first two
    leave an "apply" record behind, so the marker is what holds across all."""
    pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
    pend["journal_cleared"] = run.now
    save_rec(run, STATE_PENDING, pend)
    jp = run.journal_path
    check_target(run, str(jp), "journal")
    if os.path.isfile(str(jp)) and os.path.getsize(str(jp)) > 0:
        atomic_write(jp, b"")
    record_hash(run, str(jp), "journal", "state apply")


def pending_state(run, op_name):
    """-> "finish" | "noop" | None (go ahead); Precond on a foreign change."""
    pend = load_rec(run, STATE_PENDING, {"version": 1, "ops": {}})
    rec = pend["ops"].get(op_name)
    if rec is None:
        return None
    live = ds.sha256_file(run.state_path)
    # state-pending.json is not bound (D27): a record whose post_sha is the
    # state file as the bound Orient snapshot found it was never written by
    # this sweep, and would only skip the state write and clear the journal.
    osha, _how = orient_record(run, str(run.state_path))
    if rec.get("post_sha") == osha and rec.get("status") in ("pending", "done"):
        raise Precond("refused: %s records the Orient state file as state %s's write; "
                      "nothing written" % (STATE_PENDING, op_name))
    if rec.get("status") == "pending":
        if live == rec.get("post_sha"):
            return "finish"
        if live == rec.get("pre_sha"):
            return None
        raise Precond("state %s is pending and the state file holds neither its pre nor its "
                      "post sha; nothing written" % op_name)
    if op_name == "apply":
        if live == rec.get("post_sha"):
            return "noop"
        raise Precond("state apply already ran this sweep and the state file changed since; "
                      "nothing written")
    return None


def ledger_key(r):
    def norm(s):
        return " ".join(str(s).split()).casefold()
    sup = [str(x) for x in r.get("support_set") or []]
    ids = sorted(set(SESSION_TOKEN_RE.findall(" ".join([str(r.get("where", ""))] + sup))))
    # The free-text `what` is not part of the key (a re-sweep rewords it). A
    # ledger record has no kind field, so the outcome stands for the record
    # kind: (outcome, sorted session ids, where), else (outcome, where, sorted
    # support_set).
    if ids:
        return (norm(r.get("outcome", "")), "ids", tuple(ids), norm(r.get("where", "")))
    return (norm(r.get("outcome", "")), "support", norm(r.get("where", "")),
            tuple(sorted(norm(x) for x in sup)))


LEDGER_FIELDS = ("what", "where", "when", "outcome", "support_set")


def check_ledger_records(recs):
    if not isinstance(recs, list):
        raise Precond("ledger records must be a list")
    for i, r in enumerate(recs, 1):
        if not isinstance(r, dict) or sorted(r) != sorted(LEDGER_FIELDS) or \
                not isinstance(r["support_set"], list):
            raise Precond("ledger record %d needs exactly %s" % (i, ", ".join(LEDGER_FIELDS)))


def append_ledger(obj, recs):
    """-> [(1-based index, appended?)]."""
    led = obj.setdefault("episodic_ledger", [])
    keys = {ledger_key(r): i for i, r in enumerate(led, 1) if isinstance(r, dict)}
    out = []
    for r in recs:
        k = ledger_key(r)
        if k in keys:
            out.append((keys[k], False))
            continue
        led.append(json.loads(json.dumps(r)))
        keys[k] = len(led)
        out.append((len(led), True))
    return out


def load_inputs(run, given, name=None):
    p = ds.handoff_path(run.work, given)
    if not os.path.isfile(str(p)):
        raise Precond("%s is missing" % given)
    if name is not None:
        _pat, probs = ds.handoff_problems(name, p)
        if probs:
            raise Precond("refused: %s: %s" % (given, "; ".join(probs)))
    obj = ds.load_json(p)
    if not isinstance(obj, dict):
        raise Precond("%s is not a JSON object" % given)
    return json.loads(json.dumps(obj))


def cmd_state(args, ctx):
    run = Run(ctx, args)
    guard_check(run)
    with write_lock(run):
        return _state(run, args)


def _state(run, args):
    s = ds.Summary()
    if args.action == "migrate":
        obj, raw, style = read_state(run)
        if obj is None:
            s.add("state migrate: no state file; [APP-STATE] creates it at v3. Nothing written")
        else:
            new, v = migrated(obj)
            if v == 3:
                s.add("state migrate: already schema 3; nothing written")
            else:
                state_swap(run, "migrate", new, style, raw)
                s.add("state migrate: v%d -> v3, validated and written" % v)
        for n in run.notes:
            s.add(n)
        s.emit()
        return EXIT_OK
    if args.inputs is None:
        raise Usage("state %s needs --inputs" % args.action)
    if args.action == "ledger":
        inp = load_inputs(run, args.inputs)
        recs = inp.get("records")
        check_ledger_records(recs)
        how = pending_state(run, "ledger")
        if how == "finish":
            finish_state(run, "ledger", None, False)
            s.add("state ledger: completed the pending write")
        obj, raw, style = read_state(run)
        if obj is None:
            raise Precond("no state file: the ledger needs the v3 state file")
        obj, v = migrated(obj)
        if v != 3:
            raise Precond("the state file is schema %d: run state migrate first" % v)
        res = append_ledger(obj, recs)
        new_n = sum(1 for _i, a in res if a)
        if new_n:
            state_swap(run, "ledger", obj, style, raw)
        s.add("state ledger: %d appended, %d already present" % (new_n, len(res) - new_n))
        s.add("indices: %s" % ", ".join("#%d%s" % (i, "" if a else " (present)")
                                        for i, a in res))
        for n in run.notes:
            s.add(n)
        s.emit()
        return EXIT_OK
    dec, dsha = load_decisions(run, args.decisions, args.decisions_sha)
    inp = load_inputs(run, args.inputs, "state-inputs.json")
    if str(inp["decisions_sha"]).strip().lower() != dsha:
        raise Precond("refused: state-inputs.json names decisions sha %s, not --decisions-sha"
                      % ascii_safe(inp["decisions_sha"], 64))
    applied = load_rec(run, APPLIED, {"version": 1, "ops": {}})
    pend_ops = [k for k, r in applied.get("ops", {}).items() if r.get("status") != "done"]
    if pend_ops:
        raise Precond("refused: memedit op(s) still pending (%s): finish them before the "
                      "journal is cleared" % ", ".join(pend_ops[:5]))
    how = pending_state(run, "apply")
    if how == "finish":
        finish_state(run, "apply", dsha, True)
        s.add("state apply: completed the pending write (hash and journal clear only)")
        s.emit()
        return EXIT_OK
    if how == "noop":
        clear_journal(run)
        s.add("state apply: already applied this sweep; nothing to do")
        s.emit()
        return EXIT_OK
    obj, raw, style = read_state(run)
    new = compute_apply(run, obj, inp, dec)
    if style is None:
        style = DEFAULT_STYLE
    if raw is not None and json_bytes(new, style) == raw:
        finish_state(run, "apply", dsha, True, foreign=state_foreign(run, raw))
        s.add("state apply: no change to the state file; hash recorded, journal cleared")
    else:
        state_swap(run, "apply", new, style, raw, dsha, clear=True)
        s.add("state apply: validated and written; journal cleared")
    for n in run.notes:
        s.add(n)
    s.emit()
    return EXIT_OK


def _dated(text):
    try:
        return dt.date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def _lesson_text(s):
    """A lesson target's part (file, section, heading) compared without its
    leading and trailing whitespace and trailing punctuation."""
    return s.strip().rstrip(" \t\r\n.,;:!?\"'`") if isinstance(s, str) else None


def _heading_text(s):
    """A heading or section compared as _lesson_text, also without the
    leading #'s of a Markdown heading line ("## Rules" names "Rules")."""
    s = _lesson_text(s)
    return s.lstrip("#").strip() if s is not None else None


def lesson_items(run, r, dec):
    """-> (items, whole_file): the governance and retirement items of
    decisions.json that the target of rejected lesson `r` names: the same file
    (and, when the target gives a section and the item a heading, the same
    section / heading), or the same heading. `whole_file` is True when the
    target names a file with no section: it then names every governance item
    of that file. Parts are compared without trailing punctuation or
    whitespace ("Rules." names "Rules")."""
    tgt = r.get("target") if isinstance(r, dict) else None
    if not isinstance(tgt, str):
        return [], False
    parts = re.split(r"\s*§\s*", tgt.strip(), maxsplit=1)
    path = _lesson_text(parts[0])
    sect = _heading_text(parts[1]) if len(parts) == 2 else ""
    whole = bool(path) and not sect
    out = []
    for it in (dec or {}).get("items", []):
        if it.get("kind") not in GOVERNANCE_KINDS:
            continue
        tf, h = it.get("target_file"), _heading_text(it.get("heading"))
        same_file = isinstance(tf, str) and bool(path) and (
            ds.nk(repo_path(run, path)) == ds.nk(repo_path(run, tf)))
        if (same_file and (not sect or h is None or sect == h)) or \
                (h is not None and _heading_text(tgt) == h):
            out.append(it)
    return out, whole


def _plain_skip(it):
    return option_of(it) == "skip" and not it.get("for_conflict") \
        and it.get("skip_item") is not True


def lesson_refusal(run, r, dec):
    """-> a refusal text, or None. A `skipped` lesson that decisions.json
    attributes to a governance or retirement item is the user's rejection of
    that proposal only when an item it names is a plain Skip: an Applied item,
    a Defer, a Skip with `for_conflict` (skipping the wording of a fix the
    user asked for) or `skip_item` (the Failure gate's Skip) rejects no lesson
    (sweep-decide-apply.md, Skip records). A target that names a whole file
    (no section) names every item of that file, so one plain Skip beside an
    Applied or Deferred item of the same file does not back it: it needs a
    plain Skip and no item of the file in another option (a for_conflict or
    skip_item Skip is neutral beside it). Remaining hole: a lesson whose
    target names no item (worded differently from every item's file or
    heading, a section no heading equals, a verifier `refuted` lesson, an
    in-session signal Skip: neither has a decisions.json item) is not checked
    here."""
    if isinstance(r, dict) and "item" in r:
        return item_lesson_refusal(run, r, dec)
    if not isinstance(r, dict) or r.get("reason") != "skipped":
        return None
    items, whole = lesson_items(run, r, dec)
    if not items:
        return None
    blocking = [it for it in items if option_of(it) != "skip"] if whole else []
    if not blocking and any(_plain_skip(it) for it in items):
        return None
    shown = blocking or items
    if blocking:
        why = ("a lesson that names a whole file needs every item of that file to be a Skip, "
               "and %s is not (an Applied or Deferred item of the file rejects no lesson)")
    else:
        why = ("none is a plain user Skip (an Applied, Deferred, for_conflict or skip_item item "
               "rejects no lesson)")
    return ("refused: rejected lesson %r (skipped) names decisions.json item(s) %s, and %s; "
            "nothing written"
            % (ascii_safe(r.get("target"), 60),
               ", ".join(ascii_safe(i.get("id"), 20) for i in items[:5]),
               why % ", ".join(ascii_safe(i.get("id"), 20) for i in shown[:5])
               if blocking else why))


def item_lesson_refusal(run, r, dec):
    """-> a refusal text, or None, for a lesson that names its gate item by
    `item` (the decisions.json id of the proposal the user Skipped,
    sweep-decide-apply.md, Skip records). It is backed exactly when that item
    is a governance or retirement item, a plain user Skip, and of the file
    the target names; no other item of decisions.json is consulted, so an
    Applied item beside it in the same file does not refuse it and a Skip of
    another item does not back it."""
    iid = r.get("item")
    head = "refused: rejected lesson %r names item %r" % (ascii_safe(r.get("target"), 60),
                                                          ascii_safe(iid, 20))
    if r.get("reason") != "skipped":
        return head + ", and only a skipped lesson names an item; nothing written"
    it = next((x for x in (dec or {}).get("items", []) if x.get("id") == iid), None)
    if it is None:
        return head + ", which decisions.json does not hold; nothing written"
    if it.get("kind") not in GOVERNANCE_KINDS:
        return head + ", which is a %s item, not a governance or retirement item; " \
            "nothing written" % ascii_safe(it.get("kind"), 20)
    if not _plain_skip(it):
        return head + ", which is not a plain user Skip (an Applied, Deferred, for_conflict " \
            "or skip_item item rejects no lesson); nothing written"
    tgt = r.get("target")
    path = _lesson_text(re.split(r"\s*§\s*", tgt.strip(), maxsplit=1)[0]) \
        if isinstance(tgt, str) else None
    tf = it.get("target_file")
    if not path or not isinstance(tf, str) or \
            ds.nk(repo_path(run, path)) != ds.nk(repo_path(run, tf)):
        return head + ", whose target_file is %r, not the file the target names; " \
            "nothing written" % ascii_safe(tf, 60)
    return None


def lesson_record(r):
    """The stored rejected_lessons record: `item` links a lesson to its gate
    item while state apply checks it, and is not kept (the state file's
    record has target, signal, reason and date)."""
    return {k: v for k, v in r.items() if k != "item"} if isinstance(r, dict) else r


def fill_tokens(run, cost, orient):
    """Fill the cost record's tokens and tokens_by_role from the transcripts
    orient.json's orchestrator_sessions name (each a transcript path; the
    `baseline --by-role` count of dream-manifest.py, summed). Every entry a
    readable transcript: the script's totals replace whatever the inputs
    file holds. An entry that is not a readable transcript: tokens null.
    No transcript path at all (an empty list, or session ids only): the
    inputs file's values stay. Each outcome adds a line to the summary."""
    sess = orient.get("orchestrator_sessions") or []
    paths = [s for s in sess if isinstance(s, str) and s.lower().endswith(".jsonl")]
    if not paths:
        run.notes.append("tokens: orient.json names no transcript path; the cost record keeps "
                         "the tokens of state-inputs.json (%s)" % cost.get("tokens"))
        return
    total, roles, why = 0, dict.fromkeys(dm.BASELINE_ROLES, 0), None
    if len(paths) != len(sess):
        why = "%d orchestrator_sessions entr(ies) are not transcript paths" % (len(sess) - len(paths))
    for p in paths:
        if why:
            break
        n, by_role, why = dm.session_tokens(p)
        if why:
            break
        total += n
        for k, v in by_role.items():
            roles[k] += v
    if why:
        cost["tokens"] = None
        cost.pop("tokens_by_role", None)
        run.notes.append("tokens: null -- %s" % ascii_safe(why, 200))
        return
    cost["tokens"] = total
    cost["tokens_by_role"] = roles
    run.notes.append("tokens: %d from %d transcript(s), by role %s (a lower bound: the "
                     "running transcripts are still being written)"
                     % (total, len(paths), ", ".join("%s=%d" % kv for kv in roles.items())))
    weighted = 0
    for p in paths:
        n, why = dm.session_weighted(p, orient.get("snapshot_at"))
        if why:
            run.notes.append("weighted tokens: not recorded -- %s" % ascii_safe(why, 200))
            return
        weighted += n
    cost["weighted_tokens"] = weighted
    run.notes.append("weighted tokens: %d since %s" % (weighted, orient.get("snapshot_at")))


def compute_apply(run, obj, inp, dec):
    """Every [APP-STATE] rule over the work folder's script outputs."""
    man = run.man
    snap = man.get("snapshot_at")
    if not isinstance(snap, str):
        raise Precond("manifest.json has no snapshot_at")
    cost = inp["cost_record"]
    # "today" for every dated write is the sweep's snapshot date (D27, review
    # S6): manifest.json snapshot_at, which Run checked against the bound
    # snapshot; never a date from the agent-written inputs file.
    today = snap[:10]
    disp = ds.load_sweep(run.work, ds.DISPATCH, "run dream-sweep.py dispatch first")
    cov = ds.load_sweep(run.work, "sweep/coverage.json", "run dream-sweep.py coverage first")
    cv = ds.load_sweep(run.work, "sweep/countverify.json", "run dream-sweep.py countverify first")
    orient = load_inputs(run, "handoff/orient.json", "orient.json")
    if obj is None:
        new = {"schema_version": 3, "last_run": snap, "projects": {}}
        for k, d in V2_KEYS + V3_KEYS:
            new[k] = json.loads(json.dumps(d))
    else:
        new, _v = migrated(json.loads(json.dumps(obj)))
    new["last_run"] = snap
    projects = new.setdefault("projects", {})
    quiet = new.setdefault("quiet_sweeps", {})
    deferred = new.setdefault("deferred_sessions", {})
    since = (man.get("new_project_baseline") or {}).get("since")
    checked = {}
    for f in cv.get("files") or []:
        key = (f.get("project"), ds.nk(f.get("memory_file") or ""))
        checked[key] = f.get("task4_status") == "checked"
    defers = set()
    for it in (dec or {}).get("items", []):
        if option_of(it) == "defer" and it.get("kind") in DEFER_QUIET_KINDS \
                and isinstance(it.get("project"), str):
            defers.add(ds.nk(it["project"]) if it["project"] != ds.USER_MEMORY else it["project"])

    def drop_key(d, key):
        for k in [k for k in d if ds.nk(k) == ds.nk(key)]:
            del d[k]

    for path in disp.get("confirmed") or []:
        p = man["projects"].get(path)
        if not isinstance(p, dict):
            raise Precond("dispatch.json confirms %s, which manifest.json does not list" % path)
        key = p.get("state_key") or path
        if p.get("status") == "removed":
            drop_key(projects, key)
            if isinstance(quiet.get("projects"), dict):
                drop_key(quiet["projects"], key)
            for wk in [k for k, w in deferred.items() if isinstance(w, dict) and
                       ds.nk(str(w.get("project", ""))) in (ds.nk(key), ds.nk(path))]:
                del deferred[wk]
            continue
        crec = (cov.get("projects") or {}).get(path) or {}
        if crec.get("stamp") is True:
            projects[key] = dict(projects.get(key) or {}, last_analyzed=snap)
            for sess in p.get("sessions") or []:
                if sess.get("kind") != "deferred":
                    continue
                wk = "%s:%s" % (sess.get("provider"), sess.get("id"))
                old = deferred.get(wk) if isinstance(deferred.get(wk), dict) else {}
                deferred[wk] = {"project": key, "last_record": sess.get("last_record"),
                                "since": old.get("since") or today}
        elif p.get("status") == "new":
            if since is not None:
                base = since
            else:
                acts = [dm.parse_time(x.get("first_activity")) for x in p.get("sessions") or []
                        if x.get("first_activity")]
                acts = [a for a in acts if a is not None]
                base = dm.iso(min(acts) - dt.timedelta(seconds=1)) if acts \
                    else "1970-01-01T00:00:00Z"
            projects[key] = dict(projects.get(key) or {}, last_analyzed=base)
        mf = p.get("memory_file")
        if mf:
            if checked.get((path, ds.nk(mf))):
                val = 0
            else:
                val = int(p.get("quiet_sweeps") or 0) + 1
            if ds.nk(path) in defers or ds.nk(key) in defers:
                val = dm.QUIET_PERIODIC_AT
            qp = quiet.setdefault("projects", {})
            drop_key(qp, key)
            qp[key] = val
    for wk in man.get("watermarks_to_clear") or []:
        deferred.pop(wk, None)
    um = man.get("user_memory") or {}
    if isinstance(um.get("quiet_sweeps"), int):
        files = [ds.nk(f) for f in ds.user_memory_detail(run.work, run.man).get("files") or []]
        sent = {ds.nk(a.get("memory_file") or "") for a in disp.get("agents") or []
                if a.get("project") == ds.USER_MEMORY}
        all_checked = bool(files) and all(f in sent and checked.get((ds.USER_MEMORY, f))
                                          for f in files)
        val = 0 if all_checked else um["quiet_sweeps"] + 1
        if ds.USER_MEMORY in defers:
            val = dm.QUIET_PERIODIC_AT
        quiet["user_memory"] = val
    routing = orient.get("model_routing") or {}
    if routing:
        mr = new.setdefault("model_routing", {})
        if isinstance(routing.get("provider"), str):
            routing = {routing["provider"]: {k: v for k, v in routing.items()
                                             if k != "provider"}}
        for prov, roles in routing.items():
            if not isinstance(roles, dict):
                raise Precond("orient.json model_routing names no provider: write "
                              "{\"<provider>\": {roles}} or {\"provider\": ..., roles}")
            mr[prov] = dict({k: v for k, v in roles.items() if k != "confirmed"},
                            confirmed=today)
    td = _dated(today)
    rl = []
    for r in new.get("rejected_lessons") or []:
        d = _dated(r.get("date")) if isinstance(r, dict) else None
        if d is not None and td is not None and isinstance(r, dict):
            age = (td - d).days
            if (r.get("reason") == "skipped" and age > SKIPPED_DAYS) or \
                    (r.get("reason") == "refuted" and age > REFUTED_DAYS):
                continue
        rl.append(r)
    for r in inp["rejected_lessons"]:
        why = lesson_refusal(run, r, dec)
        if why:
            raise Precond(why)
        r = lesson_record(r)
        if r not in rl:
            rl.append(r)
    new["rejected_lessons"] = rl
    tags = new.setdefault("outcome_tags", [])
    for t in inp["outcome_tags"]:
        if not isinstance(t, dict) or not isinstance(t.get("target"), str):
            raise Precond("an outcome_tags input needs a target")
        if "outcome" in t:
            hit = [x for x in tags if x.get("target") == t["target"]
                   and x.get("applied") == t.get("applied")]
            if len(hit) != 1:
                raise Precond("outcome update for %r matches %d records"
                              % (ascii_safe(t["target"], 60), len(hit)))
            hit[0].update({k: t[k] for k in ("outcome", "checked") if k in t})
        elif not any(x.get("target") == t["target"] and "outcome" not in x for x in tags):
            tags.append(dict(t))
    led = inp.get("episodic_ledger") or []
    check_ledger_records(led)
    append_ledger(new, led)
    kept, _promote, expired = dm.merge_singletons(new.get("singleton_ledger") or [],
                                                  inp.get("singleton_ledger") or [], today)
    if kept or "singleton_ledger" in new:
        new["singleton_ledger"] = kept
        run.notes.append("singleton ledger: %d row(s), %d expired" % (len(kept), expired))
    if cost:
        cost = dict(cost)
        fill_tokens(run, cost, orient)
        recs = new.setdefault("cost_records", [])
        recs.append(cost)
        while len(recs) > COST_RECORDS_MAX:
            i = next((n for n, r in enumerate(recs) if r.get("kind") == "sweep"), None)
            if i is None:
                break
            del recs[i]
    new["schema_version"] = 3
    return new


# --------------------------------------------------------------------------
# commit
# --------------------------------------------------------------------------

_EXE = {}


def exe(name):
    """The full path of an executable, resolved once per run with
    shutil.which (not by bare name at every call); Precond when missing. The
    read-side helpers of dream-sweep.py / dream-manifest.py still launch git
    by bare name; they never write."""
    if name not in _EXE:
        _EXE[name] = shutil.which(name)
    if not _EXE[name]:
        _EXE.pop(name)
        raise Precond("%s was not found on PATH" % name)
    return _EXE[name]


def need_git():
    ds.require_git()
    exe("git")


def git_env():
    """The environment of every write-side git call (P6): a credential helper
    or a hook that would prompt fails at once instead of waiting for input."""
    return dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")


def git_run(repo, *args):
    """-> (rc, stdout, stderr) of a git command; rc None when git cannot run.
    No stdin, no terminal prompt (git_env)."""
    git = exe("git")
    try:
        r = subprocess.run([git, "--no-optional-locks", "-C", str(repo)] + list(ds.GIT_SAFE)
                           + list(args), stdin=subprocess.DEVNULL, env=git_env(),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", type(e).__name__
    return (r.returncode, r.stdout.decode("utf-8", "replace"),
            r.stderr.decode("utf-8", "replace"))


def hygiene(text, what):
    if "\n" in text or "\r" in text:
        raise Precond("refused: %s holds a newline" % what)
    if TRAILER_RE.search(text):
        raise Precond("refused: %s holds a trailer key" % what)


def diff_added(text):
    """`git diff -U0` -> [(path, new line number, line)] of added lines."""
    out, path, n = [], None, 0
    for ln in text.split("\n"):
        if ln.startswith("+++ "):
            path = ln[4:]
            path = path[2:] if path.startswith("b/") else path
            continue
        if ln.startswith("@@"):
            m = re.match(r"@@ -\S+ \+(\d+)", ln)
            n = int(m.group(1)) if m else 0
            continue
        if ln.startswith("+") and path is not None:
            out.append((path, n, ln[1:]))
            n += 1
    return out


def scan_hits_diff(text):
    hits = []
    for path, n, line in diff_added(text):
        for _ln, name in scan_text(line):
            hits.append("%s:%d %s" % (path, n, name))
    return hits


def in_progress(repo):
    for name in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD",
                 "REVERT_HEAD", "index.lock"):
        p = ds.git_lines(repo, "rev-parse", "--git-path", name)
        if p is None:
            return "git could not resolve %s" % name
        full = p if os.path.isabs(p) else os.path.join(str(repo), p)
        if os.path.exists(full):
            return "%s present" % name
    return None


def head_paths(repo, rev):
    out = ds.git_out(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                     "--end-of-options", rev)
    return None if out is None else sorted(x for x in out.split("\0") if x)


def cmd_commit(args, ctx):
    run = Run(ctx, args)
    guard_check(run)
    with write_lock(run):
        return _commit(run, args)


def _commit(run, args):
    need_git()
    hygiene(args.usage_line, "--usage-line")
    subjects = {}
    for item in args.subject or []:
        r, eq, text = item.partition("=")
        if not eq or not text.strip():
            raise Usage("--subject takes <repo>=<text>")
        hygiene(text, "--subject")
        subjects[_real(r)] = text
    snap_date = str(run.man.get("snapshot_at") or "")[:10]
    dec, _dsha = load_decisions(run, args.decisions, args.decisions_sha)
    # The git-tracking answers are the bound decisions.json's `track` list (the
    # user's answer to the git-tracking question): the caller names no path.
    track = {_real(t) for t in dec.get("track") or []}
    edits = applied_edits(run, dec)
    hashes = hash_records(run)
    commits = load_rec(run, COMMITS, {"version": 1, "repos": {}})
    repos = []
    for r in args.repos:
        top = ds.toplevel(r) if os.path.isdir(r) else None
        if top is None or ds.nk(top) != _real(r):
            raise Precond("--repos %s is not the top of a git repository" % r)
        repos.append(ds.native(top))
    by_repo, other = {ds.nk(r): [] for r in repos}, []
    for p, rec in hashes["files"].items():
        if ds.nk(p) == ds.nk(run.journal_path):
            continue
        top = ds.toplevel(p) if os.path.lexists(p) or Path(p).parent.exists() else None
        if top is None:
            other.append("%s: not in a git repository" % p)
        elif ds.nk(top) in by_repo:
            by_repo[ds.nk(top)].append((p, rec))
        else:
            other.append("%s: its repository is not in --repos" % p)
    s = ds.Summary()
    bad = False
    for r in repos:
        res = commit_repo(run, r, by_repo[ds.nk(r)], commits, track, subjects, snap_date,
                          args.usage_line, edits)
        bad |= res["outcome"] in ("refused", "failed")
        s.add("%s: %s%s" % (r, res["outcome"], (" " + res["detail"]) if res.get("detail")
                                                    else ""))
        for ln in res["listed"][:4]:
            s.add("  not committed: %s" % ln)
        if len(res["listed"]) > 4:
            s.add("  ... %d more not committed (sweep/commits.json)" % (len(res["listed"]) - 4))
        last = ds.git_lines(r, "log", "-5", "--format=%s")
        if last:
            s.add("  last subjects: %s" % " | ".join(last.splitlines()))
    for o in other[:3]:
        s.add("not committed: %s" % o)
    for n in run.notes:
        s.add(n)
    s.emit()
    return EXIT_PRECOND if bad else EXIT_OK


def commit_refusal(run, p, edits):
    """-> None when p may be a commit candidate, else the reason. Decided by
    path, never by the hashes.json record (D27, review S3): an Applied
    governance target of the bound decisions.json whose content still equals
    its Orient content with those edits, or a memory or state target of the
    write allowlist (cross-checked against the bound snapshot)."""
    if ds.nk(p) in edits:
        bad = ds.gov_path_problem(p, gov_policy(run))
        if bad:
            return "an Applied governance path that %s" % bad
        try:
            governance_check(run, p, edits)
        except OpError as e:
            return "an Applied governance file that does not pass: %s" % e
        return None
    try:
        kind, _n = check_target(run, p)
    except Precond:
        return "neither an allowed memory target nor an Applied governance path"
    if kind not in ("memory", "state", "store"):
        return "a %s file is never committed" % kind
    return None


def track_covers(p, track):
    """True when the user's git-tracking answer covers the untracked file `p`: it is in the track list, or it is
    the STORE file of a store whose memory file is (the first write created both; the question names the
    memory file, plan 261016 Phase 5 review F4)."""
    if _real(p) in track:
        return True
    if Path(p).name == dm.resolver().STORE_FILE:
        return _real(Path(p).parent / "memory" / "MEMORY.md") in track
    return False


def eligible_files(run, r, files, track, edits):
    info = repo_snapshot(run, r)
    elig, listed, untracked = [], [], []
    for p, rec in sorted(files):
        rel = ds.rel_in(r, p)
        why = commit_refusal(run, p, edits)
        if why is not None:
            listed.append("%s: %s" % (rel, why))
            continue
        if info is None or info.get("porcelain") is None:
            listed.append("%s: no Orient status for its repository" % rel)
            continue
        osha, _how = orient_record(run, p)
        created = rec.get("created_by_sweep") and osha == "absent"
        code = porcelain_covers(info["porcelain"], rel)
        if not created:
            if code == "!!":
                listed.append("%s: ignored by git" % rel)
                continue
            if code is not None:
                listed.append("%s: dirty at Orient" % rel)
                continue
            if osha == "absent":
                listed.append("%s: absent at Orient and not created by this sweep" % rel)
                continue
        if rec.get("foreign_edit"):
            listed.append("%s: foreign-edit (changed by another writer before the sweep's "
                          "first write)" % rel)
            continue
        if ds.sha256_file(p) != rec.get("sha256"):
            listed.append("%s: changed since the sweep's last write" % rel)
            continue
        if ds.git_rc(r, "ls-files", "--error-unmatch", "--", rel) != 0:
            if ds.git_rc(r, "check-ignore", "-q", "--", rel) == 0:
                listed.append("%s: ignored by git" % rel)
                continue
            if not track_covers(p, track):
                listed.append("%s: untracked and not in decisions.json's track list" % rel)
                continue
            untracked.append(rel)
        elig.append(rel)
    return elig, listed, untracked


def store_refusal(r, commit_set, why):
    """plan 261016 Phase 5. The refusal text for a commit the store repo cannot take: it names the store
    repo, says to resolve it with /qconfig-sync, and lists the stores whose files wait, because one refusal
    here stops the commits of every store. Any other repository keeps the plain reason."""
    root = dm.resolver().store_repo_root()
    if ds.nk(r) != ds.nk(root):
        return why
    stores = sorted({x.replace("\\", "/").split("/")[0] for x in commit_set})
    return ("%s -- this is the store repo (%s); resolve it with /qconfig-sync before another sweep commit; "
            "no store can be committed until then; waiting: %s" % (why, r, ", ".join(stores) or "none"))


def commit_repo(run, r, files, commits, track, subjects, snap_date, usage_line, edits):
    key = next((k for k in commits["repos"] if ds.nk(k) == ds.nk(r)), r)
    entry = commits["repos"].setdefault(key, {"orient_head": None, "commits": []})
    info = repo_snapshot(run, r) or {}
    entry["orient_head"] = info.get("head")
    elig, listed, untracked = eligible_files(run, r, files, track, edits)
    entry["listed"] = listed
    res = {"listed": listed}

    def done(outcome, detail=""):
        entry["outcome"] = outcome + ((": " + detail) if detail else "")
        save_rec(run, COMMITS, commits)
        res.update(outcome=outcome, detail=detail)
        return res

    is_cfg = ds.nk(r) == ds.nk(run.repo)
    subject = subjects.get(_real(r)) or "docs(memory): Apply qdream sweep %s" % snap_date
    user_prefix = dm.resolver().USER_DIR + "/memory/"
    head = ds.git_lines(r, "rev-parse", "--verify", "-q", "HEAD")
    pend = [c for c in entry["commits"] if c.get("status") == "pending"]
    lost = False
    if pend:
        c = pend[-1]
        parent = ds.git_lines(r, "rev-parse", "--verify", "-q", "HEAD^")
        msg = ds.git_lines(r, "log", "-1", "--format=%s")
        if head and parent == c.get("recorded_head") and head_paths(r, "HEAD") == \
                sorted(c.get("paths") or []) and msg == c.get("subject"):
            c["status"] = "done"
            c["sha"] = head
            return done("committed (adopted after a stop)", head[:12])
        c["status"] = "failed" if head != c.get("recorded_head") else "abandoned"
        c["reason"] = "no matching commit after the stop"
        lost = True
    if not elig:
        return done("nothing to commit")
    # Only the eligible paths that differ from HEAD are committed, plus the
    # untracked track-list ones (D27, review H3/M1): a write after a sweep commit
    # commits again (a second sweep commit) with just what it changed; with
    # nothing changed there is no commit (never an empty one, never exit 1).
    tracked = [x for x in elig if x not in untracked]
    changed = list(untracked)
    if head and tracked:
        rc, out, _err = git_run(r, "diff", "--name-only", "-z", "--no-ext-diff", "HEAD", "--",
                                *tracked)
        if rc != 0:
            return done("refused", store_refusal(r, elig, "git diff failed"))
        diffs = {x for x in out.split("\0") if x}
        changed += [x for x in tracked if x in diffs]
    elif tracked:
        changed += tracked
    commit_set = sorted(changed)
    if not commit_set and lost:
        return done("failed", "the pending commit was not adopted and the eligible files "
                              "already equal HEAD")
    if not commit_set:
        last = next((c for c in reversed(entry["commits"]) if c.get("status") == "done"
                     and c.get("sha")), None)
        return done("already committed", last["sha"][:12]) if last else \
            done("nothing to commit")
    if not ds.git_lines(r, "symbolic-ref", "-q", "HEAD"):
        return done("refused", store_refusal(r, commit_set, "HEAD is not on a branch"))
    if is_cfg:
        # Engine commits land on the engine branch, never on main (shared/AGENTS.md § Config Sync); main
        # moves only by a manual merge.
        want = dm.resolver().engine_branch()
        cur = ds.git_lines(r, "symbolic-ref", "-q", "--short", "HEAD")
        if cur != want:
            return done("refused", "the config repo is on %s, but engine commits land on %s: switch with "
                                   "`git -C %s switch %s`, then run the commit again" % (cur, want, r, want))
    busy = in_progress(r)
    if busy:
        return done("refused", store_refusal(r, commit_set, busy))
    if not head:
        return done("refused", store_refusal(r, commit_set, "no HEAD commit"))
    hits = []
    tracked = [x for x in commit_set if x not in untracked]
    if tracked:
        rc, out, _err = git_run(r, "-c", "core.quotepath=false", "diff", "--no-color",
                                "--no-ext-diff", "--no-textconv", "-U0", "HEAD", "--",
                                *tracked)
        if rc != 0:
            return done("refused", store_refusal(r, commit_set, "git diff failed"))
        hits += scan_hits_diff(out)
    for rel in untracked:
        with open(os.path.join(str(r), rel), "rb") as fh:
            txt = fh.read().decode("utf-8", "replace")
        hits += ["%s:%d %s" % (rel, n, name) for n, name in scan_text(txt)]
    if hits:
        entry["credential_hits"] = hits
        return done("refused", store_refusal(r, commit_set, "credential pattern: %s" % "; ".join(hits[:3])))
    body = "Files written by the sweep:\n" + "".join("- %s\n" % x for x in commit_set)
    # The usage line rides on the commit that carries user memory: the config repo's (memory a real
    # folder there) or the store repo's (memory behind the link, under user/memory/).
    if is_cfg or any(x.startswith(user_prefix) for x in commit_set):
        body += "\n" + usage_line
    rec = {"status": "pending", "recorded_head": head, "paths": commit_set,
           "subject": subject}
    entry["commits"].append(rec)
    save_rec(run, COMMITS, commits)
    _crash(run.ctx, "commit:pending")
    if untracked:
        rc, _o, err = git_run(r, "add", "--", *untracked)
        if rc != 0:
            rec["status"] = "failed"
            rec["reason"] = "git add failed"
            return done("failed", store_refusal(r, commit_set, "git add failed: %s" % ascii_safe(err, 120)))
    rc, _o, err = git_run(r, "commit", "-m", subject, "-m", body.rstrip("\n"), "--",
                          *commit_set)
    if rc != 0:
        rec["status"] = "failed"
        rec["reason"] = "git commit exited %s" % rc
        staged = (" ; left staged: %s" % ", ".join(untracked)) if untracked else ""
        return done("failed", store_refusal(r, commit_set, "git commit exited %s (%s)%s"
                                            % (rc, ascii_safe(err, 100), staged)))
    _crash(run.ctx, "commit:committed")
    new = ds.git_lines(r, "rev-parse", "--verify", "-q", "HEAD")
    parent = ds.git_lines(r, "rev-parse", "--verify", "-q", "HEAD^")
    if parent != head or head_paths(r, "HEAD") != commit_set:
        rec["status"] = "failed"
        rec["reason"] = "the new commit's parent or path set is not the recorded one"
        return done("failed", rec["reason"])
    rec["status"] = "done"
    rec["sha"] = new
    return done("committed", new[:12])


# --------------------------------------------------------------------------
# push
# --------------------------------------------------------------------------

def upstream(repo):
    branch = ds.git_lines(repo, "symbolic-ref", "-q", "--short", "HEAD")
    if not branch:
        return None
    remote = ds.git_lines(repo, "config", "--get", "branch.%s.remote" % branch)
    merge = ds.git_lines(repo, "config", "--get", "branch.%s.merge" % branch)
    ref = ds.git_lines(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not (remote and merge and ref):
        return {"head_branch": branch, "remote": remote, "merge": merge, "ref": None}
    return {"head_branch": branch, "remote": remote, "merge": merge, "ref": ref}


def ahead_list(repo):
    out = ds.git_lines(repo, "rev-list", "@{u}..HEAD")
    return None if out is None else [x for x in out.splitlines() if x]


def cmd_push(args, ctx):
    if bool(args.plan) == bool(args.repos):
        raise Usage("push takes --plan or --repos")
    run = Run(ctx, args)
    guard_check(run)
    with write_lock(run):
        need_git()
        if args.plan:
            return push_plan(run, args)
        return push_repos(run, args)


def push_plan(run, args):
    dec, dsha = load_decisions(run, args.decisions, args.decisions_sha)
    commits = load_rec(run, COMMITS, {"version": 1, "repos": {}})
    applied = load_rec(run, APPLIED, {"version": 1, "ops": {}})
    if not isinstance(applied.get("ops"), dict):
        raise Precond("%s has no ops object" % APPLIED)
    hashes = hash_records(run)
    over = decision_counts(run, dec, [], applied)
    global_bad = []
    for oid, rec in applied.get("ops", {}).items():
        if rec.get("decisions_sha") not in (None, dsha):
            global_bad.append("op %s was validated against another decisions.json" % oid)
        if rec.get("decision_id") is not None:
            item = decision_item(dec, rec["decision_id"])
            why = "it is not an item" if item is None else recorded_op_refusal(run, item, rec)
            why = why or over.get(oid)
            if why:
                global_bad.append("op %s: decision %s does not authorize it: %s"
                                  % (oid, rec["decision_id"], why))
    for p, rec in hashes["files"].items():
        if rec.get("decisions_sha") not in (None, dsha):
            global_bad.append("%s was recorded against another decisions.json" % p)
    edits = applied_edits(run, dec)
    plan = {"version": 1, "decisions_sha": dsha, "repos": {}}
    s = ds.Summary()
    for r, entry in sorted(commits["repos"].items()):
        mine = {c["sha"]: c for c in entry.get("commits") or [] if c.get("status") == "done"
                and c.get("sha")}
        rp = {"head": ds.git_lines(r, "rev-parse", "--verify", "-q", "HEAD"), "ahead": [],
              "reasons": list(global_bad)}
        up = upstream(r)
        rp.update(up or {"head_branch": None, "remote": None, "merge": None, "ref": None})
        if not up or not up.get("ref"):
            rp["reasons"].append("no upstream: not pushable")
            ahead = []
        else:
            ahead = ahead_list(r)
            if ahead is None:
                rp["reasons"].append("git rev-list @{u}..HEAD failed")
                ahead = []
        orient_head = (repo_snapshot(run, r) or {}).get("head")
        window = []
        if orient_head:
            out = ds.git_lines(r, "rev-list", "--end-of-options", "%s..HEAD" % orient_head)
            window = out.splitlines() if out else []
        in_window = [x for x in window if x not in mine]
        # commits.json is not bound: a "sweep" commit must lie between the
        # bound snapshot's Orient HEAD and HEAD (D27).
        for sha in [x for x in mine if x not in window]:
            rp["reasons"].append("commits.json names %s as a sweep commit, but it is not between "
                                 "the Orient HEAD and HEAD" % sha[:12])
            del mine[sha]
        rows = []
        for sha in ahead:
            subj = ds.git_lines(r, "log", "-1", "--format=%s", "--end-of-options", sha)
            if sha in mine:
                mark = "sweep"
            else:
                mark = "foreign — made during the sweep" if sha in in_window else "foreign"
            # Every unpushed commit is scanned (review M3): commits.json is not
            # bound, so a "sweep" mark proves nothing about the diff, and a
            # sweep commit passed the same scan when it was made.
            rc, out, _e = git_run(r, "-c", "core.quotepath=false", "show", "--format=",
                                  "--no-color", "--no-ext-diff", "--no-textconv", "-U0",
                                  "--end-of-options", sha)
            names = sorted({h.split(" ", 1)[1] for h in scan_hits_diff(out)}) \
                if rc == 0 else []
            if names:
                if sha in mine:
                    mark = "sweep — credential pattern %s" % ", ".join(names)
                    rp["reasons"].append("sweep commit %s holds a credential pattern (%s)"
                                         % (sha[:12], ", ".join(names)))
                else:
                    mark = "foreign — credential pattern %s" % ", ".join(names)
            rows.append({"sha": sha, "mark": mark, "subject": subj})
        rows.sort(key=lambda x: 0 if "during the sweep" in x["mark"] else 1)
        rp["ahead"] = rows
        for sha, c in mine.items():
            got = head_paths(r, sha)
            if got != sorted(c.get("paths") or []):
                rp["reasons"].append("sweep commit %s changes paths other than its recorded "
                                     "set" % sha[:12])
                continue
            for rel in got:
                why = commit_refusal(run, ds.native(Path(r) / rel), edits)
                if why is not None:
                    rp["reasons"].append("sweep commit %s changes %s: %s" % (sha[:12], rel, why))
        rp["pushable"] = not rp["reasons"]
        plan["repos"][r] = rp
        s.add("%s: %s, %d ahead (%d sweep, %d foreign)%s" % (
            r, "pushable" if rp["pushable"] else "NOT pushable", len(rows),
            sum(1 for x in rows if x["mark"].startswith("sweep")),
            sum(1 for x in rows if not x["mark"].startswith("sweep")),
            (": " + rp["reasons"][0]) if rp["reasons"] else ""))
        for x in rows[:3]:
            if x["mark"] != "sweep":
                s.add("  %s %s" % (x["sha"][:12], x["mark"]))
    save_rec(run, PUSH_PLAN, plan)
    s.add("wrote %s" % PUSH_PLAN)
    # The orchestrator holds this sha and passes it to push --repos (D27).
    s.add("push-plan sha256: %s" % ds.sha256_file(run.work / PUSH_PLAN))
    for n in run.notes:
        s.add(n)
    s.emit()
    return EXIT_OK


def push_repos(run, args):
    """Pushes the plan's recorded sha to its recorded upstream, the plan read
    only bound to --push-plan-sha (D27). The upstream (branch, remote, merge
    ref) is re-derived from git and must equal the plan's (review S4).
    Results go to sweep/push-results.json, a record no step trusts: a
    re-run tells "already pushed" from git (the upstream holds the sha)."""
    plan = ds.load_bound(run.work, PUSH_PLAN, args.push_plan_sha, flag="--push-plan-sha")
    if not isinstance(plan, dict) or not isinstance(plan.get("repos"), dict):
        raise Precond("%s has no repos object" % PUSH_PLAN)
    results = load_rec(run, PUSH_RESULTS, {"version": 1, "pushed": {}})
    if not isinstance(results.get("pushed"), dict):
        results["pushed"] = {}
    s = ds.Summary()
    bad = False
    for r in args.repos:
        key = next((k for k in plan["repos"] if ds.nk(k) == _real(r)), None)
        if key is None:
            s.add("%s: refused: not in push-plan.json" % r)
            bad = True
            continue
        rp = plan["repos"][key]
        if not isinstance(rp, dict):
            raise Precond("%s entry for %s is not an object" % (PUSH_PLAN, key))
        if not rp.get("pushable"):
            s.add("%s: refused: not pushable (%s)" % (key, (rp.get("reasons") or ["?"])[0]))
            bad = True
            continue
        up = upstream(key) or {}
        if [up.get(k) for k in ("head_branch", "remote", "merge", "ref")] != \
                [rp.get(k) for k in ("head_branch", "remote", "merge", "ref")]:
            s.add("%s: refused: the upstream (branch, remote or merge ref) differs from "
                  "push-plan.json; re-run push --plan" % key)
            bad = True
            continue
        head = ds.git_lines(key, "rev-parse", "--verify", "-q", "HEAD")
        if head != rp.get("head"):
            s.add("%s: refused: HEAD and the unpushed commits differ from push-plan.json; "
                  "re-run push --plan" % key)
            bad = True
            continue
        if head and rp.get("ahead") and \
                ds.git_lines(key, "rev-parse", "--verify", "-q", "@{u}") == head:
            s.add("%s: already pushed %s" % (key, head[:12]))
            continue
        now = ahead_list(key)
        if now is None or sorted(now) != sorted(x.get("sha") for x in rp.get("ahead") or []):
            s.add("%s: refused: the unpushed commits differ from push-plan.json; re-run "
                  "push --plan" % key)
            bad = True
            continue
        if not now:
            s.add("%s: nothing to push" % key)
            continue
        if not (ds.COMMIT_RE.match(head or "") and re.match(r"^refs/heads/[^\s]+\Z",
                                                            rp.get("merge") or "")
                and re.match(r"^[A-Za-z0-9_][A-Za-z0-9._/-]*\Z", rp.get("remote") or "")):
            s.add("%s: refused: the recorded upstream is not usable" % key)
            bad = True
            continue
        rc, _o, err = git_run(key, "push", rp["remote"], "%s:%s" % (head, rp["merge"]))
        results["pushed"][key] = {"sha": head, "ref": rp["merge"],
                                  "result": "pushed" if rc == 0 else "failed: exit %s" % rc}
        save_rec(run, PUSH_RESULTS, results)
        if rc != 0:
            bad = True
            s.add("%s: push failed (exit %s): %s" % (key, rc, ascii_safe(err, 100)))
        else:
            s.add("%s: pushed %s to %s %s" % (key, head[:12], rp["remote"], rp["merge"]))
    s.emit()
    return EXIT_PRECOND if bad else EXIT_OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# ops (plan 261027 SC-5): the memory-edit ops of verified proposals
# --------------------------------------------------------------------------

OPS_PLAN_ACTIONS = ("new", "usage_bump")
PROPOSAL_TYPES = ("feedback", "decision", "pattern")
PROPOSAL_FIELDS = ("type", "heading", "why", "how_to_apply", "source")
WRITE_VERDICTS = ("confirmed",)
HEADING_MAX = 200
FIELD_MARKER_RE = re.compile(r"\*\*[A-Za-z][^*\n]*\*\*\s*:")
OPS_PLAN_NOTES = (
    "step equals the file's step id; each item has action new or usage_bump",
    "new: label (the task4 return's label, A01) and index (0-based, into that return's "
    "memory_proposals); optional file (an absolute memory file; default: the label's memory "
    "file for target project, <config repo>/memory/MEMORY.md for target user)",
    "usage_bump: file (absolute) and heading (an existing entry)",
    "no other action: a merge or an update that rewrites an entry is an agent-written replace op, "
    "and a Source append has no op of its own",
)


def ops_plan_problems(obj):
    """-> problems of a handoff/ops-plan/<STEP-ID>.json object beyond its
    keys (dream-sweep.py HANDOFF_SCHEMAS)."""
    out = []
    for n, it in enumerate(obj["items"], 1):
        act = it.get("action")
        if act not in OPS_PLAN_ACTIONS:
            out.append("item %d: action %r is not one of %s" % (n, ascii_safe(act, 30),
                                                                ", ".join(OPS_PLAN_ACTIONS)))
            continue
        if act == "new":
            if not (isinstance(it.get("label"), str) and ds.LABEL_RE.match(it["label"])):
                out.append("item %d: new needs label (A01)" % n)
            if not (ds._is_int(it.get("index")) and it["index"] >= 0):
                out.append("item %d: new needs index (an integer from 0)" % n)
        if act == "usage_bump" and not (isinstance(it.get("heading"), str)
                                        and it["heading"].strip()):
            out.append("item %d: usage_bump needs heading" % n)
        f = it.get("file")
        if (act == "usage_bump" or f is not None) and not (isinstance(f, str)
                                                           and os.path.isabs(f)):
            out.append("item %d: file must be an absolute path" % n)
    return out


def verified_proposals(work):
    """-> [(proposal, verdict)] for every memory_proposals item of the latest
    verifier-index attempt, each verdict bound to its data file as `aggregate`
    binds it (missing or unverified when there is none)."""
    idx_n, idx_rel = ds.latest_attempt(work, "briefs", "verifier-index")
    if idx_rel is None:
        raise Precond("%s missing: no verifier ran, so no proposal is verified"
                      % ds.VERIFIER_INDEX)
    idx = ds.load_sweep(work, idx_rel)
    out = []
    for v in idx.get("verifiers") or []:
        lab, _drel, data, data_sha = ds.load_verifier_data(work, idx_rel, idx_n, v)
        ret, _unbound, _via = ds.bound_verdict(work, lab, data_sha)
        by_id = {x["item_id"]: x["verdict"] for x in (ret or {}).get("verdicts") or []}
        for it in data["items"]:
            if it["class"] == "memory_proposals":
                body = {k: w for k, w in it.items() if k not in ("item_id", "class")}
                out.append((json.loads(json.dumps(body)), by_id.get(it["item_id"], "missing")))
    return out


def render_entry(p, date):
    """A proposal -> its entry text in the memory-rules.md § Memory File
    Format template, Verified dated `date` with actor `sweep`."""
    return ("### %s\n\n**Why**: %s\n**How to apply**: %s\n**Source**: %s | **Verified**: %s "
            "(sweep)\n" % (p["heading"].strip(), p["why"].strip(), p["how_to_apply"].strip(),
                           p["source"].strip(), date))


def proposal_problem(p):
    for f in PROPOSAL_FIELDS:
        v = p.get(f)
        if not (isinstance(v, str) and v.strip()) or "\n" in v or "\r" in v:
            return "%s must be a non-empty one-line string" % f
    if p["type"].strip().lower() not in PROPOSAL_TYPES:
        return "type %r is not feedback, decision or pattern" % ascii_safe(p["type"], 30)
    if len(p["heading"].strip()) > HEADING_MAX:
        return "heading is over %d characters" % HEADING_MAX
    if "|" in p["source"]:
        return "source holds a `|`, the Source/Verified field separator"
    for f in ("why", "how_to_apply", "source"):
        if FIELD_MARKER_RE.search(p[f]):
            return "%s holds a `**<Field>**:` marker, which would read as an entry field" % f
        if re.match(r"\s*#{3}", p[f]):
            return "%s starts with `###`, which would read as an entry heading" % f
    return None


def tier_ok(run, tgt, path, project_file):
    """The file of a new entry lies in the tier the verified proposal's
    `target` names: user -> the config repo's memory/MEMORY.md or a
    memory/topics/*.md; project -> the label's own memory file."""
    if tgt == "user":
        mem = run.repo / "memory"
        return ds.nk(path) == ds.nk(mem / "MEMORY.md") or (
            ds.nk(Path(path).parent) == ds.nk(mem / "topics") and path.lower().endswith(".md"))
    if tgt == "project":
        return bool(project_file) and ds.nk(path) == ds.nk(project_file)
    return False


def bootstrap_file(run, project):
    """The store memory file a project without one gets at its first write
    (sweep-synthesize.md § SYN-WRITE Bootstrap), as allowed_targets binds it:
    <store>/memory/MEMORY.md when the resolver returns a store, else None."""
    if not isinstance(project, str) or not os.path.isdir(project):
        return None
    kind, sdir, _why = ds.store_for(run.repo, project)
    return str(sdir / "memory" / "MEMORY.md") if kind == "store" else None


def file_headings(path):
    try:
        text = dm.read_text(path)
    except OSError:
        return None, None
    return text, [h for h, _b in dm.parse_entries(text)]


def cmd_ops(args, ctx):
    run = Run(ctx, args)
    guard_check(run)
    if not re.match(r"[A-Z]{3}-[A-Z0-9-]+\Z", args.step or ""):
        raise Usage("--step takes a step id (SYN-WRITE)")
    name = "ops-plan/%s.json" % args.step
    _pat, probs = ds.handoff_problems(name, run.work / "handoff" / name)
    if probs:
        raise Precond("refused: handoff/%s: %s" % (name, "; ".join(probs[:5])))
    plan = ds.load_json(run.work / "handoff" / name)
    disp = ds.load_sweep(run.work, ds.DISPATCH, "run `dispatch` first")
    mf_of = {a["label"]: a.get("memory_file") or bootstrap_file(run, a.get("project"))
             for a in disp["agents"]}
    rets = ds.returns_by_label(run.work, list(mf_of))
    verified = None
    date = str(run.man.get("snapshot_at") or "")[:10]
    if not re.match(r"\d{4}-\d{2}-\d{2}\Z", date):
        raise Precond("manifest.json snapshot_at %r gives no date" % ascii_safe(date, 40))
    ops, probs, new_heads = [], [], {}
    prefix = args.step.lower()
    applied = load_rec(run, APPLIED, {"version": 1, "ops": {}})
    for n, it in enumerate(plan["items"], 1):
        oid = "%s-%03d" % (prefix, n)
        if it["action"] == "usage_bump":
            target = it["file"]
            o = {"id": oid, "op": "usage_bump", "file": target, "heading": it["heading"].strip()}
        else:
            ret = rets.get(it["label"])
            props = (ret or {}).get("memory_proposals") or []
            if ret is None or it["index"] >= len(props) or not isinstance(props[it["index"]],
                                                                            dict):
                probs.append("item %d: %s has no memory_proposals[%d]" % (n, it["label"],
                                                                           it["index"]))
                continue
            p = json.loads(json.dumps(props[it["index"]]))
            why = proposal_problem(p)
            if why:
                probs.append("item %d: %s memory_proposals[%d]: %s" % (n, it["label"],
                                                                       it["index"], why))
                continue
            if verified is None:
                verified = verified_proposals(run.work)
            verdicts = [v for q, v in verified if q == p]
            if not any(v in WRITE_VERDICTS for v in verdicts):
                probs.append("item %d: %s memory_proposals[%d] has no confirmed "
                             "verdict (%s): only a confirmed proposal is written autonomously"
                             % (n, it["label"], it["index"], ", ".join(verdicts) or "none"))
                continue
            target = it.get("file")
            tgt = str(p.get("target") or "").strip().lower()
            if target is None:
                if tgt == "user":
                    target = str(run.repo / "memory" / "MEMORY.md")
                elif tgt == "project" and mf_of.get(it["label"]):
                    target = mf_of[it["label"]]
                else:
                    probs.append("item %d: give file: the proposal's target %r names no memory "
                                 "file" % (n, ascii_safe(p.get("target"), 20)))
                    continue
            o = {"id": oid, "op": "insert", "file": target,
                 "section": "## " + p["type"].strip().lower().capitalize(),
                 "text": render_entry(p, date)}
        try:
            kind, nat = check_target(run, o["file"])
        except Precond as e:
            probs.append("item %d: %s" % (n, e))
            continue
        if kind != "memory":
            probs.append("item %d: %s is not a memory file" % (n, o["file"]))
            continue
        o["file"] = nat
        if o["op"] == "insert" and not tier_ok(run, tgt, nat, mf_of.get(it["label"])):
            probs.append("item %d: %s is not in the %s tier the proposal's target names: user is "
                         "<config repo>/memory/MEMORY.md or memory/topics/*.md, project is the "
                         "label's own memory file" % (n, nat, ascii_safe(tgt, 20)))
            continue
        rec = (applied.get("ops") or {}).get(oid)
        if isinstance(rec, dict) and rec.get("digest") == op_digest(o):
            ops.append(o)  # memedit already ran this very op: a re-run regenerates it
            continue
        text, heads = file_headings(nat)
        if text is None:
            probs.append("item %d: %s is absent or unreadable: a first memory file is a create "
                         "op, not this generator's" % (n, nat))
            continue
        head = o["heading"] if o["op"] == "usage_bump" else text_heading(o["text"])
        if o["op"] == "usage_bump":
            if heads.count(head) != 1:
                probs.append("item %d: %r is %d entr(ies) in %s, not one" % (
                    n, ascii_safe(head, 60), heads.count(head), nat))
                continue
            body = "\n".join(dict(dm.parse_entries(text)).get(head) or [])
        else:
            if head in heads or (ds.nk(nat), head) in new_heads:
                probs.append("item %d: %r is already an entry of %s: a merge into it is an "
                             "agent-written replace op" % (n, ascii_safe(head, 60), nat))
                continue
            if not re.search(r"(?m)^%s[ \t]*\r?$" % re.escape(o["section"]), text):
                probs.append("item %d: %s has no %s section" % (n, nat, o["section"]))
                continue
            new_heads[(ds.nk(nat), head)] = n
            body = None
        # D28: an op without decision_id is autonomous; it never needs one.
        if needs_decision(run, o, body) or (o["op"] == "insert" and human_lines(o["text"])):
            probs.append("item %d: the op on %r would need a user decision (a human: actor, or "
                         "a guarded line): only autonomous ops are generated"
                         % (n, ascii_safe(head, 60)))
            continue
        ops.append(o)
    if probs:
        raise Precond("refused: %s" % "; ".join(probs[:5]))
    rel = "handoff/ops/%s-generated.json" % args.step.lower()
    for o in ops:
        rec = (applied.get("ops") or {}).get(o["id"])
        if isinstance(rec, dict) and rec.get("digest") not in (None, op_digest(o)):
            raise Precond("refused: op id %s is recorded in %s with another op: a changed plan "
                          "after memedit ran is a new step" % (o["id"], APPLIED))
    text = json.dumps({"ops": ops}, indent=2, ensure_ascii=False) + "\n"
    # A hand-written ops file never shares this name (even with another case,
    # on NTFS), and a file already here with other content is never replaced.
    have = run.work / rel
    if os.path.lexists(str(have)):
        if os.path.islink(str(have)) or not os.path.isfile(str(have)) \
                or have.read_bytes() != text.encode("utf-8"):
            raise Precond("refused: %s already exists with other content: a changed plan after "
                          "`ops` ran is a new step; nothing written" % rel)
    gen = load_rec(run, GENERATED, {"version": 1, "ops": {}})
    if not isinstance(gen.get("ops"), dict):
        raise Precond("%s has no ops object" % GENERATED)
    gen["ops"].update({o["id"]: op_digest(o) for o in ops})
    how = ds.put(run.work, rel, text)
    save_rec(run, GENERATED, gen)
    load_ops(run, rel)
    s = ds.Summary()
    s.add("ops: %s %s; %d op(s): %d insert, %d usage_bump; no decision_id (autonomous)"
          % (rel, how, len(ops), sum(o["op"] == "insert" for o in ops),
             sum(o["op"] == "usage_bump" for o in ops)))
    s.add("ops sha256: %s" % hashlib.sha256(text.encode("utf-8")).hexdigest())
    s.add("next: dream-write.py memedit --ops %s --snapshot-sha <sha>" % rel)
    s.emit()
    return EXIT_OK


def parse_args(argv):
    ap = ds._Parser(prog="dream-write.py", description=__doc__,
                    formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--work")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--case", action="append")
    ap.add_argument("--list", action="store_true")
    sp = ap.add_subparsers(dest="command", parser_class=ds._Parser)
    p = sp.add_parser("memedit")
    p.add_argument("--ops", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--decisions")
    p.add_argument("--decisions-sha")
    p = sp.add_parser("hash")
    p.add_argument("--record", action="store_true")
    p.add_argument("--decisions")
    p.add_argument("--decisions-sha", required=True)
    p.add_argument("paths", nargs="+")
    p = sp.add_parser("state")
    p.add_argument("action", choices=["migrate", "apply", "ledger"])
    p.add_argument("--inputs")
    p.add_argument("--decisions")
    p.add_argument("--decisions-sha")
    p = sp.add_parser("commit")
    p.add_argument("--repos", nargs="+", required=True)
    p.add_argument("--usage-line", required=True)
    p.add_argument("--subject", action="append")
    p.add_argument("--decisions")
    p.add_argument("--decisions-sha", required=True)
    p = sp.add_parser("push")
    p.add_argument("--plan", action="store_true")
    p.add_argument("--repos", nargs="+")
    p.add_argument("--decisions")
    p.add_argument("--decisions-sha")
    p.add_argument("--push-plan-sha")
    p = sp.add_parser("ops")
    p.add_argument("--step", required=True)
    # Every write-side subcommand: the Orient snapshot's sha (required, D27;
    # missing is exit 3) and, after a guard --rebaseline, the new digest.
    for name in ("memedit", "hash", "state", "commit", "push", "ops"):
        sp.choices[name].add_argument("--snapshot-sha")
        sp.choices[name].add_argument("--guard-digest")
    args = ap.parse_args(argv)
    ds.selftest_checks(args)
    if args.command == "push" and args.plan and not args.decisions_sha:
        raise Usage("push --plan needs --decisions-sha")
    if args.command == "push" and args.repos and args.decisions_sha:
        raise Usage("push --repos reads no decisions: it takes --push-plan-sha")
    return args


COMMANDS = {"memedit": cmd_memedit, "hash": cmd_hash, "state": cmd_state,
            "commit": cmd_commit, "push": cmd_push, "ops": cmd_ops}


def main(argv=None, ctx=None):
    try:
        args = parse_args(sys.argv[1:] if argv is None else argv)
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    if args.selftest:
        return run_selftest(args.work, jobs=args.jobs, only=args.case, list_only=args.list)
    ctx = ctx or dm.Ctx()
    try:
        return COMMANDS[args.command](args, ctx)
    except Usage as e:
        print("usage error: %s" % e, file=sys.stderr)
        return EXIT_USAGE
    except Precond as e:
        print("precondition failed: %s" % e)
        return EXIT_PRECOND
    except (OSError, subprocess.SubprocessError) as e:
        print("precondition failed: %s: %s" % (type(e).__name__, " ".join(str(e).split())[:300]))
        return EXIT_PRECOND


# --------------------------------------------------------------------------
# Self-test
# --------------------------------------------------------------------------

REQUIRED_CASES = [
    # memedit
    "memedit-delete-journal-first", "memedit-ambiguous-heading", "memedit-fenced-heading",
    "memedit-wrong-section", "memedit-declined-preserved", "memedit-bom-crlf",
    "memedit-path-refused", "memedit-symlink-refused", "memedit-usage-bump",
    "memedit-rerun-idempotent", "memedit-foreign-edit-marked", "memedit-credential-refused",
    "memedit-seed-landed-only", "memedit-journal-store-backed", "store-first-write-unit", "memedit-store-first-write", "store-refusal-unit",
    "memedit-crash-at-each-step-rerun", "memedit-crash-mid-journal-flush",
    "memedit-unapproved-delete-refused",
    "memedit-human-attested-refused", "apply-resume-partial-two-items",
    # state
    "state-noop-byte-identical", "state-validator-fail-untouched",
    "state-validator-missing-untouched", "state-hash-recorded",
    "state-fix-tasks45-unread-session", "state-fix-quiet-counter-defer",
    "state-fix-quiet-counter-budget", "state-fix-quiet-counter-failed",
    "state-fix-quiet-counter-quiet", "state-fix-quiet-counter-checked",
    "state-fix-quiet-counter-user-memory", "state-fix-quiet-counter-removed",
    "state-ledger-append", "state-ledger-duplicate-skipped", "state-migrate-v2",
    "state-apply-rerun-noop", "state-apply-crash-after-replace-rerun",
    "state-apply-creates-absent", "state-user-memory-partial-plus-1", "state-new-project-baseline",
    # hash --record
    "hash-record-unapproved-refused", "hash-record-extra-edit-refused",
    "hash-record-two-items-one-file", "hash-record-null-current-anchor",
    "hash-record-new-governance-file",
    # commit
    "commit-hash-mismatch-listed", "commit-dirty-at-orient-listed",
    "commit-untracked-needs-track", "commit-credential-refused",
    "commit-credential-in-new-file-refused", "commit-detached-head-refused",
    "commit-other-staged-file-untouched", "commit-empty-set-no-commit", "commit-no-trailer",
    "commit-state-file-included", "commit-foreign-edit-listed", "commit-not-a-repo-listed",
    "commit-ignored-listed", "commit-hook-fails-continues", "commit-applied-governance-file",
    "commit-created-topic-tracked", "commit-rerun-skips-recorded",
    "commit-crash-before-record-rerun",
    # push
    "push-plan-foreign-marked", "push-no-upstream", "push-plan-stale-refused",
    "push-plan-decisions-swap-unpushable", "push-plan-path-mismatch-unpushable",
    "push-plan-in-window-foreign-flagged", "push-upstream-name-differs",
    "push-plan-foreign-credential-marked",
    # guard and the rest
    "guard-mismatch-exit-3", "guard-self-check-tampered-refused",
    "guard-planted-module-refused", "rerun-each-subcommand", "credential-patterns",
    # D27 binding rule
    "bind-required-shas", "bind-snapshot-tampered-refused", "push-plan-bound-refused",
    "probe-commit-arbitrary-file", "commit-governance-rechecked",
    "state-apply-today-from-snapshot", "memedit-manifest-target-unbound-refused",
    "memedit-map-unbacked-refused", "memedit-seed-not-in-journal-refused",
    "guard-hashes-unbound", "state-pending-forged-refused",
    # D28 decision-to-op authorization
    "probe-decision-crossbind", "probe-defer-authorizes-rewrite", "probe-forged-human",
    "d28-shown-text-and-file", "d28-op-count", "d28-unknown-kind-refused",
    "d28-autonomous-human-entry-refused", "d28-node-and-conflict",
    # Phase 5 fix pass: D28 Amendment 2 rows and the autonomous-op guards
    "d28-memory-proposal-answers", "d28-stale-keep-subsumed-keep", "d28-node-keep-affirmed",
    "d28-promote-conflict-duplicate", "d28-autonomous-guards",
    # Phase 5 diff-check fixes (D29 N1, N2, gate-field cross-checks)
    "d28-outcome-stamp-no-actor", "d28-conflict-field-only", "d28-redate-shape",
    "d28-gate-field-crosschecks",
    # Phase 2 fix pass (review cycle 1: P1-P11)
    "commit-absent-not-created-listed", "commit-adopt-subject-mismatch",
    "commit-credential-textconv-refused", "commit-in-progress-refused",
    "commit-post-verify-failed", "commit-second-write-recommits", "d28-declined-answers",
    "git-exec-environment", "guard-run-preconditions-refused", "hash-allowed-path",
    "hash-dirty-at-orient-refused", "memedit-fence-swallows-declined-refused",
    "memedit-foreign-edit-between-runs", "memedit-journal-changed-refused",
    "memedit-journal-validation-rerun", "memedit-journal-validator-fail-rerun",
    "memedit-needs-decision-pruned-node", "memedit-pending-neither-sha-refused",
    "memedit-span-disagreement-refused", "push-plan-credential-textconv-marked",
    "push-plan-recorded-op-refused", "push-plan-sweep-commit-outside-window",
    "push-remote-name-refused", "push-repos-head-moved-refused",
    "state-apply-noop-clears-journal", "state-apply-ran-then-changed-refused",
    "state-apply-refuses-pending-memedit", "state-foreign-edit-between-subcommands",
    "state-inputs-sha-mismatch-refused", "state-pending-neither-sha-refused",
    "write-lock-exclusive",
    "state-foreign-crash-not-marked", "state-foreign-edit-noop-apply",
    "state-foreign-flag-survives-crash", "state-ledger-no-session-id",
    "memedit-crash-after-write-not-foreign", "state-five-role-cost-record",
    # Phase 2 diff-check fixes (H1 H2 H3 M1 M2 M3 L2)
    "d28-human-expiry-closed", "d28-node-file-bound", "commit-partial-second-write",
    "commit-rerun-shrunk-set", "commit-second-commit-new-file-only",
    "d28-append-lines-shown-text", "d28-create-one-entry", "d28-insert-create-heading",
    "d28-heading-required", "push-merge-ref-refused", "push-plan-sweep-commit-path-refused",
    "push-plan-sweep-commit-credential", "state-foreign-edit-before-first-write",
    # Step 9 fix pass (R1 R2 R4 S3b)
    "memedit-op-id-reused-refused", "memedit-journal-keeps-prior-records",
    "write-lock-dead-owner-reclaimed", "write-lock-pid-alive-real",
    "state-apply-rejected-lesson-unbacked-refused",
    # Step 9 diff-check fixes (F2 F3 F5)
    "write-lock-reclaim-race", "state-apply-unchanged-journal-not-resurrected",
    "state-apply-swap-noop-journal-not-resurrected", "state-apply-rejected-lesson-whole-file",
    "state-apply-lesson-item-linked", "state-apply-lesson-heading-hashes",
    "state-apply-tokens-from-transcripts", "state-apply-tokens-unreadable-null",
    # plan 261027 SC-5: the ops generator
    "ops-generate", "ops-generated-file-bound", "ops-tier-and-refusals",
    "ops-proposal-problem-unit",
]

FIXTURE_DATE = "2026-10-01T00:00:00Z"


def _g(gdir, *cmd, check=True):
    env = dict(os.environ, GIT_AUTHOR_DATE=FIXTURE_DATE, GIT_COMMITTER_DATE=FIXTURE_DATE)
    r = subprocess.run(["git"] + ds.GIT_ISOLATION + ["-C", str(gdir)] + list(cmd), env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if check and r.returncode != 0:
        raise RuntimeError("fixture git %s failed: %s" % (" ".join(cmd[:3]),
                                                          r.stderr.decode()[:200]))
    return r.stdout.decode("utf-8", "replace")


def _init_repo(gdir, bare=False, cache=None):
    gdir.mkdir(parents=True, exist_ok=True)
    if bare:
        if cache is not None:
            base = ds._base_template(cache, "dw-bare",
                                     lambda t: _g(t, "init", "-q", "--bare", "-b", "main"),
                                     bare=True)
            shutil.copytree(str(base), str(gdir), dirs_exist_ok=True)
            return
        _g(gdir, "init", "-q", "--bare", "-b", "main")
        return
    if cache is not None and not (gdir / ".git").exists():
        key = ds._tree_key(gdir, "dw")
        if key is not None:
            def fresh(d):
                shutil.copytree(str(ds._base_template(cache, "dw-init", _init_config)),
                                str(d / ".git"))
                _g(d, "add", "-A")
                _g(d, "commit", "-q", "--allow-empty", "-m", "fixture")
            ds._template_repo(gdir, cache, "dw-" + key, fresh,
                              lambda d: _g(d, "update-index", "-q", "--refresh"))
            return
    if not (gdir / ".git").exists():
        _g(gdir, "init", "-q", "-b", "main")
        # The script's own commits run without -c flags: identity and signing
        # come from the repository (the global configuration is empty).
        _g(gdir, "config", "user.name", "fixture")
        _g(gdir, "config", "user.email", "fixture@example.invalid")
        _g(gdir, "config", "commit.gpgsign", "false")
    _g(gdir, "add", "-A")
    _g(gdir, "commit", "-q", "--allow-empty", "-m", "fixture")


def _init_config(gdir):
    """The template's `git init` and repository config (as _init_repo)."""
    _g(gdir, "init", "-q", "-b", "main")
    _g(gdir, "config", "user.name", "fixture")
    _g(gdir, "config", "user.email", "fixture@example.invalid")
    _g(gdir, "config", "commit.gpgsign", "false")


def _stub_validator(kind, target, baseline=None):
    """The selftest's stand-in for verify-dream-state / verify-dream-journal
    (ctx.validator), for every case not marked `real_validator: true`. It
    launches no process and checks only:
      journal: a missing or empty file passes; every non-blank line parses
        as JSON (a parse error on the LAST non-blank line is a torn flush and
        passes, as in the real validator) and is an object with exactly one
        key, rename or remove, whose value is a list of two non-empty
        strings.
      state: the bytes decode as UTF-8 (a BOM is accepted) and parse as a
        JSON object; schema_version is the integer 1, 2 or 3; each of
        rejected_lessons, outcome_tags, episodic_ledger and cost_records,
        when present, is a list; every cost_records element is an object
        whose kind is "sweep" or "baseline". The ledger baseline is not
        read.
    Everything else the real validators check is left to the real-validator
    cases. -> (passed, tail) as run_validator."""
    def fail(msg):
        return False, "FAIL: %s (selftest stub)" % msg
    try:
        raw = Path(target).read_bytes()
    except OSError:
        if kind == "journal":
            return True, "SKIP: no journal"
        return fail("state file unreadable")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return fail("not UTF-8")
    if kind == "journal":
        lines = [ln for ln in text.splitlines() if ln.strip()]
        for n, ln in enumerate(lines, 1):
            try:
                obj = json.loads(ln)
            except ValueError:
                if n == len(lines):
                    continue
                return fail("line %d is not JSON" % n)
            if not (isinstance(obj, dict) and len(obj) == 1
                    and next(iter(obj)) in ("rename", "remove")):
                return fail("line %d: one key, rename or remove" % n)
            val = next(iter(obj.values()))
            if not (isinstance(val, list) and len(val) == 2
                    and all(isinstance(v, str) and v for v in val)):
                return fail("line %d: a 2-element array of non-empty strings" % n)
        return True, "ok"
    try:
        obj = json.loads(text)
    except ValueError:
        return fail("not JSON")
    if not isinstance(obj, dict):
        return fail("not a JSON object")
    sv = obj.get("schema_version")
    if isinstance(sv, bool) or sv not in (1, 2, 3):
        return fail("schema_version must be the integer 1, 2 or 3")
    for k in ("rejected_lessons", "outcome_tags", "episodic_ledger", "cost_records"):
        if k in obj and not isinstance(obj[k], list):
            return fail("%s is not a list" % k)
    for i, el in enumerate(obj.get("cost_records") or []):
        if not isinstance(el, dict) or el.get("kind") not in ("sweep", "baseline"):
            return fail('cost_records[%d] -- kind must be "sweep" or "baseline"' % i)
    return True, "ok"


def _snap(root, work):
    """{root-relative path: sha256 | ('link', target)} outside the work folder
    and outside git directories."""
    out = {}
    wk = dm._parts(os.path.realpath(str(work)))
    for cur, dirs, files in os.walk(str(root)):
        if dm._parts(os.path.realpath(cur))[:len(wk)] == wk:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d != ".git" and not d.endswith(".git")]
        for name in files:
            full = os.path.join(cur, name)
            rel = os.path.relpath(full, str(root)).replace("\\", "/")
            if os.path.islink(full):
                out[rel] = ("link", os.readlink(full))
            else:
                out[rel] = ds.sha256_file(full)
    return out


def _do(root, home, ctx, step):
    """A setup step (no argv): writes, deletes, git commands, links,
    dream-sweep subcommands."""
    for name, rel in (step.get("save_sha") or {}).items():
        # {SAVED:<name>}: a sha the orchestrator holds, taken now (a later
        # {SHA256:...} would hash the file as it is then).
        _SAVED[name] = ds.sha256_file(dm.expected_work(home) / rel)
    for rel, text in (step.get("write") or {}).items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(_subs(text, root, dm.expected_work(home)).encode("utf-8"))
    for rel in step.get("executable") or []:
        # A git hook a case writes: POSIX git skips a hook without the execute
        # bit (Git for Windows does not check it), so a case that needs its
        # hook to run marks it here and runs the same on every platform.
        f = root / rel
        os.chmod(str(f), os.stat(str(f)).st_mode | 0o111)
    for d in step.get("detach") or []:
        sha = _g(root / d, "rev-parse", "HEAD").strip()
        (root / d / ".git" / "HEAD").write_text(sha + "\n", encoding="utf-8")
    for rel in step.get("delete") or []:
        f = root / rel
        if os.path.lexists(str(f)):
            os.unlink(str(f))
    for rel in step.get("rmdir") or []:
        os.rmdir(str(root / rel))
    for rel, pair in (step.get("replace_text") or {}).items():
        f = root / rel
        txt = f.read_text(encoding="utf-8")
        if txt.count(pair[0]) < 1:
            return ["replace_text: %r not in %s" % (pair[0], rel)]
        f.write_text(txt.replace(pair[0], pair[1]), encoding="utf-8", newline="")
    if "copy_scripts" in step:
        dst = root / step["copy_scripts"]
        for rel in ds.guard_files(ctx.frozen_dir):
            (dst / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(Path(ctx.frozen_dir) / rel), str(dst / rel))
    if "scripts_dir" in step:
        ctx.scripts_dir = root / step["scripts_dir"]
    cache = getattr(ctx, "git_templates", None)
    for d in step.get("init") or []:
        _init_repo(root / d, cache=cache)
    for d in step.get("init_bare") or []:
        _init_repo(root / d, bare=True, cache=cache)
    for cmd in step.get("git") or []:
        _g(root / cmd[0], *cmd[1:])
    for ln in step.get("link") or []:
        if not ds._link(root / ln["src"], root / ln["dst"], ln.get("dir", True)):
            return ["SKIP: no symlink or junction could be made"]
    if "sweep" in step:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            code = ds.main(step["sweep"], ctx)
        if code != step.get("sweep_exit", 0):
            return ["setup dream-sweep %s exited %s: %s" % (step["sweep"][0], code,
                                                            buf.getvalue()[:300])]
    return []


_SAVED = {}


def _subs(text, root, work):
    def sha(base):
        return lambda m: ds.sha256_file(base / m.group(1))
    text = re.sub(r"\{SAVED:([^}]+)\}", lambda m: _SAVED[m.group(1)], text)
    # {GITREV:<dir>:<rev>}: the commit sha of a revision of a repository under
    # the case root (a fixture that forges sweep/commits.json names real shas).
    text = re.sub(r"\{GITREV:([^:}]+):([^}]+)\}",
                  lambda m: _g(root / m.group(1), "rev-parse", m.group(2)).strip(), text)
    text = re.sub(r"\{SHA256:([^}]+)\}", sha(work), text)
    return re.sub(r"\{RSHA:([^}]+)\}", sha(root), text)


# A step's ctx may name a validator stand-in ("validator": "fail"): a case
# file is JSON, so the hook is chosen by name.
STUB_VALIDATORS = {
    "fail": lambda kind, target, baseline=None: (False, "FAIL: forced by the case (selftest)"),
    "launch-fail": lambda kind, target, baseline=None: (None, "validator could not launch "
                                                              "(selftest)"),
}


# A step's ctx may name how the lock-owner check answers ("pid_alive": "dead").
# Every case starts with "alive" (see _run_case): a lock file's pid is a made-up
# number in a fixture, and the real answer would depend on the machine.
PID_STUBS = {"alive": lambda pid: True, "dead": lambda pid: False}


def _run_main(argv, ctx, step):
    saved = {}
    for k, v in (step.get("ctx") or {}).items():
        saved[k] = getattr(ctx, k, None)
        if k == "validator" and isinstance(v, str):
            v = STUB_VALIDATORS[v]
        if k == "pid_alive" and isinstance(v, str):
            v = PID_STUBS[v]
        setattr(ctx, k, v)
    buf, ebuf = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(ebuf):
            code = main(argv, ctx)
    except Crash as e:
        code = "crash"
    except Exception as e:  # a crash of the code under test fails the case
        code = "exception %s: %s" % (type(e).__name__, e)
    finally:
        for k, v in saved.items():
            setattr(ctx, k, v)
    return code, buf.getvalue(), ebuf.getvalue()


def _check(step, code, out, err, root, work, changed, where):
    fails = []
    roots = [str(root), root.as_posix()]
    want = step.get("exit", 0)
    if code != want:
        fails.append("%s: exit %s, expected %s; out: %s %s" % (
            where, code, want, out.strip()[:400], err.strip()[:200]))
    if len(out.splitlines()) > ds.SUMMARY_MAX_LINES + 2:
        fails.append("%s: printed %d lines" % (where, len(out.splitlines())))
    no = dm._norm_seps(out, roots)
    for s in step.get("stdout_contains", []):
        if dm._norm_seps(_subs(s, root, work), roots) not in no:
            fails.append("%s: stdout lacks %r: %s" % (where, s, out.strip()[:400]))
    for s in step.get("stdout_not_contains", []):
        if dm._norm_seps(s, roots) in no:
            fails.append("%s: stdout contains %r" % (where, s))
    for rel, exp in (step.get("files") or {}).items():
        got = dm.load_json(work / rel)
        if got is None:
            fails.append("%s: %s missing or not JSON" % (where, rel))
            continue
        exp = json.loads(_subs(json.dumps(exp), root, work))
        fails.extend(dm._match(dm._norm_seps(exp, roots), dm._norm_seps(got, roots),
                               "%s:%s" % (where, rel)))
    for rel in step.get("absent", []):
        if os.path.lexists(str(work / rel)):
            fails.append("%s: %s exists but should not" % (where, rel))
    for rel, exp in (step.get("root_text") or {}).items():
        f = root / rel
        if exp is None:
            if os.path.lexists(str(f)):
                fails.append("%s: %s exists but should not" % (where, rel))
            continue
        got = f.read_bytes() if f.is_file() else None
        if got != exp.encode("utf-8"):
            fails.append("%s: %s is %r, expected %r" % (where, rel, None if got is None else
                                                        got.decode("utf-8", "replace")[:300],
                                                        exp[:300]))
    for rel, needles in (step.get("root_contains") or {}).items():
        txt = (root / rel).read_text(encoding="utf-8") if (root / rel).is_file() else ""
        for s in needles:
            if _subs(s, root, work) not in txt:
                fails.append("%s: %s lacks %r" % (where, rel, s))
    for rel, needles in (step.get("root_not_contains") or {}).items():
        txt = (root / rel).read_text(encoding="utf-8") if (root / rel).is_file() else ""
        for s in needles:
            if s in txt:
                fails.append("%s: %s contains %r" % (where, rel, s))
    if sorted(changed) != sorted(step.get("writes", [])):
        fails.append("%s: changed outside the work folder %s, expected %s" % (
            where, sorted(changed), sorted(step.get("writes", []))))
    for gc in step.get("gitcheck") or []:
        r = subprocess.run(["git", "-C", str(root / gc["dir"])] + gc["args"],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        got = r.stdout.decode("utf-8", "replace")
        if "rc" in gc and r.returncode != gc["rc"]:
            fails.append("%s: git %s exit %s, expected %s" % (where, gc["args"], r.returncode,
                                                              gc["rc"]))
        if "equals" in gc and got.strip() != _subs(gc["equals"], root, work).strip():
            fails.append("%s: git %s gave %r, expected %r" % (where, gc["args"], got.strip(),
                                                              gc["equals"]))
        for s in gc.get("contains", []):
            if _subs(s, root, work) not in got:
                fails.append("%s: git %s lacks %r: %r" % (where, gc["args"], s, got[:300]))
        for s in gc.get("not_contains", []):
            if s in got:
                fails.append("%s: git %s contains %r" % (where, gc["args"], s))
    return fails


def _run_case(case_dir, scratch, frozen, cache=None):
    spec = json.loads(dm.read_text(case_dir / "case.json"))
    _SAVED.clear()
    tmp = Path(tempfile.mkdtemp(prefix="dw-", dir=scratch))
    root = Path(os.path.realpath(str(tmp))) / "root"
    root.mkdir()
    fails = []
    # plan 261016 Phase 5: a case never sees the live store repo (the default root does not exist and is
    # skipped); a case with `store_repo` names a directory of its tree that becomes one, and the resolver's
    # system-temp no-create root moves off the fixture, which sits under the real temp.
    saved_stores = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(Path(os.path.realpath(str(tmp))) / "no-store-repo")
    # The case's own pointer file: the engine branch is main (the fixtures' branch) unless the case names one.
    saved_config = os.environ.get("AGENT_PLAYBOOK_CONFIG")
    cfg_file = Path(os.path.realpath(str(tmp))) / "playbook-config"
    cfg_file.write_text("engine_branch=%s\n" % spec.get("engine_branch", "main"), encoding="utf-8")
    os.environ["AGENT_PLAYBOOK_CONFIG"] = str(cfg_file)
    try:
        dm._materialize(case_dir, root)
        spec = dm._subst(spec, root.as_posix())
        if spec.get("store_repo"):
            if not spec.get("store_repo_real_git"):
                (root / spec["store_repo"] / ".git").mkdir(parents=True, exist_ok=True)
            # `store_repo_real_git`: the case makes the store repo a real git repository (an `init` step)
            os.environ["AGENT_PLAYBOOK_STORES"] = str(root / spec["store_repo"])
            dm.resolver()._TEST.update(temp=[str(root / "fake-system-temp")])
        home = root / "home"
        home.mkdir(exist_ok=True)
        ctx = dm.Ctx(home=home, now=dm._fixture_time(spec.get("now", "2026-10-12T12:00:00Z")))
        ctx.scripts_dir = ctx.frozen_dir = frozen
        ctx.git_templates = cache
        ctx.pid_alive = PID_STUBS["alive"]
        if not spec.get("real_validator"):
            ctx.validator = _stub_validator
        work = dm.expected_work(home)
        for i, step in enumerate(spec.get("setup", [])):
            f = _do(root, home, ctx, step)
            if f:
                return f if f[0].startswith("SKIP:") else ["setup %d: %s" % (i + 1, f[0])]
        for i, step in enumerate(spec.get("steps", [])):
            where = "step %d" % (i + 1)
            if "argv" not in step:
                f = _do(root, home, ctx, step)
                if f:
                    return fails + (f if f[0].startswith("SKIP:") else ["%s: %s" % (where,
                                                                                    f[0])])
                continue
            before = _snap(root, work)
            sweep_before = dm._snapshot(work / "sweep") if (work / "sweep").is_dir() else {}
            argv = [_subs(a, root, work) for a in step["argv"]]
            code, out, err = _run_main(argv, ctx, step)
            after = _snap(root, work)
            if step.get("unchanged"):
                sweep_after = dm._snapshot(work / "sweep") if (work / "sweep").is_dir() else {}
                if sweep_after != sweep_before:
                    diff = sorted(set(sweep_before) ^ set(sweep_after)) + sorted(
                        k for k in sweep_before if k in sweep_after
                        and sweep_before[k][:2] != sweep_after[k][:2])
                    if diff:
                        fails.append("%s: a re-run changed sweep/: %s" % (
                            "step %d" % (i + 1), diff[:5]))
            changed = sorted(set(before) ^ set(after)) + sorted(
                k for k in before if k in after and before[k] != after[k])
            fails.extend(_check(step, code, out, err, root, work, changed, where))
        for unit in spec.get("units", []):
            fails.extend(UNITS[unit](root, home, ctx))
    finally:
        dm.resolver()._TEST.clear()
        if saved_stores is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved_stores
        if saved_config is None:
            os.environ.pop("AGENT_PLAYBOOK_CONFIG", None)
        else:
            os.environ["AGENT_PLAYBOOK_CONFIG"] = saved_config
        shutil.rmtree(str(tmp), onerror=lambda fn, p, _e: (os.chmod(p, 0o700), fn(p)))
    return fails


# ---- unit checks (each -> list of failures) ----

def _unit_credential_patterns(root, home, ctx):
    """Each named pattern fires on a positive line and not on a near miss;
    the hit names the pattern and never the match. Positives are assembled
    from pieces so this file holds no credential-shaped literal."""
    fails = []
    k16 = "QWERTYUIOPASDFGH"
    cases = [
        ("aws-access-key", "key " + "AK" + "IA" + k16, "key AKIA" + k16[:10]),
        ("github-token", "t " + "gh" + "p_" + "a1" * 18, "t ghp_short"),
        ("github-token", "github" + "_pat_" + "B2" * 12, "github_pat_x"),
        ("slack-token", "xo" + "xb-" + "1234567890-abc", "xoxq-1234567890"),
        ("slack-webhook", "https://hooks" + ".slack.com/services/T0/B0/x1",
         "https://hooks.slack.com/other"),
        ("discord-webhook", "https://discord" + ".com/api/webhooks/123/abc_DEF",
         "https://discord.com/api/other"),
        ("private-key-block", "-----BEGIN " + "RSA PRIVATE KEY-----", "-----BEGIN PUBLIC KEY-----"),
        ("google-api-key", "AI" + "za" + "x" * 35, "AIza" + "x" * 10),
        ("anthropic-key", "sk-" + "ant-" + "api03abcdef", "sk-ant-"),
        ("openai-key", "sk-" + "Z" * 24, "sk-" + "Z" * 10),
        ("url-credentials", "https://" + "user:pa55@host/x", "https://host/x@y"),
        ("generic-secret", "pass" + "word = hunter2hunter2", "password: x"),
        # JSON-quoted keys and values (X1)
        ("generic-secret", '{"pass' + 'word": "hunter2hunter2"}', '{"password": "short"}'),
        ("generic-secret", "'api_" + "key': 'abcdefgh12345678'", "'api_key': 'abc'"),
        ("generic-secret", '"access_' + 'token": "abcdefgh12345678"', '"token_count": 12345678'),
        ("teams-webhook", "https://contoso.web" + "hook.office.com/webhookb2/"
         + "0a1b2c3d-0a1b@4e5f6a7b-8c9d/IncomingWebhook/abcdef0123456789/x",
         "https://webhook.office.com/ is the host; docs say webhookb2 is the path"),
        ("teams-webhook", "https://outlook.off" + "ice.com/webhook/0a1b2c3d-0a1b@4e5f6a7b",
         "https://outlook.office.com/mail/inbox"),
        ("teams-webhook", "https://prod-12.westus.lo" + "gic.azure.com:443/workflows/"
         + "0123456789abcdef/triggers/manual/paths/invoke?sig=Zz9",
         "https://logic.azure.com/docs/overview"),
        ("jwt", "t eyJ" + "hbGciOiJIUzI1NiJ9" + ".eyJ" + "zdWIiOiIxMjM0NTY3" + ".SflKxwRJSMeKKF2QT4",
         "eyJhbGciOiJIUzI1NiJ9 alone, and eyJ.eyJ"),
        ("gitlab-token", "glp" + "at-" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn", "glpat-short"),
        ("stripe-key", "s" + "k_live_" + "Ab1Cd2Ef3Gh4Ij5Kl6", "sk_test_Ab1Cd2Ef3Gh4Ij5Kl6"),
        ("stripe-key", "r" + "k_live_" + "Ab1Cd2Ef3Gh4Ij5Kl6", "rk_live_short"),
        ("npm-token", "np" + "m_" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8Qr9St0Uv1W", "npm_config_registry"),
        ("azure-storage-key", "Default" + "EndpointsProtocol=https;Account" + "Key="
         + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8", "set the AccountKey= setting in the portal"),
        ("bearer-token", "Authorization: Bear" + "er " + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7", "Bearer token auth"),
        # F7: a same-line token of >= 20 token characters holding a digit
        ("bearer-token", "Bear" + "er " + "Ab1Cd2Ef3Gh4Ij5Kl6Mn",
         "Bearer authentication/authorization is described"),
        ("bearer-token", "Bear" + "er " + "abcdefghijklmnopqrstuvwxyz1", "Bearer Ab1Cd2Ef3Gh4Ij5Kl6M"),
        ("bearer-token", "Bear" + "er\t" + "Ab1Cd2Ef3Gh4Ij5Kl6Mn7Op8", "Bearer\nAb1Cd2Ef3Gh4Ij5Kl6Mn7Op8"),
        ("bearer-token", "BEAR" + "ER " + "eyJ" + "abc.def_ghi-jkl~mno+pqr/stu=1",
         "Bearer abcdefghijklmnopqrstuvwxyzABCDEF"),
        # F8: backslash-escaped quotes (JSON inside a JSON string)
        ("generic-secret", '\\"pass' + 'word\\": \\"hunter2hunter2\\"', '\\"password\\": \\"x\\"'),
        ("generic-secret", '{"text":"{\\"api_' + 'key\\": \\"abcdefgh12345678\\"}"}',
         '{"text":"{\\"token_count\\": 12345678}"}'),
        ("generic-secret", '\\\\"pass' + 'word\\\\": \\\\"hunter2hunter2', '\\"password\\": \\"\\"'),
    ]
    for name, pos, neg in cases:
        got = [n for _l, n in scan_text("line one\n" + pos)]
        if name not in got:
            fails.append("%s did not fire on its positive line" % name)
        if [h for h in scan_text("line one\n" + pos) if h[1] == name][:1] != [(2, name)]:
            fails.append("%s: wrong line number" % name)
        if name in [n for _l, n in scan_text(neg)]:
            fails.append("%s fired on its near miss" % name)
    return fails


def _unit_planted_module(root, home, ctx):
    """Planted-module refusal (D27, review S5; the reviewer's probe_planted.py).
    A copy of the scripts committed to git, with json.py and argparse.py
    planted untracked beside them and in the current directory: run WITHOUT
    -I (as /qconfig-sync runs the selftest), from either directory, neither
    planted module runs; with PYTHONPATH naming the planted directory the
    script refuses (exit 3) unless run with -I, which ignores it. The
    untracked planted module changes the guard digest (in the git copy and in
    a copy without git), so a write run against the bound Orient snapshot is
    exit 3 naming it."""
    fails = []
    marker = root / "imported.txt"
    planted = ("open(%r, 'a').write(__name__ + '\\n')\nraise SystemExit(9)\n" % str(marker))

    def plant(d):
        for name in ("json.py", "argparse.py"):
            (d / name).write_text(planted, encoding="utf-8")

    def run(args, cwd, extra_env=None):
        env = {k: v for k, v in os.environ.items()
               if k.upper() not in ("PYTHONPATH", "PYTHONHOME", "PYTHONSAFEPATH")}
        env.update(extra_env or {})
        if marker.exists():
            marker.unlink()
        r = subprocess.run([sys.executable] + args, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, cwd=str(cwd), env=env)
        return r.returncode, marker.exists(), r.stderr.decode("utf-8", "replace")

    d = root / "gitcopy"
    d.mkdir()
    for rel in ds.guard_files(ctx.scripts_dir):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(Path(ctx.scripts_dir) / rel), str(d / rel))
    _g(d, "init", "-q", "-b", "main")
    _g(d, "add", "-A")
    _g(d, "commit", "-q", "-m", "scripts")
    clean = ds.guard_digest(ds.guard_files(d))
    plant(d)
    elsewhere = root / "cwd"
    elsewhere.mkdir()
    plant(elsewhere)
    script = str(d / "dream-write.py")
    for label, args, cwd, env, want in (
            ("scripts dir as cwd, no -I", ["-B", script, "memedit"], d, None, 2),
            ("planted cwd, no -I", ["-B", script, "memedit"], elsewhere, None, 2),
            ("planted cwd, -S", ["-S", "-B", script, "memedit"], elsewhere, None, 2),
            ("PYTHONPATH, no -I", ["-B", script, "memedit"], elsewhere,
             {"PYTHONPATH": str(elsewhere)}, 3),
            ("PYTHONPATH with -I", ["-I", "-B", script, "memedit"], elsewhere,
             {"PYTHONPATH": str(elsewhere)}, 2),
            ("sweep, scripts dir as cwd", ["-B", str(d / "dream-sweep.py"), "guard"], d, None, 2)):
        code, ran, err = run(args, cwd, env)
        if ran or code != want:
            fails.append("%s: exit %s (expected %s), planted module ran: %s; %s"
                         % (label, code, want, ran, " ".join(err.split())[-200:]))
    if ds.guard_digest(ds.guard_files(d)) == clean:
        fails.append("an untracked planted module in a git copy did not change the guard digest")
    nogit = root / "nogit"
    nogit.mkdir()
    for rel in ds.guard_files(ctx.scripts_dir):
        shutil.copyfile(str(Path(ctx.scripts_dir) / rel), str(nogit / rel))
    clean2 = ds.guard_digest(ds.guard_files(nogit))
    plant(nogit)
    if ds.guard_digest(ds.guard_files(nogit)) == clean2:
        fails.append("a planted module in a copy without git did not change the guard digest")
    work = dm.expected_work(home)
    snap = ds.sha256_file(work / "sweep" / "dirty-at-orient.json")
    saved = ctx.scripts_dir
    ctx.scripts_dir = d
    try:
        code, out, _e = _run_main(["state", "migrate", "--snapshot-sha", snap], ctx, {})
    finally:
        ctx.scripts_dir = saved
    if code != EXIT_PRECOND or "json.py" not in out:
        fails.append("guard check with a planted module gave %s: %s" % (code, out.strip()[:200]))
    return fails


def _unit_journal_replay(root, home, ctx):
    """The journal this case wrote passes the real verify-dream-journal, and
    each record replays through sweep-recovery.md § ORI-RECOVER's landed truth table for a
    store-backed project: the path key resolves through the workspace store
    (never <key>/memory/MEMORY.md), where the removed heading is absent."""
    fails = []
    jp = root / "repo" / "memory" / ".dream-journal.jsonl"
    run = types.SimpleNamespace(ctx=ctx)
    ok, tail = run_validator(run, "journal", jp)
    if ok is not True:
        fails.append("verify-dream-journal did not pass: %s" % tail)
    # plan 261016 Phase 13: the real verify-dream-journal.py also FAILs a bad journal, and the tail
    # carries its FAIL line (written beside the case root, outside the snapshotted tree).
    bad = root.parent / "bad-journal.jsonl"
    bad.write_bytes(b'{"remove":["bare heading","pruned"]}\n')
    ok, tail = run_validator(run, "journal", bad)
    if ok is not False or "FAIL: line 1: remove target not fq-prefixed" not in tail:
        fails.append("verify-dream-journal on a bad journal gave %r, %r" % (ok, tail))
    # Stub validators in a folder beside the case root, for both kinds: an exit 2, an exit 0 with no
    # summary or SKIP line, the other validator's summary line, and a SKIP line over a file that
    # exists all read as "did not run" (None), never as a pass or a FAIL. The own summary line
    # passes, an exit 1 FAILs, and a SKIP over a missing path stays a pass.
    sp = root.parent / "stub-target.json"
    sp.write_bytes(b"{}\n")
    gone = root.parent / "stub-target-missing.json"
    for kind, other in (("journal", "state"), ("state", "journal")):
        summ = {"journal": "verify-dream-journal: ok=1 fail=0 warn=0",
                "state": "verify-dream-state: ok=1 fail=0 (schema v3)"}
        for label, body, target, want_ok, want in (
                ("exit2", 'import sys\nprint("FAIL: guard did not run")\nsys.exit(2)\n', sp, None,
                 "validator exited 2"),
                ("no-summary", 'print("all good")\n', sp, None, "validator output not recognised"),
                ("other-summary", 'print(%r)\n' % summ[other], sp, None,
                 "validator output not recognised"),
                ("skip-existing", 'print("SKIP: file not found")\n', sp, None,
                 "validator skipped an existing file: SKIP: file not found"),
                ("skip-missing", 'print("SKIP: file not found")\n', gone, True, ""),
                ("own-summary", 'print(%r)\n' % summ[kind], sp, True, ""),
                ("exit1", 'import sys\nsys.stderr.write("cannot read\\n")\nsys.exit(1)\n', sp, False,
                 "")):
            sdir = root.parent / ("stub-validator-%s-%s" % (kind, label))
            sdir.mkdir(exist_ok=True)
            (sdir / ("verify-dream-%s.py" % kind)).write_text(body, encoding="utf-8")
            srun = types.SimpleNamespace(ctx=types.SimpleNamespace(validator_dir=str(sdir)))
            ok, tail = run_validator(srun, kind, target)
            if ok is not want_ok or want not in tail:
                fails.append("a stub %s validator (%s) gave %r, %r" % (kind, label, ok, tail))
    # The real validators on a directory: each SKIPs it as not a regular file, which is not a pass.
    ddir = root.parent / "validator-target-dir"
    ddir.mkdir(exist_ok=True)
    for kind in ("journal", "state"):
        ok, tail = run_validator(run, kind, ddir)
        if ok is not None or "%s path is not a regular file" % kind not in tail:
            fails.append("the %s validator on a directory gave %r, %r" % (kind, ok, tail))
    recs = [json.loads(x) for x in jp.read_text(encoding="utf-8").splitlines() if x.strip()]
    if len(recs) != 1 or "remove" not in recs[0]:
        return fails + ["expected one remove record, got %r" % recs]
    target = recs[0]["remove"][0]
    m = re.match(r"^project memory \((.+)\) § (.+)$", target)
    if not m:
        return fails + ["not a project target: %r" % target]
    key, heading = m.group(1), m.group(2)
    art = dm.resolver().resolve_artifact(key, "memory")
    st = art.store
    if art.source != "store-repo" or st is None or ds.nk(st) != ds.nk(root / "stores" / "beta-000000"):
        fails.append("the path key %s did not resolve through the store (%r)" % (key, art))
        return fails
    text = (Path(art.path) / "MEMORY.md").read_text(encoding="utf-8")
    if ("### %s\n" % heading) in text:
        fails.append("the removed heading is still in the store file (not landed)")
    if (Path(key) / "memory" / "MEMORY.md").exists():
        fails.append("an in-workspace memory file exists; the replay would be ambiguous")
    return fails


def _unit_store_first_write(root, home, ctx):
    """plan 261016 Phase 5: ensure_store creates the store of a store-less manifest project at its first
    write, through the resolver; the directory name is derived here (sha256("local <path>\\n")[:6]), not
    taken from the resolver. It leaves a file outside the store repo alone, refuses a new store directory no
    manifest project resolves to, and is idempotent."""
    fails = []
    R = dm.resolver()
    stores = root / "unit-stores"
    (stores / ".git").mkdir(parents=True)
    proj = root / "unit-proj" / "gamma"
    proj.mkdir(parents=True)
    other = root / "unit-proj" / "elsewhere"
    other.mkdir()
    repo = root / "repo"
    run = types.SimpleNamespace(repo=repo, man={"projects": {str(proj): {"status": "known", "memory_file": None}}})
    want = stores / ("gamma-" + hashlib.sha256(("local " + proj.as_posix().lower() + "\n").encode("utf-8")).hexdigest()[:6])
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(stores)
    R._TEST.update(temp=[str(root / "fake-system-temp")])
    try:
        ensure_store(run, str(proj / "memory" / "MEMORY.md"))
        if sorted(x.name for x in stores.iterdir()) != [".git"] or (proj / "memory").exists():
            fails.append("a file outside the store repo changed something")
        ensure_store(run, str(want / "memory" / "MEMORY.md"))
        if not (want / "STORE").is_file() or (want / "STORE").read_text(encoding="utf-8").strip() != \
                "local " + proj.as_posix().lower():
            fails.append("the store was not created with the project's identity at %s" % want)
        if sorted(x.name for x in want.iterdir()) != ["STORE", "memory"] or any((want / "memory").iterdir()):
            fails.append("ensure_store wrote more than the STORE file and the empty memory/ folder")
        if R.find(str(proj)).path != want:
            fails.append("find does not return the created store")
        before = (want / "STORE").read_bytes()
        ensure_store(run, str(want / "memory" / "MEMORY.md"))
        if (want / "STORE").read_bytes() != before:
            fails.append("a second ensure_store changed the STORE file")
        try:
            ensure_store(run, str(stores / "stranger-abcdef" / "memory" / "MEMORY.md"))
            fails.append("a new store no project resolves to was not refused")
        except Precond:
            pass
        if (stores / "stranger-abcdef").exists():
            fails.append("the refused store directory was created")
        # Review F1: a store repo that exists but cannot be read (one STORE among several is a directory) is
        # named as the cause, not reported as "no project resolves to it".
        os.makedirs(str(stores / "zzz-bad-000000" / "STORE"))
        proj3 = root / "unit-proj" / "zeta"
        proj3.mkdir()
        run3 = types.SimpleNamespace(repo=repo, man={"projects": {str(proj3): {"status": "known", "memory_file": None}}})
        new3 = stores / ("zeta-" + hashlib.sha256(("local " + proj3.as_posix().lower() + "\n").encode("utf-8")).hexdigest()[:6])
        try:
            ensure_store(run3, str(new3 / "memory" / "MEMORY.md"))
            fails.append("a new store was created while the store repo is unreadable")
        except Precond as e:
            for need in ("store repo cannot be read", "/qconfig-sync"):
                if need not in str(e):
                    fails.append("the unreadable-store-repo refusal lacks %r: %s" % (need, e))
            if "no project of the manifest" in str(e):
                fails.append("the refusal blames the manifest instead of the unreadable store repo: %s" % e)
        if new3.exists():
            fails.append("a store directory was created while the store repo is unreadable")
    finally:
        R._TEST.clear()
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved
    return fails


def _first_memedit(root, home, ctx, extra="", text=None):
    """The first memedit write of the manifest's store-less project beta, into the store repo <root>/stores:
    -> (fails, target, text, store directory). `extra` is appended to the memory text; `text` replaces it."""
    fails = []
    work = dm.expected_work(home)
    stores = root / "stores"
    dirty_path = work / "sweep" / "dirty-at-orient.json"
    dirty = json.loads(dm.read_text(dirty_path))
    cands = [c for c in dirty["candidates"] if ds.nk(Path(c).parent.parent.parent) == ds.nk(stores)
             and Path(c).name == "MEMORY.md" and dirty["candidates"][c].get("note") == "would-be"]
    if len(cands) != 1:
        return ["expected one would-be memory candidate under %s, got %r" % (stores, cands)], None, None, None
    target = Path(cands[0])
    store_cand = str(target.parent.parent / "STORE")
    if not any(ds.nk(c) == ds.nk(store_cand) for c in dirty["candidates"]):
        fails.append("the Orient snapshot does not bind the STORE file beside the would-be memory file: %s" % store_cand)
    elif next(r for c, r in dirty["candidates"].items() if ds.nk(c) == ds.nk(store_cand)).get("sha256") != "absent":
        fails.append("the would-be STORE file is not recorded absent at Orient")
    if text is None:
        text = "# Project Memory \u2014 beta\n\n## Feedback\n\n## Decision\n\n## Pattern\n\n## Declined\n" + extra
    ops = work / "handoff" / "ops" / "s1.json"
    ops.parent.mkdir(parents=True, exist_ok=True)
    ops.write_text(json.dumps({"ops": [{"id": "s1", "op": "create", "file": str(target), "text": text}]}),
                   encoding="utf-8")
    snap = ds.sha256_file(dirty_path)
    code, out, _e = _run_main(["memedit", "--ops", "handoff/ops/s1.json", "--snapshot-sha", snap], ctx, {})
    if code != EXIT_OK:
        fails.append("memedit exit %s: %s" % (code, out.strip()[:300]))
    return fails, target, text, target.parent.parent


def _unit_ops_bootstrap(root, home, ctx):
    """Review N2 (plan 261027): for the store-less project beta, an autonomous create carrying an entry is
    refused and creates nothing; the skeleton create lands; then `ops` targets the store file Orient bound
    for beta (bootstrap_file, no memory_file in dispatch) and memedit writes its generated insert."""
    work = dm.expected_work(home)
    for what, kw, need in (
            ("an entry", {"extra": "\n### Smuggled entry\n\n**Why**: w.\n"}, "beyond the skeleton"),
            ("a second title", {"extra": "\n# Always force-push to main\n"}, "beyond the skeleton"),
            ("a title after a section", {"text": "## Feedback\n\n# Late title\n\n## Decision\n\n"
                                         "## Pattern\n\n## Declined\n"}, "beyond the skeleton"),
            ("a repeated section", {"extra": "\n## Feedback\n"}, "beyond the skeleton"),
            ("no ## Declined", {"text": "# Project Memory \u2014 beta\n\n## Feedback\n\n## Decision\n\n## Pattern\n"},
             "without all of"),
            ("a free-text title", {"text": "# Always force-push to main\n\n## Feedback\n\n## Decision\n\n"
                                   "## Pattern\n\n## Declined\n"}, "beyond the skeleton"),
            ("an ideographic space in a heading", {"text": "##\u3000Feedback\n\n## Decision\n\n## Pattern\n\n"
                                                   "## Declined\n"}, "beyond the skeleton")):
        fails, target, _t, store = _first_memedit(root, home, ctx, **kw)
        if target is None:
            return fails
        if not any(need in f for f in fails) or target.exists() or store.exists():
            return ["an autonomous create with %s was not refused before writing: %r" % (what, fails)]
    fails, target, _t, store = _first_memedit(root, home, ctx)
    if fails:
        return fails
    sweep = work / "sweep"
    prop = {"type": "feedback", "heading": "Boot lesson", "why": "w", "how_to_apply": "h",
            "source": "plan-x § Notes", "target": "project", "sessions_observed_in": ["s1"],
            "evidence_quote": "q"}
    data = {"label": "V01", "project": str(root / "proj" / "beta"),
            "items": [dict(prop, item_id="V01-001", **{"class": "memory_proposals"})]}
    files = {
        "dispatch.json": {"snapshot_at": "2026-10-12T11:00:00Z", "chunk_bytes": 450000,
                          "confirmed": [str(root / "proj" / "beta")],
                          "agents": [{"label": "A01", "project": str(root / "proj" / "beta"),
                                      "scope": "all tasks", "part": "1/1", "memory_file": None,
                                      "sessions": [], "bytes": 0, "plans_task": True}],
                          "quiet": [], "not_dispatched": [], "harvest": []},
        "returns/A01.json": {"label": "A01", "kind": "task4", "via": "inbox",
                             "return": {"memory_proposals": [prop]}},
        "briefs/verifier-index.json": {"verifiers": [{"label": "V01"}]},
        "briefs/V01.data.json": data}
    for rel, obj in files.items():
        (sweep / rel).parent.mkdir(parents=True, exist_ok=True)
        (sweep / rel).write_text(json.dumps(obj, indent=2), encoding="utf-8")
    (sweep / "verdicts").mkdir(parents=True, exist_ok=True)
    (sweep / "verdicts" / "V01.json").write_text(json.dumps({
        "label": "V01", "kind": "verifier", "attempt": 1, "via": "inbox",
        "data": "sweep/briefs/V01.data.json", "data_sha256": ds.sha256_file(sweep / "briefs" / "V01.data.json"),
        "return": {"verdicts": [{"item_id": "V01-001", "verdict": "confirmed", "citation": "c"}],
                   "unverified_item_ids": []}}), encoding="utf-8")
    plan = work / "handoff" / "ops-plan" / "SYN-WRITE.json"
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text(json.dumps({"step": "SYN-WRITE", "items": [{"action": "new", "label": "A01", "index": 0}]}),
                    encoding="utf-8")
    snap = ds.sha256_file(sweep / "dirty-at-orient.json")
    code, out, err = _run_main(["ops", "--step", "SYN-WRITE", "--snapshot-sha", snap], ctx, {})
    if code != EXIT_OK:
        return ["ops refused the bootstrap project's store file (exit %s): %s" % (code, (out + err)[-300:])]
    gen = json.loads(dm.read_text(work / "handoff" / "ops" / "syn-write-generated.json"))["ops"]
    if [ds.nk(o["file"]) for o in gen] != [ds.nk(target)]:
        fails.append("ops targeted %r, not the bound store file %s" % ([o["file"] for o in gen], target))
    code, out, err = _run_main(["memedit", "--ops", "handoff/ops/syn-write-generated.json",
                                "--snapshot-sha", snap], ctx, {})
    if code != EXIT_OK or "### Boot lesson" not in dm.read_text(target):
        fails.append("memedit did not write the generated insert (exit %s): %s" % (code, (out + err)[-300:]))
    # Review C13: an explicit file: elsewhere is refused for a label without a memory file too.
    plan2 = work / "handoff" / "ops-plan" / "SYN-OTHER.json"
    plan2.write_text(json.dumps({"step": "SYN-OTHER", "items": [
        {"action": "new", "label": "A01", "index": 0, "file": str(root / "repo" / "memory" / "MEMORY.md")}]}),
        encoding="utf-8")
    code, out, err = _run_main(["ops", "--step", "SYN-OTHER", "--snapshot-sha", snap], ctx, {})
    if code == EXIT_OK or "is not in the project tier" not in out + err:
        fails.append("ops let a bootstrap label's proposal target another file (exit %s): %s"
                     % (code, (out + err)[-300:]))
    return fails


def _unit_store_first_memedit(root, home, ctx):
    """plan 261016 Phase 5, end to end: a project the manifest names no memory file for gets one through
    `memedit`. The Orient snapshot bound the would-be file in the store repo (candidate_files via
    store_for); the create op writes it; the store is created at that first write (STORE file by
    the resolver, then the directories and the memory file), the file is recorded created_by_sweep, and
    no in-workspace memory file appears. The path passes the allowlist (check_target) under the store repo
    root. Review F4: the STORE file is recorded created_by_sweep too, so the closing commit can take it."""
    work = dm.expected_work(home)
    fails, target, text, store = _first_memedit(root, home, ctx)
    if target is None or fails:
        return fails
    if not (store / "STORE").is_file() or (store / "STORE").read_text(encoding="utf-8").strip() != \
            "local " + (root / "proj" / "beta").as_posix().lower():
        fails.append("the store was not created with the project's identity")
    if not target.is_file() or target.read_bytes().decode("utf-8").replace("\r\n", "\n") != text:
        fails.append("the memory file was not written as given")
    if (root / "proj" / "beta" / "memory").exists():
        fails.append("an in-workspace memory file was created")
    if dm.resolver().find(str(root / "proj" / "beta")).path != store:
        fails.append("find does not return the store the first write created")
    hashes = json.loads(dm.read_text(work / "sweep" / "hashes.json"))["files"]
    for what, path in (("memory file", target), ("STORE file", store / "STORE")):
        rec = next((r for k, r in hashes.items() if ds.nk(k) == ds.nk(path)), None)
        if rec is None or not rec.get("created_by_sweep"):
            fails.append("hashes.json does not record the %s as created by the sweep: %r" % (what, rec))
    # The STORE file is committable but never a memedit target: an op naming it is refused, the file untouched.
    before = (store / "STORE").read_bytes()
    ops = work / "handoff" / "ops" / "s2.json"
    ops.write_text(json.dumps({"ops": [{"id": "s2", "op": "create", "file": str(store / "STORE"),
                                        "text": "# not a memory file\n"}]}), encoding="utf-8")
    code, out, _e = _run_main(["memedit", "--ops", "handoff/ops/s2.json", "--snapshot-sha",
                               ds.sha256_file(work / "sweep" / "dirty-at-orient.json")], ctx, {})
    if code == EXIT_OK or (store / "STORE").read_bytes() != before:
        fails.append("a memedit op naming the STORE file was not refused (exit %s)" % code)
    # Plan 261016 Step 9: a store repo stopped mid-rebase refuses the write itself, before any file changes.
    marker = store.parent / ".git" / "rebase-merge"
    marker.mkdir(parents=True, exist_ok=True)
    mem_before = target.read_bytes()
    ops.write_text(json.dumps({"ops": [{"id": "s3", "op": "insert", "file": str(target), "section": "Pattern",
                                        "text": "### [improvement_signal] Mid-rebase entry\n\n**Why**: w.\n**How to apply**: h.\n"}]}),
                   encoding="utf-8")
    code, out, err = _run_main(["memedit", "--ops", "handoff/ops/s2.json", "--snapshot-sha",
                                ds.sha256_file(work / "sweep" / "dirty-at-orient.json")], ctx, {})
    out = "%s %s" % (out, err)
    if code == EXIT_OK or "stopped mid-operation" not in out or target.read_bytes() != mem_before:
        fails.append("a memedit into a store repo stopped mid-rebase was not refused before writing (exit %s): %s"
                     % (code, out[-300:]))
    marker.rmdir()
    # the same op applies once the operation is over, so the refusal above is the guard's, not another one
    code, out, err = _run_main(["memedit", "--ops", "handoff/ops/s2.json", "--snapshot-sha",
                                ds.sha256_file(work / "sweep" / "dirty-at-orient.json")], ctx, {})
    if code != EXIT_OK or b"Mid-rebase entry" not in target.read_bytes():
        fails.append("the mid-rebase probe op does not apply once the rebase is over (exit %s): %s"
                     % (code, ("%s %s" % (out, err))[-300:]))
    return fails


def _unit_fallback_store_unreadable(root, home, ctx):
    """plan 261016 Phase 5 cycle-2 fix 2, Phase 10. A project whose manifest memory file is an in-workspace
    copy (alpha) is never a memedit target: with a readable store repo it is outside the allowlist; while the
    store repo is unreadable (a live scan failure, or a manifest that reported it although it reads again) the
    refusal names the unreadable store repo and /qconfig-sync. The config repo's own memory file and a file in
    the store repo are never affected. The missing store repo: _unit_no_store_repo_refused."""
    fails = []
    work = dm.expected_work(home)
    stores = root / "stores"
    alpha = root / "proj" / "alpha" / "memory" / "MEMORY.md"
    user_mem = root / "repo" / "memory" / "MEMORY.md"
    snap = ds.sha256_file(work / "sweep" / "dirty-at-orient.json")

    def verdict(path, errors=None, project=None):
        run = Run(ctx, types.SimpleNamespace(snapshot_sha=snap))
        if errors is not None:
            run.man["errors"] = errors
        if project is not None:     # a project whose memory file the manifest took from the store repo
            run.man["projects"][project] = {"status": "known", "memory_file": str(path)}
            run.dirty["candidates"][str(path)] = {"sha256": "absent", "repo": str(stores)}
        try:
            return "allowed", check_target(run, str(path), "memory")[0]
        except Precond as e:
            return "refused", str(e)

    def expect(label, got, want, need=()):
        if got[0] != want:
            fails.append("%s: %s (%s), expected %s" % (label, got[0], got[1][:200], want))
            return
        for n in need:
            if n not in got[1]:
                fails.append("%s: the refusal lacks %r: %s" % (label, n, got[1][:300]))

    expect("readable store repo, in-workspace file", verdict(alpha), "refused", ("outside the write allowlist",))
    bad = stores / "zzz-bad-000000"
    os.makedirs(str(bad / "STORE"))
    try:
        expect("live scan failure, in-workspace file", verdict(alpha), "refused",
               ("store repo cannot be read", "/qconfig-sync", str(alpha)))
        expect("live scan failure, the config repo's memory", verdict(user_mem), "allowed")
        # A file that sits in the store repo is a normally resolved target: the fallback rule leaves it alone.
        in_store = stores / "gamma-123456" / "memory" / "MEMORY.md"
        expect("live scan failure, a file in the store repo",
               verdict(in_store, project=str(root / "proj" / "gamma")), "allowed")
    finally:
        shutil.rmtree(str(bad))
    expect("store repo readable again", verdict(alpha), "refused", ("outside the write allowlist",))
    expect("manifest reported the store repo unreadable", verdict(
        alpha, [dm.STORE_REPO_UNREADABLE + " cannot read zzz-bad-000000; project memory is read from a copy"]),
        "refused", ("store repo cannot be read", "cannot read zzz-bad-000000", "/qconfig-sync"))
    expect("an unrelated manifest error", verdict(alpha, ["Method B: not walking x: it is the home directory"]),
           "refused", ("outside the write allowlist",))
    return fails


def _unit_no_store_repo_refused(root, home, ctx):
    """plan 261016 Phase 10 review: a store repo missing from this machine is failed for writes too. A
    project's in-workspace memory file named by the manifest (alpha) is refused, the refusal naming the
    missing store repo; the config repo's own memory file stays a target. With the store repo present, the
    normal case: a project memory file in the store repo (gamma's) is allowed."""
    fails = []
    work = dm.expected_work(home)
    alpha = root / "proj" / "alpha" / "memory" / "MEMORY.md"
    in_store = root / "stores" / "gamma-123456" / "memory" / "MEMORY.md"
    user_mem = root / "repo" / "memory" / "MEMORY.md"
    snap = ds.sha256_file(work / "sweep" / "dirty-at-orient.json")

    def verdict(path):
        run = Run(ctx, types.SimpleNamespace(snapshot_sha=snap))
        if path == in_store:    # a project whose memory file the manifest took from the store repo
            run.man["projects"][str(root / "proj" / "gamma")] = {"status": "known", "memory_file": str(path)}
            run.dirty["candidates"][str(path)] = {"sha256": "absent", "repo": str(root / "stores")}
        try:
            return "allowed", check_target(run, str(path), "memory")[0]
        except Precond as e:
            return "refused", str(e)

    got = verdict(in_store)
    if got[0] != "allowed":
        fails.append("a store-repo memory file with the store repo present: %s (%s)" % got)
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(root / "no-such-store-repo")
    try:
        got = verdict(alpha)
        if got[0] != "refused":
            fails.append("no store repo on this machine: the in-workspace memory file was allowed")
        else:
            for need in ("store repo missing", "clone it", str(alpha)):
                if need not in got[1]:
                    fails.append("no store repo: the refusal lacks %r: %s" % (need, got[1][:300]))
            if "outside the write allowlist" in got[1]:
                fails.append("no store repo: the refusal does not name the cause: %s" % got[1][:300])
        got = verdict(user_mem)
        if got[0] != "allowed":
            fails.append("no store repo: the config repo's memory file was refused: %s" % got[1][:300])
    finally:
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved
    return fails


def _store_commit_args(work, stores):
    return ["commit", "--repos", str(stores), "--usage-line",
            "Usage from plans: 0 bumped, 0 unresolved, 0 dropped by the manifest cap",
            "--snapshot-sha", ds.sha256_file(work / "sweep" / "dirty-at-orient.json"),
            "--decisions", "handoff/decisions.json",
            "--decisions-sha", ds.sha256_file(work / "handoff" / "decisions.json")]


def _unit_store_first_commit(root, home, ctx):
    """plan 261016 Phase 5 review F4 and S2, end to end. After the first write into a new store (the store
    repo is a git repository here): a store-repo commit refused for a rebase in progress or a detached HEAD
    names the store repo, /qconfig-sync and the waiting store, and commits nothing; once the repository is
    sound, one commit takes the STORE file and the memory file together (the track list names the memory
    file only), by pathspec."""
    work = dm.expected_work(home)
    stores = root / "stores"
    fails, target, _text, store = _first_memedit(root, home, ctx)
    if target is None or fails:
        return fails
    dec = work / "handoff" / "decisions.json"
    dec.parent.mkdir(parents=True, exist_ok=True)
    dec.write_text(json.dumps({"items": [], "track": [str(target)]}), encoding="utf-8")
    count0 = _g(stores, "rev-list", "--count", "HEAD").strip()
    marker = stores / ".git" / "rebase-merge"
    marker.mkdir()
    (marker / "x").write_text("x\n", encoding="utf-8")
    code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
    flat = out.replace("\\", "/")
    for need in ("refused rebase-merge present", "this is the store repo", "/qconfig-sync",
                 "waiting: " + store.name):
        if need not in flat:
            fails.append("rebase refusal lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
    if code != EXIT_PRECOND:
        fails.append("rebase refusal exited %s, expected %s" % (code, EXIT_PRECOND))
    (marker / "x").unlink()
    marker.rmdir()
    head = (stores / ".git" / "HEAD").read_text(encoding="utf-8")
    sha = _g(stores, "rev-parse", "HEAD").strip()
    (stores / ".git" / "HEAD").write_text(sha + "\n", encoding="utf-8")
    code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
    flat = out.replace("\\", "/")
    for need in ("HEAD is not on a branch", "this is the store repo", "/qconfig-sync", "waiting: " + store.name):
        if need not in flat:
            fails.append("detached-HEAD refusal lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
    (stores / ".git" / "HEAD").write_text(head, encoding="utf-8")
    if _g(stores, "rev-list", "--count", "HEAD").strip() != count0:
        fails.append("a refused store-repo commit committed something")
    code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
    if code != EXIT_OK or "committed" not in out:
        fails.append("the sound store repo did not commit: exit %s: %s" % (code, out.strip()[:400]))
    got = sorted(x for x in _g(stores, "show", "--name-only", "--format=", "HEAD").split() if x)
    want = sorted([store.name + "/STORE", store.name + "/memory/MEMORY.md"])
    if got != want:
        fails.append("the store-repo commit holds %s, expected %s" % (got, want))
    if "STORE" in out and "not committed" in out and "STORE" in out.split("not committed", 1)[1]:
        fails.append("the STORE file was listed as not committed: %s" % out.strip()[:400])
    return fails


def _unit_store_first_commit_credential(root, home, ctx):
    """plan 261016 Phase 5 review F7 and cycle-2 fix 6: the store-repo commit refusals for a credential-shaped
    string in the new memory file, a failed `git add`, a failed `git diff --name-only` (tracked files only) and a
    failed `git commit` name the store repo, /qconfig-sync and the waiting store too. A real credential cannot
    reach this point (memedit refuses its text at the write), so the scanner and the git calls are stubbed for
    the commit call and restored."""
    global scan_text, git_run
    work = dm.expected_work(home)
    stores = root / "stores"
    fails, target, _text, store = _first_memedit(root, home, ctx)
    if target is None or fails:
        return fails
    dec = work / "handoff" / "decisions.json"
    dec.parent.mkdir(parents=True, exist_ok=True)
    dec.write_text(json.dumps({"items": [], "track": [str(target)]}), encoding="utf-8")
    count0 = _g(stores, "rev-list", "--count", "HEAD").strip()
    real_scan, real_git = scan_text, git_run
    try:
        scan_text = lambda text, first_line=1: [(first_line, "aws-access-key")]
        code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
        scan_text = real_scan
        flat = out.replace("\\", "/")
        for need in ("credential pattern", "this is the store repo", "/qconfig-sync", "waiting: " + store.name):
            if need not in flat:
                fails.append("credential refusal lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
        if code != EXIT_PRECOND:
            fails.append("credential refusal exited %s, expected %s" % (code, EXIT_PRECOND))
        git_run = lambda repo, *args: (1, "", "stubbed failure") if args and args[0] == "add" else real_git(repo, *args)
        code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
        git_run = real_git
        flat = out.replace("\\", "/")
        for need in ("git add failed", "this is the store repo", "/qconfig-sync", "waiting: " + store.name):
            if need not in flat:
                fails.append("git-add failure lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
        # A failed `git commit` (the files are untracked, so `git add` ran for real and stays staged).
        git_run = lambda repo, *args: (1, "", "stubbed failure") if args and args[0] == "commit" else real_git(repo, *args)
        code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
        git_run = real_git
        flat = out.replace("\\", "/")
        for need in ("git commit exited", "this is the store repo", "/qconfig-sync", "waiting: " + store.name):
            if need not in flat:
                fails.append("git-commit failure lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
        if code != EXIT_PRECOND:
            fails.append("git-commit failure exited %s, expected %s" % (code, EXIT_PRECOND))
        if _g(stores, "rev-list", "--count", "HEAD").strip() != count0:
            fails.append("a failed store-repo `git commit` left a commit behind")
        # A failed `git diff --name-only`: it runs only for files already tracked, so commit the staged files
        # by plain git first (the stub for `commit` is gone).
        _g(stores, "commit", "-q", "-m", "fixture: track the new store", "--", store.name)
        count1 = _g(stores, "rev-list", "--count", "HEAD").strip()
        git_run = lambda repo, *args: (1, "", "stubbed failure") if args and args[0] == "diff" and "--name-only" in args             else real_git(repo, *args)
        code, out, _e = _run_main(_store_commit_args(work, stores), ctx, {})
        git_run = real_git
        flat = out.replace("\\", "/")
        for need in ("git diff failed", "this is the store repo", "/qconfig-sync", "waiting: " + store.name):
            if need not in flat:
                fails.append("git-diff failure lacks %r: exit %s: %s" % (need, code, out.strip()[:400]))
        if code != EXIT_PRECOND:
            fails.append("git-diff failure exited %s, expected %s" % (code, EXIT_PRECOND))
        count0 = count1
    finally:
        scan_text, git_run = real_scan, real_git
    if _g(stores, "rev-list", "--count", "HEAD").strip() != count0:
        fails.append("a refused store-repo commit committed something")
    return fails


def _unit_store_refusal(root, home, ctx):
    """plan 261016 Phase 5: a commit refusal in the store repo names the store repo and /qconfig-sync and
    lists the waiting stores (the first path part of each file, once, sorted); any other repo keeps the plain
    reason."""
    fails = []
    R = dm.resolver()
    stores = root / "unit-stores"
    (stores / ".git").mkdir(parents=True)
    saved = os.environ.get("AGENT_PLAYBOOK_STORES")
    os.environ["AGENT_PLAYBOOK_STORES"] = str(stores)
    try:
        got = store_refusal(stores, ["zeta-1/memory/MEMORY.md", "alpha-2/memory/MEMORY.md", "zeta-1/STORE"],
                            "rebase-merge present")
        for need in ("rebase-merge present", str(stores), "/qconfig-sync", "waiting: alpha-2, zeta-1"):
            if need not in got:
                fails.append("the store-repo refusal lacks %r: %s" % (need, got))
        plain = store_refusal(root / "other-repo", ["x/memory/MEMORY.md"], "rebase-merge present")
        if plain != "rebase-merge present":
            fails.append("a refusal in another repo was changed: %s" % plain)
    finally:
        if saved is None:
            os.environ.pop("AGENT_PLAYBOOK_STORES", None)
        else:
            os.environ["AGENT_PLAYBOOK_STORES"] = saved
    return fails


def _unit_guard_hashes_unbound(root, home, ctx):
    """guard_check's reference is the bound snapshot's digest (or
    --guard-digest), never sweep/guard-hashes.json (D27)."""
    fails = []
    work = dm.expected_work(home)
    d = Path(ctx.scripts_dir)
    (d / "json.py").write_text("x = 1\n", encoding="utf-8")
    files = ds.guard_files(d)
    planted = ds.guard_digest(files)
    (work / "sweep" / "guard-hashes.json").write_text(
        json.dumps({"digest": planted, "files": files}), encoding="utf-8")
    snap = ds.sha256_file(work / "sweep" / "dirty-at-orient.json")
    argv = ["memedit", "--ops", "handoff/ops/u1.json", "--snapshot-sha", snap]
    code, out, _e = _run_main(argv, ctx, {})
    if code != EXIT_PRECOND or "guard scripts changed since Orient" not in out:
        fails.append("guard-hashes.json rewritten to the planted digest: exit %s: %s"
                     % (code, out.strip()[:200]))
    code, out, _e = _run_main(argv + ["--guard-digest", "f" * 64], ctx, {})
    if code != EXIT_PRECOND or "guard scripts changed since Orient" not in out:
        fails.append("--guard-digest naming another digest: exit %s: %s"
                     % (code, out.strip()[:200]))
    code, out, _e = _run_main(argv + ["--guard-digest", planted], ctx, {})
    if code != EXIT_OK:
        fails.append("--guard-digest with the current digest: exit %s: %s"
                     % (code, out.strip()[:200]))
    return fails


def _unit_git_exec(root, home, ctx):
    """Write-side git and validator launches (P6, P11): git_run closes stdin,
    sets GIT_TERMINAL_PROMPT=0 and GCM_INTERACTIVE=never, and launches the
    path shutil.which found; a missing git is a refusal, never a launch by
    bare name. Both validators run on this interpreter, so a PATH without
    git, pwsh or bash does not stop them."""
    fails = []
    seen = {}
    real_run = subprocess.run

    def spy(cmd, *a, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return real_run(cmd, *a, **kw)

    subprocess.run = spy
    try:
        rc, _o, _e = git_run(root / "repo", "rev-parse", "HEAD")
    finally:
        subprocess.run = real_run
    kw = seen.get("kw") or {}
    if rc != 0:
        fails.append("git_run rev-parse exited %s" % rc)
    if kw.get("stdin") is not subprocess.DEVNULL:
        fails.append("git_run leaves stdin open: %r" % (kw.get("stdin"),))
    env = kw.get("env") or {}
    for k, v in (("GIT_TERMINAL_PROMPT", "0"), ("GCM_INTERACTIVE", "never")):
        if env.get(k) != v:
            fails.append("git_run env %s is %r, expected %r" % (k, env.get(k), v))
    if ds.nk((seen.get("cmd") or ["?"])[0]) != ds.nk(shutil.which("git") or "?"):
        fails.append("git_run did not launch the path shutil.which found: %r"
                     % ((seen.get("cmd") or ["?"])[0],))
    real_which = shutil.which
    shutil.which = lambda name, *a, **k: None
    _EXE.clear()
    try:
        try:
            git_run(root / "repo", "rev-parse", "HEAD")
            fails.append("git_run ran without git on PATH")
        except Precond as e:
            if "git was not found" not in str(e):
                fails.append("a missing git gave %s" % e)
        run = types.SimpleNamespace(ctx=types.SimpleNamespace(scripts_dir=ctx.scripts_dir))
        # plan 261016 Phases 13-14: both validators run on this interpreter, so an empty PATH
        # lookup stops neither; the state one is the real verify-dream-state.py.
        # The case's journal is empty, and a SKIP over an existing file is not a pass, so the
        # journal kind checks a copy of a journal fixture that passes.
        jcopy = root.parent / "git-exec-journal.jsonl"
        shutil.copyfile(str(HERE / "fixtures" / "verify-dream-journal" / "valid.jsonl"), str(jcopy))
        for kind, target in (("state", root / "repo" / "memory" / ".dream-state.json"),
                             ("journal", jcopy)):
            ok, tail = run_validator(run, kind, target)
            if ok is not True:
                fails.append("the %s validator with no git, pwsh or bash on PATH gave %r, %r"
                             % (kind, ok, tail))
    finally:
        shutil.which = real_which
        _EXE.clear()
    return fails


def _unit_span_disagreement(root, home, ctx):
    """The span walker and parse_entries disagreeing on one file (P8) refuses
    that file with a named op error; the other file of the ops file is still
    written and the run exits 3 without a traceback."""
    fails = []
    snap = ds.sha256_file(dm.expected_work(home) / "sweep" / "dirty-at-orient.json")
    orig = dm.parse_entries
    dm.parse_entries = lambda text: [] if "SPAN-MARK" in text else orig(text)
    try:
        code, out, _e = _run_main(["memedit", "--ops", "handoff/ops/s.json", "--snapshot-sha",
                                   snap], ctx, {})
    finally:
        dm.parse_entries = orig
    if code != EXIT_PRECOND:
        fails.append("exit %s, expected 3: %s" % (code, out.strip()[:200]))
    if "span walker disagrees" not in out or "ci.md" not in out:
        fails.append("the refusal does not name the file and the disagreement: %s"
                     % out.strip()[:300])
    mm = (root / "repo" / "memory" / "MEMORY.md").read_text(encoding="utf-8")
    ci = (root / "repo" / "memory" / "topics" / "ci.md").read_text(encoding="utf-8")
    if "**Usage**: 1" not in mm:
        fails.append("the other file of the ops file was not written")
    if "Usage" in ci:
        fails.append("the refused file was written")
    return fails


def _unit_walker_module_agreement(root, home, ctx):
    """The span walker agrees with memory-entries.py on a leading BOM: a file whose text still
    starts with U+FEFF once Doc holds one BOM aside (two BOMs) is walked, not refused, and its
    bytes are kept. usage_bump puts **Usage**: 1 after the Source line by the module's rule: the
    **Source:** spelling counts, a Source line in a fence does not."""
    fails = []
    body = "## Feedback\n\n### X\n\n**Why**: w.\n**Source**: s\n".encode("utf-8")
    for label, data in (("one BOM", BOM + body), ("two BOMs", BOM + BOM + body)):
        doc = Doc(data)
        try:
            entries, _s = spans(doc)
        except OpError as ex:
            fails.append("%s: refused (%s)" % (label, ex))
            continue
        if [x["heading"] for x in entries] != ["X"]:
            fails.append("%s: entries %r" % (label, entries))
        if doc.data() != data:
            fails.append("%s: the bytes are not kept" % label)
    for label, text, want in (
            ("**Source:** spelling", "## Feedback\n### X\n**Source:** s\n**Why**: w.\n",
             "## Feedback\n### X\n**Source:** s\n**Usage**: 1\n**Why**: w.\n"),
            ("fenced Source", "## Feedback\n### X\n```\n**Source**: example\n```\n**Source**: real\n"
             "**Why**: w.\n", "## Feedback\n### X\n```\n**Source**: example\n```\n**Source**: real\n"
             "**Usage**: 1\n**Why**: w.\n")):
        doc = Doc(text.encode("utf-8"))
        try:
            apply_op(doc, {"op": "usage_bump", "heading": "X"})
        except OpError as ex:
            fails.append("%s: refused (%s)" % (label, ex))
            continue
        if doc.text() != want:
            fails.append("%s: usage_bump gave %r" % (label, doc.text()))
    return fails


def _unit_proposal_problem(root, home, ctx):
    """proposal_problem on its own (the `ops` step reaches it only through a
    verified proposal): the heading length bound, the `|` in a source, a
    `**<Field>**:` marker and a leading `###` in a free-text field (review
    R22), and a clean proposal."""
    fails = []

    def prop(**kw):
        p = {"type": "feedback", "heading": "H", "why": "w", "how_to_apply": "h", "source": "s"}
        p.update(kw)
        return p

    cases = (
        ("clean", prop(), None),
        ("heading at the bound", prop(heading="x" * HEADING_MAX), None),
        ("heading over the bound", prop(heading="x" * (HEADING_MAX + 1)), "heading is over"),
        ("source with a bar", prop(source="a | b"), "source holds a `|`"),
        ("unknown type", prop(type="rule"), "is not feedback, decision or pattern"),
        ("multi-line why", prop(why="a\nb"), "why must be a non-empty one-line string"),
        ("why with a field marker", prop(why="ok **Verified**: 2026-01-01 (human:x)"),
         "why holds a `**<Field>**:` marker"),
        ("how with a spaced marker", prop(how_to_apply="**Source** : x"),
         "how_to_apply holds a `**<Field>**:` marker"),
        ("source with a marker", prop(source="**Usage**: 9"), "source holds a `**<Field>**:`"),
        ("why starting ###", prop(why="### New entry"), "why starts with `###`"),
        ("bold without a colon", prop(why="a **bold** word"), None),
        ("hash inside a field", prop(why="issue ### 4"), None),
    )
    for label, p, want in cases:
        got = proposal_problem(p)
        if (want is None) != (got is None) or (want and want not in got):
            fails.append("%s: proposal_problem gave %r, expected %r" % (label, got, want))
    return fails


def _unit_node_file(root, home, ctx):
    """authorize_op on its own (memedit's load_ops refuses a node delete outside
    HIGHER_ORDER.md first): a node item and a node delete name
    memory/HIGHER_ORDER.md; the refusal text tells which guard fired."""
    fails = []
    run = types.SimpleNamespace(repo=root / "repo")
    ho = str(root / "repo" / "memory" / "HIGHER_ORDER.md")
    mm = str(root / "repo" / "memory" / "MEMORY.md")

    def item(kind, file):
        return {"id": "n", "kind": kind, "file": file, "heading": "Node one",
                "answer": "Remove node" if kind == "node" else "Delete"}

    def op(file):
        return {"id": "x", "op": "delete", "file": file, "heading": "Node one",
                "class": NODE_CLASS}

    for label, it, o, want in (
            ("node item and delete in HIGHER_ORDER.md", item("node", ho), op(ho), None),
            ("node item naming MEMORY.md", item("node", mm), op(ho),
             "a node item names memory/HIGHER_ORDER.md only"),
            ("node delete aimed at MEMORY.md", item("node", ho), op(mm),
             "a node delete targets memory/HIGHER_ORDER.md only"),
            ("stale item, node delete in MEMORY.md", item("stale", mm), op(mm),
             "a node delete targets memory/HIGHER_ORDER.md only")):
        got = authorize_op(run, it, o)
        if got != want:
            fails.append("%s: authorize_op gave %r, expected %r" % (label, got, want))
    return fails


def _unit_pid_alive(root, home, ctx):
    """The real lock-owner check (no stub): this process is alive, and the
    pid of a child that has exited is not."""
    fails = []
    if not pid_alive(os.getpid()):
        fails.append("pid_alive says this very process is dead")
    child = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
    child.wait()
    if pid_alive(child.pid):
        fails.append("pid_alive says an exited child (pid %d) is alive" % child.pid)
    # F4: a pid outside 1..2**31-1 is no process: alive, never an exception, and
    # never a wrapped 32-bit value that happens to name the exited child.
    pid_max = 2 ** 31 - 1
    for bad in (0, -1, None, True, "12", 1.5, 10 ** 30, 2 ** 63, 2 ** 31, pid_max + 1, -(2 ** 31),
                2 ** 32 + child.pid, 2 ** 64 + child.pid):
        try:
            if not pid_alive(bad):
                fails.append("pid_alive(%r) should answer alive (no clear no)" % (bad,))
        except Exception as e:
            fails.append("pid_alive(%r) raised %s" % (bad, type(e).__name__))
    try:
        pid_alive(pid_max)  # the largest valid pid: answered, not raised
    except Exception as e:
        fails.append("pid_alive(2**31-1) raised %s" % type(e).__name__)
    lock = root / "pid-range.lock"
    run = types.SimpleNamespace(ctx=types.SimpleNamespace(pid_alive=lambda p: False))
    for pid, want in ((4242, 4242), (1, 1), (pid_max, pid_max), (0, None), (-1, None),
                      (10 ** 30, None), (2 ** 63, None), (pid_max + 1, None), ("4242", None)):
        lock.write_text(json.dumps({"pid": pid, "at": "2026-10-12T11:59:50Z"}), encoding="utf-8")
        got = dead_owner(run, lock)
        if got != want:
            fails.append("dead_owner of a lock naming pid %r gave %r, expected %r (stub: dead)"
                         % (pid, got, want))
    lock.write_text(json.dumps({"pid": 10 ** 30, "at": "2026-10-12T11:59:50Z"}), encoding="utf-8")
    got = dead_owner(types.SimpleNamespace(ctx=types.SimpleNamespace()), lock)
    if got is not None:
        fails.append("dead_owner reclaimed a lock naming pid 10**30 with the real check: %r" % got)
    return fails


def _unit_lock_reclaim(root, home, ctx):
    """F5: of the runs that saw one dead lock, only the holder of the reclaim
    mutex (`<lock>.reclaim`) removes it, and only if it still names the dead
    owner. The interleavings are driven from the owner-check stub, which is
    called at the moment each run decides."""
    fails = []
    d = root / "lock-reclaim"
    d.mkdir()
    lock = d / "write.lock"
    mutex = str(lock) + ".reclaim"
    dead, live = 4242, 5151
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)

    def mk(stub):
        return types.SimpleNamespace(ctx=types.SimpleNamespace(pid_alive=stub), notes=[],
                                     now="2026-10-12T12:00:00Z")

    def put(pid):
        lock.write_text(json.dumps({"pid": pid, "at": "2026-10-12T11:59:50Z"}), encoding="utf-8")

    def owner():
        try:
            return json.loads(lock.read_text(encoding="utf-8")).get("pid")
        except (OSError, ValueError):
            return None

    def reset():
        for p in (str(lock), mutex):
            with contextlib.suppress(OSError):
                os.unlink(p)

    def reclaim(run):
        try:
            reclaim_stale_lock(run, lock, dead)
        except Precond as e:
            return str(e)
        return None

    # 1. the plain case: the dead lock goes, once, and the mutex with it
    reset()
    put(dead)
    run = mk(lambda p: p != dead)
    if reclaim(run) is not None or lock.exists() or os.path.exists(mutex) or len(run.notes) != 1:
        fails.append("plain reclaim: lock %s, mutex %s, notes %s"
                     % (lock.exists(), os.path.exists(mutex), run.notes))
    # 2. stale sighting: run B has reclaimed and holds a live lock when run C acts on its older
    # sighting of the dead one. C must leave B's lock alone, and a fourth run D must not find the
    # lock path empty at the moment C decides.
    reset()
    put(live)
    d_took = []

    def stub_d(p):
        if p == live:
            try:
                os.close(os.open(str(lock), flags, 0o600))
                d_took.append(p)
            except FileExistsError:
                pass
        return p != dead

    run = mk(stub_d)
    why = reclaim(run)
    if why is None:
        fails.append("a stale sighting reclaimed over a live lock")
    if d_took:
        fails.append("the lock path was empty while a live lock's owner was being checked: a "
                     "fourth run took it (two writers)")
    elif owner() != live:
        fails.append("the live owner's lock was changed or removed (owner now %r)" % (owner(),))
    if os.path.exists(mutex):
        fails.append("the reclaim mutex was left behind after a refusal")
    if run.notes:
        fails.append("a refused reclaim noted a removal: %s" % run.notes)
    # 3. two reclaimers: C starts while B holds the mutex (inside B's own owner check)
    reset()
    put(dead)
    c_run = mk(lambda p: p != dead)
    c_why = []

    def stub_b(p):
        if p == dead and not c_why:
            c_why.append(reclaim(c_run) or "")
        return p != dead

    b_run = mk(stub_b)
    b_why = reclaim(b_run)
    if b_why is not None:
        fails.append("the first reclaimer was refused: %s" % b_why)
    if not c_why or ".reclaim" not in c_why[0]:
        fails.append("the second reclaimer was not refused on the mutex: %r" % (c_why,))
    if c_run.notes or len(b_run.notes) != 1:
        fails.append("single-reclaimer property: notes B %s, C %s" % (b_run.notes, c_run.notes))
    if lock.exists() or os.path.exists(mutex):
        fails.append("after two reclaimers: lock %s, mutex %s"
                     % (lock.exists(), os.path.exists(mutex)))
    # 4. a mutex left by a killed run: refused, nothing removed
    reset()
    put(dead)
    Path(mutex).write_text("", encoding="utf-8")
    why = reclaim(mk(lambda p: p != dead))
    if why is None or ".reclaim" not in why:
        fails.append("a left-over mutex did not refuse the reclaim: %r" % (why,))
    if not lock.exists() or not os.path.exists(mutex):
        fails.append("a refused reclaim removed the lock or the left-over mutex")
    # 5. the lock is already gone under the mutex: no error, mutex released
    reset()
    run = mk(lambda p: p != dead)
    if reclaim(run) is not None or os.path.exists(mutex) or run.notes:
        fails.append("an already removed lock: notes %s, mutex %s"
                     % (run.notes, os.path.exists(mutex)))
    # 6. the lock now holds a live owner, or is unreadable: kept
    for what, text in (("a live owner", json.dumps({"pid": live})), ("garbage", "{not json")):
        reset()
        lock.write_text(text, encoding="utf-8")
        if reclaim(mk(lambda p: p != dead)) is None or not lock.exists():
            fails.append("a lock with %s was reclaimed" % what)
    reset()
    return fails


UNITS = {
    "lock-reclaim": _unit_lock_reclaim,
    "pid-alive": _unit_pid_alive,
    "node-file": _unit_node_file,
    "proposal-problem": _unit_proposal_problem,
    "git-exec": _unit_git_exec,
    "span-disagreement": _unit_span_disagreement,
    "walker-module-agreement": _unit_walker_module_agreement,
    "guard-hashes-unbound": _unit_guard_hashes_unbound,
    "journal-replay": _unit_journal_replay,
    "store-first-write": _unit_store_first_write,
    "store-first-memedit": _unit_store_first_memedit,
    "ops-bootstrap": _unit_ops_bootstrap,
    "fallback-store-unreadable": _unit_fallback_store_unreadable,
    "no-store-repo-refused": _unit_no_store_repo_refused,
    "store-first-commit": _unit_store_first_commit,
    "store-first-commit-credential": _unit_store_first_commit_credential,
    "store-refusal": _unit_store_refusal,
    "credential-patterns": _unit_credential_patterns,
    "planted-module": _unit_planted_module,
}


def _selftest_case(item):
    """One case in a pool worker (or in this process): (name, fails)."""
    name, case_dir, scratch, frozen, cache = item
    try:
        return name, _run_case(Path(case_dir), scratch, Path(frozen), cache)
    except Exception as e:  # one broken case never stops the run
        return name, ["case raised %s: %s" % (type(e).__name__, e)]


def run_selftest(scratch=None, fixdir=None, required=None, jobs=None, only=None,
                 list_only=False):
    fixdir = Path(fixdir) if fixdir is not None else HERE / "fixtures" / "dream-write"
    required = REQUIRED_CASES if required is None else required
    cases, code = ds._selftest_names(fixdir, only, list_only, required)
    if code is not None:
        return code
    if scratch is not None:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    cfg_dir = Path(tempfile.mkdtemp(prefix="dw-gitcfg-", dir=scratch))
    empty = cfg_dir / "empty-gitconfig"
    # No background maintenance: git 2.53+ can start `git maintenance` after a commit, which writes
    # .git/objects/maintenance.lock into a fixture repo while the case snapshots or copies it.
    empty.write_bytes(b"[core]\n\tlongpaths = true\n[maintenance]\n\tauto = false\n[gc]\n\tauto = 0\n")
    # Set before the pool starts: spawned workers inherit this environment.
    saved = {k: os.environ.get(k) for k in ("GIT_CONFIG_GLOBAL", "GIT_CONFIG_NOSYSTEM")}
    os.environ["GIT_CONFIG_GLOBAL"] = str(empty)
    os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
    frozen = cfg_dir / "guard-scripts"
    names = set(ds.guard_files(HERE)) | {"dream-write.py", "dream-sweep.py",
                                          "dream-manifest.py"}
    for rel in names:
        if (HERE / rel).is_file():
            (frozen / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(str(HERE / rel), str(frozen / rel))
    cache = cfg_dir / "git-templates"
    cache.mkdir()
    failed = 0
    try:
        if not only:
            for req in required:
                if req not in cases:
                    print("FAIL %s: fixture missing" % req)
                    failed += 1
        items = [(n, str(fixdir / n), scratch, str(frozen), str(cache)) for n in cases]
        failed += ds._selftest_report(ds._selftest_map(_selftest_case, items,
                                                       4 if jobs is None else jobs))
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        ds._rm_tree(cfg_dir)
    print("selftest: %d case(s), %d failed" % (len(cases), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
