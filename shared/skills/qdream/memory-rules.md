# Memory Rules Reference

This file is the single source of truth for memory entry format, type taxonomy, exclusion list, proposal procedures, and the workspace store's layout and resolution contract. Cited by `shared/AGENTS.md § Memory Management`.

---

## Workspace Store

Every workspace keeps its memory and its project files in the **store repo**, a private git repository at `~/.agent-playbook/stores` (`AGENT_PLAYBOOK_STORES` overrides the location), never inside the workspace. One store directory serves one workspace identity. The store resolver, `shared/skills/qdream/scripts/store-resolver.py`, is the single implementation of identity, naming, lookup and creation: no skill, script or agent re-implements any of them.

`/qexplore`, `/qplan`, `/qdev`, `/qclose`, `/qhandoff`, `/qtest`, `/qexplain`, `/qdream`, `/qmemory-eval` and `/qwire-governance` cite this section and resolve their paths through it. `/qtest` resolves the **project-files** class, then appends `tests/`; it has no artifact class of its own. `/qwire-governance` resolves **no artifact class**: it asks the resolver for the store *directory* and writes a Kiro steering file naming it. `/qconfig-sync` and the delegate skills cite only `§ Store scratch folder`. This list is hand-maintained prose, not machine-checked: `verify-citations` counts citations to this section but cannot tell whether the names above match them, so **update this sentence in the same commit that makes a skill a citer**.

### Store layout

```
~/.agent-playbook/stores/        # the store repo
  <name>-<hex>/
    STORE              # the store's identity (§ The STORE file)
    memory/MEMORY.md   # playbook typed-section format (§ Memory File Format)
    plans/             # active project files
    plans/done/        # archived project files
    plans/tests/       # test plans
    explanations/      # optional: written by /qexplain
    artifacts/         # optional: files the user asked to keep
    visualizations/    # reserved, git-ignored: /qvisualize output
    scratch/           # reserved, git-ignored: temporary playbook working files
```

The directory name is for people: `<name>` is the folder's basename and `<hex>` keeps it unique (at least 6 hex digits; the resolver extends it by 2 on a collision). **Nothing finds a store by its name**: the resolver reads `STORE` files. Never derive, hash or invent a store directory name, and never rename one.

**Every store is a shared store.** The store repo is git-tracked as a whole, and every session and harness on every machine that syncs it writes there, so whether a store is shared or solely-owned is a property of the store repo, not of one directory.

**`visualizations/` is reserved.** The store repo ignores `*/visualizations/`. It holds generated content, not memory, so the prune criteria of `§ Derived Utility & Pruning` do not apply to it, and its retention belongs to the qvisualize project. The same holds for any other ignored subfolder inside a store.

**Store content is stored LF-normalised.** The store repo's `.gitattributes` carries `* text=auto eol=lf`, so a CRLF source committed into a store cannot be stored byte-identically. A check that compares a store file with a copy elsewhere compares **content under CRLF-to-LF normalisation**, never raw bytes.

**Store paths written in prose are not machine-verified.** `verify-links` resolves paths inside the config repo only; a path into the store repo is skipped. Write store paths carefully.

The consolidation sweep discovers a store-backed workspace under its real path, never a store directory as a project (`sweep-orient.md § ORI-DISCOVER`). `shared/skills/qconfig-sync/scripts/verify-stores.py` checks the layout above, the `STORE` files, in-workspace `memory/` or `plans/` left in a known workspace, and store-repo paths uncommitted or unpushed for over a day, on every `/qconfig-sync` run.

### Store scratch folder

Temporary playbook working files: review outputs, probe scripts, test runs. Never a project's runtime state.

- **Files needed only in this session** go in the harness's session scratchpad, if it has one.
- **Files that must outlive the session**, or any file on a harness with no scratchpad, go in the folder that `store-resolver.py scratch <folder> <name>` creates and prints. `<name>` is the plan slug, or `<YYMMDD>-<topic>` for plan-less work. A folder with no store uses `~/.agent-playbook/scratch/<name>`.
- **Scratch is disposable.** Record results as text in the project file. A file worth keeping goes to `artifacts/` only when the user says so.
- **Cleanup.** `/qclose` deletes the plan's folder. `/qconfig-sync` deletes plan-less folders whose newest file is over 30 days old, without asking, and names each one. A folder matching an open plan in the store's `plans/` is reported, never deleted by age. A plan kept outside the store has no such protection, so its work names its folder `<YYMMDD>-<topic>` and accepts the 30 days.
- `/qdream` has no scratch folder: a sweep writes no scratch files (`shared/skills/qdream/sweep-handoff.md`).

### The STORE file

`STORE` holds the store's identity, the value the resolver compares when it looks a folder up:

```
remote <host>/<owner>/<name>      # the folder's normalized git remote
path <subpath>                    # optional: the folder's path within that repo
```

or, for a folder with no usable remote, one line `local <path>` holding the folder's path in `§ Path normalization` form. One or two lines; nothing else. The resolver writes a `STORE` atomically when it creates a store, and refuses to write one that would not read back as the same identity. A store's identity changes only by the steps below:

- **A non-git workspace moved.** `/qmigrate-workspace` rewrites its `local` line.
- **A git workspace's remote changed** (a rename, a new host). Edit the `remote` line of its store by hand to the new normalized remote, keep any `path` line, commit it in the store repo, and confirm with `store-resolver.py find <folder>`, which then prints that store directory (`store-resolver.py identity <folder>` prints what the line must say). Moving a git checkout without a remote change needs nothing.

**Using a parent's store.** A folder resolves to the store at or above it (inside git, up to the toplevel; outside git, through non-git parents, stopping before the home folder). The steps for using a parent's store when a folder already has its own, and the parent is at or above it within that walk (a parent outside the walk can never serve the folder): move the folder store's `memory/` entries and `plans/` files into the parent's store, delete the folder's store directory in the store repo and commit both in one store-repo commit, then re-run `/qwire-governance` in the folder, which regenerates its `.kiro/steering/__store__.md` and `__store_memory__.md` for the parent's store. To move the folder itself, use `/qmigrate-workspace`.

### Path normalization

Four steps. Step 1 names a runnable command per platform, because an algorithm named only in prose is an algorithm two agents implement differently. The resolver implements them for `local` identities; `dream-manifest.py` implements them for project paths.

1. **Resolve to an absolute real path.**
   - Windows: `(Get-Item -LiteralPath $p).FullName`
   - POSIX: `realpath -s`

   **Reparse points and symlinks are NOT followed.** This step expands 8.3 short names and casing, nothing else. The two commands disagree by default: `(Get-Item).FullName` does not follow a junction while bare `realpath` does, so one workspace reached from two harnesses would otherwise yield two identities. The `-s` flag makes the POSIX side match. Following links is also the wrong default here — `§ Support-set referential integrity` already treats a second path to one project as a second project.

   > **Rejected:** `Resolve-Path` (returns an 8.3 short name unchanged, unlike `(Get-Item).FullName`) and `GetFinalPathNameByHandle` (no CLI; returns a `\\?\`-prefixed string). **Use instead:** the two commands above.

2. **Strip a leading `\\?\` prefix** if one is present. Map a `\\?\UNC\` prefix to `//`.
3. **Replace `\` with `/`**, then strip any trailing separator.
4. **Case-fold.**

Two cases the rule must survive:

- **A reparse point that resolves to nothing is left as-is, not treated as an error.** `C:\Users\alice\OneDrive - ExampleCo` carries the `ReparsePoint` attribute, but its `LinkType` is empty and `ResolveLinkTarget($true)` returns **null** — it is a cloud-files placeholder, not a junction. An agent that reads step 1 as "call `ResolveLinkTarget`" gets null on every OneDrive path.
- **Non-existent paths are normalized lexically.** Orphan checks normalize paths that may be gone. When the path does not exist, **skip step 1** and apply steps 2-4 lexically. What selects that branch is **step 1's own command failing**: bare `realpath` fails on a missing path, and `Get-Item -LiteralPath` throws `ItemNotFoundException`. That failure is the only existence test this section defines. The lexical fallback then runs `realpath -m` on POSIX — which succeeds on a missing path and so can never report absence by itself.

**Boundary against the existing project-path key.** Two forms coexist, so keep them apart. The normalized form above is used for **comparison and `local` identities only**. It is **never** written into `memory/.dream-state.json`, and never into a `project memory (<project-path-key>) § <heading>` pointer. Both keep the verbatim Windows path exactly as `memory/.dream-state.json` records it. Accepted consequence: one store may back two state-file keys when a workspace is reached by two paths.

### Resolution contract

Resolution answers one question: for this artifact class, in this folder, which directory do I read and write? The resolver answers it. Run it and use the path it prints:

```
<python> shared/skills/qdream/scripts/store-resolver.py find <folder> [--kind <kind>]
<python> shared/skills/qdream/scripts/store-resolver.py find-or-create <folder> [--kind <kind>]
```

`<python>` is the playbook venv interpreter (`shared/skills/qdream/SKILL.md § Interpreter`). `<folder>` is the session's working folder; `<kind>` is `memory` (the default), `plans`, `explanations` or `artifacts`. Exit 0 prints the store directory (whatever the kind, except the config-repo carve-out in step 0): append `<kind>/` yourself. Exit 3 means none (the reason on stderr), exit 2 failed. **Never derive, hash or invent a store directory name**, and never build one from the folder's name.

**0. Config-repo carve-out.** Inside the config repo, `<config-repo>/memory/` is the **user** tier and is never project memory; the config repo's project memory and project files (plans) are in its own store, which `find` returns like any other.

**1. Read with `find`.** Found: read `<store>/<kind>/`. A store holds content for a kind when that folder holds a `.md` file at any depth, `.handoff-*.md` scratch excluded; the readers that use `resolve_artifact` take the nearest store that holds content, while `find` prints the nearest store even when it is empty. None: the folder has no store; read the folder's own copy only in a no-create folder (step 3), else there is nothing to read and loading fails open (`shared/AGENTS.md § Read-time behavior`). An in-workspace `memory/` or `plans/` anywhere else is a leftover: it is not read, and `verify-stores` warns about it. Failed: say so, and read nothing. In the system temp directory and a Downloads folder only a `local` store (keyed by the folder's own path) matches: a `.git` there, or a `gitdir:` file, could claim another workspace's remote.

**2. The first write runs `find-or-create`.** It returns the store that already serves the folder, or creates one at the session folder itself. **No prompt** — the store is the default for every workspace. The `/qdream` sweep writes there too, even when the folder reads its memory from an ancestor's store; that first write, a session's or the sweep's, moves the folder's reads to its own store, so the ancestor's memory is no longer shown there. Repeat any stderr notice to the user: on creation the resolver names a store that looks like this folder's under an old path or remote, which means the store needs a re-key (`§ The STORE file`), not a second store. Only when the user names another folder, pass `--at <folder>`: it must be the session folder or an ancestor within the same git toplevel (outside git, the same non-git walk). Any other `at` answers none, because a store there could never be found again; create the store at the folder or such an ancestor instead (the steps for using a parent's store, `§ The STORE file`).

**3. None from `find-or-create` marks a no-create folder, which keeps the old behaviour.** The resolver creates no store in the system temp directory, `~/.agent-playbook`, the home folder itself, a drive root, `~/Downloads`, `.claude/worktrees` or a network (UNC) path; its reason names which. There, memory and project files stay in the folder: `memory/MEMORY.md` and `plans/` at the folder, or at the nearest level up to its git toplevel that holds them. The playbook's scripts never read a UNC folder at all, and the `/qdream` full-sweep scripts never write an in-workspace memory file anywhere (an in-session agent, `/qdream` lightweight mode included, follows this step).

**4. Failed writes nothing.** A missing or unreadable store repo, or a repository the resolver cannot read, is `failed` for reads and writes alike, also in a no-create folder: write nothing and report the reason. A missing store repo is cloned as `providers/claude/README.md` describes.

**5. Commit.** A creation and every write are uncommitted changes in the store repo. Commit them by pathspec in the store repo at the skill's next commit point, or leave them for `/qconfig-sync`, the store repo's sync point, which commits and pushes them. The SessionStart hook names store-repo paths left uncommitted or unpushed for over a day.

> **Rejected:** locating or naming a store by hashing or slugging the folder path — two agents compute two names, and a name never identifies a store. **Use instead:** `store-resolver.py find` or `find-or-create`, and the path it prints.

---

## Type Taxonomy

| Type | Description | Staleness risk | Verification rule | Examples |
|---|---|---|---|---|
| feedback | Corrections **and confirmed approaches** — what went wrong, and what the user validated; environment quirks | High (context drifts) | Grep-verify the artifact/pattern still exists. For a validated *approach* (no artifact to grep), verify no later correction reverses it | "pytest needs --no-header on CI", "user confirmed: show the diff before applying" |
| decision | Architectural choices, design trade-offs agreed upon | Medium (may be superseded) | Check recent plans for reversal | "chose SQLite over Postgres for local-first", "monorepo over polyrepo" |
| pattern | Recurring approaches, conventions, workflows | Medium (codebase evolves) | Grep-verify the pattern is still used | "all API handlers use Result<T> wrapper", "tests use builder pattern for fixtures" |

### Record from failure AND success

`feedback` is **bidirectional by design**. A store that saves only corrections will avoid past mistakes but drift away from approaches the user has already validated, and grow steadily more cautious — the agent re-litigates choices the user already blessed. Save on either signal:

- **Correction** — the user rejects or redirects an approach ("no, not that", "stop doing X").
- **Confirmation** — the user validates a *non-obvious* approach ("yes, exactly", "perfect, keep doing that").

Corrections are easy to notice; confirmations are quieter — watch for them. Note the asymmetry in evidence strength: explicit praise is evidence; **acceptance without pushback is weaker evidence, not equal evidence** — and only counts at all when the accepted choice was genuinely unusual (silence on a routine choice means nothing). Grade the two apart rather than collapsing them (`sweep-gather.md § Phase 2 — Gather`, positive signals).

### Borderline tie-breakers

- **feedback vs pattern**: `feedback` records what the *user* corrected or validated; `pattern` records what the *codebase or workflow* does regardless of who said so.
- **decision vs feedback**: `decision` records a choice among alternatives with its rationale; `feedback` records a directive or quirk with no alternatives weighed.
- **Environment facts** ("this repo's tests need X") are `feedback` (environment quirk) at project scope; **workflow state** is never memory — routing: `§ Exclusion List`.

### Provenance re-open & auto-demotion

A `/qdream` sweep — and any read-time verification (per `shared/AGENTS.md § Read-time behavior`) — may **re-open the entry's `Source` anchor** (`§ Memory File Format`) and read the cited span before trusting the entry. At read time a contradicting anchor only *discounts* the entry for the current session; only a sweep *demotes* it (first bullet below). Disposition:

- **Reachable AND contradicts the claim** → **demote** the entry. The evidence the entry was reasoned from no longer supports it, so the entry has lost its ground. This is memory's principled removal path. In a sweep, demote means Task 4 returns the entry in `stale_entries` with the contradicting span quoted in `reason`. Removal is then decided by the `sweep-synthesize.md § SYN-STALE` gate under removal class `demoted`; an item that gate does not clear is surfaced in Phase 4b. **At read time it discounts, never demotes**: only `/qdream` writes memory autonomously, so an in-session agent edits no file autonomously. It discounts the entry for the current session only, says the contradiction aloud and proposes a fix per `§ Plan-less governance capture` (Wrong memory). The persistent demotion happens only in a sweep.
- **Reachable and still supports (or is neutral to) the claim** → the entry stands; apply its type-specific verification rule (above) as usual.
- **Unreachable** (the session file rotated, or the plan-slug/section is absent) → **do NOT demote**. An anchor that cannot be opened is *not* evidence the claim is false — a rotated or missing source proves nothing. The re-open is **indeterminate**; fall back to the entry's type-specific verification rule (grep for patterns, plan-reversal for decisions, artifact check for feedback) and judge the entry on that alone.

Demote **only** on the reachable-and-contradicting case; never on unreachability. This mirrors the Cross-validation gate's unreachable-source carve-out (`sweep-synthesize.md § Phase 3 — Synthesize`, Fabrication spot-check): unreachable provenance is indeterminate, never a refutation, so valid entries are not silently lost when their source rotates.

**Cheap deterministic pre-filter (optional, before the semantic re-open)**: compare the anchor target's last-modified signal (file mtime, or the last commit touching the cited plan/file) against the entry's `Verified` date. A target unchanged since `Verified` cannot have newly contradicted the entry — its semantic re-open may be skipped this sweep; a target modified since `Verified` is a re-open candidate. Change is only a trigger for the check, never itself evidence of contradiction.

**The skip is licensed only by an `anchor-reopen` method token.** The pre-filter's logic holds only if the entry's `Verified` date actually marks an anchor re-open — a date set by a grep-only verification, a plan scan, or a merge says nothing about whether the anchor's *content* was ever read, so treating it as a baseline skips a check that never happened. So: skip only when the entry's `Verified` carries method **`anchor-reopen`** (`§ Memory File Format`). Every other method — and an **absent** annotation, which is the common legacy case — forbids the skip and routes to the full semantic re-open. This is deliberately the fail-safe direction: the cost of a needless re-open is one read, the cost of a wrongly-skipped one is a stale entry trusted indefinitely. (Before the annotation existed this caveat was stated but unenforceable — no on-disk signal distinguished the two cases.)

**A fired `Stale-after` / `Stale-when` also revokes the skip** (`§ Cross-type optional metadata`): the entry has reached its own declared expiry, which is exactly when the cheap path is least trustworthy. Firing forces the semantic re-open and the type-specific verification; it is never itself a demotion trigger.

**Human-attestation carve-out.** If the entry's current `Verified` carries a **`human:`** actor (`§ Memory File Format`), do **not** demote it autonomously — even on a reachable-and-contradicting anchor. Surface it in Phase 4b (`Delete / Keep / Defer`) showing the contradicting provenance alongside the human attestation, and let the user adjudicate. Rationale: a person confirmed this entry, and an agent's own re-reading is not independent evidence against a human check (`memory/HIGHER_ORDER.md § Pattern` — *"self-inspection is not verification"*). The sweep may still *report* the contradiction; it may not act on it alone. At read time the same holds: an in-session agent never discounts a `human:`-attested entry autonomously; it surfaces the contradicting provenance to the user instead. **Scope — two paths, not all four.** This blocks the **provenance-demotion** path (here) and the **stale-entry deletion** path (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-STALE`, condition (c)). It does **not** exempt the entry from verification, from being reported, or from a user's own `Delete` — and, deliberately, it does **not** exclude the entry from the **Size-check prune** of a project or topic file, which remains an autonomous deletion path (the user tier is never pruned autonomously, `§ Session-start memory context budget`). There, human attestation is only a **tiebreak preference** at criterion (5) (`§ Derived Utility & Pruning`), not an exclusion: an entry ranking lowest on criteria (1)-(4) is still prunable however it was verified. Contrast the non-terminal `Governance-conflict` carve-out below, which *is* a full prune-set exclusion — that record encodes an unresolved **user decision** the prune would destroy, whereas a human verification is evidence about the entry's truth, which the size budget does not owe an exemption. **Do not state this protection unqualified**; say *demotion and stale-deletion*.


