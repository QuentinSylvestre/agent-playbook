---

## Merge Strategy — field-resolution grid (kiro)

Detailed field-by-field rules for the dedup merge summarized in `§ Merge Strategy`. When a dedup check identifies a related existing entry, apply:

- **type**: Dedup identity is `(type, normalized subject)` — a `feedback` entry and a `decision` entry on the same subject are **not** duplicates and are **never** merged across type boundaries. Only entries of the same type are candidates for merging. When both entries share the same type, keep it.
- **heading**: Use the new heading if it's more specific; keep the old one otherwise.
- **Why**: Use whichever version is more precise. Do not concatenate.
- **How to apply**: For feedback/decision types, use the new version. For pattern types, append new detail to existing if it adds information; otherwise keep existing.
- **Source**: Append the new source after the existing one, separated by ` + `. Sources are re-openable anchors (`plan-slug + section`, or `session-id + line-span`). Example: `260519_COUNCIL_ENRICHED_ESCALATION § Post-Implementation Review + 945f4664#L120-138`
- **Verified**: If the merge includes a type-specific verification check (grep, plan scan, or artifact check), set to today. Otherwise, keep the more recent `Verified` date from the two source entries. A sub-agent verification reported in the same `/qdream` run counts. Note: a merged entry may still trigger staleness checks — merging is not verification.
  - **The actor/method annotation travels with the date it describes** (`**Verified**: 2026-07-28 (human:alice, anchor-reopen)`). Keep the surviving date **together with its own annotation** — NEVER recombine one entry's date with the other entry's actor: the pair describes one verification event. If the merge itself was the verification and no stronger check ran, annotate it method `merge`. **Accepted residual**: a later `sweep` verification supersedes an older `human:` one, so the human attestation — and the demotion protection it carries — is lost on that merge. That is accepted, not a bug to route around; do not invent a sticky-actor rule. The sweep Report names each such lapse (`Attestations lapsed on merge`).

Cross-type optional metadata fields (present only when the entry carries them; see `§ Memory File Format`):

- **Evidence-quote** (`evidence_quote`): Keep the verbatim quote that entails the surviving claim. If the merged claim changed, keep the quote that entails the new claim. Do not concatenate quotes. In `memory/MEMORY.md` and `memory/HIGHER_ORDER.md` keep none.
- **Usage**: Sum the two counters — the merged entry inherits the combined reliance count.
- **Outcome**: Keep the most recent by its date; a later `recurred`/`not-recurred` observation supersedes an earlier one.
- **Governance-conflict** (+ **Governance-conflict-quote**): **Union record-lists by key** (key = (contradicted/absorbing `<file § section>`, whitespace-normalized span)). Same-key records from both entries collapse to the **most-recent by `adjudicated <date>`** (same-day tie → the **non-terminal** state wins — `rule-update-pending`/`deferred` over `keep-entry`/`subsumption-kept` (both terminal-like) — fail-safe: keep the conflict live); different keys **coexist as separate records** on the merged entry. This is **resolution**, not suppression — every surviving record remains individually re-raiseable per `§ Governance-conflict adjudication`. Full rule: `shared/skills/qdream/memory-rules.md § Merge Strategy`.
- **Support-set**: Union the two pointer sets, de-duplicating. A pointer carries no marker and no state, so there is nothing to preserve — each pointer resolves fresh on the next reconciliation pass.
- **Stale-after / Stale-when**: keep the **earlier** `Stale-after` (it fires sooner, and more checking is the fail-safe direction); keep whichever `Stale-when` still describes the surviving claim, or both if both still apply. Never drop one merely because the other entry lacked it.

---

## Workspace Store — discipline (kiro)

Traps in `§ Workspace Store` that are easy to read past. Follow these literally.

- **Run the store resolver and use the path it prints.** Before a read, run `store-resolver.py find <folder>`. Before the first write, run `store-resolver.py find-or-create <folder>`. The full commands and exit codes are in `§ Resolution contract`. Exit 0 prints the store directory; append `<kind>/` yourself.
- **Never make up a store name.** Do not derive, hash, slug or guess one, and never build one from the folder's name. On 2026-10-21 a kiro `/qplan` decided to "pick a reasonable identifier like `widget-ec4f9a`" and wrote its plan into a directory it named itself. Only the resolver names a store. A directory you name yourself is a store the resolver did not create: the next session may not find it, or may find two.
- **Never find a store by its directory name.** The name is for people. The resolver reads the `STORE` files and compares identities. Do not read or compare `STORE` files by hand.
- **Never create a store directory or a `STORE` file by hand.** Only `find-or-create` creates a store. When it fails, do not retry with another tool.
- **One hand edit is allowed, and only when the user asks for it: the remote re-key** (`shared/skills/qdream/memory-rules.md § The STORE file`). Copy the new `remote` line from `store-resolver.py identity <folder>`; never type it yourself.
- **`none` from `find` only means "no store yet".** Before any write, run `find-or-create`.
- **`none` from `find-or-create` keeps memory and plans in the folder.** Exit 3 there means the resolver makes no store at that folder; the reason is on stderr. Read and write `memory/` and `plans/` at the folder, or at the nearest level up to its git toplevel that holds them (shared step 3). Do not create a store anyway.
- **`failed` writes nothing.** Exit 2 means the store repo is missing or unreadable. Report the stderr reason and stop. Do not fall back to the folder.
- **In the config repo, the root `memory/` is user memory**, never project memory. The config repo's project memory is its own store, which `find` returns. Its project files stay in the repo: `--kind plans` prints the repo itself.
- **Resolve before you create, every time.** Never write `<project>/memory/MEMORY.md` from habit. Appending a `## Declined` row creates the file too, so it is a creation site as much as a bootstrap is.
- **Commit what you wrote in the store repo**, by pathspec, at the skill's next commit point, or leave it for `/qconfig-sync`. Inside a `/qdream` full sweep, never commit by hand: the sweep's closing commit does it.
