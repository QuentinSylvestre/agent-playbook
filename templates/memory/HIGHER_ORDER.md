# Higher-Order Memory

This is the **higher-order tier** of the closed-loop memory system — the semantic half of the `/qdream` dual store (the episodic half is the `episodic_ledger` in `memory/.dream-state.json`). It holds **abstractions the `/qdream` sweep induces across episodes and base `memory/MEMORY.md` entries** — one rung above the concrete `feedback` / `decision` / `pattern` entries. Format spec: `shared/skills/qdream/memory-rules.md § Higher-Order Tier`.

How it is used:

- **Written by the sweep**: the `/qdream` full-mode Phase-3 higher-order synthesis step writes and updates the nodes below autonomously (Dream autonomy exception, `shared/AGENTS.md § Dream autonomy exception`). The grant covers a `memory/MEMORY.md` **wherever resolution places it**, so a workspace's `<store>/memory/MEMORY.md` in the store repo is within the grant, as is the `STORE` file the store resolver creates for a target — and nothing else in the store repo is (`shared/skills/qdream/memory-rules.md § Workspace Store`).
- **Compounds across sweeps**: each node carries a **`Support-set`** field pointing at the episodes / base entries it abstracts; the next sweep re-reads this file at Orient so its nodes re-enter that sweep's reflection input rather than being re-derived from scratch.
- **Loaded at session start, by whichever route the harness has**: this file is one of the two **global** tiers, so read it alongside the `memory/MEMORY.md` files unless the harness or its steering shows it was already delivered in full (a heading index is not delivery) (`shared/AGENTS.md § Memory locations` / `§ Read-time behavior`). It ranks **below user memory and below governance** (`shared/AGENTS.md § Authority hierarchy` — an abstraction never outranks its own ground truth) and is **read-time advisory** — verify before acting, and it never overrides a governance rule.
- **Referential integrity**: each sweep **resolves every `Support-set` pointer fresh** — into `resolved` / `confirmed-absent` / `indeterminate`, carrying no marker and no state between sweeps. A node whose **entire** `Support-set` resolves `confirmed-absent` is **surfaced to the user** (`Keep node / Remove node / Defer`), **never removed autonomously**; a single `indeterminate` pointer (the sweep could not look) blocks that gate, so a node is never claimed to have lost ground the sweep never checked (`shared/skills/qdream/memory-rules.md § Support-set referential integrity`).

Nodes are grouped by the same type sections as `memory/MEMORY.md`. The tier starts empty; the sweep populates it. It is **persistent** and distinct from the ephemeral per-run Insights Report (the `insights_signals`-derived chat narrative the sweep prints in Phase 4a), which is never stored here.

## Feedback

## Decision

## Pattern