**Non-terminal `Governance-conflict` carve-out.** If the entry carries **any** non-terminal `Governance-conflict` record (`rule-update-pending`/`deferred` — an unresolved user adjudication, `§ Governance-conflict adjudication`), do **not** demote it even on a reachable-and-contradicting anchor. Surface it in Phase 4b showing both the contradicting provenance and the pending adjudication, so the user resolves both at once — an autonomous demotion here would permanently suppress the conflict the user has not yet finished adjudicating.

**Scope — base entries only.** This demotion licence covers `memory/MEMORY.md` entries. A **higher-order node** (`§ Higher-Order Tier`) is **never** removed by provenance demotion and **never** removed at read time: its sole removal path is the sweep's user-gated `Keep node / Remove node / Defer` prompt.

---

## Memory File Format

Memory files live at `memory/MEMORY.md` in the config repo root (user memory; that `memory` is a link setup makes to the store repo's reserved `user/memory/`, so git tracks user memory only in the store repo: `shared/AGENTS.md § Config Repo Locations`), or at `<store>/memory/MEMORY.md` in the workspace's store in the store repo (project memory, `§ Workspace Store`). The format below is the same wherever the file lives. Entries are grouped by type as top-level sections, with individual entries as subsections:

**Route to a topic file before writing to `memory/MEMORY.md`.** The config repo carries an on-demand tier — `memory/topics/<topic>.md`, indexed by the `## Topics` table at the head of user memory, not loaded at session start (`shared/AGENTS.md § Memory locations` → Topic memory). Before writing a new user-memory entry, read that index: **if an existing topic's trigger covers the entry, it belongs in that file, not here.** Same format, same type headings, same gates — only the loading differs, and authority is identical, so this is a placement decision rather than a demotion.

The check is cheap and it is not optional.

Two consequences for the sweep specifically:

- **Topic files are outside the user tier** (`§ Session-start memory context budget`), so *routing* an eligible entry is a cheaper way under the user tier's word pin than *pruning* a valuable one; they keep the ~30-entry Size check. Prefer routing; user-gated prune proposals rank on `§ Derived Utility & Pruning`.
- **Proposing a new topic file is in scope when a cluster earns one** — roughly three or more entries sharing a condition that most sessions do not meet. Propose it like any other change (user-gated); do not create one unilaterally, and give it a row in the `## Topics` index plus a citation from the always-loaded document an agent reads while doing that work, or it will not be found.

**Insert a new entry under its type's EXISTING heading — never append at end-of-file.** Re-read the file's `## ` headings before writing. A second `## Feedback` / `## Decision` / `## Pattern` heading breaks the type partition that every read-time type-specific verification rule depends on, and the breakage is silent: entries under the orphaned heading are verified under the wrong rule.

**Loading fails open; writing fails closed.** The fail-open licence (`shared/AGENTS.md § Read-time behavior`) covers reading only. Never rewrite a memory file from a lossy or partial read (decode replacements, skipped entries, truncation); say what could not be read instead. Editing one entry you read in full is not a rewrite.

```markdown
## Feedback

### <one-line heading>

**Why**: <why this matters -- one sentence>
**How to apply**: <concrete action -- one sentence>
**Source**: <re-openable anchor: plan-slug + section, or session-id + line-span> | **Verified**: <YYYY-MM-DD>[ (<actor>[, <method>])]

## Decision

### <one-line heading>

**Why**: <why this matters -- one sentence>
**How to apply**: <concrete action -- one sentence>
**Source**: <re-openable anchor: plan-slug + section, or session-id + line-span> | **Verified**: <YYYY-MM-DD>[ (<actor>[, <method>])]

## Pattern

### <one-line heading>

**Why**: <why this matters -- one sentence>
**How to apply**: <concrete action -- one sentence>
**Source**: <re-openable anchor: plan-slug + section, or session-id + line-span> | **Verified**: <YYYY-MM-DD>[ (<actor>[, <method>])]
```

**A new heading names the situation the entry applies to, within 200 characters**, because a reader matches on the heading before opening the entry. Existing headings are never retrofitted, except one over 200 characters, which `verify-memory` fails.

**`Source` is a re-openable anchor.** Record `Source` as an anchor a later sweep or read-time check can re-open to re-verify the entry against its origin: `session-id + line-span`, or `plan-slug + section`. **Prefer the durable `plan-slug + section` over an ephemeral `session-id` where both exist** — session files rotate and become unreachable, whereas an archived plan slug + section endures. The `/qdream` sweep re-opens this anchor during verification — see `§ Type Taxonomy` for the auto-demotion rule that consumes it. **Legacy entries with a free-text `Source`** (no re-openable anchor) remain valid — a non-re-openable `Source` routes to the *unreachable / indeterminate* branch of the auto-demotion rule and is therefore **never a demotion trigger**; upgrade it to an anchor opportunistically on the next merge or verification if the origin can be recovered.

**Anchors cite stable identifiers verbatim, and the original is never rewritten.** Cite the full plan-slug, the exact heading string, or the session-id — never a paraphrase ("the deployment plan from July"): a paraphrased anchor cannot be re-opened and degrades to indeterminate. And provenance is **first-writer-wins**: re-verification appends rather than replaces — a verifier adds a second anchor after ` + ` or re-dates `Verified`, and the legacy free-text upgrade above appends the recovered anchor while keeping the original prose. (A dedup merge's field selection per `§ Merge Strategy` is entry consolidation, not a verifier rewriting provenance.) The entry's author and a later verifying sweep are distinct roles; a verifying sweep never becomes the author.

**`Verified` may name who verified, and how.** The date may carry an optional parenthesized annotation — `**Verified**: 2026-07-28 (human:alice, anchor-reopen)` — recording the **actor** that performed the most recent verification and, optionally, the **method** it used. Both token sets are closed:

| Actor | Meaning |
|---|---|
| `human:<id>` | A person confirmed it. The `human:` prefix is what the consumers below key on |
| `sweep` | A `/qdream` sweep (orchestrator or one of its sub-agents) verified it |
| `session` | An in-session agent verified it outside a sweep |

| Method (optional) | Meaning |
|---|---|
| `anchor-reopen` | The `Source` anchor was re-opened and its cited span read |
| `grep` | The pattern or artifact was grep-verified in the codebase |
| `plan-scan` | Recent plans were checked for a reversal (the `decision` verification rule) |
| `artifact-check` | The referenced artifact was confirmed to still exist |
| `merge` | The date rode along on a dedup merge — **not** an independent verification |

**Named fallback: when the actor cannot be determined, omit the whole annotation** — never guess one. A bare `**Verified**: <YYYY-MM-DD>` is valid indefinitely and is the correct form for every entry written before this field existed; an absent annotation is **neutral**, never adverse, on every ranking that reads it (`§ Derived Utility & Pruning`, graceful degradation).

**The annotation must never contain a `|`.** The line's `|` is a **field separator**, and the grammar keeps one per line. Where `Source` ends is the Source rule in the module docstring of `shared/skills/qdream/scripts/memory-entries.py`, the one memory-entry parser. A `|` inside the parentheses makes the line's field count ambiguous for any consumer that splits differently or reads from the right. Keep it parenthesized, comma-separated, pipe-free.

**Consumers** (per `shared/AGENTS.md § Structure Requires a Consumer`): the pre-filter skip licence and the human-actor demotion carve-out in `§ Type Taxonomy` (*Provenance re-open & auto-demotion*); the age-tiebreak in `§ Derived Utility & Pruning`; and the `/qdream` disposition gate at `sweep-synthesize.md § Phase 3 — Synthesize § SYN-STALE`.

### Declined records (the `## Declined` section)

`memory/MEMORY.md` may carry an additional top-level section, **`## Declined`**, holding **declination records** — the user's `Skip` of an **agent-initiated** memory proposal **or** the user's `drop` at the authority-hierarchy escalation (`§ Dedup Check Procedure`, cross-tier check) — recorded where the next session already looks (the file loads at session start, `shared/AGENTS.md § Memory locations` / `§ Read-time behavior`). It exists so a Skipped or dropped proposal is not re-proposed next session — the problem `.dream-state.json` `rejected_lessons` could not solve for memory proposals, because that file is never loaded at session start. Rows come from two sources: (1) a memory-proposal `Skip` (`§ Proposal Template`), and (2) the authority-hierarchy escalation's `drop` action (the user drops a governance-contradicting proposal — `§ Dedup Check Procedure`, cross-tier check).

**`## Declined` is a section, NOT a fourth taxonomy type** — the three types above (feedback, decision, pattern) remain the complete taxonomy — and its rows are **NOT entries**: a row carries no `Type`/`Usage`/`Outcome`/`Source`, counts toward `§ Session-start memory context budget` in words only, not entries, and is **not** ranked by the `§ Derived Utility & Pruning` prune order. Each row stores exactly **one** date:

```markdown
## Declined

- "<proposed heading>" — declined <YYYY-MM-DD> (<user's reason, if given>)
```

**Expiry — one owner, one constant.** A declination suppresses re-proposal of its subject for **60 days** from the stored `declined` date. This 60-day window is **owned here and nowhere else**: an expiry check (the dedup consult, below) computes it from this single constant. Do **not** store it per row, and do **not** declare an independent constant in any prompt string — a prompt's consequence text *references* this window, it does not re-own it.

**Write / prune actors — sessions append, no script prunes** (the Dream autonomy exception, `shared/AGENTS.md § Dream autonomy exception`, is **not** widened):

- **Sessions append only.** An in-session agent may **append** a declination row when the user Skips a memory proposal it actually showed (`§ Dedup Check Procedure`, `§ Proposal Template`) or when the user chooses `drop` at the authority-hierarchy escalation (`§ Dedup Check Procedure`, cross-tier check). The `drop` reason uses the parenthetical `(dropped: contradicts <file § section>)`. It may **never delete** a row — deleting would widen the autonomy exception, against this subsystem's own invariant, and honouring a user restatement needs no deletion (below).
- **Nothing prunes.** An **expired** row (older than the 60-day window), or one whose subject **now exists as a live entry** (the user re-authorized it), stops mattering and stays: `dream-write.py memedit` has no row-prune op.
- **Concurrency — constrain the sweep, not the session.** The sweep is the clobberer: it reads `memory/MEMORY.md` at Orient (Phase 1) and rewrites it at Phase 3/5, so a row a session appends mid-sweep would be silently overwritten. Before its write, the sweep must **re-read `## Declined` from disk and union** it with what it holds, rather than persisting the stale copy it read at Orient.
- **Never drop the heading.** `## Declined` is a **guarded** heading (`shared/skills/qconfig-sync/scripts/citation-checks.tsv`, read by `verify-citations.py`) inside a file `/qdream` autonomously rewrites, and it is **empty most of the time** — exactly what a formatting writer silently drops. **Never remove the `## Declined` heading, even when it has zero rows**: dropping it reports MISSING and makes `/qconfig-sync` exit 1 — an autonomous write breaking the user's sync. (Mirrors the guarantee the higher-order writer gives `memory/HIGHER_ORDER.md`'s guarded preamble.)

**An absent `## Declined` section means "no declinations", not an error** — project memory files created before this section predate it (`sweep-synthesize.md` bootstraps it into new files).

### `[improvement_signal]` sub-form

Governance-improvement signals that fall **below** the promotion frequency gate are persisted (per `sweep-synthesize.md` Phase 3) as a named cross-type entry sub-form, so subsequent sweeps can accumulate their frequency across runs. A session with no project file can also write one, after the user's `Save` (`§ Plan-less governance capture`). This is **not a fourth taxonomy type** — the three types above (feedback, decision, pattern) remain the complete taxonomy. `[improvement_signal]` is a specialization filed under the `## Pattern` section of the improvement-signals topic file, `memory/topics/improvement-signals.md` in the config repo (user scope), or of the project's `memory/MEMORY.md` (project scope). The user-scope home is a topic file so that signals do not load at session start; the sweep reads them there, and `user memory § <heading>` pointers still resolve to them (`§ Support-set referential integrity`). A signal is never a Size-check prune candidate (`§ Derived Utility & Pruning`); a stale singleton expires instead (below). It is distinguished by an `[improvement_signal]` heading prefix and a fixed field set:

```markdown
### [improvement_signal] <one-line description of the governance gap>

**Target**: `<governance file the signal proposes changing>`
**Why**: <what friction was observed and why it warrants a governance change — one to two sentences>
**Frequency**: <N> (below threshold) | **Sessions**: <comma-separated session tokens, project last: a session id, in-session <YYYY-MM-DD> [<session-id>], or sweep <YYYY-MM-DD> [<session-id>]; the project is optional, except required with an in-session or sweep token> | **Last observed**: <YYYY-MM-DD>
**Evidence-quote**: "<verbatim span from the session grounding the signal>"
**Source**: <optional: re-openable anchor for the Evidence-quote — session-id + line-span, or plan-slug + section>
```

**`Source` is admitted, optional, and carries no `Verified`.** A signal may carry a `**Source**` line naming where its `Evidence-quote` was taken from, in the anchor form of `§ Memory File Format`. It is a pointer for re-checking the quote, not a verification record, so the line holds `Source` alone: a signal never carries a `**Verified**` field. A signal without `Source` is valid.

**`Sessions` has an in-session form.** `Sessions` is a comma-separated list of session tokens with the project last. A signal captured in-session (`§ Plan-less governance capture`) lists its session as `in-session <YYYY-MM-DD> <session-id>`, or as `in-session <YYYY-MM-DD>` when the harness exposes no session id; a row holding an in-session token must name its project, for example `in-session 2026-10-08 8d8a328b, agent-playbook`. Each token is one session. **Session ids match by prefix**: a shorter id matches a longer one that begins with it (`8d8a328b` matches `8d8a328b-6286-…`). **A session counts at most once toward `Frequency`**: when a sweep re-observes the signal in the transcript of a session whose id `Sessions` already lists, it adds nothing. An id-less marker is matched first through the sub-agent's `saved_in_session` flag, and the sweep then writes the discovered id into the marker; the date, project and equivalent `Evidence-quote` fallback is the last resort (`sweep-synthesize.md § SYN-PROMOTE`).

**`Sessions` has a sweep form.** A signal the sweep orchestrator observed during its own run (`sweep-synthesize.md § SYN-PROMOTE`, *Orchestrator observation counts*) lists that run as `sweep <YYYY-MM-DD> <session-id>`, the sweep's own session id, or as `sweep <YYYY-MM-DD>` when the harness exposes no session id. Like an in-session token it requires the project, for example `sweep 2026-10-09 3f1c9a07, agent-playbook`. It counts as one session toward `Frequency`, and its id matches by prefix like any other, so the same run is never counted twice. Never write an empty token (`**Sessions**: , agent-playbook`).

When a signal later crosses the frequency gate it is promoted out of memory into a Dream Governance Proposal — and its `[improvement_signal]` entry is removed **only when that promotion lands**: in **§ APP-ADJUDICATE**, after the user chose `Apply` on the proposal. Crossing the gate *promotes*; it does not delete. If the user **Skips** the proposal, the entry **survives** — removing it would delete the accumulated evidence and reset the counter to zero, and nothing removes an `[improvement_signal]` entry outside an `Apply`, except the stale-singleton expiry below. But it does **not** keep accumulating while suppressed: a Skip of a gate-verified proposal writes a `skipped` record to `rejected_lessons` (`§ State File Format`). So does a user's in-session Skip of a plan-less signal proposal, though nothing is written during that session: the next sweep that reads the session appends the record (`§ Plan-less governance capture`). In both cases the Rejected-lessons consult of later sweeps (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-WRITE`) drops a matching signal before it can be **re-promoted or re-accumulated**. So the entry's `Frequency` counter is **frozen for the suppression window** — not accumulating, and not reset. It resumes when the suppression lapses: the `skipped` record expires (60 days, per `§ State File Format`'s bounded retention), or the signal re-surfaces with fresh grounded evidence and the consult lets it back through. The `**Frequency**: N (below threshold)` annotation is that counter, derived rather than incremented. When the signal recurs and is not suppressed, the sweep appends the recurrence's new session ids to `**Sessions**` (no duplicates, and no session counted twice, above), sets `Frequency` to the number of distinct sessions in `Sessions`, and re-dates `**Last observed**`. This update happens before the promotion gate is evaluated, whichever path follows (persist below threshold, or promote). The `**Evidence-quote**` line carries the verbatim span grounding the signal — the `Evidence-quote` cross-type metadata field defined in `§ Cross-type optional metadata` — as the signal's load-bearing evidence; entries persisted before this field was introduced remain valid without it.

**Stale singletons expire** (removal class `expired_signal`, `§ The rename/removal working map`). A persisted signal still at `**Frequency**: 1` whose `**Last observed**` date is more than 90 days before the sweep's date has gone unobserved for 90 days, and a full sweep removes it at `sweep-synthesize.md § SYN-PROMOTE`, journal-first (`§ Crash-recovery journal`), naming each removed heading in the Report. The check runs after that sweep's re-observation updates, so a signal re-observed this run has just been re-dated and does not expire. Only a `Frequency 1` signal expires; one observed in 2 or more sessions never does. A missing or invalid `Last observed` never expires a signal (fail-safe toward keep). The sweep checks only the signal files it reads this run: `memory/topics/improvement-signals.md` and each dispatched project memory file. Lightweight mode never expires a signal.

### Cross-type optional metadata

The following fields are **optional metadata that may attach to any entry** (feedback, decision, pattern, or the `[improvement_signal]` sub-form) — with **two exceptions, `Support-set` and `Affirmed`, which are scoped to higher-order nodes only** (see their bullets). They are absent by default; an entry without them stays valid and loadable. Each names the consumer that reads it, per `shared/AGENTS.md § Structure Requires a Consumer` (the `/qdream` consolidation sweep is the sanctioned consumer for all of them):

- **Evidence-quote** (schema key `evidence_quote`): a verbatim quote from the session or plan the entry was derived from. **Consumer**: the `/qdream` sweep's cross-validation verifier, which checks the claim is entailed by it. Never stored in `memory/MEMORY.md` or `memory/HIGHER_ORDER.md`, which load every session: the `Source` anchor re-opens it. Distinct from the `insights_signals.evidence` id-array in `§ Dream Sub-agent Return Schema`.
- **Usage** (integer): a counter a sweep bumps when an entry was relied on, also fed by plans' `Memory relied on` header (rule: `§ Derived Utility & Pruning`). Evidence, never a gate. **Consumer**: the `/qdream` sweep's derived-utility prune order (and the kiro merge grid).
- **Outcome** (recurred/not + date): whether the friction the entry addressed recurred after an applied edit, plus the check date — e.g. `recurred 2026-07-20` or `not-recurred 2026-07-20`. **Consumer**: the `/qdream` sweep's derived utility and its governance-retirement pass (and the kiro merge grid). **In-session capture feeds this signal**: when the user's next turn clearly confirms or contradicts a result that visibly relied on a memory entry, the session says so aloud (helpful/harmful, naming the entry) so the sweep's session analysis can mine it — only when the causal link is clear; never guess a rating. Mapping: in-session harmful ≙ an unresolved negative outcome (`§ Promotion path`); helpful ≙ none (informational).
- **Governance-conflict** (`<file § section> — adjudicated <date>: <state>`) + **Governance-conflict-quote** (a verbatim rule span): the user's Phase-4b adjudication of a memory-vs-governance contradiction or kept subsumption, recorded on the entry it belongs to. An entry may carry **N adjacent `(Governance-conflict, Governance-conflict-quote)` line-pairs**, each keyed by **(contradicted/absorbing `<file § section>`, whitespace-normalized span)** — one record per distinct governance rule the entry has been adjudicated against. `Governance-conflict` names the contradicted `<file § section>`, the adjudication date, and the state (`keep-entry | rule-update-pending | deferred`, or **`subsumption-kept`** for a kept subsumption — where the prefix reads `subsumed by` rather than `contradicts`, `§ Governance-conflict adjudication`); `Governance-conflict-quote` carries the verbatim span of the governance rule **as adjudicated** (the contradicted rule, or the absorbing `subsuming_quote`), so the decision can be re-checked against the live file with no git history. The grammar tolerates a trailing `(…)` note after the state token, and is robust to an in-section parenthetical in the `<file § section>` name (e.g. `shared/AGENTS.md § Memory Management (Dream autonomy exception)`). **Consumer**: the `/qdream` **reconciliation pass** (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-RECONCILE`), which reads **each** `Governance-conflict-quote` and applies the re-raise predicate in **§ Governance-conflict adjudication** **per-record** — re-checking each sweep whether each quoted span still matches its cited file, so no state suppresses a conflict forever. Format and full lifecycle (including the protection a **non-terminal** record gives its entry against every autonomous-removal path): **§ Governance-conflict adjudication** below.
- **Support-set** (pointers): pointers to the episodes, entries, archived plans, or sessions a higher-order node abstracts. **Scope — higher-order nodes only**: this field attaches to a `memory/HIGHER_ORDER.md` node and **nowhere else**; no base `memory/MEMORY.md` entry carries one. (That scoping is what makes the two-population split in `§ Higher-Order Tier` — node pointers vs. `episodic_ledger` pointers — an *exhaustive* account of where `Support-set` pointers live.) **Consumer**: the `/qdream` sweep's replay (higher-order synthesis re-reads them so they re-enter the next sweep's reflection input) and its per-sweep reconciliation pass (`§ Higher-Order Tier`, *Support-set referential integrity*).
- **Affirmed** (date): the date the user chose `Keep node` at the sweep's ungrounded-node gate. **Scope — higher-order nodes only**, like `Support-set`; no base entry carries one. **Writer**: `/qdream` § APP-ADJUDICATE's `Keep node` branch. **Consumer**: the `/qdream` sweep's **Phase-4b ungrounded-node gate**, which does not re-surface an affirmed node while its `Support-set` is unchanged (`§ Higher-Order Tier`, *The user gate*). This is the **only** persisted state on a node — a `Support-set` pointer carries none.

- **Stale-after** (absolute date): the date past which the entry's claim should not be trusted without a fresh check — the entry's own volatility expectancy, written when the author can name one (`2026-12-31` for a fact tied to a release, a support window, or a dated external dependency). Absolute `YYYY-MM-DD` only (`§ Date References`). **Consumer**: the `/qdream` sweep's Task-4 classification pass (`sweep-gather.md § Phase 2 — Gather § GAT-CLASSIFY`), which compares it against the sweep date and, when it has fired, forces the entry through its type-specific verification and revokes its pre-filter skip (`§ Type Taxonomy`). **Second consumer**: read-time behaviour (`shared/AGENTS.md § Read-time behavior`) — a fired expiry means re-verify before acting on the entry.
- **Stale-when** (condition): the same expectancy expressed as an **event** rather than a date — "when kiro-cli v3 replaces the v2 steering files" — for the common case where an entry's real expiry is an event nobody can date in advance. One sentence, naming a condition an agent can actually check (a tool version: `§ Suspect memory entries`). **Consumer**: the same Task-4 pass, which evaluates the condition and feeds the identical fired/not-fired flag.

**A fired expiry is a re-verification trigger, never evidence of staleness.** Neither field can make an entry stale, demotable, prunable, or deletable on its own, except a user-memory `pattern` entry, whose fired expiry is its type-specific check (no codebase to grep; `sweep-gather.md`, Task 4) and which only the user deletes. Firing means only *"the cheap skip is off — actually check this one"*; whether the entry survives is then decided **solely** by its type-specific verification rule, exactly as for any other entry. This is the same principle as the unreachable-anchor rule in `§ Type Taxonomy`: a calendar date is not an argument, and autonomously deleting on one would violate the asymmetric-cost heuristic in `§ Derived Utility & Pruning` (*"a stale entry costs little; deleting someone else's load-bearing note costs a lot"*). Consequently both fields are **excluded from the prune order's inputs** — an expiry never lowers utility.

**A fired expiry that survives its re-verification is cleared, and `Verified` is re-dated.** When the forced check **passes**, the sweep re-dates `Verified` to today with its own actor and method **and removes the field that fired**. A `human:` entry goes to the user instead. The expectancy was simply wrong — the entry outlived it — and a new one is not predicted autonomously; the next author may set one. **Without this, the field is a slow-acting deletion bug**: an entry whose `Verified` never advances re-fires its expiry on *every* subsequent sweep, and criterion (5) of `§ Derived Utility & Pruning` (oldest `Verified`) ratchets it toward the front of the prune queue — so an entry that has passed verification every run for a year eventually gets pruned for being old. Clearing the fired field and re-dating `Verified` is what keeps the expiry a one-shot trigger rather than a permanent handicap. (A `Stale-when` whose condition has *not* actually occurred never fired, so nothing is cleared.)

Where present, these render as additional bold fields on their own line(s) beneath the standard `Source`/`Verified` line, e.g.:

```markdown
**Evidence-quote**: "<verbatim span from the source>"
**Usage**: 3 | **Outcome**: not-recurred 2026-07-20
**Governance-conflict**: contradicts shared/AGENTS.md § Some Rule — adjudicated 2026-07-15: rule-update-pending
**Governance-conflict-quote**: "<verbatim span of the rule as adjudicated>"
**Governance-conflict**: subsumed by shared/skills/qplan/TEMPLATES.md § QA Phase Annotation — adjudicated 2026-07-16: subsumption-kept (verifier refuted the subsumption: load-bearing residue)
**Governance-conflict-quote**: "<verbatim span of the absorbing rule>"
**Support-set**: <pointer-1>, <pointer-2>
**Affirmed**: 2026-07-14
**Stale-after**: 2026-12-31
**Stale-when**: claude-code version > 2.1
```

### Governance-conflict adjudication

When a memory entry **contradicts a governance rule**, which side is stale is a **user** decision (`sweep-decide-apply.md § Phase 4b — Decisions § DEC-GATE`) — the sweep never asserts which artifact is more current (section-granular git history exists nowhere in the repo, and the only date signal is file-granular and self-labeled *"an upper bound, not proof"*). The user's decision is recorded **on the entry** in the two `§ Cross-type optional metadata` fields, so it merges with the entry and dies with it, and a project entry's adjudication stays in the project repo. An entry may carry **N** adjacent `(Governance-conflict, Governance-conflict-quote)` line-pairs — one record per distinct governance rule adjudicated against it:

```markdown
**Governance-conflict**: contradicts <file § section A> — adjudicated <YYYY-MM-DD>: keep-entry | rule-update-pending | deferred
**Governance-conflict-quote**: "<verbatim span of rule A as adjudicated>"
**Governance-conflict**: subsumed by <file § section B (optional in-section note)> — adjudicated <YYYY-MM-DD>: subsumption-kept (<optional trailing note>)
**Governance-conflict-quote**: "<verbatim span of rule B as adjudicated>"
```

Each `Governance-conflict-quote` is **load-bearing**: it is the verbatim span of the rule *at the moment the user adjudicated*, and the re-raise predicate below is a **text-to-text** check against it that needs no git history.

**Re-raise predicate — per record, and no state suppresses a conflict forever.** On each sweep, the reconciliation pass (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-RECONCILE`) re-checks **each record** on every entry carrying `Governance-conflict` fields and re-surfaces it at the Phase-4b gate when its state says to:

| State | Re-raise when | Terminates because |
|---|---|---|
| `keep-entry` | the quoted span **no longer matches** the cited file — the rule changed, so re-adjudicate | a still-matching span means the user's decision still applies to the same rule |
| `rule-update-pending` | **every sweep, unconditionally** — until the user re-adjudicates it to `keep-entry` or `delete-entry`. The span-match is a **prompt signal, not a re-raise guard**: while the span still matches, frame the prompt as *"the requested governance change hasn't landed yet"*; when the span stops matching (the rule changed), frame that sweep's re-raise as *"the rule has since changed — please re-confirm"*, which moves the user to `keep-entry`/`delete-entry` | only the user's re-adjudication to `keep-entry` or `delete-entry` terminates it — the re-raise never stops on its own. This is what prevents the stuck state: when the span stops matching, that sweep **still re-raises** (now asking the user to re-confirm) rather than falling silent |
| `deferred` | **next sweep, unconditionally** | that is what defer means |
| `subsumption-kept` | the `subsuming_quote` **no longer matches** the cited section — the absorbing rule changed, so re-offer at the Phase-4b **subsumption** gate | a still-matching quote means governance still absorbs the entry, so the user's `Keep` still applies. Without this row the verifier would re-confirm the same subsumption every sweep and re-prompt the user forever — the same nag-loop this table closes for conflicts, left open for subsumptions |

**One entry may surface at both Phase-4b gates in one sweep** — its `subsumption-kept` record at the subsumption gate, a non-terminal conflict record at the conflict gate — each record re-raising independently per the table above.

**`subsumption-kept` records a kept subsumption, not a contradiction.** When the user chooses `Keep` at the Phase-4b **subsumption** gate (`sweep-decide-apply.md § Phase 4b — Decisions § DEC-GATE` — governance has *absorbed* the entry, and the user keeps it anyway), Phase 5 writes `**Governance-conflict**: subsumed by <file § section> — adjudicated <date>: subsumption-kept` plus the `subsuming_quote` as its `Governance-conflict-quote`. It reuses this field family because the re-raise machinery is shared — the reconciliation-pass scan already walks every `Governance-conflict`-bearing entry — and the prefix reads **`subsumed by`** rather than `contradicts` to mark the relationship. `subsumption-kept` is **terminal-like**, like `keep-entry`: it re-raises only when its quote stops matching (the row above), it is **not** one of the non-terminal states (`rule-update-pending`/`deferred`) the four protection clauses shield, and it merges as a terminal-like state (`§ Merge Strategy`) — a settled decision needs no autonomous-removal protection.

**Span matching is normalized**: compare after collapsing every run of whitespace (including newlines) to a single space and trimming, so a cosmetic re-wrap of the rule does **not** fake a rule change. **And the span must still be found within the cited `§ section`**: if it matches elsewhere in the file but not in that section, the rule *moved* — the anchor is stale, so **re-raise for re-anchoring** rather than reporting a false match.

**Span-aware reconciliation.** The fresh `governance_conflicts` detection (`§ Dream Sub-agent Return Schema`) now carries a `governance_span` field — the verbatim span of the contradicted rule. The reconciliation subtraction (suppressing a fresh detection that has already been adjudicated) requires a **(section, span)** match that is **containment-based and whitespace-normalized**: a fresh `governance_span` that **contains, or is contained by**, a recorded record's `Governance-conflict-quote` span within the **same `§ section`** is the same key — so excerpt-boundary drift on the same unchanged rule does **not** spuriously re-surface a settled record. A same-section detection whose `governance_span` neither contains nor is contained by any existing record's span is a **new** conflict and is surfaced (not suppressed). **Fail-safe**: on genuine span ambiguity the reconciliation **surfaces**, never suppresses.

**A non-terminal `Governance-conflict` record protects its entry from every autonomous-removal path.** An entry is protected if **any** record on it is in state `rule-update-pending` or `deferred` — it carries an **unresolved user decision**, so an unrelated autonomous path must not destroy it before that decision is honoured — doing so would permanently suppress the conflict. Four paths would otherwise do exactly that; each routes the entry to the Phase-4b user gate instead of removing it:

- **The Size-check prune** (`§ Derived Utility & Pruning`; `sweep-synthesize.md § Phase 3 — Synthesize`, Size check) — **exclude** an entry carrying any non-terminal `Governance-conflict` record from the prune set.
- **Promotion-removal** (`sweep-decide-apply.md § Phase 4b — Decisions` and `§ Phase 5 — Apply` — promotion *moves* the entry) — **re-raise the pending adjudication before removing** the source entry.
- **Stale-entry deletion** (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-STALE` — a `rule-update-pending` entry can legitimately fail its type-specific verification while its adjudication is pending) — **never delete autonomously**; surface it in Phase 4b showing both the staleness evidence and the pending adjudication.
- **Provenance auto-demotion** (`§ Type Taxonomy`, *Provenance re-open & auto-demotion*) — a reachable-and-contradicting anchor on an entry carrying any non-terminal `Governance-conflict` record **surfaces in Phase 4b**; it does not demote silently.

**`Defer` persists the `deferred` state, and writes no `rejected_lessons` record.** `Defer` **writes** `**Governance-conflict**: contradicts <file § section> — adjudicated <date>: deferred` plus its `Governance-conflict-quote` onto the entry — a real, persisted non-terminal state (**not** "nothing"), so the re-raise predicate re-surfaces it next sweep and the four protection clauses above shield it from every autonomous-removal path in the meantime. It writes **no** `rejected_lessons` record: a weak model that conflates `Defer` with a proposal `Skip` would suppress the conflict for 60 days, directly contradicting "re-raise next sweep." The phrase "Defer writes nothing" refers only to the *`rejected_lessons` record* — the `deferred` state field is written like every other branch.

**Merge behaviour (dedup) — union by key, and a non-terminal conflict is never dropped.** `Governance-conflict` is **repeatable** and merges per `§ Merge Strategy`: dedup-merge **unions record-lists by key** (key = (contradicted/absorbing `<file § section>`, whitespace-normalized span)). Same-key records from two merging entries collapse to the **most-recent by `adjudicated <date>`** (same-day tie → the **non-terminal** state wins — `rule-update-pending`/`deferred` over `keep-entry`/`subsumption-kept` (both terminal-like) — fail-safe toward keeping the conflict live); different keys **coexist as separate records** on the merged entry. This is **resolution**, not suppression — every surviving record remains individually re-raiseable per the table above. (regression fixtures: transition-fixtures.md FIX-MERGE-*)

---

## Higher-Order Tier (`memory/HIGHER_ORDER.md`)

The higher-order tier is a third memory file — `memory/HIGHER_ORDER.md` at the config repo root — holding **abstractions the `/qdream` sweep induces across episodes and base entries**, one rung above the concrete `feedback`/`decision`/`pattern` entries in `memory/MEMORY.md`. It is the semantic half of the dual store; the episodic half is the `.dream-state.json` `episodic_ledger` (`§ State File Format`). The sweep writes it autonomously (Dream autonomy exception, `shared/AGENTS.md § Dream autonomy exception`); it is loaded at session start like the memory files (`shared/AGENTS.md § Memory locations` / `§ Read-time behavior`), ranks below user memory and below governance (`shared/AGENTS.md § Authority hierarchy` — an abstraction never outranks its own ground truth), and is read-time advisory — it never overrides a governance rule.

For read-time groundedness weighting (how a session agent should discount a weakly-grounded node), see `shared/AGENTS.md § Read-time behavior`.

**Format**: the same type-section layout as `memory/MEMORY.md` (`## Feedback`, `## Decision`, `## Pattern`) with a short self-describing preamble. Each higher-order node is an entry subsection carrying the standard `Why`/`How to apply`/`Source`/`Verified` fields plus a **`Support-set`** field (`§ Cross-type optional metadata`) whose pointers name the concrete things the node abstracts — an `episodic_ledger` record, a **user or project** `memory/MEMORY.md` entry, an **archived plan**, or a **session**. (Full legal-target list and pointer grammar: `§ Support-set referential integrity`. A pointer **never** names a governance section.)

```markdown
### <one-line higher-order heading>

**Why**: <why this abstraction matters — one to two sentences>
**How to apply**: <concrete action — one sentence>
**Source**: <re-openable anchor: plan-slug + section, or session-id + line-span> | **Verified**: <YYYY-MM-DD>[ (<actor>[, <method>])]
**Support-set**: <pointer-1>, <pointer-2>, <pointer-3>
**Affirmed**: <YYYY-MM-DD>
```

**A `Support-set` pointer carries no marker and no state** — no removal class, no date, no "this target was deleted" flag. Each sweep **resolves every pointer fresh** against what is actually there (`§ Support-set referential integrity`). Exactly one line on a node is **persisted state the next sweep reads back**, so a writer must emit and preserve it exactly:

- **`Affirmed`** (optional, absent by default) — the date the user chose `Keep node` at the Phase-4b ungrounded-node gate, written by **§ APP-ADJUDICATE**. It suppresses re-surfacing at that gate. A sweep that **updates an existing node's *content*** (`Why` / `How to apply` / `Source` / `Verified`) **preserves an existing `Affirmed` line verbatim** rather than dropping or re-deriving it. The line is dropped only when the Phase-3 higher-order synthesis step **changes that node's `Support-set`** — adds, removes, or re-points a pointer — because the affirmation was made on a set of facts that no longer holds (`§ Support-set referential integrity`), or when the user re-affirms (re-dating it).

**Compounding consumer** (the sweep): the `/qdream` Phase-3 higher-order synthesis step (`sweep-synthesize.md § Phase 3 — Synthesize`) writes/updates these nodes; the **next** sweep reads `memory/HIGHER_ORDER.md` at Orient (Phase 1) so the nodes re-enter that sweep's reflection input — the abstractions compound across sweeps instead of being re-derived from scratch. This is the consolidation-sweep consumer sanctioned by `shared/AGENTS.md § Structure Requires a Consumer`.

**Boundary vs. the Insights Report and user memory**: this tier is the **persistent** semantic store — durable, `Support-set`-backed abstractions loaded at session start. It is distinct from the Phase-4a **Insights Report** (`sweep-decide-apply.md § Phase 4a`), an **ephemeral** per-run chat narrative derived from `insights_signals` and never persisted here: a cross-project observation worth carrying forward becomes a higher-order node (earning a `Support-set`); a one-run "what's working / what's hindering" narrative stays in the Insights Report. It is also distinct from base **user memory** (`memory/MEMORY.md`): a higher-order node is an *abstraction over* several base entries/episodes, not a restatement of one — **promote into** the tier (a genuine generalization carrying a multi-target `Support-set`), do not duplicate a single base entry up a level. Keep all three from becoming parallel abstraction layers.

### Support-set referential integrity

**Two pointer populations, two different rules.** The `Support-set` field attaches to higher-order nodes only (`§ Cross-type optional metadata`), so *every* `Support-set` pointer in the subsystem lives in one of exactly two places — and only one of them is ever reconciled:

- **Node pointers** — the `Support-set` field on a `memory/HIGHER_ORDER.md` node. These are **live references**: re-pointed when this sweep renamed the target, and otherwise **resolved fresh, from scratch, on every sweep**. Everything below governs these.
- **Ledger pointers** — the `support_set` array on an `episodic_ledger` record (`§ State File Format`). These are **history in an append-only log** (`sweep-synthesize.md § Phase 3 — Synthesize`: *"Append-only — never rewrite prior records"*). A ledger pointer whose target no longer exists is **not a defect** — it faithfully records what the episode named at the time. It is **never reconciled**, never re-pointed, and its record is **never rewritten**. *Worked example*: `.dream-state.json` record 3's pointer names a `memory/MEMORY.md` entry that a later sweep rewrote under a different heading. The pointer dangles, and that is **correct** — the episode did name that entry, then. A rule ordering the sweep to rewrite it would order a write the append-only schema forbids.

**A node pointer carries no state. The sweep does not *remember* that a target is gone — it *looks*.** There is no marker on a pointer: no removal class, no date, no "this target was deleted" flag, nothing carried from one sweep to the next. Every outcome below is **derived fresh, each sweep, from what is actually on disk**. This is the core of the rule and it is deliberate: a persisted "the target was removed" marker must be *kept true*, and there is no cheap way to keep it true — leave it un-re-checked and it becomes **unfalsifiable** the moment the target comes back; re-check it by matching a heading string and it becomes **forgeable** by any unrelated entry that reuses that heading. Resolving fresh avoids **maintaining** either failure — it stores no marker that must be kept true, because the question *"is the target there?"* is answered by looking, not by remembering. It does **not** escape *heading-collision* exposure as such: resolving fresh is **itself a bare heading-string match**, with no content or semantic check, so a heading later reused by an unrelated entry still collides. What fresh resolution removes is the marker design's *false-delete* forgeability — by looking each sweep it never gets stuck asserting a removal that has since been undone — while it **inverts the residual heading-collision exposure to the fail-safe direction**: a collision now yields a false **`resolved`** (the node is wrongly *kept*), never a false absence (a node is never wrongly *deleted*). See the heading-collision residual disclosed below. The **only** persisted state on a node is the optional **`Affirmed`** line (below), and that records a **user decision**, not a fact about the world.

**Legal node-pointer targets.** A node pointer names an **`episodic_ledger` record**, a **`memory/MEMORY.md` entry** (user or project), an **archived plan**, or a **session**. It **never** names a governance section (see the retirement carve-out below). Write it in this grammar, so the next sweep can resolve it:

| Target | Written as |
|---|---|
| `episodic_ledger` record | `episodic_ledger #<N>` — `<N>` is the record's 1-based index in the array. **Positional-index guard**: that index is stable **only because the ledger is append-only today** (`§ State File Format`). If on-disk pruning/windowing of stale episodes is ever implemented — deferred to the memory-decay ROADMAP item, per `§ State File Format` — a positional pointer would silently resolve to the **wrong record**, which is worse than dangling. Any such change must **migrate every node pointer (or freeze the index) as part of itself.** |
| user memory entry | `user memory § <heading>` — the config-repo `memory/MEMORY.md` or one of its `memory/topics/*.md` files. There is exactly one user memory, so it needs no qualifier. `<heading>` is the entry's heading **text** — the `###` line with the `###` marker and its trailing space **stripped** — matched **character-for-character**. **A heading now living in `memory/topics/<topic>.md`** (`shared/AGENTS.md § Memory locations`, "Topic memory") **resolves through this same pointer form** — the on-demand tier is not a separate pointer type. |
| project memory entry | `project memory (<project-path-key>) § <heading>` — `<project-path-key>` is the project's **full normalized path key**, exactly as it appears in `.dream-state.json` `projects`. **A basename is not a project identifier**: `~/work/api` and `~/perso/api` are both `api`, so a basename-keyed pointer lets a removal in one project be attributed to another project's identically-named — and entirely intact — entry. The path-key qualifier is therefore **mandatory**. A store with no present checkout is a project keyed `store:<identity>` (its `STORE` lines, `§ The STORE file`); a pointer with that key resolves through the store repo by identity, never by directory name. A pointer written with a bare heading, or qualified by a basename that matches more than one project, is **`indeterminate`** (below): the sweep never guesses which project it meant. `<heading>` is the entry's heading **text** (the `###` line with the `###` marker and its trailing space **stripped**), matched **character-for-character**. |
| archived plan | `<plan-slug> § <section>` — the `plans/done/` filename without `.md`, plus the section heading **text** (the `##`/`###` line with the marker and its trailing space **stripped**), matched **character-for-character**. |
| session | `session <session-id>` — **the least durable form. Use it only when nothing more durable names the evidence.** Prefer an `episodic_ledger` record or `<plan-slug> § <section>`: session transcripts are **not verified during reconciliation** (below), so a session pointer is permanently `indeterminate` and permanent Report noise. (Same durability preference `§ Merge Strategy` and `§ Memory File Format` apply to `Source` anchors.) |

**The path key is stable, not portable — run the lifecycle from one canonical path per project.** `<project-path-key>` is an absolute path: it buys unambiguity at the cost of stability. Reach the same project by a *second* path — a WSL mount versus a Windows drive, a re-rooted OneDrive sync, a directory rename — and it becomes a **second project** with its own entries, whose pointers resolve `confirmed-absent` from the other side. That is the wrong signal: the ground truth exists, under a different key. The config repo is exposed whenever one person runs it from both Windows and WSL: each OS has its own clone, and each clone has its own path. For this repo the canonical path is the Windows one, which is also the environment where a PowerShell interpreter exists, so `test-parity.sh`'s cross-shell assertions actually execute rather than SKIPping to a green exit. Re-keying after the fact is a migration; running from one path is a habit.

#### The reconciliation pass — three steps, and the order is normative

On each sweep, for **node pointers only** (ledger pointers are exempt and are not reconciled at all):

1. **Re-point** every pointer whose target this sweep **renamed**.
2. **Resolve** every pointer into exactly one of three outcomes.
3. **Evaluate** the ungrounded trigger on those outcomes.

**Running (2) before (1) is a live defect, not a style preference.** A renamed target still *exists*, under its new heading — so an un-re-pointed pointer resolves `confirmed-absent`, and a node whose ground is entirely intact is driven to the deletion gate. State and execute the order as written.

**Step 1 — re-point renamed targets.** A **rename** changes an entry's heading **without removing the entry**, for example the salvage-rewrite (`sweep-synthesize.md § Phase 3 — Synthesize § SYN-STALE`, *"Salvage before deleting"*) or a dedup merge that keeps the entry under the other heading (`§ Merge Strategy`); these examples are not exhaustive. Re-point every node pointer naming the **old** heading to the **new** heading, reading the `old target → new target` pairs from the working map (below). A rename is **the one case where the sweep has perfect information** — it holds the mapping it just created — so it must never be left to the resolve step to guess at. (Ledger pointers stay exempt: they are history. Record 3's dangling ledger pointer is precisely what an unhandled rename produces.)

