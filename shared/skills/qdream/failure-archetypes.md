# Failure Archetypes

Signal catalog of recurring agent-failure patterns. Each entry: `### name` (underscore_separated_lowercase, no colons), **Description**, **Session signals**.

## Archetypes

### skill_not_fully_loaded

**Description**: Agent acts on a skill without reading its SKILL.md first.

**Session signals**: Agent produces output inconsistent with skill steps; user corrects with "you need to read the skill file"; agent reads SKILL.md mid-task after user correction.

### step_skipped_with_rationalization

**Description**: Agent rationalizes skipping a skill step ("I already have enough context," "this is straightforward enough to skip").

**Session signals**: Agent explains why a step isn't needed; user insists the step be performed; agent then performs it and finds relevant information.

### sub_agent_bypass

**Description**: Orchestrator proceeds without sub-agent output after failure or rationalizes that its own analysis is sufficient.

**Session signals**: Sub-agent returns "No result" or errors; orchestrator continues with own reasoning; user corrects ("retry the sub-agent").

### repeated_same_question_corrections

**Description**: User states the same fact, constraint, or correction multiple times within a session.

**Session signals**: User repeats a constraint verbatim or paraphrased 2+ times; agent acknowledges but doesn't persist it.

### fast_exit_exploitation

**Description**: Agent uses a tier gate, skip rule, or fast-exit to avoid expensive-but-valuable steps.

**Session signals**: Agent classifies work as Trivial to skip sub-agent dispatch; user overrides classification; the fuller process produces valuable results.

### intent_drift

**Description**: Exploration or planning phase fails to capture the user's full intent, requiring follow-up plans.

**Session signals**: User says "that's not what I meant"; subsequent plan on the same feature/area exists; user adds scope that was implicit in original request.

### governance_rule_ignored

**Description**: Agent acts contrary to an explicit rule in AGENTS.md or SKILL.md that was in context.

**Session signals**: Agent's action contradicts a rule it was shown; user points out the specific rule; agent acknowledges and corrects.

### over_scoped_change

**Description**: Agent over-engineers or changes far more than the request required. The process may have been followed perfectly — this is a failure of the *output*, not of the procedure.

**Session signals**: User says "I only asked for X", "why did you touch Y", "revert that part", or "this is more than I wanted"; the diff spans files or concerns the request never named; the agent adds abstraction, configuration, or generality nobody requested.

### delivered_broken_code

**Description**: Agent delivers code that does not work — the goal and the approach were right, the artifact was not.

**Session signals**: User reports the change does not run, does not build, or fails its tests; the agent's next turns are spent fixing what it just shipped; a "done" claim is followed by an error report rather than acceptance.

### misread_request

**Description**: Agent solved a different problem than the one asked, or picked a wrong solution method for the right goal.

**Session signals**: User says "that's not what I asked", "I meant…", or restates the request with emphasis; the agent's output is competent but aimed at the wrong target; the user re-scopes rather than corrects a detail.

### qa_environment_bootstrap_avoidance

**Description**: Agent declares runtime QA BLOCKED or "not testable from this environment" instead of provisioning the environment (starting the documented server, creating a venv, generating synthetic input), then proceeds as if verification were complete.

**Session signals**: A QA/verification step records BLOCKED with an environment reason ("server offline", "no network access") and the run continues; a one-line user nudge ("you can spawn an instance", "you can create a venv") is followed by successful bootstrap and a PASS verdict; the plan is presented as complete with zero live verification.

### guess_iteration_before_doc_lookup

**Description**: Agent iterates plausible guesses against third-party tool behavior (config formats, API parameters, transport choices) instead of consulting authoritative documentation or search first; the answer is in public docs when finally sought.

**Session signals**: A run of small variant attempts against an external tool, each handed to the user or environment to test and each failing; the user demands a doc lookup ("can you look at the online doc?"); the eventual fix arrives via web search or documentation ("Found it. The last answer on SO nails it").

### repeated_adhoc_scripting_before_generalization

**Description**: Agent writes a run of near-identical single-shot probe scripts — duplicated setup/teardown boilerplate, each testing one hypothesis — without saving any of them or folding the working one back into the artifact under repair; when the answer is finally found it is re-implemented from scratch. The proactive "these repeat — shall I generalize?" offer never fires, so the user, not the agent, initiates generification if it happens at all.

**Session signals**: Three or more consecutive shell tool uses carrying inline here-string scripts that differ only in the hypothesis under test; no file write between them; the eventual fix lands as a fresh edit rather than reusing a probe. Mitigating context worth noting when present: live-hardware or time-pressured troubleshooting can make throwaway probes defensible in the moment.

### closed_enumeration_read_as_exhaustive

