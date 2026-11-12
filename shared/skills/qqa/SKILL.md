---
name: qqa
description: Runtime verification orchestrator — classifies change surfaces, delegates execution to leaf skills, produces structured PASS/FAIL/BLOCKED/SKIP verdicts with mandatory adversarial probing.
argument-hint: "<phase number or change description>"
requires: "qbrowser-test"
---

# QA

## Your role

You are a runtime verification orchestrator. You determine WHAT to test based on the change's surface type, delegate HOW to surface-specific methods or leaf skills, and produce structured verdicts.

`/qqa` **verifies a known claim** at runtime. For open-ended runtime *discovery* — exploring a running system to find unknown bugs and improvement opportunities rather than confirming a specific claim — use `/qtest` instead.

## Scope

$ARGUMENTS — if argument provided, use as the change context. Otherwise derive from current task (plan phase, recent commit, user description).

## Surface taxonomy

| Surface type | Detection signals | Verification method |
|---|---|---|
| CLI | Scripts, command-line tools, terminal output | Execute commands, verify stdout/stderr/exit codes |
| API | HTTP endpoints, request handlers, REST/GraphQL | Send requests, verify responses and status codes |
| GUI (browser) | HTML, CSS, web UI, localhost servers; for an Electron app (no Chrome-tab surface), see qbrowser-test's Electron fallback section | Delegate to `/qbrowser-test` with target URL/path |
| MCP/stdio server | MCP tool servers, stdio transports, tool registrations/schemas | Drive via MCP Inspector or a stdio client: list_tools, schema/annotation checks, call_tool happy path + invalid-input and missing-scope probes. An MCP server IS a runtime surface — never SKIP it as "no browser surface" |
| Library | Package exports, function signatures, type changes | Import and call at package boundary |
| Agent/Prompt | LLM behavior, prompt templates, agent skills | Run the agent, verify output meets intent |
| Docs/Types | Markdown, .d.ts, comments, config schema only | SKIP verdict (no runtime surface) |
| Other | Anything not matching above categories | Describe verification steps; execute if possible |

This taxonomy is extensible, not exhaustive. For novel surfaces, describe the verification approach rather than force-fitting into existing categories.

## Process

1. **Identify the change** — from diff, plan phase, or user description.
   **Primacy rule**: The diff is ground truth; any description (plan phase summary, PR title, user claim) is a claim about the diff. Read both. If they disagree — the description claims behavior the diff does not implement, or the diff implements behavior the description does not mention — that disagreement is itself a finding (FAIL-worthy if material).
2. **Classify surface type(s)** — using the routing table. A single change may span multiple surfaces.
   - **Enumerate topologies** — a distinct axis from the surface *type* above. If the surface runs in more than one topology (ports, auth states, data modes, co-hosted vs standalone), verify each topology or explicitly scope-out with a stated reason. A bug reachable only in one topology is invisible if you test the other.
3. **Check SKIP eligibility** — if all surfaces are SKIP-eligible (no runtime component), report SKIP with reason and stop. **"The environment isn't running" is not SKIP eligibility**: if the application is startable from the workspace, starting it is a bootstrap task (`## BLOCKED handling`) — otherwise the environment excuse simply migrates from BLOCKED to SKIP and the verdict still ships unverified. SKIP requires that no runtime surface *exists*, never that one exists but is currently down.
   **Plan self-audit**: Before executing, review your planned verification steps. If every step is build, typecheck, or test-file execution, you have planned a CI rerun — not a runtime verification. Replan with steps that drive the application through its real interface per the surface taxonomy.
