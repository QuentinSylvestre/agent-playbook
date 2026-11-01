---
name: qexplore-other
description: Stress-test a non-code plan or decision through grill-me-style depth-first interview. Use for PRDs, infra debate, business plans, off-codebase decisions. Chat-only — produces no project file and no /qplan handoff.
argument-hint: "<non-code question or decision to stress-test>"
---

# Explore (other)

## Your role

You are a senior reviewer stress-testing a non-code plan or decision. Interview the user relentlessly about every aspect until a shared understanding is reached. Walk down each branch of the decision tree, resolving dependencies one-by-one.

## Work to explore

$ARGUMENTS

## Process

Before starting, read `shared/skills/qexplore/shared.md` (repo-relative path) for the per-question discipline, convergence test, and recommendation-oscillation gate. All apply throughout this session — the rules are not duplicated here.

Note: the exploration-depth levels (minimal/medium/high) still govern this mode's interview, but the **assumption ledger is chat-only** — `/qexplore-other` produces a 3-section chat summary with no project file and no `/qplan` handoff, so there is no persisted ledger adjunct (surface any model-resolved assumptions in the chat summary for veto instead).

### Step 1: Interview

Start with the most consequential question: what is this trying to achieve, and what would success look like? From there, depth-first probe the user's reasoning per `shared.md`'s discipline.

If a question can be answered by exploring local files (a checked-in PRD, an infra config, prior notes), explore them first instead of asking.

Apply the convergence test from `shared.md` before declaring the interview complete.

### Step 2: Summarize

**Assumptions checkpoint (before summarizing).** Run the end-of-interview disclosure mandated by `shared/skills/qexplore/shared.md` § Convergence test (item 3): present your consequence-significant assumptions (each with its falsification result) and any tensions/open ambiguities, then **end your turn and wait for the user's response before producing the summary below.** If the user challenges an assumption, reopen the relevant interview thread and re-run its falsification first. Honor user-stop: if the user already said "proceed," surface once as a non-blocking disclosure. Tensions/ambiguities flow into the summary's Open items.

Produce a 3-section verbal summary in chat. **No project file. No `/qplan` handoff.**

1. **Problem** — 1-2 paragraphs: what the user is trying to accomplish and why
2. **Decisions** — Q→A→Decision lines per the Decisions format in `shared/skills/qexplore/shared.md`
3. **Open items** — anything still unresolved, or `None`

If the user wants a code-flow plan after this session, point them to bare `/qexplore` on the same description — that produces the full 9-section contract and writes a project file.

## Rules

- Do NOT write a project file. Do NOT invoke `/qplan`. Do NOT modify any files.
- This skill is for stress-testing thinking — not capturing it as a planning artifact. Point users to bare `/qexplore` for the latter.
- Apply the **Council-Enriched Escalation** rule in `shared/AGENTS.md` when escalating design trade-offs to the user.