**Description**: A governance rule states a general prohibition and then lists example instances of the rationalization it forbids. The agent treats the list as the rule's full extent and acts on a neighbouring shape the list does not name — believing itself compliant, because its case is not enumerated. Distinct from `governance_rule_ignored` (acting against a rule squarely on point) and `fast_exit_exploitation` (exploiting a sanctioned skip gate).

**Session signals**: Agent prose that recites the enumerated exceptions and then distinguishes its own case from each of them ("Per the gate: … But this is X, so I'll proceed"); a governance file whose own text records that its exception list has been extended by past bypasses; the bypassed action is benign, so no user correction follows. Observed at ≥4 occurrences across ≥3 sites (qconfig-sync Step 1, qexplore Step 1 Non-bypasses, kiro-governance-discipline). The recurring repair — appending a closure clause per site after the fact — is what a named archetype pre-empts.

### ceremony_not_downgraded_at_convergence

**Description**: Agent carries a heavyweight process to its artifact-producing step without re-testing the tier at the moment scope has actually settled, and the *user* initiates the downgrade. The output would have been right; the *process* was oversized. Distinct from `fast_exit_exploitation` (agent takes a cheap exit to avoid valuable work) and `over_scoped_change` (about the diff, not the procedure).

**Session signals**: Agent ends a phase with "then I'll write the project file" / "I'll capture the intent" as a foregone conclusion; the user replies with a **question rather than a correction** ("do you need the project file?", "do you think you could handle it by yourself from here?"); the agent's own subsequent assessment concedes the lighter path. Under-detected because the intervention is phrased as a question and generates no correction-shaped text — the same blind spot `silent_instruction_drop` names.

### premature_capitulation

**Description**: Agent declares a problem unfixable or a broken state acceptable to exit a hard debugging loop; the user overrides from direct experience; continued investigation then produces new information. Promoted from candidate accumulation at 2 sessions.

**Session signals**: "This isn't fixable through config" / "that approach is exhausted" followed by a manual workaround offer; a one-line user push contradicting it ("X works, i can guarantee it"); investigation resumes and yields progress. Note the honest counter-consideration: the final diagnosis may be substantially correct — the failure is declaring a dead end while cheap avenues remain, not misdiagnosing.

### partial_corpus_search_declared_complete

**Description**: Agent checks one part of the population a conclusion depends on — one comment type, a subset of the target files, one source among several — then states the conclusion for the whole population, usually just before a destructive or committing step. Distinct from `closed_enumeration_read_as_exhaustive` (a governance list read as complete) and `guess_iteration_before_doc_lookup` (no check at all).

**Session signals**: "completely safe" / "no other X" asserted right after a search whose scope is visibly narrower than the claim; the user names the unchecked part ("there are some inline comments"); a coverage check whose file count is smaller than the set of files the change lands in. Under-detected: it produces correction-shaped text only when the user notices (see the detection note below). Promoted from candidate accumulation at 2 sessions across 2 projects (2026-09-28).

### unisolated_fix_codified_as_rule

**Description**: After a debugging loop succeeds with several changes applied at once, the agent writes a causal claim about one of them into a skill, steering or memory file without isolating it (removing only that change and watching the failure return). The rule then loads as authority in later sessions. Distinct from `delivered_broken_code` (the output fails) — here the output works and the recorded *explanation* is wrong.

**Session signals**: a governance or memory commit right after a multi-change fix, stating that one specific element is "required"; no one-variable test in between; a later session contradicts the rule by experiment. Promoted from candidate accumulation at 2 sessions (2026-09-28).

### non_answer_read_as_decision

**Description**: Agent has put an option question to the user ("A or B?", "implement directly, or start with /qexplore?") and treats a following user turn that names no option as the answer, then proceeds on the option it favoured. The turn was a question, a comment, a request for information or a topic change, so no decision was given. Distinct from `misread_request` (the request itself is misunderstood) and `step_skipped_with_rationalization` (the agent argues a step away; here it reads consent into a turn that gave none).

**Session signals**: A pending option question is followed by a user turn that selects none of the options; the agent's next message says "since you want...", "as you confirmed..." or simply acts on one option; the user later says "I didn't say that", "I hadn't decided", or re-answers the original question. Under-detected: when the agent's pick happens to match the user's wish, no correction follows. Observed in 2 sessions (ce01bfef, 0b7d7c60), evidence V05-034.

### silent_instruction_drop

