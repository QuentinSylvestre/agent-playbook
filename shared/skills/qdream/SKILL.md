---
name: qdream
description: Cross-project self-improvement engine. Discovers projects from session metadata and structural markers (memory/AGENTS.md), dispatches sub-agents per project, consolidates memory, proposes governance improvements.
argument-hint: "<optional: lightweight>"
---

# Dream — Cross-Project Self-Improvement

## Your role

Discover all projects from provider session metadata and structural markers (directories with `memory/MEMORY.md` or `AGENTS.md`), confirm the project list with the user, dispatch sub-agents to analyze each project's memory, sessions, and patterns, then synthesize cross-project learnings into memory entries and governance improvement proposals. In lightweight mode (called from `/qclose`), consolidate memory for the just-completed plan or research run only.

## Arguments

$ARGUMENTS

## Process

### Mode detection

If argument is `lightweight`: execute the **Lightweight Consolidation** section below. Do not run the 5-phase full process.

Otherwise: run the full 5-phase sweep, loading each sweep file per the **Phase index** below.

### Interpreter

The qdream scripts (`scripts/*.py` beside this file) run in the playbook's dedicated venv and nowhere else. Wherever these skill files write `<python>`, use `<config-repo>/.venv-agent-playbook/Scripts/python.exe` with `-I`. If that file is missing, or a script exits 2 printing `guard did not run: venv missing — run setup.ps1`, report that message as could-not-run and stop. Never try `python`, `py` or `python3` from PATH. A full sweep stops before Phase 2 — Rule 4 makes session access optional, not tooling. Lightweight mode without the venv reads the sections named in its Load step by their headings instead. Windows only; Linux and macOS are unsupported until `setup.sh` gains the venv step.

### Step-ID convention

Steps carry a stable `[ID]` tag; cite a step by `§ <ID>`, never by ordinal position. Ordinals are reflowable reading sugar. Cross-file references MAY prefix with the phase heading (`§ Phase X — Name § ID`) for grep discoverability; in-file references use the bare `§ ID`. Inside sub-agent briefs (blockquoted text shipped to dispatched agents), use backtick form (`` `ID` ``) instead of `§`. Prefix legend: **ORI** (Phase 1 — Orient), **GAT** (Phase 2 — Gather), **SYN** (Phase 3 — Synthesize), **DEC** (Phase 4b — Decisions), **APP** (Phase 5 — Apply).

### Mode matrix

Index of which closed-loop mechanisms run in which mode. This table is a summary — the per-step "full mode only" / "full sweep only" markers below remain the operative rule at each site.

| Mechanism | Full sweep | Lightweight |
|---|---|---|
| Scope | all discovered projects | just-completed plan or research run only |
| Autonomous writes (Dream autonomy exception) | yes — the paths and script carve-out in `shared/AGENTS.md § Dream autonomy exception` | no — `Save / Skip / Edit?` proposals, max 3 |
| Evidence quotes | structured `evidence_quote` field, verifier-checked | prose inside the proposal (no structured field) |
| Cross-validation gate (adversarial verifier) | yes | no |
| Rejected-lessons store + consult | yes | no |
| Outcome tagging | yes | no |
| Derived-utility pruning (Size check) | yes | no |
| Governance retirement pass | yes | no |
| Governance conflict routing † | yes | no |
| Episodic ledger + higher-order synthesis | yes | no |
| State file (`.dream-state.json`) | read/write + validate | untouched |
| Work folder (`~/.agent-playbook/dream-work`) | created by `dream-manifest.py manifest` at `§ ORI-DISCOVER`, deleted by its `clean` at `§ APP-CLEAN` (and on Abort); `count` and `dream-check.py extract` are read-only and need no grant | none — the sweep-due line comes from `dream-manifest.py count`, which writes nothing |

† Lightweight's `no` means only that the § SYN-RECONCILE `governance_conflicts` **routing** does not run — lightweight dispatches no sub-agents, so it produces no `governance_conflicts` array to route. A governance contradiction found at **write time** is still caught and escalated by the mode-independent cross-tier dedup check (`shared/AGENTS.md § Write-time quality gates`; `shared/skills/qdream/memory-rules.md § Dedup Check Procedure`, cross-tier check).

### Lightweight Consolidation

Scoped to the just-completed plan or research run in the current project. Maximum 3 proposals. Use the standard proposal format from `shared/skills/qdream/memory-rules.md` (Save / Skip / Edit? — user approval required). The Dream autonomy exception does NOT apply in lightweight mode.

**Load step — read sections, never whole files.** Before step 1, load only these sections. `<skill-dir>` is the directory holding this file (on a provider that merges overlays, its deployed copy); `<config-repo>` is per `shared/AGENTS.md § Config Repo Locations`.

