# Playbook Authoring Reference

Authoring-time governance for the agent-playbook repo: conventions for writing a
`SKILL.md` and a guard script, the rule for writing a measured claim, and the
rule governing when new formalism is allowed at all. Read this when creating or
substantially editing a skill, an overlay, a guard script, or a governance file
— not during ordinary work in a consuming project.

Topic memory for this work: `memory/topics/playbook-authoring.md` holds the user's learned
patterns for editing governance, skills, overlays, guard scripts and the memory sweep. Read it
alongside this file.

Lazily loaded. `shared/AGENTS.md` keeps the two section headings (`## SKILL.md
Authoring`, `## Structure Requires a Consumer`) with a summary and a pointer
here, so existing citations to those heading names continue to resolve.

## SKILL.md Authoring

- In YAML frontmatter, never use bare square brackets for `argument-hint` values -- YAML parses `[...]` as flow sequences. Use quoted strings with `<angle brackets>` for placeholders instead: `argument-hint: "<path to file>"`.
- **Cross-file references use repo-relative paths**. When a skill file references another file in the repo — e.g., a SKILL.md whose `## Process` instructs the agent to read a peer rules file, or one skill citing a section of another (`shared/skills/qplan/TEMPLATES.md ## Bugfix Invariants Format`), or hyperlinks in plans and project files — use repo-relative paths from the repo root (e.g., `shared/skills/qexplore/shared.md`), not relative paths (`./shared.md`, `../qexplore/shared.md`) or absolute paths (no `/home/...`, no Windows drive letters). The reading agent resolves these against the repo root, which it can determine via `git rev-parse --show-toplevel` or by the conventional working-directory placement. This convention keeps cross-file references stable across providers (Claude Code, Codex, Gemini CLI, Kiro) and across user machines.
- **Verbatim sub-agent briefs use curly-brace `{token}` substitution markers**, not angle-bracket `<token>`. When a SKILL.md authors a verbatim sub-agent brief that requires runtime token substitution (e.g., `{persona_name}`, `{focus_area}`, `{plan_slug}`), use curly braces — angle brackets in markdown blockquotes can be mis-rendered as HTML auto-links and are also easier to ship unfilled to a sub-agent if the orchestrator forgets to substitute. Document the convention in the skill file (citation-convention note, footer, or equivalent location) so future contributors adding new verbatim briefs see the rule. Precedent: `shared/skills/qcouncil/SKILL.md § Your role` and `§ Juror dispatch`.
- **A behavior-overriding skill names its first action**: state the override, the exact first step, and the banned habitual alternative — otherwise habit wins. When routing sub-commands to aux files, mark the aux-file read as mandatory inline: "You MUST read `<file>` before acting — skipping it drops steps the user expects."
- **State when NOT to use a skill**: where misuse is plausible, a non-applicability note routes to the correct alternative.
- **Closed-set choices name a positive fallback**: when the model picks from a fixed set (tier, persona, verdict), name the specific in-set member the choice falls back to — `Senior engineer` for personas, `Standard` for plan tier. Define the fallback by what it **is**, never by what it is not: "anything unrecognised" names no member, so an out-of-set answer quietly becomes a new category.
- **Write a shared skill as deviations from the model's default behaviour, not as a tutorial.** A frontier model already knows the topic; name the default habits to steer away from and what to do instead. Kiro overlays are the sanctioned exception (`shared/AGENTS.md § Repository Layout`). This is the authoring-time counterpart of the Proportionality/Leanness review standard (`shared/skills/qreview/SKILL.md § Standards union`). Measured on one eval (codex GPT-5.6, Rust Zstd, 160 runs per condition, 2026-09, danluu.com/agentic-testing): a 5-bullet nudge skill had the highest share of fully correct runs, while a 20k-token tutorial skill raised cost 26–41% without improving correctness.

## Script Authoring

- **Never extract a script's `--help` text with a hardcoded line count or range.** Read from the top and stop at the end of the header: the first non-comment line in a shell script, the end of the module docstring in Python. A fixed count truncates silently the moment the header grows — the former `close-plan.ps1 -Help` dropped its whole `Recovery:` block while its `.sh` twin printed it, and stayed green because the parity check compared stdout, never `--help`.
- **Name a behavioural fixture by its input shape, never by its expected outcome.** The reader sees the directory name in the path even when handed only `input/`, so an outcome-shaped name leaks the answer the cold read exists to produce — and can be wrong about it: `pair-1-merge` gave away a verdict and misstated it (gate 0 emits nothing), and the cold reader spent a paragraph reconciling the contradiction. `pair-1-source-linked` names the input and tells the reader nothing about the result.
- **A refusal or FAIL line names the next action.** After the line saying what failed, print what to do: the fix, the file to edit, or "do not retry — tell the user" when retrying cannot help. An agent shown only `FAIL: <check>` probes and retries; one shown the fix applies it. When the failing content may be sensitive, name the rule that matched, never the content (`shared/skills/qdream/memory-rules.md § Exclusion List`, "report the pattern, never the match").