**Step 2 — resolve. Exactly three outcomes.**

- **`resolved`** — the target **exists now**. Nothing to do.
- **`confirmed-absent`** — the sweep **could look, and the target is not there**: the pointer's target artifact was loaded/analyzed *this sweep*, and the exact heading is **absent** from it.
- **`indeterminate`** — the sweep **could not look**. Never treated as absent.

**The distinction between the last two is the load-bearing safety property.** *"Confirmed-absent" means the sweep looked and it was gone. "Indeterminate" means the sweep could not look. Conflating them is how a node gets driven to the deletion gate on evidence the sweep never actually had.* This subsystem already refuses that conflation everywhere else — `§ Type Taxonomy`'s unreachable-provenance rule: *"an anchor that cannot be opened is not evidence the claim is false"* — and this applies the same principle consistently.

Resolve by target form:

| Pointer form | Can the sweep look? | Outcome |
|---|---|---|
| `episodic_ledger #<N>`, `<N>` in range | Yes — the sweep holds the ledger | **`resolved`** (see the accepted property below) |
| `user memory § <heading>` | Yes — the orchestrator reads the config-repo `memory/MEMORY.md` at Orient (Phase 1), and the manifest's `user_memory.json` lists every `memory/topics/*.md` heading | heading present in either → `resolved`; absent from both → **`confirmed-absent`** |
| `project memory (<project-path-key>) § <heading>` | Only if that project was **analyzed this sweep** (here: a dispatch ran Task 4 on its memory file, `all tasks` or `Tasks 4-5 only`) (its headings are the manifest side file's `entries[]`) | analyzed → `resolved` / `confirmed-absent`. **Not analyzed this sweep, inaccessible, or the path key is not in `.dream-state.json` `projects`** → **`indeterminate`** |
| `<plan-slug> § <section>` | Only if the sweep can open exactly one `plans/done/<plan-slug>.md` among the projects analyzed this sweep | opened → `resolved` / `confirmed-absent`. Not found, or ambiguous across projects → **`indeterminate`**. **Cross-project blind spot** (same as an unqualified project reference): a plan-slug carries **no project qualifier**, so if the slug is ambiguous across the projects analyzed this sweep, **or could exist in a project not analyzed this sweep**, an absence is not verifiable across all projects — the pointer is **`indeterminate`**, never `confirmed-absent`. The sweep does not assert an absence it cannot verify everywhere the slug might live. |
| `session <session-id>` | **No** — session transcripts are not verified during reconciliation, and no phase agent or orchestrator opens them (Rule 7) | always **`indeterminate`** |
| any unrecognized or illegal form | **No** — the sweep does not guess what a malformed pointer meant, even when a near-match target exists | always **`indeterminate`** |

**Accepted residual — a reused heading resolves `resolved` (fail-safe over-retention).** The resolve step matches a `user memory § <heading>` / `project memory (<project-path-key>) § <heading>` pointer by **heading string, character-for-character** — there is **no content or semantic check**. So if a pruned entry's heading is later reused by an **unrelated** entry, the pointer resolves **`resolved`** and the node is silently re-grounded on that unrelated content. This is an **accepted residual**, disclosed in the same spirit as the project-basename collision above: it can only over-**retain** a node (inert clutter), never over-delete one — a collision drives the outcome to the *keep* side, and node removal is user-gated regardless. **Reopen trigger**: if mis-grounding via heading reuse is ever observed in practice, add an identity check at resolve time — comparing the resolved entry's content, or its `Source`/`Verified`, against what the pointer originally named. That guard is **deliberately not built now**: it is new machinery this plan's invariants exclude.

**Step 3 — the ungrounded trigger, fail-safe by construction.** A node is **ungrounded** — and surfaced to the user — **if and only if it has at least one pointer and *every* pointer is `confirmed-absent`**: zero `resolved`, and **zero `indeterminate`**.

**Any single `indeterminate` pointer blocks the gate.** The sweep cannot claim a node has lost all its ground when there is ground it never checked. This **fails safe**: the node is **kept**, and named in the Report. (A node with **no** pointers at all is not ungrounded either — there is nothing for it to have lost.)

**Every `confirmed-absent` and every `indeterminate` pointer is named in the Report** (`sweep-decide-apply.md § Report`), together with the node carrying it. Neither is ever removed and neither ever removes its node on its own, so the Report is the only thing that keeps them visible — *loudly* inert rather than silently immortal.

**Accepted property — a node carrying a ledger pointer can never become ungrounded.** `episodic_ledger` records are append-only and are never removed, so a ledger pointer **always** resolves. A node with at least one of them therefore never has an all-`confirmed-absent` Support-set, and never reaches the gate. This is a **feature, not an oversight**: an episode is *permanent ground*, and a node induced from one keeps that ground forever. It is stated plainly here so no future reader rediscovers it as a bug.

**Accepted behaviour on out-of-band and unreachable targets.** A target removed *out of band* — the user hand-editing `memory/MEMORY.md` — needs no catch-up machinery at all: the next sweep simply looks, finds it gone, and resolves `confirmed-absent`. A target the sweep can never reach (a session pointer; a project it never analyzes) stays `indeterminate` for as long as that holds, and is reported every sweep. That is the deliberate shape of the rule: **self-heal where the sweep can look; never delete on inference where it cannot.**

#### The rename/removal working map

The reconciliation pass runs *after* the Phase-3 steps that do the removing and renaming, so those steps must **record what they did** rather than leave the pass to re-derive it. The steps below record `old target → new target` pairs and `removed target → removal class` records, each through `dream-write.py memedit`, into a **per-sweep working map** (`sweep/working-map.json` in the work folder, whose only writer is `dream-write.py memedit`; persisted **within** a sweep as the crash-recovery journal, cleared on success; not carried across sweeps — a *successful* sweep's map is still gone by the next sweep, so `.dream-state.json` "not a recovery surface" pins remain true): **§ ORI-RECOVER** (initializes the map: its landed renames go to `handoff/working-map-seed.json`, which `memedit` loads on its first run — `§ Crash-recovery journal`), then **§ SYN-WRITE and § SYN-STALE** (append to it during Phase 3, through `memedit` ops). **§ SYN-PROMOTE** appends removal records only, for its `expired_signal` removals. **§ APP-ADJUDICATE** appends the user-gated Phase-5 removals, and `memedit` journals any of its `replace` ops that changes an entry's heading as a rename too. Those ops run after the reconciliation pass, so this sweep re-points no pointer onto them: at the next sweep a pointer to the old heading can resolve `confirmed-absent`, and its node then reaches the user-gated `Keep node / Remove node / Defer` prompt, never an autonomous removal. The re-point in `§ SYN-HIGHERORDER` item 3 consumes `old→new` pairs from the **three** steps whose renames this sweep re-points (`§ ORI-RECOVER`, `§ SYN-WRITE`, `§ SYN-STALE`). The map records (a) every **renamed** entry as an explicit `old target → new target` pair, and (b) every **removed** entry paired with its **removal class**. **Key the map on the fully-qualified pointer target** in the grammar above — `user memory § <heading>`, `project memory (<project-path-key>) § <heading>` — **never on a bare heading.**

The two halves have **different jobs, and only one of them decides an outcome**:

- The **rename** half is **load-bearing**: it drives Step 1's re-point. Without it, a renamed target resolves `confirmed-absent` and its node is falsely reported ungrounded.
- The **removal** half is **descriptive only**. It **never** decides a pointer's outcome — Step 2 does that by looking. It exists so the Report and the Phase-4b prompt can **name the cause** of an absence *this sweep* caused. Where the target was already absent when the sweep arrived, say so honestly: `absent (removed by an earlier sweep or out of band)`. **Never guess a cause.**

The **eight** live removal classes — the vocabulary the working map records, **not** a set of triggers:

| Removal class | Executes in |
|---|---|
| **demoted** — provenance auto-demotion (`§ Type Taxonomy`) | § SYN-STALE |
| **pruned** — the autonomous budget prune of any tier (`§ Derived Utility & Pruning`, `§ Session-start memory context budget`) | § APP-WRITE (autonomous) |
| **stale-entry deletion** — type-verification failure (a *distinct* cause from demotion) | § SYN-STALE (autonomous, gated), or § APP-ADJUDICATE (user-gated via Phase 4b) |
| **promotion-removal** — the source entry is deleted once an approved promotion lands | § APP-ADJUDICATE |
| **`[improvement_signal]` promotion-removal** — a signal crossed the frequency gate and the user chose `Apply` on the resulting proposal; the entry is removed as that promotion lands (`§ [improvement_signal] sub-form`) | § APP-ADJUDICATE |
| **subsumption removal** — governance absorbed the entry's claim and the user chose `Remove` at the Phase-4b subsumption gate (`§ Governance-conflict adjudication`) | § APP-ADJUDICATE |
| **Delete entry** — the user chose `Delete entry` at the Phase-4b governance-conflict gate (`§ Governance-conflict adjudication`) | § APP-ADJUDICATE |
| **`expired_signal`** — a below-threshold `[improvement_signal]` at `Frequency 1` that no session re-observed for 90 days, by its `Last observed` date (`§ [improvement_signal] sub-form`, *Stale singletons expire*) | § SYN-PROMOTE (autonomous) |

**The Phase-3/Phase-5 timing split needs no special handling.** The four Phase-5 removal classes (the two promotion-removals, **subsumption removal**, and **`Delete entry`**, plus a user-gated **stale-entry deletion** or **pruned**) execute in **Phase 5**, *after* this sweep's reconciliation pass — so their targets are still present when it runs, and their pointers correctly resolve `resolved` this sweep. On the **next** sweep the target is simply gone, and the pointer resolves `confirmed-absent` by ordinary lookup. Nothing has to be marked at execution, and nothing can go stale in between. (Record them in the working map anyway, so *this* sweep's Report can name the cause.)

**There is no `merge-absorption` class — a dedup merge removes nothing.** `§ Merge Strategy` merges a **new proposal** into an **existing entry**; it never removes an existing entry, so it can never orphan a pointer's target. The only thing a merge can change is the surviving entry's *heading* (it "prefer[s] the more precise `Why`/`heading`") — and that is a **rename**, handled by Step 1.

**Retirement carve-out** (it survives the target-list widening above): a governance rule *retired* by the Phase-4b retirement pass is **not** a Support-set target — **pointers never name governance sections** — so retirement can never move a node toward removal.

#### Crash-recovery journal

The working map is **serialized to disk** as `memory/.dream-journal.jsonl` — a `.gitignore`d (the store repo ignores `user/memory/.dream-journal.jsonl`), non-git-tracked, non-session-loaded file under the config repo's `memory` link. It is the **durable, crash-recoverable form** of the working map (`sweep/working-map.json`): logically append-only (the map only grows within a sweep) but **re-serialized whole-file per flush** by `dream-write.py memedit` (a temp file, fsync, then an atomic replace; never shell `>>`). A torn whole-file rewrite (agent stops mid-tool-call, real power-loss) may lose a record **suffix** — the last **complete** flush is the recoverable state.

**JSONL record grammar.** One record per working-map entry, in two forms:

- **Rename**: `{"rename":["<old fq target>","<new fq target>"]}`
- **Remove**: `{"remove":["<fq target>","<removal class>"]}`

Where `<fq target>` is the fully-qualified pointer target in the grammar of the preceding subsection — `user memory § <heading>` or `project memory (<project-path-key>) § <heading>`.

Example records:

```
{"rename":["user memory § Old heading text","user memory § New heading text"]}
{"remove":["project memory (~/work/api) § Deleted entry","pruned"]}
```

**Machine validator**: `verify-dream-journal.py` (`shared/skills/qdream/scripts/`, run with the venv python) — validates the two-form grammar, fully-qualified target prefixes, and the removal-class vocabulary. Keep the validator's `CLASSES` set in lockstep with the removal-class table at `§ The rename/removal working map` above (the canonical source). Unknown class → WARN.

**The journal-first triple.** Before performing **any** working-map-recording destructive mutation (a rename OR a removal): (1) record its working-map entry in `sweep/working-map.json`, (2) flush the **whole** working map to `memory/.dream-journal.jsonl`, (3) then perform the mutation. `dream-write.py memedit` performs the triple for every op it applies; no agent writes the map, the journal or a memory file itself. This is the one list of what the triple covers; every sweep file that runs a memory edit cites it. The triple fires before nine kinds of mutation: the **rename** (any `replace` that changes an entry's heading in a user-memory or manifest-named project memory file, a dedup merge and a salvage-rewrite among them) and the eight **removal** classes in the table above, the `pruned` delete of a budget `Move` included. It does not fire for an additive write, a salvage-rewrite that keeps the heading, an in-place `Verified` re-date, a node removal (class `node`, which has no working-map form), a node re-point, or an `Affirmed`-line drop.

**Lifecycle.** Created/extended by flushes during Phases 3 and 5. Cleared **only** on successful sweep completion, after `§ APP-STATE`'s state-write-and-validate succeeds. Full-sweep-only (lightweight never touches it). A **non-empty journal at sweep Orient is the crash signal**.

**Consumer** (`shared/AGENTS.md § Structure Requires a Consumer`, consolidation-sweep consumer): **`§ ORI-RECOVER`** — reads the journal every full sweep; acts when it is non-empty.

**Recovery semantics** live in one place, `sweep-recovery.md § ORI-RECOVER`: the target-file derivation (a targeted read that needs neither Phase 2 nor `§ ORI-READMEM`), the landed truth table, the working-map seed (which makes § ORI-RECOVER a writer of `old→new` pairs, `§ The rename/removal working map`), report at recovery time and never restore, fail-safe toward keep, idempotence, and the reused-heading residual.

**Carry-forward invariant.** `§ ORI-RECOVER` **initializes** the map (seeds recovered renames); each journal-first flush **re-serializes the whole map** (carrying seeded renames forward alongside new entries); Phase 3 `§ SYN-WRITE`, `§ SYN-STALE` and `§ SYN-PROMOTE`, and Phase 5 `§ APP-ADJUDICATE`, **append** to that same map; nothing clears the journal until `§ APP-STATE` succeeds. This makes nested-crash correct: a re-crash keeps un-recovered prior renames in the journal, so the next recovery processes them.

**OneDrive-sync note.** The journal is `.gitignore`d but syncs via OneDrive (the repo lives in a synced directory). Cross-machine sequential recovery is intended and safe (the landed truth table makes a partial-sync window fail-safe: an unsynced rename reads "didn't land" → no-op + surface). Concurrent full sweeps are unsupported (pre-existing limitation, not journal-specific).

#### The user gate

**An ungrounded node is surfaced to the user, never removed autonomously.** It has lost all its ground, but disposing of it is a **user** decision. Surface it in **Phase 4b** (`sweep-decide-apply.md § Phase 4b — Decisions`) showing **each pointer with its outcome** — and, where *this sweep* removed the target, the removal class read from the working map; otherwise `absent (removed by an earlier sweep or out of band)`. **Never guess a cause.** Offer the three branches with what each **means** stated inline, so the user can tell them apart at the point of decision:

> **`Keep node`** (durable — not asked again unless the node's `Support-set` changes) **/ `Remove node`** (deletes the node) **/ `Defer`** (ask again next sweep)**?**

The three branches are **distinct**, and **§ APP-ADJUDICATE** executes all three:

- **`Remove node`** → **delete the node** from `memory/HIGHER_ORDER.md`. This is the **only** path that removes a node.
- **`Keep node`** → a **durable affirmation**: stamp the node `**Affirmed**: <YYYY-MM-DD>` (`§ Higher-Order Tier` format). While the affirmation stands, the Phase-4b gate does **not** re-surface this node. **State the consequence honestly, in the prompt and in this rule: absent a change to its `Support-set`, `Keep node` suppresses the gate *indefinitely*.** That is what the user chose — *"this node earns its place despite its lost ground"* — and re-asking every sweep would collapse `Keep node` into `Defer` and tax the user for the same decision forever. Do **not** dress it up as a conditional that is re-checked against something it is not.
- **`Defer`** → **no-op**: no affirmation is written, and the node is **re-surfaced next sweep**. This is the genuine *"ask me again"* branch.

**No `episodic_ledger` record is touched on any branch.** The node is *not* routed through the reachable-and-contradicting provenance test (`§ Type Taxonomy`) that governs base entries — a node whose targets are all gone could never satisfy it — which is exactly why it gets its own user gate rather than an autonomous disposition.

**`Affirmed` staleness is event-driven — there is no date comparison.** Whenever the Phase-3 higher-order synthesis step **changes a node's `Support-set`** — adding a pointer, removing one, or re-pointing one — it **drops that node's `Affirmed` line** (`sweep-synthesize.md § Phase 3 — Synthesize`). That named step is the **single place** a `Support-set` can change, so the affirmation goes stale exactly when the facts it was made on change, with **no comparison procedure and no dates to compare**. An update that changes only the node's *content* (`Why` / `How to apply` / `Source` / `Verified`) **preserves** the `Affirmed` line verbatim.

A **returning** target needs no mechanism at all: it resolves `resolved` again, so the node stops being ungrounded and never reaches the gate. The affirmation becomes **moot**, not stale.

**Node removal is sweep-only and user-gated.** The provenance auto-demotion licence, which at read time only discounts the entry for the session and edits no file (`§ Type Taxonomy`: *"a `/qdream` sweep — **and any read-time verification**"*; `shared/AGENTS.md § Read-time behavior`), applies to base `memory/MEMORY.md` entries **only**. A session agent that loads `memory/HIGHER_ORDER.md` at session start **never removes a node**, whatever its `Source` anchor turns out to say. The single removal path for a node is the user-gated Phase-4b prompt above.

Re-pointing a renamed pointer, stamping (or dropping) an `Affirmed` date, and an approved node removal are all sweep writes within the Dream autonomy exception (`shared/AGENTS.md § Dream autonomy exception`). Of these, **only the approved node removal deletes anything — and it is user-gated.**

---

## Derived Utility & Pruning

The `/qdream` full-mode Size-check prune step (the Size check in `sweep-synthesize.md § Phase 3 — Synthesize`) ranks entries by a **derived utility signal**. No new rated field is stored — importance is *derived* from data already on each entry; the only new persisted field is the on-disk `Usage` counter. The signal's sole consumer is that prune step, so it is sanctioned structure under `shared/AGENTS.md § Structure Requires a Consumer` (the consolidation-sweep consumer type).

**Inputs** (each already present on the entry — no rating required):

- **Type** — `feedback` carries the highest staleness risk, `decision`/`pattern` lower (`§ Type Taxonomy`); higher staleness lowers utility.
- **Frequency** — accumulated observation count (the `**Frequency**` counter on `[improvement_signal]` sub-form entries); lower frequency lowers utility. Inert since signals left the prune set (*Prune-set exclusions* below); kept, with criterion (4), for ordering stability.
- **Verification pass/fail** — whether the entry's type-specific verification (`§ Type Taxonomy`) currently passes; a failing entry, or one whose provenance is *reachable-and-contradicting* (`§ Provenance re-open & auto-demotion`), has the lowest utility.
- **`Usage`** — the reference counter (`§ Cross-type optional metadata`); `0` / lowest means unreferenced, lowering utility.
- **`Outcome`** — `recurred` means the recorded lesson did not prevent the friction from returning (lowers utility); `not-recurred` means it held (raises utility).

**Prune order** (ascending utility, lowest pruned first): (1) verification-failed / reachable-and-contradicting → (2) `Outcome: recurred` → (3) unreferenced (`Usage` `0` and unseen in recent plans/sessions) → (4) weak `Frequency` (inert: no prune candidate carries it) → (5) oldest `Verified` (age tiebreaker; `feedback` breaks ties toward pruning ahead of `decision`/`pattern`; and at **equal age**, an entry verified by `sweep`/`session` prunes ahead of one verified by a **`human:`** actor — an abstraction never outranks the person who confirmed it, mirroring the read-time `§ Authority hierarchy`. An **absent** actor annotation is neutral here, ranking with `sweep`/`session` rather than below it). This is the value-aware replacement for the former age-only "verification-failed > unreferenced > oldest Verified" order. **This section is the sole owner and full definition of the prune order**; `§ Session-start memory context budget` cites it for both scopes, and `shared/AGENTS.md` points there. (`sweep-synthesize.md`'s Phase-3 Size check *cites* this section rather than restating the order. Two Kiro overlays restate parts of it for the weak model and must be synced on any change: `providers/kiro/skills/qdream/sweep-synthesize.OVERLAY.md` (the Size-check corrections under *Utility pruning & rejected lessons*) and `providers/kiro/skills/qdream/memory-rules.OVERLAY.md` (the merge grid's `Usage` and `Outcome` rows).)

**Rediscovery cost breaks near-ties.** When two entries rank adjacently, weigh what each cost to learn: an entry recording knowledge that was expensive to discover (long exploration, painful debugging — usually visible in its `Why`/`Source`) outranks one restating a cheaply re-derivable fact. No field stores this; judge it at prune time.

**Autonomous, within budget.** `dream-write.py apply-all` removes only the amount over budget, lowest utility first: failed verification goes by `sweep-synthesize.md § SYN-STALE`, then `Outcome: recurred`, then lowest `Usage`, then oldest `Verified`. Budgets: `MEMORY_BUDGET_WORDS` over the budgeted user pair, `ENTRY_PIN` entries in a project or topic file. A `human:` entry is never selected. Each removal is journalled, named in the Report and recoverable from git.

**Expiry fields are not prune inputs.** `Stale-after` and `Stale-when` (`§ Cross-type optional metadata`) contribute **nothing** to this order — a fired expiry never lowers an entry's utility and never selects it for pruning. Firing routes the entry to *verification*, and only a verification **failure** (criterion 1) can lower its rank. Treating an expiry as a prune signal would let the Size check delete an entry the sweep has not actually checked, which is the failure mode criterion 1 exists to prevent.

**Prune-set exclusions — five populations** (this list is the single source; `sweep-synthesize.md § Phase 3 — Synthesize § SYN-WRITE`'s Size check and the Kiro overlays cite it). The first four are excluded from both the entry count and the prune set:

- **Any entry carrying a non-terminal `Governance-conflict` record** (`rule-update-pending`/`deferred`, `§ Governance-conflict adjudication`) — it holds an unresolved user adjudication, and pruning it would permanently suppress the conflict.
- **Any `human:`-attested entry** (it routes to the user),
- **any entry Task 4 flagged this run as a `subsumed_entries` candidate**, and
- **any entry Task 4 flagged this run as a `stale_entries` candidate** (`sweep-synthesize.md § SYN-RECONCILE`). At Size-check time only candidates exist, not dispositions, and their disposing gates (the Phase-4b `Remove / Keep / Defer`, or the gated path in `§ SYN-STALE`) run strictly later. Excluding a candidate from the **count** stops it forcing a lossy prune of a *different* entry; excluding it from the **prune set** stops the prune deleting the candidate itself ahead of its user gate. A count-only exclusion would leave it autonomously selectable. ("Dispose before you prune" is impossible for the same ordering reason, so exclusion, not reordering, is the mechanism.)

The fifth is always excluded from the prune set; whether it counts depends on the file:

- **Every `[improvement_signal]` entry**, in whichever file it lives (`§ [improvement_signal] sub-form`). Nothing removes a signal outside an `Apply` at `sweep-decide-apply.md § APP-ADJUDICATE` except the stale-singleton expiry (`expired_signal`, at `sweep-synthesize.md § SYN-PROMOTE`), and a prune would delete its accumulated `Frequency`. It is excluded from the entry count everywhere, so signals never push a verified entry out; `memory/topics/improvement-signals.md` is never pruned by the budget.

**Graceful degradation**: any input absent on an entry is treated as its neutral value, so the order is well-defined on partial data. The `Outcome` input is written by the `/qdream` **Outcome tagging** pass (`sweep-synthesize.md § Phase 3 — Synthesize`), which grades a prior-run edit as recurred/not-recurred; an entry with no `Outcome` tag yet — the common case, until a later sweep has followed up the applied edit — contributes neutrally on criterion (2), so the order degrades gracefully to the remaining signals. This instantiates a general invariant: **a missing signal is neutral, never negative** — an advisory signal (usage, outcome, groundedness) discounts an entry only when present and adverse, and an entry that predates a signal's introduction is never penalized for lacking it.

**`Usage` bump rule**: a sweep increments an entry's `Usage` by `1` — **at most once per entry per sweep** — when it finds the entry was **relied on** this run: the Phase-3 dedup check merged a new observation into it, or the sweep found it referenced in an analyzed session or a recent plan. **Plan feeder**: a new archived plan's `> **Memory relied on**:` header line (written by `/qdev` Step 7, finalized by `/qclose` Step 3; the manifest's `new_plans[].memory_relied_on`) bumps an entry only when one of its headings matches exactly one entry heading, by the deterministic match in `sweep-synthesize.md § Phase 3 — Synthesize § SYN-WRITE`. A plan header counts as a reference only through this feeder, so a heading it leaves unresolved bumps nothing. An entry the sweep never touched is not bumped. `Usage` is evidence shown to the user, never a gate on its own. This counter is the "unreferenced" signal in the prune order above; on merge, `Usage` counters are **summed** per `§ Merge Strategy`.

---

## Suspect memory entries

A **suspect memory entry** is an entry that `shared/skills/qdream/scripts/dream-manifest.py` flagged for a full re-verification. The flags are deterministic. The script reads memory files, project trees, session records, harness logs and `git` history. It never runs a tool that memory text names.

| Flag | Set when |
|---|---|
| `stale_after_passed` | the entry's `Stale-after` date has passed |
| `cited_paths_missing`, `cited_slugs_missing` | a cited path or plan slug was not found |
| `cited_path_changed` | a file cited on the entry's `Source` line (its anchor) is tracked in `git` and has a commit dated after the entry's `Verified` date. A path named only in `Why` or `How to apply` is not checked: an edit to a file the prose merely mentions is noise. `cited_paths_missing` still reads the whole entry. Day granularity: a change on the `Verified` day itself is not seen. An entry without a valid `Verified` date is not checked, and a shallow clone is skipped |
| `cited_commit_missing` | a backticked commit hash (7 to 40 lowercase hex characters, at least one a letter) is in no known repository |
| `stale_when_fired` | a version-shaped `Stale-when` fired (below) |

An entry with any of these flags is a suspect. Two other flags never make one. `governance_conflict_open`: an open adjudication says nothing about whether the entry changed. `stale_when_unknown`: informational, see below. Each side-file entry carries `suspect: true|false`, and the manifest index counts suspects per memory file. Lookup failures (`git` unavailable, a shallow clone, an invalid `Verified` date, a near-miss `Stale-when` line) fail open: no flag, and a line in the manifest's top-level `errors[]`.

**A suspect is never evidence of staleness; it only selects the entry for a full check.** The full check is the entry's type-specific verification rule (`§ Type Taxonomy`), run even where a cheap skip would otherwise apply.
- When it passes, the entry is verified and not reported stale. Re-date `Verified` with actor `sweep`, plus the method the check actually used if one was returned. **Never overwrite `human:`**: an entry whose `Verified` carries a `human:` actor keeps its `Verified` line untouched; it stays a suspect, and its file's normal passes give it the extra check (user decision 2026-10-06). This bullet covers flag-forced re-dates (a manifest expiry flag, `stale_after_passed` or `stale_when_fired`, counts as expiry-forced, not flag-forced). A passing expiry-forced check on such an entry is not re-dated and its fired field is not cleared by the sweep: in a full sweep it goes to the user at `sweep-decide-apply.md § DEC-GATE`, who can re-date it with `human:<id>` or `sweep` and remove the fired field, or defer it unchanged (`§ Cross-type optional metadata`).
- When it fails, the failing check is the evidence, never the flag.
- Only the three trigger flags (`TRIGGER_FLAGS`) dispatch a quiet memory file: `stale_after_passed` and `stale_when_fired` (user decision 2026-10-06), and `governance_conflict_open`, which dispatches without making the entry a suspect. Every other suspect flag is an input to a dispatched agent only (`sweep-orient.md § ORI-DISPATCH`).

**Version-shaped `Stale-when`.** `**Stale-when**: <tool> version > <x.y[.z]>` is the one `Stale-when` form the script evaluates. Write the version the entry was verified on.
- `<tool>` must be `claude-code` or `kiro-cli`, the allowlist `STALE_WHEN_TOOLS`.
- The current version is read from that harness's newest session record (`claude-code`) or harness log (`kiro-cli`), never by running the tool.
- It is compared at the precision written: `> 2.18` fires on 2.19, not on 2.18.4.
- A tool outside the allowlist, or a version neither the session record nor the harness log carries, gives `stale_when_unknown`. **An unreadable condition is not fired**: it forces nothing, the entry is not a suspect on that account, and it gets its ordinary Task 4 check (user decision 2026-10-06).
- A Kiro session record holds no CLI version (measured 2026-10-06 and 2026-10-09). The `kiro-cli` version is the adjacent `"origin":"KIRO_CLI","version":"x.y.z"` pair in the newest `~/.kiro/logs/<timestamp>/kiro.log` that holds one (measured 2026-10-09 on Windows, kiro-cli 2.29.0; other platforms unmeasured). When no kept log is a CLI run, the version is unknown and the condition is `stale_when_unknown`. A fired `kiro-cli` condition gets its full check, and the fired field is cleared (except a `human:` entry, above; `§ Cross-type optional metadata`).
- Any other `Stale-when` text sets no flag and stays model-evaluated (`§ Cross-type optional metadata`).

---

## Date References

All date references in memory entry prose must use absolute format (YYYY-MM-DD). Never use relative references ("yesterday", "last week", "this session") — they become uninterpretable after session context is lost. Applies to `Verified`, `Source`, and any dates in `Why`/`How to apply`. Plan-slug identifiers (e.g. `260519` in a `Source` filename reference) are not date prose and are exempt.

**Record dating & day-granularity tie rules (sweep bookkeeping)**: an `evidence_quote` or observation has no intrinsic date — it carries the date of the source it was drawn from (a session's metadata timestamp date, or an archived plan's filename date prefix). All sweep bookkeeping comparisons — `rejected_lessons` record `date`s and the "dated before this sweep" consult boundary, the re-surfacing override's "dated after", `outcome_tags` `applied`/`checked` — operate at `YYYY-MM-DD` day granularity. Same-day ties resolve toward adjudication, not suppression: a `rejected_lessons` record dated the **same day** as the current sweep is treated as same-sweep and is NOT consulted (the proposal proceeds to the Cross-validation gate instead of being silently suppressed); conversely, for the re-surfacing override, a quote dated the same day as the suppression record does NOT count as "after" (fresh evidence must genuinely post-date the suppression).

---

## Exclusion List

Hard ban -- never persist these as memory entries. Each ban names where the information **should** go instead: rejecting a memory write is a *routing* decision, not a discard. A ban with no destination silently drops information the user may still need.

| Do not persist | Route to |
|---|---|
| Temporary or in-progress state (current branch, mid-task context, WIP decisions, workflow state that must survive context compaction) | The project file (`## Progress`), the task list, or a `/qhandoff` export |
| A task-scoped instruction ("put the table first in this report"), unless the user says it applies beyond this task. A correction of your work is not one (the speculative-conclusions row) | Nowhere |
| Debugging history: the attempts behind a fix, a diagnosis that expires with it | The fix's commit or plan. A durable cause class may still be memory |
| Personal or sensitive data not needed for future work (health, political, religious, sexual), and anything the user asked not to save | Nowhere, and exempt from the ask-what-was-non-obvious rule below |
| An approach change made mid-plan — the pivot feels like a durable `decision`, but it belongs to the plan | The project file — **update the plan**, do not also write a memory entry (the plan gets archived; a memory copy would keep loading at session start and silently desynchronize) |
| Information already in governance files (AGENTS.md, SKILL.md, project docs) | Nowhere — it is already durable |
| Per-tool-event automation ("always run X after every edit to Y") | Harness config (hooks / provider settings). Memory is advisory context that is **never executed** (`shared/AGENTS.md § Read-time behavior`), so an automation request saved as memory is correctly refused at read time and the user's automation silently never runs |
| Speculative conclusions from a single **inference** — wait for confirmation. (An explicit user correction is *direct testimony*, not a speculative conclusion: save it on the **first** occurrence — do not make the user repeat themselves) | Nowhere yet — wait |
| Session-specific tool output (error messages, stack traces, command output) | Nowhere |
| Secrets, credentials, tokens, or paths containing them | Nowhere — never persist |
| Opinions not confirmed by the user ("I think X might be better") | Nowhere |
| Restatements of documentation (if it's in the README, don't memory it) | The docs themselves, if they are wrong |
| Facts self-evident from reading the relevant source file (config field names, CLI flags, function signatures, architectural decisions visible in code structure) | Nowhere — the code is the source |
| A value a deterministic guard or script already owns (a budget, a threshold, a version pin, a computed path) | The guard — record **the lookup**, not the number ("read `verify-mass.py`'s `BUDGETS` table", not "the ceiling is 7,100"). A hard-coded copy goes stale silently on the first change, and a session-loaded file is where that costs most: the entry keeps asserting a number nothing re-checks. |

**Sanitize quoted material before it persists.** When an entry quotes tool output or an error message, strip secrets AND volatile identifiers — tokens, UUIDs, run ids, temp paths, ephemeral ports — replacing them with `[redacted]`/`[uuid]`-style placeholders. These placeholders are the only permitted alteration of a quote's content (its shape may still be escaped, below), and a redacted quote is matched by grep on its unredacted neighbours. Secrets must never reach a durable file; volatile values pin the lesson to one occurrence and defeat dedup and grep-based re-verification. Prefer the metadata fields for dates; any date that must appear in prose uses the absolute format per `§ Date References`.

**Escape structural markers in a quoted span.** The rule above covers *what the content is*; this one covers *what shape it has*. `Evidence-quote` and `Governance-conflict-quote` are verbatim spans, and this playbook's governance quotes governance — so a legitimate span can contain text that **parses as memory structure**: a `###` entry heading, a `**Field**:` bold prefix the sweep consumes, or `## Declined`. Written through unescaped, the next sweep reads it as a real heading, a real field, or a real declination record. **Escape, never reject**: neutralize the offending line so it no longer parses (prefix the marker, e.g. `\###`) and note the escape in the proposal. Rejecting the entry instead would make the most important quotes — the ones *about* the format — unstorable, which is the wrong trade in a repo whose governance documents its own memory format.

**Report the pattern, never the match.** When a write is refused because the content matched a credential shape (the secrets row above), name the **pattern** that matched — "refused: AWS access-key pattern" — never the matched text. The refusal is narrated into a transcript, and transcripts are themselves a memory source (`providers/*/steering/memory-sources.md`), so a refusal that quotes the secret persists it through the very act of declining to persist it.

**When the user explicitly asks you to remember something on this list**: do not silently refuse, and do not save it anyway. Ask what was **non-obvious** about it and save *that* instead. The exclusion means they named the wrong thing to persist, not that nothing durable is there.

---

## Proposal Template

Before proposing, run the dedup check (below). Write `human:<id>` only after the user's own Save or approved Edit; otherwise `sweep`, `session` or none. Then present:

```
**Memory proposal** (`<type>` -> `<target: project | user>`)

<heading: the situation it applies to, within 200 characters>
**Why**: <why>
**How to apply**: <action>
**Source**: <source> | **Verified**: <YYYY-MM-DD>[ (<actor>[, <method>])]

Related entry checked: <yes -- no conflict | yes -- updates existing entry "X" | no existing entries>

Save / Skip / Edit?
```

**On `Skip` — the consequence, scoped to a memory proposal.** A Skip of this (memory) proposal is **recorded as a declination**: append a `## Declined` row (`§ Memory File Format`) to the memory file `§ Resolution contract` returns — appending creates that file when it does not exist, so resolve before you append — and do **not** re-propose the same subject for the 60-day declination window. A **governance-rule / `[improvement_signal]`** proposal Skip is a *different* store — the sweep writes a `rejected_lessons` record (`§ State File Format`), not a `## Declined` row — so no Skip ever writes both (the suppression split). **An examination gap is not a rejection**: record a declination **only** for a proposal the user was actually **shown and explicitly Skipped** — never an exclusion-check or self-test self-rejection (the proposal was never surfaced), and never under bulk triage of unverified items.

---

## Dedup Check Procedure

Before proposing a new memory entry:

**Declination consult (agent-initiated proposals only).** First, check the proposal's subject against the `## Declined` section (`§ Memory File Format`). If a **live** (un-expired, within the 60-day window) declination matches — the user already Skipped a semantically equivalent proposal — do **not** re-propose it. **An explicit user instruction is never suppressed**: this consult gates **only agent-initiated** proposals, so a user's own restatement or explicit "remember this" (`§ Restated-context trigger`) never reaches it, and honouring the user requires **no row deletion** (sessions never delete rows — the row simply stops mattering once its subject becomes a live entry, and no script prunes it). **The in-session re-surfacing predicate, stated positively** (in-session agents carry no structured `evidence_quote`, so it cannot depend on one): an agent may re-propose a declined item before it expires when the user restates the fact themselves — any `§ Restated-context trigger` marker. Otherwise the declination holds until it expires. **The consult suppresses only a *new* agent-initiated proposal of a declined subject — never an update or merge into an entry already live on that subject** (a live entry and a moot declination row for the same subject can coexist: no script prunes the row, and the live entry makes it moot, above).

1. Scan the target memory file for entries with a similar heading or overlapping content. Dedup identity is **(type, normalized subject)**: compare headings case-, punctuation-, and separator-insensitively, and never *merge* across type boundaries — a `feedback` "prefer X" and a `pattern` "prefer X" are distinct records with different verification rules. (The type boundary scopes merge identity only; contradiction flagging in step 3 stays cross-type.) **Read the file itself, not its heading index** (`shared/AGENTS.md § Read-time behavior`). If you cannot read all of it, propose no new entry and say what you could not read; editing an entry you read in full stays allowed. In a sweep this binds the Synthesize phase agent.
2. If a related entry exists: propose an **update** to the existing entry instead of a new one. Same facts make a duplicate; an entry lacking a fact the new one carries is related, not duplicate: merge into one keeping both facts, or add. **A dedup hit strengthens the entry — never silently drop the observation**: the merge appends the new `Source` (`§ Merge Strategy`), and the sweep credits the reliance via the `Usage` bump (`§ Derived Utility & Pruning`); re-observation is the frequency evidence the derived-utility ranking runs on.
3. If the new information **contradicts** an existing entry: flag the conflict to the user and let them decide which to keep.
4. **Cross-tier check** (the scan is not single-file): also check the **higher-authority** tiers on the same topic — governance > user memory > higher-order tier > project memory (`shared/AGENTS.md § Authority hierarchy`). If the new entry **restates** a higher tier, do not save it — the higher tier already carries it. On a **contradiction, split by the object of the disagreement**:
   - **Contradicts governance** (AGENTS.md / SKILL.md): do **not** save it — a memory entry may not silently override governance. **Escalate** with an explicit action set — `record with an explicit override note` / `propose a governance update` / `drop` — via the `Save / Skip / Edit?` proposal idiom (the `/qdream` sweep surfaces it in Phase 4b instead). A user `drop` **appends a canonical heading-keyed `## Declined` row**: `- "<dropped proposal heading>" — declined <YYYY-MM-DD> (dropped: contradicts <file § section>)` — so the dedup gate's declination consult suppresses re-proposal of the same subject. The `record with an explicit override note` action is reachable **only via this user-approved escalation, never autonomously** — no agent may write the override note without the user having chosen that action here. A bare do-not-write ban is itself forbidden here: *a ban with no destination silently drops information the user may still need* (`§ Exclusion List`). **Advisory carve-out**: a governance line that **explicitly disclaims being a hard rule** — an *advisory* line pre-authorizing deviation, e.g. `§ Session-start memory context budget` (*"advisory, not a hard cap"*) — is **not** a contradiction that triggers this escalate-don't-save branch; follow that line's own carve-out.
   - **Contradicts a higher *memory* tier** (user memory > higher-order > project memory — **not** governance): you **may** save it **directly — by you, without escalation** — with the override **noted explicitly** in the `Why`, so a later sweep can adjudicate a recorded disagreement rather than guess at a silent one.
   - **Contradicts both at once** (a governance rule **and** a higher memory tier): the **governance branch governs** — do **not** save it; escalate. This follows `shared/AGENTS.md § Authority hierarchy` ("governance wins") and is what the memory-tier branch's "**not** governance" scoping already implies.
5. **Write at the narrowest scope where the claim is true**, and never restate it upward. The authority hierarchy is the *read-time* rule for resolving a cross-tier conflict; this is the *write-time* rule for not creating one. Not manufacturing a contradiction beats resolving it well.

### Native-memory harvest dedup

Scope: the `/qdream` sweep's harvest of Claude Code's native project memory
(`sweep-gather.md § GAT-NATIVE`). These gates run **before** the general procedure above,
because a harvested entry arrives in a *different format* from the store's — so heading similarity, the
signal step 1 leans on, is much weaker here than usual. Gate 0 and gate 1 below are a separate list,
distinct from the five write-time gates of `shared/AGENTS.md § Write-time quality gates`.

**Gate 0 — already harvested (mechanical; runs first).** If any existing entry's `Source` names this
native file **or** its legacy native ID — the translation writes both
(`providers/claude/steering/memory-sources.md § Native project memory`) — the native entry is already in
the store. Emit nothing. Gate 0 is also what keeps the harvest quiet across sweeps: every branch below
ends with the native `Source` recorded on a live entry, so from the next sweep on this gate answers
first and the pair is never re-raised.

> **What "names this native file" means, because the two sides are written differently.** A recorded
> `Source` holds a **workspace-relative** path (`memory/<file>.md`) while the live file is read from an
> absolute one (`~/.claude/projects/<slug>/memory/<file>.md`). Match on the **basename** — `<file>.md`,
> the last path segment — and nothing longer. Do not normalize through `§ Path normalization`: that rule
> normalizes *workspace* paths for a store identity and neither of these is a workspace path. The legacy-native-ID
> disjunct is the **stronger** test (it matches the native `name:` frontmatter exactly), so where the two
> disagree, the ID decides. A basename collision across two projects cannot reach this gate, because the
> harvest is already scoped to one project's memory directory by the time it runs.

**Gate 1 — translation-equivalence (judgement).** Otherwise, merge into an existing entry **only** when
the two are the same fact in two formats: same claim, same scope, and **no fact carried by one that the
other lacks**. Merge per `§ Merge Strategy`, appending the native `Source`.

**Otherwise — keep both and surface. Never merge on doubt.** Emit the harvested entry as an ordinary
`memory_proposals` item, exactly as `§ GAT-NATIVE` does for every other translated entry, and surface the
near-duplicate pair at the Phase-4b gate (`sweep-decide-apply.md § Phase 4b — Decisions § DEC-GATE`).
**The proposal is written by Phase 5, after adjudication** —
the harvest never writes directly, so "keep both" is the default the gate confirms rather than an
already-committed state.

> **When the two entries *contradict* rather than merely differ, say so in the prompt and widen the
> choice.** The general procedure's step 3 has a contradiction branch; these gates run ahead of it, so
> the branch has to be restated here or it is lost. A near-duplicate whose difference is a genuine
> disagreement — the same condition given opposite handling by each side — gets
> `Merge / Keep both / Keep existing / Keep harvested?` instead of the two-way prompt, and the
> `Difference:` line states the disagreement first, before any additive facts. Reason: on a real
> contradiction, "keep both" leaves the store holding two rules that cannot both be followed, which is a
> worse resting state than either single answer, and the two-way prompt makes it the only reachable one.
**The asymmetry is the whole point**: a false-positive merge is a *permanent silent omission* — every later sweep dedups identically,
so a fact folded away never returns and nothing records that it ever existed. A false-negative leaves a
visible duplicate the user disposes of in one turn. This is the direction `§ The user gate` already
takes for an ungrounded node ("surfaced to the user, never removed autonomously").

**Regression pair — replay it before changing any rule above.**
`shared/skills/qdream/scripts/fixtures/harvest-dedup/README.md` holds two fixtures and the cold-read
procedure for running them. One must merge, one must not; neither alone discriminates a correct harvest
from a stuck one.

### Merge Strategy

When a dedup check identifies a related existing entry, merge into it rather than creating a duplicate: prefer the more precise `Why`/`heading`, append the new `Source` after the old one with ` + `, and re-date `Verified` only when the merge included a real verification check (merging alone is not verification). For pattern types, append new detail when it adds information; otherwise keep the existing entry. For the cross-type optional metadata fields: keep the `Evidence-quote` that entails the surviving claim (do not concatenate quotes); **sum** the `Usage` counters; keep the most recent `Outcome` by its date (a later recurred/not-recurred observation supersedes an earlier one); **union `Governance-conflict` record-lists by key** (key = (contradicted/absorbing `<file § section>`, whitespace-normalized span)) — same-key records from both entries collapse to the **most-recent by `adjudicated <date>`** (same-day tie → the **non-terminal** state wins, `rule-update-pending`/`deferred` over `keep-entry`/`subsumption-kept` (both terminal-like), fail-safe: keep the conflict live); different keys **coexist as separate records** on the merged entry (this is **resolution**, not suppression — every record remains individually re-raiseable per `§ Governance-conflict adjudication`); and **union** the `Support-set` pointers, de-duplicating. Rewrite only the statements the new observation changes; an entry grows by durable facts, never narrative.

For the `Verified` annotation (`§ Memory File Format`): the surviving `Verified` carries **its own** actor and method — the annotation travels with the date it describes, never recombined across entries. A merge that is not itself a verification keeps the more recent date with that entry's annotation; a merge that *did* include a real verification check re-dates to today and is annotated with the merging actor and method **`merge`** only when no stronger check was run.

**Accepted residual — a `human:` actor is not sticky.** Because the annotation follows the surviving date, a later `sweep` verification supersedes an older `human:` one, and the entry loses the demotion protection of the human-attestation carve-out (`§ Type Taxonomy`). This is **accepted, not overlooked**: the alternatives were to pin the actor independently of its date (producing a date/actor pair that describes no single event) or to carry `Verified` as an append-only event list (a materially larger grammar, deliberately out of scope). Two durable protections remain unaffected and are the right tool where permanence matters: a **non-terminal `Governance-conflict` record** (excluded from every autonomous-removal path) and, at the higher-order tier, **`Affirmed`**. **Reopen trigger**: if a user attestation is observed being lost this way in practice, promote the actor to its own field rather than widening this rule.

For the expiry fields (`§ Cross-type optional metadata`): keep the **earlier** `Stale-after` of the two — it fires sooner, and more checking is the fail-safe direction; keep whichever `Stale-when` still describes the surviving claim (both, if both remain applicable). Neither field is dropped merely because the other entry lacked it. (The kiro deployment carries an expanded field-by-field grid via its aux overlay.)


---

## State File Format

The `/qdream` skill tracks cross-project state in `memory/.dream-state.json` (config repo root). Created automatically on first `/qdream` full run.

**Machine validator**: `shared/skills/qdream/scripts/verify-dream-state.py` (run with the venv python) deterministically validates a state file against this section — declared-version key sets (a v1 file carrying v2 or v3 sections, or a v2 file carrying v3 sections, fails as half-migrated), element shapes, `reason`/`outcome`/`kind` vocabularies, routing roles, counts, `YYYY-MM-DD` date fields — and, for v2 and later, that `episodic_ledger` is append-only: its baseline's records must be an exact prefix of it (element-wise JSON equality, key order ignored), so a dropped, rewritten or reordered record FAILs even when padding restores the count. On that FAIL, restore the records from `git show HEAD:memory/.dream-state.json`; never pad or edit the ledger to pass. The baseline is the version committed at `HEAD` (`git show HEAD:memory/.dream-state.json`) when the validated file is the repo's `memory/.dream-state.json`, or the file passed as `--ledger-baseline`. With neither (no git, file not committed, any other path) that one check prints a `note: episodic_ledger shrink check skipped (<reason>)` line and does not count. Only `dream-write.py state` writes the state file, and it runs this validator on its temp file before swapping it in, so a FAIL leaves the live file untouched; the sweep also runs it on the live file after each state write. It is the deterministic-tool consumer for these shapes (`shared/AGENTS.md § Structure Requires a Consumer`); keep the script and its fixtures (`shared/skills/qdream/scripts/fixtures/dream-state/`, expected verdicts in its `expected.tsv`) in lockstep with this section when the schema changes.

Schema (version 3):

```json
{
  "schema_version": 3,
  "last_run": "2026-06-03T12:00:00-05:00",
  "projects": {
    "/path/to/project": { "last_analyzed": "2026-06-03T12:00:00-05:00" }
  },
  "rejected_lessons": [],
  "outcome_tags": [],
  "episodic_ledger": [],
  "cost_records": [],
  "model_routing": {},
  "deferred_sessions": {},
  "quiet_sweeps": {}
}
```

| Field | Type | Description |
|---|---|---|
| schema_version | integer | Currently `3`. Increment on schema changes. |
| last_run | string (ISO-8601) | The manifest's `snapshot_at` of the most recent completed full sweep (not the time it finished). |
| projects | object | Map of project path (string) to per-project metadata. |
| projects[path].last_analyzed | string (ISO-8601) | The snapshot time up to which this project's sessions have been read: the `snapshot_at` of the last sweep that covered it, or, for a new project dispatched but not covered, the baseline its next read starts from (`sweep-decide-apply.md § APP-STATE`). Not advanced on inaccessible, failed or truncated projects. |
| rejected_lessons | array | Suppression list: proposals refuted by the cross-validation verifier or user-Skipped, consulted at the next sweep's write/dedup gate so the same shallow reflection does not recur. Each element: `{ "target": "<file § section, a governance file path (an in-session signal Skip writes its `target_file`), or entry heading the proposal addressed>", "signal": "<one-line description>", "reason": "refuted|skipped", "date": "YYYY-MM-DD" }`. The consult matches on `target` + a semantically equivalent `signal`, so both are stored. **Only explicit judgments are recorded**: a `refuted` record requires that the Cross-validation verifier actually examined the item and returned `refuted` with a refutation reason — an item *default-refuted* because the verifier returned no verdict (truncation, partial coverage) is withheld from writing that run but never recorded here; a `skipped` record requires the user to have Skipped a **gate-verified** (confirmed/plausible) **governance-rule or `[improvement_signal]`** proposal — a **memory-proposal** Skip is recorded as a `## Declined` row (`§ Memory File Format`, the suppression split), **not** here — and a Skip of an unverified, verifier-failure-downgraded proposal is not recorded (an examination gap is not a rejection). A third admission path, for `skipped` only: the user's explicit in-session Skip of a plan-less `[improvement_signal]` proposal (`§ Plan-less governance capture`), which the sweep that reads the session finds in the transcript. The sub-agent's `user_skipped` item quotes the proposal heading and the Skip turn verbatim, and the record's `signal` is that heading. It is not gate-verified, because it records a user decision rather than a claim, and it gets the same 60-day window and the same re-surfacing override. **Bounded retention — suppression is not permanent**: on each full sweep (at persist time), drop a `skipped` record whose `date` is older than **60 days** and a `refuted` record older than **180 days** (`refuted` carries verifier evidence, so it suppresses longer). An expired lesson is merely eligible to be re-proposed and re-adjudicated by the gate — nothing is force-re-learned; this also bounds array growth. **Re-surfacing override — the path back before expiry**: the consult does **not** suppress a matching proposal that re-surfaces with **fresh grounded evidence** — a verbatim `evidence_quote` dated *after* the record's `date`, across **2+ distinct** post-suppression observations. On such re-surfacing it drops the now-stale record and lets the proposal proceed to the Cross-validation gate for re-adjudication, so a lesson that genuinely became true is re-learnable rather than silently locked out. **A later user `Save` also overrides a `skipped` record**, both in the sweep that would write it (a `saved_in_session` item from a session later than the Skip, `sweep-synthesize.md § SYN-PROMOTE`) and afterwards: when the user Saves the same signal in-session on or after the record's `date` (the row's in-session token is dated on or after it), the sweep treats the record as cleared and drops it, because the user's newer decision wins. Defaults to `[]`. |
| outcome_tags | array | Outcome records for applied governance/memory edits, written on each full sweep. Each element: `{ "target": "<file § section, or entry heading>", "applied": "YYYY-MM-DD", "outcome": "recurred|not-recurred", "checked": "YYYY-MM-DD" }`. Keyed by applied-date + target; feeds derived utility and the retirement pass. Defaults to `[]`. |
| episodic_ledger | array | Append-only episodic replay store: compact what/where/when/outcome records the sweep induces rules from — the replay substrate the Phase-3 higher-order synthesis step (`sweep-synthesize.md § Phase 3 — Synthesize`) appends to on each full sweep and reads to induce higher-order nodes. Each element: `{ "what": "<one-line>", "where": "<session-id, plan-slug, or — for a governance-conflict adjudication record — the entry heading + contradicted file § section>", "when": "YYYY-MM-DD", "outcome": "<short outcome>", "support_set": ["<pointer>", "..."] }`. The `support_set` pointers here are **history, not live references**: they are **exempt from reconciliation** — never resolved, never re-pointed, never rewritten — and a stale one is not a defect (`§ Higher-Order Tier`, "Support-set referential integrity", the two-population split). Append-only, so it never rewrites history. Consumers read a **bounded window**, not the full history: the higher-order synthesis step reads this sweep's appends plus the most recent 50 prior records (by `when`), so unbounded on-disk growth never enters sweep context; on-disk pruning/windowing of stale episodes is deferred to the memory-decay ROADMAP item. **Dependency to honour when that item is picked up**: `memory/HIGHER_ORDER.md` node pointers name ledger records **positionally** (`episodic_ledger #<N>`, `§ Higher-Order Tier`), and a positional pointer into a pruned array resolves *successfully to the wrong record* — the worst failure mode there is. Any pruning/windowing implementation must therefore **migrate those node pointers (or freeze the index) as part of the same change**. Defaults to `[]`. |
| cost_records | array | Per-sweep cost record, with `weighted_tokens` (API price ratios in `dream-manifest.py` `USAGE_WEIGHTS`, relative cost rather than a quota percentage; a normal pass aims for at most 28M, about half a 5-hour window, and the sweep reports this figure without stopping on it), at most 20, in append order, newest last (past 20 the oldest `kind: sweep` record is dropped at persist time, never a `kind: baseline` one; the validator does not compare dates, append order is authoritative). `date` is the date the measured run happened. Each element: `{ "date": "YYYY-MM-DD", "kind": "sweep|baseline", "projects_analyzed": n, "sessions_read": n, "bytes_read": n, "agents": { "<role>": n }, "models": { "<role>": "<model name>" }, "findings": { "surfaced": n, "kept": n, "dropped_by_stage": { "<stage>": n } }, "proposals": { "surfaced": n, "applied": n }, "tokens": n|null, "tokens_by_role": { "orchestrator": n, "task4": n, "verifier": n, "drafter": n, "other": n } }` — every `n` a non-negative integer; `findings.surfaced` counts memory proposals before any drop stage, `findings.kept` those written or merged, and `dropped_by_stage` lists every stage, zeros included, with `kept ≤ surfaced` and the stages summing to at most `surfaced − kept` (an escalated governance contradiction counts as kept when recorded with an override note and under `contradicts_governance` when dropped; the gap is user Skips, Defers and governance-update proposals; `sweep-decide-apply.md § APP-STATE`); `tokens_by_role` is optional, the `baseline --by-role` totals, all five role keys, summing to a non-null `tokens`; a legacy record without `drafter` (the four keys `orchestrator`, `task4`, `verifier`, `other`, written before the drafter role existed) is also accepted, and any other key set FAILs. The validator enforces the five stage keys (`already_known`, `not_durable`, `unsupported`, `suppressed`, `contradicts_governance`) and the two `findings` invariants only on a `kind: sweep` record carrying `tokens_by_role`, so records written before that field existed stay exempt; `tokens` is `null` where the provider records none (Kiro). A `kind: baseline` record may also hold `null` for `projects_analyzed`, `bytes_read`, `findings` and `proposals`, the fields its source did not measure; a `kind: sweep` record may not. `qmemory-eval.py` prints `n/a` for a null count. The baseline was measured to the first Phase 4b question and a `kind: sweep` record covers the whole sweep, so `qmemory-eval.py` labels its sweep-vs-baseline percentages "not like-for-like". v3. |
| model_routing | object | Dispatch model per provider, as the user last confirmed it: `{ "<provider>": { "task4": "<model>", "verifier": "<model>", "drafter": "<model>", "confirmed": "YYYY-MM-DD" } }` (`task4` is the per-project agent), or `{}` before the first confirmation. `drafter` is optional: a provider confirmed before the drafter role existed has none; when present it is a non-empty string. v3. |
| deferred_sessions | object | Watermarks for sessions still in progress at the manifest snapshot: `{ "<provider>:<session id>": { "project": "<project state key, else path>", "last_record": "<last record read>", "since": "YYYY-MM-DD" } }`, or `{}`. The next sweep reads such a session from after `last_record`; a deferred session beside read sessions does not block stamping its project, but a project whose sessions are all deferred is not stamped. v3. |
| quiet_sweeps | object | Quiet-project cadence counters: `{ "projects": { "<projects key>": n }, "user_memory": n }`, both keys optional, `{}` valid, each `n` a non-negative integer: the cadence counter (seeded per key so first passes spread over five sweeps; 0 after a `checked` Task 4 pass over the whole scope; set to 4 by a user Defer on a `subsumed`, `stale` or `stale-salvage` item; otherwise + 1 each sweep). A `projects` key need not be a key of `projects`: a project with a memory file is counted before it is first stamped. `dream-manifest.py` reads it (a missing or invalid value is seeded per key, an invalid one named in `errors[]`) and emits each scope's `quiet_sweeps` and `memory_pass`: `flagged` when an entry's `Stale-after` has passed, its `Stale-when` fired (`stale_when_fired`) or it carries a non-terminal `Governance-conflict` state, `periodic` at `n` ≥ 4, else null. A missing cited path or plan slug is emitted as an entry flag for a dispatched agent but does not set `flagged`. `sweep-decide-apply.md § APP-STATE` writes it. v3. |

**Read-only aggregating consumer**: `shared/skills/qdream/scripts/qmemory-eval.py` consumes `outcome_tags` (graded/ungraded split) and `episodic_ledger` (pointer resolution range) as read-only inputs; it writes nothing.

**Version history**: v1 carried `schema_version`, `last_run`, `projects` only. v2 adds `rejected_lessons`, `outcome_tags`, and `episodic_ledger`. v3 adds `cost_records`, `model_routing`, `deferred_sessions` and `quiet_sweeps`. Each upgrade is additive and in-place: existing sections are preserved unchanged, the new sections are added empty (`[]` for arrays, `{}` for objects), and no historical data is backfilled; a v1 file goes to v3 in one pass. v3 also redefines `last_run` and `last_analyzed` as manifest snapshot times (no shape change). v3 was redefined on 2026-09-25 without a version bump, when the sweep's classification cache and collector path were retired: the Task-4 `classification_cache` it first carried was removed and is now an unknown key, `quiet_sweeps` was added, the `collector` routing role was removed, and a `kind: baseline` cost record may hold nulls; the one v3 file then in existence (this repo's) was edited by hand in that change, so no migration exists. On 2026-10-08, also without a version bump, `cost_records` gained the optional `tokens_by_role` and the stage-key and `findings` checks it opts a record into; no record was rewritten. On 2026-10-14, again without a bump, `tokens_by_role` gained the `drafter` role and `model_routing` an optional `drafter`; four-key records and two-role providers stay valid, so none was rewritten. See `sweep-orient.md` § ORI-STATE for the migration and first-run-init logic.

---

## Dream Sub-agent Return Schema

Each per-project sub-agent returns a structured object to the orchestrator, used for cross-project synthesis, dedup, and governance proposal generation. **The schema itself is defined inline in `sweep-gather.md § Phase 2 — Gather (parallel sub-agents)`** — inlined there, not here, because a dispatched sub-agent cannot follow a citation. This reference copy carries no field the inline copy does not.

## Memory Lifecycle

Full detail for `shared/AGENTS.md § Memory Management > Lifecycle: promotion, bootstrap, and hygiene`, which keeps the operative summary resident and points here.

### Promotion path

- Feedback stable >7 days with no contradictions -> propose promotion to project AGENTS.md.
- User memory entry appearing in 2+ projects -> propose promotion to shared AGENTS.md.
- All promotions require explicit user approval.
- An entry with an unresolved negative outcome (`recurred`, or in-session harmful) is ineligible for promotion until re-validated.
- **Promotion _moves_ the entry; it does not copy it** — the source entry is removed once the governance edit lands (`/qdream` § APP-ADJUDICATE); a copy left in memory duplicates governance.
- Promotion converts advisory context into standing instruction, so it also requires a **`human:`** `Verified` actor — a `sweep`-only attestation is ineligible.
- **A third rung: governance prose → mechanically enforced check.** When a documented rule keeps being violated, more prose is not the fix — the rung it already failed at is prose. Propose a deterministic guard that fails on the violation (a `verify-*` check, a `CHECKS` row, a `qvalidate` check). Subject to `shared/AGENTS.md § Structure Requires a Consumer` and the same explicit user approval as any other promotion; the twin-script and fixture cost makes this a user decision, never an automatic escalation.

### Bootstrap

Lazy: create `memory/MEMORY.md` at first memory proposal, in the store `find-or-create` returns (`§ Resolution contract`, step 2). The store repo is git-tracked, so there is no tracking question; a folder where no store is created (step 3) keeps the file in place, and there ask the user whether to git-track it. `/qdream` full mode creates `memory/.dream-state.json` on first run.

### Singleton ledger

A signal or plausible lesson seen in one session is not memory yet. It is a row of `.dream-state.json` `singleton_ledger` (`target`, `gist`, `sessions`, `first_seen`, `last_seen`), loaded at no session start. Only `dream-manifest.py` `merge_singletons` counts rows: `dream-sweep.py singletons` during Synthesize, `state apply` when persisting. A row reaching `SINGLETON_PROMOTE_SESSIONS` distinct sessions re-enters `sweep-synthesize.md § SYN-PROMOTE`. A row unseen for `SINGLETON_EXPIRY_DAYS` is removed and counted in the Report's `Stages` line.

### Staleness nudge

Suggest running `/qdream` for consolidation on work volume, with a limit for quiet periods, so a pass stays small enough to launch (the cost target is in `§ State File Format`, `cost_records`):

- **Work volume**: `SWEEP_DUE_SESSIONS` new sessions across discovered projects (read the pin from `dream-manifest.py`), each counted from its own project's `last_analyzed` (a `history_only` stub and a session of a Claude Code scratchpad folder under the OS temp directory are not counted: the manifest still lists them and the sweep still reads them, but a bare `/resume` or a sub-agent probe is not work), **or** any project whose oldest unread transcript is within 7 days of the provider's deletion age (each provider's `memory-sources.md` states that age; a provider with none raises no flag), **or** `SWEEP_DUE_DAYS` since the last run with at least one new session. Do not count by hand: `dream-manifest.py count --state <config-repo>/memory/.dream-state.json --repo <config-repo>` (read-only, writes nothing) prints `sweep due: yes|no (N new sessions, K projects near deletion)` and a `memory budget:` line (`§ Session-start memory context budget`), and the `/qdream lightweight` report — so every `/qclose` — ends with both lines.

### Session-start memory context budget

Two rules, one per scope. Neither is grounds for an agent to refuse a proposal outside `/qdream`.

**The budgeted user pair — a word pin.** The pin covers the always-loaded pair in the config repo, `memory/MEMORY.md` + `memory/HIGHER_ORDER.md`, and nothing else. This is not a tier definition: `memory/HIGHER_ORDER.md` is the higher-order tier, and user-scope topic files (`memory/topics/*.md`) are user memory of the same authority tier (`shared/AGENTS.md § Memory locations`). Topic files load on demand and are **not** in the pair: they keep the project and topic Size check below, and they are shared stores under the `§ Derived Utility & Pruning` asymmetry rule.

- **What is counted**: the pair's words, as `qmemory-eval.py`'s `compute_memory_tax` counts them (whitespace-separated tokens). `## Declined` rows count in words, though they are not entries. A file that exists but cannot be read is named on the row and the line (`(MEMORY.md unreadable)`), never counted silently as 0; a counter failure prints `unavailable` or `unknown` and changes no exit code.
- **The pin** is `MEMORY_BUDGET_WORDS` in `shared/skills/qdream/scripts/dream-manifest.py`. Read it there; never copy the number into prose or memory (`§ Exclusion List`, last row). `dream-check.py budget` prints it as its `memory` row and `dream-manifest.py count` as its `memory budget:` line. Both warn only: being over never changes an exit code, and never fails `/qconfig-sync`.
- **The ratchet**: after a deliberate reduction, the pin may be lowered to min(current pin, ceil(measured words x 1.10)). Raising it needs the user's approval, recorded in the commit message.
- **Over the pin** (full sweep): `dream-write.py apply-all` removes the over-budget amount autonomously, by `§ Derived Utility & Pruning`, and names each removal in the Report. `memory/HIGHER_ORDER.md` nodes count toward the words but are **never** prune candidates; a node's only removal path is its own `Keep node / Remove node / Defer` gate (`§ Higher-Order Tier`). To keep an entry through a prune, attest it with a `human:` `Verified` actor or move it to a topic file.

**Project memory files and topic files — the entry budget.** Keep each project `memory/MEMORY.md` and each `memory/topics/<topic>.md` concise. Past `ENTRY_PIN` entries, `apply-all` prunes the excess, lowest value first, by `§ Derived Utility & Pruning` (importance is derived, never rated at write time). These files are not counted toward the user-tier word pin.

### Restated-context trigger

The user is establishing persistent context by hand because the memory system did not — that is the signal, not repetition-counting. Propose a memory note immediately on **any** of:

- **A restatement marker** — "as I mentioned", "like I said", "I keep telling you": the user's own evidence they told you before; it fires even the first time you hear it, across sessions or in paraphrase.
- **An explicit request to remember** — no repetition required; it still runs the write-time quality gates.
- **Repetition within the session** — the backstop for a correction you failed to persist the first time; save an explicit correction on the **first** occurrence.

**A restated fact already in memory is a read-time failure, not a write opportunity** — say so: the entry's `How to apply` may be unactionable, or the lesson may belong in governance (`§ Promotion path` above).

Route the near-misses: per-tool-event automation is a **hook** (`§ Exclusion List`); a recurring manual workflow belongs in `shared/AGENTS.md § Continuous Improvement`; harness friction in the project file's `## Harness Improvement Opportunities` (`shared/AGENTS.md § Harness Improvement Capture`), or, with no project file, an `[improvement_signal]` proposal (`§ Plan-less governance capture` below).

### Plan-less governance capture

Any session can record governance friction and fix wrong memory without a project file. `shared/AGENTS.md § Harness Improvement Capture` points here for the session that has none.

**Friction and skill ideas.** With no active project file, governance or skill friction, and an idea for a new or improved skill, become a proposal of an `[improvement_signal]` row (`§ Memory File Format`, `[improvement_signal]` sub-form) that closes with `Save / Skip / Edit?`; `Edit` means the user amends the row before it is saved. It runs the write-time quality gates first (`shared/AGENTS.md § Write-time quality gates`). Its `Why` states what the friction cost, because `shared/AGENTS.md § Harness Improvement Capture` requires a cost.

- **Where.** In `memory/topics/improvement-signals.md` in the config repo, or in the project's `memory/MEMORY.md` when the target is a project-specific file (the scope routing of `sweep-synthesize.md § SYN-PROMOTE`). A session in the config repo itself whose signal targets a `shared/` or `providers/` file writes the topic file, never the config repo's project store: the target is not project-specific (`shared/AGENTS.md § Harness Improvement Capture`).
- **Fields.** The sub-form's fields, with a verbatim `Evidence-quote` from this session, `**Frequency**: 1 (below threshold)`, and `**Sessions**: in-session <YYYY-MM-DD> <session-id>, <project>`: comma-separated tokens, the project last and required. The session id comes from the harness where it exposes one (Claude Code: the `CLAUDE_CODE_SESSION_ID` environment variable, `providers/claude/steering/memory-sources.md`). Otherwise omit it: `in-session <YYYY-MM-DD>, <project>`.
- **Re-observation.** If the target file already holds a row with an equivalent concern, propose updating that row instead of adding one: add this session's token to its `Sessions` (`Frequency` is derived from `Sessions`, never incremented by hand) and re-date `Last observed`. A session already listed is not added again. A user Skip of such an update records nothing: the row keeps its count, and only a Skip of a new-row proposal goes to the sweep's `user_skipped`.

**Skip.** An in-session `Skip` of a new-row proposal writes nothing during the session: no `## Declined` row, which holds memory-proposal Skips and escalation drops but never a signal Skip, and no state write, which only `/qdream` makes. Do not re-propose a signal the user Skipped earlier in this session. The sweep that later reads the session records it:

- the per-project sub-agent returns the Skipped signal in `user_skipped`, with the verbatim proposal heading and the user's Skip turn (`sweep-gather.md § Phase 2 — Gather`, return schema), and never also in `improvement_signals`, even when the same friction appears elsewhere in the transcript;
- `sweep-synthesize.md § SYN-PROMOTE` drops every signal that matches this sweep's `user_skipped` list (same target, equivalent concern) **before** promotion, before below-threshold persistence and before the re-observation update of a persisted row. This is needed because the `rejected_lessons` consult ignores records dated on the sweep's own day, and this record is only written at `[APP-STATE]`;
- `sweep-decide-apply.md § APP-STATE` appends a `rejected_lessons` record with `reason: skipped` and the sweep date (`§ State File Format`, the third admission path).
- **A later Save wins**: when this sweep's `saved_in_session` lists also hold an equivalent signal (same target, equivalent concern) from a session later than the Skip's, the user's later decision stands: the signal is not dropped and no `skipped` record is written. The record carries the sweep date, not the Skip's, so without this rule an earlier Skip would suppress a later Save made before the sweep ran.

Later sweeps then suppress the signal through the normal consult for the 60-day window. A user Skip is therefore never undone autonomously, in that sweep or later. In-session agents never see the suppression, so later sessions may propose the signal again during the 60-day window. That repeat prompt is the accepted cost, and a user `Save` dated on or after the record's `date` then clears the record (`sweep-synthesize.md § SYN-WRITE`). A same-day Save counts: the record carries the date of the sweep that wrote it, so a Save later that day must not stay suppressed.

**Wrong memory.** A memory entry found wrong while verifying before acting (`shared/AGENTS.md § Read-time behavior`) is said aloud, then:

- **Factual drift** (a cited path, command or version moved): propose a correction to the entry under the normal write-time gates.
- **Contradiction with governance**: follow governance for the task at hand. That is not a discount, so the `human:` carve-out below does not apply, and the escalation goes to the user whoever verified the entry. If the entry already carries a `Governance-conflict` record (`§ Governance-conflict adjudication`), the conflict is adjudicated or pending: mention the record and do not escalate again. Otherwise route it through the escalation action set of `§ Dedup Check Procedure` (cross-tier check):
  - `record with an explicit override note` writes nothing during the session. The next sweep detects the conflict, and the `Governance-conflict` record is written at Phase 4b and Phase 5 as today (`sweep-decide-apply.md`). The cost: the user is asked again when a sweep next checks that file;
  - `propose a governance update` is an ordinary governance proposal, edited only after the user approves the shown edit;
  - `drop` deletes the existing entry once the user chooses it, and appends the `## Declined` row exactly as for a new proposal.

  Never "correct" the entry to match governance: it may record a correction the user made after the rule was written.
- **Contradicting `Source` anchor**: the entry is discounted for this session only, and the fix is proposed as above (`§ Type Taxonomy`, Provenance re-open & auto-demotion). A `human:`-attested entry is surfaced to the user, not discounted. The `human:` carve-out applies to this provenance-anchor discount only.
- Never add a `Stale-after` or `Stale-when` expiry to an entry known to be wrong. An expiry defers a check; this entry needs a fix now.