```
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Memory File Format" --exclude "### [improvement_signal] sub-form" --exclude "### Governance-conflict adjudication"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "### Resolution contract"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Exclusion List"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Proposal Template"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Dedup Check Procedure" --exclude "### Native-memory harvest dedup"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Date References"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Type Taxonomy" --exclude "### Provenance re-open & auto-demotion"
<python> <skill-dir>/scripts/dream-check.py extract --file <config-repo>/shared/AGENTS.md --section "### Write-time quality gates"
```

The first command yields the entry-format templates, `### Declined records` and `### Cross-type optional metadata`. On Kiro the deployed `memory-rules.md` ends with the `memory-rules.OVERLAY.md` fragment, which no section above reaches, so also run:

```
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Merge Strategy — field-resolution grid (kiro)"
<python> <skill-dir>/scripts/dream-check.py extract --file <skill-dir>/memory-rules.md --section "## Workspace Store — discipline (kiro)"
```

Every `memory-rules.md` citation in the steps below refers to these extracted sections. Lightweight opens no `sweep-*.md` file.

Steps:
1. Read project memory file (`memory/MEMORY.md` in the workspace's store; `memory-rules.md § Resolution contract`, step 1).
2. Read user memory file (`memory/MEMORY.md` in config repo — see `shared/AGENTS.md § Config Repo Locations` for path).
3. If neither file exists, create `memory/MEMORY.md` (empty with type section headers) in the store `find-or-create` returns (`shared/skills/qdream/memory-rules.md § Resolution contract`, step 2). In a no-create folder (step 3), create it in the folder and ask the user whether to git-track it; on `failed` (step 4), create nothing.
4. Scan the just-completed plan (or, for a research run, its research log and `research.md`) for: resolved decisions, feedback corrections, patterns discovered. Also scan it for these signal tags, each a candidate for step 5: `correction`, `frustration`, `approval` (explicit), `verification_pushback` (e.g. "shouldn't we test this?"), `repeated_friction`, `agent_retry` (3+ attempts at one task), `agent_behavior`, `governance_friction` (a step or rule that did not fit), `decision`, `manual_workflow` (a repeated manual pattern) and `durable_fact`. `governance_friction`, `verification_pushback` and `manual_workflow` become proposals only as an existing entry type that passes the gates.
5. For each signal worth persisting (max 3):
   - Check if related entry already exists (update vs create).
   - Apply write-time quality gates from `shared/skills/qdream/memory-rules.md`.
   - Include the verbatim evidence quote that grounds the signal as prose within the proposal (in the `Why` or `Source`), not as a separate structured field — lightweight has no cross-validation verifier to consume a structured `evidence_quote`, so the quote is user-facing context and the standard proposal template is left unchanged.
   - Present using the standard proposal format. Wait for user decision.
6. Report: entries proposed, accepted, skipped. End it with the `count` lines: run `<python> <skill-dir>/scripts/dream-manifest.py count --state <config-repo>/memory/.dream-state.json --repo <config-repo>` (read-only) and print its `sweep due:` and `memory budget:` lines verbatim; on a non-zero exit or without an interpreter print `sweep due: unknown (<reason>)` and `memory budget: unknown (<reason>)`.

---

### Destructive-path invariants

Always loaded. Each line names the step that owns the full rule, so these hold even when a sweep file is not loaded.

- **Single-flight**: concurrent full sweeps over the same store are unsupported. A non-empty journal is a crash artifact (`§ ORI-RECOVER`), a paused sweep (`sweep-handoff.md § Orient order`) or a sweep still running elsewhere — when the user indicates another sweep may be in flight, stop rather than recover.
- **Leftover work folder**: shown to the user at Orient — resume the same snapshot, discard, or stop — never silently reused; only the scripts' guarded `clean` deletes it, and any Abort after the manifest ran runs it, except after a state-file or journal incident, when the folder and its backup are kept and the next Orient offers it as a leftover folder (`§ ORI-DISCOVER`, `§ APP-CLEAN`; `shared/AGENTS.md § Dream autonomy exception`).
- **Stamp only what was read**: `last_analyzed` and `last_run` take the manifest's `snapshot_at`, never the end-of-sweep clock; `dream-sweep.py coverage` stamps a project only when its agents returned and read every normal session, never deferred-only ones (`§ APP-STATE`).
- **Stale deletion needs all four conditions**: a count-verified `task4_status: checked`, a `confirmed` staleness verdict, no `human:` actor on the entry's `Verified`, and a real failing check quoted in `reason`. The gate covers salvage-rewrites as well as deletions. What happens otherwise is set by `§ SYN-STALE` conditions (a)-(d); an expiry-only item (d) is not surfaced as stale, except a user-memory `pattern` entry, whose expiry is its check.
- **Never autonomous, whatever the verdict**: a stale item whose heading is also in this sweep's `governance_conflicts` is only ever surfaced at `§ DEC-GATE` (`§ SYN-STALE`).
- **One write call**: phases and children write no memory, state or governance file; `§ APP-WRITE`'s `apply-all`, in the main session, does.
- **`subsumed` beats `stale`**: an entry returned in both channels is dispositioned as subsumed, never as stale (`§ SYN-STALE`, `§ SYN-RECONCILE`).
- **Pending governance conflict**: never autonomously delete or salvage-rewrite an entry carrying a non-terminal `Governance-conflict` record — surface it at `§ DEC-GATE` (`shared/skills/qdream/memory-rules.md § Governance-conflict adjudication`, `§ SYN-STALE`).
- **No autonomous governance edit**: a governance file changes only on the user's explicit Apply, executed at `§ APP-WRITE` (Rule 1).
- **Journal-first**: before any rename or removal recorded in the working map, `dream-write.py memedit` records it, flushes the whole map to `memory/.dream-journal.jsonl`, then mutates (`§ SYN-WRITE`). `§ ORI-RECOVER` consumes the journal; only `§ APP-STATE` clears it.

### Phase index

A full sweep loads each sweep file (beside this SKILL.md) when its phase starts, in the order below; a phase agent loads its own. Lightweight mode loads none of them.

| File | Step IDs | Load when |
|---|---|---|
| `sweep-handoff.md` | — | First: at Orient, and in every phase agent |
| `sweep-recovery.md` | ORI-RECOVER | Full sweep, only when `memory/.dream-journal.jsonl` is non-empty and no paused sweep is resumed; it runs at step 3 of `sweep-handoff.md § Orient order` |
| `sweep-orient.md` | ORI-STATE, ORI-DISCOVER, ORI-ROUTE, ORI-READMEM, ORI-DISPATCH | Phase 1 — Orient |
| `sweep-gather.md` | GAT-SESSIONS, GAT-ARCHETYPES, GAT-PLANS, GAT-CLASSIFY, GAT-DRIFT, GAT-SIGNALS, GAT-NATIVE | Phase 2 — Gather |
| `sweep-synthesize.md` | SYN-GATE, SYN-OUTCOME, SYN-WRITE, SYN-STALE, SYN-RECONCILE, SYN-PATTERN, SYN-ARCHPROMO, SYN-PROMOTE, SYN-REPEATS, SYN-SKILLS, SYN-INSIGHTS, SYN-HIGHERORDER | Phase 3 — Synthesize |
| `sweep-decide-apply.md` | DEC-PROPOSALS, DEC-RETIRE, DEC-GATE, APP-ADJUDICATE, APP-STATE, APP-COMMIT, APP-CLEAN, APP-METRICS | Synthesize (DEC-PROPOSALS, DEC-RETIRE); the orchestrator (Phase 4a, the gate, the Report); Apply (Phase 5) |

**Improvement signals** (user scope) live in the config repo's `memory/topics/improvement-signals.md`, not `memory/MEMORY.md`: read at `§ ORI-READMEM`, written at `§ SYN-PROMOTE`, removed only at `§ APP-ADJUDICATE`.

## Rules

1. Never modify governance files without user approval — governance proposals require explicit Apply confirmation
2. In full mode, autonomous writes to `memory/MEMORY.md` files — wherever `shared/skills/qdream/memory-rules.md § Resolution contract` places them, the store-resolved location included — and the config repo's `memory/topics/*.md`, plus `memory/HIGHER_ORDER.md`, `memory/.dream-state.json` and `memory/.dream-journal.jsonl` are permitted, written only by the qdream scripts these skill files name, which also write the work folder (only the scripts' `clean` deletes it) — all per `shared/AGENTS.md § Dream autonomy exception`, the single source of truth for what is writable and what stays denied
3. In lightweight mode, use the standard proposal format (Save / Skip / Edit?) — no autonomous writes
4. Session access is optional; never fail if sessions are unavailable or a provider steering file is missing
5. Reference `shared/skills/qdream/memory-rules.md` for format spec and quality gates — do not duplicate those rules here
6. When deleting entries, report what was deleted and why in the Report
7. Do not load entire session files into orchestrator or phase-agent context; sub-agents manage their own context budget
8. Verify proposals against the authority hierarchy before writing (per `shared/AGENTS.md § Memory Management`); if a proposal contradicts **governance**, do not write it — escalate to the user in Phase 4b with an action set (`record with an explicit override note` / `propose a governance update` / `drop`), never a destination-less ban. A contradiction with a higher *memory* tier (not governance) may instead be recorded with an explicit override note per `shared/skills/qdream/memory-rules.md § Dedup Check Procedure`
9. Every sub-agent or phase-agent failure follows `sweep-handoff.md § Failure gate`
