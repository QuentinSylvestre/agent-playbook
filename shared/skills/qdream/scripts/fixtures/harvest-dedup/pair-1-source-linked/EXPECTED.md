# pair-1-source-linked — expected outcome

**OUTCOME: one entry. Nothing emitted, nothing surfaced.**

`input/playbook/MEMORY.md` ends the harvest byte-identical to how it started — exactly one `###` entry
under `## Feedback`, all three type headings present, `## Declined` present.

## Why

**Gate 0 (already harvested) fires.** The existing entry's `Source` line names both keys the
translation is required to write:

- the native file — `memory/feedback_data_dir_large_files.md`
- the legacy native ID — `data-dir-large-file-edits` (the native frontmatter's `name:`)

So the native entry is already in the store, and the harvest emits nothing.

**Gate 1 would fire too, if gate 0 were deleted.** The native file's lead paragraph, `**Why:**` body and
`**How to apply:**` body are character-for-character the same text as the store entry's lead paragraph,
`**Why**` and `**How to apply**`. They are one fact in two formats — the definition of
translation-equivalence. This pair therefore kills a never-merge mutant at both gates, not just one.

## The mapping, if you re-derive rather than dedup

The store half is also the reference answer for the native→playbook mapping table
(`providers/claude/steering/memory-sources.md § Native project memory`), including the two judgement
calls the table did not originally cover:

- the `###` heading is the index line's link text **plus its gloss**, joined as written;
- the index file's **title** line (`# Project Memory — widget-service`) survives into the destination file;
- `description:` was compared against that heading and **discarded** (it differed by two words, both
  already carried);
- `name:` lives **inside `Source`** as the legacy native ID;
- **`Verified` is absent** — no verification event occurred.

## FAIL if

- a second entry appears anywhere in the file (a harvest that never dedups);
- a near-duplicate is surfaced at § DEC-GATE (there is nothing ambiguous here);
- the `## Declined` heading, or any of the three type headings, is dropped or duplicated;
- either file under `input/native/` is modified — they are the only surviving copy of the native
  two-file form (see `../README.md`).
