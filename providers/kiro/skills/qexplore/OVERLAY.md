## Kiro /qexplore Discipline

Kiro-specific enforcement overlay for `/qexplore`. Cites sections in `shared/skills/qexplore/SKILL.md` by name (per `shared/AGENTS.md § SKILL.md Authoring`), never by line or step number (desync guard).

### No scope-based bypass (Mandatory dispatch gate)

The mandatory dispatch gate applies regardless of perceived scope size, familiarity, or how much context the orchestrator believes it already has. "The change is small," "I already read the relevant files," and "this is just governance prose" are not valid reasons to skip dispatch. Only the greenfield classification and explicit user override can bypass this gate.

### Explicit-NA discipline (Pre-summary self-audit)

For each category in the pre-summary self-audit: when a category does not apply, explicitly mark it NA with reasoning. Do not silently skip categories — state your reasoning for resolution or non-applicability.

At the **minimal** exploration-depth level, a self-audit category resolved by model assumption is neither "confirmed/applies" nor "NA" — log it to the **Assumptions (unconfirmed)** ledger (per `shared/skills/qexplore/shared.md § Exploration depth`). Explicit-NA marking still applies to categories that genuinely do not apply; an assumed-but-applicable category belongs in the ledger, not marked NA.

### Interview discipline (one question, with a recommendation, after the full read)

Before the first interview question, read the complete `shared/skills/qexplore/SKILL.md` and `shared/skills/qexplore/shared.md` — not the step you think you need. Then ask **one question per turn**, and give every question a recommended answer with its rationale. Batching several questions into one turn is a rationalization, not a time-saver: the user has corrected all three of these in the same words across sessions ("you didn't read the full skill and associated content, do that now. 1 question per turn only"). Before sending any interview message, run this pre-send check: count the question marks and interrogative requests in the outgoing message. If there is more than one, delete everything after the first question and its recommendation, and keep the rest for later turns. The only allowed second item is a Probe-gate consent request (a yes/no on side effects), per `shared/skills/qexplore/shared.md`.

### Anti-shortcut framing

These disciplines exist because agents predictably rationalize skipping expensive-but-valuable steps. The dispatch gate prevents "I already know enough" shortcuts that miss constraints only fresh-context sub-agents would find. The explicit-NA discipline prevents silent omission of audit categories that would reveal gaps. Both are cheap to comply with and expensive to skip.

### Assumptions-checkpoint gate (always shown)

The end-of-interview assumptions checkpoint (under Pre-summary self-audit) is a hard gate, not a discretionary step: always present it and wait for the user before writing any summary or taking any persistence path — even when you assess your assumptions as low-risk. "I'm confident" is not grounds to skip it. A decision or assumption is settled only by a user answer to that specific item. The checkpoint never declares its own assumptions confirmed, and an unanswered or ignored item stays open (carry it as unconfirmed, re-ask it) rather than being treated as settled.