**Description**: The user gives an explicit request, parameter or constraint and the agent neither carries it out nor acknowledges it, so the instruction vanishes without a trace. Distinct from `misread_request` (the agent understood something else and solved that, visibly) and `governance_rule_ignored` (the instruction came from a rule file, not from the user's turn). Here the request was understood well enough to be read, then lost.

**Session signals**: A user turn contains a named ask (a flag, a file, a step, a format) with no matching tool call, edit or reply in the agent's following turns; the agent's final summary omits the item and does not say it was skipped; the user either never reacts or notices late and asks "did you do X?". Under-detected: it produces correction-shaped text only when the user happens to notice (see the detection note below). Promoted from candidate accumulation at 5 sessions (V05-021, V10-007, V17-012 among them).

<!-- RULED OUT 2026-08-05, do not re-propose without new evidence: fabricated_extraction_from_read_source. The claim was that an agent read two ws-debug logs in full and then reported field-level findings absent from them. Refuted at the cross-validation gate: the telemetry is hex-encoded in `raw_bytes`, so the plaintext grep that "proved" absence proved nothing. Decoded, the reported values ('1.5-32', '17385.000000', 'AP-610') are present in log 2 and absent from log 1, exactly as reported. Only the protobuf field LABELS were over-specified — over-specification, not fabrication. -->

<!-- Detection note (2026-08-05): eight of the candidates above are detectable ONLY when the user happens to react. `silent_instruction_drop`, `ceremony_not_downgraded_at_convergence` (promoted above) and `partial_corpus_search_declared_complete` each fire in sessions that produce no correction-shaped text at all, so their observed frequency is a floor, not an estimate. Do not read a low count as low incidence. -->

<!-- RULED OUT 2026-07-28, do not re-propose without new evidence: premature_halt_continue_nudges. The open question was whether kiro-cli's "Tool uses were interrupted, waiting for the next user prompt" indicated a harness turn budget. It does not: across 12 occurrences the line is immediately preceded by a ToolResults record reading "Tool use was cancelled by the user" with status:error — a user Esc — and the 12 map one-to-one onto 12 of 14 bare "continue" prompts. This is user-initiated interruption, not agent capitulation, so an auto-continue fix would target the wrong cause. -->


### unverified_inference_in_rationale

**Description**: Agent states an inference it did not check as established fact inside a recommendation or its justification, so the user decides on a premise that was never tested. The check was cheap and available (a grep, a file read, a one-line command); the claim simply carried no verification label. Distinct from `partial_corpus_search_declared_complete` (a check was run but its scope was narrower than the conclusion), `guess_iteration_before_doc_lookup` (repeated guesses against a third-party tool) and `unisolated_fix_codified_as_rule` (a causal claim written into a governance file after a multi-change fix).

**Session signals**: A recommendation whose reason is asserted in flat declarative prose ("X is not possible because Y", "this already handles Z") with no tool call, citation or `[unverified]` label behind it; the user questions the premise ("are you sure?", "did you check?") or supplies the counter-fact; the agent then runs the one check and the claim is wrong or only partly right. Observed in 17 sessions across 9 projects. Under-detected: when the inference happens to be true, nothing prompts a correction, so the count is a floor.

### verification_claimed_before_performed

**Description**: Agent states that something is verified, tested, checked or confirmed before it has run the check, or in place of running it. The claim stands where the evidence should be. Distinct from `delivered_broken_code` (the artifact fails; here the verification statement is the failure, and the artifact may be fine), from `partial_corpus_search_declared_complete` (a real check ran but covered too little), and from `qa_environment_bootstrap_avoidance` (the check is declared blocked, not claimed done).

**Session signals**: "verified", "tests pass", "confirmed" or "all N cases checked" appears in a turn with no preceding tool call that could have produced the result; the user asks "did you actually run it?" or runs the check and gets a different answer; the agent then performs the check it had already reported. Under-detected: when the claim happens to be true, no correction-shaped text follows. Promoted from candidate accumulation at 5 sessions (V02-015, V05-081, V06-040, V06-051 and a persisted CANDIDATE row).

### proxy_check_substituted_for_goal

**Description**: Agent verifies a cheaper stand-in for the goal (a source is reachable, the code reads correctly, a check passes) and reports the goal as met. The check it ran is real but does not test what the user wanted, so the result is a vacuous PASS. Distinct from `partial_corpus_search_declared_complete` (a real check of the right property on too small a population) and `qa_environment_bootstrap_avoidance` (no check run at all).

**Session signals**: Agent reports availability or presence ("the feed responds and holds 'ring' products", "the code looks correct", "PASS") where the user's goal was fitness for a purpose; the user runs a quick look at the real output and finds it off-target ("most images are not even rings"); the check the agent ran could not have failed for the reason the user cares about. Observed in 4 sessions (V02-008, V05-053, V05-064 and one more; see also V05-082).

### reviewer_primed_toward_verdict

**Description**: A review sub-agent brief carries the author's own framing of the work or the verdict the author expects, so the reviewer starts from the author's conclusion and confirms it instead of judging the output independently. The brief may state the author's reasoning, the alternatives the author rejected, a question shaped around the author's chosen answer, or the expected result ("confirm this is safe", "check that the fix is correct"). Distinct from `governance_rule_ignored` only in that the rule broken is the review-brief independence rule in `shared/AGENTS.md`, and from `fast_exit_exploitation` (no sanctioned skip gate is used). Subsumes the earlier candidate `author_question_anchored_review`.

**Session signals**: A review brief that includes the author's rationale, a "the fix is X, verify it" framing, or a yes/no question whose answer the author already holds; the reviewer returns agreement with no finding that the author did not already name; a later independent review or the user finds a defect the first review passed. Under-detected: the brief is agent-written and the review looks clean, so no correction-shaped text appears unless someone re-reviews. Observed in 2 sessions (V06-054, V05-052).

### orchestrator_answers_user_gate

**Description**: The orchestrator answers a question that belongs to the user: a question a sub-agent raised, or a workflow gate relayed to the orchestrator for the user's decision. The agent supplies the answer itself and carries on, so the user's decision is replaced by the agent's guess. Distinct from `sub_agent_bypass` (the orchestrator proceeds without a sub-agent's output after it failed): here the sub-agent's output arrived and contained a question or gate, and the failure is who answered it.