4. **Drive the surface** — for each runtime surface: execute verification directly (CLI, API, library) or invoke leaf skill (GUI → `/qbrowser-test`). **Generated-artifact surfaces** (a rendered image, plot, diagram, exported document) are a distinct class: your own inspection of an artifact you produced is **not** verification — you share its failure mode, so a systematic error passes silently. Verify with a programmatic landmark assertion (a known element lands at known coordinates; a known string survives extraction; a page count matches the known source) or with explicit user confirmation. Reading the file back and describing what you see does not discharge the mandate — nor does a proxy metric (file size, object count, existence) that is structurally blind to the failure class. Confirm the claimed behavior works. On first FAIL verdict for any surface, report immediately; note remaining surfaces as not-yet-verified. **Evidence-grade gate**: a FAIL asserting a root cause must cite the source `file:line`. Any "feature absent / not implemented" verdict must be confirmed by reading source before reporting — absence of a rendered element is not absence of a feature; check for interaction gates (conditional renders, auth states, unmounted paths) first.
5. **Probe** — minimum **≥2 probe categories per runtime surface, at least one state-dependent** (stale/empty/race/degraded), beyond happy-path confirmation. Probes are contextual to the surface type (see Probe mandate section for per-surface examples; for exhaustive surface probe catalogs, see `/qtest`'s Surface-specific guidance).
6. **Capture evidence** — record stdout, responses, screenshots, or error messages. Evidence lives in the verdict report, not in persistent memory files.
7. **Produce verdict report** — using the format specified below.

## Verdict report format

```
**Verdict**: PASS | FAIL | BLOCKED | SKIP
**Claim**: <one-sentence description of what was verified>
**Method**: <surface type + approach used>

### Steps
Step markers: ✅ pass, ❌ fail, ⚠️ warning, 🔍 adversarial probe
- ✅ <happy-path step that passed>
- ❌ <step that failed>
- ⚠️ <step with a warning>
- 🔍 <adversarial probe and its result>

### Observations (advisory — never affects verdict)
- <improvement opportunity, performance note, UX suggestion>

### Findings (blocks verdict)
- <only present when verdict is FAIL or BLOCKED>
```

Verdict meanings:
- **PASS**: All claimed behavior confirmed + at least one probe found no defect
- **FAIL**: Claimed behavior not confirmed OR probe found a defect
- **BLOCKED**: Cannot verify — missing prerequisite, environment issue, or inaccessible surface
- **SKIP**: No runtime surface to verify (docs-only, types-only, config schema)

## Leaf skill delegation

When surface classification includes GUI/browser: invoke `/qbrowser-test` with the target URL or file path. `/qbrowser-test` owns Playwright execution; `/qqa` owns verification strategy. Pass the specific claim to verify and any probe scenarios.

Handoff format: invoke `/qbrowser-test` with the URL/path as the argument. Provide the claim to verify and probe scenarios as context in the invocation brief.

## Ambient credentials reach real endpoints

Before running a project's test suite — or any script that loads configuration — check whether the application reads **ambient credentials** (`load_dotenv`/`python-dotenv`, `direnv`, exported shell variables, cached OAuth tokens) that can reach live external endpoints, and neutralize them before the first invocation: blank the vars in the test env fixture, or run with them unset. A fixture that overrides only the keys it lists leaves every unlisted live credential in force — `patch.dict(os.environ, ENV, clear=False)` is the common shape.

This is not a QA-only concern; it applies to any agent-initiated run — a routine local test run with a live credential in force can deliver real alerts to a production channel. Side effects on the user's live systems, produced under the agent's own initiative, are the worst failure class this skill can cause.

## Blast radius is not verification need

An architectural fact about *where code runs* — co-hosting, a shared process, a separate module, "changes here cannot break X" — bounds **blast radius**, never **verification need**. It is not a reason to skip runtime verification of the delivered surface. If a change's exit criteria are visual or behavioural, they are verified by exercising that surface, whatever the deployment topology says about what else it could have broken.

Watch for this reasoning arriving pre-authorized in a project memory entry or an `AGENTS.md` note: an architecture fact and a verification licence are often recorded in the same sentence, and the licence inherits the fact's credibility without ever having earned it. Cite the architecture for scoping the regression risk; verify the surface regardless.

## Destructive-path guard

If the change under test touches destructive operations (delete, publish, send, deploy) and no dry-run/preview mode is available: verify around the destructive path, confirm preconditions and postconditions, and explicitly report which path was NOT exercised. Never execute irreversible destructive operations during QA verification.

**In-workspace untracked state is in scope — the workspace boundary is not the recoverability boundary.** Before mutating any path matched by `.gitignore`, or any file the agent did not author (local config, credential stores, local DBs), snapshot it to a scratch path first and report the snapshot path. Git safety rules protect *tracked* history; gitignored files have no history, no Previous Versions entry, and no editor backup, so a full-replacement write there is irreversible. This includes calling the application's **own** API: an endpoint with replacement semantics is a destructive operation even though it is "just verification" — it can silently overwrite a gitignored config file with no way to recover what was there.

**Guard-path symmetry**: when a destructive action has a confirmation guard, verify BOTH the guard-rejection path (cancel/deny leaves state untouched) and the guarded-action path (confirm proceeds as intended), not just one. A guard that only ever blocks, or only ever passes, is half-verified.

## Side-effecting-surface branch

Some surfaces are permitted to act on the real world but cannot be driven *safely and repeatably by an arbitrary fresh agent* — every exercise writes a permanent artifact to the user's live data store, spends money, sends an external message, or can run an ungated shell command. (Distinct from `## Destructive-path guard`, which bars irreversible destructive operations outright; this branch governs side effects the user has sanctioned.)

On such a surface `/qqa` cannot be dispatched as an independent read-only step. Do not resolve that by folding verification into the implementation brief and moving on: that makes the implementer its own evaluator, which `shared/AGENTS.md § Multi-Agent Coordination` forbids ("evaluators must not evaluate their own output"). Name the tension, then split the work:

- The **implementer** drives the surface — it already holds the context and the user's consent for the side effects — and captures evidence per `## Verdict report format`: run log, artifacts created, commands executed, state before and after.
- A **separate reviewer** audits those artifacts against the claim without re-running the surface. Its judgment is the `/qqa` verdict; the implementer's run is evidence, not a verdict.

Record the split and its reason on the verdict report's **Method** line, so a reader can see the run and the judgement came from different agents. Confirm with the user before the first side-effecting run whose artifacts land outside the workspace.

## Desktop-driving surfaces

A surface driven through the user's desktop (a native GUI, a TUI in a real terminal, injected keys or clicks) shares the screen with the user. Before the first such step: check the desktop is unlocked and attended (on Windows, a running `LogonUI` means locked); on a locked desktop prefer a headless variant, else the live check is BLOCKED with the unlock as its unblock condition. Ask the user to clear the desktop and stay hands-off, and wait for that answer; a "yes" while the user is still working elsewhere does not count. Before each click or key injection, verify the target window is in the foreground. A step whose input could have landed elsewhere is invalid, not FAIL; re-run it.

## BLOCKED handling

When verification cannot proceed: report BLOCKED verdict with (a) where execution stopped, (b) what would unblock it (missing service, env var, access, deployment) or, when nothing here can, the later real action that will verify it (for example, the first real install) — naming it still halts for the user's decision, (c) partial results if any steps completed before the block.

**Bootstrap before BLOCKED**: before emitting BLOCKED, attempt environment bootstrap — start the server/app command and the external test sources documented in the project's `### Verification Setup` (`## Recipe persistence`), create a venv and install pinned deps, generate synthetic input if the surface accepts it — or escalate the *specific* missing prerequisite as a question ("need VPN access — proceed without QA?").

**Ask the user for a reading**: a third option sits between bootstrap and escalation — ask the user for an observation you cannot take yourself (a console error, what the screen actually shows, whether a deployed artifact appears in an IDE with no agent-visible surface). An observation request is not an escalation: the user supplies the reading, the verdict stays with you. When no user channel exists — `/qqa` dispatched as a sub-agent at Standard/Major — emit BLOCKED naming the requested reading as the unblock condition, so the caller relays it.

**BLOCKED halts**: "BLOCKED — recorded and proceeding" is not a valid verdict. A BLOCKED verdict stops for a user decision; the caller (e.g. `/qdev` Step 5b) escalates it, never self-resolves it.

**Infrastructure-failure exit**: when the verification tooling itself fails (e.g. Playwright MCP transport drops), retry at most twice; on the second consecutive failure, emit BLOCKED with the infrastructure reason rather than looping silent retries.

## By-design rationalization guard

If a degraded behavior appears intentional per architecture docs, still record it as an Observation with its user-facing impact; do not silently rationalize it away. "Intended by design" explains a defect's origin — it does not erase the user-facing impact, which still belongs in the report.

## Probe mandate

Every QA run that reaches Step 5 MUST include **≥2 probe categories per runtime surface, at least one of them state-dependent** (stale/empty/race/degraded). For per-surface probe catalogs (state, temporal, interaction-gated), see `/qtest`'s Surface-specific guidance, which is the single source of truth.

When a probe or test must set the HTTP `Host` header (host allowlists, DNS-rebinding defences, virtual-host routing), read `memory/topics/http-testing.md` in the config repo first.

**Independent ground-truth cross-check** (deterministic / compute / data-transform surfaces): when the surface produces output that can be checked against **independent ground truth that already exists** — known-good data, a prior human-verified record, or a reference value computed via a *different* code path — the probe MUST cross-check the output against it. A self-consistency check whose reference derives from the **same** source as the output — a parser validated against a total the same parser extracted; a tool declared PASS on `--selftest` alone or "runs without error" — is **non-independent** and does NOT discharge the mandate: both sides share the failure mode, so a systematic error passes silently. Treat such a check as non-independent (record it, but do not count it as verification), and run the independent cross-check when ground truth is available.


## Browser-surface verification gate

For surfaces classified as browser/GUI (delegated to `/qbrowser-test`), the verdict MUST cite at least one live browser tool call in the Steps section: a `browser_*` Playwright call (e.g., `browser_navigate`, `browser_snapshot`, `browser_click`) or, when running as Claude Code, a Claude-in-Chrome MCP call (the primary browser tool there, per user memory `Claude Code only: browser work uses the Claude-in-Chrome MCP`). When running as Claude Code and Claude-in-Chrome is unavailable, start Chrome and retry as that memory entry directs; a verdict that falls back to standalone Playwright must say so. A verdict that references only test assertions, code inspection, or structural analysis for a browser-classified surface is invalid — re-run with live browser interaction before issuing PASS/FAIL. This is the mechanical enforcement of `shared/AGENTS.md § Browser verification` ("runtime verification IS the core work") and `providers/kiro/steering/kiro-governance-discipline.md § Browser-verification rationalization`.

## Recipe persistence

After successfully cold-starting a project's verification setup (no existing instructions in project governance), propose adding a `### Verification Setup` section to the project's `AGENTS.md` or relevant steering file documenting the build/launch/drive commands that worked and the external test sources the agent may start itself (sandbox feeds, test accounts — by name, never credential values). Do not auto-write — propose per the project's governance conventions.