## Measured Claims

When a measurement is written into governance, record the **surface, version and shape** it was taken on, in the same sentence as the claim. A narrow measurement read as a wide claim survives review easily, because the wide reading is always the reasonable one. Three did so in one project: `#[[file:...]]` inert on **v2** became "dead everywhere"; "**Kiro IDE** does not follow symlinks", a **deployment** fact, became "Kiro does not follow symlinks"; a probe target that **had frontmatter** became "symlinks work for any target". The second cost a success criterion, lowered to fit a constraint that did not exist. Writing the boundary into the sentence costs a clause. Reconstructing it later costs a re-probe, and the next reader usually does not know one is needed.

## Structure Requires a Consumer

Structure in playbook artifacts (schemas, IDs, notations, machine-checkable
grammars) must have a consumer, of one of three sanctioned types: a
deterministic tool that parses it, the weak-model provider layer that relies on
it, or the **consolidation-sweep consumer** — the `/qdream` sweep that
deterministically iterates a structure (the episodic ledger, support-set
pointers, per-entry memory metadata) on every run, even though the reader is
itself a frontier model. This third type sanctions structure whose value is
that the sweep walks it mechanically and consistently across sessions, not that
an ad-hoc frontier reader parses it once. To invoke it, the proposer must name
the concrete sweep pass that reads the structure and the specific field it
iterates — a bare "the sweep reads it" does not qualify, so the type cannot
become a blanket exemption. Structure whose only reader is a
frontier model outside these three consumer types stays prose. Complements the
Proportionality/Leanness review standard (`shared/skills/qreview/SKILL.md §
Standards union`): this rule prevents at authoring time what Leanness prunes at
review time. When proposing new formalism, name the consumer.

The playbook map and the citation-check guard cite the `## Structure Requires a
Consumer` heading by name; **renaming that heading breaks those citations** —
search for the literal heading string before renaming.

## Doc & Test Guidelines citation sites

Maintainer guidance for `shared/skills/qplan/TEMPLATES.md § Doc & Test
Guidelines` — split out here because it is a consumer/extension list for
maintainers, not runtime instruction for agents running that section. The
rename hazard itself stays declared once, at the canonical heading
(`shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines`); this list is
what that declaration protects.

**Citation sites** (canonical list — referenced by the rename-guard rule in
`shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines` and the
lockstep-extension rule below):

1. `shared/skills/qplan/TEMPLATES.md § Doc & Test Guidelines` — canonical text and consumer documentation.
2. `shared/skills/qplan/SKILL.md` Step 2 — bootstrap-and-confirm flow + durable-update rule.
3. `shared/skills/qdev/SKILL.md` Step 4 sub-agent brief — names this subsection in the governance-file reading instruction.
4. `shared/skills/qdev/SKILL.md` Step 9 review-scope item — verifies compliance.
5. `shared/skills/qreview/SKILL.md` § Standards union, `Documentation` standard — full verification text.
6. `shared/AGENTS.md` § Code Quality — pointer bullets to this section.
7. `providers/kiro/skills/qwire-governance/SKILL.md` Step 3 — subfolder-conflict precedence reference.
8. `shared/skills/qclose/SKILL.md` Step 2 Pass 4 — documentation-ripple sweep gating (runs or skips based on section presence/waiver state).
9. `shared/AGENTS.md` § Doc & Test Guidelines — **owns the guideline text** this section cites; also a `verify-citations` CHECKS site.
10. `shared/skills/qextract/references/playbook-map.md` and `providers/kiro/steering/kiro-guidelines.md` — `verify-citations` CHECKS sites for the `Doc & Test Guidelines` row; a rename must keep the literal string present in both.
11. The config repo's own root `AGENTS.md` § Doc & Test Guidelines — a **pointer body** citing site 9 by name. It sits outside `shared/` and `providers/`, which is why the rename guard names the repository root as a third search scope. Any other project that adopts a pointer body is the same case.

When adding new guideline categories or consumer call sites, update all sites in lockstep. Adding a category without updating every site listed above is a review finding. New consumers must be appended explicitly.