**Session signals**: A sub-agent return or relayed gate asks for a decision ("Retry / Skip / Abort?", "which option?", a clarifying question); the orchestrator's next turn answers it, or acts as if it had been answered, with no user turn in between; the user later says they were never asked, or reverses the choice. Evidence at proposal time: 4 sessions (V01-014; V05-066 with V05-035 and V05-036).

### inline_logic_copy_test

**Description**: Agent writes a test that copies the production branch logic into the test body and asserts on the copy, so the test stays green when the production guard is deleted. The test exercises its own reimplementation, not the shipped code. Distinct from `delivered_broken_code` (the shipped artifact fails) and `unisolated_fix_codified_as_rule` (a wrong causal claim recorded as a rule): here the code under test may be correct, but the test cannot detect its removal.

**Session signals**: A test body that re-declares the condition, branch or transform it claims to verify instead of importing and calling the production function; the user or a reviewer asks whether the test would fail if the guard were removed ("That's essentially the same inline copy problem though"); a replacement test written to fix the problem repeats the same shape. Observed three times in one feature (the plan's test, the coder's version, the orchestrator's replacement), so a corrected test is not evidence that the pattern is gone. Promoted from candidate accumulation at 2 sessions (2026-10-22).

### silent_rule_drives_in_head_build

**Description**: On kiro, a steering rule that says to work silently (no narration, no commentary between tool calls) is read as "do not emit anything", and the model builds the whole artifact (a document, script or file body) inside its reasoning instead of producing it with tools. The reasoning is not narration, so the rule is not violated; the artifact is never written to disk, or arrives late as one block with no intermediate tool use. Distinct from `governance_rule_ignored` (the rule is obeyed, and the obedience is the fault) and `delivered_broken_code` (nothing was delivered to break).

**Session signals**: A long reasoning block that contains the full text of the intended artifact; few or no write or edit tool uses for the length of the turn; the user asks where the output is or why nothing happened; the agent then writes the file from the reasoning text in one step. Observed in 2 sessions (70e80f04, fa3d3684; candidate V12-022).

## Output Routing

Archetype names MUST NOT contain colons. Use underscore_separated_lowercase for names.

When reporting findings in the Dream Sub-agent Return Schema:

- **Archetype matches** → `improvement_signals` array. Set `observation` field to: `ARCHETYPE:<name> — <description>` (first colon only is the delimiter; e.g., "ARCHETYPE:step_skipped_with_rationalization — agent skipped /qexplore Step 1.5 dispatch in 3 sessions").
- **Missed-intent plan clusters** → `improvement_signals` array. Set `target_file` to the skill most responsible (typically `shared/skills/qexplore/SKILL.md` or `shared/skills/qplan/SKILL.md`). Set `observation` to a description of the cluster. Use plan count (not session count) for `frequency` field.
- **Candidate archetypes** (patterns not matching existing archetypes) → `improvement_signals` array. Set `observation` to: `CANDIDATE_ARCHETYPE:<proposed_name> — <description>`.

**Format**: `<PREFIX>:<name> — <description>`. The ` — ` (space-em-dash-space) delimiter separates the archetype name from the description. The first colon separates the prefix keyword from the payload. Match prefixes by exact start-of-field comparison, longer prefix first.
