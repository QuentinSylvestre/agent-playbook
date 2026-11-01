# /qexplore — prose/governance trio briefs

<!-- Loaded by shared/skills/qexplore/SKILL.md § Step 1.5 when task-type inference selects this trio. Each brief is sent verbatim, with the {token} placeholders filled and the Sub-agent report contract block (in SKILL.md) appended. -->

Dispatch these three when task-type inference selected **prose/governance**.

**Directed (ticket-aware) sub-agent brief**:

```
You are performing directed governance/prose research for an upcoming change to
documentation, skill, or governance files.

Inputs:
- Work description: {work_description}
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}
- Archived plans: {archive_root}

Read the governance files first. Then perform goal-oriented tracing of the prose
the work will touch:
- The specific rules, sections, headings, and anchors the change will modify
- Cross-file references (citations by section name, repo-relative links) that
  point INTO the sections being changed
- Precedents — places in the governance/skill files that already do something
  similar to what is proposed (existing conventions to follow)
- Constraints the change must respect (authoring conventions, single-sourcing
  rules, citation conventions, reserved names)
- Prior decisions on the files in scope, from archived plans (decision and
  plan filename)
- Risks identified, with file:line evidence

You have full repo access. The orchestrator's findings are starting points, not
boundaries — follow citation chains and cross-references wherever they lead.
Prioritize depth over breadth: trace the relevant rule/citation chains
thoroughly rather than scanning broadly. Pay special attention to the
orchestrator's reported gaps — sections it identified but did not read.

Return a structured report with file:line references for every finding.
Do not propose solutions. Do not write code.
```

**Consistency/Duplication-finder (ticket-blind) sub-agent brief**:

```
You are mapping consistency and single-sourcing across a body of governance,
skill, and documentation prose. You are NOT told what change is planned. Do not
speculate about future changes. Map what exists.

Inputs:
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}

Read the governance files first. Then inventory cross-file consistency factually:
- Restatement: the same rule, definition, or instruction stated in more than one
  place (duplicated content that should be cited from a single source)
- Single-sourcing violations: content that claims to be canonical in two places,
  or that duplicates a section explicitly marked as the canonical source
- Orphaned citations: references (by section name or repo-relative path) whose
  target no longer exists or has been renamed
- Colliding citations: two sources both presenting themselves as the authority
  for the same rule
- Inconsistent terminology or conventions across files

You have full repo access. Follow citation and cross-reference chains wherever
they lead. Prioritize depth over breadth: map the connected citation graph
thoroughly rather than scanning broadly. Pay special attention to the
orchestrator's reported gaps — sections it identified but did not read.

Return a factual consistency/duplication map with file:line references for every
finding.
Do not propose changes. Do not speculate about why the area was
selected.
```

**Citation/Caller-impact (ticket-aware) sub-agent brief**:

```
You are tracing citation blast-radius across governance, skill, and
documentation prose.

Inputs:
- Work description: {work_description}
- Orchestrator's initial findings (advisory — tells you where to start, not
  where to stop):
  {problem_context_summary}
- Governance files: {governance_file_paths}

Read the governance files first. Then trace what breaks if the sections the work
touches are renamed, moved, or removed:
- Which files cite the touched sections by name (section-name citations) or by
  repo-relative path, and would desync if the section is renamed or moved
- Which anchors, headings, or named conventions other files depend on
- Step-number vs section-name citation hazards (citations that hardcode a
  position which a reorganization would break)
- Downstream consumers (other skills, AGENTS.md rules, templates) that read or
  reference the touched content and would need a coordinated update

You have full repo access. Follow citation chains end-to-end through every
referencing file. The orchestrator's findings tell you the sections being
touched — your job is to map everyone who depends on them. Prioritize depth over
breadth: trace the citation dependency graph thoroughly rather than scanning
broadly. Pay special attention to the orchestrator's reported gaps — sections it
identified but did not read.

Return a structured report with file:line references for every finding.
Do not propose solutions. Do not write code.
```
