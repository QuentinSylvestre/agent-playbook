# /qexplore — code-tracing trio briefs

<!-- Loaded by shared/skills/qexplore/SKILL.md § Step 1.5 when task-type inference selects this trio. Each brief is sent verbatim, with the {token} placeholders filled and the Sub-agent report contract block (in SKILL.md) appended. -->

Dispatch these three when task-type inference selected **code-tracing**.

**Directed (ticket-aware) sub-agent brief**:

```
You are performing directed codebase research for an upcoming change.

Inputs:
- Work description: {work_description}
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}
- Archived plans: {archive_root}

Read the governance files first. Then perform goal-oriented tracing:
- Code paths, callers, and dependencies the work will touch
- Similar patterns or precedents in the codebase
- Constraints (tests, contracts, invariants) the work must respect
- Prior decisions on the files in scope, from archived plans (decision and
  plan filename)
- Risks identified, with file:line evidence
- When the work touches storage, logging or capture: an inventory of every
  store involved (where it lives, its format, what writes and what reads it)

You have full codebase access. The orchestrator's findings are starting points,
not boundaries — follow import chains, call graphs, and any trail you find
relevant. Prioritize depth over breadth: trace relevant chains thoroughly
rather than scanning broadly. Pay special attention to the orchestrator's
reported gaps — sections it identified but did not read.

Return a structured report with file:line references for every finding.
Do not propose solutions. Do not write code.
```

**Subsystem (ticket-blind) sub-agent brief**:

```
You are mapping a subsystem of the codebase. You are NOT told what change is
planned. Do not speculate about future changes. Map what exists.

Inputs:
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}

Read the governance files first. Then describe the relevant subsystem factually:
- Data structures, types, and their relationships
- Public interfaces and key functions
- Control flow and integration points
- Invariants the code relies on (what is true about the current state)
- Tests and quality gates

You have full codebase access. Follow relationships between components wherever
they lead. Prioritize depth over breadth: map connected components thoroughly
rather than scanning broadly. Pay special attention to the orchestrator's
reported gaps — sections it identified but did not read.

Return a factual subsystem map with file:line references for every finding.
Do not propose changes. Do not speculate about why the area was selected.
```

**Intermediary/Mutation Finder (ticket-aware) sub-agent brief**:

```
You are tracing data transformations and runtime mutations in a codebase.

Inputs:
- Work description: {work_description}
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}

Read the governance files first. Then trace what happens to data BETWEEN
producers and consumers:
- Runtime state mutations (dicts, objects, configs modified in-flight)
- Config/data transformations by orchestrators, runners, or middleware
- Decorator/hook injections that modify behavior invisibly
- Monkey-patching or dynamic attribute assignment
- Any logic that sits between an obvious input source and its final consumer

You have full codebase access. Follow the data flow end-to-end through every
intermediary. The orchestrator's findings tell you the endpoints — your job is
to map everything that happens in between. Prioritize depth over breadth:
trace the transformation pipeline thoroughly rather than scanning broadly.
Pay special attention to the orchestrator's reported gaps — sections it
identified but did not read.

Return a structured report with file:line references for every finding.
Do not propose solutions. Do not write code.
```
