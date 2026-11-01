# harvest-dedup — regression fixtures for the native-memory harvest

**Consumer** (per `shared/AGENTS.md § Structure Requires a Consumer`, type 3 — the `/qdream`
consolidation sweep, with the pass named): `shared/skills/qdream/sweep-gather.md § GAT-NATIVE`, the Phase-2
Gather task that harvests Claude Code's native project memory, and the dedup gates it follows in
`shared/skills/qdream/memory-rules.md § Native-memory harvest dedup`.

**Before changing any dedup rule at either of those two sites, replay the procedure below.** That is
what these files are for; nothing else reads them. `qmemory-eval.py` enumerates its fixture cases by
name and never walks this directory, so this tree cannot affect its self-test.

## Why two pairs, and why neither alone is enough

Harvest dedup is a **model judgement**, not a computable function, so the fixture is a cold-read replay
rather than a script. A single fixture would be worthless, because a broken harvest passes it:

| Mutant | pair-1-source-linked | pair-2-heading-similar |
|---|---|---|
| never merges (emits every native entry as new) | **FAIL** | pass |
| always merges (folds any same-subject entry) | pass | **FAIL** |
| correct | pass | pass |

Only the pair discriminates. (This is the mutation-test lesson from Phase 6 of the plan that added this
directory: a fixture that passes whether or not the behaviour is correct tests nothing.)

## Procedure

Run it cold — a fresh session or sub-agent that has not read this file.

1. Give the agent **only** `<pair>/input/` and the two rule sites named above. Do **not** show it
   `EXPECTED.md`, and do not show it this README: both state the answer.
2. Ask it: *"Harvest the native memory under `input/native/` into `input/playbook/MEMORY.md`, following
   `§ GAT-NATIVE`. Report how many entries the file ends with, what you emitted, and what you would
   surface to the user."*
3. Compare its report against `<pair>/EXPECTED.md`. The **OUTCOME** line is the pass/fail test; the
   rest of that file is the reasoning it should have produced, useful for diagnosing a near-miss.
4. Work on a copy if the agent has write tools. `input/` is the fixture, not scratch.

Run **both** pairs. Reporting one is reporting nothing (see the table above).

## Layout

```
README.md                     <- this file: the procedure
pair-1-source-linked/input/           <- inputs only; hand the agent this directory
pair-1-source-linked/EXPECTED.md      <- the answer; kept outside input/ on purpose
pair-2-heading-similar/input/
pair-2-heading-similar/EXPECTED.md
```

Each `input/` holds `native/` (the Claude Code two-file form: an index plus one file per entry) and
`playbook/MEMORY.md` (the destination, in the format
`shared/skills/qdream/memory-rules.md § Memory File Format` defines).

## Provenance

**pair-1 is real data. Do not edit `pair-1-source-linked/input/native/`.** Those two files are the `widget-service`
native memory, copied byte-identically from `workspaces/.snapshots/260814-1418/widget-service-a98707/memory/`
— the **only surviving copy** of that native form, since the migration that produced the playbook half
deleted the source and the snapshot itself is removed by a later phase. SHA-256:

```
5992d60d1692bc97b30b53e3677d544256a8b4021989c74834d3e7538a97d6a0  native/MEMORY.md
1c64bc53fc162016c525bf31a5dd3ceceeb75fabbc02bfac8feb200d2e43d837  native/feedback_data_dir_large_files.md
767d3fe104737d2a1a3f935dcbcde8568c23d007ccad6716522c5c0fbdaf42a7  playbook/MEMORY.md
```

`playbook/MEMORY.md` is the committed store file `workspaces/widget-service-a98707/memory/MEMORY.md` as it
stood when this fixture was built. It is a **copy** and will not track later edits to the store — which
is correct for a fixture, and is why the hash is recorded here.

**pair-2 is fictional** — an invented `seedlab` project. No employer content, no real paths. The
data-governance gate that cleared pair-1's content covered `widget-service` only, so new fixtures stay
fictional.
